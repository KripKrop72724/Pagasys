from django.core.management import call_command
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from django.test import TestCase

from pagasys.models import (
    Company,
    Branch,
    Department,
    TradeLicense,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    Employee,
    RosterEntry,
)


class RosterEntryHolidayTests(TestCase):
    """Ensure roster entries auto-flag holidays and allow overrides."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="LIC",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch])
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="Day",
            start_time="09:00",
            end_time="17:00",
        )
        self.calendar = WorkCalendar.objects.create(
            company=self.company,
            name="Default",
            is_default=True,
        )
        Holiday.objects.create(calendar=self.calendar, date="2024-12-02", name="HD")
        self.user = Employee.objects.create_user(
            username="u1",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.user.groups.add(Group.objects.get(name="Company Admin"))
        self.client.force_authenticate(self.user)

    def test_model_auto_marks_holiday(self):
        entry = RosterEntry.objects.create(
            employee=self.user, date="2024-12-02", shift=self.shift
        )
        assert entry.is_holiday and entry.is_holiday_calendar

    def test_model_manual_override_on_create(self):
        entry = RosterEntry.objects.create(
            employee=self.user,
            date="2024-12-02",
            shift=self.shift,
            is_holiday=False,
        )
        assert not entry.is_holiday and entry.is_holiday_calendar

    def test_model_manual_override_after_create(self):
        entry = RosterEntry.objects.create(
            employee=self.user, date="2024-12-02", shift=self.shift
        )
        entry.is_holiday = False
        entry.save()
        entry.refresh_from_db()
        assert not entry.is_holiday and entry.is_holiday_calendar

    def test_bulk_create_applies_holiday(self):
        objs = [
            RosterEntry(employee=self.user, date="2024-12-02", shift=self.shift),
            RosterEntry(employee=self.user, date="2024-12-03", shift=self.shift),
        ]
        RosterEntry.objects.bulk_create(objs)
        holiday = RosterEntry.objects.get(date="2024-12-02")
        normal = RosterEntry.objects.get(date="2024-12-03")
        assert holiday.is_holiday and holiday.is_holiday_calendar
        assert not normal.is_holiday and not normal.is_holiday_calendar

    def test_api_auto_marks_holiday(self):
        resp = self.client.post(
            "/api/roster-entries/",
            {
                "employee": self.user.id,
                "date": "2024-12-02",
                "shift": self.shift.id,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["is_holiday"] and resp.data["is_holiday_calendar"]

    def test_api_manual_override(self):
        resp = self.client.post(
            "/api/roster-entries/",
            {
                "employee": self.user.id,
                "date": "2024-12-02",
                "shift": self.shift.id,
                "is_holiday": False,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert not resp.data["is_holiday"]
        assert resp.data["is_holiday_calendar"]
