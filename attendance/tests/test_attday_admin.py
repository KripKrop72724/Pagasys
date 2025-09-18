from datetime import date, datetime

from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.contrib import admin

from pagasys.models import Company, Branch, Department, Project, Employee
from attendance.models import AttDay, AttPair, AttAdjustment
from attendance.admin import AttDayAdmin


def test_attday_admin_includes_date_filter():
    assert "date" in AttDayAdmin.list_filter
    assert AttDayAdmin.date_hierarchy == "date"


class AttendanceCalendarAdminViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="ACME")
        self.branch = Branch.objects.create(company=self.company, name="HQ")
        self.department = Department.objects.create(branch=self.branch, name="Ops")
        self.project = Project.objects.create(
            branch=self.branch,
            name="Site A",
            start_date=date(2024, 1, 1),
        )
        self.admin = Employee.objects.create_superuser(
            username="admin",
            password="pass",
            department=self.department,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
        )
        self.employee = Employee.objects.create_user(
            username="emp1",
            password="pass",
            first_name="Alice",
            last_name="Anderson",
            department=self.department,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
        )

        self.day_one = date(2024, 5, 1)
        self.day_two = date(2024, 5, 2)

        AttDay.objects.create(
            employee=self.employee,
            date=self.day_one,
            work_min=480,
            late_min=5,
            ot_regular_min=60,
            status="present",
            anomalies={"missing_out_closed_at_next_in": 1},
        )
        AttDay.objects.create(
            employee=self.employee,
            date=self.day_two,
            status="absent",
        )

        AttPair.objects.create(
            employee=self.employee,
            date=self.day_one,
            in_event_id=100,
            out_event_id=101,
            in_ts=timezone.make_aware(datetime(2024, 5, 1, 8, 0)),
            out_ts=timezone.make_aware(datetime(2024, 5, 1, 16, 0)),
            duration_min=480,
        )

        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.day_one,
            delta_work_min=-15,
            reason="Late arrival waiver",
            created_by_id=self.admin.id,
        )

        AttDay.objects.filter(employee=self.employee, date=self.day_one).update(locked=True)

        self.factory = RequestFactory()
        self.attday_admin = AttDayAdmin(AttDay, admin.site)

    def test_calendar_view_redirects_to_current_month_when_missing(self):
        request = self.factory.get("/admin/attendance/attday/calendar/")
        request.user = self.admin
        request._cached_user = self.admin
        response = self.attday_admin.calendar_view(request)
        assert response.status_code == 302
        assert "month=" in response["Location"]

    def test_calendar_view_renders_calendar_grid(self):
        request = self.factory.get(
            "/admin/attendance/attday/calendar/",
            {
                "month": "2024-05",
                "include_pairs": "true",
                "include_adjustments": "true",
            },
        )
        request.user = self.admin
        request._cached_user = self.admin
        response = self.attday_admin.calendar_view(request)
        response.render()
        assert response.status_code == 200
        context = response.context_data
        employees = context["employees"]
        assert employees, context
        alice = next(emp for emp in employees if emp["display"] == "Alice Anderson")
        assert alice["summary"]["present"] == 1
        assert alice["summary"]["locked_days"] == 1
        rows = {row["date"]: row for row in alice["rows"]}
        may_first = rows["2024-05-01"]
        assert may_first["status_display"] == "Present"
        assert may_first["metrics"]["work_min"] == 480
        assert may_first["metrics"]["late_min"] == 5
        assert may_first["total_ot"] == 60
        assert may_first["locked"] is True
        assert may_first["pairs"]
        assert may_first["adjustments"]
        assert may_first["anomalies"] == {"missing_out_closed_at_next_in": 1}

    def test_monthly_report_form_renders(self):
        request = self.factory.get("/admin/attendance/attday/monthly-attendance-report/")
        request.user = self.admin
        request._cached_user = self.admin
        response = self.attday_admin.monthly_attendance_report(request)
        response.render()
        assert response.status_code == 200
        assert b"Monthly attendance report" in response.content

    def test_monthly_report_generates_pdf(self):
        request = self.factory.post(
            "/admin/attendance/attday/monthly-attendance-report/",
            {"month": "2024-05"},
        )
        request.user = self.admin
        request._cached_user = self.admin
        response = self.attday_admin.monthly_attendance_report(request)
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
