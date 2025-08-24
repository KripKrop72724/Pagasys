from rest_framework.test import APIClient
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from pagasys.models import (
    Company,
    Branch,
    Department,
    TradeLicense,
    Employee,
    ShiftTemplate,
    RosterEntry,
)


class RosterEntryApiTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch])
        self.user = Employee.objects.create_user(
            username="u1",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        admin_group = Group.objects.get(name="Company Admin")
        self.user.groups.add(admin_group)
        self.client.force_authenticate(self.user)
        self.shift = ShiftTemplate.objects.create(
            company=self.company, name="Day", start_time="09:00", end_time="17:00"
        )
        RosterEntry.objects.bulk_create(
            [
                RosterEntry(employee=self.user, shift=self.shift, date="2024-07-01"),
                RosterEntry(
                    employee=self.user,
                    shift=self.shift,
                    date="2024-07-02",
                    is_rest_day=True,
                ),
                RosterEntry(employee=self.user, shift=self.shift, date="2024-07-03"),
            ]
        )
        # second branch and employee for branch filtering
        self.branch2 = Branch.objects.create(company=self.company, name="B2")
        dept2 = Department.objects.create(branch=self.branch2, name="D2")
        user2 = Employee.objects.create_user(
            username="u2",
            password="pass",
            department=dept2,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        RosterEntry.objects.create(
            employee=user2, shift=self.shift, date="2024-07-01"
        )

    def test_filter_date_range(self):
        resp = self.client.get(
            "/api/roster-entries/?date_from=2024-07-01&date_to=2024-07-02"
        )
        assert resp.status_code == 200
        assert [r["date"] for r in resp.data["results"]] == [
            "2024-07-01",
            "2024-07-01",
            "2024-07-02",
        ]

    def test_filter_branch(self):
        resp = self.client.get(f"/api/roster-entries/?branch={self.branch.id}")
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 3
        resp = self.client.get(f"/api/roster-entries/?branch={self.branch2.id}")
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    def test_ordering(self):
        resp = self.client.get("/api/roster-entries/?ordering=-date")
        assert resp.status_code == 200
        assert [r["date"] for r in resp.data["results"]] == [
            "2024-07-03",
            "2024-07-02",
            "2024-07-01",
            "2024-07-01",
        ]

    def test_patch_update(self):
        entry = RosterEntry.objects.first()
        resp = self.client.patch(
            f"/api/roster-entries/{entry.id}/",
            {"is_rest_day": True},
            format="json",
        )
        assert resp.status_code == 200
        entry.refresh_from_db()
        assert entry.is_rest_day is True

    def test_overview(self):
        resp = self.client.get("/api/roster-entries/overview/?start=2024-07-01&days=3")
        assert resp.status_code == 200
        assert resp.data["start"] == "2024-07-01"
        assert resp.data["days"] == 3
        assert len(resp.data["employees"]) == 2
        first = next(e for e in resp.data["employees"] if e["id"] == self.user.id)
        assert len(first["entries"]) == 3

    def test_overview_requires_params(self):
        resp = self.client.get("/api/roster-entries/overview/?start=bad&days=-1")
        assert resp.status_code == 400
