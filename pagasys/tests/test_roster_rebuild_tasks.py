from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase, RequestFactory

from rest_framework.test import APIClient

from pagasys.admin import RosterEntryAdmin, RosterEntryRangeForm
from pagasys.models import (
    Branch,
    Company,
    Department,
    Employee,
    RosterEntry,
    ShiftTemplate,
    TradeLicense,
)


class RosterRebuildSchedulingTests(TransactionTestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.factory = RequestFactory()
        self.client = APIClient()
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date=date(2024, 1, 1),
            expiry_date=date(2099, 1, 1),
            max_visas=5,
        )
        self.license.branches.set([self.branch])
        self.admin_user = Employee.objects.create_user(
            username="admin",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="company",
            is_staff=True,
            is_superuser=True,
        )
        self.other_employee = Employee.objects.create_user(
            username="e2",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="company",
        )
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )
        self.admin = RosterEntryAdmin(RosterEntry, admin.sites.AdminSite())
        company_admin = Group.objects.get(name="Company Admin")
        self.admin_user.groups.add(company_admin)
        self.client.force_authenticate(self.admin_user)

    def _make_request(self, data):
        req = self.factory.post("/admin/", data)
        req.user = self.admin_user
        req.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage

        setattr(req, "_messages", FallbackStorage(req))
        return req

    def test_admin_bulk_range_enqueues_rebuilds(self):
        start = date(2024, 7, 1)
        with patch("attendance.signals.pair_employee_day_task.delay"), patch(
            "attendance.signals.compute_employee_day_task.delay"
        ):
            RosterEntry.objects.create(
                employee=self.admin_user, date=start, shift=self.shift
            )

        form_data = {
            "branch": self.branch.id,
            "shift": self.shift.id,
            "date": start.isoformat(),
            "repeat_days": 2,
        }
        form = RosterEntryRangeForm(data=form_data, instance=RosterEntry())
        assert form.is_valid()
        obj = form.save(commit=False)
        req = self._make_request(form_data)

        with patch("pagasys.admin.ASYNC_BULK_THRESHOLD", 10), patch(
            "pagasys.admin.pair_employee_day_task.delay"
        ) as mock_pair, patch(
            "pagasys.admin.compute_employee_day_task.delay"
        ) as mock_compute:
            self.admin.save_model(req, obj, form, False)

        expected = {
            (self.admin_user.id, start),
            (self.admin_user.id, start + timedelta(days=1)),
            (self.other_employee.id, start),
            (self.other_employee.id, start + timedelta(days=1)),
        }
        called_pairs = {
            (call.args[0], date.fromisoformat(call.args[1]))
            for call in mock_pair.call_args_list
        }
        self.assertSetEqual(called_pairs, expected)
        self.assertEqual(mock_pair.call_count, len(expected))
        self.assertEqual(mock_compute.call_count, len(expected))

    def test_bulk_upsert_enqueues_rebuilds(self):
        start = date(2024, 8, 1)
        payload = {
            "entries": [
                {"employee": self.admin_user.id, "date": start.isoformat(), "shift": self.shift.id},
                {
                    "employee": self.admin_user.id,
                    "date": (start + timedelta(days=1)).isoformat(),
                    "shift": self.shift.id,
                },
            ]
        }

        with patch(
            "pagasys.policy.views.pair_employee_day_task.delay"
        ) as mock_pair, patch(
            "pagasys.policy.views.compute_employee_day_task.delay"
        ) as mock_compute:
            resp = self.client.post(
                f"/api/companies/{self.company.id}/roster/bulk-upsert/",
                payload,
                format="json",
            )

        self.assertEqual(resp.status_code, 200, resp.data)
        expected = {
            (self.admin_user.id, start),
            (self.admin_user.id, start + timedelta(days=1)),
        }
        called_pairs = {
            (call.args[0], date.fromisoformat(call.args[1]))
            for call in mock_pair.call_args_list
        }
        self.assertSetEqual(called_pairs, expected)
        self.assertEqual(mock_pair.call_count, len(expected))
        self.assertEqual(mock_compute.call_count, len(expected))

    def test_schedule_range_sync_enqueues_rebuilds(self):
        start = date(2024, 9, 1)
        with patch("attendance.signals.pair_employee_day_task.delay"), patch(
            "attendance.signals.compute_employee_day_task.delay"
        ):
            RosterEntry.objects.create(
                employee=self.admin_user, date=start, shift=self.shift
            )

        payload = {
            "employees": [self.admin_user.id],
            "shift": self.shift.id,
            "start_date": start.isoformat(),
            "days": 2,
        }

        with patch("pagasys.policy.views.ASYNC_BULK_THRESHOLD", 99), patch(
            "pagasys.policy.views.pair_employee_day_task.delay"
        ) as mock_pair, patch(
            "pagasys.policy.views.compute_employee_day_task.delay"
        ) as mock_compute:
            resp = self.client.post(
                f"/api/companies/{self.company.id}/roster/schedule-range/",
                payload,
                format="json",
            )

        self.assertEqual(resp.status_code, 200, resp.data)
        expected = {
            (self.admin_user.id, start),
            (self.admin_user.id, start + timedelta(days=1)),
        }
        called_pairs = {
            (call.args[0], date.fromisoformat(call.args[1]))
            for call in mock_pair.call_args_list
        }
        self.assertSetEqual(called_pairs, expected)
        self.assertEqual(mock_pair.call_count, len(expected))
        self.assertEqual(mock_compute.call_count, len(expected))

    def test_schedule_range_async_enqueues_rebuilds(self):
        start = date(2024, 10, 1)
        with patch("attendance.signals.pair_employee_day_task.delay"), patch(
            "attendance.signals.compute_employee_day_task.delay"
        ):
            RosterEntry.objects.create(
                employee=self.admin_user, date=start, shift=self.shift
            )

        payload = {
            "employees": [self.admin_user.id, self.other_employee.id],
            "shift": self.shift.id,
            "start_date": start.isoformat(),
            "days": 2,
        }

        class DummyResult:
            id = "dummy"

        def immediate_run(*args, **kwargs):
            from pagasys.tasks import schedule_range_bulk

            schedule_range_bulk.run(*args, **kwargs)
            return DummyResult()

        with patch("pagasys.tasks.pair_employee_day_task.delay") as mock_pair, patch(
            "pagasys.tasks.compute_employee_day_task.delay"
        ) as mock_compute, patch(
            "pagasys.policy.views.ASYNC_BULK_THRESHOLD", 0
        ), patch(
            "pagasys.tasks.schedule_range_bulk.delay", side_effect=immediate_run
        ):
            resp = self.client.post(
                f"/api/companies/{self.company.id}/roster/schedule-range/",
                payload,
                format="json",
            )

        self.assertEqual(resp.status_code, 202, resp.data)
        expected = {
            (self.admin_user.id, start),
            (self.admin_user.id, start + timedelta(days=1)),
            (self.other_employee.id, start),
            (self.other_employee.id, start + timedelta(days=1)),
        }
        called_pairs = {
            (call.args[0], date.fromisoformat(call.args[1]))
            for call in mock_pair.call_args_list
        }
        self.assertSetEqual(called_pairs, expected)
        self.assertEqual(mock_pair.call_count, len(expected))
        self.assertEqual(mock_compute.call_count, len(expected))
