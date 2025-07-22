from django.contrib import admin

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
admin.site.register(Employee)

