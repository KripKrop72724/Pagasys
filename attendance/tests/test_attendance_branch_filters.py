from datetime import date, datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, Employee
from attendance.models import AttDay, AttPair


class AttendanceBranchFilterTests(TestCase):
    def setUp(self):
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
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
        )
        self.client.force_authenticate(self.admin)

        self.employee_one = Employee.objects.create_user(
            username="emp-one",
            password="pw",
            department=self.department_one,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
        )
        self.employee_two = Employee.objects.create_user(
            username="emp-two",
            password="pw",
            department=self.department_two,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
        )

        self.day = date(2024, 6, 1)
        AttDay.objects.create(employee=self.employee_one, date=self.day, status="present")
        AttDay.objects.create(employee=self.employee_two, date=self.day, status="leave")

        AttPair.objects.create(
            employee=self.employee_one,
            date=self.day,
            in_event_id=1,
            out_event_id=2,
            in_ts=timezone.make_aware(datetime(2024, 6, 1, 8, 0)),
            out_ts=timezone.make_aware(datetime(2024, 6, 1, 16, 0)),
            duration_min=480,
        )
        AttPair.objects.create(
            employee=self.employee_two,
            date=self.day,
            in_event_id=3,
            out_event_id=4,
            in_ts=timezone.make_aware(datetime(2024, 6, 1, 9, 0)),
            out_ts=timezone.make_aware(datetime(2024, 6, 1, 17, 0)),
            duration_min=480,
        )

    @staticmethod
    def _extract_results(response):
        payload = response.json()
        if isinstance(payload, dict) and "results" in payload:
            return payload["results"]
        return payload

    def test_attday_branch_filter_accepts_multiple_values(self):
        url = reverse("att-day-list", kwargs={"company_id": self.company.id})
        single = self.client.get(url, [("branch", self.branch_two.id)])
        assert single.status_code == 200
        employees = {item["employee"] for item in self._extract_results(single)}
        assert employees == {self.employee_two.id}

        combo = self.client.get(
            url,
            [("branch", self.branch_one.id), ("branch", self.branch_two.id)],
        )
        assert combo.status_code == 200
        employees = {item["employee"] for item in self._extract_results(combo)}
        assert employees == {self.employee_one.id, self.employee_two.id}

    def test_attpair_branch_filter_limits_results(self):
        url = reverse("att-pair-list", kwargs={"company_id": self.company.id})
        response = self.client.get(url, [("branch", self.branch_one.id)])
        assert response.status_code == 200
        employees = {
            item["employee"] for item in self._extract_results(response)
        }
        assert employees == {self.employee_one.id}

        repeat = self.client.get(url, [("branch", f"{self.branch_two.id},{self.branch_one.id}")])
        assert repeat.status_code == 200
        employees = {
            item["employee"] for item in self._extract_results(repeat)
        }
        assert employees == {self.employee_one.id, self.employee_two.id}
