from django.contrib import admin
from django.contrib.messages import get_messages
from django.test import TestCase, RequestFactory
from django import forms
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

    def test_get_form_scopes_branch(self):
        req = self._make_request({})
        with patch("pagasys.admin.scope_queryset") as mock_scope:
            def side_effect(qs, user):
                if qs.model is Branch:
                    return Branch.objects.filter(id=self.branch.id)
                return qs

            mock_scope.side_effect = side_effect
            form_class = self.admin.get_form(req)

            mock_scope.assert_any_call(ANY, req.user)
            branch_calls = [c for c in mock_scope.call_args_list if c.args[0].model is Branch]
            self.assertGreaterEqual(len(branch_calls), 1)

            self.assertEqual(
                list(form_class.base_fields["branch"].queryset),
                [self.branch],
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
        mock_delay.return_value.id = "t1"
        form_data = {
            "date": "2024-07-01",
            "shift": self.shift.id,
            "branch": self.branch.id,
            "repeat_days": 1,
        }
        form = RosterEntryRangeForm(data=form_data, instance=RosterEntry())
        assert form.is_valid()
        obj = form.save(commit=False)
        req = self._make_request(form_data)
        with patch("pagasys.admin.ASYNC_BULK_THRESHOLD", 1):
            self.admin.save_model(req, obj, form, False)
        mock_delay.assert_called_once()
        messages = [m.message for m in get_messages(req)]
        self.assertIn("task t1", messages[0])
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
            "branch": self.branch.id,
            "repeat_days": 1,
        }
        form = RosterEntryRangeForm(data=form_data, instance=RosterEntry())
        assert form.is_valid()
        obj = form.save(commit=False)
        req = self._make_request(form_data)
        with patch("pagasys.admin.ASYNC_BULK_THRESHOLD", 10):
            self.admin.save_model(req, obj, form, False)
        mock_delay.assert_not_called()
        self.assertEqual(RosterEntry.objects.count(), 2)
        for emp in [self.admin_user, e2]:
            self.assertTrue(
                RosterEntry.objects.filter(employee=emp, date="2024-07-01").exists()
            )

    def test_add_form_uses_checkbox_widget(self):
        req = self.factory.get("/admin/", {"stage2": "1"})
        req.user = self.admin_user
        req.session = {}
        form_class = self.admin.get_form(req)
        self.assertIsInstance(
            form_class.base_fields["employee"].widget, forms.CheckboxSelectMultiple
        )
