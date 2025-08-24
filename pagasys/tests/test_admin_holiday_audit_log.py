from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase

from .test_models import ModelFactoryMixin
from pagasys.models import WorkCalendar, Holiday, HolidayAuditLog


class HolidayAuditLogAdminTests(ModelFactoryMixin, TestCase):
    """Ensure HolidayAuditLog is exposed read-only in the admin."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
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
        self.client.force_login(self.user)

        hol = Holiday.objects.create(calendar=self.calendar, date="2024-01-10", name="H1")
        hol.date = "2024-01-11"
        hol.save()
        self.log = HolidayAuditLog.objects.latest("timestamp")

    def test_list_view_accessible(self):
        url = reverse("admin:pagasys_holidayauditlog_changelist")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "updated")

    def test_add_disallowed(self):
        url = reverse("admin:pagasys_holidayauditlog_add")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)
