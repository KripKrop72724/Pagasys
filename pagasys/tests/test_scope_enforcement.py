import json

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.core.management import call_command
from rest_framework.test import APIClient

from pagasys.models import (
    Company,
    Branch,
    Department,
    TradeLicense,
    ShiftTemplate,
    RosterEntry,
    WorkCalendar,
)


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
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.lic1.branches.set([self.b1])
        self.lic2 = TradeLicense.objects.create(
            company=self.c2,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.lic2.branches.set([self.b2])
        self.emp_c1 = User.objects.create_user(
            username="e1",
            password="pass",
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        self.emp_c2 = User.objects.create_user(
            username="e2",
            password="pass",
            trade_license=self.lic2,
            department=self.d2,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        self.shift1 = ShiftTemplate.objects.create(
            company=self.c1,
            name="S1",
            start_time="09:00",
            end_time="17:00",
        )
        self.shift2 = ShiftTemplate.objects.create(
            company=self.c2,
            name="S2",
            start_time="09:00",
            end_time="17:00",
        )
        self.cal1 = WorkCalendar.objects.create(company=self.c1, name="Cal1")
        self.cal2 = WorkCalendar.objects.create(company=self.c2, name="Cal2")
        ca_group = Group.objects.get(name="Company Admin")
        self.company_admin = User.objects.create_user(
            username="ca",
            password="pass",
            is_staff=True,
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.company_admin.groups.add(ca_group)
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

    def test_roster_entry_add_form_scopes_fields(self):
        url = reverse("admin:pagasys_rosterentry_add")
        res = self.client.get(url)
        html = res.content.decode()
        import re

        shift_block = re.search(r'<select[^>]*id="id_shift"[^>]*>(.*?)</select>', html, re.S).group(1)
        self.assertIn(f'value="{self.shift1.pk}"', shift_block)
        self.assertNotIn(f'value="{self.shift2.pk}"', shift_block)

        url = reverse("admin:pagasys_employee_autocomplete")
        params = {
            "term": "",
            "app_label": "pagasys",
            "model_name": "rosterentry",
            "field_name": "employee",
            "forward": "branch",
            "branch": self.b1.pk,
        }
        res = self.client.get(url, params)
        data = json.loads(res.content)
        ids = [int(r["id"]) for r in data["results"]]
        self.assertIn(self.emp_c1.pk, ids)
        self.assertNotIn(self.emp_c2.pk, ids)

    def test_holiday_add_form_scopes_calendar(self):
        self.client.force_login(self.company_admin)
        url = reverse("admin:pagasys_holiday_add")
        res = self.client.get(url)
        label1 = f">{self.cal1.name} - {self.cal1.company.name}</option>"
        label2 = f">{self.cal2.name} - {self.cal2.company.name}</option>"
        self.assertContains(res, label1)
        self.assertNotContains(res, label2)

    def test_branch_form_scopes_calendar(self):
        self.client.force_login(self.company_admin)
        add_url = reverse("admin:pagasys_branch_add")
        res = self.client.get(add_url)
        label1 = f">{self.cal1.name} - {self.cal1.company.name}</option>"
        label2 = f">{self.cal2.name} - {self.cal2.company.name}</option>"
        self.assertContains(res, label1)
        self.assertNotContains(res, label2)
        change_url = reverse("admin:pagasys_branch_change", args=[self.b1.pk])
        res = self.client.get(change_url)
        label1 = f">{self.cal1.name} - {self.cal1.company.name}</option>"
        label2 = f">{self.cal2.name} - {self.cal2.company.name}</option>"
        self.assertContains(res, label1)
        self.assertNotContains(res, label2)

    def test_employee_form_scopes_calendar(self):
        self.client.force_login(self.company_admin)
        add_url = reverse("admin:pagasys_employee_add")
        res = self.client.get(add_url)
        label2 = f">{self.cal2.name} - {self.cal2.company.name}</option>"
        self.assertNotContains(res, label2)
        change_url = reverse("admin:pagasys_employee_change", args=[self.emp_c1.pk])
        label1 = f">{self.cal1.name} - {self.cal1.company.name}</option>"
        res = self.client.get(change_url)
        self.assertContains(res, label1)
        self.assertNotContains(res, label2)


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
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.lic1.branches.set([self.b1])
        self.lic2 = TradeLicense.objects.create(
            company=self.c2,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.lic2.branches.set([self.b2])
        self.emp_c1 = User.objects.create_user(
            username="e1",
            password="pass",
            trade_license=self.lic1,
            department=self.d1,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        self.emp_c2 = User.objects.create_user(
            username="e2",
            password="pass",
            trade_license=self.lic2,
            department=self.d2,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        self.shift1 = ShiftTemplate.objects.create(
            company=self.c1,
            name="S1",
            start_time="09:00",
            end_time="17:00",
        )
        self.shift2 = ShiftTemplate.objects.create(
            company=self.c2,
            name="S2",
            start_time="09:00",
            end_time="17:00",
        )
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

    def test_cannot_create_roster_entry_outside_scope(self):
        payload = {
            "employee": self.emp_c2.id,
            "date": "2024-03-01",
            "shift": self.shift2.id,
        }
        res = self.client.post("/api/roster-entries/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(RosterEntry.objects.count(), 0)

    def test_create_roster_entry_within_scope(self):
        payload = {
            "employee": self.emp_c1.id,
            "date": "2024-03-01",
            "shift": self.shift1.id,
        }
        res = self.client.post("/api/roster-entries/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(RosterEntry.objects.count(), 1)


class ShiftTemplateAPIScopeTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.client = APIClient()
        self.c1 = Company.objects.create(name="C1")
        self.c2 = Company.objects.create(name="C2")
        pm_group = Group.objects.get(name="Payroll Manager")
        b1 = self.c1.branches.create(name="B1")
        dept = Department.objects.create(branch=b1, name="D1")
        lic = TradeLicense.objects.create(
            company=self.c1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        lic.branches.set([b1])
        self.user = User.objects.create_user(
            username="pm",
            password="pass",
            is_staff=True,
            trade_license=lic,
            department=dept,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.user.groups.add(pm_group)
        self.client.force_authenticate(self.user)

    def test_cannot_create_shift_template_outside_scope(self):
        payload = {
            "company": self.c2.id,
            "name": "Sx",
            "start_time": "09:00",
            "end_time": "17:00",
        }
        res = self.client.post("/api/shift-templates/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(ShiftTemplate.objects.filter(name="Sx").count(), 0)

    def test_create_shift_template_within_scope(self):
        payload = {
            "company": self.c1.id,
            "name": "Sx",
            "start_time": "09:00",
            "end_time": "17:00",
        }
        res = self.client.post("/api/shift-templates/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(ShiftTemplate.objects.filter(name="Sx").count(), 1)
