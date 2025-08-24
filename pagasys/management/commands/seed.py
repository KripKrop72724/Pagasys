from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.utils import timezone
from zoneinfo import ZoneInfo

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
    "Company Admin": [Company, Designation],
    "Branch Manager": [Branch, TradeLicense],
    "Payroll Manager": [Employee],
    "Department Manager": [Department],
    "Project Manager": [Project],
    "Employee": [],
}


class Command(BaseCommand):
    help = "Seed default groups and populate sample data"

    def handle(self, *args, **options):
        self._create_groups()
        with transaction.atomic():
            self._create_demo_data()
        self.stdout.write(self.style.SUCCESS("Seed complete"))

    def _create_groups(self):
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

    def _create_demo_data(self):
        """Create companies and related objects with a few records each."""
        # Companies
        acme, _ = Company.objects.get_or_create(name="Acme Corp", defaults={"timezone": "Asia/Dubai"})
        beta, _ = Company.objects.get_or_create(name="Beta LLC", defaults={"timezone": "Asia/Kolkata"})

        with timezone.override(ZoneInfo(acme.timezone)):
            acme_b1, _ = Branch.objects.get_or_create(company=acme, name="Acme Dubai")
            acme_b2, _ = Branch.objects.get_or_create(company=acme, name="Acme Abu Dhabi")
            acme_d1, _ = Department.objects.get_or_create(branch=acme_b1, name="HR")
            acme_d2, _ = Department.objects.get_or_create(branch=acme_b2, name="Engineering")
            acme_p1, _ = Project.objects.get_or_create(
                branch=acme_b1, name="Project X", start_date="2024-01-01"
            )
            acme_des, _ = Designation.objects.get_or_create(company=acme, name="Engineer")
            acme_lic, _ = TradeLicense.objects.get_or_create(
                company=acme,
                license_no="LIC-ACME",
                defaults={
                    "issued_date": "2024-01-01",
                    "expiry_date": "2025-01-01",
                    "max_visas": 10,
                },
            )
            acme_lic.branches.set([acme_b1, acme_b2])
            admin, created = Employee.objects.get_or_create(
                username="admin",
                defaults={
                    "email": "fytfytfyt420@gmail.com",
                    "is_staff": True,
                    "is_superuser": True,
                    "trade_license": acme_lic,
                    "department": acme_d1,
                    "first_name": "Admin",
                    "last_name": "User",
                    "hire_date": "2024-01-01",
                    "employment_type": "permanent",
                },
            )
            if created:
                admin.set_password("admin")
                admin.save()
            Employee.objects.get_or_create(
                username="acme_emp",
                defaults={
                    "password": "pass",
                    "trade_license": acme_lic,
                    "department": acme_d2,
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "hire_date": "2024-02-01",
                    "employment_type": "permanent",
                    "designation": acme_des,
                },
            )

        with timezone.override(ZoneInfo(beta.timezone)):
            beta_b1, _ = Branch.objects.get_or_create(company=beta, name="Beta Dubai")
            beta_b2, _ = Branch.objects.get_or_create(company=beta, name="Beta Sharjah")
            beta_d1, _ = Department.objects.get_or_create(branch=beta_b1, name="HR")
            beta_d2, _ = Department.objects.get_or_create(branch=beta_b2, name="Engineering")
            beta_p1, _ = Project.objects.get_or_create(
                branch=beta_b1, name="Project Y", start_date="2024-01-01"
            )
            beta_des, _ = Designation.objects.get_or_create(company=beta, name="Analyst")
            beta_lic, _ = TradeLicense.objects.get_or_create(
                company=beta,
                license_no="LIC-BETA",
                defaults={
                    "issued_date": "2024-01-01",
                    "expiry_date": "2025-01-01",
                    "max_visas": 10,
                },
            )
            beta_lic.branches.set([beta_b1, beta_b2])
            Employee.objects.get_or_create(
                username="beta_emp",
                defaults={
                    "password": "pass",
                    "trade_license": beta_lic,
                    "project": beta_p1,
                    "first_name": "Bob",
                    "last_name": "Jones",
                    "hire_date": "2024-03-01",
                    "employment_type": "permanent",
                    "designation": beta_des,
                },
            )

