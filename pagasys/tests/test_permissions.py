from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient


class BulkPermissionsTests(TestCase):
    """Ensure bulk endpoints enforce authentication and group permissions."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        from pagasys.models import Company, Branch, Department, TradeLicense
        company = Company.objects.create(name="C")
        branch = Branch.objects.create(company=company, name="B1")
        department = Department.objects.create(branch=branch, name="D1")
        license = TradeLicense.objects.create(
            company=company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        license.branches.set([branch])
        self.user = User.objects.create_user(
            username="permuser",
            password="pass",
            is_staff=True,
            is_superuser=False,
            trade_license=license,
            department=department,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        # Groups exist but user is not added to any
        for name in [
            "Company Admin",
            "Branch Manager",
            "Department Manager",
            "Project Manager",
            "Payroll Manager",
        ]:
            Group.objects.get_or_create(name=name)

    def test_unauthenticated_requests_denied(self):
        endpoints = [
            ("post", "/api/companies/bulk/"),
            ("patch", "/api/companies/bulk-update/"),
            ("post", "/api/companies/bulk-delete/"),
            ("post", "/api/branches/bulk/"),
            ("patch", "/api/branches/bulk-update/"),
            ("post", "/api/branches/bulk-delete/"),
        ]
        for method, url in endpoints:
            with self.subTest(url=url):
                res = getattr(self.client, method)(url, [], format="json")
                self.assertEqual(res.status_code, 401)

    def test_missing_group_denied(self):
        self.client.force_authenticate(self.user)
        endpoints = [
            ("post", "/api/companies/bulk/"),
            ("patch", "/api/companies/bulk-update/"),
            ("post", "/api/companies/bulk-delete/"),
            ("post", "/api/branches/bulk/"),
            ("patch", "/api/branches/bulk-update/"),
            ("post", "/api/branches/bulk-delete/"),
            ("post", "/api/departments/bulk/"),
            ("patch", "/api/departments/bulk-update/"),
            ("post", "/api/departments/bulk-delete/"),
            ("post", "/api/projects/bulk/"),
            ("patch", "/api/projects/bulk-update/"),
            ("post", "/api/projects/bulk-delete/"),
            ("post", "/api/employees/bulk/"),
            ("patch", "/api/employees/bulk-update/"),
            ("post", "/api/employees/bulk-delete/"),
            ("post", "/api/designations/bulk/"),
            ("patch", "/api/designations/bulk-update/"),
            ("post", "/api/designations/bulk-delete/"),
            ("post", "/api/licenses/bulk/"),
            ("patch", "/api/licenses/bulk-update/"),
            ("post", "/api/licenses/bulk-delete/"),
        ]
        for method, url in endpoints:
            with self.subTest(url=url):
                res = getattr(self.client, method)(url, [], format="json")
                self.assertEqual(res.status_code, 403)

