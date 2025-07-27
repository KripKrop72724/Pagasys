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
        company=None,
        branches=None,
        license_no="LIC",
        issued="2024-01-01",
        expiry="2025-01-01",
        max_visas=1,
    ):
        lic = TradeLicense.objects.create(
            company=company or self.company,
            license_no=license_no,
            issued_date=issued,
            expiry_date=expiry,
            max_visas=max_visas,
        )
        lic.branches.set(branches or [self.branch])
        return lic

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
        self.license = self.create_license(branches=[self.branch], license_no="LIC1", max_visas=1)

    def test_trade_license_date_validation(self):
        lic = TradeLicense(
            company=self.company,
            license_no="LICX",
            issued_date="2025-01-01",
            expiry_date="2024-01-01",
            max_visas=1,
        )
        lic.save()
        lic.branches.set([self.branch])
        with self.assertRaises(ValidationError):
            lic.full_clean()

    def test_trade_license_branches_must_match_company(self):
        other_company = self.create_company("Other")
        other_branch = self.create_branch(other_company, "OB")
        lic = TradeLicense(
            company=self.company,
            license_no="LICY",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=1,
        )
        lic.save()
        lic.branches.set([other_branch])
        with self.assertRaisesMessage(ValidationError, "license company"):
            lic.full_clean()

    def test_trade_license_multiple_branch_mismatch(self):
        other_company = self.create_company("Other2")
        other_branch = self.create_branch(other_company, "OB2")
        b2 = self.create_branch(self.company, "B2")
        lic = TradeLicense(
            company=self.company,
            license_no="LICZ",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=1,
        )
        lic.save()
        lic.branches.set([self.branch, other_branch, b2])
        with self.assertRaises(ValidationError):
            lic.full_clean()

    def test_employee_visa_quota_enforced(self):
        Employee.objects.create(
            username="emp1",
            password="pass",
            trade_license=self.license,
            department=self.department,
            first_name="A",
            last_name="B",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        emp = Employee(
            username="emp2",
            password="pass",
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
            username="emp3",
            password="pass",
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
            username="emp4",
            password="pass",
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
            username="emp5",
            password="pass",
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

    def test_employee_branch_must_be_covered(self):
        other_company = self.create_company("OtherCo")
        other_branch = self.create_branch(other_company, name="OB")
        other_license = self.create_license(company=other_company, branches=[other_branch], license_no="O1")
        emp = Employee(
            username="emp6",
            password="pass",
            trade_license=other_license,
            department=self.department,
            first_name="E",
            last_name="F",
            hire_date="2024-02-01",
            employment_type="permanent",
        )
        with self.assertRaisesMessage(ValidationError, "License company must match branch company"):
            emp.full_clean()

    def test_employee_license_other_branch_same_company_ok(self):
        other_branch = self.create_branch(self.company, name="B2")
        lic = self.create_license(branches=[self.branch], license_no="LIC2")
        dept = self.create_department(other_branch, name="Dept2")
        emp = Employee(
            username="emp7",
            password="pass",
            trade_license=lic,
            department=dept,
            first_name="G",
            last_name="H",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        # should not raise
        emp.full_clean()

    def test_unique_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_license(branches=[self.branch], license_no="LIC1")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_designation(self.company, name="Engineer")

    def test_db_check_constraints(self):
        # bypass model.clean by saving directly
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Employee.objects.create(
                    username="emp8",
                    password="pass",
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
                            username="emp9",
                            password="pass",
                            trade_license=self.license,
                            first_name="Q",
                            last_name="W",
                            hire_date="2024-01-02",
                            employment_type="permanent",
                        )
                    ]
                )


class ModelStringTests(ModelFactoryMixin, TestCase):
    """Ensure __str__ methods include related model info."""

    def setUp(self):
        self.company = self.create_company("Comp")
        self.branch = self.create_branch(self.company, "B1")
        self.department = self.create_department(self.branch, "Dept1")
        self.project = self.create_project(self.branch, "Proj1")
        self.designation = self.create_designation(self.company, "Engineer")
        self.license = self.create_license(company=self.company, branches=[self.branch], license_no="LICA")

    def test_branch_str(self):
        self.assertEqual(str(self.branch), "B1 - Comp")

    def test_department_str(self):
        self.assertEqual(str(self.department), "Dept1 - B1 - Comp")

    def test_designation_str(self):
        self.assertEqual(str(self.designation), "Engineer - Comp")

    def test_project_str(self):
        self.assertEqual(str(self.project), "Proj1 - B1 - Comp")

    def test_tradelicense_str_single_branch(self):
        self.assertEqual(str(self.license), "LICA - Comp - B1")

    def test_tradelicense_str_multiple_branches(self):
        b2 = self.create_branch(self.company, "B2")
        lic = self.create_license(company=self.company, branches=[self.branch, b2], license_no="LICB")
        self.assertEqual(str(lic), "LICB - Comp - B1, B2")

    def test_employee_str_department(self):
        emp = Employee.objects.create(
            username="emp1",
            password="pass",
            trade_license=self.license,
            department=self.department,
            designation=self.designation,
            first_name="A",
            last_name="B",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        self.assertEqual(str(emp), "A B - Comp - B1 - Dept1 - LICA - Engineer")

    def test_employee_str_project_no_designation(self):
        b2 = self.create_branch(self.company, "B2")
        proj = self.create_project(b2, "Proj2")
        lic = self.create_license(company=self.company, branches=[b2], license_no="LICC")
        emp = Employee.objects.create(
            username="emp2",
            password="pass",
            trade_license=lic,
            project=proj,
            first_name="C",
            last_name="D",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        self.assertEqual(str(emp), "C D - Comp - B2 - Proj2 - LICC")

