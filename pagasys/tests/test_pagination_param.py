from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, TradeLicense


class PageSizeQueryParamTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        User = get_user_model()
        self.company = Company.objects.create(name="Acme")
        branch = Branch.objects.create(company=self.company, name="B1")
        dept = Department.objects.create(branch=branch, name="D1")
        license = TradeLicense.objects.create(
            company=self.company,
            license_no="LIC1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        license.branches.set([branch])
        self.user = User.objects.create_user(
            username="api",
            password="pass",
            is_staff=True,
            is_superuser=True,
            trade_license=license,
            department=dept,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_authenticate(self.user)

    def test_page_size_limits_results(self):
        Company.objects.create(name="Other1")
        Company.objects.create(name="Other2")
        res = self.client.get("/api/companies/?page_size=1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertIn("next", res.data)

    def test_page_size_above_max_capped(self):
        for i in range(6):
            Company.objects.create(name=f"C{i}")
        rf = {**settings.REST_FRAMEWORK, "MAX_PAGE_SIZE": 5}
        with override_settings(REST_FRAMEWORK=rf):
            res = self.client.get("/api/companies/?page_size=10")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 5)

    def test_invalid_page_size_falls_back_to_default(self):
        for i in range(3):
            Company.objects.create(name=f"Bad{i}")
        rf = {**settings.REST_FRAMEWORK, "PAGE_SIZE": 1}
        with override_settings(REST_FRAMEWORK=rf):
            res = self.client.get("/api/companies/?page_size=0")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
