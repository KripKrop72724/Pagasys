"""Core HR models used throughout the application."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import AbstractUser
from django.db.models import F
from django.db.models.functions import Lower
from django.utils import timezone
from django_countries.fields import CountryField
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    address = models.TextField(
        blank=True,
        help_text="Physical address of the company",
    )
    logo = models.ImageField(
        upload_to="company_logos/",
        blank=True,
        null=True,
        help_text="Company logo image",
    )
    email = models.EmailField(
        blank=True,
        help_text="General contact email address",
    )
    phone = models.CharField(
        max_length=32,
        blank=True,
        help_text="Primary contact phone number",
    )
    website = models.URLField(
        blank=True,
        help_text="Official company website",
    )
    bank_account_number = models.CharField(
        max_length=64,
        blank=True,
        help_text="Bank account number used for payroll transactions",
    )
    is_only_company = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, this instance represents the sole company and "
            "blocks creation of any additional companies."
        ),
    )

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["name"], name="company_name_idx")
        ]

    def clean(self):
        super().clean()
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValidationError({"timezone": "Invalid IANA time zone (e.g., 'Asia/Dubai')"})
        other_companies = Company.objects.exclude(pk=self.pk)
        if self.is_only_company and other_companies.exists():
            raise ValidationError(
                {
                    "is_only_company": (
                        "Cannot mark this company as the only company while other companies exist. "
                        "Delete or archive the others first."
                    )
                }
            )
        if not self.is_only_company and other_companies.filter(is_only_company=True).exists():
            raise ValidationError(
                {
                    "is_only_company": (
                        "Another company is marked as the only company. "
                        "Unset that flag before adding or updating additional companies."
                    )
                }
            )

    def __str__(self) -> str:
        return self.name




class Branch(models.Model):
    """Individual branch office of a company.

    Branches with active employees cannot be hard deleted. Instead, mark them
    inactive in the admin or via the API to archive them.
    """

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
    address = models.TextField(
        blank=True,
        help_text="Physical address of the branch",
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
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uniq_branch_name_per_company"
            )
        ]
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
        blank=True,
        help_text="Which branches this license covers. Leave empty for a company-wide license",
    )
    license_no = models.CharField(
        max_length=100,
        unique=True,
        help_text="Official license number",
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Trade license name",
    )
    establishment_card_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Establishment card number",
    )
    license_document = models.FileField(
        upload_to="trade_licenses/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])],
        help_text="Scanned copy of the trade license",
    )
    issued_date = models.DateField(blank=True, null=True, help_text="Date license was issued")
    expiry_date = models.DateField(blank=True, null=True, help_text="Date license expires")
    max_visas = models.PositiveIntegerField(help_text="Maximum number of visa slots")

    class Meta:
        verbose_name = "trade license"
        verbose_name_plural = "trade licenses"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(expiry_date__isnull=True)
                    | models.Q(issued_date__isnull=True)
                    | models.Q(expiry_date__gte=models.F("issued_date"))
                ),
                name="license_expiry_after_issue",
            ),
            models.CheckConstraint(
                check=models.Q(max_visas__gt=0),
                name="license_max_visas_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "license_no"], name="license_company_no_idx"),
            models.Index(fields=["company", "issued_date", "expiry_date"], name="license_date_range_idx"),
        ]

    def clean(self):
        """Validate logical consistency and branch-company rules."""
        issued = self.issued_date
        expiry = self.expiry_date
        if isinstance(issued, str):
            issued = date.fromisoformat(issued)
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)
        if issued and expiry and expiry < issued:
            raise ValidationError("Expiry date must be after issued date")
        if self.max_visas <= 0:
            raise ValidationError({"max_visas": "Must be greater than 0"})
        branches = self.branches.all() if self.pk else getattr(self, "_branches_cache", [])
        if any(b.company_id != self.company_id for b in branches):
            raise ValidationError("Branches must belong to the license company")

    def __str__(self) -> str:
        branches = ", ".join(b.name for b in self.branches.all()) if self.pk else ""
        return f"{self.license_no} - {self.company.name}" + (f" - {branches}" if branches else "")


class Department(models.Model):
    """Organizational department within a branch.

    Departments referenced by employees are protected from deletion; archive or
    mark them inactive rather than removing them.
    """

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
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"], name="uniq_department_name_per_branch"
            )
        ]
        indexes = [
            models.Index(fields=["branch", "name"], name="dept_branch_name_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.branch.name} - {self.branch.company.name}"


class Project(models.Model):
    """Project carried out by a branch.

    Projects with assigned employees cannot be deleted. To retire a project,
    mark it inactive instead of deleting it.
    """

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
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="project_end_on_or_after_start",
            ),
            models.UniqueConstraint(
                fields=["branch", "name"], name="uniq_project_name_per_branch"
            ),
        ]
        indexes = [
            models.Index(fields=["branch", "name"], name="project_branch_name_idx"),
            models.Index(
                fields=["branch", "start_date", "end_date"],
                name="project_date_range_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("end_date must be on/after start_date")

    def __str__(self) -> str:
        return f"{self.name} - {self.branch.name} - {self.branch.company.name}"



class Employee(AbstractUser):
    """User account combined with employment info."""

    VISA_TYPE_CHOICES = [
        ("company", "Company"),
        ("personal", "Personal"),
        ("visit", "Visit"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("wps", "WPS"),
        ("cash", "Cash"),
    ]

    visa_type = models.CharField(
        max_length=20,
        choices=VISA_TYPE_CHOICES,
        default="company",
        help_text="Whether the employee uses a company, personal, or visit visa",
    )

    middle_name = models.CharField(
        max_length=150,
        blank=True,
        help_text="Middle name",
    )

    primary_contact = models.CharField(
        max_length=20,
        blank=True,
        help_text="Primary contact number",
    )
    secondary_contact = models.CharField(
        max_length=20,
        blank=True,
        help_text="Secondary contact number",
    )
    nationality = CountryField(blank=True, help_text="Nationality")
    payment_status = models.CharField(
        max_length=10,
        choices=PAYMENT_STATUS_CHOICES,
        default="cash",
        help_text=(
            "Payment method: WPS or Cash. Automatically cash for personal or visit visas"
        ),
    )
    wps_account_number = models.CharField(
        max_length=30,
        blank=True,
        help_text=(
            "WPS account number (required if payment status is WPS; not allowed for personal or visit visas)"
        ),
    )
    current_address = models.TextField(blank=True, help_text="Current residential address")
    permanent_address = models.TextField(blank=True, help_text="Permanent home country address")
    hometown = models.CharField(
        max_length=255,
        blank=True,
        help_text="Hometown",
    )
    gender = models.CharField(
        max_length=10,
        blank=True,
        choices=[("male", "Male"), ("female", "Female")],
        help_text="Gender",
    )
    visa_file_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Government visa file number",
    )
    wps_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="WPS ID (not allowed for personal or visit visas)",
    )
    c3_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="C3 ID (not allowed for personal or visit visas)",
    )
    profile_picture = models.ImageField(
        upload_to="profile_pictures/",
        blank=True,
        null=True,
        help_text="Profile picture",
    )
    special_notes = models.TextField(
        blank=True,
        help_text="Special notes about the employee",
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
        on_delete=models.PROTECT,
        related_name="employees",
        help_text="Department assigned; protected from deletion",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="employees",
        help_text="Project assigned; protected from deletion",
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
    hire_date = models.DateField(help_text="Date of joining")
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
                    | models.Q(visa_type__in=["personal", "visit"], trade_license__isnull=True)
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
            models.Index(
                fields=["first_name", "middle_name", "last_name"],
                name="emp_name_idx",
            ),
            models.Index(
                fields=["designation", "employment_type"],
                name="emp_desig_type_idx",
            ),
            models.Index(fields=["visa_type"], name="employee_visa_type_idx"),
            models.Index(fields=["hire_date"], name="emp_hire_date_idx"),
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
            today = timezone.now().date()
            expiry = self.trade_license.expiry_date
            if expiry:
                if isinstance(expiry, str):
                    expiry = date.fromisoformat(expiry)
                if expiry < today:
                    raise ValidationError("Cannot assign an expired trade license to an employee")
            current = self.trade_license.employees.exclude(pk=self.pk).count()
            if current >= self.trade_license.max_visas:
                raise ValidationError("Visa quota reached")

            if self.designation and self.designation.company != self.trade_license.company:
                raise ValidationError("Designation must match company")

            if self.trade_license.company != branch.company:
                raise ValidationError("License company must match branch company")
            if self.trade_license.branches.exists() and not self.trade_license.branches.filter(pk=branch.pk).exists():
                raise ValidationError("Trade license does not cover employee's branch")
        else:  # personal or visit visa
            if self.trade_license:
                raise ValidationError({"trade_license": ["Trade license must be empty for personal or visit visa"]})
            if self.payment_status != "cash":
                raise ValidationError({"payment_status": ["Personal or visit visa requires cash payment"]})
            if self.wps_account_number:
                raise ValidationError({
                    "wps_account_number": [
                        "WPS account number must be empty for personal or visit visa"
                    ]
                })
            if self.wps_id:
                raise ValidationError({"wps_id": ["WPS ID must be empty for personal or visit visa"]})
            if self.c3_id:
                raise ValidationError({"c3_id": ["C3 ID must be empty for personal or visit visa"]})

        # Personal visa with designation company mismatch:
        # ensure designation matches branch.company
        if self.designation and self.designation.company != branch.company:
            raise ValidationError("Designation must match company")

        if self.work_calendar and self.work_calendar.company_id != branch.company_id:
            raise ValidationError("Work calendar company must match employee company")

        if self.payment_status == "wps" and not self.wps_account_number:
            raise ValidationError({"wps_account_number": ["WPS account number required when payment status is WPS"]})
        if self.payment_status != "wps" and self.wps_account_number:
            raise ValidationError({"wps_account_number": ["WPS account number must be empty unless payment status is WPS"]})

    def __str__(self) -> str:
        name = " ".join(
            part for part in [self.first_name, self.middle_name, self.last_name] if part
        )
        parts = [name]
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


class HolidayAuditLog(models.Model):
    """Audit trail for holiday changes."""

    ACTION_CHOICES = [
        ("created", "created"),
        ("updated", "updated"),
        ("deleted", "deleted"),
    ]

    calendar = models.ForeignKey(
        WorkCalendar,
        on_delete=models.CASCADE,
        related_name="holiday_audit_logs",
        help_text="Calendar this audit entry relates to",
    )
    name = models.CharField(max_length=255, help_text="Holiday name at change time")
    old_date = models.DateField(null=True, blank=True, help_text="Previous holiday date")
    new_date = models.DateField(null=True, blank=True, help_text="New holiday date")
    action = models.CharField(max_length=7, choices=ACTION_CHOICES, help_text="Change action")
    timestamp = models.DateTimeField(auto_now_add=True, help_text="When the change occurred")

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.calendar_id}:{self.name}:{self.action}"


def effective_calendar_for(employee):
    """Resolve the effective work calendar for an employee."""
    return (
        employee.work_calendar
        or (employee.branch.work_calendar if employee.branch else None)
        or employee.company.calendars.filter(is_default=True).first()
    )


def holiday_flags(employee, target_date, is_holiday=None):
    """Determine holiday flags for a roster entry.

    Returns a tuple ``(is_holiday, was_holiday)`` where ``is_holiday`` is the
    effective flag (respecting manual overrides) and ``was_holiday`` records if
    the date is a holiday in the employee's calendar.
    """

    calendar = effective_calendar_for(employee)
    was_holiday = bool(
        calendar and calendar.holidays.filter(date=target_date).exists()
    )
    if is_holiday is None:
        is_holiday = was_holiday
    return is_holiday, was_holiday


def _minutes_between(start, end, cross_midnight):
    """Return minutes between two times accounting for next-day shifts."""
    d = date(2000, 1, 1)
    a = datetime.combine(d, start)
    b = datetime.combine(d + timedelta(days=1 if cross_midnight else 0), end)
    return int((b - a).total_seconds() // 60)


WEEKDAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def normalize_weekdays(value: str) -> str:
    """Normalize comma separated weekdays to canonical abbreviations."""
    parts = [p.strip().upper() for p in value.split(",") if p.strip()]
    if len(parts) != len(set(parts)) or any(p not in WEEKDAY_ORDER for p in parts):
        raise ValidationError(
            "weekdays must be comma separated MON-SUN abbreviations without duplicates"
        )
    ordered = [d for d in WEEKDAY_ORDER if d in parts]
    return ",".join(ordered)


class ShiftTemplate(models.Model):
    """Reusable description of a work shift.

    For cross_midnight shifts (e.g. 22:00→06:00) the shift starts on day D and
    ends on day D+1.
    """

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
        help_text=(
            "Rule value. For time windows use HH:MM-HH:MM and it may cross midnight "
            "(e.g. 22:00-04:00)"
        ),
    )
    params = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Additional parameters; break rules require paid (bool) and enforcement "
            "(warn, flag, auto_deduct, block)"
        ),
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
            self.weekdays = normalize_weekdays(self.weekdays)
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

    def save(self, *args, **kwargs):
        if self.weekdays:
            self.weekdays = normalize_weekdays(self.weekdays)
        super().save(*args, **kwargs)

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
    is_holiday = models.BooleanField(
        default=False,
        help_text="Treat the day as a holiday (auto-set for calendar holidays)",
    )
    was_holiday = models.BooleanField(
        default=False,
        editable=False,
        help_text="True if the date was a holiday when scheduled",
    )

    class Meta:
        unique_together = (("employee", "date"),)
        ordering = ["date"]
        indexes = [
            models.Index(
                fields=["employee", "date"], name="roster_employee_date_idx"
            ),
            models.Index(fields=["date"], name="roster_date_idx"),
        ]

    def clean(self):
        super().clean()
        if self.override_start and self.override_end and self.override_end <= self.override_start:
            raise ValidationError("override_end must be after override_start")

        # Ensure overrides are within a reasonable range of the scheduled times
        if self.override_start or self.override_end:
            shift_start = datetime.combine(date(2000, 1, 1), self.shift.start_time)
            shift_end = datetime.combine(date(2000, 1, 1), self.shift.end_time)
            if self.shift.cross_midnight and shift_end <= shift_start:
                shift_end += timedelta(days=1)

            if self.override_start:
                os_dt = datetime.combine(date(2000, 1, 1), self.override_start)
                if not (
                    shift_start - timedelta(hours=8)
                    <= os_dt
                    <= shift_start + timedelta(hours=8)
                ):
                    raise ValidationError(
                        "override_start must be within 8 hours of shift start"
                    )

            if self.override_end:
                oe_dt = datetime.combine(date(2000, 1, 1), self.override_end)
                if self.shift.cross_midnight and oe_dt <= shift_start:
                    oe_dt += timedelta(days=1)
                if not (
                    shift_end - timedelta(hours=8)
                    <= oe_dt
                    <= shift_end + timedelta(hours=8)
                ):
                    raise ValidationError(
                        "override_end must be within 8 hours of shift end"
                    )

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
                F("company"),
                name="leavetype_company_code_ci_unique",
            ),
        ]

    def clean(self):
        if not (Decimal("0") <= self.paid_pct <= Decimal("100")):
            raise ValidationError("paid_pct must be between 0 and 100")

    def __str__(self) -> str:
        return f"{self.code} - {self.company.name}"
