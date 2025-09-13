from datetime import date

from django.test import TestCase, Client
from rest_framework.test import APIClient

from attendance.models import AttAdjustment
from pagasys.models import Company, Branch, Department, Employee


class AttAdjustmentCreatedByTests(TestCase):
    def setUp(self):
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.dept = Department.objects.create(branch=self.branch, name="D1")
        self.employee = Employee.objects.create(
            username="emp",
            first_name="E",
            last_name="One",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.user = Employee.objects.create(
            username="admin",
            first_name="Ad",
            last_name="Min",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
            is_superuser=True,
        )

    def test_api_sets_created_by(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        url = f"/api/companies/{self.company.id}/att-adjustments/"
        resp = client.post(
            url,
            {"employee": self.employee.id, "date": str(self.day), "reason": "manual"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        adj = AttAdjustment.objects.get()
        self.assertEqual(adj.created_by_id, self.user.id)

    def test_admin_sets_created_by(self):
        client = Client()
        client.force_login(self.user)
        url = "/admin/attendance/attadjustment/add/"
        resp = client.post(
            url,
            {
                "employee": self.employee.id,
                "date": str(self.day),
                "reason": "manual",
                "delta_work_min": 0,
                "delta_unpaid_break_min": 0,
                "delta_paid_break_min": 0,
                "delta_ot_regular_min": 0,
                "delta_ot_night_min": 0,
                "delta_ot_holiday_min": 0,
                "override_status": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        adj = AttAdjustment.objects.get()
        self.assertEqual(adj.created_by_id, self.user.id)

