import pytest
from decimal import Decimal
from datetime import datetime, date, time, timezone as dt_timezone
from django.utils import timezone
from zoneinfo import ZoneInfo

from capture.utils import (
    localize_to_company,
    get_face_threshold,
    compute_roster_date,
    within_device_scope,
    geofence_ok,
)
from capture.models import AttendanceDevice
from pagasys.models import (
    Company,
    Branch,
    Department,
    Project,
    Employee,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
)


@pytest.fixture
def company(db):
    return Company.objects.create(name="Co", timezone="Asia/Dubai")


@pytest.fixture
def branches(company):
    b1 = Branch.objects.create(company=company, name="B1")
    b2 = Branch.objects.create(company=company, name="B2")
    return b1, b2


@pytest.fixture
def departments(branches):
    b1, b2 = branches
    d1 = Department.objects.create(branch=b1, name="D1")
    d2 = Department.objects.create(branch=b2, name="D2")
    return d1, d2


@pytest.fixture
def projects(branches):
    b1, b2 = branches
    today = timezone.localdate()
    p1 = Project.objects.create(branch=b1, name="P1", start_date=today)
    p2 = Project.objects.create(branch=b2, name="P2", start_date=today)
    return p1, p2


@pytest.fixture
def employees(departments, projects):
    d1, d2 = departments
    p1, p2 = projects
    e1 = Employee.objects.create_user(
        username="e1",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        department=d1,
        visa_type="personal",
    )
    e2 = Employee.objects.create_user(
        username="e2",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        project=p1,
        visa_type="personal",
    )
    e3 = Employee.objects.create_user(
        username="e3",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        department=d2,
        visa_type="personal",
    )
    e4 = Employee.objects.create_user(
        username="e4",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        project=p2,
        visa_type="personal",
    )
    return e1, e2, e3, e4


def test_localize_to_company(company):
    utc_dt = datetime(2024, 5, 1, 12, 0, 0)
    aware = datetime(2024, 5, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
    tz = ZoneInfo("Asia/Dubai")
    assert localize_to_company(company, utc_dt) == datetime(2024, 5, 1, 16, 0, tzinfo=tz)
    assert localize_to_company(company, aware) == datetime(2024, 5, 1, 16, 0, tzinfo=tz)


def test_get_face_threshold_default_and_rule(company):
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=time(9, 0),
        end_time=time(17, 0),
        cross_midnight=False,
    )
    assert get_face_threshold(shift, date(2024, 5, 1)) == pytest.approx(0.90)
    ShiftRule.objects.create(
        shift=shift,
        kind=ShiftRule.Kind.FACE_MIN_CONF,
        value="0.75",
        active_from=date(2024, 1, 1),
    )
    assert get_face_threshold(shift, date(2024, 5, 1)) == pytest.approx(0.75)
    rule = shift.rules.first()
    rule.value = "-5"
    rule.save()
    assert get_face_threshold(shift, date(2024, 5, 1)) == 0.0
    rule.value = "1.5"
    rule.save()
    assert get_face_threshold(shift, date(2024, 5, 1)) == 1.0
    rule.value = "bad"
    rule.save()
    assert get_face_threshold(shift, date(2024, 5, 1)) == pytest.approx(0.90)


def test_compute_roster_date_cross_midnight(company, employees):
    e1 = employees[0]
    tz = ZoneInfo("Asia/Dubai")
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Night",
        start_time=time(22, 0),
        end_time=time(6, 0),
        cross_midnight=True,
    )
    RosterEntry.objects.create(employee=e1, date=date(2024, 7, 1), shift=shift)
    dt1 = datetime(2024, 7, 1, 23, 0, tzinfo=tz)
    dt2 = datetime(2024, 7, 2, 1, 0, tzinfo=tz)
    dt3 = datetime(2024, 7, 2, 7, 0, tzinfo=tz)
    assert compute_roster_date(e1, dt1)[0] == date(2024, 7, 1)
    assert compute_roster_date(e1, dt2)[0] == date(2024, 7, 1)
    assert compute_roster_date(e1, dt3)[0] is None


def test_within_device_scope(company, branches, departments, projects, employees):
    b1, b2 = branches
    d1, d2 = departments
    p1, p2 = projects
    e1, e2, e3, e4 = employees
    dev_branch = AttendanceDevice.objects.create(company=company, name="db", api_key="k1", branch=b1)
    dev_dept = AttendanceDevice.objects.create(company=company, name="dd", api_key="k2", department=d1)
    dev_proj = AttendanceDevice.objects.create(company=company, name="dp", api_key="k3", project=p1)
    dev_all = AttendanceDevice.objects.create(company=company, name="da", api_key="k4")

    assert within_device_scope(dev_branch, e1)
    assert within_device_scope(dev_branch, e2)
    assert not within_device_scope(dev_branch, e3)
    assert not within_device_scope(dev_branch, e4)

    assert within_device_scope(dev_dept, e1)
    assert not within_device_scope(dev_dept, e2)
    assert not within_device_scope(dev_dept, e3)
    assert not within_device_scope(dev_dept, e4)

    assert within_device_scope(dev_proj, e2)
    assert not within_device_scope(dev_proj, e1)
    assert not within_device_scope(dev_proj, e3)
    assert not within_device_scope(dev_proj, e4)

    assert within_device_scope(dev_all, e1)
    assert within_device_scope(dev_all, e3)


def test_geofence_ok(company):
    device = AttendanceDevice.objects.create(
        company=company,
        name="dev",
        api_key="k1",
        latitude=Decimal("25.000000"),
        longitude=Decimal("55.000000"),
        radius_m=100,
    )
    assert geofence_ok(device, Decimal("25.000500"), Decimal("55.000500"))
    assert not geofence_ok(device, Decimal("25.002000"), Decimal("55.002000"))
    assert geofence_ok(device, None, Decimal("55.000000"))
    device2 = AttendanceDevice.objects.create(company=company, name="dev2", api_key="k2")
    assert geofence_ok(device2, Decimal("0"), Decimal("0"))

