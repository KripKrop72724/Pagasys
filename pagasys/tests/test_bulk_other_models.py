from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from pagasys.models import (
    Company, Branch, Designation, TradeLicense,
    Department, Project, Employee
)


class OtherBulkActionsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="bulkuser", password="pass", is_staff=True, is_superuser=True
        )
        groups = [
            "Company Admin",
            "Branch Manager",
            "Department Manager",
            "Project Manager",
            "Payroll Manager",
        ]
        for name in groups:
            grp, _ = Group.objects.get_or_create(name=name)
            self.user.groups.add(grp)
        self.client.force_authenticate(self.user)

        self.company = Company.objects.create(name="Acme")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.project = Project.objects.create(branch=self.branch, name="P1", start_date="2024-01-01")
        self.designation = Designation.objects.create(company=self.company, name="Eng")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="LIC0",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch])

    def _run_crud_flow(self, base, model, create_payload, update_fields):
        initial = model.objects.count()
        res = self.client.post(f"/api/{base}/bulk/", create_payload, format="json")
        self.assertEqual(res.status_code, 201)
        ids = [obj["id"] for obj in res.data["created"]]
        self.assertEqual(len(ids), len(create_payload))

        update_payload = []
        for obj_id, fields in zip(ids, update_fields):
            data = {"id": obj_id}
            data.update(fields)
            update_payload.append(data)

        res = self.client.patch(f"/api/{base}/bulk-update/", update_payload, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["updated"]), len(update_payload))

        res = self.client.patch(f"/api/{base}/bulk-update/", [update_fields[0]], format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["errors"]), 1)

        res = self.client.post(f"/api/{base}/bulk-delete/", ids, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["deleted"], len(ids))
        self.assertEqual(model.objects.count(), initial)

        res = self.client.patch(f"/api/{base}/bulk-update/", update_payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["errors"]), len(update_payload))

        res = self.client.post(f"/api/{base}/bulk-delete/", {"id": ids[0]}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_branch_bulk_flow(self):
        create = [
            {"company": self.company.id, "name": "A"},
            {"company": self.company.id, "name": "B"},
        ]
        updates = [{"name": "A1"}, {"name": "B1"}]
        self._run_crud_flow("branches", Branch, create, updates)

    def test_designation_bulk_flow(self):
        create = [
            {"company": self.company.id, "name": "D1"},
            {"company": self.company.id, "name": "D2"},
        ]
        updates = [{"description": "x"}, {"description": "y"}]
        self._run_crud_flow("designations", Designation, create, updates)

    def test_license_bulk_flow(self):
        lic1 = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        lic1.branches.set([self.branch])
        lic2 = TradeLicense.objects.create(
            company=self.company,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        lic2.branches.set([self.branch])

        update = [
            {
                "id": lic1.id,
                "max_visas": 6,
                "issued_date": "2024-01-01",
                "expiry_date": "2025-01-01",
            },
            {
                "id": lic2.id,
                "max_visas": 7,
                "issued_date": "2024-01-01",
                "expiry_date": "2025-01-01",
            },
        ]
        res = self.client.patch("/api/licenses/bulk-update/", update, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.client.post("/api/licenses/bulk-delete/", [lic1.id, lic2.id], format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(TradeLicense.objects.filter(id__in=[lic1.id, lic2.id]).count(), 0)

    def test_department_bulk_flow(self):
        create = [
            {"branch": self.branch.id, "name": "A"},
            {"branch": self.branch.id, "name": "B"},
        ]
        updates = [{"name": "A1"}, {"name": "B1"}]
        self._run_crud_flow("departments", Department, create, updates)

    def test_project_bulk_flow(self):
        create = [
            {"branch": self.branch.id, "name": "A", "start_date": "2024-01-01"},
            {"branch": self.branch.id, "name": "B", "start_date": "2024-01-01"},
        ]
        updates = [{"name": "A1"}, {"end_date": "2024-12-31"}]
        self._run_crud_flow("projects", Project, create, updates)

    def test_employee_bulk_flow(self):
        create = [
            {
                "trade_license": self.license.id,
                "department": self.department.id,
                "first_name": "A",
                "last_name": "B",
                "hire_date": "2024-01-02",
                "employment_type": "permanent",
            },
            {
                "trade_license": self.license.id,
                "department": self.department.id,
                "first_name": "C",
                "last_name": "D",
                "hire_date": "2024-01-03",
                "employment_type": "permanent",
            },
        ]
        updates = [
            {
                "last_name": "B1",
                "department": self.department.id,
                "trade_license": self.license.id,
            },
            {
                "last_name": "D1",
                "department": self.department.id,
                "trade_license": self.license.id,
            },
        ]
        self._run_crud_flow("employees", Employee, create, updates)
