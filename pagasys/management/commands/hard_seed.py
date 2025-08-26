from datetime import date, time

from django.contrib.auth.models import Group
from django.core.management import BaseCommand, call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from pagasys.models import (
    Branch,
    Company,
    Department,
    Employee,
    Holiday,
    HolidayAuditLog,
    LeaveType,
    Project,
    RosterEntry,
    ShiftRule,
    ShiftTemplate,
    TradeLicense,
    WorkCalendar,
    holiday_flags,
)


class Command(BaseCommand):
    """Dangerously reset the database and load comprehensive demo data."""

    help = "Flush database and seed extensive sample data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip warning confirmation",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Assume yes to prompts (non-interactive)",
        )

    def handle(self, *args, **options):
        if not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    "*** WARNING: This will DELETE all data and recreate demo records ***"
                )
            )
            if not options["yes"]:
                confirm = input("Type 'yes' to continue: ")
                if confirm.lower() != "yes":
                    self.stdout.write(self.style.ERROR("Aborted"))
                    return

        call_command("flush", interactive=False)
        call_command("migrate")

        summary = {}
        failures = []

        with transaction.atomic():
            # Companies
            acme = Company.objects.create(name="Acme Corp", timezone="Asia/Dubai")
            dst_co = Company.objects.create(name="DST Corp", timezone="Europe/Berlin")

            # Calendars
            acme_cal_main = WorkCalendar.objects.create(
                company=acme, name="Acme Main", is_default=True
            )
            acme_cal_alt = WorkCalendar.objects.create(company=acme, name="Acme Alt")
            dst_cal = WorkCalendar.objects.create(
                company=dst_co, name="DST Default", is_default=True
            )

            # Branches
            acme_b1 = Branch.objects.create(
                company=acme, name="Acme Dubai", work_calendar=acme_cal_main
            )
            acme_b2 = Branch.objects.create(
                company=acme, name="Acme Abu Dhabi", work_calendar=acme_cal_alt
            )
            dst_branch = Branch.objects.create(
                company=dst_co, name="Berlin HQ", work_calendar=dst_cal
            )

            # Departments & Projects
            acme_d1 = Department.objects.create(branch=acme_b1, name="HR")
            acme_d2 = Department.objects.create(branch=acme_b2, name="Engineering")
            acme_proj = Project.objects.create(
                branch=acme_b1, name="Project X", start_date=date(2024, 1, 1)
            )
            dst_dept = Department.objects.create(branch=dst_branch, name="R&D")
            dst_proj = Project.objects.create(
                branch=dst_branch, name="DST Project", start_date=date(2024, 1, 1)
            )

            # Trade licenses
            acme_lic = TradeLicense.objects.create(
                company=acme,
                license_no="LIC-ACME",
                issued_date=date(2024, 1, 1),
                expiry_date=date(2025, 1, 1),
                max_visas=10,
            )
            acme_lic.branches.set([acme_b1, acme_b2])
            dst_lic = TradeLicense.objects.create(
                company=dst_co,
                license_no="LIC-DST",
                issued_date=date(2024, 1, 1),
                expiry_date=date(2025, 1, 1),
                max_visas=5,
            )
            dst_lic.branches.set([dst_branch])

            # Shift templates
            day_shift = ShiftTemplate.objects.create(
                company=acme,
                name="Day Shift",
                start_time=time(9, 0),
                end_time=time(17, 0),
                break_minutes=60,
            )
            normal_shift = ShiftTemplate.objects.create(
                company=acme,
                name="Normal Shift",
                start_time=time(8, 0),
                end_time=time(16, 0),
                break_minutes=30,
            )
            night_shift = ShiftTemplate.objects.create(
                company=acme,
                name="Night Shift",
                start_time=time(22, 0),
                end_time=time(6, 0),
                cross_midnight=True,
                break_minutes=30,
            )
            dst_night = ShiftTemplate.objects.create(
                company=dst_co,
                name="DST Night",
                start_time=time(22, 0),
                end_time=time(6, 0),
                cross_midnight=True,
                break_minutes=30,
            )

            # Shift rules covering all kinds
            rules = [
                (
                    ShiftRule.Kind.FIXED_BREAK_WINDOW,
                    day_shift,
                    "12:00-12:30",
                    {"paid": False, "enforcement": "warn", "min_minutes": 30},
                ),
                (
                    ShiftRule.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE,
                    day_shift,
                    "240",
                    {"paid": False, "enforcement": "warn", "minutes": 15},
                ),
                (
                    ShiftRule.Kind.MIN_TOTAL_BREAK_PER_DAY,
                    day_shift,
                    "60",
                    {"paid": False, "enforcement": "flag"},
                ),
                (
                    ShiftRule.Kind.PAID_BREAK_WINDOW,
                    day_shift,
                    "15:00-15:15",
                    {"paid": True, "enforcement": "auto_deduct"},
                ),
                (
                    ShiftRule.Kind.NIGHT_OT_WINDOW,
                    night_shift,
                    "22:00-04:00",
                    None,
                ),
                (
                    ShiftRule.Kind.RAMADAN_REDUCE_MINUTES,
                    day_shift,
                    "60",
                    None,
                ),
                (
                    ShiftRule.Kind.WEEKLY_REST_DAY,
                    day_shift,
                    "SUN",
                    None,
                ),
                (
                    ShiftRule.Kind.MAX_DAILY_HOURS,
                    day_shift,
                    "12",
                    None,
                ),
                (
                    ShiftRule.Kind.GEOFENCE_REQUIRED,
                    day_shift,
                    "100",
                    None,
                ),
                (
                    ShiftRule.Kind.FACE_MIN_CONF,
                    day_shift,
                    "0.8",
                    None,
                ),
            ]
            for kind, shift, value, params in rules:
                ShiftRule.objects.create(
                    shift=shift, kind=kind, value=value, params=params
                )

            # Groups for permission variations
            groups = {
                name: Group.objects.get_or_create(name=name)[0]
                for name in ["Company Admin", "Department Manager", "Employee"]
            }

            # Employees with variations
            emp_license = Employee.objects.create(
                username="lic_emp",
                email="lic@example.com",
                first_name="Larry",
                last_name="License",
                hire_date=date(2024, 1, 10),
                employment_type="permanent",
                visa_type="company",
                trade_license=acme_lic,
                department=acme_d1,
            )
            emp_license.set_password("pass")
            emp_license.groups.add(groups["Company Admin"])

            emp_department = Employee.objects.create(
                username="dept_emp",
                email="dept@example.com",
                first_name="Dora",
                last_name="Dept",
                hire_date=date(2024, 2, 1),
                employment_type="permanent",
                visa_type="personal",
                department=acme_d2,
            )
            emp_department.set_password("pass")
            emp_department.groups.add(groups["Employee"])

            emp_project = Employee.objects.create(
                username="proj_emp",
                email="proj@example.com",
                first_name="Peter",
                last_name="Project",
                hire_date=date(2024, 3, 1),
                employment_type="temporary",
                visa_type="personal",
                project=acme_proj,
            )
            emp_project.set_password("pass")
            emp_project.groups.add(groups["Department Manager"])

            emp_custom_cal = Employee.objects.create(
                username="cal_emp",
                email="cal@example.com",
                first_name="Cathy",
                last_name="Calendar",
                hire_date=date(2024, 2, 15),
                employment_type="permanent",
                visa_type="company",
                trade_license=acme_lic,
                department=acme_d1,
                work_calendar=acme_cal_alt,
            )
            emp_custom_cal.set_password("pass")
            emp_custom_cal.groups.add(groups["Employee"])

            dst_emp = Employee.objects.create(
                username="dst_emp",
                email="dst@example.com",
                first_name="Derek",
                last_name="DST",
                hire_date=date(2024, 3, 15),
                employment_type="permanent",
                visa_type="company",
                trade_license=dst_lic,
                department=dst_dept,
            )
            dst_emp.set_password("pass")

            # Holidays
            christmas = Holiday.objects.create(
                calendar=acme_cal_main,
                date=date(2024, 12, 25),
                name="Christmas",
                is_public=True,
            )
            alt_holiday = Holiday.objects.create(
                calendar=acme_cal_alt, date=date(2024, 5, 1), name="Founders Day"
            )
            dst_holiday = Holiday.objects.create(
                calendar=dst_cal, date=date(2024, 10, 3), name="Unity Day"
            )

            upd_holiday = Holiday.objects.create(
                calendar=acme_cal_main, date=date(2024, 1, 1), name="New Year"
            )
            upd_holiday.date = date(2024, 1, 2)
            upd_holiday.save()

            del_holiday = Holiday.objects.create(
                calendar=acme_cal_main, date=date(2024, 3, 1), name="Temp Holiday"
            )
            del_holiday.delete()

            try:
                Holiday.objects.create(
                    calendar=acme_cal_main, date=christmas.date, name="Christmas"
                )
            except IntegrityError as exc:
                failures.append(f"Duplicate holiday skipped: {exc}")

            # Leave types
            LeaveType.objects.create(
                company=acme, code="UL", name="Unpaid Leave", paid_pct=0
            )
            LeaveType.objects.create(
                company=acme,
                code="SL",
                name="Sick Leave",
                paid_pct=50,
                requires_doc=True,
                max_days_per_year=10,
            )
            LeaveType.objects.create(
                company=acme,
                code="AL",
                name="Annual Leave",
                paid_pct=100,
                max_days_per_year=30,
            )

            # Roster entries
            flags = holiday_flags(emp_license, date(2024, 2, 1))
            RosterEntry.objects.create(
                employee=emp_license,
                date=date(2024, 2, 1),
                shift=day_shift,
                is_holiday=flags[0],
                was_holiday=flags[1],
            )
            flags = holiday_flags(emp_license, christmas.date)
            RosterEntry.objects.create(
                employee=emp_license,
                date=christmas.date,
                shift=day_shift,
                is_holiday=flags[0],
                was_holiday=flags[1],
            )
            flags = holiday_flags(emp_department, date(2024, 2, 2))
            RosterEntry.objects.create(
                employee=emp_department,
                date=date(2024, 2, 2),
                shift=day_shift,
                is_rest_day=True,
                is_holiday=flags[0],
                was_holiday=flags[1],
            )
            flags = holiday_flags(emp_project, date(2024, 4, 10))
            RosterEntry.objects.create(
                employee=emp_project,
                date=date(2024, 4, 10),
                shift=night_shift,
                is_holiday=flags[0],
                was_holiday=flags[1],
            )
            flags = holiday_flags(emp_custom_cal, date(2024, 2, 20))
            RosterEntry.objects.create(
                employee=emp_custom_cal,
                date=date(2024, 2, 20),
                shift=normal_shift,
                override_start=time(10, 0),
                override_end=time(18, 0),
                is_holiday=flags[0],
                was_holiday=flags[1],
            )
            flags = holiday_flags(dst_emp, date(2024, 3, 30))
            RosterEntry.objects.create(
                employee=dst_emp,
                date=date(2024, 3, 30),
                shift=dst_night,
                is_holiday=flags[0],
                was_holiday=flags[1],
            )

            # Conflict validation: roster with mismatched company
            bad_entry = RosterEntry(
                employee=emp_department,
                date=date(2024, 5, 1),
                shift=dst_night,
            )
            try:
                bad_entry.full_clean()
                bad_entry.save()
            except ValidationError as exc:
                failures.append(f"Cross-company roster prevented: {exc}")

        summary = {
            "companies": Company.objects.count(),
            "branches": Branch.objects.count(),
            "departments": Department.objects.count(),
            "projects": Project.objects.count(),
            "licenses": TradeLicense.objects.count(),
            "calendars": WorkCalendar.objects.count(),
            "holidays": Holiday.objects.count(),
            "holiday_audits": HolidayAuditLog.objects.count(),
            "shift_templates": ShiftTemplate.objects.count(),
            "shift_rules": ShiftRule.objects.count(),
            "employees": Employee.objects.count(),
            "roster_entries": RosterEntry.objects.count(),
            "leave_types": LeaveType.objects.count(),
        }

        self.stdout.write(self.style.SUCCESS("Hard seed complete"))
        for k, v in summary.items():
            self.stdout.write(f"{k}: {v}")
        if failures:
            self.stdout.write(self.style.WARNING("Failures/Skips:"))
            for f in failures:
                self.stdout.write(f"- {f}")
