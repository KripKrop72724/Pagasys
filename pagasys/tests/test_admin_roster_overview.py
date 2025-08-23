from datetime import timedelta, date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from pagasys.models import RosterEntry

from .test_models import ModelFactoryMixin


class RosterEntryOverviewTests(ModelFactoryMixin, TestCase):
    """Ensure the custom roster overview view renders a useful grid."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.license = self.create_license(
            company=self.company, branches=[self.branch], license_no="LIC0", max_visas=5
        )
        self.shift = self.create_shift_template(self.company)
        User = get_user_model()
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
        self.client.defaults["HTTP_HOST"] = "0.0.0.0"

    def _create_employee(self, username):
        User = get_user_model()
        return User.objects.create_user(
            username=username,
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

    def test_changelist_links_to_overview(self):
        url = reverse("admin:pagasys_rosterentry_changelist")
        res = self.client.get(url)
        self.assertContains(res, reverse("admin:pagasys_rosterentry_overview"))

    def test_overview_displays_roster_grid(self):
        e1 = self._create_employee("e1")
        e2 = self._create_employee("e2")
        RosterEntry.objects.create(employee=e1, date="2024-07-01", shift=self.shift)
        RosterEntry.objects.create(
            employee=e1, date="2024-07-02", shift=self.shift, is_rest_day=True
        )
        RosterEntry.objects.create(employee=e2, date="2024-07-01", shift=self.shift)
        url = (
            reverse("admin:pagasys_rosterentry_overview")
            + "?start=2024-07-01&days=2"
        )
        res = self.client.get(url)
        self.assertContains(res, "e1")
        self.assertContains(res, "e2")
        self.assertContains(res, self.shift.name)
        self.assertContains(res, "Rest")
        self.assertContains(res, "-")

    def test_overview_handles_bad_params(self):
        url = reverse("admin:pagasys_rosterentry_overview") + "?start=bad&days=-5"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        today = date.today()
        self.assertContains(res, today.isoformat())
        self.assertContains(res, (today + timedelta(days=6)).isoformat())

    def test_overview_no_entries(self):
        url = reverse("admin:pagasys_rosterentry_overview") + "?start=2024-07-01&days=3"
        res = self.client.get(url)
        self.assertNotContains(res, "e1")
        self.assertContains(res, "2024-07-01")

