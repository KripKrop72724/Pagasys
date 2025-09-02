from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from pagasys.models import (
    Branch,
    Company,
    Department,
    Designation,
    Employee,
    LeaveType,
    Project,
    RosterEntry,
    ShiftRule,
    ShiftTemplate,
    TradeLicense,
    WorkCalendar,
    effective_calendar_for,
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
        expiry="2099-01-01",
        max_visas=1,
    ):
        lic = TradeLicense.objects.create(
            company=company or self.company,
            license_no=license_no,
            issued_date=issued,
            expiry_date=expiry,
            max_visas=max_visas,
        )
        if branches is None:
            branches = [self.branch]
        lic.branches.set(branches)
        lic.refresh_from_db()
        return lic

    def create_department(self, branch=None, name="Dept"):
        return Department.objects.create(branch=branch or self.branch, name=name)

    def create_project(self, branch=None, name="Proj"):
        return Project.objects.create(
            branch=branch or self.branch,
            name=name,
            start_date="2024-01-01",
        )

    def create_shift_template(
        self,
        company=None,
        name="Shift",
        start="09:00",
        end="17:00",
        cross_midnight=False,
    ):
        start_time = (
            start if isinstance(start, time) else datetime.strptime(start, "%H:%M").time()
        )
        end_time = (
            end if isinstance(end, time) else datetime.strptime(end, "%H:%M").time()
        )
        return ShiftTemplate.objects.create(
            company=company or self.company,
            name=name,
            start_time=start_time,
            end_time=end_time,
            cross_midnight=cross_midnight,
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

    def test_company_invalid_timezone(self):
        c = Company(name="BadCo", timezone="Mars/Phobos")
        with self.assertRaisesMessage(ValidationError, "Invalid IANA time zone"):
            c.full_clean()

    def test_trade_license_date_validation(self):
        lic = TradeLicense(
            company=self.company,
            license_no="LICX",
            issued_date="2025-01-01",
            expiry_date="2024-01-01",
            max_visas=1,
        )
        with self.assertRaises(ValidationError):
            lic.full_clean()

    def test_trade_license_clean_handles_missing_dates(self):
        lic = TradeLicense(
            company=self.company,
            license_no="LICM",
            max_visas=1,
        )
        # Should not raise TypeError when dates are missing
        lic.clean()

    def test_trade_license_branches_must_match_company(self):
        other_company = self.create_company("Other")
        other_branch = self.create_branch(other_company, "OB")
        lic = TradeLicense(
            company=self.company,
            license_no="LICY",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        lic.save()
        with self.assertRaises(ValidationError):
            lic.branches.set([other_branch])

    def test_trade_license_multiple_branch_mismatch(self):
        other_company = self.create_company("Other2")
        other_branch = self.create_branch(other_company, "OB2")
        b2 = self.create_branch(self.company, "B2")
        lic = TradeLicense(
            company=self.company,
            license_no="LICZ",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        lic.save()
        with self.assertRaises(ValidationError):
            lic.branches.set([self.branch, other_branch, b2])

    def test_trade_license_add_branch_mismatch(self):
        other_company = self.create_company("Other3")
        other_branch = self.create_branch(other_company, "OB3")
        with self.assertRaises(ValidationError):
            self.license.branches.add(other_branch)

    def test_trade_license_db_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TradeLicense.objects.create(
                    company=self.company,
                    license_no="BADLIC1",
                    issued_date="2025-01-01",
                    expiry_date="2024-01-01",
                    max_visas=1,
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TradeLicense.objects.create(
                    company=self.company,
                    license_no="BADLIC2",
                    issued_date="2024-01-01",
                    expiry_date="2099-01-01",
                    max_visas=0,
                )

    def test_branch_name_unique_per_company(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Branch.objects.create(company=self.company, name=self.branch.name)
        other_company = self.create_company("OtherCo")
        Branch.objects.create(company=other_company, name=self.branch.name)

    def test_shift_rule_weekdays_normalized_on_save(self):
        shift = self.create_shift_template(self.company)
        rule = ShiftRule(
            shift=shift,
            kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
            value="10",
            weekdays="fri,mon",
        )
        rule.save()
        self.assertEqual(rule.weekdays, "MON,FRI")

    def test_shift_rule_save_invalid_weekday(self):
        shift = self.create_shift_template(self.company)
        rule = ShiftRule(
            shift=shift,
            kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
            value="10",
            weekdays="funday",
        )
        with self.assertRaises(ValidationError):
            rule.save()

    def test_effective_calendar_for(self):
        company_cal = WorkCalendar.objects.create(
            company=self.company, name="Default", is_default=True
        )
        branch_cal = WorkCalendar.objects.create(
            company=self.company, name="Branch", is_default=False
        )
        self.branch.work_calendar = branch_cal
        self.branch.save()
        emp_cal = WorkCalendar.objects.create(
            company=self.company, name="Emp", is_default=False
        )
        emp = Employee.objects.create(
            username="emp_cal",
            password="pass",
            trade_license=self.license,
            department=self.department,
            first_name="E",
            last_name="F",
            hire_date="2024-02-01",
            employment_type="permanent",
            work_calendar=emp_cal,
        )
        self.assertEqual(effective_calendar_for(emp), emp_cal)
        emp.work_calendar = None
        emp.save()
        self.assertEqual(effective_calendar_for(emp), branch_cal)
        self.branch.work_calendar = None
        self.branch.save()
        self.assertEqual(effective_calendar_for(emp), company_cal)

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

    def test_employee_expired_trade_license(self):
        expired = TradeLicense.objects.create(
            company=self.company,
            license_no="EX",
            issued_date="1999-01-01",
            expiry_date="2000-01-01",
            max_visas=1,
        )
        expired.branches.set([self.branch])
        emp = Employee(
            username="exp_emp",
            password="pass",
            trade_license=expired,
            department=self.department,
            first_name="X",
            last_name="Y",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        with self.assertRaisesMessage(
            ValidationError, "Cannot assign an expired trade license to an employee"
        ):
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

    def test_branch_scoped_license_rejects_other_branch(self):
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
        with self.assertRaises(ValidationError):
            emp.full_clean()

    def test_unscoped_license_allows_any_branch(self):
        other_branch = self.create_branch(self.company, name="B2")
        lic = self.create_license(branches=[], license_no="LIC3")
        dept = self.create_department(other_branch, name="Dept2")
        emp = Employee(
            username="emp8",
            password="pass",
            trade_license=lic,
            department=dept,
            first_name="I",
            last_name="J",
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        emp.full_clean()  # should not raise

    def test_unique_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_license(branches=[self.branch], license_no="LIC1")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_designation(self.company, name="Engineer")

    def test_department_name_unique_per_branch(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_department(self.branch, name="Dept")
        other_branch = self.create_branch(self.company, name="B2")
        # same name in different branch is allowed
        self.create_department(other_branch, name="Dept")

    def test_project_name_unique_per_branch(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_project(self.branch, name="Proj")
        other_branch = self.create_branch(self.company, name="B3")
        # same name in different branch is allowed
        self.create_project(other_branch, name="Proj")

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

    def test_leavetype_case_insensitive_unique(self):
        LeaveType.objects.create(
            company=self.company, code="AL", name="Annual"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LeaveType.objects.create(
                    company=self.company, code="al", name="Another"
                )

    def test_leavetype_same_code_different_company_ok(self):
        LeaveType.objects.create(
            company=self.company, code="AL", name="Annual"
        )
        other_company = self.create_company("Other")
        LeaveType.objects.create(
            company=other_company, code="al", name="Annual2"
        )

    def test_tradelicense_branch_company_alignment_signal(self):
        other_company = self.create_company("OtherCo")
        other_branch = self.create_branch(other_company, "OB")
        lic = self.create_license(branches=[self.branch], license_no="LICSIG")
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                lic.branches.add(other_branch)
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                lic.branches.set([self.branch, other_branch])
        same_branch = self.create_branch(self.company, "B2")
        lic.branches.add(same_branch)  # should not raise

    def test_project_end_before_start_invalid(self):
        proj = Project(
            branch=self.branch,
            name="Bad",
            start_date="2024-01-10",
            end_date="2024-01-09",
        )
        with self.assertRaisesMessage(
            ValidationError, "end_date must be on/after start_date"
        ):
            proj.full_clean()

    def test_project_db_date_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Project.objects.create(
                    branch=self.branch,
                    name="BadDB",
                    start_date="2024-01-10",
                    end_date="2024-01-09",
                )

    def test_rosterentry_override_near_shift(self):
        shift = self.create_shift_template(start="09:00", end="17:00")
        emp = Employee.objects.create(
            username="emp_roster",
            password="pass",
            trade_license=self.license,
            department=self.department,
            first_name="R",
            last_name="S",
            hire_date="2024-02-01",
            employment_type="permanent",
        )

        bad_start = RosterEntry(
            employee=emp,
            date="2024-02-02",
            shift=shift,
            override_start="00:00",
        )
        with self.assertRaises(ValidationError):
            bad_start.full_clean()

        bad_end = RosterEntry(
            employee=emp,
            date="2024-02-03",
            shift=shift,
            override_end="03:00",
        )
        with self.assertRaises(ValidationError):
            bad_end.full_clean()

        ok = RosterEntry(
            employee=emp,
            date="2024-02-04",
            shift=shift,
            override_start="08:00",
            override_end="18:00",
        )
        ok.full_clean()  # should not raise


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


class DeletionProtectionTests(ModelFactoryMixin, TestCase):
    """Ensure core models cannot be deleted while employees reference them."""

    def setUp(self):
        self.company = self.create_company("Comp")
        self.branch = self.create_branch(self.company, "B1")
        self.department = self.create_department(self.branch, "Dept1")
        self.project = self.create_project(self.branch, "Proj1")

    def create_employee(self, **kwargs):
        data = {
            "username": f"emp{Employee.objects.count()}",
            "first_name": "A",
            "last_name": "B",
            "visa_type": "personal",
            "hire_date": "2024-01-01",
            "employment_type": "permanent",
        }
        data.update(kwargs)
        return Employee.objects.create(**data)

    def test_department_deletion_protected(self):
        emp = self.create_employee(department=self.department)
        with self.assertRaises(ProtectedError):
            self.department.delete()
        self.assertTrue(Department.objects.filter(pk=self.department.pk).exists())
        self.assertTrue(Employee.objects.filter(pk=emp.pk, department=self.department).exists())

    def test_project_deletion_protected(self):
        emp = self.create_employee(project=self.project)
        with self.assertRaises(ProtectedError):
            self.project.delete()
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())
        self.assertTrue(Employee.objects.filter(pk=emp.pk, project=self.project).exists())

    def test_branch_deletion_protected_via_department(self):
        self.create_employee(department=self.department)
        with self.assertRaises(ProtectedError):
            self.branch.delete()
        self.assertTrue(Branch.objects.filter(pk=self.branch.pk).exists())

