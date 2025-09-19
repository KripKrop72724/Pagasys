from datetime import date, datetime, time

from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.contrib import admin
from django.contrib.messages.storage.fallback import FallbackStorage

from pagasys.models import (
    Company,
    Branch,
    Department,
    Project,
    Employee,
    ShiftTemplate,
    RosterEntry,
)
from capture.models import AttendanceDevice, PunchEvent, PunchException
from attendance.models import AttDay, AttPair, AttAdjustment
from attendance.admin import AttDayAdmin, EmployeeBranchListFilter


def test_attday_admin_includes_date_filter():
    assert "date" in AttDayAdmin.list_filter
    assert AttDayAdmin.date_hierarchy == "date"


def test_attday_admin_includes_branch_filter():
    assert EmployeeBranchListFilter in AttDayAdmin.list_filter


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

        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="Day",
            start_time=time(9, 0),
            end_time=time(17, 0),
        )

        self.roster_entry = RosterEntry.objects.create(
            employee=self.employee,
            date=date(2024, 5, 1),
            shift=self.shift,
            override_start=time(9, 0),
            override_end=time(17, 0),
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
            shift=self.shift,
            roster=self.roster_entry,
        )
        AttDay.objects.create(
            employee=self.employee,
            date=self.day_two,
            status="partial",
            work_min=420,
            shift=self.shift,
        )

        self.device = AttendanceDevice.objects.create(
            company=self.company,
            name="North Gate",
            api_key="device-key-1",
        )

        self.punch_in = PunchEvent.objects.create(
            id=100,
            device=self.device,
            company=self.company,
            employee=self.employee,
            action="in",
            device_ts=timezone.make_aware(datetime(2024, 5, 1, 8, 0)),
            face_matched=True,
            requires_face=True,
            geofence_ok=True,
            roster_date=self.day_one,
        )
        self.punch_out = PunchEvent.objects.create(
            id=101,
            device=self.device,
            company=self.company,
            employee=self.employee,
            action="out",
            device_ts=timezone.make_aware(datetime(2024, 5, 1, 16, 0)),
            face_matched=False,
            requires_face=True,
            geofence_ok=False,
            geofence_rule_violation=True,
            roster_fallback=True,
            roster_date=self.day_one,
            notes="Left early",
        )
        PunchException.objects.create(
            event=self.punch_out, kind="geofence", details={"reason": "Outside"}
        )

        AttPair.objects.create(
            employee=self.employee,
            date=self.day_one,
            in_event_id=self.punch_in.id,
            out_event_id=self.punch_out.id,
            in_ts=self.punch_in.device_ts,
            out_ts=self.punch_out.device_ts,
            duration_min=480,
            anomaly={"missing_out_closed_at_next_in": True},
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
        self.client.force_login(self.admin)

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

    def test_change_view_includes_quick_adjustment_form(self):
        day = AttDay.objects.get(employee=self.employee, date=self.day_two)
        request = self.factory.get(f"/admin/attendance/attday/{day.pk}/change/")
        request.user = self.admin
        request._cached_user = self.admin
        response = self.attday_admin.changeform_view(request, str(day.pk))
        response.render()
        assert response.context_data["quick_adjustment_target"] == day
        form = response.context_data["quick_adjustment_form"]
        assert form is not None
        url = response.context_data["quick_adjustment_url"]
        assert url.endswith(f"/{day.pk}/add-adjustment/")

    def test_change_view_includes_related_context(self):
        day = AttDay.objects.get(employee=self.employee, date=self.day_one)
        request = self.factory.get(f"/admin/attendance/attday/{day.pk}/change/")
        request.user = self.admin
        request._cached_user = self.admin
        day_with_select = self.attday_admin.get_queryset(request).get(pk=day.pk)

        with self.assertNumQueries(2):
            related = self.attday_admin._build_day_related_context(day_with_select)

        assert "roster_overview" in related
        assert related["roster_overview"]["shift"]["name"] == self.shift.name
        assert related["roster_overview"]["roster"]["id"] == self.roster_entry.id

        pairs = related["pair_sessions"]
        assert len(pairs) == 1
        assert pairs[0]["in_event_id"] == self.punch_in.id
        assert pairs[0]["anomalies"] == ["missing_out_closed_at_next_in"]

        punches = related["punch_events"]
        assert [event["id"] for event in punches] == [self.punch_in.id, self.punch_out.id]
        assert punches[-1]["exception"]["kind"] == "geofence"

        response = self.attday_admin.changeform_view(request, str(day.pk))
        response.render()
        context = response.context_data
        assert context["roster_overview"]["shift"]["name"] == self.shift.name
        assert context["pair_sessions"][0]["out_event_id"] == self.punch_out.id
        assert context["punch_events"][0]["device_label"] == str(self.device)

    def test_add_adjustment_view_creates_record(self):
        day = AttDay.objects.get(employee=self.employee, date=self.day_two)
        request = self.factory.post(
            f"/admin/attendance/attday/{day.pk}/add-adjustment/",
            {"delta_work_min": 30, "reason": "Quick fix"},
        )
        request.user = self.admin
        request._cached_user = self.admin
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        response = self.attday_admin.add_adjustment_view(request, str(day.pk))
        assert response.status_code == 302
        created = AttAdjustment.objects.filter(
            employee=self.employee, date=self.day_two, reason="Quick fix"
        ).latest("id")
        assert created.delta_work_min == 30
        assert created.created_by_id == self.admin.id

    def test_add_adjustment_view_marks_full_attendance(self):
        day = AttDay.objects.get(employee=self.employee, date=self.day_two)
        request = self.factory.post(
            f"/admin/attendance/attday/{day.pk}/add-adjustment/",
            {"mark_full_attendance": "on", "reason": "Fill to full day"},
        )
        request.user = self.admin
        request._cached_user = self.admin
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        response = self.attday_admin.add_adjustment_view(request, str(day.pk))
        assert response.status_code == 302
        created = AttAdjustment.objects.filter(
            employee=self.employee, date=self.day_two, reason="Fill to full day"
        ).latest("id")
        assert created.delta_work_min == 60
