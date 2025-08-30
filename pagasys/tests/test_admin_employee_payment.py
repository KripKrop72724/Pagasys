from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from pagasys.admin import EmployeeAdmin
from pagasys.models import Branch, Company, Department, TradeLicense, Employee


class EmployeeAdminPaymentTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
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

    def _get_request(self):
        req = self.factory.post("/")
        req.user = self.admin_user
        return req

    def test_wps_requires_account(self):
        admin = EmployeeAdmin(Employee, self.site)
        emp = Employee(
            username="e1",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
            payment_status="wps",
        )
        emp.set_password("pass")
        with self.assertRaises(ValidationError):
            admin.save_model(self._get_request(), emp, None, False)

    def test_visit_forces_cash(self):
        admin = EmployeeAdmin(Employee, self.site)
        emp = Employee(
            username="e2",
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="visit",
            payment_status="wps",
            wps_account_number="123",
        )
        emp.set_password("pass")
        with self.assertRaises(ValidationError):
            admin.save_model(self._get_request(), emp, None, False)
