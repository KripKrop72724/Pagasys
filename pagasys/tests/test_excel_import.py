import io
from datetime import date

import pytest
from django.core.management import call_command
from openpyxl import Workbook

pytestmark = pytest.mark.django_db(transaction=True)

from pagasys.excel_import import import_main_format_workbook
from pagasys.models import Branch, Company, Department, Designation, Employee, TradeLicense
from pagasys.policy.permissions import EMPLOYEE_ROLE


def _build_workbook(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


@pytest.fixture(autouse=True)
def reset_db(transactional_db):
    call_command("flush", verbosity=0, interactive=False)


def test_main_format_import_creates_employee():
    company = Company.objects.create(name="OMG Group")
    branch = Branch.objects.create(company=company, name="CAR OMG")
    trade_license = TradeLicense.objects.create(
        company=company, license_no="EMP-OMG", max_visas=10
    )

    header = [
        "FIRST NAME",
        "MIDDLE NAME",
        "LAST NAME",
        "BRANCH",
        "TRADR LICENSE",
        "VISA TYPE",
        "PAYMENT STATUS",
        "WPS ACC NUMEBR",
        "DESIGNATION",
        "C3 NUMBER",
        "HIRE DATE",
        "GENDER",
    ]
    data = [
        "JAMAN",
        "MIAH",
        "KHAN",
        "CAR OMG",
        "EMP-OMG",
        "COMPANY",
        "WPS",
        "30122109131140",
        "SENIOR UPHOLSTERY",
        "COAA 05",
        "2022/06/10",
        "MALE",
    ]
    stream = _build_workbook([header, data])

    results = import_main_format_workbook(stream)

    assert results["created"] == 1
    assert results["errors"] == []

    employee = Employee.objects.get()
    assert employee.first_name == "Jaman"
    assert employee.middle_name == "Miah"
    assert employee.last_name == "Khan"
    assert employee.visa_type == "company"
    assert employee.payment_status == "wps"
    assert employee.wps_account_number == "30122109131140"
    assert employee.trade_license == trade_license
    assert employee.c3_id == "COAA 05"
    assert employee.hire_date == date(2022, 6, 10)
    assert employee.gender == "male"
    assert employee.employment_type == "permanent"
    assert employee.groups.filter(name=EMPLOYEE_ROLE).exists()

    department = Department.objects.get(branch=branch, name="General")
    assert employee.department == department
    assert trade_license.branches.filter(pk=branch.pk).exists()

    designation = Designation.objects.get(company=company)
    assert designation.name == "SENIOR UPHOLSTERY"
    assert employee.designation == designation


def test_main_format_import_reports_unknown_branch():
    company = Company.objects.create(name="OMG Group")
    TradeLicense.objects.create(company=company, license_no="EMP-OMG", max_visas=5)

    header = [
        "FIRST NAME",
        "MIDDLE NAME",
        "LAST NAME",
        "BRANCH",
        "TRADR LICENSE",
        "VISA TYPE",
        "PAYMENT STATUS",
        "WPS ACC NUMEBR",
        "DESIGNATION",
        "C3 NUMBER",
        "HIRE DATE",
        "GENDER",
    ]
    data = [
        "John",
        "",
        "Doe",
        "Unknown Branch",
        "EMP-OMG",
        "COMPANY",
        "WPS",
        "123456",
        "Mechanic",
        "C3-1",
        "2022/06/10",
        "MALE",
    ]
    stream = _build_workbook([header, data])

    results = import_main_format_workbook(stream)

    assert results["created"] == 0
    assert len(results["errors"]) == 1
    assert "unknown branch" in results["errors"][0].lower()
    assert Employee.objects.count() == 0
