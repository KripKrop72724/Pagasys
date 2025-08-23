from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db import transaction
from datetime import timedelta
from copy import deepcopy

from .utils import scope_queryset

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
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
)


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
    """Admin configuration for companies with comprehensive filters."""

    list_filter = ["name"]


@admin.register(Branch)
class BranchAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for branches with comprehensive filters."""
    form = BranchForm
    list_filter = ["company", "work_calendar", "name"]




@admin.register(Designation)
class DesignationAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for designations with comprehensive filters."""

    list_filter = ["company", "name", "level"]


@admin.register(TradeLicense)
class TradeLicenseAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    form = TradeLicenseForm
    filter_horizontal = ["branches"]
    list_filter = [
        "company",
        "branches",
        "license_no",
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

    class Meta(AdminUserCreationForm.Meta):
        model = Employee
        fields = AdminUserCreationForm.Meta.fields + (
            "work_calendar",
            "trade_license",
            "visa_type",
            "department",
            "project",
            "designation",
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
                    "department",
                    "project",
                    "work_calendar",
                    "designation",
                    "hire_date",
                    "employment_type",
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
                    "department",
                    "project",
                    "work_calendar",
                    "designation",
                    "hire_date",
                    "employment_type",
                )
            },
        ),
    )

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

    Example: to assign a week's shift starting on 2024‑07‑01 and rest on
    weekends, set ``repeat_days=7`` and pick ``Sat``/``Sun`` in *rest weekdays*.
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

    class Meta:
        model = RosterEntry
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("repeat_days") and cleaned.get("repeat_until"):
            raise forms.ValidationError("Provide either repeat_days or repeat_until")
        return cleaned


@admin.register(RosterEntry)
class RosterEntryAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for roster entries."""
    form = RosterEntryRangeForm
    list_display = ["employee", "date", "shift", "is_rest_day"]
    list_filter = ["employee", "shift", "is_rest_day"]
    search_fields = ["employee__username", "shift__name"]
    date_hierarchy = "date"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Ensure employee and shift dropdowns only show in-scope objects."""
        if db_field.name == "employee":
            kwargs["queryset"] = scope_queryset(Employee.objects.all(), request.user)
        elif db_field.name == "shift":
            kwargs["queryset"] = scope_queryset(ShiftTemplate.objects.all(), request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        repeat_days = form.cleaned_data.get("repeat_days")
        repeat_until = form.cleaned_data.get("repeat_until")
        name_to_idx = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        rest_weekdays = {name_to_idx[w] for w in (form.cleaned_data.get("rest_weekdays") or [])}

        if repeat_days or repeat_until:
            start = obj.date
            end = (
                start + timedelta(days=repeat_days - 1)
                if repeat_days
                else repeat_until
            )
            entries = []
            current = start
            while current <= end:
                entry = RosterEntry(
                    employee=obj.employee,
                    date=current,
                    shift=obj.shift,
                    override_start=obj.override_start,
                    override_end=obj.override_end,
                    is_rest_day=current.weekday() in rest_weekdays,
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
                    ],
                    unique_fields=["employee", "date"],
                )
        else:
            super().save_model(request, obj, form, change)


@admin.register(LeaveType)
class LeaveTypeAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for leave types."""

    list_display = ["code", "name", "company", "paid_pct"]
    list_filter = ["company", "paid_pct"]
    search_fields = ["code", "name", "company__name"]
