from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase, RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from attendance.admin import AttDayAdmin
from attendance.models import AttDay, AttPair
from attendance.services import build_pairs_for, compute_att_day
from pagasys.models import Company, Branch, Department, Employee
from capture.models import AttendanceDevice, PunchEvent
from attendance.views import MAX_RANGE_DAYS, MAX_EMPLOYEES


class BaseSetup(TestCase):
    def setUp(self):
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.dept = Department.objects.create(branch=self.branch, name="D1")
        self.emp = Employee.objects.create(
            username="emp1",
            first_name="E1",
            last_name="One",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.emp2 = Employee.objects.create(
            username="emp2",
            first_name="E2",
            last_name="Two",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.admin_user = Employee.objects.create(
            username="admin",
            first_name="Ad",
            last_name="Min",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
            is_superuser=True,
        )


class ManualRecomputeActionTests(BaseSetup):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.admin = AttDayAdmin(AttDay, admin.sites.AdminSite())

    @patch("attendance.admin.recompute_range_task.delay")
    def test_valid_manual_recompute(self, mock_delay):
        req = self.factory.post(
            "/admin/", {
                "post": "yes",
                "start": "2024-01-01",
                "end": "2024-01-02",
                "employee_ids": str(self.emp.id),
            }
        )
        req.user = self.admin_user
        req.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, "_messages", FallbackStorage(req))
        response = self.admin.manual_recompute(req, AttDay.objects.none())
        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with([self.emp.id], "2024-01-01", "2024-01-02")

    @patch("attendance.admin.recompute_range_task.delay")
    def test_invalid_range_rejected(self, mock_delay):
        req = self.factory.post(
            "/admin/", {
                "post": "yes",
                "start": "2024-01-01",
                "end": "2024-02-15",  # exceeds limit
            }
        )
        req.user = self.admin_user
        req.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, "_messages", FallbackStorage(req))
        self.admin.manual_recompute(req, AttDay.objects.none())
        mock_delay.assert_not_called()


class RebuildApiActionTests(BaseSetup):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)
        self.url = f"/api/companies/{self.company.id}/att-pairs/rebuild/"

    @patch("attendance.views.pair_employee_day_task.delay")
    @patch("attendance.views.compute_employee_day_task.delay")
    def test_rebuild_happy_path(self, mock_compute, mock_pair):
        resp = self.client.post(
            self.url,
            {
                "employee_ids": [self.emp.id],
                "start": "2024-01-01",
                "end": "2024-01-02",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_pair.call_count, 2)
        self.assertEqual(mock_compute.call_count, 2)

    def test_rebuild_invalid_dates(self):
        resp = self.client.post(
            self.url,
            {"employee_ids": [self.emp.id], "start": "2024-02-01", "end": "2024-01-01"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_rebuild_nonexistent_employee(self):
        resp = self.client.post(
            self.url,
            {"employee_ids": [999], "start": "2024-01-01", "end": "2024-01-02"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_rebuild_excessive_range(self):
        end = (self.day + timedelta(days=MAX_RANGE_DAYS + 1)).isoformat()
        resp = self.client.post(
            self.url,
            {"employee_ids": [self.emp.id], "start": "2024-01-01", "end": end},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class EdgeCaseServiceTests(BaseSetup):
    def test_cross_midnight_pairs(self):
        device = AttendanceDevice.objects.create(company=self.company, name="d", api_key="k")
        tz = timezone.get_current_timezone()
        PunchEvent.objects.create(
            device=device,
            company=self.company,
            employee=self.emp,
            matched_employee=self.emp,
            action="in",
            device_ts=timezone.make_aware(datetime.combine(self.day, time(23, 0)), tz),
            roster_date=self.day,
        )
        PunchEvent.objects.create(
            device=device,
            company=self.company,
            employee=self.emp,
            matched_employee=self.emp,
            action="out",
            device_ts=timezone.make_aware(datetime.combine(self.day + timedelta(days=1), time(1, 0)), tz),
            roster_date=self.day,
        )
        build_pairs_for(self.emp.id, self.day)
        pair = AttPair.objects.get(employee=self.emp, date=self.day)
        self.assertTrue(pair.cross_midnight)

    def test_locked_day_skips_compute(self):
        AttDay.objects.create(employee=self.emp, date=self.day, locked=True)
        self.assertEqual(build_pairs_for(self.emp.id, self.day), 0)
        self.assertEqual(compute_att_day(self.emp.id, self.day), 0)
        self.assertEqual(AttPair.objects.count(), 0)
