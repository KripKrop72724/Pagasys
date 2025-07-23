from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

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

@admin.register(Company)
class CompanyAdmin(ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Branch)
class BranchAdmin(ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Designation)
class DesignationAdmin(ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(TradeLicense)
class TradeLicenseAdmin(ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Department)
class DepartmentAdmin(ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Project)
class ProjectAdmin(ScopedAdminMixin, admin.ModelAdmin):
    pass


@admin.register(Employee)
class EmployeeAdmin(ScopedAdminMixin, UserAdmin):
    """Admin configuration for Employee model with password reset."""

    add_form = UserCreationForm
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


