from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.core.management import call_command
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, TradeLicense


class AdminDropdownScopeTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        # two companies/branches/departments
        self.c1 = Company.objects.create(name="C1")
        self.c2 = Company.objects.create(name="C2")
        self.b1 = Branch.objects.create(company=self.c1, name="B1")
        self.b2 = Branch.objects.create(company=self.c2, name="B2")
        self.d1 = Department.objects.create(branch=self.b1, name="D1")
        self.d2 = Department.objects.create(branch=self.b2, name="D2")
        self.lic1 = TradeLicense.objects.create(
            company=self.c1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        self.lic1.branches.set([self.b1])
        bm_group = Group.objects.get(name="Branch Manager")
        self.user = User.objects.create_user(
            username="bm",
            password="pass",
            is_staff=True,
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.user.groups.add(bm_group)
        self.client.force_login(self.user)

    def test_employee_add_form_filters_departments(self):
        url = reverse("admin:pagasys_employee_add")
        res = self.client.get(url)
        self.assertContains(res, self.d1.name)
        # Ensure only departments from the branch manager's scope appear
        dept_field = res.context["adminform"].form.fields["department"]
        qs = dept_field.queryset
        self.assertIn(self.d1, qs)
        self.assertNotIn(self.d2, qs)


class APICreateScopeTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.client = APIClient()
        self.c1 = Company.objects.create(name="C1")
        self.c2 = Company.objects.create(name="C2")
        self.b1 = Branch.objects.create(company=self.c1, name="B1")
        self.b2 = Branch.objects.create(company=self.c2, name="B2")
        self.d1 = Department.objects.create(branch=self.b1, name="D1")
        self.d2 = Department.objects.create(branch=self.b2, name="D2")
        self.lic1 = TradeLicense.objects.create(
            company=self.c1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        self.lic1.branches.set([self.b1])
        bm_group = Group.objects.get(name="Branch Manager")
        self.user = User.objects.create_user(
            username="bm",
            password="pass",
            is_staff=True,
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.user.groups.add(bm_group)
        self.client.force_authenticate(self.user)

    def _emp_payload(self, dept):
        return {
            "username": "emp",
            "password": "pass",
            "trade_license": self.lic1.id,
            "department": dept,
            "hire_date": "2024-02-01",
            "employment_type": "permanent",
            "visa_type": "company",
        }

    def test_cannot_create_employee_outside_scope(self):
        res = self.client.post("/api/employees/", self._emp_payload(self.d2.id), format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(get_user_model().objects.filter(username="emp").count(), 0)

    def test_create_employee_within_scope(self):
        res = self.client.post("/api/employees/", self._emp_payload(self.d1.id), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(get_user_model().objects.filter(username="emp").count(), 1)
