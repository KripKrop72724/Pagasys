from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, TradeLicense


class CompanyAPITests(TestCase):
    """Ensure company endpoints expose contact fields."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        user_company = Company.objects.create(name="UserCo")
        branch = Branch.objects.create(company=user_company, name="B1")
        department = Department.objects.create(branch=branch, name="D1")
        license = TradeLicense.objects.create(
            company=user_company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        license.branches.set([branch])
        self.user = User.objects.create_user(
            username="api", password="pass", is_staff=True, is_superuser=True,
            trade_license=license, department=department,
            hire_date="2024-01-01", employment_type="permanent", visa_type="company",
        )
        self.client.force_authenticate(self.user)

    def test_contact_fields_crud(self):
        payload = {
            "name": "CompA",
            "timezone": "Asia/Dubai",
            "address": "123 Main",
            "logo": "http://example.com/logo.png",
            "email": "a@b.com",
            "phone": "+1",
            "website": "http://example.com",
        }
        res = self.client.post("/api/companies/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        comp_id = res.data["id"]

        res = self.client.get(f"/api/companies/{comp_id}/")
        self.assertEqual(res.status_code, 200)
        for field in ["address", "logo", "email", "phone", "website"]:
            self.assertEqual(res.data[field], payload[field])

        res = self.client.patch(
            f"/api/companies/{comp_id}/", {"address": "456 Ave"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["address"], "456 Ave")
