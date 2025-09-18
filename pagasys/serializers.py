from functools import lru_cache
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from django.db import models
from django.contrib.auth.models import Group
from django_countries.serializer_fields import CountryField
from drf_spectacular.utils import extend_schema_field

from .utils import ensure_in_scope


class ScopedSerializerMixin:
    """Validate that related objects reside within the request user's scope."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None:
            for field, value in attrs.items():
                if isinstance(value, models.Model):
                    ensure_in_scope(value, user, field)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        if isinstance(item, models.Model):
                            ensure_in_scope(item, user, field)
        return attrs


class BulkErrorSerializer(serializers.Serializer):
    """Information about an object that failed validation."""

    data = serializers.DictField()
    errors = serializers.DictField()


class IdListSerializer(serializers.Serializer):
    """Simple serializer for a list of integer IDs."""

    ids = serializers.ListField(child=serializers.IntegerField())


@lru_cache()
def bulk_create_response_serializer(item_serializer):
    """Factory for bulk-create response serializers."""

    class BulkCreateResponse(serializers.Serializer):
        created = item_serializer(many=True)
        errors = BulkErrorSerializer(many=True)

        class Meta:
            ref_name = f"{item_serializer.__name__}BulkCreateResponse"

    return BulkCreateResponse


@lru_cache()
def bulk_update_response_serializer(item_serializer):
    """Factory for bulk-update response serializers."""

    class BulkUpdateResponse(serializers.Serializer):
        updated = item_serializer(many=True)
        errors = BulkErrorSerializer(many=True)

        class Meta:
            ref_name = f"{item_serializer.__name__}BulkUpdateResponse"

    return BulkUpdateResponse


class BulkDeleteErrorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField())


class BulkDeleteResponse(serializers.Serializer):
    deleted = serializers.IntegerField()
    errors = BulkDeleteErrorSerializer(many=True)

    class Meta:
        ref_name = "BulkDeleteResponse"


def bulk_delete_response_serializer():
    """Serializer for bulk-delete results."""

    return BulkDeleteResponse

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    HolidayAuditLog,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
    holiday_flags,
)


class CompanySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Company.

    Exposes contact fields such as address, logo, email, phone, website
    and bank account number in addition to the basic metadata.
    """

    class Meta:
        model = Company
        fields = '__all__'


class BranchSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Branch"""

    class Meta:
        model = Branch
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in Branch._meta.fields}
            data.update(attrs)
        else:
            data = attrs
        instance = Branch(**data)
        instance.clean()
        return attrs


class DesignationSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Designation"""

    class Meta:
        model = Designation
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = Designation(**attrs)
        instance.clean()
        return attrs


class TradeLicenseSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for :class:`~pagasys.models.TradeLicense`.

    Branch associations as well as issued and expiry dates are optional. The
    ``branches`` many-to-many relation is kept in ``fields`` via ``"__all__"``
    so that DRF's ``save()`` automatically calls ``save_m2m()`` during bulk
    operations.
    """

    class Meta:
        model = TradeLicense
        fields = '__all__'

    def validate(self, attrs):
        """Run model validation and hook for branch rules."""

        attrs = super().validate(attrs)

        company = attrs.get("company") or getattr(self.instance, "company", None)
        branches = attrs.get("branches")

        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in TradeLicense._meta.fields}
            data.update({k: v for k, v in attrs.items() if k != "branches"})
        else:
            data = {k: v for k, v in attrs.items() if k != "branches"}

        instance = TradeLicense(**data)
        instance.clean()

        if branches is not None and any(b.company_id != company.id for b in branches):
            raise serializers.ValidationError("Branch company mismatch")

        return attrs


class DepartmentSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Department"""

    class Meta:
        model = Department
        fields = '__all__'


class ProjectSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Project"""

    class Meta:
        model = Project
        fields = '__all__'


class WorkCalendarSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for WorkCalendar"""

    class Meta:
        model = WorkCalendar
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        base = {}
        if self.instance:
            for f in WorkCalendar._meta.fields:
                base[f.name] = getattr(self.instance, f.name)
        data = {**base, **attrs}
        instance = WorkCalendar(**data)
        instance.clean()
        return attrs


class HolidaySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Holiday.

    Editing or deleting a holiday triggers asynchronous recalculation of
    roster entries tied to the holiday's calendar. Manual ``is_holiday``
    overrides on those entries are preserved while ``was_holiday`` reflects
    the calendar's current state.
    """

    class Meta:
        model = Holiday
        fields = '__all__'


class HolidayAuditLogSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for HolidayAuditLog."""

    class Meta:
        model = HolidayAuditLog
        fields = '__all__'


class ShiftTemplateSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for ShiftTemplate"""

    class Meta:
        model = ShiftTemplate
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        base = {}
        if self.instance:
            for f in ShiftTemplate._meta.fields:
                base[f.name] = getattr(self.instance, f.name)
        data = {**base, **attrs}
        instance = ShiftTemplate(**data)
        instance.clean()
        return attrs


class ShiftRuleSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for ShiftRule"""
    kind = extend_schema_field(
        {"type": "string", "enum": [k for k, _ in ShiftRule.Kind.choices]}
    )(serializers.ChoiceField(choices=ShiftRule.Kind.choices, help_text="Rule kind"))

    class Meta:
        model = ShiftRule
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in ShiftRule._meta.fields}
            data.update(attrs)
        else:
            data = attrs
        instance = ShiftRule(**data)
        instance.clean()
        return attrs


class RosterEntrySerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for RosterEntry"""

    class Meta:
        model = RosterEntry
        fields = '__all__'
        read_only_fields = ("was_holiday",)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in RosterEntry._meta.fields}
            data.update(attrs)
        else:
            data = attrs
        instance = RosterEntry(**data)
        instance.clean()
        is_holiday_input = attrs.get("is_holiday") if "is_holiday" in attrs else (
            instance.is_holiday if self.instance else None
        )
        instance.is_holiday, instance.was_holiday = holiday_flags(
            instance.employee, instance.date, is_holiday_input
        )
        attrs["is_holiday"] = instance.is_holiday
        attrs["was_holiday"] = instance.was_holiday
        return attrs


class RosterOverviewEntrySerializer(serializers.Serializer):
    date = serializers.DateField()
    shift = serializers.IntegerField(allow_null=True)
    is_rest_day = serializers.BooleanField()
    is_holiday = serializers.BooleanField()
    was_holiday = serializers.BooleanField()


class RosterOverviewEmployeeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    entries = RosterOverviewEntrySerializer(many=True)


class RosterOverviewSerializer(serializers.Serializer):
    start = serializers.DateField()
    days = serializers.IntegerField()
    employees = RosterOverviewEmployeeSerializer(many=True)

    class Meta:
        ref_name = "RosterOverviewSerializer"


class LeaveTypeSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for LeaveType"""

    class Meta:
        model = LeaveType
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in LeaveType._meta.fields}
            data.update(attrs)
        else:
            data = attrs
        instance = LeaveType(**data)
        instance.clean()
        return attrs


