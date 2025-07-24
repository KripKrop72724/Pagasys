from functools import lru_cache
from rest_framework import serializers


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
)


class CompanySerializer(serializers.ModelSerializer):
    """Serializer for Company"""

    class Meta:
        model = Company
        fields = '__all__'


class BranchSerializer(serializers.ModelSerializer):
    """Serializer for Branch"""

    class Meta:
        model = Branch
        fields = '__all__'


class DesignationSerializer(serializers.ModelSerializer):
    """Serializer for Designation"""

    class Meta:
        model = Designation
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = Designation(**attrs)
        instance.clean()
        return attrs


class TradeLicenseSerializer(serializers.ModelSerializer):
    """Serializer for :class:`~pagasys.models.TradeLicense`.

    The ``branches`` many-to-many relation is kept in ``fields`` via
    ``"__all__"`` so that DRF's ``save()`` automatically calls
    ``save_m2m()`` during bulk operations.
    """

    class Meta:
        model = TradeLicense
        fields = '__all__'

    def validate(self, attrs):
        """Run model validation and hook for branch rules."""

        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in TradeLicense._meta.fields}
            data.update({k: v for k, v in attrs.items() if k != 'branches'})
        else:
            data = {k: v for k, v in attrs.items() if k != 'branches'}
        instance = TradeLicense(**data)
        instance.clean()
        # Add custom branch logic here if needed.
        return attrs


class DepartmentSerializer(serializers.ModelSerializer):
    """Serializer for Department"""

    class Meta:
        model = Department
        fields = '__all__'


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for Project"""

    class Meta:
        model = Project
        fields = '__all__'


class EmployeeSerializer(serializers.ModelSerializer):
    """Serializer for Employee"""

    username = serializers.CharField(help_text="Login name")
    password = serializers.CharField(write_only=True, help_text="Password")
    first_name = serializers.CharField(required=False, allow_blank=True, help_text="Given name")
    last_name = serializers.CharField(required=False, allow_blank=True, help_text="Family name")
    email = serializers.EmailField(required=False, allow_blank=True, help_text="Email address")

    class Meta:
        model = Employee
        fields = [
            'id',
            'username',
            'password',
            'first_name',
            'last_name',
            'email',
            'trade_license',
            'department',
            'project',
            'designation',
            'hire_date',
            'employment_type',
        ]
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            data = {f.name: getattr(self.instance, f.name) for f in Employee._meta.fields}
            data.update(attrs)
            instance = Employee(**data)
        else:
            instance = Employee(**attrs)
        instance.clean()
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = Employee.objects.create_user(password=password, **validated_data)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user
