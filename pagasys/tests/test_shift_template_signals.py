from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from pagasys.models import Employee, RosterEntry

from .test_models import ModelFactoryMixin


class ShiftTemplateSignalTests(ModelFactoryMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        call_command("initgroups", verbosity=0)

        self.company = self.create_company("Comp")
        self.branch = self.create_branch(self.company, "Main")
        self.department = self.create_department(self.branch, "Dept")
        self.license = self.create_license(
            company=self.company,
            branches=[self.branch],
            license_no="LIC-1",
            max_visas=5,
        )
        self.shift = self.create_shift_template(self.company, name="Day Shift")
        self.day_one = date(2024, 1, 1)
        self.day_two = date(2024, 1, 2)

        self.worker_one = Employee.objects.create(
            username="worker1",
            first_name="Worker",
            last_name="One",
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="personal",
        )
        self.worker_two = Employee.objects.create(
            username="worker2",
            first_name="Worker",
            last_name="Two",
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="personal",
        )

        self.api_user = Employee.objects.create_user(
            username="policyadmin",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        admin_group = Group.objects.get(name="Company Admin")
        self.api_user.groups.add(admin_group)
        self.api_client = APIClient()
        self.api_client.force_authenticate(self.api_user)

        UserModel = get_user_model()
        self.superuser = UserModel.objects.create_superuser(
            username="super",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.admin_client = Client()
        self.admin_client.force_login(self.superuser)
        self.admin_client.defaults["HTTP_HOST"] = "0.0.0.0"

    def _create_roster_pairs(self):
        pairs = [
            (self.worker_one, self.day_one),
            (self.worker_one, self.day_two),
            (self.worker_two, self.day_one),
        ]
        for employee, roster_day in pairs:
            RosterEntry.objects.create(
                employee=employee,
                date=roster_day,
                shift=self.shift,
            )
        return {(employee.id, roster_day.isoformat()) for employee, roster_day in pairs}

    def test_policy_shift_template_update_enqueues_tasks(self):
        with patch("pagasys.signals.pair_employee_day_task.delay") as mock_pair, patch(
            "pagasys.signals.compute_employee_day_task.delay"
        ) as mock_compute:
            expected_pairs = self._create_roster_pairs()
            mock_pair.reset_mock()
            mock_compute.reset_mock()

            response = self.api_client.patch(
                f"/api/companies/{self.company.id}/shift-templates/{self.shift.id}/",
                {"name": "Updated", "start_time": "08:00", "end_time": "16:00"},
                format="json",
            )
            self.assertEqual(response.status_code, 200)

            pair_calls = {(call.args[0], call.args[1]) for call in mock_pair.call_args_list}
            compute_calls = {
                (call.args[0], call.args[1]) for call in mock_compute.call_args_list
            }
            self.assertEqual(pair_calls, expected_pairs)
            self.assertEqual(compute_calls, expected_pairs)
            self.assertEqual(mock_pair.call_count, len(expected_pairs))
            self.assertEqual(mock_compute.call_count, len(expected_pairs))

    def test_admin_shift_template_update_enqueues_tasks(self):
        change_url = reverse("admin:pagasys_shifttemplate_change", args=[self.shift.id])
        form_data = {
            "company": self.company.id,
            "name": "Admin Updated",
            "start_time": "07:00",
            "end_time": "15:00",
            "break_minutes": 0,
            "grace_in_min": 0,
            "grace_out_min": 0,
            "late_after_min": 0,
            "early_leave_before_min": 0,
            "rounding_min": 0,
        }
        with patch("pagasys.signals.pair_employee_day_task.delay") as mock_pair, patch(
            "pagasys.signals.compute_employee_day_task.delay"
        ) as mock_compute:
            expected_pairs = self._create_roster_pairs()
            mock_pair.reset_mock()
            mock_compute.reset_mock()

            response = self.admin_client.post(change_url, form_data)
            self.assertEqual(response.status_code, 302)

            pair_calls = {(call.args[0], call.args[1]) for call in mock_pair.call_args_list}
            compute_calls = {
                (call.args[0], call.args[1]) for call in mock_compute.call_args_list
            }
            self.assertEqual(pair_calls, expected_pairs)
            self.assertEqual(compute_calls, expected_pairs)
            self.assertEqual(mock_pair.call_count, len(expected_pairs))
            self.assertEqual(mock_compute.call_count, len(expected_pairs))
