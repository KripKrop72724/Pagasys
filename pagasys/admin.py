from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
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
)
from .models_attendance import LeaveType


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
        }
        if related_model in target_models:
            qs = scope_queryset(related_model.objects.all(), request.user)
            kwargs["queryset"] = qs
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Restrict M2M dropdowns to objects within the user's scope."""
        related_model = db_field.remote_field.model
        target_models = {Branch, Employee}
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
        cleaned = super().clean()
        self.instance._branches_for_validation = cleaned.get("branches")
        return cleaned


@admin.register(Company)
class CompanyAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for companies with comprehensive filters."""

    list_filter = ["name"]




@admin.register(Branch)
class BranchAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for branches with comprehensive filters."""

    list_filter = ["company", "name"]




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
        obj._branches_for_validation = form.cleaned_data.get("branches")
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


@admin.register(Employee)
class EmployeeAdmin(CleanSaveModelMixin, ScopedAdminMixin, UserAdmin):
    """Admin configuration for Employee model with password reset."""

    add_form = AdminUserCreationForm
    form = UserChangeForm
    model = Employee

    list_filter = UserAdmin.list_filter + (
        "visa_type",
        "employment_type",
        "trade_license",
        "department",
        "project",
        "designation",
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


@admin.register(LeaveType)
class LeaveTypeAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    """Admin configuration for leave types with comprehensive filters."""

    list_display = [
        "name",
        "code",
        "company",
        "pay_percent",
        "requires_doc",
        "max_days_per_year",
    ]
    list_filter = ["company", "requires_doc"]
