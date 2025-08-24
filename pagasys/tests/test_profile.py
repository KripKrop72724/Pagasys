from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from pagasys.models import Company, Branch, Department, Employee


class ProfileEndpointTests(TestCase):
    """Tests for the authenticated user profile endpoint."""

    def setUp(self):
        self.client = APIClient()
        company = Company.objects.create(name="Acme")
        branch = Branch.objects.create(company=company, name="HQ")
        self.department = Department.objects.create(branch=branch, name="IT")

    def _create_employee(self, **kwargs):
        defaults = dict(
            username="alice",
            password="pass",
            visa_type="personal",
            department=self.department,
            hire_date=timezone.localdate(),
            employment_type="permanent",
        )
        defaults.update(kwargs)
        user = Employee.objects.create_user(**defaults)
        return user

    def test_requires_authentication(self):
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, 401)

    def test_returns_profile_for_authenticated_user(self):
        user = self._create_employee()
        self.client.force_authenticate(user)
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], user.id)
        self.assertNotIn("password", response.data)

    def test_superuser_response_excludes_groups(self):
        user = self._create_employee(username="admin", is_superuser=True)
        self.client.force_authenticate(user)
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("groups", response.data)
