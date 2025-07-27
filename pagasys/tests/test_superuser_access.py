from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from pagasys.models import Company, Branch, Department, TradeLicense


class SuperUserAccessTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.client = APIClient()

        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch])

        self.user = User.objects.create_superuser(
            username="su",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

    def test_superuser_can_access_api_without_groups(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/companies/")
        self.assertEqual(res.status_code, 200)

    def test_superuser_can_access_admin_without_groups(self):
        self.client.force_login(self.user)
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 200)
