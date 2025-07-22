from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from pagasys.models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
)


ROLE_PERMS = {
    "Super Admin": "all",
    "Company Admin": [Company, Designation],
    "Branch Manager": [Branch, TradeLicense],
    "Payroll Manager": [Employee],
    "Department Manager": [Department],
    "Project Manager": [Project],
    "Employee": [],
}


class Command(BaseCommand):
    help = "Seed default groups and demo data"

    def handle(self, *args, **options):
        for role, models_list in ROLE_PERMS.items():
            group, _ = Group.objects.get_or_create(name=role)
            if models_list == "all":
                perms = Permission.objects.all()
            else:
                perms = Permission.objects.filter(
                    content_type__model__in=[m._meta.model_name for m in models_list]
                )
            group.permissions.set(perms)
            self.stdout.write(f"Synced permissions for {role}")

        self.stdout.write(self.style.SUCCESS("Seed complete"))

