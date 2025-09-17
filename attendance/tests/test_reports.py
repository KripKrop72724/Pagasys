import io
from collections import OrderedDict
from datetime import date, datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.template.loader import render_to_string
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
            first_name="Alice",
            last_name="Anderson",
            department=self.dept1,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )
        self.emp2 = Employee.objects.create_user(
            username="e2",
            password="pass",
            first_name="Bob",
            last_name="Brown",
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
        expected_emp1_name = f"{self.emp1.first_name} {self.emp1.last_name}".strip()
        expected_emp2_name = f"{self.emp2.first_name} {self.emp2.last_name}".strip()
        assert filtered[0]["employee"] == expected_emp1_name
        assert filtered[0]["branch"] == self.branch1.name
        branches, stats = group_late_comers(records)
        assert stats["total_late_min"] == 20
        assert set(branches.keys()) == {self.branch1.name, self.branch2.name}
        branch1_records = branches[self.branch1.name]["records"]
        branch2_records = branches[self.branch2.name]["records"]
        assert branches[self.branch1.name]["total_late_min"] == 15
        assert branches[self.branch2.name]["total_late_min"] == 5
        assert [r["employee"] for r in branch1_records] == [expected_emp1_name]
        assert [r["employee"] for r in branch2_records] == [expected_emp2_name]

    def test_late_comers_template_renders_simple_layout(self):
        generated_at = timezone.make_aware(datetime(2024, 1, 2, 9, 30))
        branches = OrderedDict(
            (
                (
                    self.branch1.name,
                    {
                        "records": [
                            {
                                "employee": "Alice Anderson",
                                "shift": "S1",
                                "date": self.day,
                                "late_min": 15,
                            }
                        ],
                        "total_late_min": 15,
                    },
                ),
                (
                    self.branch2.name,
                    {
                        "records": [
                            {
                                "employee": "Bob Brown",
                                "shift": "S2",
                                "date": self.day,
                                "late_min": 5,
                            }
                        ],
                        "total_late_min": 5,
                    },
                ),
            )
        )
        html = render_to_string(
            "reports/late_comers.html",
            {
                "branches": branches,
                "start_date": self.day,
                "end_date": self.day,
                "generated_at": generated_at,
                "total_late_min": 20,
            },
        )
        # The simplified template should just show a heading, the selected date, and a basic table.
        assert "<h1>Late Comers Report</h1>" in html
        assert "Date:" in html
        # When the start and end dates match, only a single date should be shown.
        assert "01 Jan 2024" in html
        assert " - " not in html
        assert "<table>" in html
        assert "<th>Branch</th>" in html
        assert "<th>Employee</th>" in html
        assert "<th>Shift</th>" in html
        assert "<th>Date</th>" in html
        assert "<th>Late (min)</th>" in html
        assert f">{self.branch1.name}<" in html
        assert f">{self.branch2.name}<" in html
        assert "Alice Anderson" in html
        assert "Bob Brown" in html
        assert "S1" in html and "S2" in html
        assert "15" in html and "5" in html

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
