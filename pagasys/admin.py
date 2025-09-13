from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db import connection, transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.db.models import Max
from datetime import timedelta, date
from copy import deepcopy
from django.forms.models import construct_instance

from .excel_import import import_employee_workbook, import_company_visa_workbook

from .utils import scope_queryset
from .tasks import schedule_range_bulk

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    HolidayAuditLog,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
    holiday_flags,
)

ASYNC_BULK_THRESHOLD = 50


class ScopedAdminMixin:
    """Limit admin querysets based on the logged-in user."""

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return scope_queryset(qs, request.user)

    def _has_perm(self, request, action):
        """Check the user's model permission for the given action."""
        return request.user.has_perm(
            f"{self.opts.app_label}.{action}_{self.opts.model_name}"
        )

    def has_add_permission(self, request):
        return self._has_perm(request, "add")

    def has_change_permission(self, request, obj=None):
        if not self._has_perm(request, "change"):
            return False
        if obj is None:
            return True
        qs = scope_queryset(self.model.objects.filter(pk=obj.pk), request.user)
        return qs.exists()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Restrict FK dropdowns to objects within the user's scope."""
        related_model = db_field.remote_field.model
        target_models = {
            Company,
            Branch,
            Designation,
            TradeLicense,
            Department,
            Project,
            Employee,
            WorkCalendar,
            ShiftTemplate,
            RosterEntry,
            LeaveType,
        }
        if related_model in target_models:
            qs = scope_queryset(related_model.objects.all(), request.user)
            kwargs["queryset"] = qs
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Restrict M2M dropdowns to objects within the user's scope."""
        related_model = db_field.remote_field.model
        target_models = {Branch, Employee, ShiftTemplate, WorkCalendar}
        if related_model in target_models:
            qs = scope_queryset(related_model.objects.all(), request.user)
            kwargs["queryset"] = qs
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def has_view_permission(self, request, obj=None):
        """Restrict view access to objects within the user's scope."""
        if not (self._has_perm(request, "view") or self._has_perm(request, "change")):
            return False
        if obj is None:
            return True
        qs = scope_queryset(self.model.objects.filter(pk=obj.pk), request.user)
        return qs.exists()

    def has_delete_permission(self, request, obj=None):
        if not self._has_perm(request, "delete"):
            return False
        if obj is None:
            return True
        qs = scope_queryset(self.model.objects.filter(pk=obj.pk), request.user)
        return qs.exists()


class ScopedInlineMixin:
    """Mixin for inlines to apply the same queryset scoping."""

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return scope_queryset(qs, request.user)


class CleanSaveModelMixin:
    """Ensure model.clean() is triggered when saving through the admin."""

    def save_model(self, request, obj, form, change):
        try:
            if form is not None and hasattr(form, "cleaned_data") and "branches" in form.cleaned_data:
                obj._branches_cache = form.cleaned_data["branches"]
            obj.full_clean()
        except ValidationError as exc:
            if form is not None:
                form.add_error(None, exc)
            raise
        super().save_model(request, obj, form, change)


class BranchSelectMultiple(FilteredSelectMultiple):
    """Select box that annotates options with the branch company."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        try:
            option["attrs"]["data-company"] = str(value.instance.company_id)
        except Exception:
            pass
        return option



class TradeLicenseForm(forms.ModelForm):
    """Form for :class:`TradeLicense` with dynamic branch queryset.

    Branches are optional; leaving the field empty creates a company-wide
    license. Issued and expiry dates are also optional.
    """

    class Meta:
        model = TradeLicense
        fields = "__all__"
        widgets = {"branches": BranchSelectMultiple("branches", False)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_id = (
            self.data.get("company")
            or self.initial.get("company")
            or getattr(self.instance, "company_id", None)
        )
        if company_id:
            self.fields["branches"].queryset = Branch.objects.filter(company_id=company_id)

    def clean(self):
        return super().clean()


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_id = (
            self.data.get("company")
            or self.initial.get("company")
            or getattr(self.instance, "company_id", None)
        )
        if company_id:
            self.fields["work_calendar"].queryset = WorkCalendar.objects.filter(
                company_id=company_id
            )


@admin.register(Company)
class CompanyAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for companies with comprehensive filters.

    Includes address, logo, email, phone, website and bank account number
    fields to capture detailed contact and payroll information.
    """

    list_filter = ["name"]
    fieldsets = (
        (None, {"fields": ("name", "timezone")}),
        (
            "Contact details",
            {
                "fields": ("address", "logo", "email", "phone", "website"),
                "description": "Optional fields describing how to reach the company.",
            },
        ),
        (
            "Financial details",
            {
                "fields": ("bank_account_number",),
                "description": "Bank account number used for payroll disbursements.",
            },
        ),
    )


