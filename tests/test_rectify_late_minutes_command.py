from datetime import date, datetime, time
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from zoneinfo import ZoneInfo

from attendance.models import AttDay, AttPair
from attendance.services import build_pairs_for, compute_att_day
from capture.models import AttendanceDevice, PunchEvent
from pagasys.models import Branch, Company, Department, Employee, RosterEntry, ShiftTemplate


class RectifyLateMinutesCommandTests(TestCase):
    def setUp(self):
        tzname = timezone.get_current_timezone_name()
        self.day = date(2024, 1, 2)
        self.company = Company.objects.create(name="C1", timezone=tzname)
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.employee = Employee.objects.create(
            username="emp",
            first_name="E",
            last_name="One",
            department=self.department,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.device = AttendanceDevice.objects.create(
            company=self.company,
            name="dev1",
            api_key="k1",
        )
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="Day",
            start_time=time(9, 0),
            end_time=time(17, 0),
            grace_in_min=0,
            grace_out_min=0,
            break_minutes=0,
        )
        RosterEntry.objects.create(employee=self.employee, date=self.day, shift=self.shift)

        self.tz = ZoneInfo(tzname)
        self.pair_patch = patch("capture.signals.pair_employee_day_task.delay")
        self.compute_patch = patch("capture.signals.compute_employee_day_task.delay")
        self.pair_patch.start()
        self.compute_patch.start()
        self.addCleanup(self.pair_patch.stop)
        self.addCleanup(self.compute_patch.stop)

    def make_legacy_state(self):
        stray_out = timezone.make_aware(
            datetime.combine(self.day, time(8, 30)),
            self.tz,
        )
        valid_in = timezone.make_aware(
            datetime.combine(self.day, time(9, 0)),
            self.tz,
        )
        valid_out = timezone.make_aware(
            datetime.combine(self.day, time(17, 0)),
            self.tz,
        )

        PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="out",
            device_ts=stray_out,
            roster_date=self.day,
            roster_fallback=False,
        )
        PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="in",
            device_ts=valid_in,
            roster_date=self.day,
            roster_fallback=False,
        )
        PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="out",
            device_ts=valid_out,
            roster_date=self.day,
            roster_fallback=False,
        )

        build_pairs_for(self.employee.id, self.day, self.shift)
        compute_att_day(self.employee.id, self.day)

        day = AttDay.objects.get(employee=self.employee, date=self.day)
        day.late_min = 45
        day.save(update_fields=["late_min"])
        return day

    def test_dry_run_reports_without_changes(self):
        original_day = self.make_legacy_state()
        output = StringIO()

        call_command(
            "rectify_late_minutes",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.day),
            "--dry-run",
            "--no-input",
            stdout=output,
        )

        refreshed = AttDay.objects.get(pk=original_day.pk)
        self.assertEqual(refreshed.late_min, 45)
        first_pair = (
            AttPair.objects.filter(employee=self.employee, date=self.day)
            .order_by("in_ts")
            .first()
        )
        self.assertIn("unpaired_out", first_pair.anomaly)
        self.assertIn("Dry run", output.getvalue())

    def test_live_run_resets_late_minutes(self):
        self.make_legacy_state()

        call_command(
            "rectify_late_minutes",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.day),
            "--no-input",
        )

        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.late_min, 0)
        self.assertEqual(day.anomalies.get("unpaired_out"), 1)
        first_pair = (
            AttPair.objects.filter(employee=self.employee, date=self.day)
            .order_by("in_ts")
            .first()
        )
        self.assertIn("unpaired_out", first_pair.anomaly)

    def test_locked_day_is_skipped(self):
        day = self.make_legacy_state()
        AttDay.objects.filter(pk=day.pk).update(locked=True)

        output = StringIO()
        call_command(
            "rectify_late_minutes",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.day),
            "--no-input",
            stdout=output,
        )

        refreshed = AttDay.objects.get(pk=day.pk)
        self.assertTrue(refreshed.locked)
        self.assertEqual(refreshed.late_min, 45)
        self.assertIn("Skipping locked day", output.getvalue())
