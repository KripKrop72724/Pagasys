from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError

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


class ScopedAdminMixin:
    """Limit admin querysets based on the logged-in user."""

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return scope_queryset(qs, request.user)

    def _has_perm(self, request, action):
        """Check the user's model permission for the given action."""
        return request.user.has_perm(f"{self.opts.app_label}.{action}_{self.opts.model_name}")

    def has_add_permission(self, request):
        return self._has_perm(request, "add")

    def has_change_permission(self, request, obj=None):
        if not self._has_perm(request, "change"):
            return False
        if obj is None:
            return True
        qs = scope_queryset(self.model.objects.filter(pk=obj.pk), request.user)
        return qs.exists()

    def has_view_permission(self, request, obj=None):
        """Restrict view access to objects within the user's scope."""
        if not (
            self._has_perm(request, "view") or self._has_perm(request, "change")
        ):
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

@admin.register(Company)
class CompanyAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Branch)
class BranchAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Designation)
class DesignationAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(TradeLicense)
class TradeLicenseAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Department)
class DepartmentAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Project)
class ProjectAdmin(CleanSaveModelMixin, ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Employee)
class EmployeeAdmin(CleanSaveModelMixin, ScopedAdminMixin, UserAdmin):
    """Admin configuration for Employee model with password reset."""

    add_form = AdminUserCreationForm
    form = UserChangeForm
    model = Employee

    fieldsets = UserAdmin.fieldsets + (
        (
            "Employment Info",
            {
                "fields": (
                    "trade_license",
                    "department",
                    "project",
                    "designation",
                    "hire_date",
                    "employment_type",
                )
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Employment Info",
            {
                "fields": (
                    "trade_license",
                    "department",
                    "project",
                    "designation",
                    "hire_date",
                    "employment_type",
                )
            },
        ),
    )


