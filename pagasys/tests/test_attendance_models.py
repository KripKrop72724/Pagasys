import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from pagasys.models import Branch, Company, Department, Employee
from pagasys.models_attendance import (
    AttDay,
    AttEvent,
    AttPair,
    Device,
    LeaveDay,
    LeaveRequest,
    LeaveType,
    ShiftRule,
    RosterEntry,
    ShiftTemplate,
    WorkCalendar,
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
        payload_sig="sig",
    )
    with pytest.raises(ValidationError):
        AttEvent.objects.create(
            company=emp.branch.company,
            employee=emp,
            device=device,
            direction="OUT",
            ts=ts,
            provider="p",
            payload_sig="sig",
        )
    # Duplicate UNK events are allowed
    AttEvent.objects.create(
        company=emp.branch.company,
        employee=emp,
        device=device,
        direction="UNK",
        ts=ts,
        provider="p",
        payload_sig="sig",
    )
    AttEvent.objects.create(
        company=emp.branch.company,
        employee=emp,
        device=device,
        direction="UNK",
        ts=ts,
        provider="p",
        payload_sig="sig",
    )
    assert AttEvent.objects.filter(direction="UNK").count() == 2
    evt = AttEvent.objects.filter(direction="IN").first()
    evt.provider = "x"
    with pytest.raises(Exception):
        evt.save()


@pytest.mark.django_db
def test_att_event_company_consistency_and_direction(basic_employee):
    emp = basic_employee
    company = emp.branch.company
    other_company = Company.objects.create(name="Other")
    other_branch = Branch.objects.create(company=other_company, name="O-B")
    other_dept = Department.objects.create(branch=other_branch, name="O-IT")
    other_emp = Employee.objects.create(
        username="bob",
        first_name="Bob",
        last_name="Employee",
        department=other_dept,
        hire_date=dt.date(2024, 1, 1),
        employment_type="permanent",
        visa_type="personal",
        password="!",
    )
    device_other = Device.objects.create(
        company=other_company, name="TermO", device_type="kiosk", hmac_secret="s"
    )
    with pytest.raises(ValidationError):
        AttEvent.objects.create(
            company=company,
            employee=emp,
            device=device_other,
            direction="IN",
            ts=timezone.now(),
            provider="p",
            payload_sig="sig",
        )
    device = Device.objects.create(
        company=company, name="Term1", device_type="kiosk", hmac_secret="s"
    )
    with pytest.raises(ValidationError):
        AttEvent.objects.create(
            company=company,
            employee=other_emp,
            device=device,
            direction="IN",
            ts=timezone.now(),
            provider="p",
            payload_sig="sig",
        )
    with pytest.raises(ValidationError):
        AttEvent.objects.create(
            company=company,
            employee=emp,
            device=device,
            direction="BAD",
            ts=timezone.now(),
            provider="p",
            payload_sig="sig",
        )


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
        RosterEntry.objects.create(employee=emp, date=dt.date(2024, 5, 1), shift=shift)


@pytest.mark.django_db
def test_leave_request_date_range(basic_employee):
    emp = basic_employee
    lt = LeaveType.objects.create(
        company=emp.branch.company, name="Annual", paid_pct=100
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
def test_attpair_derived_fields(basic_employee):
    emp = basic_employee
    company = emp.branch.company
    device = Device.objects.create(
        company=company, name="Term1", device_type="kiosk", hmac_secret="s"
    )
    ts_in = timezone.now()
    ts_out = ts_in + dt.timedelta(minutes=90)
    evt_in = AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=ts_in,
        provider="p",
        payload_sig="sig",
    )
    evt_out = AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=ts_out,
        provider="p",
        payload_sig="sig",
    )
    AttPair.objects.all().delete()
    pair = AttPair.objects.create(employee=emp, in_event=evt_in, out_event=evt_out)
    assert pair.in_ts == ts_in
    assert pair.out_ts == ts_out
    assert pair.duration_min == 90
    evt_in2 = AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=ts_out + dt.timedelta(minutes=30),
        provider="p",
        payload_sig="sig",
    )
    pair2 = AttPair.objects.get(in_event=evt_in2)
    assert pair2.out_ts is None
    assert pair2.duration_min == 0


@pytest.mark.django_db
def test_attday_shift_and_statuses(basic_employee):
    emp = basic_employee
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=dt.time(9, 0),
        end_time=dt.time(17, 0),
    )
    day = AttDay.objects.create(
        employee=emp,
        date=dt.date(2024, 5, 2),
        status="rest",
        shift=shift,
    )
    assert day.shift == shift
    assert day.status == "rest"
    bad = AttDay(
        employee=emp,
        date=dt.date(2024, 5, 3),
        status="bogus",
    )
    with pytest.raises(ValidationError):
        bad.full_clean()


@pytest.mark.django_db
def test_attday_unique(basic_employee):
    emp = basic_employee
    AttDay.objects.create(
        employee=emp,
        date=dt.date(2024, 5, 1),
        status="present",
    )
    with pytest.raises(IntegrityError):
        AttDay.objects.create(employee=emp, date=dt.date(2024, 5, 1), status="present")


@pytest.mark.django_db
def test_shift_rule_unique(basic_employee):
    company = basic_employee.branch.company
    shift = ShiftTemplate.objects.create(
        company=company, name="Day", start_time=dt.time(9), end_time=dt.time(17)
    )
    ShiftRule.objects.create(shift=shift, kind="ramadan_reduce_minutes", value="120")
    with pytest.raises(IntegrityError):
        ShiftRule.objects.create(shift=shift, kind="ramadan_reduce_minutes", value="60")


@pytest.mark.django_db
def test_workcalendar_default_unique(basic_employee):
    company = basic_employee.branch.company
    WorkCalendar.objects.create(company=company, name="A", is_default=True)
    with pytest.raises(IntegrityError):
        WorkCalendar.objects.create(company=company, name="B", is_default=True)


@pytest.mark.django_db
def test_leave_pay_percent_overrides(basic_employee):
    emp = basic_employee
    company = emp.branch.company
    lt = LeaveType.objects.create(company=company, name="Sick", paid_pct=100)
    lr = LeaveRequest.objects.create(
        employee=emp,
        leave_type=lt,
        start_date=dt.date(2024, 5, 10),
        end_date=dt.date(2024, 5, 10),
        paid_pct=50,
    )
    day1 = LeaveDay.objects.create(
        request=lr, date=dt.date(2024, 5, 10), minutes_covered=480
    )
    assert day1.get_paid_pct() == 50
    day2 = LeaveDay.objects.create(
        request=lr,
        date=dt.date(2024, 5, 11),
        minutes_covered=480,
        paid_pct=80,
    )
    assert day2.get_paid_pct() == 80
    lr2 = LeaveRequest.objects.create(
        employee=emp,
        leave_type=lt,
        start_date=dt.date(2024, 6, 1),
        end_date=dt.date(2024, 6, 1),
    )
    day3 = LeaveDay.objects.create(
        request=lr2, date=dt.date(2024, 6, 1), minutes_covered=480
    )
    assert day3.get_paid_pct() == 100
