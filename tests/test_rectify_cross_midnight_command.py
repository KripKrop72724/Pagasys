from datetime import date, datetime, time, timedelta
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


class RectifyCrossMidnightCommandTests(TestCase):
    def setUp(self):
        tzname = timezone.get_current_timezone_name()
        self.day = date(2024, 1, 1)
        self.next_day = self.day + timedelta(days=1)
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
            name="Night",
            start_time=time(22, 0),
            end_time=time(6, 0),
            cross_midnight=True,
            break_minutes=0,
        )
        RosterEntry.objects.create(employee=self.employee, date=self.day, shift=self.shift)
        RosterEntry.objects.create(employee=self.employee, date=self.next_day, shift=self.shift)

        self.tz = ZoneInfo(tzname)
        self.pair_patch = patch("capture.signals.pair_employee_day_task.delay")
        self.compute_patch = patch("capture.signals.compute_employee_day_task.delay")
        self.pair_patch.start()
        self.compute_patch.start()
        self.addCleanup(self.pair_patch.stop)
        self.addCleanup(self.compute_patch.stop)

    def make_legacy_state(self):
        in_dt = datetime.combine(self.day, time(22, 0), tzinfo=self.tz)
        out_dt = datetime.combine(self.next_day, time(7, 0), tzinfo=self.tz)
        in_event = PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="in",
            device_ts=in_dt,
            roster_date=self.day,
            roster_fallback=False,
        )
        out_event = PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action="out",
            device_ts=out_dt,
            roster_date=self.next_day,
            roster_fallback=True,
        )
        build_pairs_for(self.employee.id, self.day, self.shift)
        compute_att_day(self.employee.id, self.day)
        build_pairs_for(self.employee.id, self.next_day, self.shift)
        compute_att_day(self.employee.id, self.next_day)
        return in_event, out_event

    def test_dry_run_reports_without_changes(self):
        self.make_legacy_state()
        before_pairs_day1 = list(
            AttPair.objects.filter(employee=self.employee, date=self.day)
            .order_by("id")
            .values_list("in_event_id", "out_event_id")
        )
        before_pairs_day2 = list(
            AttPair.objects.filter(employee=self.employee, date=self.next_day)
            .order_by("id")
            .values_list("in_event_id", "out_event_id")
        )
        day_two_before = AttDay.objects.get(employee=self.employee, date=self.next_day)
        self.assertIn("unpaired_out", day_two_before.anomalies)

        output = StringIO()
        call_command(
            "rectify_cross_midnight",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.next_day),
            "--dry-run",
            "--no-input",
            stdout=output,
        )

        self.assertIn("Dry run", output.getvalue())
        after_pairs_day1 = list(
            AttPair.objects.filter(employee=self.employee, date=self.day)
            .order_by("id")
            .values_list("in_event_id", "out_event_id")
        )
        after_pairs_day2 = list(
            AttPair.objects.filter(employee=self.employee, date=self.next_day)
            .order_by("id")
            .values_list("in_event_id", "out_event_id")
        )
        self.assertEqual(before_pairs_day1, after_pairs_day1)
        self.assertEqual(before_pairs_day2, after_pairs_day2)
        day_two_after = AttDay.objects.get(employee=self.employee, date=self.next_day)
        self.assertEqual(day_two_after.anomalies, day_two_before.anomalies)

    def test_live_run_rectifies_and_rebuilds(self):
        in_event, out_event = self.make_legacy_state()

        call_command(
            "rectify_cross_midnight",
            "--start-date",
            str(self.day),
            "--end-date",
            str(self.next_day),
            "--no-input",
        )

        out_event.refresh_from_db()
        self.assertEqual(out_event.roster_date, self.day)
        self.assertFalse(out_event.roster_fallback)

        pairs_day1 = AttPair.objects.filter(employee=self.employee, date=self.day).order_by("in_ts")
        self.assertEqual(pairs_day1.count(), 1)
        pair = pairs_day1.first()
        self.assertEqual(pair.in_event_id, in_event.id)
        self.assertEqual(pair.out_event_id, out_event.id)

        day_one = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day_one.work_min, 8 * 60)
        self.assertEqual(day_one.ot_regular_min, 60)
        self.assertNotIn("unpaired_out", day_one.anomalies)

        pairs_day2 = AttPair.objects.filter(employee=self.employee, date=self.next_day)
        self.assertFalse(pairs_day2.exists())
        day_two = AttDay.objects.get(employee=self.employee, date=self.next_day)
        self.assertNotIn("unpaired_out", day_two.anomalies)
