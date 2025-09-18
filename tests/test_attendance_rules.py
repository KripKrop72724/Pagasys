from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from zoneinfo import ZoneInfo

from attendance.services import build_pairs_for, compute_att_day
from attendance.services_helpers import active_rules
from capture.models import AttendanceDevice, PunchEvent
from pagasys.models import (
    Company,
    Branch,
    Department,
    Employee,
    ShiftTemplate,
    RosterEntry,
    ShiftRule,
)
from attendance.models import AttAdjustment, AttDay, AttPair


class AttendanceBase(TestCase):
    def setUp(self):
        active_rules.cache_clear()
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(
            name="C1", timezone=timezone.get_current_timezone_name()
        )
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
        self.device = AttendanceDevice.objects.create(
            company=self.company, name="dev1", api_key="k1"
        )
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )
        RosterEntry.objects.create(
            employee=self.employee, date=self.day, shift=self.shift
        )

    def punch(self, t: time, action="in"):
        tz = ZoneInfo(self.company.timezone)
        ts = datetime.combine(self.day, t, tzinfo=tz)
        return PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action=action,
            device_ts=ts,
            roster_date=self.day,
        )

    def compute(self):
        build_pairs_for(self.employee.id, self.day)
        compute_att_day(self.employee.id, self.day)
        return self.employee.att_days.get(date=self.day)


class AutoEventSequenceAnomalyTests(AttendanceBase):
    def test_in_auto_out_yields_unpaired_out(self):
        self.punch(time(9, 0), "in")
        self.punch(time(12, 0), "auto")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.anomalies.get("unpaired_out"), 1)

    def test_duplicate_in_triggers_missing_out_closed(self):
        self.punch(time(9, 0), "in")
        self.punch(time(10, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.anomalies.get("missing_out_closed_at_next_in"), 1)
        self.assertNotIn("unpaired_out", day.anomalies)

    def test_quick_duplicate_in_punch_creates_exception(self):
        first = self.punch(time(9, 0, 0), "in")
        dup = self.punch(time(9, 0, 30), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.anomalies, {})
        pair = self.employee.att_pairs.get()
        self.assertEqual(pair.in_event_id, first.id)
        dup.refresh_from_db()
        self.assertEqual(dup.exception.kind, "duplicate")

    def test_quick_duplicate_out_punch_creates_exception(self):
        self.punch(time(9, 0), "in")
        out = self.punch(time(17, 0), "out")
        dup = self.punch(time(17, 0, 30), "out")
        day = self.compute()
        self.assertEqual(day.anomalies, {})
        pair = self.employee.att_pairs.get()
        self.assertEqual(pair.out_event_id, out.id)
        dup.refresh_from_db()
        self.assertEqual(dup.exception.kind, "duplicate")

    def test_stray_out_only_sets_unpaired_out(self):
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.anomalies.get("unpaired_out"), 1)


class AutoClosureRegressionTests(AttendanceBase):
    def test_auto_closed_missing_out_exclusive_and_no_work(self):
        self.punch(time(16, 50), "in")
        build_pairs_for(self.employee.id, self.day, self.shift)
        compute_att_day(self.employee.id, self.day)
        day = self.employee.att_days.get(date=self.day)
        self.assertEqual(day.work_min, 0)
        self.assertEqual(day.anomalies.get("auto_close_min"), 10)
        self.assertNotIn("missing_out", day.anomalies)

        compute_att_day(self.employee.id, self.day)
        day.refresh_from_db()
        self.assertEqual(day.work_min, 0)
        self.assertEqual(day.anomalies.get("auto_close_min"), 10)
        self.assertNotIn("missing_out", day.anomalies)


class AbsentDayCreationTests(AttendanceBase):
    def test_no_roster_no_punches_creates_no_day(self):
        RosterEntry.objects.filter(employee=self.employee, date=self.day).delete()
        compute_att_day(self.employee.id, self.day)
        self.assertFalse(
            AttDay.objects.filter(employee=self.employee, date=self.day).exists()
        )

    def test_rostered_no_punches_mark_absent(self):
        compute_att_day(self.employee.id, self.day)
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.status, "absent")


