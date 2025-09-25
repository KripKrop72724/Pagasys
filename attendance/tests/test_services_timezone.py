from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo as StdZoneInfo
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from attendance.services import build_pairs_for, compute_att_day
from capture.models import AttendanceDevice, PunchEvent
from pagasys.models import Branch, Company, Department, Employee


class AttendanceServiceTimezoneTests(TestCase):
    def setUp(self) -> None:
        self.company = Company.objects.create(name="AssignmentCo", timezone="Asia/Dubai")
        self.branch = Branch.objects.create(company=self.company, name="HQ")
        self.department = Department.objects.create(branch=self.branch, name="Ops")
        self.pair_patcher = patch("capture.signals.pair_employee_day_task.delay")
        self.compute_patcher = patch("capture.signals.compute_employee_day_task.delay")
        self.addCleanup(self.pair_patcher.stop)
        self.addCleanup(self.compute_patcher.stop)
        self.pair_patcher.start()
        self.compute_patcher.start()
        self.device = AttendanceDevice.objects.create(
            company=self.company,
            name="Device",
            api_key="device-key",
            branch=self.branch,
        )
        self.employee = Employee.objects.create_user(
            username="worker",
            password="pass",
            department=self.department,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
        )
        self.day = date(2024, 6, 1)
        in_ts = timezone.make_aware(datetime(2024, 6, 1, 4, 0), dt_timezone.utc)
        out_ts = timezone.make_aware(datetime(2024, 6, 1, 12, 0), dt_timezone.utc)
        PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="in",
            device_ts=in_ts,
            roster_date=self.day,
        )
        PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="out",
            device_ts=out_ts,
            roster_date=self.day,
        )

    def test_build_pairs_uses_assignment_company_timezone(self) -> None:
        with patch("attendance.services.ZoneInfo") as zoneinfo_mock:
            zoneinfo_mock.side_effect = lambda value: StdZoneInfo(value)
            build_pairs_for(self.employee.id, self.day)
        zoneinfo_mock.assert_called_with(self.company.timezone)

    def test_compute_day_uses_assignment_company_timezone(self) -> None:
        build_pairs_for(self.employee.id, self.day)
        with patch("attendance.services.ZoneInfo") as zoneinfo_mock:
            zoneinfo_mock.side_effect = lambda value: StdZoneInfo(value)
            compute_att_day(self.employee.id, self.day)
        zoneinfo_mock.assert_called_with(self.company.timezone)
