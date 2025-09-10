from django.contrib import admin
from django.test import TestCase, RequestFactory
from unittest.mock import patch, ANY

from pagasys.admin import RosterEntryAdmin, RosterEntryRangeForm
from pagasys.models import (
    Company,
    Branch,
    Department,
    Employee,
    TradeLicense,
    ShiftTemplate,
    RosterEntry,
)


class RosterEntryAdminTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch])
        self.admin_user = Employee.objects.create_user(
            username="admin",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
            is_staff=True,
            is_superuser=True,
        )
        self.shift = ShiftTemplate.objects.create(
            company=self.company, name="S1", start_time="09:00", end_time="17:00"
        )
        self.factory = RequestFactory()
        self.admin = RosterEntryAdmin(RosterEntry, admin.sites.AdminSite())

    def _make_request(self, data):
        req = self.factory.post("/admin/", data)
        req.user = self.admin_user
        req.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage

        setattr(req, "_messages", FallbackStorage(req))
        return req

    def test_get_form_scopes_employees(self):
        req = self._make_request({})
        with patch("pagasys.admin.scope_queryset") as mock_scope:
            # Return model-specific querysets depending on the queryset's model
            def side_effect(qs, user):
                if qs.model is Employee:
                    return Employee.objects.filter(id=self.admin_user.id)
                return qs

            mock_scope.side_effect = side_effect
            form_class = self.admin.get_form(req)

            # Ensure Employee queryset was scoped
            mock_scope.assert_any_call(ANY, req.user)
            emp_calls = [c for c in mock_scope.call_args_list if c.args[0].model is Employee]
            self.assertGreaterEqual(len(emp_calls), 1)

            self.assertEqual(
                list(form_class.base_fields["employees"].queryset),
                [self.admin_user],
            )

    @patch("pagasys.admin.schedule_range_bulk.delay")
    def test_admin_async_queue(self, mock_delay):
        e2 = Employee.objects.create_user(
            username="e2",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        form_data = {
            "date": "2024-07-01",
            "shift": self.shift.id,
            "employees": [self.admin_user.id, e2.id],
            "repeat_days": 1,
        }
        form = RosterEntryRangeForm(
            data=form_data, instance=RosterEntry(employee=self.admin_user)
        )
        assert form.is_valid()
        obj = form.save(commit=False)
        req = self._make_request(form_data)
        with patch("pagasys.admin.ASYNC_BULK_THRESHOLD", 1):
            self.admin.save_model(req, obj, form, False)
        mock_delay.assert_called_once()
        self.assertEqual(RosterEntry.objects.count(), 0)

    @patch("pagasys.admin.schedule_range_bulk.delay")
    def test_admin_sync_multiple_employees(self, mock_delay):
        e2 = Employee.objects.create_user(
            username="e2",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        form_data = {
            "date": "2024-07-01",
            "shift": self.shift.id,
            "employees": [self.admin_user.id, e2.id],
            "repeat_days": 1,
        }
        form = RosterEntryRangeForm(
            data=form_data, instance=RosterEntry(employee=self.admin_user)
        )
        assert form.is_valid()
        obj = form.save(commit=False)
        req = self._make_request(form_data)
        with patch("pagasys.admin.ASYNC_BULK_THRESHOLD", 10):
            self.admin.save_model(req, obj, form, False)
        mock_delay.assert_not_called()
        self.assertEqual(RosterEntry.objects.count(), 2)
