from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase

from pagasys.models import RosterEntry, Employee, WorkCalendar, Holiday
from .test_models import ModelFactoryMixin


class RosterEntryAdminRangeTests(ModelFactoryMixin, TestCase):
    def _create_employee(self, **kwargs):
        data = {
            "username": f"emp{Employee.objects.count()}",
            "password": "pass",
            "first_name": "A",
            "last_name": "B",
            "visa_type": "personal",
            "hire_date": "2024-01-01",
            "employment_type": "permanent",
        }
        data.update(kwargs)
        if data.get("trade_license") and data.get("visa_type") == "personal":
            data["visa_type"] = "company"
        return Employee.objects.create_user(**data)

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.license = self.create_license(
            company=self.company,
            branches=[self.branch],
            license_no="LICX",
            max_visas=5,
        )
        self.calendar = WorkCalendar.objects.create(
            company=self.company, name="Cal", is_default=True
        )
        Holiday.objects.create(calendar=self.calendar, date="2024-07-04", name="H1")
        self.employee = self._create_employee(
            department=self.department,
            trade_license=self.license,
        )
        self.shift = self.create_shift_template(self.company)
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.superuser)

    def test_repeat_days_with_rest(self):
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": self.shift.id,
            "repeat_days": 7,
            # Roster admin expects weekday names (e.g. "sat", "sun")
            "rest_weekdays": ["sat", "sun"],
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(RosterEntry.objects.filter(employee=self.employee).count(), 7)
        self.assertTrue(RosterEntry.objects.get(date="2024-07-06").is_rest_day)
        self.assertTrue(RosterEntry.objects.get(date="2024-07-07").is_rest_day)

    def test_holiday_flag_on_repeat(self):
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-04",
            "shift": self.shift.id,
            "repeat_days": 1,
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        entry = RosterEntry.objects.get(employee=self.employee, date="2024-07-04")
        self.assertTrue(entry.is_holiday)
        self.assertTrue(entry.was_holiday)

    def test_repeat_until_with_rest(self):
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": self.shift.id,
            "repeat_until": "2024-07-07",
            "rest_weekdays": ["sat", "sun"],
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(RosterEntry.objects.filter(employee=self.employee).count(), 7)
        self.assertTrue(RosterEntry.objects.get(date="2024-07-06").is_rest_day)
        self.assertTrue(RosterEntry.objects.get(date="2024-07-07").is_rest_day)

    def test_single_entry_respects_rest_weekday(self):
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-06",  # Saturday
            "shift": self.shift.id,
            "rest_weekdays": ["sat"],
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        entry = RosterEntry.objects.get(employee=self.employee)
        self.assertTrue(entry.is_rest_day)

    def test_repeat_until(self):
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": self.shift.id,
            "repeat_until": "2024-07-03",
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(RosterEntry.objects.filter(employee=self.employee).count(), 3)

    def test_repeat_conflict(self):
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": self.shift.id,
            "repeat_days": 2,
            "repeat_until": "2024-07-03",
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Provide either repeat_days or repeat_until")

    def test_repeat_days_updates_existing_entries(self):
        RosterEntry.objects.create(
            employee=self.employee, date="2024-07-01", shift=self.shift
        )
        RosterEntry.objects.create(
            employee=self.employee, date="2024-07-02", shift=self.shift
        )
        entry = RosterEntry.objects.get(date="2024-07-01")
        change_url = reverse("admin:pagasys_rosterentry_change", args=[entry.id])
        new_shift = self.create_shift_template(self.company, name="Night")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": new_shift.id,
            "repeat_days": 3,
        }
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        qs = RosterEntry.objects.filter(
            employee=self.employee, date__range=["2024-07-01", "2024-07-03"]
        ).order_by("date")
        self.assertEqual(qs.count(), 3)
        self.assertEqual(list(qs.values_list("shift_id", flat=True)), [new_shift.id] * 3)

    def test_repeat_days_with_rest_updates_existing_entries(self):
        # create entries without rest day flags
        for d in ["2024-07-01", "2024-07-02", "2024-07-03"]:
            RosterEntry.objects.create(
                employee=self.employee, date=d, shift=self.shift, is_rest_day=False
            )
        entry = RosterEntry.objects.get(date="2024-07-01")
        change_url = reverse("admin:pagasys_rosterentry_change", args=[entry.id])
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": self.shift.id,
            "repeat_days": 7,
            "rest_weekdays": ["sat", "sun"],
        }
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        sat_entry = RosterEntry.objects.get(date="2024-07-06", employee=self.employee)
        sun_entry = RosterEntry.objects.get(date="2024-07-07", employee=self.employee)
        self.assertTrue(sat_entry.is_rest_day)
        self.assertTrue(sun_entry.is_rest_day)

    def test_repeat_until_updates_existing_entries(self):
        RosterEntry.objects.create(
            employee=self.employee, date="2024-07-01", shift=self.shift
        )
        RosterEntry.objects.create(
            employee=self.employee, date="2024-07-02", shift=self.shift
        )
        entry = RosterEntry.objects.get(date="2024-07-01")
        change_url = reverse("admin:pagasys_rosterentry_change", args=[entry.id])
        new_shift = self.create_shift_template(self.company, name="Late")
        data = {
            "employee": self.employee.id,
            "date": "2024-07-01",
            "shift": new_shift.id,
            "repeat_until": "2024-07-03",
        }
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        qs = RosterEntry.objects.filter(
            employee=self.employee, date__range=["2024-07-01", "2024-07-03"]
        ).order_by("date")
        self.assertEqual(qs.count(), 3)
        self.assertEqual(list(qs.values_list("shift_id", flat=True)), [new_shift.id] * 3)
