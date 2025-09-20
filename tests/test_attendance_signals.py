from datetime import date, time, timedelta, datetime
from unittest.mock import patch

from django.test import TransactionTestCase
from django.utils import timezone

from attendance.models import LeaveRequest, LeaveDay, AttAdjustment
from pagasys.models import (
    Company,
    Branch,
    Department,
    Employee,
    ShiftTemplate,
    RosterEntry,
    LeaveType,
)


class AttendanceSignalTests(TransactionTestCase):
    def setUp(self):
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(name="C1")
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
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )

    def test_roster_entry_save_triggers_pair_and_compute(self):
        with patch("attendance.signals.pair_employee_day_task.delay") as mock_pair, patch(
            "attendance.signals.compute_employee_day_task.delay"
        ) as mock_compute:
            RosterEntry.objects.create(
                employee=self.employee, date=self.day, shift=self.shift
            )
            day_iso = self.day.isoformat()
            mock_pair.assert_called_once_with(self.employee.id, day_iso)
            mock_compute.assert_called_once_with(self.employee.id, day_iso)

    def test_roster_entry_delete_triggers_pair_and_compute(self):
        with patch("attendance.signals.pair_employee_day_task.delay") as mock_pair, patch(
            "attendance.signals.compute_employee_day_task.delay"
        ) as mock_compute:
            entry = RosterEntry.objects.create(
                employee=self.employee, date=self.day, shift=self.shift
            )
            day_iso = self.day.isoformat()
            mock_pair.assert_called_once_with(self.employee.id, day_iso)
            mock_compute.assert_called_once_with(self.employee.id, day_iso)
            mock_pair.reset_mock()
            mock_compute.reset_mock()
            entry.delete()
            mock_pair.assert_called_once_with(self.employee.id, day_iso)
            mock_compute.assert_called_once_with(self.employee.id, day_iso)

    def test_holiday_flag_updates_trigger_compute(self):
        with patch("attendance.signals.pair_employee_day_task.delay") as mock_pair, patch(
            "attendance.signals.compute_employee_day_task.delay"
        ) as mock_compute:
            entry = RosterEntry.objects.create(
                employee=self.employee, date=self.day, shift=self.shift
            )
            day_iso = self.day.isoformat()
            mock_pair.assert_called_once_with(self.employee.id, day_iso)
            mock_compute.assert_called_once_with(self.employee.id, day_iso)
            for fields in (
                ["is_holiday"],
                ["was_holiday"],
                ["is_holiday", "was_holiday"],
            ):
                mock_pair.reset_mock()
                mock_compute.reset_mock()
                if "is_holiday" in fields:
                    entry.is_holiday = not entry.is_holiday
                if "was_holiday" in fields:
                    entry.was_holiday = not entry.was_holiday
                entry.save(update_fields=fields)
                mock_pair.assert_called_once_with(self.employee.id, day_iso)
                mock_compute.assert_called_once_with(self.employee.id, day_iso)

    @patch("attendance.signals.compute_employee_day_task.delay")
    def test_leave_day_creation_triggers_compute(self, mock_delay):
        lt = LeaveType.objects.create(company=self.company, code="AL", name="Annual")
        req = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type=lt,
            date_from=self.day,
            date_to=self.day,
            status="approved",
        )
        LeaveDay.objects.create(
            employee=self.employee,
            date=self.day,
            leave_type=lt,
            paid_pct=100,
            portion=1,
            request=req,
        )
        mock_delay.assert_called_once_with(self.employee.id, self.day.isoformat())

    @patch("attendance.signals.compute_employee_day_task.delay")
    def test_att_adjustment_save_triggers_compute(self, mock_delay):
        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            reason="Manual fix",
            created_by_id=1,
        )
        mock_delay.assert_called_once_with(self.employee.id, self.day.isoformat())

    @patch("attendance.signals.compute_employee_day_task.delay")
    def test_att_adjustment_delete_triggers_compute(self, mock_delay):
        adj = AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            reason="Manual fix",
            created_by_id=1,
        )
        mock_delay.assert_called_once_with(self.employee.id, self.day.isoformat())
        mock_delay.reset_mock()
        adj.delete()
        mock_delay.assert_called_once_with(self.employee.id, self.day.isoformat())

    @patch("attendance.signals.compute_employee_day_task.delay")
    def test_att_adjustment_update_triggers_compute(self, mock_delay):
        adj = AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day,
            reason="Manual fix",
            created_by_id=1,
        )
        mock_delay.assert_called_once_with(self.employee.id, self.day.isoformat())
        mock_delay.reset_mock()
        adj.delta_work_min = 5
        adj.save()
        mock_delay.assert_called_once_with(self.employee.id, self.day.isoformat())

    def test_punch_event_save_triggers_pair_and_compute(self):
        from capture.models import AttendanceDevice, PunchEvent
        with patch("capture.signals.pair_employee_day_task.delay") as mock_pair, \
                patch("capture.signals.compute_employee_day_task.delay") as mock_compute:
            device = AttendanceDevice.objects.create(
                company=self.company, name="dev", api_key="k"
            )
            PunchEvent.objects.create(
                device=device,
                company=self.company,
                matched_employee=self.employee,
                action="in",
                device_ts=timezone.make_aware(datetime(2024, 1, 1, 9, 0)),
            )
            day_iso = self.day.isoformat()
            mock_pair.assert_called_once_with(self.employee.id, day_iso)
            mock_compute.assert_any_call(self.employee.id, day_iso)
            mock_compute.assert_any_call(
                self.employee.id, (self.day - timedelta(days=1)).isoformat()
            )
            assert mock_compute.call_count == 2
