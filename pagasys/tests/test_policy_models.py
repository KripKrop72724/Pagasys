from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from pagasys.models import (
    Company,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
    Department,
    TradeLicense,
    Employee,
)


class PolicyModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="C1")
        self.branch = self.company.branches.create(name="B")
        self.department = Department.objects.create(branch=self.branch, name="D")

    def test_one_default_calendar_per_company(self):
        WorkCalendar.objects.create(company=self.company, name="Cal1", is_default=True)
        cal2 = WorkCalendar(company=self.company, name="Cal2", is_default=True)
        with self.assertRaises(ValidationError):
            cal2.full_clean()

    def test_company_can_have_non_default_calendar(self):
        company = Company.objects.create(name="C2")
        cal = WorkCalendar(company=company, name="Cal1")
        cal.full_clean()
        cal.save()

    def test_can_unset_last_default_calendar(self):
        cal = WorkCalendar.objects.create(
            company=self.company, name="Cal", is_default=True
        )
        cal.is_default = False
        cal.full_clean()
        cal.save()

    def test_holiday_unique_per_calendar(self):
        cal = WorkCalendar.objects.create(company=self.company, name="Cal")
        Holiday.objects.create(calendar=cal, date="2024-01-01", name="New Year")
        h2 = Holiday(calendar=cal, date="2024-01-01", name="Dup")
        with self.assertRaises(ValidationError):
            h2.full_clean()

    def test_branch_work_calendar_company_alignment(self):
        cal_same = WorkCalendar.objects.create(company=self.company, name="CalSame")
        other_company = Company.objects.create(name="C2")
        cal_other = WorkCalendar.objects.create(company=other_company, name="CalOther")

        self.branch.work_calendar = cal_other
        with self.assertRaises(ValidationError):
            self.branch.full_clean()

        self.branch.work_calendar = cal_same
        self.branch.full_clean()  # no ValidationError

    def test_employee_work_calendar_company_alignment(self):
        branch = self.department.branch
        license = TradeLicense.objects.create(
            company=branch.company,
            license_no="LIC1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        license.branches.set([branch])
        emp = Employee.objects.create(
            username="emp1",
            password="pass",
            trade_license=license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        cal_same = WorkCalendar.objects.create(company=self.company, name="CalSame2")
        other_company = Company.objects.create(name="C3")
        cal_other = WorkCalendar.objects.create(company=other_company, name="CalOther2")

        emp.work_calendar = cal_other
        with self.assertRaises(ValidationError):
            emp.full_clean()

        emp.work_calendar = cal_same
        emp.full_clean()  # no ValidationError

    def test_shift_template_cross_midnight_validation(self):
        st = ShiftTemplate(
            company=self.company,
            name="S1",
            start_time="09:00",
            end_time="08:00",
            cross_midnight=False,
        )
        with self.assertRaises(ValidationError):
            st.full_clean()
        st2 = ShiftTemplate(
            company=self.company,
            name="S2",
            start_time="20:00",
            end_time="22:00",
            cross_midnight=True,
        )
        with self.assertRaises(ValidationError):
            st2.full_clean()

    def test_shift_template_duration_must_be_positive_and_under_24h(self):
        st = ShiftTemplate(
            company=self.company,
            name="Dur1",
            start_time="09:00",
            end_time="09:00",
            cross_midnight=False,
        )
        with self.assertRaises(ValidationError):
            st.full_clean()
        st2 = ShiftTemplate(
            company=self.company,
            name="Dur2",
            start_time="20:00",
            end_time="20:00",
            cross_midnight=True,
        )
        with self.assertRaises(ValidationError):
            st2.full_clean()

    def test_shift_template_break_must_fit_within_duration(self):
        st = ShiftTemplate(
            company=self.company,
            name="Break1",
            start_time="09:00",
            end_time="10:00",
            break_minutes=60,
        )
        with self.assertRaises(ValidationError):
            st.full_clean()

    def test_shift_template_threshold_ordering(self):
        st = ShiftTemplate(
            company=self.company,
            name="Thresh1",
            start_time="09:00",
            end_time="10:00",
            grace_in_min=5,
            late_after_min=4,
        )
        with self.assertRaises(ValidationError):
            st.full_clean()
        st2 = ShiftTemplate(
            company=self.company,
            name="Thresh2",
            start_time="09:00",
            end_time="10:00",
            grace_out_min=5,
            early_leave_before_min=4,
        )
        with self.assertRaises(ValidationError):
            st2.full_clean()

    def test_shift_template_rounding_min_whitelist(self):
        st = ShiftTemplate(
            company=self.company,
            name="Round1",
            start_time="09:00",
            end_time="10:00",
            rounding_min=7,
        )
        with self.assertRaises(ValidationError):
            st.full_clean()
        st_ok = ShiftTemplate(
            company=self.company,
            name="Round2",
            start_time="09:00",
            end_time="10:00",
            rounding_min=5,
        )
        st_ok.full_clean()

    def test_shift_rule_active_dates_validation(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S",
            start_time="09:00",
            end_time="17:00",
        )
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="22:00-04:00",
            active_from="2024-02-01",
            active_to="2024-01-01",
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_shift_rule_weekdays_validation(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S3",
            start_time="09:00",
            end_time="17:00",
        )
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.WEEKLY_REST_DAY,
            value="FRI",
            weekdays="MON,FOO",
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule2 = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.WEEKLY_REST_DAY,
            value="FRI",
            weekdays="MON,MON",
        )
        with self.assertRaises(ValidationError):
            rule2.full_clean()

    def test_shift_rule_weekdays_normalization(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S4",
            start_time="09:00",
            end_time="17:00",
        )
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.WEEKLY_REST_DAY,
            value="FRI",
            weekdays="fri, Mon",
        )
        rule.full_clean()
        self.assertEqual(rule.weekdays, "MON,FRI")

    def test_shift_rule_value_and_params_validation(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S4",
            start_time="09:00",
            end_time="17:00",
        )
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="2200-0400",
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.RAMADAN_REDUCE_MINUTES,
            value="-30",
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.FIXED_BREAK_WINDOW,
            value="13:00-14:00",
            params={"paid": False},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.FIXED_BREAK_WINDOW,
            value="13:00-14:00",
            params={"paid": False, "enforcement": "auto_deduct", "min_minutes": 60},
        )
        rule.full_clean()  # should not raise

    def test_shift_rule_break_params_positive(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S5",
            start_time="09:00",
            end_time="17:00",
        )
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.FIXED_BREAK_WINDOW,
            value="13:00-14:00",
            params={"paid": False, "enforcement": "auto_deduct", "min_minutes": 0},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule.params["min_minutes"] = -5
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule.params["min_minutes"] = "60"
        with self.assertRaises(ValidationError):
            rule.full_clean()
        rule.params["min_minutes"] = 60
        rule.full_clean()  # ok

        rule2 = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE,
            value="300",
            params={"paid": False, "enforcement": "flag", "minutes": 0},
        )
        with self.assertRaises(ValidationError):
            rule2.full_clean()
        rule2.params["minutes"] = -10
        with self.assertRaises(ValidationError):
            rule2.full_clean()
        rule2.params["minutes"] = "30"
        with self.assertRaises(ValidationError):
            rule2.full_clean()
        rule2.params["minutes"] = 30
        rule2.full_clean()  # ok

    def test_shift_rule_special_kinds_and_enforcement(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S6",
            start_time="09:00",
            end_time="17:00",
        )
        face_rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.FACE_MIN_CONF,
            value="abc",
        )
        with self.assertRaises(ValidationError):
            face_rule.full_clean()
        face_rule.value = "1.2"
        with self.assertRaises(ValidationError):
            face_rule.full_clean()
        face_rule.value = "0.5"
        face_rule.full_clean()

        geo_rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
            value="-5",
        )
        with self.assertRaises(ValidationError):
            geo_rule.full_clean()
        geo_rule.value = "0"
        with self.assertRaises(ValidationError):
            geo_rule.full_clean()
        geo_rule.value = "100"
        geo_rule.full_clean()

        break_rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.MIN_TOTAL_BREAK_PER_DAY,
            value="60",
            params={"paid": True, "enforcement": "oops"},
        )
        with self.assertRaises(ValidationError):
            break_rule.full_clean()
        break_rule.params["enforcement"] = "warn"
        break_rule.full_clean()

        paid_rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.PAID_BREAK_WINDOW,
            value="13:00-14:00",
            params={"paid": False, "enforcement": "warn"},
        )
        with self.assertRaises(ValidationError):
            paid_rule.full_clean()
        paid_rule.params["paid"] = True
        paid_rule.full_clean()

    def test_shift_rule_cross_midnight_and_duplicate(self):
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S7",
            start_time="09:00",
            end_time="17:00",
        )
        rule = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="22:00-04:00",
        )
        rule.full_clean()  # crossing midnight allowed
        rule.save()
        dup = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="22:00-04:00",
            active_from="2024-01-01",
            active_to="2024-12-31",
            weekdays="MON",
        )
        dup.full_clean()
        dup.save()
        dup2 = ShiftRule(
            shift=st,
            kind=ShiftRule.Kind.NIGHT_OT_WINDOW,
            value="22:00-04:00",
            active_from="2024-01-01",
            active_to="2024-12-31",
            weekdays="MON",
        )
        with self.assertRaises(IntegrityError):
            dup2.save()

    def test_roster_entry_requires_employee_context(self):
        branch = self.department.branch
        license = TradeLicense.objects.create(
            company=branch.company,
            license_no="L3",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        license.branches.set([branch])
        emp = Employee.objects.create(
            username="e3",
            password="pass",
            trade_license=license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        emp.trade_license = None
        emp.department = None
        emp.project = None
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S8",
            start_time="09:00",
            end_time="17:00",
        )
        r = RosterEntry(employee=emp, date="2024-01-04", shift=st)
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_roster_entry_unique_and_company_match(self):
        branch = self.department.branch
        license = TradeLicense.objects.create(
            company=branch.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        license.branches.set([branch])
        emp = Employee.objects.create(
            username="e",
            password="pass",
            trade_license=license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S",
            start_time="09:00",
            end_time="17:00",
        )
        RosterEntry.objects.create(employee=emp, date="2024-01-01", shift=st)
        r2 = RosterEntry(employee=emp, date="2024-01-01", shift=st)
        with self.assertRaises(ValidationError):
            r2.full_clean()
        other_company = Company.objects.create(name="C2")
        st_other = ShiftTemplate.objects.create(
            company=other_company,
            name="SO",
            start_time="09:00",
            end_time="17:00",
        )
        r3 = RosterEntry(employee=emp, date="2024-01-02", shift=st_other)
        with self.assertRaises(ValidationError):
            r3.full_clean()

    def test_roster_entry_override_validation(self):
        branch = self.department.branch
        license = TradeLicense.objects.create(
            company=branch.company,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        license.branches.set([branch])
        emp = Employee.objects.create(
            username="e2",
            password="pass",
            trade_license=license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        st = ShiftTemplate.objects.create(
            company=self.company,
            name="S2",
            start_time="09:00",
            end_time="17:00",
        )
        r = RosterEntry(
            employee=emp,
            date="2024-01-03",
            shift=st,
            override_start="10:00",
            override_end="09:00",
        )
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_leave_type_paid_pct_bounds_and_constraints(self):
        lt = LeaveType(
            company=self.company,
            code="AL",
            name="Annual",
            paid_pct=Decimal("150"),
        )
        with self.assertRaises(ValidationError):
            lt.full_clean()
        lt2 = LeaveType(
            company=self.company,
            code="UP",
            name="Unpaid",
            paid_pct=Decimal("-10"),
        )
        with self.assertRaises(ValidationError):
            lt2.full_clean()
        LeaveType.objects.create(
            company=self.company,
            code="PD",
            name="Paid",
            paid_pct=Decimal("50"),
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                LeaveType.objects.create(
                    company=self.company,
                    code="pd",
                    name="Dup",
                    paid_pct=Decimal("50"),
                )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                LeaveType.objects.create(
                    company=self.company,
                    code="BAD",
                    name="Bad",
                    paid_pct=Decimal("200"),
                )

    def test_company_timezone_default(self):
        c = Company.objects.create(name="CTZ")
        self.assertEqual(c.timezone, "Asia/Dubai")
