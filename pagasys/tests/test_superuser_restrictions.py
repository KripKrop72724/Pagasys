from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, TradeLicense


class SuperuserRestrictionAPITests(TestCase):
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

        self.superuser = User.objects.create_superuser(
            username="super",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
        )

        self.user = User.objects.create_user(
            username="admin",
            password="pass",
            is_staff=True,
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.user.groups.add(Group.objects.get(name="Company Admin"))
        self.client.force_authenticate(self.user)

    def _emp_payload(self, **extra):
        data = {
            "username": "emp",
            "password": "pass",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
        }
        data.update(extra)
        return data

    def test_superusers_filtered_from_list(self):
        res = self.client.get("/api/employees/")
        ids = {obj["id"] for obj in res.data["results"]}
        self.assertNotIn(self.superuser.id, ids)

    def test_get_superuser_returns_404(self):
        res = self.client.get(f"/api/employees/{self.superuser.id}/")
        self.assertEqual(res.status_code, 404)

    def test_cannot_create_superuser(self):
        payload = self._emp_payload(is_superuser=True)
        res = self.client.post("/api/employees/", payload, format="json")
        self.assertEqual(res.status_code, 403)

    def test_cannot_promote_to_superuser(self):
        User = get_user_model()
        emp = User.objects.create_user(
            username="emp1",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        url = f"/api/employees/{emp.id}/"
        res = self.client.patch(url, {"is_superuser": True}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_cannot_delete_superuser(self):
        res = self.client.delete(f"/api/employees/{self.superuser.id}/")
        self.assertIn(res.status_code, [403, 404])
