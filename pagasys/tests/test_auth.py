from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from pagasys.models import Company, Branch, Department, TradeLicense
from rest_framework.test import APIClient
from django.test import TestCase


class JWTAuthTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch])

        self.user = User.objects.create_user(
            username="jwtuser",
            password="pass",
            is_staff=True,
            is_superuser=True,
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        grp, _ = Group.objects.get_or_create(name="Company Admin")
        self.user.groups.add(grp)
        self.client = APIClient()

    def test_obtain_token_and_authenticate(self):
        response = self.client.post(
            "/api/token/", {"username": "jwtuser", "password": "pass"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        token = response.data["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        res = self.client.get("/api/companies/")
        self.assertEqual(res.status_code, 200)
