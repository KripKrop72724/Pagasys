from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from attendance.tasks import recompute_recent_task
from pagasys.models import Company, Branch, Department, Employee
from capture.models import AttendanceDevice, PunchEvent


class RecomputeRecentTaskTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.dept = Department.objects.create(branch=self.branch, name="D1")
        self.emp1 = Employee.objects.create(
            username="e1",
            first_name="E1",
            last_name="One",
            department=self.dept,
            hire_date=self.now.date(),
            employment_type="permanent",
            visa_type="personal",
        )
        self.emp2 = Employee.objects.create(
            username="e2",
            first_name="E2",
            last_name="Two",
            department=self.dept,
            hire_date=self.now.date(),
            employment_type="permanent",
            visa_type="personal",
        )
        self.device = AttendanceDevice.objects.create(
            company=self.company, name="dev", api_key="k"
        )

    @patch("attendance.tasks.build_pairs_for")
    @patch("attendance.tasks.compute_att_day", return_value=1)
    def test_processes_distinct_recent_punches(self, mock_compute, mock_pairs):
        with patch("attendance.tasks.timezone.now", return_value=self.now), \
            patch("capture.signals.pair_employee_day_task.delay"), \
            patch("capture.signals.compute_employee_day_task.delay"):
            # two punches for emp1 same day -> deduped
            PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                matched_employee=self.emp1,
                action="in",
                device_ts=self.now - timedelta(minutes=1),
                roster_date=self.now.date(),
            )
            PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                matched_employee=self.emp1,
                action="out",
                device_ts=self.now - timedelta(minutes=2),
                roster_date=self.now.date(),
            )
            # punch for emp2 -> processed separately
            PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                matched_employee=self.emp2,
                action="in",
                device_ts=self.now - timedelta(minutes=3),
                roster_date=self.now.date(),
            )
            total = recompute_recent_task(minutes=5)
        self.assertEqual(mock_pairs.call_count, 2)
        self.assertEqual(mock_compute.call_count, 2)
        self.assertEqual(total, 2)

    @patch("attendance.tasks.build_pairs_for")
    @patch("attendance.tasks.compute_att_day")
    def test_skips_old_or_unmatched_punches(self, mock_compute, mock_pairs):
        with patch("attendance.tasks.timezone.now", return_value=self.now), \
            patch("capture.signals.pair_employee_day_task.delay"), \
            patch("capture.signals.compute_employee_day_task.delay"):
            # unmatched employee -> ignored
            PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                matched_employee=None,
                action="in",
                device_ts=self.now - timedelta(minutes=1),
                roster_date=self.now.date(),
            )
            # punch older than cutoff -> ignored
            PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                matched_employee=self.emp1,
                action="in",
                device_ts=self.now - timedelta(minutes=10),
                roster_date=self.now.date(),
            )
            recompute_recent_task(minutes=5)
        mock_pairs.assert_not_called()
        mock_compute.assert_not_called()

    @patch("attendance.tasks.build_pairs_for")
    @patch("attendance.tasks.compute_att_day")
    def test_uses_localdate_for_missing_roster_date(self, mock_compute, mock_pairs):
        with patch("attendance.tasks.timezone.now", return_value=self.now), \
            patch("attendance.tasks.localdate", return_value=self.now.date()), \
            patch("capture.signals.pair_employee_day_task.delay"), \
            patch("capture.signals.compute_employee_day_task.delay"):
            PunchEvent.objects.create(
                device=self.device,
                company=self.company,
                matched_employee=self.emp1,
                action="in",
                device_ts=self.now - timedelta(minutes=1),
                roster_date=None,
            )
            recompute_recent_task(minutes=5)
        mock_pairs.assert_called_once_with(self.emp1.id, self.now.date())
        mock_compute.assert_called_once_with(self.emp1.id, self.now.date())


class BeatScheduleTests(SimpleTestCase):
    def test_minutely_recompute_entry(self):
        entry = settings.CELERY_BEAT_SCHEDULE.get("attendance-minutely-recompute")
        assert entry is not None
        self.assertEqual(entry["task"], "attendance.tasks.recompute_recent_task")
        self.assertEqual(entry["schedule"], 60.0)
