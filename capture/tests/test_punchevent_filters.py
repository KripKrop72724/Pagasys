from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from pagasys.models import Company, Branch, Department, Employee
from capture.models import AttendanceDevice, PunchEvent


class PunchEventBranchFilterTests(TestCase):
    def setUp(self):
        pair_patcher = patch("capture.signals.pair_employee_day_task.delay")
        compute_patcher = patch("capture.signals.compute_employee_day_task.delay")
        self.addCleanup(pair_patcher.stop)
        self.addCleanup(compute_patcher.stop)
        pair_patcher.start()
        compute_patcher.start()

        self.client = APIClient()
        self.company = Company.objects.create(name="ACME")
        self.branch_one = Branch.objects.create(company=self.company, name="North")
        self.branch_two = Branch.objects.create(company=self.company, name="South")
        self.department_one = Department.objects.create(branch=self.branch_one, name="Ops")
        self.department_two = Department.objects.create(branch=self.branch_two, name="HR")

        self.admin = Employee.objects.create_superuser(
            username="admin",
            password="pw",
            department=self.department_one,
            hire_date=timezone.localdate(),
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
        )
        self.client.force_authenticate(self.admin)

        self.employee_one = Employee.objects.create_user(
            username="emp1",
            password="pw",
            department=self.department_one,
            hire_date=timezone.localdate(),
            employment_type="permanent",
            visa_type="personal",
        )
        self.employee_two = Employee.objects.create_user(
            username="emp2",
            password="pw",
            department=self.department_two,
            hire_date=timezone.localdate(),
            employment_type="permanent",
            visa_type="personal",
        )

        self.device_one = AttendanceDevice.objects.create(
            company=self.company,
            name="Dev1",
            api_key="key1",
            branch=self.branch_one,
        )
        self.device_two = AttendanceDevice.objects.create(
            company=self.company,
            name="Dev2",
            api_key="key2",
            branch=self.branch_two,
        )

        base_ts = timezone.make_aware(datetime(2024, 6, 1, 8, 0))
        PunchEvent.objects.create(
            device=self.device_one,
            company=self.company,
            employee=self.employee_one,
            matched_employee=self.employee_one,
            action="in",
            device_ts=base_ts,
            s3_key="",
        )
        PunchEvent.objects.create(
            device=self.device_two,
            company=self.company,
            employee=self.employee_two,
            matched_employee=self.employee_two,
            action="in",
            device_ts=base_ts + timedelta(hours=1),
            s3_key="",
        )
        PunchEvent.objects.create(
            device=self.device_two,
            company=self.company,
            employee=None,
            matched_employee=None,
            action="out",
            device_ts=base_ts + timedelta(hours=2),
            s3_key="",
        )

    def test_branch_filter_matches_employees_and_devices(self):
        url = reverse("punch-events-list", kwargs={"company_id": self.company.id})
        response = self.client.get(url, [("branch", self.branch_two.id)])
        assert response.status_code == 200
        event_ids = {item["id"] for item in self._extract_results(response)}
        assert len(event_ids) == 2

        combined = self.client.get(
            url,
            [("branch", self.branch_one.id), ("branch", self.branch_two.id)],
        )
        assert combined.status_code == 200
        event_ids = {item["id"] for item in self._extract_results(combined)}
        assert len(event_ids) == 3

    @staticmethod
    def _extract_results(response):
        payload = response.json()
        if isinstance(payload, dict) and "results" in payload:
            return payload["results"]
        return payload
