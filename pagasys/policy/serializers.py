from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from pagasys.models import (
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
    Employee,
)
from pagasys.utils import scope_queryset

class CleanModelMixin:
    """Call model.full_clean() before saving to enforce model rules."""

    def validate(self, attrs):
        instance = self.instance or self.Meta.model(**attrs)
        if self.instance:
            for k, v in attrs.items():
                setattr(self.instance, k, v)
            instance = self.instance
        else:
            company = self.context.get("company")
            if company and hasattr(instance, "company_id") and not instance.company_id:
                instance.company = company
        instance.full_clean()
        return attrs

class WorkCalendarSerializer(CleanModelMixin, serializers.ModelSerializer):
    class Meta:
        model = WorkCalendar
        fields = ["id", "company", "name", "is_default"]
        read_only_fields = ["company"]
        ref_name = "PolicyWorkCalendar"

class HolidaySerializer(CleanModelMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        if req:
            self.fields["calendar"].queryset = scope_queryset(
                WorkCalendar.objects.all(), req.user
            )

    class Meta:
        model = Holiday
        fields = ["id", "calendar", "date", "name", "is_public"]
        ref_name = "PolicyHoliday"

class ShiftTemplateSerializer(CleanModelMixin, serializers.ModelSerializer):
    class Meta:
        model = ShiftTemplate
        fields = [
            "id", "company", "name", "start_time", "end_time", "cross_midnight",
            "break_minutes", "grace_in_min", "grace_out_min", "late_after_min",
            "early_leave_before_min", "rounding_min", "requires_face",
        ]
        read_only_fields = ["company"]
        ref_name = "PolicyShiftTemplate"

class ShiftRuleSerializer(CleanModelMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        if req:
            self.fields["shift"].queryset = scope_queryset(
                ShiftTemplate.objects.all(), req.user
            )

    kind = extend_schema_field(
        {"type": "string", "enum": [k for k, _ in ShiftRule.Kind.choices]}
    )(serializers.ChoiceField(choices=ShiftRule.Kind.choices, help_text="Rule kind"))

    params = extend_schema_field(
        {
            "type": "object",
            "properties": {
                "paid": {
                    "type": "boolean",
                    "description": "Treat break time as paid",
                },
                "enforcement": {
                    "type": "string",
                    "description": "Action when rule is violated",
                    "enum": ["warn", "flag", "auto_deduct", "block"],
                },
                "min_minutes": {
                    "type": "integer",
                    "description": "Minimum minutes for fixed_break_window",
                },
                "minutes": {
                    "type": "integer",
                    "description": "Break minutes for required_break_after_consecutive",
                },
            },
            "additionalProperties": True,
        }
    )(
        serializers.JSONField(
            required=False,
            help_text=(
                "Additional parameters; break rules require 'paid' boolean and "
                "'enforcement' (warn, flag, auto_deduct, block)"
            ),
        )
    )

    class Meta:
        model = ShiftRule
        fields = [
            "id", "shift", "kind", "value", "params", "active_from", "active_to", "weekdays",
        ]
        ref_name = "PolicyShiftRule"

    def validate(self, attrs):
        wd = attrs.get("weekdays")
        if wd:
            from pagasys.models import normalize_weekdays
            attrs["weekdays"] = normalize_weekdays(wd)
        return super().validate(attrs)


class RosterEntrySerializer(CleanModelMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        if req:
            self.fields["employee"].queryset = scope_queryset(
                Employee.objects.all(), req.user
            )
            self.fields["shift"].queryset = scope_queryset(
                ShiftTemplate.objects.all(), req.user
            )

    employee_name = serializers.CharField(source="employee.get_full_name", read_only=True)
    shift_name = serializers.CharField(source="shift.name", read_only=True)
    is_holiday = serializers.BooleanField(required=False)
    was_holiday = serializers.BooleanField(read_only=True)

    class Meta:
        model = RosterEntry
        fields = [
            "id", "employee", "date", "shift",
            "override_start", "override_end", "is_rest_day",
            "is_holiday", "was_holiday",
            "employee_name", "shift_name",
        ]
        ref_name = "PolicyRosterEntry"

class LeaveTypeSerializer(CleanModelMixin, serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "id", "company", "code", "name", "paid_pct", "requires_doc", "max_days_per_year", "params",
        ]
        read_only_fields = ["company"]
        ref_name = "PolicyLeaveType"


class RosterRangeSerializer(serializers.Serializer):
    """Serialize parameters for creating roster entries across a date range."""

    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), help_text="Employee ID to schedule"
    )
    shift = serializers.PrimaryKeyRelatedField(
        queryset=ShiftTemplate.objects.all(), help_text="Shift template to assign"
    )
    start_date = serializers.DateField(
        help_text="First day of the range"
    )
    days = serializers.IntegerField(
        required=False, min_value=1,
        help_text="Number of days to create starting from start_date"
    )
    until = serializers.DateField(
        required=False,
        help_text="Inclusive end date; alternative to days"
    )
    rest_weekdays = serializers.ListField(
        child=serializers.ChoiceField(
            choices=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        ),
        required=False,
        help_text="Weekday codes to mark as rest days, e.g. ['SAT','SUN']",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        if req:
            self.fields["employee"].queryset = scope_queryset(
                Employee.objects.all(), req.user
            )
            self.fields["shift"].queryset = scope_queryset(
                ShiftTemplate.objects.all(), req.user
            )

    def validate(self, attrs):
        days = attrs.get("days")
        until = attrs.get("until")
        if (days and until) or (not days and not until):
            raise serializers.ValidationError("Provide either 'days' or 'until'")
        if until and until < attrs["start_date"]:
            raise serializers.ValidationError({"until": "must be on or after start_date"})
        return attrs
