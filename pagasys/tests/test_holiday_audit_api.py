from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from django.test import TestCase

from .test_models import ModelFactoryMixin
from pagasys.models import WorkCalendar, Holiday, HolidayAuditLog


class HolidayAuditLogAPITests(ModelFactoryMixin, TestCase):
    """API tests for the holiday audit log endpoints."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        User = get_user_model()
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.calendar = WorkCalendar.objects.create(company=self.company, name="Cal")
        self.license = self.create_license(company=self.company, branches=[self.branch], license_no="LICA")
        self.user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_authenticate(self.user)

        # Create holiday to generate audit logs
        hol = Holiday.objects.create(calendar=self.calendar, date="2024-01-10", name="H1")
        hol.date = "2024-01-11"
        hol.save()
        self.logs = list(HolidayAuditLog.objects.order_by("timestamp"))

    def _ids(self, res):
        return [obj["id"] for obj in res.data["results"]]

    def test_list_logs(self):
        res = self.client.get("/api/holiday-audit-logs/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 2)

    def test_filter_by_action(self):
        res = self.client.get("/api/holiday-audit-logs/?action=updated")
        self.assertEqual(self._ids(res), [self.logs[1].id])

    def test_filter_by_calendar(self):
        url = f"/api/holiday-audit-logs/?calendar={self.calendar.id}"
        res = self.client.get(url)
        self.assertEqual(set(self._ids(res)), {l.id for l in self.logs})

    def test_ordering(self):
        res = self.client.get("/api/holiday-audit-logs/?ordering=timestamp")
        self.assertEqual(self._ids(res), [l.id for l in self.logs])

    def test_timestamp_range(self):
        from urllib.parse import quote

        ts = quote(self.logs[1].timestamp.isoformat())
        res = self.client.get(f"/api/holiday-audit-logs/?timestamp_from={ts}")
        self.assertEqual(self._ids(res), [self.logs[1].id])

    def test_invalid_calendar_filter(self):
        res = self.client.get("/api/holiday-audit-logs/?calendar=9999")
        self.assertEqual(res.status_code, 400)

    def test_post_disallowed(self):
        res = self.client.post("/api/holiday-audit-logs/", {})
        self.assertEqual(res.status_code, 405)
