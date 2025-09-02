import io

from django.test import TestCase
from django.contrib.auth.models import Group
from openpyxl import Workbook

from pagasys.models import Company, Branch, Employee
from pagasys.excel_import import import_employee_workbook
from pagasys.policy.permissions import EMPLOYEE_ROLE


class EmployeeExcelUploadTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Co")
        self.branch = Branch.objects.create(company=self.company, name="SCH")

    def _make_workbook(self):
        wb = Workbook()
        headers = [
            "NAME",
            "DESIGNATION",
            "VISA STATUS",
            "GENDER",
            "WORKING BRANCH",
            "NATIONALITY",
            "DOB",
            "DATE OF JOINING",
            "TP NUMBER",
            "BIRTH PLACE",
        ]
        ws_own = wb.active
        ws_own.title = "OWN"
        ws_own.append(headers)
        ws_own.append([
            "MUHAMMAD YOUNIS",
            "TECHNICIAN",
            "OWN VISA",
            "MALE",
            "SCH",
            "PAKISTAN",
            "1988/08/08",
            "2022/08/26",
            "971565358302",
            "MULTAN",
        ])
        ws_visit = wb.create_sheet("VISIT")
        ws_visit.append(headers)
        ws_visit.append([
            "ALI AHMED",
            "HELPER",
            "VISIT VISA",
            "MALE",
            "SCH",
            "NEPAL",
            "1990/01/01",
            "2023/01/01",
            "12345",
            "DELHI",
        ])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def test_import_workbook_creates_employees(self):
        bio = self._make_workbook()
        result = import_employee_workbook(bio)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["errors"], [])
        emp1 = Employee.objects.get(username="muhammadyounis")
        self.assertEqual(emp1.visa_type, "personal")
        self.assertEqual(emp1.nationality, "PK")
        emp2 = Employee.objects.get(username="aliahmed")
        self.assertEqual(emp2.visa_type, "visit")
        self.assertEqual(emp2.nationality, "NP")
        self.assertEqual(emp2.special_notes, "VISIT VISA")
        group = Group.objects.get(name=EMPLOYEE_ROLE)
        self.assertTrue(emp1.groups.filter(name=EMPLOYEE_ROLE).exists())