from rest_framework import serializers


class BulkErrorSerializer(serializers.Serializer):
    """Information about an object that failed validation."""

    data = serializers.DictField()
    errors = serializers.DictField()


class IdListSerializer(serializers.Serializer):
    """Simple serializer for a list of integer IDs."""

    ids = serializers.ListField(child=serializers.IntegerField())


def bulk_create_response_serializer(item_serializer):
    """Factory for bulk-create response serializers."""

    class BulkCreateResponse(serializers.Serializer):
        created = item_serializer(many=True)
        errors = BulkErrorSerializer(many=True)

    return BulkCreateResponse


def bulk_update_response_serializer(item_serializer):
    """Factory for bulk-update response serializers."""

    class BulkUpdateResponse(serializers.Serializer):
        updated = item_serializer(many=True)
        errors = BulkErrorSerializer(many=True)

    return BulkUpdateResponse


class BulkDeleteErrorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField())


def bulk_delete_response_serializer():
    """Serializer for bulk-delete results."""

    class BulkDeleteResponse(serializers.Serializer):
        deleted = serializers.IntegerField()
        errors = BulkDeleteErrorSerializer(many=True)

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
        instance = Designation(**attrs)
        instance.clean()
        return attrs


class TradeLicenseSerializer(serializers.ModelSerializer):
    """Serializer for TradeLicense"""

    class Meta:
        model = TradeLicense
        fields = '__all__'

    def validate(self, attrs):
        instance = TradeLicense(**attrs)
        instance.clean()
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

    class Meta:
        model = Employee
        fields = '__all__'

    def validate(self, attrs):
        instance = Employee(**attrs)
        instance.clean()
        return attrs
