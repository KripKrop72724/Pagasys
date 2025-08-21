"""Core HR models used throughout the application."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractUser
from django.db.models.functions import Lower


class Company(models.Model):
    """Registered company."""

    name = models.CharField(
        max_length=255,
        help_text="Official company name",
    )
    timezone = models.CharField(
        max_length=64,
        default="Asia/Dubai",
        help_text="IANA time zone for scheduling/attendance",
    )

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["name"], name="company_name_idx")
        ]

    def __str__(self) -> str:
        return self.name




class Branch(models.Model):
    """Individual branch office of a company."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="branches",
        help_text="Parent company",
    )
    name = models.CharField(
        max_length=255,
        help_text="Branch office name",
    )
    work_calendar = models.ForeignKey(
        "WorkCalendar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="branches",
        help_text="Specific work calendar for this branch",
    )

    class Meta:
        verbose_name_plural = "branches"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "name"], name="branch_company_name_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name}"

    def clean(self):
        if self.work_calendar and self.work_calendar.company_id != self.company_id:
            raise ValidationError("work_calendar company must match branch company")


class Designation(models.Model):
    """Job title defined per company."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="designations",
        help_text="Company that defines the designation",
    )
    name = models.CharField(
        max_length=100,
        help_text="Job title name",
    )
    level = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Seniority level",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this designation",
    )

    class Meta:
        unique_together = (("company", "name"),)
        verbose_name_plural = "designations"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "name", "level"], name="designation_comp_name_lvl_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name}"


class TradeLicense(models.Model):
    """Government trade license issued to a company covering branches."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="licenses",
        help_text="License owning company",
    )
    branches = models.ManyToManyField(
        Branch,
        related_name="licenses",
        help_text="Which branches this license covers",
    )
    license_no = models.CharField(
        max_length=100,
        unique=True,
        help_text="Official license number",
    )
    issued_date = models.DateField(help_text="Date license was issued")
    expiry_date = models.DateField(help_text="Date license expires")
    max_visas = models.PositiveIntegerField(help_text="Maximum number of visa slots")

    class Meta:
        verbose_name = "trade license"
        verbose_name_plural = "trade licenses"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "license_no"], name="license_company_no_idx"),
            models.Index(fields=["company", "issued_date", "expiry_date"], name="license_date_range_idx"),
        ]

    def clean(self):
        """Validate logical consistency and branch-company rules."""
        if self.expiry_date < self.issued_date:
            raise ValidationError("Expiry date must be after issued date")

        branches = getattr(self, "_branches_for_validation", None)
        if branches is None:
            branches = self.branches.all()
        invalid = [b for b in branches if b.company_id != self.company_id]
        if invalid:
            raise ValidationError("Branches must belong to the license company")

    def __str__(self) -> str:
        branches = ", ".join(b.name for b in self.branches.all())
        return f"{self.license_no} - {self.company.name}" + (f" - {branches}" if branches else "")


class Department(models.Model):
    """Organizational department within a branch."""

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="departments",
        help_text="Branch that houses the department",
    )
    name = models.CharField(
        max_length=255,
        help_text="Department name",
    )

    class Meta:
        verbose_name_plural = "departments"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["branch", "name"], name="dept_branch_name_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.branch.name} - {self.branch.company.name}"


