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
    Project,
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
        self.proj1 = Project.objects.create(
            branch=self.branch1,
            name="P1",
            start_date="2024-01-01",
        )
        self.proj2 = Project.objects.create(
            branch=self.branch2,
            name="P2",
            start_date="2024-01-01",
        )
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch1, self.branch2])
        User = Employee
        bm_group = Group.objects.get(name="Branch Manager")
        dm_group = Group.objects.get(name="Department Manager")
        pm_group = Group.objects.get(name="Project Manager")
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
        self.dept_manager = User.objects.create_user(
            username="dm",
            password="pass",
            department=self.dept1,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
            is_staff=True,
        )
        self.dept_manager.groups.add(dm_group)
        self.dept_emp = User.objects.create_user(
            username="ed1",
            password="pass",
            department=self.dept1,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
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
        for u in [self.dept_emp, self.emp_other]:
            u.groups.add(emp_group)
        self.project_manager = User.objects.create_user(
            username="pm",
            password="pass",
            project=self.proj1,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
            is_staff=True,
        )
        self.project_manager.groups.add(pm_group)
        self.proj_emp = User.objects.create_user(
            username="ep1",
            password="pass",
            project=self.proj1,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.proj_other = User.objects.create_user(
            username="ep2",
            password="pass",
            project=self.proj2,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.proj_emp.groups.add(emp_group)
        self.proj_other.groups.add(emp_group)
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

    def test_department_manager_scoped_roster(self):
        self.client.force_authenticate(self.dept_manager)
        ok = {"employee": self.dept_emp.id, "date": "2024-08-04", "shift": self.shift.id}
        resp_ok = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            ok,
            format="json",
        )
        assert resp_ok.status_code == 201
        bad = {"employee": self.emp_other.id, "date": "2024-08-05", "shift": self.shift.id}
        resp_bad = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            bad,
            format="json",
        )
        assert resp_bad.status_code == 403
        RosterEntry.objects.create(employee=self.dept_emp, date="2024-08-06", shift=self.shift)
        RosterEntry.objects.create(employee=self.emp_other, date="2024-08-07", shift=self.shift)
        resp = self.client.get(f"/api/companies/{self.company.id}/roster/")
        ids = {r["employee"] for r in resp.data["results"]}
        assert ids == {self.dept_emp.id}

    def test_project_manager_scoped_roster(self):
        self.client.force_authenticate(self.project_manager)
        ok = {"employee": self.proj_emp.id, "date": "2024-08-08", "shift": self.shift.id}
        resp_ok = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            ok,
            format="json",
        )
        assert resp_ok.status_code == 201
        bad = {"employee": self.proj_other.id, "date": "2024-08-09", "shift": self.shift.id}
        resp_bad = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            bad,
            format="json",
        )
        assert resp_bad.status_code == 403
        RosterEntry.objects.create(employee=self.proj_emp, date="2024-08-10", shift=self.shift)
        RosterEntry.objects.create(employee=self.proj_other, date="2024-08-11", shift=self.shift)
        resp = self.client.get(f"/api/companies/{self.company.id}/roster/")
        ids = {r["employee"] for r in resp.data["results"]}
        assert ids == {self.proj_emp.id}

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
