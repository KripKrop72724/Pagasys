from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from zoneinfo import ZoneInfo

from attendance.models import AttPair, AttDay
from attendance.services import compute_att_day
from capture.models import AttendanceDevice, PunchEvent, PunchException
from pagasys.models import Company, Branch, Department, Employee, ShiftTemplate, RosterEntry


class FixDuplicatePairsCommandTests(TestCase):
    def setUp(self):
        self.day = date(2024, 1, 1)
        tzname = timezone.get_current_timezone_name()
        self.company = Company.objects.create(name="C1", timezone=tzname)
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.dept = Department.objects.create(branch=self.branch, name="D1")
        self.employee = Employee.objects.create(
            username="emp",
            first_name="E",
            last_name="One",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.device = AttendanceDevice.objects.create(company=self.company, name="dev1", api_key="k1")
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )
        RosterEntry.objects.create(employee=self.employee, date=self.day, shift=self.shift)
        self.tz = ZoneInfo(tzname)

    def make_legacy(self):
        first_ts = datetime.combine(self.day, time(9, 0), tzinfo=self.tz)
        dup_ts = first_ts + timedelta(seconds=30)
        out_ts = datetime.combine(self.day, time(17, 0), tzinfo=self.tz)
        with patch("capture.signals.pair_employee_day_task.delay"), patch(
            "capture.signals.compute_employee_day_task.delay"
        ):
            first = PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                employee=self.employee,
                matched_employee=self.employee,
                action="in",
                device_ts=first_ts,
                roster_date=self.day,
            )
            dup = PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                employee=self.employee,
                matched_employee=self.employee,
                action="in",
                device_ts=dup_ts,
                roster_date=self.day,
            )
            out = PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                employee=self.employee,
                matched_employee=self.employee,
                action="out",
                device_ts=out_ts,
                roster_date=self.day,
            )
        AttPair.objects.create(
            employee=self.employee,
            date=self.day,
            in_event_id=first.id,
            out_event_id=dup.id,
            in_ts=first_ts,
            out_ts=dup_ts,
            duration_min=0,
            anomaly={},
        )
        duration = int((out_ts - dup_ts).total_seconds() // 60)
        AttPair.objects.create(
            employee=self.employee,
            date=self.day,
            in_event_id=dup.id,
            out_event_id=out.id,
            in_ts=dup_ts,
            out_ts=out_ts,
            duration_min=duration,
            anomaly={},
        )
        compute_att_day(self.employee.id, self.day)
        return first, dup, out

    def test_dry_run_makes_no_changes(self):
        first, dup, out = self.make_legacy()
        initial_pairs = list(AttPair.objects.filter(employee=self.employee, date=self.day))
        initial_day = AttDay.objects.get(employee=self.employee, date=self.day)

        call_command(
            "fix_duplicate_pairs",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.day),
            "--dry-run",
            "--no-input",
        )

        self.assertFalse(PunchException.objects.exists())
        pairs = list(AttPair.objects.filter(employee=self.employee, date=self.day))
        self.assertEqual(len(pairs), len(initial_pairs))
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.work_min, initial_day.work_min)

    def test_live_run_flags_duplicates_and_rebuilds(self):
        first, dup, out = self.make_legacy()
        call_command(
            "fix_duplicate_pairs",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.day),
            "--no-input",
        )
        dup.refresh_from_db()
        self.assertEqual(dup.exception.kind, "duplicate")
        pairs = AttPair.objects.filter(employee=self.employee, date=self.day).order_by("in_ts")
        self.assertEqual(pairs.count(), 1)
        pair = pairs.first()
        self.assertEqual(pair.in_event_id, first.id)
        self.assertEqual(pair.out_event_id, out.id)
        self.assertEqual(pair.duration_min, 480)
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.work_min, 480)
