from rest_framework import serializers

from django.db.models import Min

from drf_spectacular.utils import OpenApiExample, extend_schema_serializer

from pagasys.models import Employee
from .models import AttDay, AttPair, AttAdjustment, LeaveRequest, LeaveDay

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

    class Meta:
        model = AttAdjustment
        fields = "__all__"
        read_only_fields = ["created_at", "created_by_id"]


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
