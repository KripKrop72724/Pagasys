from django.test import TestCase

from pagasys.models import (
    Branch,
    Company,
    Department,
    Employee,
    Holiday,
    HolidayAuditLog,
    RosterEntry,
    ShiftTemplate,
    TradeLicense,
    WorkCalendar,
)


class HolidayRecalcTests(TestCase):
    """Ensure roster entries stay in sync with holiday changes."""

    def setUp(self):
        self.company = Company.objects.create(name="Comp")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.calendar = WorkCalendar.objects.create(company=self.company, name="Cal")
        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="Shift",
            start_time="09:00",
            end_time="17:00",
        )
        license = TradeLicense.objects.create(
            company=self.company,
            license_no="LIC",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        license.branches.set([self.branch])
        self.emp = Employee.objects.create(
            username="emp",
            password="pass",
            trade_license=license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            work_calendar=self.calendar,
        )

    def make_entry(self, day, **overrides):
        entry = RosterEntry.objects.create(
            employee=self.emp, date=day, shift=self.shift, **overrides
        )
        # ensure holiday flags mimic API behaviour
        from pagasys.models import holiday_flags

        override = overrides.get("is_holiday")
        entry.is_holiday, entry.was_holiday = holiday_flags(self.emp, entry.date, override)
        entry.save(update_fields=["is_holiday", "was_holiday"])
        return entry

    def test_recalc_on_holiday_update(self):
        hol = Holiday.objects.create(calendar=self.calendar, date="2024-01-10", name="Old")
        e_old = self.make_entry("2024-01-10")
        e_new = self.make_entry("2024-01-11")
        e_old.refresh_from_db()
        e_new.refresh_from_db()
        self.assertTrue(e_old.is_holiday and e_old.was_holiday)
        self.assertFalse(e_new.is_holiday or e_new.was_holiday)

        hol.date = "2024-01-11"
        hol.save()

        e_old.refresh_from_db()
        e_new.refresh_from_db()
        self.assertFalse(e_old.is_holiday or e_old.was_holiday)
        self.assertTrue(e_new.is_holiday and e_new.was_holiday)

        audit = HolidayAuditLog.objects.latest("timestamp")
        self.assertEqual(audit.action, "updated")
        self.assertEqual(audit.old_date.isoformat(), "2024-01-10")
        self.assertEqual(audit.new_date.isoformat(), "2024-01-11")

    def test_recalc_on_holiday_delete_preserves_override(self):
        hol = Holiday.objects.create(calendar=self.calendar, date="2024-02-01", name="Feb")
        e = self.make_entry("2024-02-01", is_holiday=False)
        e.refresh_from_db()
        self.assertFalse(e.is_holiday)
        self.assertTrue(e.was_holiday)

        hol.delete()

        e.refresh_from_db()
        self.assertFalse(e.is_holiday)
        self.assertFalse(e.was_holiday)

        audit = HolidayAuditLog.objects.latest("timestamp")
        self.assertEqual(audit.action, "deleted")
        self.assertEqual(audit.old_date.isoformat(), "2024-02-01")

    def test_recalc_preserves_manual_true_on_update(self):
        hol = Holiday.objects.create(calendar=self.calendar, date="2024-03-01", name="Mar")
        e1 = self.make_entry("2024-03-01", is_holiday=False)
        e2 = self.make_entry("2024-03-02", is_holiday=True)

        hol.date = "2024-03-02"
        hol.save()

        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertFalse(e1.is_holiday)
        self.assertFalse(e1.was_holiday)
        self.assertTrue(e2.is_holiday)
        self.assertTrue(e2.was_holiday)
