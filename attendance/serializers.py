from rest_framework import serializers

from django.db.models import Min

from drf_spectacular.utils import (
    OpenApiExample,
    extend_schema_field,
    extend_schema_serializer,
)

from pagasys.models import Employee
from .models import AttDay, AttPair, AttAdjustment, LeaveRequest, LeaveDay
from .services_helpers import compute_full_attendance_delta

CANONICAL_ANOMALY_KEYS = [
    "unpaired_out",
    "missing_out_closed_at_next_in",
    "missing_out",
    "auto_closed",
    "capped",
    "face_required_no_match",
    "geofence_rule_violation",
    "outside_scope",
    "overtime_over_cap",
    "break_auto_deduct_*",
    "manual_adjustments_applied",
]


class AttDayCodeLabelSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Machine-readable value used internally")
    label = serializers.CharField(help_text="Human-friendly label exposed to users")


class AttDayEmployeeSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Employee identifier")
    display = serializers.CharField(help_text="Display name rendered in the UI")


class AttDayBreakSummarySerializer(serializers.Serializer):
    unpaid = serializers.IntegerField(help_text="Unpaid break minutes deducted from work time")
    paid = serializers.IntegerField(help_text="Paid break minutes credited to the day")


class AttDayOvertimeSummarySerializer(serializers.Serializer):
    regular = serializers.IntegerField(help_text="Regular overtime minutes for the day")
    night = serializers.IntegerField(help_text="Night differential overtime minutes")
    holiday = serializers.IntegerField(help_text="Holiday overtime minutes")


class AttDayRosterShiftSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Shift template identifier")
    name = serializers.CharField(help_text="Shift template name")
    start = serializers.TimeField(help_text="Scheduled start time")
    end = serializers.TimeField(help_text="Scheduled end time")
    cross_midnight = serializers.BooleanField(
        help_text="True when the shift spans midnight"
    )
    requires_face = serializers.BooleanField(
        help_text="Whether face match is required for punches"
    )
    break_minutes = serializers.IntegerField(
        help_text="Total break minutes allocated to the shift"
    )
    total_minutes = serializers.IntegerField(
        help_text="Net scheduled minutes after unpaid breaks are deducted"
    )


class AttDayRosterAssignmentSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Roster entry identifier")
    is_rest_day = serializers.BooleanField(
        help_text="True when the roster marks the day as a rest day"
    )
    is_holiday = serializers.BooleanField(
        help_text="True when the roster marks the day as a holiday"
    )
    override_start = serializers.TimeField(
        allow_null=True,
        help_text="Override start time applied to this roster entry",
    )
    override_end = serializers.TimeField(
        allow_null=True,
        help_text="Override end time applied to this roster entry",
    )


class AttDayAnomalySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Canonical anomaly code")
    count = serializers.IntegerField(help_text="Occurrences of the anomaly")


class AttDayDeviceSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(
        allow_null=True, help_text="Primary key for the capture device"
    )
    label = serializers.CharField(
        allow_blank=True, help_text="Display label for the capture device"
    )


class AttDayPunchExceptionSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="Exception type raised during punch processing")
    details = serializers.DictField(
        allow_null=True,
        help_text="Structured payload describing the exception context",
    )

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "IN-AUTO-OUT pair",
            value={
                "id": 1,
                "employee": 1,
                "date": "2024-01-01",
                "in_event_id": 10,
                "out_event_id": 11,
                "in_ts": "2024-01-01T08:00:00+04:00",
                "out_ts": "2024-01-01T17:00:00+04:00",
                "duration_min": 540,
                "cross_midnight": False,
                "source": "auto",
                "anomaly": {},
            },
        ),
        OpenApiExample(
            "Duplicate IN closes prior session",
            value={
                "id": 2,
                "employee": 1,
                "date": "2024-01-02",
                "in_event_id": 12,
                "out_event_id": None,
                "in_ts": "2024-01-02T08:00:00+04:00",
                "out_ts": "2024-01-02T08:30:00+04:00",
                "duration_min": 30,
                "cross_midnight": False,
                "source": "auto",
                "anomaly": {"missing_out_closed_at_next_in": True},
            },
        ),
    ],
)
class AttPairSerializer(serializers.ModelSerializer):
    """Paired IN/OUT session derived from punch events.

    'auto' punches open a new session when none is active or close the
    current session. Anomalies such as 'missing_out_closed_at_next_in'
    appear when a new IN arrives before an OUT.
    """

    class Meta:
        model = AttPair
        fields = "__all__"
        read_only_fields = [f.name for f in AttPair._meta.fields]