@admin.register(Branch)
class BranchAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for branches with comprehensive filters."""
    form = BranchForm
    list_filter = ["company", "work_calendar", "name"]
    fieldsets = (
        (
            None,
            {
                "fields": ("company", "name", "address", "work_calendar"),
                "description": "Branch details including address and calendar.",
            },
        ),
    )




@admin.register(Designation)
class DesignationAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for designations with comprehensive filters."""

    list_filter = ["company", "name", "level"]


@admin.register(TradeLicense)
class TradeLicenseAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for trade licenses with comprehensive filters.

    Branch assignments, issued date and expiry date are optional. When
    branches are selected the license becomes branch‑scoped; otherwise it
    can be applied to any employee of the company.
    """

    form = TradeLicenseForm
    filter_horizontal = ["branches"]
    list_filter = [
        "company",
        "branches",
        "name",
        "license_no",
        "establishment_card_number",
        "issued_date",
        "expiry_date",
        "max_visas",
    ]

    class Media:
        js = ["pagasys/js/tradelicense_admin.js"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "branches":
            kwargs["widget"] = BranchSelectMultiple(db_field.verbose_name, False)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Department)
class DepartmentAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for departments with comprehensive filters."""

    list_filter = ["branch", "name"]


@admin.register(Project)
class ProjectAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for projects with comprehensive filters."""

    list_filter = ["branch", "name", "start_date", "end_date"]


class EmployeeAdminForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Employee
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "work_calendar" in self.fields:
            company_id = self._derive_company()
            if company_id:
                self.fields["work_calendar"].queryset = WorkCalendar.objects.filter(
                    company_id=company_id
                )
            else:
                self.fields["work_calendar"].queryset = WorkCalendar.objects.none()

    def _derive_company(self):
        data = self.data or self.initial
        if data.get("trade_license"):
            return TradeLicense.objects.filter(pk=data["trade_license"]).values_list("company_id", flat=True).first()
        if data.get("department"):
            return Department.objects.filter(pk=data["department"]).values_list("branch__company_id", flat=True).first()
        if data.get("project"):
            return Project.objects.filter(pk=data["project"]).values_list("branch__company_id", flat=True).first()
        inst = getattr(self, "instance", None)
        if inst:
            if inst.trade_license_id:
                return inst.trade_license.company_id
            if inst.department_id:
                return inst.department.branch.company_id
            if inst.project_id:
                return inst.project.branch.company_id
        return None


class EmployeeAdminCreationForm(AdminUserCreationForm):
    work_calendar = forms.ModelChoiceField(
        queryset=WorkCalendar.objects.none(), required=False
    )
    # ``payment_status`` has a model default ("cash") but the Django admin
    # form generated from the model treats it as a required field because the
    # model field has ``blank=False``.  The admin tests create employees
    # without explicitly specifying a payment status and expect the default
    # to be applied.  Mark the field as optional here so that the form can be
    # submitted without providing a value and the model default will be used.
    payment_status = forms.ChoiceField(
        choices=Employee.PAYMENT_STATUS_CHOICES,
        required=False,
    )

    class Meta(AdminUserCreationForm.Meta):
        model = Employee
        fields = AdminUserCreationForm.Meta.fields + (
            "first_name",
            "middle_name",
            "last_name",
            "email",
            "work_calendar",
            "trade_license",
            "visa_type",
            "payment_status",
            "wps_account_number",
            "department",
            "project",
            "designation",
            "primary_contact",
            "secondary_contact",
            "nationality",
            "current_address",
            "permanent_address",
            "hometown",
            "profile_picture",
            "gender",
            "visa_file_number",
            "wps_id",
            "c3_id",
            "special_notes",
            "hire_date",
            "employment_type",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_id = self._derive_company()
        if company_id:
            self.fields["work_calendar"].queryset = WorkCalendar.objects.filter(
                company_id=company_id
            )

    def _derive_company(self):
        data = self.data
        if data.get("trade_license"):
            return TradeLicense.objects.filter(pk=data["trade_license"]).values_list("company_id", flat=True).first()
        if data.get("department"):
            return Department.objects.filter(pk=data["department"]).values_list("branch__company_id", flat=True).first()
        if data.get("project"):
            return Project.objects.filter(pk=data["project"]).values_list("branch__company_id", flat=True).first()
        return None


@admin.register(Employee)
class EmployeeAdmin(CleanSaveModelMixin, ScopedAdminMixin, UserAdmin):
    """Admin configuration for Employee model with password reset."""

    add_form = EmployeeAdminCreationForm
    form = EmployeeAdminForm
    model = Employee
    change_list_template = "admin/pagasys/employee/change_list.html"

    class VisaUploadForm(forms.Form):
        file = forms.FileField()

    list_filter = UserAdmin.list_filter + (
        "visa_type",
        "employment_type",
        "trade_license",
        "department",
        "project",
        "designation",
        "work_calendar",
    )

    base_fieldsets = list(UserAdmin.fieldsets)
    personal = list(base_fieldsets[1][1]["fields"])
    personal.insert(1, "middle_name")
    base_fieldsets[1][1]["fields"] = tuple(personal)
    perms = list(base_fieldsets[2][1]["fields"])
    if "user_permissions" in perms:
        perms.remove("user_permissions")
    base_fieldsets[2][1]["fields"] = tuple(perms)

    fieldsets = tuple(base_fieldsets) + (
        (
            "Employment Info",
            {
                "fields": (
                    "trade_license",
                    "visa_type",
                    "payment_status",
                    "wps_account_number",
                    "department",
                    "project",
                    "work_calendar",
                    "designation",
                    "visa_file_number",
                    "wps_id",
                    "c3_id",
                    "hire_date",
                    "employment_type",
                )
            },
        ),
        (
            "Personal Info",
            {
                "fields": (
                    "primary_contact",
                    "secondary_contact",
                    "nationality",
                    "current_address",
                    "permanent_address",
                    "hometown",
                    "profile_picture",
                    "gender",
                    "special_notes",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "password1",
                    "password2",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "email",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                ),
            },
        ),
        (
            "Employment Info",
            {
                "fields": (
                    "trade_license",
                    "visa_type",
                    "payment_status",
                    "wps_account_number",
                    "department",
                    "project",
                    "work_calendar",
                    "designation",
                    "visa_file_number",
                    "wps_id",
                    "c3_id",
                    "hire_date",
                    "employment_type",
                )
            },
        ),
        (
            "Personal Info",
            {
                "fields": (
                    "primary_contact",
                    "secondary_contact",
                    "nationality",
                    "current_address",
                    "permanent_address",
                    "hometown",
                    "profile_picture",
                    "gender",
                    "special_notes",
                )
            },
        ),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "own-visa-upload/",
                self.admin_site.admin_view(self.own_visa_upload),
                name="pagasys_employee_own_visa_upload",
            ),
            path(
                "company-visa-upload/",
                self.admin_site.admin_view(self.company_visa_upload),
                name="pagasys_employee_company_visa_upload",
            ),
            path(
                "reset-id-sequence/",
                self.admin_site.admin_view(self.reset_id_sequence),
                name="pagasys_employee_reset_id_sequence",
            ),
        ]
        return custom + urls

    def own_visa_upload(self, request):
        if request.method == "POST":
            form = self.VisaUploadForm(request.POST, request.FILES)
            if form.is_valid():
                results = import_employee_workbook(form.cleaned_data["file"])
                if results["created"]:
                    messages.success(
                        request, f"Created {results['created']} employees."
                    )
                for err in results["errors"]:
                    messages.error(request, err)
                return redirect("..")
        else:
            form = self.VisaUploadForm()
        context = dict(
            self.admin_site.each_context(request),
            title="Own Visa Upload",
            form=form,
            opts=self.model._meta,
        )
        return TemplateResponse(
            request, "admin/pagasys/employee/own_visa_upload.html", context
        )

    def company_visa_upload(self, request):
        if request.method == "POST":
            form = self.VisaUploadForm(request.POST, request.FILES)
            if form.is_valid():
                results = import_company_visa_workbook(form.cleaned_data["file"])
                if results["created"]:
                    messages.success(
                        request, f"Created {results['created']} employees."
                    )
                for err in results["errors"]:
                    messages.error(request, err)
                return redirect("..")
        else:
            form = self.VisaUploadForm()
        context = dict(
            self.admin_site.each_context(request),
            title="Company Visa Upload",
            form=form,
            opts=self.model._meta,
        )
        return TemplateResponse(
            request, "admin/pagasys/employee/company_visa_upload.html", context
        )

    def reset_id_sequence(self, request):
        max_id = self.model.objects.aggregate(max_id=Max("id"))["max_id"] or 0
        table_name = self.model._meta.db_table
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)",
                    [table_name, max_id],
                )
            elif connection.vendor == "sqlite":
                cursor.execute(
                    "UPDATE sqlite_sequence SET seq = %s WHERE name = %s",
                    [max_id, table_name],
                )
        messages.success(request, "Employee ID sequence reset.")
        return redirect("..")

    class Media:
        js = ["pagasys/js/employee_admin.js"]

    def get_fieldsets(self, request, obj=None):
        fieldsets = deepcopy(super().get_fieldsets(request, obj))
        if not request.user.is_superuser:
            for name, opts in fieldsets:
                fields = list(opts.get("fields", ()))
                if "is_superuser" in fields:
                    fields.remove("is_superuser")
                opts["fields"] = tuple(fields)
        if (obj and obj.is_superuser) or request.POST.get("is_superuser"):
            for name, opts in fieldsets:
                fields = list(opts.get("fields", ()))
                if "groups" in fields:
                    fields.remove("groups")
                    opts["fields"] = tuple(fields)
        return fieldsets

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.is_superuser:
            obj.groups.clear()


@admin.register(WorkCalendar)
class WorkCalendarAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for work calendars."""

    list_display = ["name", "company", "is_default"]
    list_filter = ["company", "is_default"]
    search_fields = ["name", "company__name"]


