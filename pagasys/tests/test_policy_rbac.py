from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from pagasys.models import (
    Company,
    Branch,
    Department,
    TradeLicense,
    Employee,
    WorkCalendar,
    ShiftTemplate,
    RosterEntry,
)


class PolicyRBACScopeTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        self.company = Company.objects.create(name="C1")
        self.branch1 = Branch.objects.create(company=self.company, name="B1")
        self.branch2 = Branch.objects.create(company=self.company, name="B2")
        self.dept1 = Department.objects.create(branch=self.branch1, name="D1")
        self.dept2 = Department.objects.create(branch=self.branch2, name="D2")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch1, self.branch2])
        User = Employee
        bm_group = Group.objects.get(name="Branch Manager")
        self.branch_manager = User.objects.create_user(
            username="bm",
            password="pass",
            department=self.dept1,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
            is_staff=True,
        )
        self.branch_manager.groups.add(bm_group)
        self.emp_other = User.objects.create_user(
            username="e2",
            password="pass",
            department=self.dept2,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        emp_group = Group.objects.get(name="Employee")
        self.emp_other.groups.add(emp_group)
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="S",
            start_time="09:00",
            end_time="17:00",
        )

    def test_branch_manager_scoped_roster(self):
        self.client.force_authenticate(self.branch_manager)
        payload_ok = {"employee": self.branch_manager.id, "date": "2024-08-01", "shift": self.shift.id}
        resp_ok = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            payload_ok,
            format="json",
        )
        assert resp_ok.status_code == 201
        payload_bad = {"employee": self.emp_other.id, "date": "2024-08-02", "shift": self.shift.id}
        resp_bad = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            payload_bad,
            format="json",
        )
        assert resp_bad.status_code == 403
        RosterEntry.objects.create(employee=self.emp_other, date="2024-08-03", shift=self.shift)
        resp = self.client.get(f"/api/companies/{self.company.id}/roster/")
        ids = [r["employee"] for r in resp.data["results"]]
        assert ids == [self.branch_manager.id]

    def test_holiday_import_requires_admin(self):
        self.client.force_authenticate(self.branch_manager)
        cal = WorkCalendar.objects.create(company=self.company, name="Cal")
        payload = [{"date": "2024-01-01", "name": "NY"}]
        resp = self.client.post(
            f"/api/companies/{self.company.id}/work-calendars/{cal.id}/holidays/import/",
            payload,
            format="json",
        )
        assert resp.status_code == 403

    def test_employee_roster_read_only(self):
        self.client.force_authenticate(self.emp_other)
        RosterEntry.objects.create(employee=self.emp_other, date="2024-09-01", shift=self.shift)
        RosterEntry.objects.create(employee=self.branch_manager, date="2024-09-02", shift=self.shift)
        resp = self.client.get(f"/api/companies/{self.company.id}/roster/")
        ids = [r["employee"] for r in resp.data["results"]]
        assert ids == [self.emp_other.id]
        payload = {"employee": self.emp_other.id, "date": "2024-09-03", "shift": self.shift.id}
        resp2 = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            payload,
            format="json",
        )
        assert resp2.status_code == 403
