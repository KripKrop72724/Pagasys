from django.contrib.auth import get_user_model
from django.test import TestCase

from pagasys.admin import EmployeeAdminCreationForm, EmployeeAdminForm
from pagasys.models import (
    Branch,
    Company,
    Department,
    Project,
    TradeLicense,
    WorkCalendar,
)


class EmployeeAdminFormCompanyResolutionTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="Company A")
        self.branch_a = Branch.objects.create(company=self.company_a, name="Branch A")
        self.department_a = Department.objects.create(branch=self.branch_a, name="Dept A")
        self.project_a = Project.objects.create(
            branch=self.branch_a,
            name="Project A",
            start_date="2024-01-01",
        )
        self.calendar_a = WorkCalendar.objects.create(
            company=self.company_a, name="Calendar A"
        )

        self.company_b = Company.objects.create(name="Company B")
        self.branch_b = Branch.objects.create(company=self.company_b, name="Branch B")
        self.calendar_b = WorkCalendar.objects.create(
            company=self.company_b, name="Calendar B"
        )
        self.trade_license_b = TradeLicense.objects.create(
            company=self.company_b,
            license_no="TL-B",
            issued_date="2024-01-01",
            expiry_date="2030-01-01",
            max_visas=5,
        )
        self.trade_license_b.branches.set([self.branch_b])

        self.User = get_user_model()

    def test_employee_admin_form_prefers_assignment_company(self):
        employee = self.User.objects.create_user(
            username="project-employee",
            password="pass",
            project=self.project_a,
            trade_license=self.trade_license_b,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )

        form = EmployeeAdminForm(instance=employee)

        queryset = form.fields["work_calendar"].queryset
        self.assertEqual(list(queryset), [self.calendar_a])

    def test_employee_admin_creation_form_filters_by_department_company(self):
        form = EmployeeAdminCreationForm(
            data={
                "username": "new-user",
                "password1": "Sup3rSecr3t!",
                "password2": "Sup3rSecr3t!",
                "hire_date": "2024-01-04",
                "employment_type": "permanent",
                "visa_type": "company",
                "department": self.department_a.pk,
            }
        )

        queryset = form.fields["work_calendar"].queryset
        self.assertEqual(list(queryset), [self.calendar_a])

    def test_employee_admin_creation_form_ignores_trade_license_without_assignment(self):
        form = EmployeeAdminCreationForm(
            data={
                "username": "licensed-only",
                "password1": "Sup3rSecr3t!",
                "password2": "Sup3rSecr3t!",
                "hire_date": "2024-01-05",
                "employment_type": "permanent",
                "visa_type": "company",
                "trade_license": self.trade_license_b.pk,
            }
        )

        queryset = form.fields["work_calendar"].queryset
        self.assertEqual(list(queryset), [])
