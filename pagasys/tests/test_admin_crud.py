from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase
from django.core.exceptions import ValidationError

from pagasys.models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
)

from .test_models import ModelFactoryMixin


class AdminCRUDTests(ModelFactoryMixin, TestCase):
    """Verify basic CRUD flows for all admin models."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.project = self.create_project(self.branch)
        self.designation = self.create_designation(self.company)
        self.license = self.create_license(
            company=self.company, branches=[self.branch], license_no="LICX", max_visas=5
        )

        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.client.force_login(self.superuser)

    def _assert_deleted(self, model, obj_id):
        self.assertFalse(model.objects.filter(id=obj_id).exists())

    def test_company_crud(self):
        add_url = reverse("admin:pagasys_company_add")
        res = self.client.post(add_url, {"name": "NewCo"})
        self.assertEqual(res.status_code, 302)
        comp = Company.objects.get(name="NewCo")

        change_url = reverse("admin:pagasys_company_change", args=[comp.id])
        res = self.client.post(change_url, {"name": "NewCo2"})
        self.assertEqual(res.status_code, 302)
        comp.refresh_from_db()
        self.assertEqual(comp.name, "NewCo2")

        delete_url = reverse("admin:pagasys_company_delete", args=[comp.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Company, comp.id)

    def test_branch_crud(self):
        add_url = reverse("admin:pagasys_branch_add")
        res = self.client.post(add_url, {"company": self.company.id, "name": "B2"})
        self.assertEqual(res.status_code, 302)
        obj = Branch.objects.get(name="B2")

        change_url = reverse("admin:pagasys_branch_change", args=[obj.id])
        res = self.client.post(change_url, {"company": self.company.id, "name": "B3"})
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "B3")

        delete_url = reverse("admin:pagasys_branch_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Branch, obj.id)

    def test_designation_crud(self):
        add_url = reverse("admin:pagasys_designation_add")
        res = self.client.post(
            add_url, {"company": self.company.id, "name": "Des1", "level": "1"}
        )
        self.assertEqual(res.status_code, 302)
        obj = Designation.objects.get(name="Des1")

        change_url = reverse("admin:pagasys_designation_change", args=[obj.id])
        res = self.client.post(
            change_url,
            {"company": self.company.id, "name": "Des2", "level": "2"},
        )
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "Des2")

        delete_url = reverse("admin:pagasys_designation_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Designation, obj.id)

    def test_tradelicense_crud(self):
        add_url = reverse("admin:pagasys_tradelicense_add")
        data = {
            "company": self.company.id,
            "license_no": "LNEW",
            "issued_date": "2024-01-01",
            "expiry_date": "2025-01-01",
            "max_visas": 1,
            "branches": [self.branch.id],
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        obj = TradeLicense.objects.get(license_no="LNEW")

        change_url = reverse("admin:pagasys_tradelicense_change", args=[obj.id])
        data["license_no"] = "LNEW2"
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.license_no, "LNEW2")

        delete_url = reverse("admin:pagasys_tradelicense_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(TradeLicense, obj.id)

    def test_department_crud(self):
        add_url = reverse("admin:pagasys_department_add")
        res = self.client.post(add_url, {"branch": self.branch.id, "name": "D2"})
        self.assertEqual(res.status_code, 302)
        obj = Department.objects.get(name="D2")

        change_url = reverse("admin:pagasys_department_change", args=[obj.id])
        res = self.client.post(change_url, {"branch": self.branch.id, "name": "D3"})
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "D3")

        delete_url = reverse("admin:pagasys_department_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Department, obj.id)

    def test_project_crud(self):
        add_url = reverse("admin:pagasys_project_add")
        res = self.client.post(
            add_url, {"branch": self.branch.id, "name": "P2", "start_date": "2024-01-02"}
        )
        self.assertEqual(res.status_code, 302)
        obj = Project.objects.get(name="P2")

        change_url = reverse("admin:pagasys_project_change", args=[obj.id])
        res = self.client.post(
            change_url,
            {"branch": self.branch.id, "name": "P3", "start_date": "2024-01-03"},
        )
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "P3")

        delete_url = reverse("admin:pagasys_project_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Project, obj.id)

    def test_employee_crud(self):
        add_url = reverse("admin:pagasys_employee_add")
        data = {
            "username": "empadd",
            "usable_password": "true",
            "password1": "strongpass",
            "password2": "strongpass",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-02-01",
            "employment_type": "permanent",
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        emp = Employee.objects.get(username="empadd")

        change_url = reverse("admin:pagasys_employee_change", args=[emp.id])
        res = self.client.get(change_url)
        self.assertEqual(res.status_code, 200)

        delete_url = reverse("admin:pagasys_employee_delete", args=[emp.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Employee, emp.id)


class FieldValidationEdgeCaseTests(ModelFactoryMixin, TestCase):
    """Ensure model validations handle edge cases appropriately."""

    def setUp(self):
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)

    def test_company_name_length(self):
        with self.assertRaises(ValidationError):
            Company(name="" * 0).full_clean()
        with self.assertRaises(ValidationError):
            Company(name="x" * 256).full_clean()

    def test_branch_required_fields(self):
        with self.assertRaises(ValidationError):
            Branch(name="B", company=None).full_clean()
        with self.assertRaises(ValidationError):
            Branch(company=self.company, name="x" * 256).full_clean()

    def test_department_required_fields(self):
        with self.assertRaises(ValidationError):
            Department(name="", branch=self.branch).full_clean()
        with self.assertRaises(ValidationError):
            Department(name="x" * 256, branch=self.branch).full_clean()

    def test_project_required_fields(self):
        with self.assertRaises(ValidationError):
            Project(branch=self.branch, name="", start_date="2024-01-01").full_clean()
        with self.assertRaises(ValidationError):
            Project(branch=None, name="P", start_date="2024-01-01").full_clean()

    def test_designation_edge_cases(self):
        with self.assertRaises(ValidationError):
            Designation(company=self.company, name="x" * 101).full_clean()
        with self.assertRaises(ValidationError):
            Designation(company=None, name="D").full_clean()