class Project(models.Model):
    """Project carried out by a branch."""

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="projects",
        help_text="Branch executing the project",
    )
    name = models.CharField(
        max_length=255,
        help_text="Project name",
    )
    start_date = models.DateField(help_text="Project start date")
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Project end date",
    )

    class Meta:
        verbose_name_plural = "projects"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["branch", "name"], name="project_branch_name_idx"),
            models.Index(fields=["branch", "start_date", "end_date"], name="project_date_range_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.branch.name} - {self.branch.company.name}"



class Employee(AbstractUser):
    """User account combined with employment info."""

    VISA_TYPE_CHOICES = [
        ("company", "Company"),
        ("personal", "Personal"),
    ]

    visa_type = models.CharField(
        max_length=20,
        choices=VISA_TYPE_CHOICES,
        default="company",
        help_text="Whether the employee uses a company or personal visa",
    )

    trade_license = models.ForeignKey(
        TradeLicense,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="employees",
        help_text="Visa license assigned",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Department assigned",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Project assigned",
    )
    work_calendar = models.ForeignKey(
        "WorkCalendar",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Specific work calendar for the employee",
    )
    designation = models.ForeignKey(
        Designation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Job designation",
    )
    hire_date = models.DateField(help_text="Date hired")
    employment_type = models.CharField(
        max_length=20,
        choices=[("permanent", "Permanent"), ("temporary", "Temporary")],
        help_text="Employment contract type",
    )

    @property
    def company(self):
        """Convenience access to the employee's company."""
        if self.trade_license:
            return self.trade_license.company
        if self.department:
            return self.department.branch.company
        if self.project:
            return self.project.branch.company
        return None

    @property
    def branch(self):
        """Branch derived from department or project."""
        if self.department:
            return self.department.branch
        if self.project:
            return self.project.branch
        return None

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(department__isnull=False, project__isnull=True)
                    | models.Q(department__isnull=True, project__isnull=False)
                ),
                name="employee_one_of_dept_or_proj",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(visa_type="company", trade_license__isnull=False)
                    | models.Q(visa_type="personal", trade_license__isnull=True)
                ),
                name="employee_license_matches_visa_type",
            ),
        ]
        verbose_name_plural = "employees"
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["trade_license", "department", "employment_type"],
                name="emp_lic_dept_type_idx",
            ),
            models.Index(
                fields=["trade_license", "project", "employment_type"],
                name="emp_lic_proj_type_idx",
            ),
            models.Index(
                fields=["department", "designation", "employment_type"],
                name="emp_dept_desig_type_idx",
            ),
            models.Index(
                fields=["project", "designation", "employment_type"],
                name="emp_proj_desig_type_idx",
            ),
            models.Index(fields=["first_name", "last_name"], name="emp_name_idx"),
        ]

    def clean(self):
        super().clean()
        if not (bool(self.department) ^ bool(self.project)):
            raise ValidationError(
                "Employee must belong to exactly one of department or project"
            )

        branch = self.department.branch if self.department else self.project.branch

        if self.visa_type == "company":
            if not self.trade_license:
                raise ValidationError({"trade_license": ["This field is required for company visas"]})

            current = self.trade_license.employees.exclude(pk=self.pk).count()
            if current >= self.trade_license.max_visas:
                raise ValidationError("Visa quota reached")

            if self.designation and self.designation.company != self.trade_license.company:
                raise ValidationError("Designation must match company")

            if self.trade_license.company != branch.company:
                raise ValidationError("License company must match branch company")

        else:  # personal visa
            if self.trade_license:
                raise ValidationError({"trade_license": ["Trade license must be empty for personal visa"]})

        # Personal visa with designation company mismatch:
        # ensure designation matches branch.company
        if self.designation and self.designation.company != branch.company:
            raise ValidationError("Designation must match company")

        if self.work_calendar and self.work_calendar.company_id != branch.company_id:
            raise ValidationError("Work calendar company must match employee company")

    def __str__(self) -> str:
        parts = [f"{self.first_name} {self.last_name}"]
        if self.trade_license:
            parts.append(self.trade_license.company.name)
        elif self.branch:
            parts.append(self.branch.company.name)
        if self.department:
            parts.append(self.department.branch.name)
            parts.append(self.department.name)
        elif self.project:
            parts.append(self.project.branch.name)
            parts.append(self.project.name)
        if self.trade_license:
            parts.append(self.trade_license.license_no)
        if self.designation:
            parts.append(self.designation.name)
        return " - ".join(parts)

    def save(self, *args, **kwargs):
        """Ensure visa quota checks are performed atomically."""
        from django.db import transaction

        if self.visa_type == "company" and self.trade_license_id:
            with transaction.atomic():
                lic = (
                    TradeLicense.objects.select_for_update()
                    .get(pk=self.trade_license_id)
                )
                current = lic.employees.exclude(pk=self.pk).count()
                if current >= lic.max_visas:
                    raise ValidationError("Visa quota reached")
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class WorkCalendar(models.Model):
    """Holiday/season calendar scoped to a company."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="calendars",
        help_text="Company this calendar belongs to",
    )
    name = models.CharField(max_length=255, help_text="Calendar name")
    is_default = models.BooleanField(
        default=False,
        help_text="Mark as company default calendar; at most one per company"
    )

    class Meta:
        unique_together = (("company", "name"),)
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=models.Q(is_default=True),
                name="unique_default_calendar_per_company",
            )
        ]
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["company", "name"], name="calendar_company_name_idx"
            )
        ]

    def clean(self):
        super().clean()
        if self.is_default:
            clash = (
                WorkCalendar.objects
                .filter(company=self.company, is_default=True)
                .exclude(pk=self.pk)
                .exists()
            )
            if clash:
                raise ValidationError("Only one default calendar per company")

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name}"


class Holiday(models.Model):
    """Single holiday entry on a calendar."""

    calendar = models.ForeignKey(
        WorkCalendar,
        on_delete=models.CASCADE,
        related_name="holidays",
        help_text="Parent work calendar",
    )
    date = models.DateField(help_text="Holiday date")
    name = models.CharField(max_length=255, help_text="Holiday name")
    is_public = models.BooleanField(
        default=False, help_text="Public vs company holiday"
    )

    class Meta:
        unique_together = (("calendar", "date"),)
        ordering = ["date"]
        indexes = [
            models.Index(
                fields=["calendar", "date"], name="holiday_calendar_date_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.date}"


def _minutes_between(start, end, cross_midnight):
    """Return minutes between two times accounting for next-day shifts."""
    d = date(2000, 1, 1)
    a = datetime.combine(d, start)
    b = datetime.combine(d + timedelta(days=1 if cross_midnight else 0), end)
    return int((b - a).total_seconds() // 60)


class ShiftTemplate(models.Model):
    """Reusable description of a work shift."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="shift_templates",
        help_text="Company owning this template",
    )
    name = models.CharField(max_length=100, help_text="Template name")
    start_time = models.TimeField(help_text="Scheduled start time")
    end_time = models.TimeField(help_text="Scheduled end time")
    cross_midnight = models.BooleanField(
        default=False, help_text="Does shift end next day?"
    )
    break_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Total unpaid break minutes (must be < shift duration)"
    )
    grace_in_min = models.PositiveIntegerField(
        default=0, help_text="Minutes allowed late without penalty"
    )
    grace_out_min = models.PositiveIntegerField(
        default=0, help_text="Minutes allowed early without penalty"
    )
    late_after_min = models.PositiveIntegerField(
        default=0,
        help_text="Mark late after this many minutes (≥ grace_in_min)"
    )
    early_leave_before_min = models.PositiveIntegerField(
        default=0,
        help_text="Mark early leave before this many minutes (≥ grace_out_min)"
    )
    ROUNDING_CHOICES = [(0, "0"), (1, "1"), (5, "5"), (10, "10"), (15, "15"), (30, "30")]
    rounding_min = models.PositiveSmallIntegerField(
        choices=ROUNDING_CHOICES,
        default=0,
        help_text="Rounding increment in minutes (0,1,5,10,15,30)"
    )
    requires_face = models.BooleanField(
        default=False, help_text="Require face authentication"
    )

    class Meta:
        unique_together = (("company", "name"),)
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["company", "name"], name="shifttemplate_company_name_idx"
            )
        ]

    def clean(self):
        if not self.cross_midnight and self.end_time <= self.start_time:
            raise ValidationError(
                "end_time must be after start_time for non-cross-midnight shifts"
            )
        if self.cross_midnight and self.end_time >= self.start_time:
            raise ValidationError(
                "for cross-midnight, end_time must be before start_time (next day)"
            )

        minutes = _minutes_between(self.start_time, self.end_time, self.cross_midnight)
        if minutes <= 0 or minutes >= 24 * 60:
            raise ValidationError("Shift duration must be >0 and <24 hours")

        if self.break_minutes and self.break_minutes >= minutes:
            raise ValidationError("break_minutes must be less than shift duration")

        if self.late_after_min and self.late_after_min < self.grace_in_min:
            raise ValidationError("late_after_min cannot be less than grace_in_min")
        if (
            self.early_leave_before_min
            and self.early_leave_before_min < self.grace_out_min
        ):
            raise ValidationError(
                "early_leave_before_min cannot be less than grace_out_min"
            )

        if self.rounding_min not in (0, 1, 5, 10, 15, 30):
            raise ValidationError(
                "rounding_min must be one of 0,1,5,10,15,30"
            )

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name}"


