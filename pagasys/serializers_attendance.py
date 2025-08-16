from rest_framework import serializers

from .serializers import ScopedSerializerMixin
from .models_attendance import (
    Device,
    AttEvent,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    AttPair,
    AttDay,
    LeaveType,
    LeaveRequest,
    LeaveDay,
)


class DeviceSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = "__all__"
        extra_kwargs = {
            "hmac_secret": {"write_only": True},
        }


class AttEventSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AttEvent
        fields = "__all__"
        read_only_fields = [f.name for f in AttEvent._meta.fields]


class WorkCalendarSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = WorkCalendar
        fields = "__all__"


class HolidaySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = "__all__"


class ShiftTemplateSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ShiftTemplate
        fields = "__all__"


class ShiftRuleSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ShiftRule
        fields = "__all__"


class RosterEntrySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RosterEntry
        fields = "__all__"


class AttPairSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AttPair
        fields = "__all__"


class AttDaySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AttDay
        fields = "__all__"


class LeaveTypeSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = "__all__"


class LeaveRequestSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = "__all__"


class LeaveDaySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = LeaveDay
        fields = "__all__"


class AttEventIngestSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    ts = serializers.DateTimeField()
    direction = serializers.ChoiceField(choices=[d[0] for d in AttEvent.DIRECTION_CHOICES])
    device_id = serializers.IntegerField()
    provider = serializers.CharField()
    confidence = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    liveness = serializers.BooleanField(required=False, allow_null=True)
    payload_sig = serializers.CharField()
    meta = serializers.JSONField(required=False)


class AttEventIngestResponseSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    duplicates = serializers.IntegerField()
