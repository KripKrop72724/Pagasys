from datetime import date
import io

from django.core.management import call_command
from django.test import TestCase

from attendance.models import AttDay, AttPair
from attendance.services_helpers import active_rules
from capture.models import PunchEvent
from pagasys.models import Company, Branch, Department, Employee


class SimulatePunchesTests(TestCase):
    def setUp(self):
        active_rules.cache_clear()
        self.day = date(2024, 1, 1)
        self.company = Company.objects.create(name="C1")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.dept = Department.objects.create(branch=self.branch, name="D1")
        self.employee = Employee.objects.create(
            username="emp",
            first_name="E",
            last_name="One",
            department=self.dept,
            hire_date=self.day,
            employment_type="permanent",
            visa_type="personal",
        )

    def _run(self, scenario: str, mode: str) -> str:
        out = io.StringIO()
        call_command(
            "simulate_punches",
            "--employee",
            str(self.employee.id),
            "--start",
            self.day.isoformat(),
            "--days",
            "1",
            "--scenarios",
            scenario,
            f"--{mode}",
            stdout=out,
        )
        return out.getvalue()

    def test_core_pairing_anomaly(self):
        out = self._run("core", "dry-run")
        self.assertIn("DRY RUN", out)
        self.assertEqual(PunchEvent.objects.count(), 0)
        self._run("core", "commit")
        self.assertEqual(PunchEvent.objects.count(), 1)
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.anomalies.get("unpaired_out"), 1)

    def test_timekeeping_metrics(self):
        self._run("metrics", "commit")
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(PunchEvent.objects.count(), 2)
        self.assertEqual(day.late_min, 15)
        self.assertEqual(day.work_min, 480)
        self.assertEqual(day.ot_regular_min, 105)

    def test_break_rule_cross_midnight(self):
        self._run("break_cross", "commit")
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        pair = AttPair.objects.get(employee=self.employee, date=self.day)
        self.assertTrue(pair.cross_midnight)
        self.assertEqual(day.work_min, 420)

    def test_face_geofence(self):
        self._run("face_geo", "commit")
        self.assertEqual(PunchEvent.objects.count(), 3)
        day = AttDay.objects.get(employee=self.employee, date=self.day)
        self.assertEqual(day.anomalies.get("face_required_no_match"), 1)
        pair = AttPair.objects.filter(
            employee=self.employee, date=self.day, anomaly__has_key="geofence"
        ).first()
        self.assertIsNotNone(pair)

    def test_metadata_propagation(self):
        self._run("metadata", "commit")
        events = list(
            PunchEvent.objects.filter(matched_employee=self.employee).order_by("device_ts")
        )
        self.assertEqual(events[0].notes, "note1")
        self.assertEqual(events[0].external_id, "ext1")
        self.assertEqual(events[1].external_id, "ext2")
