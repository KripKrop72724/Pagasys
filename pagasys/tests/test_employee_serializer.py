from django.test import TestCase

from pagasys.models import Company, Branch, Department, TradeLicense, Employee
from pagasys.serializers import EmployeeSerializer


class EmployeeSerializerPasswordTests(TestCase):
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

    def test_password_hashed_on_create(self):
        data = {
            "username": "u1",
            "password": "secret",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
        }
        ser = EmployeeSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        emp = ser.save()
        self.assertNotEqual(emp.password, "secret")
        self.assertTrue(emp.check_password("secret"))

    def test_password_hashed_on_update(self):
        emp = Employee.objects.create_user(
            username="u2",
            password="old",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
        )
        ser = EmployeeSerializer(emp, data={"password": "new"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)
        emp = ser.save()
        self.assertTrue(emp.check_password("new"))


