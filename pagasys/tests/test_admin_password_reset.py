from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from pagasys.models import Company, Branch, Department, TradeLicense


class AdminPasswordResetTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch])

        self.superuser = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

        self.employee = User.objects.create_user(
            username="emp",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

    def test_superuser_can_access_password_change_view(self):
        self.client.force_login(self.superuser)
        url = reverse("admin:auth_user_password_change", args=[self.employee.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "password")