@admin.register(Holiday)
class HolidayAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for holidays."""

    list_display = ["name", "date", "calendar", "is_public"]
    list_filter = ["calendar", "is_public"]
    search_fields = ["name"]
    date_hierarchy = "date"


@admin.register(HolidayAuditLog)
class HolidayAuditLogAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Read-only audit trail of holiday changes."""

    list_display = [
        "calendar",
        "name",
        "old_date",
        "new_date",
        "action",
        "timestamp",
    ]
    list_filter = ["calendar", "action"]
    search_fields = ["name"]
    readonly_fields = ["calendar", "name", "old_date", "new_date", "action", "timestamp"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for shift templates."""

    list_display = ["name", "company", "start_time", "end_time", "cross_midnight"]
    list_filter = ["company", "cross_midnight"]
    search_fields = ["name", "company__name"]


@admin.register(ShiftRule)
class ShiftRuleAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for shift rules."""

    list_display = ["kind", "shift", "value", "active_from", "active_to"]
    list_filter = ["shift", "kind"]
    search_fields = ["kind", "shift__name"]


class RosterEntryRangeForm(forms.ModelForm):
    """Admin form mirroring the ``schedule-range`` API action.

    Select a branch to schedule all of its employees. Example: to assign a
    week's shift starting on 2024‑07‑01 and rest on weekends, set
    ``repeat_days=7`` and pick ``Sat``/``Sun`` in *rest weekdays*.
    """

    repeat_days = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="Number of consecutive days to create (e.g. 7 for a week)",
    )
    repeat_until = forms.DateField(
        required=False,
        help_text="Create entries up to and including this date (e.g. 2024-07-31)",
    )
    rest_weekdays = forms.MultipleChoiceField(
        required=False,
        choices=[
            ("mon", "Mon"),
            ("tue", "Tue"),
            ("wed", "Wed"),
            ("thu", "Thu"),
            ("fri", "Fri"),
            ("sat", "Sat"),
            ("sun", "Sun"),
        ],
        help_text="Weekdays to mark as rest days (e.g. select Sat/Sun for weekends)",
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.all(),
        required=True,
        help_text="Branch whose employees will be scheduled",
    )

    employee = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Employees to schedule within the branch",
    )

    class Meta:
        model = RosterEntry
        exclude = ("employee",)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("repeat_days") and cleaned.get("repeat_until"):
            raise forms.ValidationError("Provide either repeat_days or repeat_until")
        return cleaned

    def _post_clean(self):
        """Skip model.full_clean(); validation handled per employee during save."""
        opts = self._meta
        construct_instance(self, self.instance, opts.fields, opts.exclude)

