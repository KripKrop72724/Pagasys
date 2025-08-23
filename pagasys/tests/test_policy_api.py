from rest_framework.test import APIClient
from django.test import TestCase
from pagasys.models import Company, WorkCalendar, Holiday, ShiftTemplate, ShiftRule, RosterEntry, Employee, Department, Branch

class PolicyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.user = Employee.objects.create_user(
            username="u1", password="pass", department=self.department,
            hire_date="2024-01-01", employment_type="permanent",
            visa_type="personal"
        )
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
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="personal",
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
