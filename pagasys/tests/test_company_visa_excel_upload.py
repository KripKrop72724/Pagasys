import io

from django.test import TestCase
from django.contrib.auth.models import Group
from openpyxl import Workbook

from pagasys.models import Company, Branch, Employee
from pagasys.excel_import import import_company_visa_workbook
from pagasys.policy.permissions import EMPLOYEE_ROLE


class CompanyVisaExcelUploadTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
        self.branch_head = Branch.objects.create(company=self.company, name="HEAD")
        self.branch_fch = Branch.objects.create(company=self.company, name="FCH")

    def _make_workbook(self):
        wb = Workbook()
        ws_head = wb.active
        ws_head.title = "HEAD"
        ws_head.append(["NAME", "DOJ", "DESIGNATION", "TRADE LIC", "WPS NO", "NATIONALITY"])
        ws_head.append([
            "ABDUL KARIM KHAN",
            "2 Nov 2024",
            "DIGITAL MAREKETING",
            "EMP-HEAD",
            "10028050335108",
            "INDIAN",
        ])
        ws_fch = wb.create_sheet("FCH")
        ws_fch.append(["NAME", "DOJ", "TRADE LIC", "WPS NO", "NATIONALITY"])
        ws_fch.append([
            "ALI HAMZA",
            "27 Aug 2023",
            "EMP-FCH",
            "20008090046400",
            "PAKISTAN",
        ])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def test_import_workbook_creates_employees(self):
        bio = self._make_workbook()
        result = import_company_visa_workbook(bio)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["errors"], [])

        emp1 = Employee.objects.get(username="abdulkarimkhan")
        self.assertEqual(emp1.visa_type, "company")
        self.assertEqual(emp1.payment_status, "wps")
        self.assertEqual(emp1.wps_id, "10028050335108")
        self.assertEqual(emp1.trade_license.license_no, "EMP-HEAD")
        self.assertEqual(emp1.designation.name, "DIGITAL MAREKETING")
        self.assertEqual(emp1.nationality, "IN")

        emp2 = Employee.objects.get(username="alihamza")
        self.assertIsNone(emp2.designation)
        self.assertEqual(emp2.trade_license.license_no, "EMP-FCH")
        self.assertEqual(emp2.nationality, "PK")

        group = Group.objects.get(name=EMPLOYEE_ROLE)
        self.assertTrue(emp1.groups.filter(name=EMPLOYEE_ROLE).exists())
        self.assertTrue(emp2.groups.filter(name=EMPLOYEE_ROLE).exists())
