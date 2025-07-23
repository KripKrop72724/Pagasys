from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from rest_framework.test import APIClient

from pagasys.models import (
    Company, Branch, Department, Project, TradeLicense, Employee
)


class ObjectPermissionsTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        User = get_user_model()

        # company and branches
        self.c1 = Company.objects.create(name="C1")
        self.c2 = Company.objects.create(name="C2")
        self.b1 = Branch.objects.create(company=self.c1, name="B1")
        self.b2 = Branch.objects.create(company=self.c1, name="B2")
        self.b3 = Branch.objects.create(company=self.c2, name="B3")
        self.d1 = Department.objects.create(branch=self.b1, name="D1")
        self.d2 = Department.objects.create(branch=self.b2, name="D2")
        self.d3 = Department.objects.create(branch=self.b3, name="D3")
        self.p1 = Project.objects.create(branch=self.b2, name="P1", start_date="2024-01-01")

        self.lic1 = TradeLicense.objects.create(
            company=self.c1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        self.lic1.branches.set([self.b1, self.b2])
        self.lic2 = TradeLicense.objects.create(
            company=self.c2,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        self.lic2.branches.set([self.b3])

        self.emp1 = User.objects.create_user(
            username="emp1",
            password="pass",
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.emp2 = User.objects.create_user(
            username="emp2",
            password="pass",
            trade_license=self.lic1,
            project=self.p1,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.emp_other = User.objects.create_user(
            username="emp3",
            password="pass",
            trade_license=self.lic2,
            department=self.d3,
            hire_date="2024-01-01",
            employment_type="permanent",
        )

        def make_user(username, group, **kwargs):
            u = User.objects.create_user(
                username=username,
                password="pass",
                is_staff=True,
                trade_license=self.lic1,
                hire_date="2024-01-01",
                employment_type="permanent",
                **kwargs,
            )
            u.groups.add(Group.objects.get(name=group))
            return u

        self.company_admin = make_user("ca", "Company Admin", department=self.d1)
        self.branch_manager = make_user("bm", "Branch Manager", department=self.d1)
        self.department_manager = make_user("dm", "Department Manager", department=self.d1)
        self.project_manager = make_user("pm", "Project Manager", project=self.p1)
        self.employee_user = make_user("eu", "Employee", department=self.d1)

    def _get_ids(self, response):
        return {obj["id"] for obj in response.data["results"]}

    def test_company_admin_scope(self):
        self.client.force_authenticate(self.company_admin)
        res = self.client.get("/api/employees/")
        ids = self._get_ids(res)
        self.assertIn(self.emp1.id, ids)
        self.assertIn(self.emp2.id, ids)
        self.assertNotIn(self.emp_other.id, ids)

    def test_branch_manager_scope(self):
        self.client.force_authenticate(self.branch_manager)
        res = self.client.get("/api/employees/")
        ids = self._get_ids(res)
        self.assertIn(self.emp1.id, ids)
        self.assertNotIn(self.emp2.id, ids)
        self.assertNotIn(self.emp_other.id, ids)

        res = self.client.get(f"/api/employees/?department={self.d2.id}")
        ids = self._get_ids(res)
        self.assertNotIn(self.emp2.id, ids)

    def test_department_manager_scope(self):
        self.client.force_authenticate(self.department_manager)
        res = self.client.get("/api/employees/")
        ids = self._get_ids(res)
        self.assertIn(self.emp1.id, ids)
        self.assertNotIn(self.emp2.id, ids)
        self.assertNotIn(self.emp_other.id, ids)
        for obj in res.data["results"]:
            self.assertEqual(obj["department"], self.d1.id)

    def test_project_manager_scope(self):
        self.client.force_authenticate(self.project_manager)
        res = self.client.get("/api/employees/")
        ids = self._get_ids(res)
        self.assertEqual(ids, {self.emp2.id, self.project_manager.id})

    def test_employee_scope(self):
        self.client.force_authenticate(self.employee_user)
        res = self.client.get("/api/employees/")
        ids = self._get_ids(res)
        self.assertEqual(ids, {self.employee_user.id})

    def test_object_permission_denied(self):
        self.client.force_authenticate(self.branch_manager)
        url = f"/api/employees/{self.emp2.id}/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)
        res = self.client.patch(url, {"first_name": "X"}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_allowed_update(self):
        self.client.force_authenticate(self.department_manager)
        url = f"/api/employees/{self.emp1.id}/"
        res = self.client.patch(
            url,
            {
                "first_name": "New",
                "department": self.d1.id,
                "trade_license": self.lic1.id,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.emp1.refresh_from_db()
        self.assertEqual(self.emp1.first_name, "New")

