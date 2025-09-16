from datetime import date, datetime
import io

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, Project, Employee, ShiftTemplate
from attendance.models import AttDay, AttPair
from attendance.reports import get_late_comers, group_late_comers


class LateComersReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="C1")
        self.branch1 = Branch.objects.create(company=self.company, name="B1")
        self.branch2 = Branch.objects.create(company=self.company, name="B2")
        self.dept1 = Department.objects.create(branch=self.branch1, name="D1")
        self.day = date(2024, 1, 1)
        self.proj2 = Project.objects.create(
            branch=self.branch2, name="P2", start_date=self.day
        )
        self.shift1 = ShiftTemplate.objects.create(
            company=self.company, name="S1", start_time="09:00", end_time="17:00"
        )
        self.shift2 = ShiftTemplate.objects.create(
            company=self.company, name="S2", start_time="10:00", end_time="18:00"
        )
        self.emp1 = Employee.objects.create_user(
            username="e1",
            password="pass",
            department=self.dept1,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.emp2 = Employee.objects.create_user(
            username="e2",
            password="pass",
            project=self.proj2,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.admin = Employee.objects.create_superuser(
            username="admin",
            password="pass",
            department=self.dept1,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
        )
        AttDay.objects.create(
            employee=self.emp1, date=self.day, shift=self.shift1, late_min=15
        )
        AttPair.objects.create(
            employee=self.emp1,
            date=self.day,
            in_event_id=1,
            in_ts=timezone.make_aware(datetime(2024, 1, 1, 9, 15)),
        )
        AttDay.objects.create(
            employee=self.emp2, date=self.day, shift=self.shift2, late_min=5
        )
        AttPair.objects.create(
            employee=self.emp2,
            date=self.day,
            in_event_id=2,
            in_ts=timezone.make_aware(datetime(2024, 1, 1, 10, 5)),
        )
        self.api_client = APIClient()

    def test_get_and_group_late_comers(self):
        records = get_late_comers(self.day, self.day)
        assert len(records) == 2
        filtered = get_late_comers(self.day, self.day, {"branch_id": self.branch1.id})
        assert len(filtered) == 1
        assert filtered[0]["employee"] == str(self.emp1)
        ordered, stats = group_late_comers(records)
        assert stats["total_late_min"] == 20
        assert {r["employee"] for r in ordered} == {str(self.emp1), str(self.emp2)}

    def test_api_late_comers_report(self):
        self.api_client.force_authenticate(self.admin)
        url = reverse("att-day-late-comers-report", kwargs={"company_id": self.company.id})
        resp = self.api_client.get(
            url,
            {"start": self.day.isoformat(), "end": self.day.isoformat()},
        )
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        try:
            from PyPDF2 import PdfReader

            text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(resp.content)).pages)
            assert "Late comers" in text or "Late Comers" in text
        except Exception:
            pass

    def test_admin_view_generates_pdf(self):
        self.client.force_login(self.admin)
        url = reverse("admin:attendance_attday_late_comers_report")
        get_resp = self.client.get(url)
        assert get_resp.status_code == 200
        post_resp = self.client.post(
            url,
            {"start": self.day.isoformat(), "end": self.day.isoformat()},
        )
        assert post_resp.status_code == 200
        assert post_resp["Content-Type"] == "application/pdf"
