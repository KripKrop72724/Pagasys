from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from pagasys.models import Company, Branch, Department, TradeLicense, Employee


class AdminScopeTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.company = Company.objects.create(name="C")
        other = Company.objects.create(name="Other")
        branch = Branch.objects.create(company=self.company, name="B1")
        other_branch = Branch.objects.create(company=other, name="OB1")
        department = Department.objects.create(branch=branch, name="D1")
        other_department = Department.objects.create(branch=other_branch, name="OD1")
        license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        license.branches.set([branch])
        other_license = TradeLicense.objects.create(
            company=other,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        other_license.branches.set([other_branch])

        Group.objects.filter(name="Company Admin").exists() or call_command("initgroups", verbosity=0)
        ca_group = Group.objects.get(name="Company Admin")

        self.admin_user = User.objects.create_user(
            username="ca",
            password="pass",
            is_staff=True,
            trade_license=license,
            department=department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.admin_user.groups.add(ca_group)

        self.other_emp = User.objects.create_user(
            username="otheremp",
            password="pass",
            trade_license=other_license,
            department=other_department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

    def test_admin_queryset_scoped(self):
        self.client.force_login(self.admin_user)
        res = self.client.get("/admin/pagasys/employee/")
        self.assertContains(res, self.admin_user.username)
        self.assertNotContains(res, self.other_emp.username)

