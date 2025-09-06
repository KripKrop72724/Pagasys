from datetime import datetime, date, time

from django.test import TestCase
from django.utils import timezone

from attendance.services import build_pairs_for, compute_att_day
from attendance.services_helpers import active_rules
from capture.models import AttendanceDevice, PunchEvent
from pagasys.models import (
    Company,
    Branch,
    Department,
    Employee,
    ShiftTemplate,
    RosterEntry,
    ShiftRule,
)


class FaceRulePairingTests(TestCase):
    def setUp(self):
        active_rules.cache_clear()
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.dept = Department.objects.create(branch=self.branch, name="D1")
        self.device = AttendanceDevice.objects.create(company=self.company, name="dev1", api_key="k1")
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
            requires_face=True,
        )
        RosterEntry.objects.create(employee=self.employee, date=self.day, shift=self.shift)

    @property
    def employee(self):
        # lazily create to ensure TestCase isolation
        if not hasattr(self, "_employee"):
            self._employee = Employee.objects.create(
                username="emp",
                first_name="E",
                last_name="One",
                department=self.dept,
                hire_date=self.day,
                employment_type="permanent",
                visa_type="personal",
            )
        return self._employee

    def _punch(
        self,
        action="in",
        face_matched=True,
        face_conf=None,
        geofence_rule_violation=False,
        out_of_scope=False,
    ):
        tz = timezone.get_current_timezone()
        ts = timezone.make_aware(datetime.combine(self.day, time(9 if action != "out" else 17, 0)), tz)
        return PunchEvent.objects.create(
            device=self.device,
            company=self.company,
            employee=self.employee,
            matched_employee=self.employee,
            action=action,
            device_ts=ts,
            requires_face=True,
            face_matched=face_matched,
            face_confidence=face_conf,
            roster_date=self.day,
            geofence_rule_violation=geofence_rule_violation,
            out_of_scope=out_of_scope,
        )

    def test_requires_face_excludes_non_matched(self):
        self._punch(action="in", face_matched=False)
        self._punch(action="out", face_matched=False)
        build_pairs_for(self.employee.id, self.day)
        self.assertEqual(0, self.employee.att_pairs.count())

    def test_face_min_conf_blocks_low_confidence(self):
        ShiftRule.objects.create(
            shift=self.shift,
            kind=ShiftRule.Kind.FACE_MIN_CONF,
            value="0.90",
        )
        ev1 = self._punch(action="in", face_conf=0.5)
        self._punch(action="out", face_conf=0.5)
        build_pairs_for(self.employee.id, self.day)
        ev1.refresh_from_db()
        self.assertFalse(ev1.face_matched)
        self.assertEqual(0, self.employee.att_pairs.count())

    def test_face_mismatch_recorded_in_anomalies(self):
        self._punch(action="in", face_matched=False)
        self._punch(action="out", face_matched=False)
        build_pairs_for(self.employee.id, self.day)
        compute_att_day(self.employee.id, self.day)
        day = self.employee.att_days.get(date=self.day)
        self.assertEqual(day.anomalies["face_required_no_match"], 2)

    def test_geofence_violation_recorded_in_anomalies(self):
        self._punch(face_matched=True, geofence_rule_violation=True)
        self._punch(action="out", face_matched=True, geofence_rule_violation=True)
        build_pairs_for(self.employee.id, self.day)
        self.assertEqual(0, self.employee.att_pairs.count())
        compute_att_day(self.employee.id, self.day)
        day = self.employee.att_days.get(date=self.day)
        self.assertEqual(day.anomalies["geofence_rule_violation"], 2)

    def test_outside_scope_recorded_in_anomalies(self):
        self._punch(face_matched=True, out_of_scope=True)
        self._punch(action="out", face_matched=True, out_of_scope=True)
        build_pairs_for(self.employee.id, self.day)
        self.assertEqual(0, self.employee.att_pairs.count())
        compute_att_day(self.employee.id, self.day)
        day = self.employee.att_days.get(date=self.day)
        self.assertEqual(day.anomalies["outside_scope"], 2)
