from rest_framework import serializers

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
