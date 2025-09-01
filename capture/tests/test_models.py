import pytest
import secrets
from decimal import Decimal
from datetime import timedelta

from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings

from pagasys.models import Company, Branch, Department, Project, Employee
from capture.models import AttendanceDevice, EnrollmentLink, PunchEvent, FaceEnrollment


@pytest.fixture
def company(db):
    return Company.objects.create(name="Co", timezone="Asia/Dubai")


@pytest.fixture
def branch(company):
    return Branch.objects.create(company=company, name="B1")


@pytest.fixture
def department(branch):
    return Department.objects.create(branch=branch, name="D1")


@pytest.fixture
def project(branch):
    return Project.objects.create(branch=branch, name="P1")


@pytest.fixture
def employee(department):
    return Employee.objects.create_user(
        username="emp",
        password="pw",
        hire_date=timezone.now().date(),
        employment_type="permanent",
        department=department,
        visa_type="personal",
    )


def test_attendance_device_scope_validation(company, branch, department):
    device = AttendanceDevice(company=company, name="dev", api_key="k1", branch=branch, department=department)
    with pytest.raises(ValidationError):
        device.full_clean()


def test_attendance_device_geofence_requires_all(company):
    device = AttendanceDevice(company=company, name="dev", api_key="k1", latitude=1.0)
    with pytest.raises(ValidationError):
        device.full_clean()


def test_enrollment_link_validity(employee):
    link = EnrollmentLink.objects.create(
        employee=employee,
        token="abc",
        expires_at=timezone.now() + timedelta(days=1),
        max_uses=1,
    )
    assert link.is_valid
    link.mark_used()
    link.refresh_from_db()
    assert link.uses == 1
    assert not link.is_valid


def test_punch_event_unique_external_id(company, branch, employee):
    device = AttendanceDevice.objects.create(company=company, name="dev", api_key="k1", branch=branch)
    ts = timezone.now()
    PunchEvent.objects.create(device=device, company=company, device_ts=ts, external_id="abc")
    with pytest.raises(IntegrityError):
        PunchEvent.objects.create(
            device=device,
            company=company,
            device_ts=ts + timedelta(seconds=1),
            external_id="abc",
        )


def test_punch_event_allows_empty_external_id(company, branch):
    device = AttendanceDevice.objects.create(company=company, name="dev", api_key="k1", branch=branch)
    ts = timezone.now()
    PunchEvent.objects.create(device=device, company=company, device_ts=ts, external_id="")
    # second event with empty external_id should not raise
    PunchEvent.objects.create(device=device, company=company, device_ts=ts + timedelta(seconds=1), external_id="")

def test_enrollment_link_invalid_cases(employee):
    expired = EnrollmentLink.objects.create(
        employee=employee,
        token="expired",
        expires_at=timezone.now() - timedelta(days=1),
    )
    assert not expired.is_valid
    used_up = EnrollmentLink.objects.create(
        employee=employee,
        expires_at=timezone.now() + timedelta(days=1),
        max_uses=1,
        uses=1,
    )
    assert not used_up.is_valid


def test_enrollment_link_token_generation_and_immutability(monkeypatch, employee):
    """Tokens are auto-generated, unique and cannot be changed."""
    tokens = iter(["dup", "dup", "unique"])
    monkeypatch.setattr(secrets, "token_urlsafe", lambda n: next(tokens))

    link1 = EnrollmentLink.objects.create(
        employee=employee,
        token="ignored",
        expires_at=timezone.now() + timedelta(hours=1),
        max_uses=1,
    )
    assert link1.token == "dup"

    original = link1.token
    link1.token = "changed"
    link1.save()
    link1.refresh_from_db()
    assert link1.token == original

    link2 = EnrollmentLink.objects.create(
        employee=employee,
        expires_at=timezone.now() + timedelta(hours=1),
        max_uses=1,
    )
    assert link2.token == "unique"
    assert link1.token != link2.token


def test_enrollment_link_url_property(employee):
    link = EnrollmentLink.objects.create(
        employee=employee,
        expires_at=timezone.now() + timedelta(hours=1),
        max_uses=1,
    )
    expected = f"{settings.PUBLIC_BASE_URL}/api/face/enroll/{link.token}"
    assert link.url == expected

def test_attendance_device_valid_geofence(company, branch):
    device = AttendanceDevice(
        company=company,
        name="dev",
        api_key="k1",
        branch=branch,
        latitude=Decimal("25.204800"),
        longitude=Decimal("55.270800"),
        radius_m=50,
    )
    device.full_clean()  # should not raise


def test_punchevent_geofence_defaults_and_validation(company, branch):
    device = AttendanceDevice.objects.create(company=company, name="dev", api_key="k1", branch=branch)
    ts = timezone.now()
    ev = PunchEvent.objects.create(device=device, company=company, device_ts=ts)
    assert ev.geofence_ok is None
    assert ev.geofence_rule_violation is False
    assert ev.roster_fallback is False
    ev2 = PunchEvent.objects.create(
        device=device,
        company=company,
        device_ts=ts + timedelta(seconds=1),
        geofence_ok=False,
    )
    assert ev2.geofence_ok is False
    ev3 = PunchEvent(device=device, company=company, device_ts=ts + timedelta(seconds=2), geofence_ok=None)
    ev3.full_clean()


@pytest.mark.parametrize("status", ["active", "revoked", "pending"])
def test_faceenrollment_status_valid(employee, status):
    fe = FaceEnrollment(employee=employee, collection_id="c", face_ids=["f1"], status=status)
    fe.full_clean()  # should not raise


def test_faceenrollment_status_invalid(employee):
    fe = FaceEnrollment(employee=employee, collection_id="c", face_ids=["f1"], status="invalid")
    with pytest.raises(ValidationError):
        fe.full_clean()
