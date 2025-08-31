from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from PIL import Image
import tempfile


def _create_test_image():
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile("pic.png", buf.read(), content_type="image/png")

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
            expiry_date="2099-01-01",
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
            "visa_type": "company",
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
            visa_type="company",
        )
        ser = EmployeeSerializer(emp, data={"password": "new"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)
        emp = ser.save()
        self.assertTrue(emp.check_password("new"))

    def test_profile_picture_and_hometown_serialization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir):
                image = _create_test_image()
                data = {
                    "username": "uimg",
                    "password": "secret",
                    "trade_license": self.license.id,
                    "department": self.department.id,
                    "hire_date": "2024-01-02",
                    "employment_type": "permanent",
                    "visa_type": "company",
                    "hometown": "Springfield",
                    "profile_picture": image,
                }
                ser = EmployeeSerializer(data=data)
                self.assertTrue(ser.is_valid(), ser.errors)
                emp = ser.save()
                self.assertEqual(emp.hometown, "Springfield")
                self.assertTrue(emp.profile_picture.name.endswith("pic.png"))


class EmployeeSerializerGroupTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
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
        from django.contrib.auth.models import Group
        self.g1 = Group.objects.create(name="G1")

    def test_groups_serialized_for_regular_user(self):
        emp = Employee.objects.create_user(
            username="u3",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        emp.groups.add(self.g1)
        data = EmployeeSerializer(emp).data
        self.assertIn("groups", data)
        self.assertEqual(data["groups"], [self.g1.id])

    def test_groups_omitted_for_superuser(self):
        emp = Employee.objects.create_superuser(
            username="su",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        emp.groups.add(self.g1)
        data = EmployeeSerializer(emp).data
        self.assertNotIn("groups", data)


    def test_update_ignores_groups_when_superuser(self):
        emp = Employee.objects.create_superuser(
            username="su3",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        ser = EmployeeSerializer(emp, data={"groups": [self.g1.id]}, partial=True)
        self.assertFalse(ser.is_valid())
        self.assertIn("groups", ser.errors)

    def test_create_defaults_to_regular_user(self):
        data = {
            "username": "nosu",
            "password": "pass",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
            "visa_type": "company",
        }
        ser = EmployeeSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        emp = ser.save()
        self.assertFalse(emp.is_superuser)



    def test_create_superuser_with_groups_errors(self):
        data = {
            "username": "su4",
            "password": "pass",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
            "is_superuser": True,
            "groups": [self.g1.id],
        }
        ser = EmployeeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("groups", ser.errors)

    def test_update_to_superuser_with_groups_errors(self):
        emp = Employee.objects.create_user(
            username="reg",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        ser = EmployeeSerializer(emp, data={"is_superuser": True, "groups": [self.g1.id]}, partial=True)
        self.assertFalse(ser.is_valid())
        self.assertIn("groups", ser.errors)


class EmployeeSerializerVisaTypeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
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

    def test_company_visa_requires_license(self):
        data = {
            "username": "cvis",
            "password": "pass",
            "visa_type": "company",
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
        }
        ser = EmployeeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("trade_license", ser.errors)


class EmployeeSerializerPaymentTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
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

    def test_wps_requires_account(self):
        data = {
            "username": "wps1",
            "password": "pass",
            "visa_type": "company",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
            "payment_status": "wps",
        }
        ser = EmployeeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("wps_account_number", ser.errors)

    def test_cash_disallows_wps_account(self):
        data = {
            "username": "cash1",
            "password": "pass",
            "visa_type": "company",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
            "payment_status": "cash",
            "wps_account_number": "123",
        }
        ser = EmployeeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("wps_account_number", ser.errors)

    def test_visit_forces_cash(self):
        data = {
            "username": "visit1",
            "password": "pass",
            "visa_type": "visit",
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
        }
        ser = EmployeeSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        emp = ser.save()
        self.assertEqual(emp.payment_status, "cash")

    def test_personal_visa_forbids_license(self):
        data = {
            "username": "pvis",
            "password": "pass",
            "visa_type": "personal",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-01-02",
            "employment_type": "permanent",
        }
        ser = EmployeeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("trade_license", ser.errors)
