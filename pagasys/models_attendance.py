"""Attendance and leave models for shift based tracking."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .models import Company, Employee


class Device(models.Model):
    """Physical or virtual device capturing attendance events."""

    DEVICE_TYPE_CHOICES = [
        ("kiosk", "Kiosk"),
        ("mobile", "Mobile"),
        ("web", "Web"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="devices",
        help_text="Company that owns the device",
    )
    name = models.CharField(max_length=100, help_text="Device identifier")
    device_type = models.CharField(
        max_length=10, choices=DEVICE_TYPE_CHOICES, help_text="Device type"
    )
    hmac_secret = models.CharField(
        max_length=64,
        help_text="Shared secret for validating payload signatures",
    )
    geofence = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional geofence definition for device location",
    )

    class Meta:
        verbose_name = "device"
        verbose_name_plural = "devices"
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["company", "device_type"],
                name="device_company_type_idx",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.get_device_type_display()})"


class AttEvent(models.Model):
    """Immutable raw attendance events from devices."""

    DIRECTION_CHOICES = [("IN", "In"), ("OUT", "Out"), ("UNK", "Unknown")]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="attendance_events",
        help_text="Company of the employee",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_events",
        help_text="Employee generating the event",
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="events",
        help_text="Device used for the event",
    )
    direction = models.CharField(
        max_length=3, choices=DIRECTION_CHOICES, help_text="Punch direction"
    )
    ts = models.DateTimeField(help_text="Timestamp in UTC")
    provider = models.CharField(max_length=50, help_text="Event provider identifier")
    face_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Face match confidence",
    )
    liveness = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Liveness score from provider",
    )
    signed_payload = models.TextField(help_text="Original signed payload")

    class Meta:
        verbose_name = "attendance event"
        verbose_name_plural = "attendance events"
        ordering = ["ts"]
        indexes = [
            models.Index(
                fields=["company", "employee", "ts"],
                name="att_event_comp_emp_ts_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "ts", "device"],
                condition=~models.Q(direction="UNK"),
                name="att_event_emp_ts_device_unique",
            )
        ]

    def clean(self):
        """Validate cross-company consistency and direction values."""
        if (
            self.device
            and self.company_id
            and self.device.company_id != self.company_id
        ):
            raise ValidationError("Device company must match event company.")
        if self.employee_id and self.company_id:
            comp = getattr(self.employee, "company", None)
            if comp and comp.id != self.company_id:
                raise ValidationError("Employee company must match event company.")
        if self.direction not in {"IN", "OUT", "UNK"}:
            raise ValidationError("Invalid direction.")

    def save(self, *args, **kwargs):
        """Run validation and prevent mutation after insert."""
        if self.pk and not self._state.adding:
            raise ValidationError("Attendance events are immutable")
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} {self.direction} {self.ts.isoformat()}"


class WorkCalendar(models.Model):
    """Company specific working calendar with optional default flag."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="calendars",
        help_text="Company using the calendar",
    )
    name = models.CharField(max_length=100, help_text="Calendar name")
    is_default = models.BooleanField(
        default=False, help_text="Default calendar for the company"
    )

    class Meta:
        verbose_name = "work calendar"
        verbose_name_plural = "work calendars"
        unique_together = (("company", "name"),)
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=models.Q(is_default=True),
                name="unique_default_calendar_per_company",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} - {self.company.name}"


class Holiday(models.Model):
    """Holiday entry associated with a work calendar."""

    calendar = models.ForeignKey(
        WorkCalendar,
        on_delete=models.CASCADE,
        related_name="holidays",
        help_text="Calendar containing this holiday",
    )
    date = models.DateField(help_text="Holiday date")
    name = models.CharField(max_length=100, help_text="Holiday name")

    class Meta:
        verbose_name = "holiday"
        verbose_name_plural = "holidays"
        unique_together = (("calendar", "date"),)
        ordering = ["date"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.date})"


