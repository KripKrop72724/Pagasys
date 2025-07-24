from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.management import call_command
from django.contrib.admin.sites import AdminSite
from pagasys.admin import EmployeeAdmin

from pagasys.models import Company, Branch, Department, TradeLicense

class EmployeeAdminFieldTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
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
        self.admin = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.client.force_login(self.admin)
        self.factory = RequestFactory()
        self.site = AdminSite()

    def _create_employee(self, **kwargs):
        User = get_user_model()
        data = {
            "username": "emp",
            "password": "pass",
            "trade_license": self.license,
            "department": self.department,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
            "is_staff": True,
        }
        data.update(kwargs)
        return User.objects.create_user(**data)

    def test_change_form_shows_groups_for_regular_user(self):
        emp = self._create_employee()
        url = reverse("admin:pagasys_employee_change", args=[emp.id])
        res = self.client.get(url)
        self.assertNotContains(res, "id_user_permissions")

    def test_change_form_hides_groups_for_superuser(self):
        emp = self._create_employee(is_superuser=True, is_staff=True)
        url = reverse("admin:pagasys_employee_change", args=[emp.id])
        res = self.client.get(url)
        self.assertNotContains(res, "id_groups")
        self.assertNotContains(res, "id_user_permissions")

    def test_add_form_no_permissions_field(self):
        url = reverse("admin:pagasys_employee_add")
        res = self.client.get(url)
        self.assertContains(res, "id_groups")
        self.assertNotContains(res, "id_user_permissions")

    def test_superuser_edit_does_not_affect_regular_forms(self):
        super_emp = self._create_employee(is_superuser=True, is_staff=True)
        url = reverse("admin:pagasys_employee_change", args=[super_emp.id])
        self.client.get(url)

        emp = self._create_employee(username="emp2")
        url = reverse("admin:pagasys_employee_change", args=[emp.id])
        res = self.client.get(url)
        self.assertContains(res, "id_groups")

    def test_post_is_superuser_hides_groups(self):
        emp_admin = EmployeeAdmin(get_user_model(), AdminSite())
        factory = RequestFactory()
        req = factory.post("/", {"is_superuser": "on"})
        req.user = self.admin
        fieldsets = emp_admin.get_fieldsets(req, self._create_employee())
        self.assertNotIn("groups", fieldsets[2][1]["fields"])

    def test_post_without_superuser_shows_groups(self):
        emp_admin = EmployeeAdmin(get_user_model(), AdminSite())
        factory = RequestFactory()
        req = factory.post("/", {})
        req.user = self.admin
        fieldsets = emp_admin.get_fieldsets(req, self._create_employee())
        self.assertIn("groups", fieldsets[2][1]["fields"])

