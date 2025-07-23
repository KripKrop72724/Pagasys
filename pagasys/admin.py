from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
)

admin.site.register(Company)
admin.site.register(Branch)
admin.site.register(Designation)
admin.site.register(TradeLicense)
admin.site.register(Department)
admin.site.register(Project)


@admin.register(Employee)
class EmployeeAdmin(UserAdmin):
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