class EmployeeSerializer(ScopedSerializerMixin, serializers.ModelSerializer):
    """Serializer for Employee"""

    username = serializers.CharField(help_text="Login name")
    branch = serializers.SerializerMethodField(
        help_text="Branch derived from the employee's department or project",
    )
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Password",
    )
    groups = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.all(),
        many=True,
        required=False,
        help_text="Group IDs for this employee",
    )
    is_superuser = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Give the user all permissions. Defaults to false when omitted",
    )
    first_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Given name"
    )
    middle_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Middle name"
    )
    last_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Family name"
    )
    email = serializers.EmailField(required=False, allow_blank=True, help_text="Email address")
    primary_contact = serializers.CharField(required=False, allow_blank=True, help_text="Primary contact number")
    secondary_contact = serializers.CharField(required=False, allow_blank=True, help_text="Secondary contact number")
    nationality = CountryField(
        required=False,
        allow_blank=True,
        help_text="Nationality as ISO 3166-1 alpha-2 country code (e.g. 'US' for United States). Uses django-countries.",
    )
    payment_status = serializers.ChoiceField(
        choices=Employee.PAYMENT_STATUS_CHOICES,
        required=False,
        help_text="Payment method: WPS or Cash. Automatically cash for personal or visit visas",
    )
    wps_account_number = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="WPS account number (required if payment status is WPS; not allowed for personal or visit visas)",
    )
    current_address = serializers.CharField(required=False, allow_blank=True, help_text="Current residential address")
    permanent_address = serializers.CharField(required=False, allow_blank=True, help_text="Permanent home country address")
    hometown = serializers.CharField(required=False, allow_blank=True, help_text="Hometown")
    gender = serializers.ChoiceField(
        choices=Employee._meta.get_field('gender').choices,
        required=False,
        allow_blank=True,
        help_text="Gender",
    )
    visa_file_number = serializers.CharField(required=False, allow_blank=True, help_text="Government visa file number")
    wps_id = serializers.CharField(
        required=False, allow_blank=True, help_text="WPS ID (not allowed for personal or visit visas)"
    )
    c3_id = serializers.CharField(
        required=False, allow_blank=True, help_text="C3 ID (not allowed for personal or visit visas)"
    )
    special_notes = serializers.CharField(
        required=False, allow_blank=True, help_text="Special notes about the employee"
    )
    profile_picture = serializers.ImageField(required=False, allow_null=True, help_text="Profile picture")

    class Meta:
        model = Employee
        fields = [
            'id',
            'username',
            'password',
            'is_superuser',
            'visa_type',
            'first_name',
            'middle_name',
            'last_name',
            'email',
            'trade_license',
            'department',
            'project',
            'work_calendar',
            'designation',
            'hire_date',
            'employment_type',
            'primary_contact',
            'secondary_contact',
            'nationality',
            'payment_status',
            'wps_account_number',
            'current_address',
            'permanent_address',
            'hometown',
            'profile_picture',
            'gender',
            'visa_file_number',
            'wps_id',
            'c3_id',
            'special_notes',
            'branch',
            'groups',
        ]
        extra_kwargs = {
            'password': {'write_only': True},
        }

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_branch(self, obj):
        branch = obj.branch
        return branch.pk if branch else None

    def validate_is_superuser(self, value):
        request = self.context.get('request')
        if request and value and not request.user.is_superuser:
            raise PermissionDenied('Only superusers can assign superuser status.')
        return value

    def validate(self, attrs):
        groups = attrs.pop('groups', None)
        is_super = attrs.get('is_superuser', getattr(self.instance, 'is_superuser', False))
        if is_super and groups:
            raise serializers.ValidationError({'groups': ['Superuser cannot belong to groups.']})

        visa = attrs.get('visa_type') or (
            self.instance.visa_type if self.instance else None
        )
        if visa in ('personal', 'visit'):
            attrs['payment_status'] = 'cash'
            attrs['wps_account_number'] = ''
            attrs['wps_id'] = ''
            attrs['c3_id'] = ''

        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in Employee._meta.fields}
            data.update(attrs)
            instance = Employee(**data)
        else:
            instance = Employee(**attrs)
        instance.clean()
        if groups is not None:
            attrs['groups'] = groups
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if password == "":
            password = None
        groups = validated_data.pop('groups', [])
        if validated_data.get("is_superuser"):
            if password is None:
                raise serializers.ValidationError(
                    {"password": ["This field is required for superusers."]}
                )
            user = Employee.objects.create_superuser(password=password, **validated_data)
        else:
            user = Employee.objects.create_user(password=password, **validated_data)
        if not user.is_superuser:
            user.groups.set(groups)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        groups = validated_data.pop('groups', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        if groups is not None and not user.is_superuser:
            user.groups.set(groups)
        return user

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_superuser:
            data.pop('groups', None)
        return data