class AfterShiftPunchTests(AttendanceBase):
    def test_post_shift_in_is_unpaired_out(self):
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        self.punch(time(19, 0), "in")
        build_pairs_for(self.employee.id, self.day, self.shift)
        compute_att_day(self.employee.id, self.day)
        day = self.employee.att_days.get(date=self.day)
        self.assertEqual(day.work_min, 8 * 60)
        self.assertEqual(day.anomalies.get("unpaired_out"), 1)
        self.assertNotIn("auto_close_min", day.anomalies)
        self.assertEqual(
            AttPair.objects.filter(
                employee=self.employee, date=self.day, out_ts__isnull=True
            ).count(),
            0,
        )


class ActiveRuleResolutionTests(AttendanceBase):
    def test_resolution_filters(self):
        active_rules.cache_clear()
        rule = ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.MAX_DAILY_HOURS,
            value="480",
            active_from=self.day,
            active_to=self.day,
            weekdays="MON",
        )
        rules = active_rules(self.shift, self.day)
        self.assertIn(rule, rules[ShiftRule.Kind.MAX_DAILY_HOURS])
        active_rules.cache_clear()
        rules = active_rules(self.shift, self.day + timedelta(days=1))
        self.assertNotIn(ShiftRule.Kind.MAX_DAILY_HOURS, rules)
        active_rules.cache_clear()
        rules = active_rules(self.shift, self.day - timedelta(days=1))
        self.assertNotIn(ShiftRule.Kind.MAX_DAILY_HOURS, rules)

    def test_no_shift_returns_empty(self):
        active_rules.cache_clear()
        self.assertEqual(active_rules(None, self.day), {})


class BreakRuleTests(AttendanceBase):
    def test_fixed_break_window_auto_deduct(self):
        rule = ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.FIXED_BREAK_WINDOW,
            value="12:00-13:00",
            params={"paid": False, "enforcement": "auto_deduct", "min_minutes": 30},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.unpaid_break_min, 30)
        self.assertEqual(day.anomalies.get(f"break_auto_deduct_{rule.id}"), 30)

    def test_paid_break_window_tracked(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.PAID_BREAK_WINDOW,
            value="15:00-15:15",
            params={"paid": True, "enforcement": "warn"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.paid_break_min, 15)

    def test_required_break_after_consecutive(self):
        rule = ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE,
            value="240",
            params={"minutes": 30, "paid": False, "enforcement": "auto_deduct"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(15, 0), "out")
        day = self.compute()
        self.assertEqual(day.unpaid_break_min, 30)
        self.assertEqual(day.anomalies.get(f"break_auto_deduct_{rule.id}"), 30)

    def test_min_total_break_per_day(self):
        rule = ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.MIN_TOTAL_BREAK_PER_DAY,
            value="60",
            params={"paid": False, "enforcement": "auto_deduct"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.unpaid_break_min, 60)
        self.assertEqual(day.anomalies.get(f"break_auto_deduct_{rule.id}"), 60)

    def test_fixed_break_window_cross_midnight(self):
        self.shift.start_time = time(22, 0)
        self.shift.end_time = time(6, 0)
        self.shift.cross_midnight = True
        self.shift.save()
        roster = self.employee.roster_entries.get(date=self.day)
        roster.shift = self.shift
        roster.save()
        rule = ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.FIXED_BREAK_WINDOW,
            value="23:00-01:00",
            params={"paid": False, "enforcement": "auto_deduct", "min_minutes": 30},
        )
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(self.day, time(22, 0)), tz)
        out_ts = timezone.make_aware(
            datetime.combine(self.day + timedelta(days=1), time(6, 0)), tz
        )
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
        day = self.compute()
        self.assertEqual(day.unpaid_break_min, 30)

    def test_paid_break_windows_overlap_no_double(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.PAID_BREAK_WINDOW,
            value="10:00-11:00",
            params={"paid": True, "enforcement": "warn"},
        )
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.PAID_BREAK_WINDOW,
            value="10:30-11:30",
            params={"paid": True, "enforcement": "warn"},
        )
        self.punch(time(10, 0), "in")
        self.punch(time(12, 0), "out")
        day = self.compute()
        self.assertEqual(day.paid_break_min, 90)