class ShiftRule(models.Model):
    """Policy rule applied to a shift template."""

    class Kind(models.TextChoices):
        FIXED_BREAK_WINDOW = "fixed_break_window", "fixed break window"
        REQUIRED_BREAK_AFTER_CONSECUTIVE = (
            "required_break_after_consecutive",
            "required break after consecutive",
        )
        MIN_TOTAL_BREAK_PER_DAY = "min_total_break_per_day", "min total break per day"
        PAID_BREAK_WINDOW = "paid_break_window", "paid break window"
        NIGHT_OT_WINDOW = "night_ot_window", "night ot window"
        RAMADAN_REDUCE_MINUTES = "ramadan_reduce_minutes", "Ramadan reduce minutes"
        WEEKLY_REST_DAY = "weekly_rest_day", "weekly rest day"
        MAX_DAILY_HOURS = "max_daily_hours", "max daily hours"
        GEOFENCE_REQUIRED = "geofence_required", "geofence required"
        FACE_MIN_CONF = "face_min_conf", "face minimum confidence"

    shift = models.ForeignKey(
        ShiftTemplate,
        on_delete=models.CASCADE,
        related_name="rules",
        help_text="Shift template this rule applies to",
    )
    kind = models.CharField(
        max_length=40,
        choices=Kind.choices,
        help_text="Rule kind",
    )
    value = models.CharField(
        max_length=100,
        help_text="Rule value. For time windows use HH:MM-HH:MM and it may cross midnight (e.g. 22:00-04:00)",
    )
    params = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional parameters; break rules require paid (bool) and enforcement (warn, flag, auto_deduct, block)",
    )
    active_from = models.DateField(
        null=True,
        blank=True,
        help_text="Rule active start date",
    )
    active_to = models.DateField(
        null=True,
        blank=True,
        help_text="Rule active end date",
    )
    weekdays = models.CharField(
        max_length=20,
        blank=True,
        help_text="Comma-separated weekdays e.g. MON,TUE",
    )

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["shift", "kind"], name="shiftrule_shift_kind_idx"),
            models.Index(
                fields=["shift", "active_from", "active_to"],
                name="shiftrule_active_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "shift",
                    "kind",
                    "value",
                    "active_from",
                    "active_to",
                    "weekdays",
                ],
                name="uniq_rule_signature_per_shift",
            )
        ]

    def clean(self):
        if self.active_from and self.active_to and self.active_to < self.active_from:
            raise ValidationError("active_to must be after active_from")
        if self.weekdays:
            valid = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
            parts = [p.strip().upper() for p in self.weekdays.split(",") if p.strip()]
            if len(parts) != len(set(parts)) or any(p not in valid for p in parts):
                raise ValidationError(
                    "weekdays must be comma separated MON-SUN abbreviations without duplicates"
                )
        time_window_kinds = {
            self.Kind.NIGHT_OT_WINDOW,
            self.Kind.FIXED_BREAK_WINDOW,
            self.Kind.PAID_BREAK_WINDOW,
        }
        numeric_kinds = {
            self.Kind.RAMADAN_REDUCE_MINUTES,
            self.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE,
            self.Kind.MIN_TOTAL_BREAK_PER_DAY,
            self.Kind.MAX_DAILY_HOURS,
        }
        if self.kind in time_window_kinds:
            import re

            if not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", self.value):
                raise ValidationError("value must be in HH:MM-HH:MM format")
            start_str, end_str = self.value.split("-")
            from datetime import time as _time
            start = _time.fromisoformat(start_str)
            end = _time.fromisoformat(end_str)
            if start == end:
                raise ValidationError("start and end times cannot be equal")
        if self.kind in numeric_kinds:
            if not self.value.isdigit() or int(self.value) <= 0:
                raise ValidationError("value must be a positive integer")

        if self.kind == self.Kind.FACE_MIN_CONF:
            try:
                conf = float(self.value)
            except ValueError:
                raise ValidationError("FACE_MIN_CONF value must be a float 0..1")
            if not (0.0 <= conf <= 1.0):
                raise ValidationError("FACE_MIN_CONF must be between 0 and 1")

        if self.kind == self.Kind.GEOFENCE_REQUIRED:
            if not self.value.isdigit() or int(self.value) <= 0:
                raise ValidationError(
                    "GEOFENCE_REQUIRED value must be positive meters (integer)"
                )

        break_kinds = {
            self.Kind.FIXED_BREAK_WINDOW,
            self.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE,
            self.Kind.MIN_TOTAL_BREAK_PER_DAY,
            self.Kind.PAID_BREAK_WINDOW,
        }
        if self.kind in break_kinds:
            if not isinstance(self.params, dict):
                raise ValidationError("params must be provided for break rules")
            missing = {"paid", "enforcement"} - self.params.keys()
            if missing:
                raise ValidationError("params missing required keys: " + ", ".join(sorted(missing)))
            allowed = {"warn", "flag", "auto_deduct", "block"}
            if self.params.get("enforcement") not in allowed:
                raise ValidationError(
                    f"params.enforcement must be one of {sorted(allowed)}"
                )
            if (
                self.kind == self.Kind.PAID_BREAK_WINDOW
                and self.params.get("paid") is not True
            ):
                raise ValidationError("PAID_BREAK_WINDOW requires params.paid = true")
            if self.kind == self.Kind.FIXED_BREAK_WINDOW and "min_minutes" not in self.params:
                raise ValidationError("params must include min_minutes for fixed_break_window")
            if self.kind == self.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE and "minutes" not in self.params:
                raise ValidationError("params must include minutes for required_break_after_consecutive")
            if self.kind == self.Kind.FIXED_BREAK_WINDOW:
                mm = self.params.get("min_minutes")
                if not isinstance(mm, int) or mm <= 0:
                    raise ValidationError("min_minutes must be a positive integer")
            if self.kind == self.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE:
                mins = self.params.get("minutes")
                if not isinstance(mins, int) or mins <= 0:
                    raise ValidationError("minutes must be a positive integer")

    def __str__(self) -> str:
        return f"{self.kind} - {self.shift.name}"


