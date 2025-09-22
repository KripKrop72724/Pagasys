from datetime import date

from rest_framework.test import APIClient
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from unittest.mock import patch
from pagasys.models import (
    Company,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    Employee,
    Department,
    Branch,
    TradeLicense,
)

@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_BROKER_URL="memory://")
class PolicyApiTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company, license_no="L1", issued_date="2024-01-01", expiry_date="2099-01-01", max_visas=5,
        )
        self.license.branches.set([self.branch])
        self.user = Employee.objects.create_user(
            username="u1", password="pass", department=self.department, trade_license=self.license,
            hire_date="2024-01-01", employment_type="permanent",
            visa_type="company"
        )
        admin_group = Group.objects.get(name="Company Admin")
        self.user.groups.add(admin_group)
        self.client.force_authenticate(self.user)

    def test_workcalendar_cross_company_post_forbidden(self):
        other = Company.objects.create(name="C2")
        payload = {"name": "X"}
        resp = self.client.post(
            f"/api/companies/{other.id}/work-calendars/", payload, format="json"
        )
        assert resp.status_code == 403

    def test_workcalendar_cross_company_list_forbidden(self):
        other = Company.objects.create(name="C2")
        resp = self.client.get(f"/api/companies/{other.id}/work-calendars/")
        assert resp.status_code in (403, 404)

    def test_workcalendar_company_injected_on_create(self):
        resp = self.client.post(
            f"/api/companies/{self.company.id}/work-calendars/",
            {"name": "Cal"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["company"] == self.company.id

    def test_workcalendar_filter_is_default(self):
        WorkCalendar.objects.create(company=self.company, name="Cal1", is_default=True)
        WorkCalendar.objects.create(company=self.company, name="Cal2", is_default=False)
        resp = self.client.get(
            f"/api/companies/{self.company.id}/work-calendars/?is_default=true"
        )
        assert resp.status_code == 200
        names = [item["name"] for item in resp.data["results"]]
        assert names == ["Cal1"]

    def test_workcalendar_holidays_subroute_filter(self):
        cal = WorkCalendar.objects.create(company=self.company, name="Cal")
        Holiday.objects.create(calendar=cal, date="2024-01-01", name="NY")
        Holiday.objects.create(calendar=cal, date="2024-02-01", name="Feb")
        url = f"/api/companies/{self.company.id}/work-calendars/{cal.id}/holidays/?date_from=2024-01-15"
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["name"] == "Feb"

    def test_import_holidays_upsert(self):
        cal = WorkCalendar.objects.create(company=self.company, name="Cal")
        Holiday.objects.create(calendar=cal, date="2024-01-01", name="Old")
        payload = [
            {"date": "2024-01-01", "name": "New1"},
            {"date": "2024-01-01", "name": "New2"},
        ]
        resp = self.client.post(
            f"/api/companies/{self.company.id}/work-calendars/{cal.id}/holidays/import/",
            payload,
            format="json",
        )
        assert resp.status_code == 200 and resp.data["count"] == 2
        holidays = Holiday.objects.filter(calendar=cal, date="2024-01-01")
        assert holidays.count() == 1
        assert holidays.first().name == "New2"

    def test_workcalendar_list_scoped(self):
        c2 = Company.objects.create(name="C2")
        WorkCalendar.objects.create(company=self.company, name="Cal1")
        WorkCalendar.objects.create(company=c2, name="Cal2")
        resp = self.client.get(f"/api/companies/{self.company.id}/work-calendars/")
        assert resp.status_code == 200
        ids = [item["name"] for item in resp.data["results"]]
        assert ids == ["Cal1"]

    def test_holiday_filter_range(self):
        cal = WorkCalendar.objects.create(company=self.company, name="Cal")
        Holiday.objects.create(calendar=cal, date="2024-01-01", name="NY")
        Holiday.objects.create(calendar=cal, date="2024-02-01", name="Feb")
        url = f"/api/companies/{self.company.id}/holidays/?date_from=2024-01-15"
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["name"] == "Feb"

    def test_holiday_cannot_use_other_company_calendar(self):
        other = Company.objects.create(name="C2")
        other_cal = WorkCalendar.objects.create(company=other, name="OtherCal")
        payload = {
            "calendar": other_cal.id,
            "date": "2024-03-01",
            "name": "Bad",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/holidays/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert "calendar" in resp.data["errors"]

    def test_shift_rule_validate_normalizes_weekdays(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift", start_time="09:00", end_time="17:00"
        )
        payload = {
            "shift": st.id,
            "kind": "max_daily_hours",
            "value": "10",
            "weekdays": "mon,tue"
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/shift-rules/validate/", payload, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["normalized"]["weekdays"] == "MON,TUE"

    def test_shift_rule_cannot_use_other_company_shift(self):
        other = Company.objects.create(name="C2")
        st_other = ShiftTemplate.objects.create(
            company=other, name="Other", start_time="09:00", end_time="17:00"
        )
        payload = {
            "shift": st_other.id,
            "kind": "max_daily_hours",
            "value": "8",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/shift-rules/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert "shift" in resp.data["errors"]

    def test_roster_bulk_upsert_and_summary(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift", start_time="09:00", end_time="17:00"
        )
        entries = {
            "entries": [
                {"employee": self.user.id, "date": "2024-03-01", "shift": st.id},
                {"employee": self.user.id, "date": "2024-03-02", "shift": st.id, "is_rest_day": True},
            ]
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/bulk-upsert/", entries, format="json"
        )
        assert resp.status_code == 200 and resp.data["upserted"] == 2
        resp = self.client.get(
            f"/api/companies/{self.company.id}/roster/summary/?group_by=shift"
        )
        assert resp.status_code == 200
        days = sum(item["days"] for item in resp.data)
        rest_days = sum(item["rest_days"] for item in resp.data)
        assert days == 2 and rest_days == 1

    def test_error_shape_from_bulk_upsert(self):
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/bulk-upsert/",
            {"entries": []},
            format="json",
        )
        assert resp.status_code == 400
        assert "detail" in resp.data and "errors" in resp.data

    def test_shift_template_cross_midnight_validation(self):
        payload = {
            "name": "Night",
            "start_time": "17:00",
            "end_time": "09:00",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/shift-templates/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert "Validation" in resp.data["detail"]
        assert "end_time" in str(resp.data["errors"])

    def test_shift_template_response_includes_total_minutes(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Day",
            start_time="09:00",
            end_time="17:00",
            break_minutes=60,
        )
        resp = self.client.get(
            f"/api/companies/{self.company.id}/shift-templates/{st.id}/"
        )
        assert resp.status_code == 200
        assert resp.data["total_minutes"] == 420

    def test_shift_template_total_minutes_is_read_only(self):
        payload = {
            "name": "WithTotal",
            "start_time": "09:00",
            "end_time": "17:00",
            "break_minutes": 30,
            "total_minutes": 999,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/shift-templates/",
            payload,
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["total_minutes"] == 450

    def test_shift_rule_validate_rejects_bad_weekday(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "shift": st.id,
            "kind": "max_daily_hours",
            "value": "10",
            "weekdays": "foo",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/shift-rules/validate/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert "weekdays" in str(resp.data["errors"])

    def test_roster_override_end_outside_window(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "date": "2024-04-01",
            "shift": st.id,
            "override_end": "02:00",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert "override_end" in str(resp.data["errors"])

    def test_roster_employee_shift_company_mismatch(self):
        other = Company.objects.create(name="C2")
        st_other = ShiftTemplate.objects.create(
            company=other,
            name="Other",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "date": "2024-04-02",
            "shift": st_other.id,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            payload,
            format="json",
        )
        assert resp.status_code == 400

    def test_roster_bulk_upsert_dedup(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "entries": [
                {"employee": self.user.id, "date": "2024-05-01", "shift": st.id},
                {"employee": self.user.id, "date": "2024-05-01", "shift": st.id},
            ]
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/bulk-upsert/",
            payload,
            format="json",
        )
        assert resp.status_code == 200
        assert RosterEntry.objects.count() == 1

    def test_roster_bulk_upsert_atomic_failure(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        other = Company.objects.create(name="C2")
        st_other = ShiftTemplate.objects.create(
            company=other,
            name="Other",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "entries": [
                {"employee": self.user.id, "date": "2024-05-02", "shift": st.id},
                {"employee": self.user.id, "date": "2024-05-03", "shift": st_other.id},
            ]
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/bulk-upsert/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert RosterEntry.objects.count() == 0

    def test_roster_list_filters(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        branch2 = Branch.objects.create(company=self.company, name="B2")
        dept2 = Department.objects.create(branch=branch2, name="D2")
        emp2 = Employee.objects.create_user(
            username="u2",
            password="pass",
            department=dept2,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        RosterEntry.objects.create(employee=self.user, date="2024-06-01", shift=st)
        RosterEntry.objects.create(
            employee=emp2,
            date="2024-06-02",
            shift=st,
            is_rest_day=True,
        )
        url = (
            f"/api/companies/{self.company.id}/roster/"
            "?date_from=2024-06-02&date_to=2024-06-02"
            f"&branch={branch2.id}&is_rest_day=true"
        )
        resp = self.client.get(url)
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["employee"] == emp2.id

    def test_leave_type_unique_code(self):
        payload = {"code": "VAC", "name": "Vacation"}
        resp1 = self.client.post(
            f"/api/companies/{self.company.id}/leave-types/",
            payload,
            format="json",
        )
        assert resp1.status_code == 201
        resp2 = self.client.post(
            f"/api/companies/{self.company.id}/leave-types/",
            payload,
            format="json",
        )
        assert resp2.status_code == 400

    def test_leave_type_search(self):
        self.client.post(
            f"/api/companies/{self.company.id}/leave-types/",
            {"code": "VAC", "name": "Vacation"},
            format="json",
        )
        self.client.post(
            f"/api/companies/{self.company.id}/leave-types/",
            {"code": "SICK", "name": "Sick"},
            format="json",
        )
        resp = self.client.get(
            f"/api/companies/{self.company.id}/leave-types/?search=VAC"
        )
        assert resp.status_code == 200
        codes = [item["code"] for item in resp.data["results"]]
        assert codes == ["VAC"]

    def test_roster_schedule_range_days_with_rest(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 7,
            "rest_weekdays": ["SAT", "SUN"],
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 200 and resp.data["count"] == 7
        sat = RosterEntry.objects.get(date="2024-07-06")
        sun = RosterEntry.objects.get(date="2024-07-07")
        assert sat.is_rest_day and sun.is_rest_day

    def test_roster_schedule_range_until(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "shift": st.id,
            "start_date": "2024-07-01",
            "until": "2024-07-03",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 200 and resp.data["count"] == 3
        assert RosterEntry.objects.filter(employee=self.user).count() == 3

    def test_roster_schedule_range_invalid_weekday(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 3,
            "rest_weekdays": ["FUNDAY"],
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 400

    def test_roster_schedule_range_multiple_employees(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        other = Employee.objects.create_user(
            username="u2",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        payload = {
            "employees": [self.user.id, other.id],
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 2,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 200 and resp.data["count"] == 4
        assert RosterEntry.objects.filter(employee=self.user).count() == 2
        assert RosterEntry.objects.filter(employee=other).count() == 2

    def test_roster_schedule_range_requires_employee_or_employees(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload_missing = {
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 1,
        }
        resp1 = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload_missing,
            format="json",
        )
        assert resp1.status_code == 400
        payload_both = {
            "employee": self.user.id,
            "employees": [self.user.id],
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 1,
        }
        resp2 = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload_both,
            format="json",
        )
        assert resp2.status_code == 400

    def test_roster_schedule_range_rejects_empty_employees(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employees": [],
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 1,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["detail"] == "Validation error"
        errors = [str(err) for err in resp.data["errors"].get("non_field_errors", [])]
        assert "employees must contain at least one ID" in errors

    @patch("pagasys.policy.views.schedule_range_bulk.delay")
    def test_roster_schedule_range_bulk_async(self, mock_delay):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        other = Employee.objects.create_user(
            username="u2",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        payload = {
            "employees": [self.user.id, other.id],
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 1,
        }
        with patch("pagasys.policy.views.ASYNC_BULK_THRESHOLD", 1):
            resp = self.client.post(
                f"/api/companies/{self.company.id}/roster/schedule-range/",
                payload,
                format="json",
            )
        assert resp.status_code == 202
        mock_delay.assert_called_once()
        assert RosterEntry.objects.count() == 0

    def test_roster_schedule_range_requires_days_or_until(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "shift": st.id,
            "start_date": "2024-07-01",
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 400

    def test_roster_schedule_range_deduplicates_employee_ids(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employees": [self.user.id, self.user.id],
            "shift": st.id,
            "start_date": "2024-07-01",
            "days": 2,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["count"] == 2
        assert RosterEntry.objects.filter(employee=self.user).count() == 2

    def test_roster_schedule_range_upsert(self):
        st1 = ShiftTemplate.objects.create(
            company=self.company,
            name="S1",
            start_time="09:00",
            end_time="17:00",
        )
        st2 = ShiftTemplate.objects.create(
            company=self.company,
            name="S2",
            start_time="10:00",
            end_time="18:00",
        )
        payload1 = {
            "employee": self.user.id,
            "shift": st1.id,
            "start_date": "2024-07-01",
            "days": 2,
        }
        payload2 = {
            "employee": self.user.id,
            "shift": st2.id,
            "start_date": "2024-07-01",
            "days": 2,
        }
        self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload1,
            format="json",
        )
        self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload2,
            format="json",
        )
        assert RosterEntry.objects.filter(employee=self.user).count() == 2
        assert RosterEntry.objects.filter(shift=st2).count() == 2

    def test_schedule_range_marks_holidays(self):
        cal = WorkCalendar.objects.create(
            company=self.company, name="Cal", is_default=True
        )
        Holiday.objects.create(calendar=cal, date="2024-07-04", name="H1")
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "employee": self.user.id,
            "shift": st.id,
            "start_date": "2024-07-03",
            "days": 3,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 200
        entry = RosterEntry.objects.get(employee=self.user, date="2024-07-04")
        assert entry.is_holiday and entry.was_holiday

    def test_schedule_range_rejects_out_of_scope_shift(self):
        other = Company.objects.create(name="C2")
        st_other = ShiftTemplate.objects.create(
            company=other, name="Other", start_time="09:00", end_time="17:00"
        )
        payload = {
            "employee": self.user.id,
            "shift": st_other.id,
            "start_date": "2024-07-01",
            "days": 1,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/schedule-range/",
            payload,
            format="json",
        )
        assert resp.status_code == 400

    def test_roster_schedule_range_query_count_constant(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        other1 = Employee.objects.create_user(
            username="u2",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        other2 = Employee.objects.create_user(
            username="u3",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        employee_map = {e.id: e for e in (self.user, other1, other2)}
        shift_map = {st.id: st}

        class DummyRosterEntrySerializer:
            def __init__(self, instance=None, data=None, context=None, **kwargs):
                self.instance = instance
                self.context = context
                payload = data or {}
                self.validated_data = dict(payload)
                emp_id = self.validated_data.get("employee")
                if emp_id is not None:
                    self.validated_data["employee"] = employee_map[emp_id]
                shift_id = self.validated_data.get("shift")
                if shift_id is not None:
                    self.validated_data["shift"] = shift_map[shift_id]

            def is_valid(self, raise_exception=False):
                return True

        class DummyRosterRangeSerializer:
            def __init__(self, data=None, context=None):
                self.data = data or {}
                self.context = context or {}
                self._validated = False

            def is_valid(self, raise_exception=False):
                self._validated = True
                return True

            @property
            def validated_data(self):
                assert self._validated
                employees = [employee_map[eid] for eid in self.data.get("employees", [])]
                seen = set()
                unique = []
                for emp in employees:
                    if emp.id not in seen:
                        seen.add(emp.id)
                        unique.append(emp)
                result = {
                    "employees": unique,
                    "shift": shift_map[self.data["shift"]],
                    "start_date": date.fromisoformat(self.data["start_date"]),
                }
                if "days" in self.data:
                    result["days"] = self.data["days"]
                if "until" in self.data:
                    result["until"] = date.fromisoformat(self.data["until"])
                if "rest_weekdays" in self.data:
                    result["rest_weekdays"] = self.data["rest_weekdays"]
                return result

        with patch("pagasys.policy.views.holiday_flags", return_value=(False, False)), patch(
            "pagasys.policy.views.RosterViewSet.serializer_class", DummyRosterEntrySerializer
        ), patch("pagasys.policy.views.RosterRangeSerializer", DummyRosterRangeSerializer):
            payload_single = {
                "employees": [self.user.id],
                "shift": st.id,
                "start_date": "2024-07-01",
                "days": 1,
            }
            with CaptureQueriesContext(connection) as ctx_single:
                resp1 = self.client.post(
                    f"/api/companies/{self.company.id}/roster/schedule-range/",
                    payload_single,
                    format="json",
                )
            assert resp1.status_code == 200
            RosterEntry.objects.all().delete()
            payload_many = {
                "employees": [self.user.id, other1.id, other2.id],
                "shift": st.id,
                "start_date": "2024-07-01",
                "days": 5,
            }
            with CaptureQueriesContext(connection) as ctx_many:
                resp2 = self.client.post(
                    f"/api/companies/{self.company.id}/roster/schedule-range/",
                    payload_many,
                    format="json",
                )
            assert resp2.status_code == 200
            assert len(ctx_single) == len(ctx_many)

    def test_roster_single_create_and_update_holiday_flags(self):
        cal = WorkCalendar.objects.create(
            company=self.company, name="Cal", is_default=True
        )
        Holiday.objects.create(calendar=cal, date="2024-08-10", name="HX")
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        # create with explicit override on holiday
        payload = {
            "employee": self.user.id,
            "date": "2024-08-10",
            "shift": st.id,
            "is_holiday": False,
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/",
            payload,
            format="json",
        )
        assert resp.status_code == 201
        entry = RosterEntry.objects.get(employee=self.user, date="2024-08-10")
        assert not entry.is_holiday and entry.was_holiday
        # update without explicit override but changing date to non-holiday
        payload2 = {"date": "2024-08-11"}
        resp2 = self.client.patch(
            f"/api/companies/{self.company.id}/roster/{entry.id}/",
            payload2,
            format="json",
        )
        assert resp2.status_code == 200
        entry.refresh_from_db()
        assert not entry.is_holiday and not entry.was_holiday
        # update with override True
        resp3 = self.client.patch(
            f"/api/companies/{self.company.id}/roster/{entry.id}/",
            {"is_holiday": True},
            format="json",
        )
        assert resp3.status_code == 200
        entry.refresh_from_db()
        assert entry.is_holiday and not entry.was_holiday

    def test_bulk_upsert_holiday_combinations(self):
        cal = WorkCalendar.objects.create(
            company=self.company, name="Cal", is_default=True
        )
        Holiday.objects.create(calendar=cal, date="2024-07-04", name="H1")
        Holiday.objects.create(calendar=cal, date="2024-07-05", name="H2")
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        payload = {
            "entries": [
                {"employee": self.user.id, "shift": st.id, "date": "2024-07-04"},
                {
                    "employee": self.user.id,
                    "shift": st.id,
                    "date": "2024-07-05",
                    "is_holiday": False,
                },
                {
                    "employee": self.user.id,
                    "shift": st.id,
                    "date": "2024-07-06",
                    "is_holiday": True,
                },
            ]
        }
        resp = self.client.post(
            f"/api/companies/{self.company.id}/roster/bulk-upsert/",
            payload,
            format="json",
        )
        assert resp.status_code == 200
        hol = RosterEntry.objects.get(employee=self.user, date="2024-07-04")
        overridden = RosterEntry.objects.get(employee=self.user, date="2024-07-05")
        manual = RosterEntry.objects.get(employee=self.user, date="2024-07-06")
        assert hol.is_holiday and hol.was_holiday
        assert not overridden.is_holiday and overridden.was_holiday
        assert manual.is_holiday and not manual.was_holiday

    def test_shift_template_filters_search_ordering(self):
        ShiftTemplate.objects.create(
            company=self.company,
            name="Morning",
            start_time="09:00",
            end_time="17:00",
            rounding_min=0,
            cross_midnight=False,
            requires_face=False,
        )
        ShiftTemplate.objects.create(
            company=self.company,
            name="Night",
            start_time="21:00",
            end_time="05:00",
            cross_midnight=True,
            requires_face=False,
            rounding_min=15,
        )
        ShiftTemplate.objects.create(
            company=self.company,
            name="Night Face",
            start_time="21:00",
            end_time="05:00",
            cross_midnight=True,
            requires_face=True,
            rounding_min=15,
        )
        url = (
            f"/api/companies/{self.company.id}/shift-templates/?cross_midnight=true"
            "&requires_face=true&rounding_min=15&search=Night&ordering=-name"
        )
        resp = self.client.get(url)
        assert resp.status_code == 200
        names = [item["name"] for item in resp.data["results"]]
        assert names == ["Night Face"]
        url = (
            f"/api/companies/{self.company.id}/shift-templates/?cross_midnight=true"
            "&search=Night&ordering=-name"
        )
        resp = self.client.get(url)
        assert [item["name"] for item in resp.data["results"]] == ["Night Face", "Night"]

    def test_shift_rule_filters_and_ordering(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        r1 = ShiftRule.objects.create(
            shift=st,
            kind="k1",
            value="1",
            active_from="2024-01-01",
            active_to="2024-01-31",
            weekdays="MON",
        )
        r2 = ShiftRule.objects.create(
            shift=st,
            kind="k1",
            value="2",
            active_from="2024-02-01",
            active_to="2024-02-28",
            weekdays="TUE",
        )
        r3 = ShiftRule.objects.create(shift=st, kind="k2", value="3")
        resp = self.client.get(
            f"/api/companies/{self.company.id}/shift-rules/?shift={st.id}&kind=k1&ordering=-active_from"
        )
        assert [item["id"] for item in resp.data["results"]] == [r2.id, r1.id]
        resp = self.client.get(
            f"/api/companies/{self.company.id}/shift-rules/?active_on=2024-02-15&kind=k1"
        )
        assert [item["id"] for item in resp.data["results"]] == [r2.id]
        resp = self.client.get(
            f"/api/companies/{self.company.id}/shift-rules/?weekday=TUE"
        )
        assert [item["id"] for item in resp.data["results"]] == [r2.id, r3.id]
        resp = self.client.get(
            f"/api/companies/{self.company.id}/shift-rules/?weekday=FUNDAY"
        )
        assert resp.data["results"] == []
