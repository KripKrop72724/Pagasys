from datetime import date, datetime, time, timezone as dt_timezone
import os
import sys
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()

from pagasys.models import Company, Branch, Department, Employee
from pagasys.models_attendance import (
    ShiftTemplate,
    RosterEntry,
    AttEvent,
    AttDay,
)
from pagasys.tasks_attendance import compute_attday_task


def _make_basic_setup(**shift_kwargs):
    company = Company.objects.create(name="C1")
    branch = Branch.objects.create(company=company, name="B1")
    dept = Department.objects.create(branch=branch, name="D1")
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=0,
        **shift_kwargs,
    )
    emp = Employee.objects.create_user(
        username="emp",
        password="pass",
        department=dept,
        hire_date=date(2024, 1, 1),
        employment_type="permanent",
        visa_type="personal",
    )
    return company, emp, shift


def test_late_after_min_threshold(db):
    company, emp, shift = _make_basic_setup(
        grace_in_min=0,
        grace_out_min=0,
        late_after_min=5,
        early_leave_before_min=0,
    )
    day = date(2024, 1, 1)
    RosterEntry.objects.create(employee=emp, date=day, shift=shift)
    in_ts = datetime(2024, 1, 1, 9, 6, tzinfo=dt_timezone.utc)
    out_ts = datetime(2024, 1, 1, 17, 0, tzinfo=dt_timezone.utc)
    in_ev = AttEvent.objects.create(
        company=company,
        employee=emp,
        direction="IN",
        ts=in_ts,
        provider="test",
        payload_sig="sig",
    )
    out_ev = AttEvent.objects.create(
        company=company,
        employee=emp,
        direction="OUT",
        ts=out_ts,
        provider="test",
        payload_sig="sig",
    )
    compute_attday_task(company.id, emp.id, day)
    day_obj = AttDay.objects.get(employee=emp, date=day)
    assert day_obj.late_minutes == 1


def test_early_leave_before_min_threshold(db):
    company, emp, shift = _make_basic_setup(
        grace_in_min=0,
        grace_out_min=0,
        late_after_min=0,
        early_leave_before_min=5,
    )
    day = date(2024, 1, 1)
    RosterEntry.objects.create(employee=emp, date=day, shift=shift)
    in_ts = datetime(2024, 1, 1, 9, 0, tzinfo=dt_timezone.utc)
    out_ts = datetime(2024, 1, 1, 16, 54, tzinfo=dt_timezone.utc)
    in_ev = AttEvent.objects.create(
        company=company,
        employee=emp,
        direction="IN",
        ts=in_ts,
        provider="test",
        payload_sig="sig",
    )
    out_ev = AttEvent.objects.create(
        company=company,
        employee=emp,
        direction="OUT",
        ts=out_ts,
        provider="test",
        payload_sig="sig",
    )
    compute_attday_task(company.id, emp.id, day)
    day_obj = AttDay.objects.get(employee=emp, date=day)
    assert day_obj.early_leave_minutes == 1

