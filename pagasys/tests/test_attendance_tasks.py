import datetime as dt

import pytest

from pagasys.models import Branch, Company, Department, Employee
from pagasys.models_attendance import (
    AttDay,
    AttPair,
    AttEvent,
    Device,
    LeaveDay,
    LeaveRequest,
    LeaveType,
    RosterEntry,
    ShiftRule,
    ShiftTemplate,
    WorkCalendar,
    Holiday,
)
from pagasys.tasks_attendance import pair_events_task, compute_attday_task


@pytest.fixture
def employee(db):
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


def _mk_device(emp):
    return Device.objects.create(
        company=emp.branch.company,
        name="Term1",
        device_type="kiosk",
        hmac_secret="s",
    )


@pytest.mark.django_db
def test_pairing_dup_and_missing(employee):
    emp = employee
    device = _mk_device(emp)
    company_id = emp.branch.company_id

    def ts(h):
        return dt.datetime(2024, 5, 1, h, 0, tzinfo=dt.timezone.utc)
    AttEvent.objects.create(
        company_id=company_id,
        employee=emp,
        device=device,
        direction="IN",
        ts=ts(9),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company_id=company_id,
        employee=emp,
        device=device,
        direction="IN",
        ts=ts(10),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company_id=company_id,
        employee=emp,
        device=device,
        direction="OUT",
        ts=ts(18),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company_id, emp.id, dt.date(2024, 5, 1))
    pairs = AttPair.objects.filter(employee=emp).order_by("in_ts")
    assert pairs.count() == 2
    assert pairs[0].out_event is None and pairs[0].quality == "missing_out"
    assert pairs[1].duration_min == 480 and pairs[1].source == "auto"


@pytest.mark.django_db
def test_cross_midnight_attday(employee):
    emp = employee
    device = _mk_device(emp)
    company_id = emp.branch.company_id
    shift = ShiftTemplate.objects.create(
        company=emp.branch.company,
        name="Night",
        start_time=dt.time(20, 0),
        end_time=dt.time(4, 0),
        cross_midnight=True,
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 5, 1), shift=shift)
    AttEvent.objects.create(
        company_id=company_id,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 5, 1, 20, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company_id=company_id,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 5, 2, 4, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company_id, emp.id, dt.date(2024, 5, 1))
    compute_attday_task(company_id, emp.id, dt.date(2024, 5, 1))
    day = AttDay.objects.get(employee=emp, date=dt.date(2024, 5, 1))
    assert day.work_minutes == 480


@pytest.mark.django_db
def test_night_ot_window(employee):
    emp = employee
    device = _mk_device(emp)
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Night",
        start_time=dt.time(20, 0),
        end_time=dt.time(4, 0),
        cross_midnight=True,
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 5, 1), shift=shift)
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 5, 1, 20, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 5, 2, 4, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company.id, emp.id, dt.date(2024, 5, 1))
    compute_attday_task(company.id, emp.id, dt.date(2024, 5, 1))
    day = AttDay.objects.get(employee=emp, date=dt.date(2024, 5, 1))
    assert day.ot150_minutes > 0


@pytest.mark.django_db
def test_ramadan_reduction(employee):
    emp = employee
    device = _mk_device(emp)
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=dt.time(9, 0),
        end_time=dt.time(17, 0),
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 3, 12), shift=shift)
    cal = WorkCalendar.objects.create(company=company, name="C", is_default=True)
    Holiday.objects.create(calendar=cal, date=dt.date(2024, 3, 12), name="Ramadan")
    ShiftRule.objects.create(shift=shift, kind="ramadan_reduce_minutes", value="120")
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 3, 12, 9, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 3, 12, 17, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company.id, emp.id, dt.date(2024, 3, 12))
    compute_attday_task(company.id, emp.id, dt.date(2024, 3, 12))
    day = AttDay.objects.get(employee=emp, date=dt.date(2024, 3, 12))
    assert day.ot125_minutes == 120


@pytest.mark.django_db
def test_ot_caps(employee):
    emp = employee
    device = _mk_device(emp)
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=dt.time(9, 0),
        end_time=dt.time(17, 0),
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 5, 1), shift=shift)
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 5, 1, 9, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 5, 1, 21, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company.id, emp.id, dt.date(2024, 5, 1))
    compute_attday_task(company.id, emp.id, dt.date(2024, 5, 1))
    day = AttDay.objects.get(employee=emp, date=dt.date(2024, 5, 1))
    assert day.ot125_minutes == 120




@pytest.mark.django_db
def test_partial_day_leave(employee):
    emp = employee
    device = _mk_device(emp)
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=dt.time(9, 0),
        end_time=dt.time(17, 0),
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 6, 1), shift=shift)
    lt = LeaveType.objects.create(company=company, name="Annual", pay_percent=100)
    req = LeaveRequest.objects.create(
        employee=emp,
        leave_type=lt,
        start_date=dt.date(2024, 6, 1),
        end_date=dt.date(2024, 6, 1),
        status="approved",
    )
    LeaveDay.objects.create(request=req, date=dt.date(2024, 6, 1), minutes=240)
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 6, 1, 9, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 6, 1, 17, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company.id, emp.id, dt.date(2024, 6, 1))
    compute_attday_task(company.id, emp.id, dt.date(2024, 6, 1))
    day = AttDay.objects.get(employee=emp, date=dt.date(2024, 6, 1))
    assert day.status == "present"
    assert day.ot125_minutes == 120


@pytest.mark.django_db
def test_locked_day_not_overwritten(employee):
    emp = employee
    device = _mk_device(emp)
    company = emp.branch.company
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=dt.time(9, 0),
        end_time=dt.time(17, 0),
    )
    RosterEntry.objects.create(employee=emp, date=dt.date(2024, 7, 1), shift=shift)
    AttDay.objects.create(
        employee=emp,
        date=dt.date(2024, 7, 1),
        status="present",
        shift=shift,
        work_minutes=0,
        locked=True,
    )
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 7, 1, 9, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 7, 1, 17, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    pair_events_task(company.id, emp.id, dt.date(2024, 7, 1))
    compute_attday_task(company.id, emp.id, dt.date(2024, 7, 1))
    day = AttDay.objects.get(employee=emp, date=dt.date(2024, 7, 1))
    assert day.work_minutes == 0


@pytest.mark.django_db
def test_manual_pairs_are_preserved(employee):
    from django.db.models.signals import post_save
    from pagasys.signals import enqueue_pairing

    post_save.disconnect(enqueue_pairing, sender=AttEvent)
    emp = employee
    device = _mk_device(emp)
    company = emp.branch.company
    in_ev = AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="IN",
        ts=dt.datetime(2024, 5, 1, 9, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    out_ev = AttEvent.objects.create(
        company=company,
        employee=emp,
        device=device,
        direction="OUT",
        ts=dt.datetime(2024, 5, 1, 17, 0, tzinfo=dt.timezone.utc),
        provider="p",
        payload_sig="s",
    )
    p = AttPair.objects.create(
        employee=emp,
        in_event=in_ev,
        out_event=out_ev,
        source="manual",
        quality="manual",
    )
    pair_events_task(company.id, emp.id, dt.date(2024, 5, 1))
    post_save.connect(enqueue_pairing, sender=AttEvent)
    assert AttPair.objects.filter(pk=p.pk).exists()
