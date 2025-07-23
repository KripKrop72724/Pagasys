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