class OvertimeTests(AttendanceBase):
    def test_regular_overtime(self):
        self.punch(time(9, 0), "in")
        self.punch(time(18, 0), "out")
        day = self.compute()
        self.assertEqual(day.work_min, 480)
        self.assertEqual(day.ot_regular_min, 60)

    def test_rest_day_all_ot(self):
        roster = self.employee.roster_entries.get(date=self.day)
        roster.is_rest_day = True
        roster.save()
        self.punch(time(9, 0), "in")
        self.punch(time(10, 0), "out")
        day = self.compute()
        self.assertEqual(day.work_min, 0)
        self.assertEqual(day.ot_regular_min, 60)

    def test_holiday_ot(self):
        roster = self.employee.roster_entries.get(date=self.day)
        roster.is_holiday = True
        roster.save()
        self.punch(time(9, 0), "in")
        self.punch(time(10, 0), "out")
        day = self.compute()
        self.assertEqual(day.ot_holiday_min, 60)
        self.assertEqual(day.work_min, 0)

    def test_boundary_no_ot(self):
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.ot_regular_min, 0)

    def test_night_overtime(self):
        self.shift.start_time = time(20, 0)
        self.shift.end_time = time(4, 0)
        self.shift.cross_midnight = True
        self.shift.save()
        roster = self.employee.roster_entries.get(date=self.day)
        roster.shift = self.shift
        roster.save()
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="22:00-06:00",
        )
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(self.day, time(20, 0)), tz)
        out_ts = timezone.make_aware(
            datetime.combine(self.day + timedelta(days=1), time(2, 0)), tz
        )
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
        day = self.compute()
        self.assertEqual(day.ot_night_min, 240)

    def test_holiday_overrides_night(self):
        roster = self.employee.roster_entries.get(date=self.day)
        roster.is_holiday = True
        roster.save()
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="00:00-23:59",
        )
        self.punch(time(9, 0), "in")
        self.punch(time(10, 0), "out")
        day = self.compute()
        self.assertEqual(day.ot_holiday_min, 60)
        self.assertEqual(day.ot_night_min, 0)

    def test_rounding_after_classification(self):
        self.shift.rounding_min = 15
        self.shift.save()
        self.punch(time(9, 0), "in")
        self.punch(time(17, 10), "out")
        day = self.compute()
        self.assertEqual(day.work_min, 480)
        self.assertEqual(day.ot_regular_min, 15)


