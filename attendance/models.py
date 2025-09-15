from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from pagasys.models import Employee, ShiftTemplate, RosterEntry, LeaveType


class LeaveRequest(models.Model):
    """Employee-submitted leave request awaiting approval."""

    STATUS = [
        ("pending", "pending"),
        ("approved", "approved"),
        ("rejected", "rejected"),
        ("cancelled", "cancelled"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    date_from = models.DateField()
    date_to = models.DateField()
    partial_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Time when leave begins for a partial day",
    )
    partial_end = models.TimeField(
        null=True,
        blank=True,
        help_text="Time when leave ends for a partial day",
    )
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by_id = models.IntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["employee", "date_from", "date_to"]),
            models.Index(fields=["status"]),
        ]


class LeaveDay(models.Model):
    """Materialized, approved leave per day for fast compute."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_days",
    )
    date = models.DateField()
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    paid_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Percent of this leave day that is paid (0-100)",
    )
    portion = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1,
        help_text="Portion of the day covered by leave (1=full, 0.5=half)",
    )
    request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.CASCADE,
        related_name="days",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("employee", "date", "request"),)
        indexes = [models.Index(fields=["employee", "date"])]


class AttPair(models.Model):
    """Paired session from IN/OUT events."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="att_pairs",
    )
    date = models.DateField(help_text="Roster date this pair belongs to")
    in_event_id = models.IntegerField(
        help_text="ID of the originating IN punch event",
    )
    out_event_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ID of the OUT punch event, if any",
    )
    in_ts = models.DateTimeField(
        help_text="Timestamp of the IN punch",
    )
    out_ts = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the OUT punch, if any",
    )
    duration_min = models.IntegerField(
        default=0,
        help_text="Minutes between in_ts and out_ts, capped per policy",
    )
    cross_midnight = models.BooleanField(
        default=False,
        help_text="True if out_ts falls on the day after in_ts",
    )
    source = models.CharField(
        max_length=10,
        choices=[("auto", "auto"), ("manual", "manual")],
        default="auto",
        help_text=(
            "Origin of the pair; 'auto' punches open a new session or close"
            " the current one, while 'manual' pairs are entered by managers"
        ),
    )
    anomaly = models.JSONField(
        default=dict,
        help_text=(
            "Canonical anomalies detected for this pair, e.g."
            " {'missing_out_closed_at_next_in': true}"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("employee", "in_event_id"),)
        indexes = [
            models.Index(fields=["employee", "date"]),
            models.Index(fields=["employee", "in_ts"]),
        ]


class AttDay(models.Model):
    """Canonical, lockable daily outcome for payroll."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="att_days",
    )
    date = models.DateField()
    shift = models.ForeignKey(
        ShiftTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    roster = models.ForeignKey(
        RosterEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    work_min = models.IntegerField(
        default=0,
        help_text="Net work minutes after unpaid breaks and deductions",
    )
    unpaid_break_min = models.IntegerField(
        default=0,
        help_text="Total unpaid break minutes deducted from work_min",
    )
    paid_break_min = models.IntegerField(
        default=0,
        help_text="Paid break minutes that do not reduce work_min",
    )
    late_min = models.IntegerField(
        default=0,
        help_text="Minutes late beyond shift start after grace",
    )
    early_leave_min = models.IntegerField(
        default=0,
        help_text="Minutes left early before shift end after grace",
    )

    ot_regular_min = models.IntegerField(
        default=0,
        help_text="Overtime minutes outside night/holiday buckets",
    )
    ot_night_min = models.IntegerField(
        default=0,
        help_text="Overtime minutes classified as night",
    )
    ot_holiday_min = models.IntegerField(
        default=0,
        help_text="Overtime minutes worked on holidays",
    )

    is_holiday = models.BooleanField(default=False)
    is_rest_day = models.BooleanField(default=False)
    on_leave = models.BooleanField(default=False)
    leave_portion = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0,
        help_text="Portion of the day covered by approved leave (0-1)",
    )
    status = models.CharField(
        max_length=16,
        default="absent",
        choices=[
            ("present", "present"),
            ("absent", "absent"),
            ("leave", "leave"),
            ("holiday", "holiday"),
            ("rest", "rest"),
            ("partial", "partial"),
        ],
        help_text="Final attendance status consumed by payroll and reports",
    )

    pairs_count = models.IntegerField(
        default=0,
        help_text="Number of AttPair sessions contributing to this day",
    )
    punches_used = models.IntegerField(
        default=0,
        help_text="Total punch events used to build the pairs",
    )
    anomalies = models.JSONField(
        default=dict,
        help_text=(
            "Counts keyed by canonical anomaly names: unpaired_out, "
            "missing_out_closed_at_next_in, missing_out, auto_closed, capped, "
            "face_required_no_match, geofence_rule_violation, outside_scope, "
            "manual_adjustments_applied"
        ),
    )
    compute_version = models.IntegerField(
        default=1,
        help_text="Internal algorithm version used for this compute",
    )
    computed_at = models.DateTimeField(auto_now=True)
    locked = models.BooleanField(
        default=False,
        help_text="Freeze this day to prevent recomputation or adjustments",
    )

    class Meta:
        unique_together = (("employee", "date"),)
        indexes = [
            models.Index(fields=["employee", "date"]),
            models.Index(fields=["locked"]),
            models.Index(fields=["date", "late_min"]),
        ]


class AttAdjustment(models.Model):
    """Manual, additive adjustments to an AttDay."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        help_text="Employee whose day is adjusted",
    )
    date = models.DateField(
        help_text="Roster date the adjustment applies to",
    )
    delta_work_min = models.IntegerField(
        default=0,
        help_text="Additive minutes applied to work_min",
    )
    delta_unpaid_break_min = models.IntegerField(
        default=0,
        help_text="Additive minutes applied to unpaid_break_min",
    )
    delta_paid_break_min = models.IntegerField(
        default=0,
        help_text="Additive minutes applied to paid_break_min",
    )
    delta_ot_regular_min = models.IntegerField(
        default=0,
        help_text="Additive minutes applied to ot_regular_min",
    )
    delta_ot_night_min = models.IntegerField(
        default=0,
        help_text="Additive minutes applied to ot_night_min",
    )
    delta_ot_holiday_min = models.IntegerField(
        default=0,
        help_text="Additive minutes applied to ot_holiday_min",
    )
    override_status = models.CharField(
        max_length=16,
        blank=True,
        help_text="Override computed status (e.g. 'present')",
    )
    reason = models.CharField(
        max_length=255,
        help_text="Human-readable reason for the adjustment",
    )
    created_by_id = models.IntegerField(
        help_text=(
            "Identifier of the user who created the adjustment. "
            "Set automatically from the authenticated user."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["employee", "date"])]

    def clean(self):
        """Prevent adjustments on locked days."""
        if AttDay.objects.filter(
            employee=self.employee, date=self.date, locked=True
        ).exists():
            raise ValidationError(
                "Cannot create adjustment for a locked attendance day."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
