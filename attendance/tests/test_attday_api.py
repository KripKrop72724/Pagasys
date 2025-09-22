from datetime import date, datetime, time

from django.urls import reverse
from django.utils import timezone
from django.test import TestCase

from rest_framework.test import APIClient

from pagasys.models import (
    Company,
    Branch,
    Department,
    Employee,
    ShiftTemplate,
    RosterEntry,
)
from capture.models import AttendanceDevice, PunchEvent, PunchException

from attendance.models import AttDay, AttPair, AttAdjustment


class AttDayFullContextAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.company = Company.objects.create(name="ACME")
        self.branch = Branch.objects.create(company=self.company, name="HQ")
        self.department = Department.objects.create(branch=self.branch, name="Ops")

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
            requires_face=True,
            break_minutes=60,
        )

        self.roster_entry = RosterEntry.objects.create(
            employee=self.employee,
            date=date(2024, 5, 20),
            shift=self.shift,
            override_start=time(9, 0),
            override_end=time(17, 0),
        )

        self.att_day = AttDay.objects.create(
            employee=self.employee,
            date=date(2024, 5, 20),
            work_min=480,
            unpaid_break_min=60,
            late_min=5,
            ot_regular_min=30,
            status="present",
            anomalies={"missing_out_closed_at_next_in": 1},
            shift=self.shift,
            roster=self.roster_entry,
        )

        device = AttendanceDevice.objects.create(
            company=self.company,
            name="North Gate",
            api_key="device-key-1",
        )
        self.punch_in = PunchEvent.objects.create(
            id=200,
            device=device,
            company=self.company,
            employee=self.employee,
            action="in",
            device_ts=timezone.make_aware(datetime(2024, 5, 20, 8, 0)),
            face_matched=True,
            requires_face=True,
            geofence_ok=True,
            roster_date=self.att_day.date,
        )
        self.punch_out = PunchEvent.objects.create(
            id=201,
            device=device,
            company=self.company,
            employee=self.employee,
            action="out",
            device_ts=timezone.make_aware(datetime(2024, 5, 20, 16, 0)),
            face_matched=False,
            requires_face=True,
            geofence_ok=False,
            geofence_rule_violation=True,
            roster_fallback=True,
            roster_date=self.att_day.date,
            notes="Left early",
        )
        PunchException.objects.create(
            event=self.punch_out, kind="geofence", details={"reason": "Outside"}
        )

        AttPair.objects.create(
            employee=self.employee,
            date=self.att_day.date,
            in_event_id=self.punch_in.id,
            out_event_id=self.punch_out.id,
            in_ts=self.punch_in.device_ts,
            out_ts=self.punch_out.device_ts,
            duration_min=540,
            cross_midnight=False,
            anomaly={"missing_out_closed_at_next_in": True},
        )

        AttAdjustment.objects.create(
            employee=self.employee,
            date=self.att_day.date,
            delta_work_min=30,
            override_status="present",
            reason="Manager approved overtime",
            created_by_id=self.admin.id,
        )

        self.att_day.refresh_from_db()
        self.att_day.locked = True
        self.att_day.save(update_fields=["locked"])

        self.client.force_authenticate(user=self.admin)

    def _url(self, company_id=None, day_id=None):
        return reverse(
            "att-day-full-context",
            kwargs={
                "company_id": company_id or self.company.id,
                "pk": day_id or self.att_day.id,
            },
        )

    def test_full_context_returns_expected_payload(self):
        response = self.client.get(self._url())
        assert response.status_code == 200
        payload = response.json()

        assert payload["day"]["id"] == self.att_day.id
        assert payload["day"]["status"] == "present"

        overview = payload["roster_overview"]
        assert overview["employee"] == {
            "id": self.employee.id,
            "display": str(self.employee),
        }
        assert overview["shift"]["id"] == self.shift.id
        assert overview["shift"]["total_minutes"] == 420
        assert overview["overtime"]["regular"] == 30

        sessions = payload["pair_sessions"]
        assert len(sessions) == 1
        assert sessions[0]["in_event_id"] == self.punch_in.id
        assert sessions[0]["source"]["code"] == "auto"
        assert sessions[0]["anomalies"] == ["missing_out_closed_at_next_in"]

        punches = payload["punch_events"]
        assert [event["id"] for event in punches] == [
            self.punch_in.id,
            self.punch_out.id,
        ]
        assert punches[-1]["exception"]["kind"] == "geofence"

        adjustments = payload["adjustments"]
        assert len(adjustments) == 1
        assert adjustments[0]["reason"] == "Manager approved overtime"

    def test_optional_flags_trim_payload_sections(self):
        response = self.client.get(
            self._url()
            + "?include_pairs=false&include_punches=false&include_adjustments=false"
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["pair_sessions"] == []
        assert payload["punch_events"] == []
        assert payload["adjustments"] == []

    def test_employee_out_of_scope_is_rejected(self):
        other_employee = Employee.objects.create_user(
            username="emp2",
            password="pass",
            department=self.department,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
        )
        self.client.force_authenticate(user=other_employee)

        response = self.client.get(self._url())
        assert response.status_code == 403
