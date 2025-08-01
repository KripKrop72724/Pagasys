from datetime import date
from django.test import TestCase
from unittest.mock import patch
from rest_framework import serializers

from pagasys.models import Company, Branch, Department, TradeLicense
from pagasys.serializers import (
    DesignationSerializer,
    TradeLicenseSerializer,
    EmployeeSerializer,
)


class ValidateSuperCallTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch])

    def test_designation_calls_parent_validate(self):
        data = {"company": self.company, "name": "Eng"}
        with patch.object(
            serializers.ModelSerializer,
            "validate",
            autospec=True,
            side_effect=lambda self, attrs: attrs,
        ) as parent:
            ser = DesignationSerializer()
            ser.validate(data)
            parent.assert_called()

    def test_tradelicense_calls_parent_validate(self):
        data = {
            "company": self.company,
            "license_no": "X1",
            "issued_date": date(2024, 1, 1),
            "expiry_date": date(2025, 1, 1),
            "max_visas": 1,
        }
        with patch.object(
            serializers.ModelSerializer,
            "validate",
            autospec=True,
            side_effect=lambda self, attrs: attrs,
        ) as parent:
            ser = TradeLicenseSerializer()
            ser.validate(data)
            parent.assert_called()

    def test_employee_calls_parent_validate(self):
        data = {
            "username": "emp",
            "password": "secret",
            "trade_license": self.license,
            "department": self.department,
            "hire_date": date(2024, 1, 2),
            "employment_type": "permanent",
        }
        with patch.object(
            serializers.ModelSerializer,
            "validate",
            autospec=True,
            side_effect=lambda self, attrs: attrs,
        ) as parent:
            ser = EmployeeSerializer()
            ser.validate(data)
            parent.assert_called()


class TradeLicenseSerializerFieldTests(TestCase):
    def test_branches_field_present(self):
        fields = TradeLicenseSerializer().get_fields()
        assert 'branches' in fields


class TradeLicenseSerializerBranchTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.other = Company.objects.create(name="O")
        self.other_branch = Branch.objects.create(company=self.other, name="OB")

    def _base_data(self):
        return {
            "company": self.company.id,
            "license_no": "L1",
            "issued_date": "2024-01-01",
            "expiry_date": "2025-01-01",
            "max_visas": 1,
        }

    def test_mismatched_branch_rejected(self):
        data = self._base_data()
        data["branches"] = [self.other_branch.id]
        ser = TradeLicenseSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("non_field_errors", ser.errors)

    def test_mixed_branches_rejected(self):
        data = self._base_data()
        data["branches"] = [self.branch.id, self.other_branch.id]
        ser = TradeLicenseSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("non_field_errors", ser.errors)

    def test_valid_branches_ok(self):
        data = self._base_data()
        data["branches"] = [self.branch.id]
        ser = TradeLicenseSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)

    def test_update_company_with_old_branch_fails(self):
        lic = TradeLicense.objects.create(
            company=self.company,
            license_no="LX",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=1,
        )
        lic.branches.set([self.branch])
        data = {"company": self.other.id}
        ser = TradeLicenseSerializer(lic, data=data, partial=True)
        self.assertFalse(ser.is_valid())
        self.assertIn("non_field_errors", ser.errors)