class RosterEntry(models.Model):
    """Daily assignment of an employee to a shift."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="roster_entries",
        help_text="Employee for the roster entry",
    )
    date = models.DateField(help_text="Shift start date")
    shift = models.ForeignKey(
        ShiftTemplate,
        on_delete=models.CASCADE,
        related_name="roster_entries",
        help_text="Shift template applied",
    )
    override_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Override start time",
    )
    override_end = models.TimeField(
        null=True,
        blank=True,
        help_text="Override end time",
    )
    is_rest_day = models.BooleanField(
        default=False,
        help_text="Marks the day as a scheduled rest day",
    )

    class Meta:
        unique_together = (("employee", "date"),)
        ordering = ["date"]
        indexes = [
            models.Index(
                fields=["employee", "date"], name="roster_employee_date_idx"
            )
        ]

    def clean(self):
        if self.override_start and self.override_end and self.override_end <= self.override_start:
            raise ValidationError("override_end must be after override_start")

        if not any(
            [
                self.employee.trade_license_id,
                self.employee.department_id,
                self.employee.project_id,
            ]
        ):
            raise ValidationError(
                "Employee must have a license or an assignment before rostering"
            )

        # Ensure shift company matches employee company
        employee_company = None
        if self.employee.trade_license_id:
            employee_company = self.employee.trade_license.company_id
        elif self.employee.department_id:
            employee_company = self.employee.department.branch.company_id
        elif self.employee.project_id:
            employee_company = self.employee.project.branch.company_id
        if employee_company and self.shift.company_id != employee_company:
            raise ValidationError("Shift company must match employee company")

    def __str__(self) -> str:
        return f"{self.employee} - {self.date}"


class LeaveType(models.Model):
    """Configuration for various leave types."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="leave_types",
        help_text="Company defining this leave type",
    )
    code = models.CharField(max_length=20, help_text="Short code e.g. AL")
    name = models.CharField(max_length=100, help_text="Descriptive name")
    paid_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=100,
        help_text="Percent of pay the leave grants",
    )
    requires_doc = models.BooleanField(
        default=False, help_text="Whether documentation is required"
    )
    max_days_per_year = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum days allowed per year",
    )
    params = models.JSONField(null=True, blank=True, help_text="Extra configuration")

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["company", "code"], name="leavetype_company_code_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(paid_pct__gte=0) & models.Q(paid_pct__lte=100),
                name="leavetype_paid_pct_0_100",
            ),
            models.UniqueConstraint(
                Lower("code"),
                "company",
                name="leavetype_company_code_ci_unique",
            ),
        ]

    def clean(self):
        if not (Decimal("0") <= self.paid_pct <= Decimal("100")):
            raise ValidationError("paid_pct must be between 0 and 100")

    def __str__(self) -> str:
        return f"{self.code} - {self.company.name}"
