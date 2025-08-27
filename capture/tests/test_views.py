import base64
from datetime import datetime, date, time, timezone as dt_timezone
from django.utils import timezone
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from capture.models import AttendanceDevice, FaceEnrollment, PunchEvent, PunchException
from pagasys.models import (
    Company,
    Branch,
    Department,
    Employee,
    ShiftTemplate,
    RosterEntry,
)


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def company(db):
    return Company.objects.create(name="Co", timezone="Asia/Dubai")


@pytest.fixture
def branch(company):
    return Branch.objects.create(company=company, name="B1")


@pytest.fixture
def branch2(company):
    return Branch.objects.create(company=company, name="B2")


@pytest.fixture
def department(branch):
    return Department.objects.create(branch=branch, name="D1")


@pytest.fixture
def department2(branch2):
    return Department.objects.create(branch=branch2, name="D2")


@pytest.fixture
def employee(department):
    return Employee.objects.create_user(
        username="emp",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        department=department,
        visa_type="personal",
    )


@pytest.fixture
def employee_other(department2):
    return Employee.objects.create_user(
        username="emp2",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        department=department2,
        visa_type="personal",
    )


@pytest.fixture
def device(company, branch):
    return AttendanceDevice.objects.create(company=company, name="dev", api_key="k1", branch=branch)


def auth_headers(device):
    return {"HTTP_X_DEVICE_KEY": device.api_key}


@pytest.fixture
def shift(company):
    return ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=time(9, 0),
        end_time=time(17, 0),
        cross_midnight=False,
        requires_face=False,
    )


@pytest.fixture
def night_shift(company):
    return ShiftTemplate.objects.create(
        company=company,
        name="Night",
        start_time=time(22, 0),
        end_time=time(6, 0),
        cross_midnight=True,
        requires_face=False,
    )


@pytest.fixture
def face_shift(company):
    return ShiftTemplate.objects.create(
        company=company,
        name="Face",
        start_time=time(9, 0),
        end_time=time(17, 0),
        cross_midnight=False,
        requires_face=True,
    )


@pytest.fixture
def roster(employee, shift):
    return RosterEntry.objects.create(employee=employee, date=date(2024, 7, 1), shift=shift)


@pytest.fixture
def night_roster(employee, night_shift):
    return RosterEntry.objects.create(employee=employee, date=date(2024, 7, 1), shift=night_shift)


@pytest.fixture
def face_roster(employee, face_shift):
    return RosterEntry.objects.create(employee=employee, date=date(2024, 7, 1), shift=face_shift)


def test_cross_midnight_roster_mapping(client, company, device, employee, night_roster):
    ts = datetime(2024, 7, 1, 21, 0, tzinfo=dt_timezone.utc)  # 01:00 local on Jul 2
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    assert resp.json()["roster_date"] == "2024-07-01"


def test_scope_violation_flagged(client, company, device, employee_other, roster):
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee_other.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["out_of_scope"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "outside_scope"


def test_geofence_violation(client, company, device, employee, roster):
    device.latitude = Decimal("25.0")
    device.longitude = Decimal("55.0")
    device.radius_m = 50
    device.save()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.002,
            "lon": 55.002,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["geofence_ok"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "geofence"


def test_requires_face_blocks_without_image(client, company, device, employee, face_roster):
    FaceEnrollment.objects.create(employee=employee, collection_id="c1", face_ids=["f1"], status="active")
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["accepted"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "face_required_no_match"


def test_idempotent_external_id(client, company, device, employee, roster):
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    payload = {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat(), "external_id": "abc"}
    r1 = client.post("/api/capture/punch", payload, **auth_headers(device))
    r2 = client.post("/api/capture/punch", payload, **auth_headers(device))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["event_id"] == r2.json()["event_id"]
    assert PunchEvent.objects.filter(device=device).count() == 1


def test_face_match_success(client, company, device, employee, roster, monkeypatch):
    def fake_put_capture_to_s3(company_id, device_id, bytes_):
        return ("k", "h")

    def fake_search(company_id, image_bytes, threshold):
        return {"FaceMatches": [{"Similarity": 94.7, "Face": {"ExternalImageId": str(employee.id)}}]}

    monkeypatch.setattr("capture.views.put_capture_to_s3", fake_put_capture_to_s3)
    monkeypatch.setattr("capture.views.search_face_by_image", fake_search)

    img_b64 = base64.b64encode(b"img").decode()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"action": "in", "timestamp": ts.isoformat(), "image_b64": img_b64},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched_employee"] == employee.id
    assert data["face_confidence"] == pytest.approx(0.947, rel=1e-3)
