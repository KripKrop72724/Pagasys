from django.test import TestCase


class TradeLicenseNameAPITests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        from pagasys.models import Company, Branch, Department, TradeLicense

        self.client = APIClient()
        User = get_user_model()
        self.company = Company.objects.create(name="Co")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        license.branches.set([self.branch])
        self.user = User.objects.create_user(
            username="api", password="pass", is_staff=True, is_superuser=True,
            trade_license=license, department=self.department,
            hire_date="2024-01-01", employment_type="permanent", visa_type="company",
        )
        self.client.force_authenticate(self.user)

    def _base(self):
        return {
            "company": self.company.id,
            "license_no": "L2",
            "issued_date": "2024-01-01",
            "expiry_date": "2099-01-01",
            "max_visas": 1,
            "branches": [self.branch.id],
        }

    def test_create_with_name(self):
        from pagasys.models import TradeLicense

        payload = self._base()
        payload["name"] = "License A"
        res = self.client.post("/api/licenses/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["name"], "License A")
        self.assertTrue(TradeLicense.objects.filter(name="License A").exists())

    def test_create_name_too_long(self):
        payload = self._base()
        payload["name"] = "X" * 101
        res = self.client.post("/api/licenses/", payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data["errors"])
