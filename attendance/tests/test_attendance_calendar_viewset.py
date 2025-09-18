from datetime import date, datetime, time
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from pagasys.models import Company, Branch, Department, Project, Employee, ShiftTemplate
from attendance.models import AttDay, AttPair, AttAdjustment

from attendance.services import PDF_DAY_COLUMNS, build_monthly_calendar


class AttendanceCalendarViewSetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
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
        self.employee_dept = Employee.objects.create_user(
            username="emp1",
            password="pass",
            first_name="Alice",
            last_name="Anderson",
            department=self.department,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
        )
        self.employee_proj = Employee.objects.create_user(
            username="emp2",
            password="pass",
            first_name="Bob",
            last_name="Brown",
            project=self.project,
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
        self.day_one = date(2024, 5, 1)
        self.day_two = date(2024, 5, 2)

        AttDay.objects.create(
            employee=self.employee_dept,
            date=self.day_one,
            work_min=480,
            late_min=5,
            ot_regular_min=60,
            status="present",
            locked=False,
            anomalies={"missing_out_closed_at_next_in": 1},
            shift=self.shift,
        )
        AttDay.objects.create(
            employee=self.employee_dept,
            date=self.day_two,
            status="absent",
            shift=self.shift,
        )
        AttDay.objects.create(
            employee=self.employee_proj,
            date=self.day_one,
            work_min=420,
            status="present",
            shift=self.shift,
        )
        AttDay.objects.create(
            employee=self.employee_proj,
            date=self.day_two,
            status="rest",
            shift=self.shift,
        )

        AttPair.objects.create(
            employee=self.employee_dept,
            date=self.day_one,
            in_event_id=101,
            out_event_id=102,
            in_ts=timezone.make_aware(datetime(2024, 5, 1, 8, 0)),
            out_ts=timezone.make_aware(datetime(2024, 5, 1, 16, 0)),
            duration_min=480,
        )

        AttAdjustment.objects.create(
            employee=self.employee_dept,
            date=self.day_one,
            delta_work_min=-15,
            reason="Late arrival waiver",
            created_by_id=self.admin.id,
        )

        AttDay.objects.filter(employee=self.employee_dept, date=self.day_one).update(locked=True)

        self.client.force_authenticate(self.admin)

    def _list_url(self):
        return reverse(
            "attendance-calendar-list", kwargs={"company_id": self.company.id}
        )

    def _detail_url(self, employee):
        return reverse(
            "attendance-calendar-detail",
            kwargs={"company_id": self.company.id, "pk": employee.id},
        )

    def _lock_url(self):
        return reverse(
            "attendance-calendar-lock", kwargs={"company_id": self.company.id}
        )

    def _adjustments_url(self):
        return reverse(
            "attendance-calendar-adjustments",
            kwargs={"company_id": self.company.id},
        )

    def test_calendar_list_returns_month_grid_with_summaries(self):
        response = self.client.get(self._list_url(), {"month": "2024-05"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["month"] == "2024-05"
        assert payload["days"][0] == "2024-05-01"
        employees = {item["id"]: item for item in payload["employees"]}
        assert set(employees.keys()) == {self.employee_dept.id, self.employee_proj.id}
        dept_day = next(
            row
            for row in employees[self.employee_dept.id]["rows"]
            if row["date"] == "2024-05-01"
        )
        assert dept_day["status"] == "present"
        assert dept_day["locked"] is True
        assert dept_day["locked_reason"]
        assert dept_day["metrics"]["work_min"] == 480
        assert dept_day["metrics"]["late_min"] == 5
        assert dept_day["metrics"]["ot_regular_min"] == 60
        assert dept_day["anomalies"] == {"missing_out_closed_at_next_in": 1}
        summary = employees[self.employee_dept.id]["summary"]
        assert summary["present"] == 1
        assert summary["absent"] == 1
        assert summary["locked_days"] == 1
        assert summary["total_ot_min"] == 60

    def test_calendar_list_includes_pairs_and_adjustments_when_requested(self):
        response = self.client.get(
            self._list_url(),
            {
                "month": "2024-05",
                "include_pairs": "true",
                "include_adjustments": "true",
                "include_anomalies": "false",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        employees = {item["id"]: item for item in payload["employees"]}
        row = next(
            r
            for r in employees[self.employee_dept.id]["rows"]
            if r["date"] == "2024-05-01"
        )
        assert "pairs" in row and len(row["pairs"]) == 1
        assert "adjustments" in row and len(row["adjustments"]) == 1
        assert "anomalies" not in row

    def test_calendar_list_search_filters_employees(self):
        response = self.client.get(
            self._list_url(),
            {
                "month": "2024-05",
                "search": "Alice",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        ids = [emp["id"] for emp in payload["employees"]]
        assert ids == [self.employee_dept.id]

        response = self.client.get(
            self._list_url(),
            {
                "month": "2024-05",
                "search": "alice ops",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        ids = [emp["id"] for emp in payload["employees"]]
        assert ids == [self.employee_dept.id]

        response = self.client.get(
            self._list_url(),
            {
                "month": "2024-05",
                "search": "Site",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        ids = [emp["id"] for emp in payload["employees"]]
        assert ids == [self.employee_proj.id]

    def test_calendar_list_all_param_disables_pagination(self):
        extra_employees = [
            Employee.objects.create_user(
                username=f"bulk{i}",
                password="pass",
                first_name=f"Extra{i}",
                last_name="User",
                department=self.department,
                hire_date=date(2024, 1, 1),
                employment_type="permanent",
                visa_type="personal",
            )
            for i in range(3)
        ]

        with mock.patch("attendance.views.CALENDAR_PAGE_SIZE", 1), mock.patch(
            "attendance.views.AttendanceCalendarPagination.page_size",
            1,
        ):
            paginated = self.client.get(
                self._list_url(),
                {"month": "2024-05"},
            )
            assert paginated.status_code == 200
            payload = paginated.json()
            assert len(payload["employees"]) == 1
            assert payload.get("next")

            unpaginated = self.client.get(
                self._list_url(),
                {"month": "2024-05", "all": "true"},
            )
            assert unpaginated.status_code == 200
            payload_all = unpaginated.json()
            expected_count = Employee.objects.filter(is_superuser=False).count()
            assert len(payload_all["employees"]) == expected_count
            assert "next" not in payload_all

        for employee in extra_employees:
            employee.delete()

    def test_calendar_stats_only_returns_empty_rows(self):
        response = self.client.get(
            self._list_url(),
            {
                "month": "2024-05",
                "stats_only": "true",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert all(emp["rows"] == [] for emp in payload["employees"])
        employees = {item["id"]: item for item in payload["employees"]}
        assert employees[self.employee_dept.id]["summary"]["present"] == 1

    def test_calendar_detail_focuses_on_single_employee(self):
        response = self.client.get(
            self._detail_url(self.employee_dept),
            {"month": "2024-05", "include_pairs": "true"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["employees"]) == 1
        assert payload["employees"][0]["id"] == self.employee_dept.id

    def test_calendar_lock_action_updates_days(self):
        day = AttDay.objects.get(employee=self.employee_proj, date=self.day_one)
        assert day.locked is False
        response = self.client.post(
            self._lock_url(),
            {
                "start": "2024-05-01",
                "end": "2024-05-02",
                "employee_ids": [self.employee_proj.id],
                "locked": True,
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["updated"] == 2
        day.refresh_from_db()
        assert day.locked is True

    def test_calendar_adjustments_action_creates_record(self):
        response = self.client.post(
            self._adjustments_url(),
            {
                "employee": self.employee_proj.id,
                "date": "2024-05-01",
                "delta_work_min": 15,
                "reason": "Manual correction",
            },
            format="json",
        )
        assert response.status_code == 201
        created = AttAdjustment.objects.filter(employee=self.employee_proj).latest("id")
        assert created.delta_work_min == 15
        assert created.created_by_id == self.admin.id

    def test_calendar_adjustments_action_marks_full_attendance(self):
        response = self.client.post(
            self._adjustments_url(),
            {
                "employee": self.employee_proj.id,
                "date": "2024-05-01",
                "mark_full_attendance": True,
                "reason": "Grant full shift credit",
            },
            format="json",
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["delta_work_min"] == 60
        created = AttAdjustment.objects.filter(employee=self.employee_proj).latest("id")
        assert created.delta_work_min == 60

    def test_build_monthly_calendar_report_structure(self):
        result = build_monthly_calendar(
            [self.employee_dept, self.employee_proj],
            "2024-05",
            user=self.admin,
            include_pairs=True,
            include_adjustments=True,
            include_anomalies=True,
        )
        payload = result["payload"]
        assert payload["month"] == "2024-05"
        assert len(payload["days"]) == 31
        report = result["report"]
        assert report["month_label"] == "May 2024"
        assert report["legend_totals"]
        branch_names = [branch["name"] for branch in report["branch_list"]]
        assert self.branch.name in branch_names
        branch = report["branch_list"][branch_names.index(self.branch.name)]
        first_employee = branch["employees"][0]
        glyphs = {cell["glyph"] for cell in first_employee["rows"]}
        assert "P" in glyphs
        assert "-" in glyphs
        classes = {cell["css_class"] for cell in first_employee["rows"]}
        assert any("status-present" in value for value in classes)
        assert branch["legend_totals"][0]["count"] >= 0
        tables = branch.get("tables")
        assert tables
        layout = report["day_column_layout"]
        assert len(tables) == len(layout)
        assert layout == [16, 15]
        assert all(len(table["days"]) == expected for table, expected in zip(tables, layout))
        assert all(len(table["days"]) <= PDF_DAY_COLUMNS for table in tables)
        total_days = sum(len(table["days"]) for table in tables)
        assert total_days == len(report["days"])
        for table, expected in zip(tables, layout):
            for employee in table["employees"]:
                assert len(employee["cells"]) == expected

    def test_monthly_calendar_uses_two_pages_for_month_lengths(self):
        scenarios = [
            ("2024-04", [15, 15]),
            ("2024-02", [15, 14]),
            ("2023-02", [14, 14]),
        ]
        for month, expected_layout in scenarios:
            result = build_monthly_calendar(
                [self.employee_dept, self.employee_proj],
                month,
                user=self.admin,
            )
            report = result["report"]
            assert report["day_column_layout"] == expected_layout
            assert len(report["day_column_layout"]) <= 2

    def test_monthly_report_pdf_endpoint(self):
        url = reverse(
            "attendance-calendar-monthly-report",
            kwargs={"company_id": self.company.id},
        )
        response = self.client.get(url, {"month": "2024-05"})
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert "monthly_attendance_2024-05.pdf" in response["Content-Disposition"]
        assert len(response.content) > 500

    def test_monthly_report_rejects_invalid_month(self):
        url = reverse(
            "attendance-calendar-monthly-report",
            kwargs={"company_id": self.company.id},
        )
        response = self.client.get(url, {"month": "not-a-month"})
        assert response.status_code == 400

    def test_monthly_report_handles_many_employees(self):
        for idx in range(15):
            employee = Employee.objects.create_user(
                username=f"bulk{idx}",
                password="pass",
                department=self.department,
                hire_date=date(2024, 1, 1),
                employment_type="permanent",
                visa_type="personal",
            )
            AttDay.objects.create(
                employee=employee,
                date=self.day_one,
                status="present",
            )
        url = reverse(
            "attendance-calendar-monthly-report",
            kwargs={"company_id": self.company.id},
        )
        response = self.client.get(url, {"month": "2024-05"})
        assert response.status_code == 200
        assert len(response.content) > 1500