class ManualAttPairSerializer(serializers.ModelSerializer):
    """Serializer for creating manual attendance pairs."""

    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), help_text="Employee ID"
    )
    date = serializers.DateField(help_text="Roster date in YYYY-MM-DD")
    in_ts = serializers.DateTimeField(help_text="Clock-in timestamp in ISO 8601 with timezone")
    out_ts = serializers.DateTimeField(help_text="Clock-out timestamp in ISO 8601 with timezone")

    class Meta:
        model = AttPair
        fields = ["employee", "date", "in_ts", "out_ts"]

    def validate(self, attrs):
        if attrs["out_ts"] <= attrs["in_ts"]:
            raise serializers.ValidationError("out_ts must be after in_ts")
        return attrs

    def create(self, validated_data):
        employee = validated_data["employee"]
        in_ts = validated_data["in_ts"]
        out_ts = validated_data["out_ts"]
        date = validated_data["date"]
        duration = int((out_ts - in_ts).total_seconds() // 60)
        min_id = (
            AttPair.objects.filter(employee=employee).aggregate(m=Min("in_event_id"))[
                "m"
            ]
            or 0
        )
        in_event_id = min_id - 1  # ensure uniqueness using negative IDs
        return AttPair.objects.create(
            employee=employee,
            date=date,
            in_event_id=in_event_id,
            out_event_id=None,
            in_ts=in_ts,
            out_ts=out_ts,
            duration_min=duration,
            cross_midnight=in_ts.date() != out_ts.date(),
            source="manual",
            anomaly={}
        )


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Day with anomalies",
            value={
                "id": 1,
                "employee": 1,
                "date": "2024-01-02",
                "work_min": 450,
                "anomalies": {"unpaired_out": 1, "face_required_no_match": 2},
            },
        )
    ]
)
class AttDaySerializer(serializers.ModelSerializer):
    """Canonical anomaly keys: {}""".format(", ".join(CANONICAL_ANOMALY_KEYS))

    anomalies = serializers.DictField(
        child=serializers.IntegerField(),
        read_only=True,
        help_text=(
            "Counts keyed by canonical anomaly names (e.g. "
            + ", ".join(CANONICAL_ANOMALY_KEYS)
            + "). Keys like 'break_auto_deduct_<rule_id>' use a rule-specific suffix."
        ),
    )

    class Meta:
        model = AttDay
        fields = "__all__"
        read_only_fields = [f.name for f in AttDay._meta.fields]


class LeaveRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = "__all__"
        read_only_fields = ["status", "created_at", "decided_at"]


class LeaveDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveDay
        fields = "__all__"
        read_only_fields = [f.name for f in LeaveDay._meta.fields]


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Add 30 minutes paid break and override status",
            value={
                "employee": 1,
                "date": "2024-01-03",
                "delta_paid_break_min": 30,
                "override_status": "present",
                "reason": "Manager approved paid break",
            },
        )
    ]
)
class AttAdjustmentSerializer(serializers.ModelSerializer):
    """Manual, additive deltas applied after computation. Negative values reduce
    totals. Set `override_status` to replace the computed AttDay.status."""
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), help_text="Employee ID"
    )
    mark_full_attendance = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
        help_text=(
            "When true, delta_work_min is set to the minutes needed to meet the "
            "scheduled shift total."
        ),
    )

    class Meta:
        model = AttAdjustment
        fields = "__all__"
        read_only_fields = ["created_at", "created_by_id"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        mark_full = attrs.pop("mark_full_attendance", False)
        if mark_full:
            employee = attrs.get("employee") or getattr(
                self.instance, "employee", None
            )
            date_value = attrs.get("date") or getattr(
                self.instance, "date", None
            )
            if not employee or not date_value:
                raise serializers.ValidationError(
                    {
                        "mark_full_attendance": (
                            "Employee and date are required to mark full attendance."
                        )
                    }
                )
            try:
                delta = compute_full_attendance_delta(employee.id, date_value)
            except ValueError as exc:
                raise serializers.ValidationError(
                    {"mark_full_attendance": str(exc)}
                ) from exc
            attrs["delta_work_min"] = delta
        return attrs


class PairSessionContextSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    in_ts = serializers.DateTimeField()
    out_ts = serializers.DateTimeField(allow_null=True)
    duration_min = serializers.IntegerField()
    cross_midnight = serializers.BooleanField()
    source = serializers.SerializerMethodField()
    anomalies = serializers.ListField(child=serializers.CharField())
    in_event_id = serializers.IntegerField(allow_null=True)
    out_event_id = serializers.IntegerField(allow_null=True)

    @extend_schema_field(AttDayCodeLabelSerializer)
    def get_source(self, data):
        return {
            "code": data.get("source_value"),
            "label": data.get("source"),
        }


class PunchEventContextSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    device_ts = serializers.DateTimeField()
    server_ts = serializers.DateTimeField()
    action = serializers.CharField()
    device = serializers.SerializerMethodField()
    face_matched = serializers.BooleanField()
    requires_face = serializers.BooleanField()
    geofence_ok = serializers.BooleanField(allow_null=True)
    geofence_rule_violation = serializers.BooleanField()
    out_of_scope = serializers.BooleanField()
    roster_fallback = serializers.BooleanField()
    roster_date = serializers.DateField(allow_null=True)
    exception = serializers.SerializerMethodField()
    notes = serializers.CharField(allow_blank=True)

    @extend_schema_field(AttDayDeviceSummarySerializer)
    def get_device(self, data):
        return {
            "id": data.get("device_id"),
            "label": data.get("device_label"),
        }

    @extend_schema_field(AttDayPunchExceptionSerializer(allow_null=True))
    def get_exception(self, data):
        exception = data.get("exception")
        if not exception:
            return None
        return {
            "kind": exception.get("kind"),
            "details": exception.get("details"),
        }


class AttDayRosterOverviewSerializer(serializers.Serializer):
    employee = serializers.SerializerMethodField()
    date = serializers.DateField()
    status = serializers.SerializerMethodField()
    locked = serializers.BooleanField()
    work_min = serializers.IntegerField()
    breaks = serializers.SerializerMethodField()
    late_min = serializers.IntegerField()
    early_leave_min = serializers.IntegerField()
    overtime = serializers.SerializerMethodField()
    shift = serializers.SerializerMethodField()
    roster = serializers.SerializerMethodField()
    anomalies = serializers.SerializerMethodField()

    @extend_schema_field(AttDayEmployeeSummarySerializer)
    def get_employee(self, data):
        return {
            "id": data.get("employee_id"),
            "display": data.get("employee_display"),
        }

    @extend_schema_field(AttDayCodeLabelSerializer)
    def get_status(self, data):
        return {
            "code": data.get("status_value"),
            "label": data.get("status"),
        }

    @extend_schema_field(AttDayBreakSummarySerializer)
    def get_breaks(self, data):
        return {
            "unpaid": data.get("unpaid_break_min"),
            "paid": data.get("paid_break_min"),
        }

    @extend_schema_field(AttDayOvertimeSummarySerializer)
    def get_overtime(self, data):
        return {
            "regular": data.get("ot_regular_min"),
            "night": data.get("ot_night_min"),
            "holiday": data.get("ot_holiday_min"),
        }

    @extend_schema_field(AttDayRosterShiftSerializer(allow_null=True))
    def get_shift(self, data):
        shift = data.get("shift")
        if not shift:
            return None
        return {
            "id": shift.get("id"),
            "name": shift.get("name"),
            "start": shift.get("start_time"),
            "end": shift.get("end_time"),
            "cross_midnight": shift.get("cross_midnight"),
            "requires_face": shift.get("requires_face"),
            "break_minutes": shift.get("break_minutes"),
            "total_minutes": shift.get("total_minutes"),
        }

    @extend_schema_field(AttDayRosterAssignmentSerializer(allow_null=True))
    def get_roster(self, data):
        roster = data.get("roster")
        if not roster:
            return None
        return {
            "id": roster.get("id"),
            "is_rest_day": roster.get("is_rest_day"),
            "is_holiday": roster.get("is_holiday"),
            "override_start": roster.get("override_start"),
            "override_end": roster.get("override_end"),
        }

    @extend_schema_field(AttDayAnomalySerializer(many=True))
    def get_anomalies(self, data):
        anomalies = data.get("anomalies") or []
        return [
            {"key": entry.get("key", entry.get("name")), "count": entry.get("count")}
            for entry in anomalies
        ]


ATT_DAY_FULL_CONTEXT_EXAMPLE = {
    "day": {
        "id": 1,
        "employee": 123,
        "date": "2024-05-20",
        "status": "present",
        "work_min": 480,
        "ot_regular_min": 30,
        "locked": False,
        "anomalies": {"missing_out": 1},
    },
    "roster_overview": {
        "employee": {"id": 123, "display": "Alice Anderson"},
        "date": "2024-05-20",
        "status": {"code": "present", "label": "Present"},
        "locked": False,
        "work_min": 480,
        "breaks": {"unpaid": 60, "paid": 0},
        "late_min": 5,
        "early_leave_min": 0,
        "overtime": {"regular": 30, "night": 0, "holiday": 0},
        "shift": {
            "id": 4,
            "name": "Day",
            "start": "09:00:00",
            "end": "17:00:00",
            "cross_midnight": False,
            "requires_face": True,
            "break_minutes": 60,
            "total_minutes": 420,
        },
        "roster": {
            "id": 9,
            "is_rest_day": False,
            "is_holiday": False,
            "override_start": "09:00:00",
            "override_end": "17:00:00",
        },
        "anomalies": [
            {"key": "missing_out", "count": 1},
        ],
    },
    "pair_sessions": [
        {
            "id": 99,
            "in_ts": "2024-05-20T08:00:00+04:00",
            "out_ts": "2024-05-20T17:00:00+04:00",
            "duration_min": 540,
            "cross_midnight": False,
            "source": {"code": "auto", "label": "Automatic"},
            "anomalies": ["missing_out_closed_at_next_in"],
            "in_event_id": 555,
            "out_event_id": 556,
        }
    ],
    "punch_events": [
        {
            "id": 555,
            "device_ts": "2024-05-20T07:59:32+04:00",
            "server_ts": "2024-05-20T08:00:01+04:00",
            "action": "in",
            "device": {"id": 42, "label": "Main Gate"},
            "face_matched": True,
            "requires_face": True,
            "geofence_ok": True,
            "geofence_rule_violation": False,
            "out_of_scope": False,
            "roster_fallback": False,
            "roster_date": "2024-05-20",
            "exception": None,
            "notes": "",
        }
    ],
    "adjustments": [
        {
            "id": 7,
            "employee": 123,
            "date": "2024-05-20",
            "delta_work_min": 30,
            "delta_unpaid_break_min": 0,
            "delta_paid_break_min": 0,
            "delta_ot_regular_min": 0,
            "delta_ot_night_min": 0,
            "delta_ot_holiday_min": 0,
            "override_status": "present",
            "reason": "Manager approved overtime",
            "created_by_id": 3,
            "created_at": "2024-05-21T09:00:00Z",
        }
    ],
}


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            "Attendance day full context",
            value=ATT_DAY_FULL_CONTEXT_EXAMPLE,
            response_only=True,
        )
    ]
)
class AttDayFullContextSerializer(serializers.Serializer):
    day = AttDaySerializer()
    roster_overview = AttDayRosterOverviewSerializer()
    pair_sessions = PairSessionContextSerializer(many=True)
    punch_events = PunchEventContextSerializer(many=True)
    adjustments = AttAdjustmentSerializer(many=True)

    class Meta:
        example = ATT_DAY_FULL_CONTEXT_EXAMPLE


class RecomputeRangeSerializer(serializers.Serializer):
    """Serializer for recompute and lock actions."""

    employee_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Optional list of employee IDs to limit the operation",
    )
    start = serializers.DateField(
        help_text="Start date in ISO format (YYYY-MM-DD)",
    )
    end = serializers.DateField(
        help_text="End date in ISO format (YYYY-MM-DD)",
    )


class LockDaysSerializer(RecomputeRangeSerializer):
    """Serializer for locking/unlocking attendance days."""

    locked = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Set to true to lock days or false to unlock",
    )
