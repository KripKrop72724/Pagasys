from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from pagasys.models import (
    Branch,
    Company,
    Department,
    Designation,
    Employee,
    Project,
    TradeLicense,
)


class ModelFactoryMixin:
    """Helper mixin providing factory methods for test data."""

    def create_company(self, name="Comp"):
        return Company.objects.create(name=name)

    def create_branch(self, company=None, name="Branch"):
        return Branch.objects.create(company=company or self.company, name=name)

    def create_designation(self, company=None, name="Des"):
        return Designation.objects.create(
            company=company or self.company, name=name
        )

    def create_license(
        self,
        branch=None,
        license_no="LIC",
        issued="2024-01-01",
        expiry="2025-01-01",
        max_visas=1,
    ):
        return TradeLicense.objects.create(
            branch=branch or self.branch,
            license_no=license_no,
            issued_date=issued,
            expiry_date=expiry,
            max_visas=max_visas,
        )

    def create_department(self, branch=None, name="Dept"):
        return Department.objects.create(branch=branch or self.branch, name=name)

    def create_project(self, branch=None, name="Proj"):
        return Project.objects.create(
            branch=branch or self.branch,
            name=name,
            start_date="2024-01-01",
        )


class ModelValidationTests(ModelFactoryMixin, TestCase):
    """Comprehensive validation tests for core models."""

    def setUp(self):
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.project = self.create_project(self.branch)
        self.designation = self.create_designation(self.company, name="Engineer")
        self.license = self.create_license(self.branch, license_no="LIC1", max_visas=1)

    def test_trade_license_date_validation(self):
        lic = TradeLicense(
            branch=self.branch,
            license_no="LICX",
            issued_date="2025-01-01",
            expiry_date="2024-01-01",
            max_visas=1,
        )
        with self.assertRaises(ValidationError):
            lic.full_clean()

    def test_employee_visa_quota_enforced(self):
        Employee.objects.create(
            trade_license=self.license,
            department=self.department,
            first_name="A",
            last_name="B",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        emp = Employee(
            trade_license=self.license,
            department=self.department,
            first_name="C",
            last_name="D",
            hire_date="2024-01-03",
            employment_type="permanent",
        )
        with self.assertRaisesMessage(ValidationError, "Visa quota reached"):
            emp.full_clean()

    def test_department_project_exclusive(self):
        emp = Employee(
            trade_license=self.license,
            department=self.department,
            project=self.project,
            first_name="A",
            last_name="B",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        with self.assertRaises(ValidationError):
            emp.full_clean()

        emp2 = Employee(
            trade_license=self.license,
            first_name="C",
            last_name="D",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        with self.assertRaises(ValidationError):
            emp2.full_clean()

    def test_designation_company_mismatch(self):
        other_company = self.create_company("Other")
        wrong_des = self.create_designation(other_company, "OtherDes")
        emp = Employee(
            trade_license=self.license,
            department=self.department,
            designation=wrong_des,
            first_name="A",
            last_name="B",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        with self.assertRaisesMessage(ValidationError, "Designation must match company"):
            emp.full_clean()

    def test_unique_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_license(self.branch, license_no="LIC1")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_designation(self.company, name="Engineer")

    def test_db_check_constraints(self):
        # bypass model.clean by saving directly
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Employee.objects.create(
                    trade_license=self.license,
                    department=self.department,
                    project=self.project,
                    first_name="X",
                    last_name="Y",
                    hire_date="2024-01-02",
                    employment_type="permanent",
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Employee.objects.bulk_create(
                    [
                        Employee(
                            trade_license=self.license,
                            first_name="Q",
                            last_name="W",
                            hire_date="2024-01-02",
                            employment_type="permanent",
                        )
                    ]
                )

