from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase

from pagasys.models import RosterEntry, Employee
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
