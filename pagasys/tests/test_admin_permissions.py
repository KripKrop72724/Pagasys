from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.core.management import call_command
from django.test import RequestFactory
from django.contrib import admin

from pagasys.models import Company, Branch, Department, Project, TradeLicense
from pagasys.admin import ScopedInlineMixin


class AdminObjectPermissionTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()

        self.c1 = Company.objects.create(name="C1")
        self.c2 = Company.objects.create(name="C2")
        self.b1 = Branch.objects.create(company=self.c1, name="B1")
        self.b2 = Branch.objects.create(company=self.c2, name="B2")
        self.d1 = Department.objects.create(branch=self.b1, name="D1")
        self.d2 = Department.objects.create(branch=self.b2, name="D2")
        self.p1 = Project.objects.create(branch=self.b1, name="P1", start_date="2024-01-01")
        self.p2 = Project.objects.create(branch=self.b2, name="P2", start_date="2024-01-01")

        self.lic1 = TradeLicense.objects.create(
            company=self.c1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        self.lic1.branches.set([self.b1])
        self.lic2 = TradeLicense.objects.create(
            company=self.c2,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=10,
        )
        self.lic2.branches.set([self.b2])

        bm_group = Group.objects.get(name="Branch Manager")
        self.branch_manager = User.objects.create_user(
            username="bm",
            password="pass",
            is_staff=True,
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.branch_manager.groups.add(bm_group)

        self.emp1 = User.objects.create_user(
            username="e1",
            password="pass",
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.emp2 = User.objects.create_user(
            username="e2",
            password="pass",
            trade_license=self.lic2,
            department=self.d2,
            hire_date="2024-01-01",
            employment_type="permanent",
        )

        employee_group = Group.objects.get(name="Employee")
        self.employee_staff = User.objects.create_user(
            username="staffemp",
            password="pass",
            is_staff=True,
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.employee_staff.groups.add(employee_group)

    def test_department_list_scoped(self):
        self.client.force_login(self.branch_manager)
        url = reverse("admin:pagasys_department_changelist")
        res = self.client.get(url)
        self.assertContains(res, self.d1.name)
        self.assertNotContains(res, self.d2.name)

    def test_department_change_permission_denied(self):
        self.client.force_login(self.branch_manager)
        url = reverse("admin:pagasys_department_change", args=[self.d2.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)
        url = reverse("admin:pagasys_department_change", args=[self.d1.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_department_delete_permission_denied(self):
        self.client.force_login(self.branch_manager)
        url = reverse("admin:pagasys_department_delete", args=[self.d2.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)
        url = reverse("admin:pagasys_department_delete", args=[self.d1.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)

    def test_employee_change_permission_denied(self):
        self.client.force_login(self.branch_manager)
        url = reverse("admin:pagasys_employee_change", args=[self.emp2.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)
        url = reverse("admin:pagasys_employee_change", args=[self.emp1.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_employee_delete_permission_denied(self):
        self.client.force_login(self.branch_manager)
        url = reverse("admin:pagasys_employee_delete", args=[self.emp2.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)
        url = reverse("admin:pagasys_employee_delete", args=[self.emp1.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)

    def test_employee_view_permission_scoped(self):
        self.client.force_login(self.employee_staff)
        url = reverse("admin:pagasys_employee_change", args=[self.emp1.id])
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)
        url = reverse("admin:pagasys_employee_change", args=[self.employee_staff.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_inline_queryset_scoped(self):
        class DeptInline(ScopedInlineMixin, admin.TabularInline):
            model = Department

        inline = DeptInline(Branch, admin.site)
        factory = RequestFactory()
        req = factory.get("/")
        req.user = self.branch_manager

        qs = inline.get_queryset(req)
        self.assertIn(self.d1, qs)
        self.assertNotIn(self.d2, qs)