class ShiftTemplate(models.Model):
    """Template describing a working shift."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="shift_templates",
        help_text="Company defining the shift",
    )
    name = models.CharField(max_length=100, help_text="Shift name")
    start_time = models.TimeField(help_text="Start time")
    end_time = models.TimeField(help_text="End time")
    break_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Total break minutes"
    )
    grace_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Grace minutes before late"
    )
    rounding = models.PositiveSmallIntegerField(
        default=1, help_text="Rounding minutes for calculations"
    )
    cross_midnight = models.BooleanField(
        default=False, help_text="Shift crosses midnight"
    )
    requires_face = models.BooleanField(
        default=False, help_text="Face recognition required"
    )
    shift_worker_night_exempt = models.BooleanField(
        default=False,
        help_text="Shift workers exempt from night OT",
    )

    class Meta:
        verbose_name = "shift template"
        verbose_name_plural = "shift templates"
        ordering = ["id"]

    def clean(self):
        if not self.cross_midnight and self.end_time < self.start_time:
            raise ValidationError(
                "End time must be after start time unless cross midnight"
            )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.start_time}-{self.end_time})"


class ShiftRule(models.Model):
    """Company wide rules applied to shifts."""

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="shift_rule",
        help_text="Company these rules apply to",
    )
    ramadan_reduce_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Daily minute reduction during Ramadan"
    )
    weekly_rest_day = models.PositiveSmallIntegerField(
        default=6, help_text="Weekly rest day (0=Mon ... 6=Sun)"
    )
    night_ot_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Optional night OT window start",
    )
    night_ot_end = models.TimeField(
        null=True,
        blank=True,
        help_text="Optional night OT window end",
    )
    max_daily_hours = models.PositiveSmallIntegerField(
        default=24, help_text="Maximum allowed daily work hours"
    )

    class Meta:
        verbose_name = "shift rule"
        verbose_name_plural = "shift rules"
        ordering = ["company"]  # stable, one row per company

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Rules for {self.company.name}"


class RosterEntry(models.Model):
    """Planned shift assignment per employee and date."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="roster_entries",
        help_text="Employee assigned",
    )
    date = models.DateField(help_text="Roster date")
    shift = models.ForeignKey(
        ShiftTemplate,
        on_delete=models.PROTECT,
        related_name="roster_entries",
        help_text="Shift to apply",
    )
    overrides = models.JSONField(
        null=True, blank=True, help_text="Optional calculation overrides"
    )

    class Meta:
        verbose_name = "roster entry"
        verbose_name_plural = "roster entries"
        unique_together = (("employee", "date"),)
        indexes = [
            models.Index(fields=["employee", "date"], name="roster_employee_date_idx")
        ]
        ordering = ["date"]

    def clean(self):
        if not (self.employee.department or self.employee.project) or (
            self.employee.department and self.employee.project
        ):
            raise ValidationError(
                "Employee must belong to exactly one of department or project"
            )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} on {self.date}"


