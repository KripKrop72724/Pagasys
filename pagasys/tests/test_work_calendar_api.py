from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from pagasys.models import (
    Company,
    Branch,
    Department,
    TradeLicense,
    WorkCalendar,
    Employee,
)


class WorkCalendarApiTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.company1 = Company.objects.create(name="C1")
        self.company2 = Company.objects.create(name="C2")
        self.cal1_default = WorkCalendar.objects.create(company=self.company1, name="C1 Def", is_default=True)
        self.cal1_other = WorkCalendar.objects.create(company=self.company1, name="C1 Other")
        self.cal2_default = WorkCalendar.objects.create(company=self.company2, name="C2 Def", is_default=True)
        self.branch1 = Branch.objects.create(company=self.company1, name="B1")
        self.department1 = Department.objects.create(branch=self.branch1, name="D1")
        self.license1 = TradeLicense.objects.create(
            company=self.company1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.license1.branches.set([self.branch1])
        self.user = User.objects.create_superuser(
            username="su",
            password="pass",
            trade_license=self.license1,
            department=self.department1,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.employee1 = Employee.objects.create(
            username="e1",
            password="pass",
            trade_license=self.license1,
            department=self.department1,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        self.employee2 = Employee.objects.create(
            username="e2",
            password="pass",
            trade_license=self.license1,
            department=self.department1,
            hire_date="2024-01-03",
            employment_type="permanent",
            visa_type="company",
        )

    def test_branch_work_calendar_patch(self):
        url = f"/api/branches/{self.branch1.id}/"
        res = self.client.patch(url, {"work_calendar": self.cal2_default.id}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.patch(url, {"work_calendar": self.cal1_other.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.branch1.refresh_from_db()
        self.assertEqual(self.branch1.work_calendar_id, self.cal1_other.id)

    def test_branch_work_calendar_bulk_patch(self):
        branch2 = Branch.objects.create(company=self.company1, name="B2")
        payload = [
            {"id": self.branch1.id, "work_calendar": self.cal1_other.id},
            {"id": branch2.id, "work_calendar": self.cal1_other.id},
        ]
        res = self.client.patch("/api/branches/bulk-update/", payload, format="json")
        self.assertEqual(res.status_code, 200)
        payload = [
            {"id": self.branch1.id, "work_calendar": self.cal2_default.id},
            {"id": branch2.id, "work_calendar": self.cal2_default.id},
        ]
        res = self.client.patch("/api/branches/bulk-update/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertTrue(res.data["errors"])

    def test_employee_work_calendar_patch(self):
        url = f"/api/employees/{self.employee1.id}/"
        res = self.client.patch(url, {"work_calendar": self.cal2_default.id}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.patch(url, {"work_calendar": self.cal1_other.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.employee1.refresh_from_db()
        self.assertEqual(self.employee1.work_calendar_id, self.cal1_other.id)

    def test_employee_work_calendar_bulk_patch(self):
        payload = [
            {"id": self.employee1.id, "work_calendar": self.cal1_other.id},
            {"id": self.employee2.id, "work_calendar": self.cal1_other.id},
        ]
        res = self.client.patch("/api/employees/bulk-update/", payload, format="json")
        self.assertEqual(res.status_code, 200)
        payload = [
            {"id": self.employee1.id, "work_calendar": self.cal2_default.id},
            {"id": self.employee2.id, "work_calendar": self.cal2_default.id},
        ]
        res = self.client.patch("/api/employees/bulk-update/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertTrue(res.data["errors"])