class RamadanReductionTests(AttendanceBase):
    def test_ramadan_reduction_affects_requirement(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.RAMADAN_REDUCE_MINUTES,
            value="60",
            params={"enforcement": "warn"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.ot_regular_min, 60)

    def test_ramadan_reduction_allows_early_leave_without_penalty(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.RAMADAN_REDUCE_MINUTES,
            value="60",
            params={"enforcement": "warn"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(16, 0), "out")
        day = self.compute()
        self.assertEqual(day.early_leave_min, 0)
        self.assertEqual(day.status, "present")
        self.assertEqual(day.work_min, 420)

    def test_ramadan_reduction_marks_partial_when_under_requirement(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.RAMADAN_REDUCE_MINUTES,
            value="60",
            params={"enforcement": "warn"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(15, 0), "out")
        day = self.compute()
        self.assertEqual(day.early_leave_min, 60)
        self.assertEqual(day.status, "partial")
        self.assertEqual(day.work_min, 360)

    def test_ramadan_reduction_does_not_change_late(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.RAMADAN_REDUCE_MINUTES,
            value="60",
            params={"enforcement": "warn"},
        )
        self.punch(time(9, 30), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertEqual(day.late_min, 30)
        self.assertEqual(day.early_leave_min, 0)
        self.assertEqual(day.status, "present")


class MaxDailyHoursTests(AttendanceBase):
    def test_max_daily_hours_spill(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.MAX_DAILY_HOURS,
            value="600",
            params={"enforcement": "warn"},
        )
        self.punch(time(9, 0), "in")
        self.punch(time(21, 0), "out")
        day = self.compute()
        self.assertEqual(day.anomalies.get("overtime_over_cap"), 120)
        self.assertEqual(day.work_min, 360)
        self.assertEqual(day.ot_regular_min, 360)

    def test_max_daily_hours_boundary(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.MAX_DAILY_HOURS,
            value="480",
        )
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        self.assertIsNone(day.anomalies.get("overtime_over_cap"))
        self.assertEqual(day.work_min, 480)


class AdjustmentTests(AttendanceBase):
    def test_manual_adjustment_applied(self):
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        self.compute()
        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            delta_work_min=30,
            reason="add",
            created_by_id=1,
        )
        day = self.compute()
        self.assertEqual(day.work_min, 510)
        self.assertTrue(day.anomalies.get("manual_adjustments_applied"))

    def test_adjustment_rejected_when_locked(self):
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        day = self.compute()
        day.locked = True
        day.save()
        with self.assertRaises(ValidationError):
            AttAdjustment.objects.create(
                employee=self.employee,
                date=self.day,
                delta_work_min=30,
                reason="add",
                created_by_id=1,
            )
        self.assertEqual(AttAdjustment.objects.count(), 0)
        day = self.compute()
        self.assertEqual(day.work_min, 480)
        self.assertFalse(day.anomalies.get("manual_adjustments_applied"))

    def test_adjustment_status_override(self):
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        self.compute()
        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            delta_work_min=0,
            override_status="leave",
            reason="override",
            created_by_id=1,
        )
        day = self.compute()
        self.assertEqual(day.status, "leave")
        self.assertTrue(day.anomalies.get("manual_adjustments_applied"))

    def test_adjustment_without_override_updates_status(self):
        day = self.compute()
        self.assertEqual(day.status, "absent")

        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            delta_work_min=8 * 60,
            reason="make_present",
            created_by_id=1,
        )

        day = self.compute()
        self.assertEqual(day.status, "present")
        self.assertEqual(day.work_min, 8 * 60)
        self.assertTrue(day.anomalies.get("manual_adjustments_applied"))

    def test_adjustment_idempotent(self):
        self.punch(time(9, 0), "in")
        self.punch(time(17, 0), "out")
        self.compute()
        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            delta_work_min=30,
            reason="add",
            created_by_id=1,
        )
        day1 = self.compute()
        day2 = self.compute()
        self.assertEqual(day1.work_min, day2.work_min)


class ManualPairApiTests(TestCase):
    def setUp(self):
        from django.core.management import call_command
        from django.contrib.auth.models import Group
        from rest_framework.test import APIClient

        active_rules.cache_clear()
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(name="C1")
        branch = Branch.objects.create(company=self.company, name="B1")
        dept = Department.objects.create(branch=branch, name="D1")
        self.employee = Employee.objects.create_user(
            username="emp",
            password="pass",
            department=dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_authenticate(self.employee)
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )
        RosterEntry.objects.create(
            employee=self.employee, date=self.day, shift=self.shift
        )
        self.url = f"/api/companies/{self.company.id}/att-pairs/"

    def test_create_manual_pair_recomputes_day(self):
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(self.day, time(9, 0)), tz)
        out_ts = timezone.make_aware(datetime.combine(self.day, time(17, 0)), tz)
        payload = {
            "employee": self.employee.id,
            "date": str(self.day),
            "in_ts": in_ts.isoformat(),
            "out_ts": out_ts.isoformat(),
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 201)
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.work_min, 480)
        self.assertEqual(resp.data["source"], "manual")