class AttPair(models.Model):
    """Paired in/out events for a work period.

    Derived timestamp and duration fields are stored to speed up daily rollups
    and reporting while retaining references to the raw events for auditing.
    """

    QUALITY_CHOICES = [
        ("good", "Good"),
        ("suspect", "Suspect"),
        ("missing", "Missing"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_pairs",
        help_text="Employee for the pair",
    )
    in_event = models.ForeignKey(
        AttEvent,
        on_delete=models.PROTECT,
        related_name="pair_as_in",
        help_text="In event",
    )
    out_event = models.ForeignKey(
        AttEvent,
        on_delete=models.PROTECT,
        related_name="pair_as_out",
        null=True,
        blank=True,
        help_text="Out event",
    )
    quality = models.CharField(
        max_length=20, choices=QUALITY_CHOICES, default="good", help_text="Pair quality"
    )
    in_ts = models.DateTimeField(db_index=True)
    out_ts = models.DateTimeField(null=True, blank=True)
    duration_min = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "attendance pair"
        verbose_name_plural = "attendance pairs"
        ordering = ["in_event__ts"]
        indexes = [
            models.Index(fields=["employee", "in_ts"], name="attpair_emp_in_idx")
        ]

    def save(self, *args, **kwargs):
        """Cache event timestamps and duration for efficient queries."""
        self.in_ts = self.in_event.ts
        self.out_ts = self.out_event.ts if self.out_event else None
        if self.out_ts:
            delta = self.out_ts - self.in_ts
            self.duration_min = max(0, int(delta.total_seconds() // 60))
        else:
            self.duration_min = 0
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} {self.in_event.ts.date()}"


class AttDay(models.Model):
    """Computed attendance metrics per day.

    Tracks the shift template used for calculations and exposes a broader set
    of status values for clarity.
    """

    STATUS_CHOICES = [
        ("present", "Present"),
        ("absent", "Absent"),
        ("leave", "Leave"),
        ("holiday", "Holiday"),
        ("rest", "Rest Day"),
        ("missing", "Missing Punch"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_days",
        help_text="Employee for the day",
    )
    date = models.DateField(help_text="Calendar date")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, help_text="Attendance status"
    )
    shift = models.ForeignKey(
        "ShiftTemplate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Shift template used for this day’s calculation",
    )
    work_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Worked minutes"
    )
    late_minutes = models.PositiveSmallIntegerField(default=0, help_text="Late minutes")
    early_leave_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Minutes left early"
    )
    ot125_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Overtime minutes at 1.25x"
    )
    ot150_minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Overtime minutes at 1.50x"
    )
    notes = models.JSONField(default=dict, blank=True, help_text="Additional notes")
    locked = models.BooleanField(default=False, help_text="Locked from recalculation")

    class Meta:
        verbose_name = "attendance day"
        verbose_name_plural = "attendance days"
        unique_together = (("employee", "date"),)
        indexes = [
            models.Index(fields=["employee", "date"], name="attday_employee_date_idx")
        ]
        ordering = ["date"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} {self.date} {self.status}"


class LeaveType(models.Model):
    """Type of leave with associated default pay percentage."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="leave_types",
        help_text="Company defining the leave type",
    )
    name = models.CharField(max_length=100, help_text="Leave type name")
    pay_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Default percentage of pay during leave",
    )

    class Meta:
        verbose_name = "leave type"
        verbose_name_plural = "leave types"
        unique_together = (("company", "name"),)
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} - {self.company.name}"


class LeaveRequest(models.Model):
    """Employee leave request covering a date range, with optional pay override."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        help_text="Requesting employee",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name="requests",
        help_text="Leave type",
    )
    start_date = models.DateField(help_text="Start date")
    end_date = models.DateField(help_text="End date")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        help_text="Request status",
    )
    reason = models.TextField(blank=True, help_text="Optional reason")
    pay_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Override pay percentage for this request",
    )

    class Meta:
        verbose_name = "leave request"
        verbose_name_plural = "leave requests"
        ordering = ["start_date"]

    def clean(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError("start_date must be before or equal to end_date")

    def get_pay_percent(self) -> "Decimal":
        """Return effective pay percent for the request."""
        if self.pay_percent is not None:
            return self.pay_percent
        return self.leave_type.pay_percent

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} {self.start_date}-{self.end_date}"


class LeaveDay(models.Model):
    """Per-day leave details allowing partial day minutes and pay overrides."""

    request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.CASCADE,
        related_name="days",
        help_text="Parent leave request",
    )
    date = models.DateField(help_text="Leave date")
    minutes = models.PositiveSmallIntegerField(
        default=0, help_text="Leave minutes on this date"
    )
    pay_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Override pay percentage for this day",
    )

    class Meta:
        verbose_name = "leave day"
        verbose_name_plural = "leave days"
        unique_together = (("request", "date"),)
        ordering = ["date"]

    def get_pay_percent(self) -> "Decimal":
        """Return effective pay percent for the day."""
        if self.pay_percent is not None:
            return self.pay_percent
        return self.request.get_pay_percent()

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.request.employee} {self.date}"
