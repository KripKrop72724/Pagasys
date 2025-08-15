import datetime as dt

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from pagasys.models import Branch, Company, Department, Employee
from pagasys.models_attendance import (
    AttDay,
    AttEvent,
    Device,
    LeaveRequest,
    LeaveType,
    RosterEntry,
    ShiftTemplate,
)


@pytest.fixture
def basic_employee(db):
    company = Company.objects.create(name="Co")
    branch = Branch.objects.create(company=company, name="B")
    dept = Department.objects.create(branch=branch, name="IT")
    emp = Employee.objects.create(
        username="alice",
        first_name="Alice",
        last_name="Employee",
        department=dept,
        hire_date=dt.date(2024, 1, 1),
        employment_type="permanent",
        visa_type="personal",
        password="!",
    )
    return emp


@pytest.mark.django_db
def test_att_event_unique_and_immutable(basic_employee):
    emp = basic_employee
    device = Device.objects.create(
        company=emp.branch.company,
        name="Term1",
        device_type="kiosk",
        hmac_secret="secret",
    )
    ts = timezone.now()
    AttEvent.objects.create(
        company=emp.branch.company,
        employee=emp,
        device=device,
        direction="IN",
        ts=ts,
        provider="p",
        signed_payload="payload",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AttEvent.objects.create(
                company=emp.branch.company,
                employee=emp,
                device=device,
                direction="OUT",
                ts=ts,
                provider="p",
                signed_payload="payload",
            )
    # UNK direction should bypass unique constraint
    AttEvent.objects.create(
        company=emp.branch.company,
        employee=emp,
        device=device,
        direction="UNK",
        ts=ts,
        provider="p",
        signed_payload="payload",
    )
    evt = AttEvent.objects.filter(direction="IN").first()
    evt.provider = "x"
    with pytest.raises(Exception):
        evt.save()


@pytest.mark.django_db
def test_shift_template_validation(basic_employee):
    company = basic_employee.branch.company
    st = ShiftTemplate(
        company=company,
        name="Bad",
        start_time=dt.time(10, 0),
        end_time=dt.time(9, 0),
    )
    with pytest.raises(Exception):
        st.full_clean()
    st = ShiftTemplate(
        company=company,
        name="Night",
        start_time=dt.time(22, 0),
        end_time=dt.time(6, 0),
        cross_midnight=True,
    )
    st.full_clean()  # should not raise


@pytest.mark.django_db
def test_roster_entry_unique(basic_employee):
    emp = basic_employee
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=dt.time(9, 0),
        end_time=dt.time(17, 0),
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 5, 1), shift=shift)
    with pytest.raises(IntegrityError):
        RosterEntry.objects.create(
            employee=emp, date=dt.date(2024, 5, 1), shift=shift
        )


@pytest.mark.django_db
def test_leave_request_date_range(basic_employee):
    emp = basic_employee
    lt = LeaveType.objects.create(
        company=emp.branch.company, name="Annual", pay_percent=100
    )
    lr = LeaveRequest(
        employee=emp,
        leave_type=lt,
        start_date=dt.date(2024, 5, 10),
        end_date=dt.date(2024, 5, 9),
    )
    with pytest.raises(Exception):
        lr.full_clean()


@pytest.mark.django_db
def test_attday_unique(basic_employee):
    emp = basic_employee
    AttDay.objects.create(
        employee=emp,
        date=dt.date(2024, 5, 1),
        status="present",
    )
    with pytest.raises(IntegrityError):
        AttDay.objects.create(
            employee=emp, date=dt.date(2024, 5, 1), status="present"
        )
