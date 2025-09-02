from __future__ import annotations

from datetime import datetime, date
from typing import IO, List, Dict, Tuple

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils.text import slugify
from openpyxl import load_workbook

from .models import Branch, Department, Designation, Employee
from .policy.permissions import EMPLOYEE_ROLE

# Mapping of provided nationality names to ISO country codes
NATIONALITY_MAP = {
    "BANGLADESH": "BD",
    "EGYPTION": "EG",
    "INDIAN": "IN",
    "NEPALI": "NP",
    "SRI LANKAN": "LK",
    "PAKISTAN": "PK",
    "NIGERIAN": "NG",
}


def _split_name(raw: str) -> Tuple[str, str, str]:
    parts = raw.split()
    first = parts[0].title()
    if len(parts) == 1:
        return first, "", ""
    if len(parts) == 2:
        return first, "", parts[1].title()
    # more than 2 parts
    middle = parts[1].title()
    last = parts[2].title()
    return first, middle, last


def import_employee_workbook(file: IO[bytes]) -> Dict[str, object]:
    """Import employees from an Excel workbook.

    Returns a dict with counts of created employees and any error messages.
    """

    wb = load_workbook(file, data_only=True)
    group, _ = Group.objects.get_or_create(name=EMPLOYEE_ROLE)
    results = {"created": 0, "errors": []}  # type: Dict[str, object]

    sheets = [("OWN", "personal"), ("VISIT", "visit")]
    for sheet_name, visa_type in sheets:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        headers = [cell.value for cell in ws[1]]
        header_index = {str(h).strip(): i for i, h in enumerate(headers)}
        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                name = str(row[header_index["NAME"]]).strip()
                first, middle, last = _split_name(name)

                designation_name = str(row[header_index["DESIGNATION"]]).strip()
                branch_name = str(row[header_index["WORKING BRANCH"]]).strip()
                branch = Branch.objects.filter(name__iexact=branch_name).first()
                if not branch:
                    raise ValueError(f"Unknown branch '{branch_name}'")
                department, _ = Department.objects.get_or_create(branch=branch, name="General")

                designation = None
                if designation_name:
                    designation, _ = Designation.objects.get_or_create(
                        company=branch.company, name=designation_name
                    )

                nationality_raw = str(row[header_index["NATIONALITY"]]).strip().upper()
                country_code = NATIONALITY_MAP.get(nationality_raw)
                if not country_code:
                    raise ValueError(f"Unsupported nationality '{nationality_raw}'")

                hire_raw = row[header_index["DATE OF JOINING"]]
                hire_date: date | None = None
                if hire_raw:
                    if isinstance(hire_raw, datetime):
                        hire_date = hire_raw.date()
                    elif isinstance(hire_raw, date):
                        hire_date = hire_raw
                    else:
                        hire_date = datetime.strptime(str(hire_raw), "%Y/%m/%d").date()

                tp_number = str(row[header_index["TP NUMBER"]]).strip()
                username_base = tp_number or slugify(f"{first}-{last}")
                username = username_base
                suffix = 1
                while Employee.objects.filter(username=username).exists():
                    username = f"{username_base}{suffix}"
                    suffix += 1

                special_notes = ""
                if sheet_name == "VISIT":
                    special_notes = str(row[header_index.get("VISA STATUS")]).strip()

                gender_raw = str(row[header_index["GENDER"]]).strip().lower()
                hometown = str(row[header_index["BIRTH PLACE"]] or "").strip()

                with transaction.atomic():
                    emp = Employee(
                        username=username,
                        first_name=first,
                        middle_name=middle,
                        last_name=last,
                        visa_type=visa_type,
                        department=department,
                        designation=designation,
                        hire_date=hire_date,
                        primary_contact=tp_number,
                        hometown=hometown,
                        gender=gender_raw,
                        nationality=country_code,
                        special_notes=special_notes,
                        is_active=True,
                        is_staff=False,
                        is_superuser=False,
                    )
                    emp.set_password("carhub123")
                    emp.save()
                    emp.groups.set([group])
                    results["created"] += 1
            except Exception as exc:
                results["errors"].append(f"{sheet_name} row {row_num}: {exc}")
    return results
