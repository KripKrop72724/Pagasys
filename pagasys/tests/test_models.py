from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django import forms
from django.test import TestCase

from pagasys.models import Company, Branch, Designation, TradeLicense, Department, Project, Employee


class TradeLicenseForm(forms.ModelForm):
    class Meta:
        model = TradeLicense
        fields = "__all__"


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = "__all__"


class DesignationForm(forms.ModelForm):
    class Meta:
        model = Designation
        fields = "__all__"


class ModelValidationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="CompA")
        self.branch = Branch.objects.create(company=self.company, name="BranchA")
        self.department = Department.objects.create(branch=self.branch, name="HR")
        self.project = Project.objects.create(branch=self.branch, name="Proj", start_date="2024-01-01")
        self.designation = Designation.objects.create(company=self.company, name="Engineer")
        self.license = TradeLicense.objects.create(
            branch=self.branch,
            license_no="LIC1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=1,
        )

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

        form = TradeLicenseForm(data={
            "branch": self.branch.pk,
            "license_no": "LICFORM",
            "issued_date": "2025-01-01",
            "expiry_date": "2024-01-01",
            "max_visas": 1,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_employee_visa_quota(self):
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
        with self.assertRaises(ValidationError):
            emp.full_clean()

    def test_employee_department_project_exclusive(self):
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

    def test_employee_designation_company_mismatch(self):
        other_company = Company.objects.create(name="Other")
        wrong_designation = Designation.objects.create(company=other_company, name="OtherDes")
        emp = Employee(
            trade_license=self.license,
            department=self.department,
            designation=wrong_designation,
            first_name="A",
            last_name="B",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        with self.assertRaises(ValidationError):
            emp.full_clean()

    def test_unique_constraints(self):
        from django.db import transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TradeLicense.objects.create(
                    branch=self.branch,
                    license_no="LIC1",
                    issued_date="2024-02-01",
                    expiry_date="2025-02-01",
                    max_visas=1,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Designation.objects.create(company=self.company, name="Engineer")

    def test_form_validation_and_save(self):
        form = EmployeeForm(data={
            "trade_license": self.license.pk,
            "department": self.department.pk,
            "first_name": "Foo",
            "last_name": "Bar",
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
        })
        self.assertTrue(form.is_valid())
        form.save()
        # adding another should fail due to visa quota
        form2 = EmployeeForm(data={
            "trade_license": self.license.pk,
            "department": self.department.pk,
            "first_name": "Foo2",
            "last_name": "Bar2",
            "hire_date": "2024-01-03",
            "employment_type": "permanent",
        })
        self.assertFalse(form2.is_valid())
        self.assertIn("__all__", form2.errors)
