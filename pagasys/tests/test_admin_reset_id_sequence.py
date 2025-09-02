from django.test import TestCase
from django.urls import reverse

from pagasys.models import Company, Branch, Department, TradeLicense, Employee


class EmployeeAdminResetIdSequenceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch])
        self.admin_user = Employee.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.admin_user)

    def test_reset_id_sequence(self):
        emp = Employee.objects.create(
            username="emp1",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        emp_id = emp.id
        emp.delete()

        url = reverse("admin:pagasys_employee_reset_id_sequence")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        emp2 = Employee.objects.create(
            username="emp2",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-03",
            employment_type="permanent",
            visa_type="company",
        )
        self.assertEqual(emp2.id, emp_id)