@admin.register(RosterEntry)
class RosterEntryAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for roster entries."""
    list_display = [
        "employee",
        "date",
        "shift",
        "is_rest_day",
        "is_holiday",
        "was_holiday",
    ]
    list_filter = [
        "employee__department__branch",
        "employee",
        "shift",
        "is_rest_day",
        "is_holiday",
        "was_holiday",
    ]
    search_fields = ["employee__username", "shift__name"]
    date_hierarchy = "date"
    change_list_template = "admin/pagasys/rosterentry/change_list.html"
    readonly_fields = ["was_holiday"]
    autocomplete_fields = ["employee"]

    class Media:
        js = (
            "grappelli/js/jquery.grp_autocomplete_generic.js",
            "grappelli/js/jquery.grp_autocomplete_m2m.js",
        )

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if obj is None:
            fields = [f for f in fields if f != "employee"]
        return fields

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "overview/",
                self.admin_site.admin_view(self.overview),
                name="pagasys_rosterentry_overview",
            ),
        ]
        return custom + urls

    def overview(self, request):
        from datetime import date
        from django.template.response import TemplateResponse
        from django.utils import timezone

        try:
            start = date.fromisoformat(request.GET.get("start"))
        except Exception:
            start = timezone.localdate()
        raw_days = request.GET.get("days", "7")
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            days = 7
        if days < 1:
            days = 7
        days = min(days, 31)

        end = start + timedelta(days=days - 1)
        qs = (
            RosterEntry.objects.filter(date__range=(start, end))
            .select_related("employee", "shift")
            .order_by("employee__username")
        )
        date_list = [start + timedelta(days=i) for i in range(days)]
        grouped = {}
        for entry in qs:
            grouped.setdefault(entry.employee, {})[entry.date] = entry
        rows = [
            (emp, [day_map.get(d) for d in date_list])
            for emp, day_map in grouped.items()
        ]
        context = dict(
            self.admin_site.each_context(request),
            title="Roster overview",
            rows=rows,
            date_list=date_list,
            opts=self.model._meta,
            start=start,
            days=days,
        )
        return TemplateResponse(
            request, "admin/pagasys/rosterentry/overview.html", context
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Ensure shift dropdown only shows in-scope objects."""
        if db_field.name == "shift":
            kwargs["queryset"] = scope_queryset(
                ShiftTemplate.objects.all(), request.user
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = RosterEntryRangeForm
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            form.base_fields["branch"].queryset = scope_queryset(
                Branch.objects.all(), request.user
            )
            branch_id = request.POST.get("branch") or request.GET.get("branch")
            if branch_id:
                form.base_fields["employee"].queryset = scope_queryset(
                    Employee.objects.filter(department__branch_id=branch_id),
                    request.user,
                )
            else:
                form.base_fields["employee"].queryset = Employee.objects.none()
        return form

    def add_view(self, request, form_url="", extra_context=None):
        if request.method == "POST" and "employee" not in request.POST:
            form = RosterEntryRangeForm(request.POST)
            if form.is_valid():
                params = request.POST.copy()
                params.pop("csrfmiddlewaretoken", None)
                params["stage2"] = "1"
                return redirect(f"{request.path}?{params.urlencode()}")
        return super().add_view(request, form_url, extra_context)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        if request.GET.get("stage2"):
            for field in [
                "branch",
                "date",
                "shift",
                "repeat_days",
                "repeat_until",
            ]:
                if field in request.GET:
                    initial[field] = request.GET[field]
            if "rest_weekdays" in request.GET:
                initial["rest_weekdays"] = request.GET.getlist("rest_weekdays")
        return initial

    def save_model(self, request, obj, form, change):
        repeat_days = form.cleaned_data.get("repeat_days")
        repeat_until = form.cleaned_data.get("repeat_until")
        rest_weekday_names = form.cleaned_data.get("rest_weekdays")
        branch = form.cleaned_data.get("branch")

        if repeat_days is None and form.data.get("repeat_days"):
            try:
                repeat_days = int(form.data.get("repeat_days"))
            except (TypeError, ValueError):
                repeat_days = None
        if repeat_until is None and form.data.get("repeat_until"):
            try:
                repeat_until = date.fromisoformat(form.data.get("repeat_until"))
            except (TypeError, ValueError):
                repeat_until = None
        if rest_weekday_names is None and form.data.getlist("rest_weekdays"):
            rest_weekday_names = form.data.getlist("rest_weekdays")

        if change:
            if repeat_days or repeat_until or rest_weekday_names:
                employees = [obj.employee]
            else:
                super().save_model(request, obj, form, change)
                return
        else:
            selected = form.cleaned_data.get("employee")
            if selected:
                employees = list(selected)
            else:
                employees = list(
                    scope_queryset(
                        Employee.objects.filter(department__branch=branch),
                        request.user,
                    )
                )
            if not employees:
                return
            obj.employee = employees[0]
        name_to_idx = {
            "mon": 0,
            "tue": 1,
            "wed": 2,
            "thu": 3,
            "fri": 4,
            "sat": 5,
            "sun": 6,
        }
        rest_weekdays = {name_to_idx[w] for w in (rest_weekday_names or [])}
        override = obj.is_holiday if "is_holiday" in form.changed_data else None

        start = obj.date
        end = (
            start + timedelta(days=repeat_days - 1)
            if repeat_days
            else repeat_until
            if repeat_until
            else start
        )
        if len(employees) > ASYNC_BULK_THRESHOLD:
            codes = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            task = schedule_range_bulk.delay(
                [e.id for e in employees],
                obj.shift_id,
                start.isoformat(),
                end.isoformat(),
                [codes[i] for i in rest_weekdays],
            )
            messages.info(request, f"Roster scheduling queued (task {task.id})")
            return

        entries = []
        for emp in employees:
            current = start
            while current <= end:
                entry = RosterEntry(
                    employee=emp,
                    date=current,
                    shift=obj.shift,
                    override_start=obj.override_start,
                    override_end=obj.override_end,
                    is_rest_day=current.weekday() in rest_weekdays,
                )
                entry.is_holiday, entry.was_holiday = holiday_flags(
                    entry.employee, current, override
                )
                entry.full_clean(validate_unique=False)
                entries.append(entry)
                current += timedelta(days=1)
        with transaction.atomic():
            RosterEntry.objects.bulk_create(
                entries,
                update_conflicts=True,
                update_fields=[
                    "shift",
                    "override_start",
                    "override_end",
                    "is_rest_day",
                    "is_holiday",
                    "was_holiday",
                ],
                unique_fields=["employee", "date"],
            )


@admin.register(LeaveType)
class LeaveTypeAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for leave types."""

    list_display = ["code", "name", "company", "paid_pct"]
    list_filter = ["company", "paid_pct"]
    search_fields = ["code", "name", "company__name"]
