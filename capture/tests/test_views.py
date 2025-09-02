import base64
from datetime import datetime, date, time, timezone as dt_timezone, timedelta
from django.utils import timezone
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from botocore.exceptions import ClientError

from capture.models import AttendanceDevice, FaceEnrollment, PunchEvent, PunchException
from capture.aws import company_collection_id
from pagasys.models import (
    Company,
    Branch,
    Department,
    Project,
    Employee,
    ShiftTemplate,
    RosterEntry,
    ShiftRule,
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
def project(branch):
    return Project.objects.create(branch=branch, name="P1", start_date=date(2024, 7, 1))


@pytest.fixture
def employee_project(project):
    return Employee.objects.create_user(
        username="emp_proj",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        project=project,
        visa_type="personal",
    )


@pytest.fixture
def device_project(company, project):
    return AttendanceDevice.objects.create(
        company=company,
        name="devp",
        api_key="kproj",
        project=project,
    )


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


@pytest.fixture
def roster_project(employee_project, shift):
    return RosterEntry.objects.create(employee=employee_project, date=date(2024, 7, 1), shift=shift)


def test_cross_midnight_roster_mapping(client, company, device, employee, night_roster):
    ts = datetime(2024, 7, 1, 21, 0, tzinfo=dt_timezone.utc)  # 01:00 local on Jul 2
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    assert resp.json()["roster_date"] == "2024-07-01"


def test_previous_day_non_cross_roster_not_matched(client, company, device, employee, roster):
    ts = datetime(2024, 7, 2, 1, 0, tzinfo=dt_timezone.utc)  # 05:00 local on Jul 2
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    assert resp.json()["roster_date"] is None


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


def test_project_scope_allows_only_project_members(
    client, company, device_project, employee_project, employee, roster_project, roster
):
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp_ok = client.post(
        "/api/capture/punch",
        {"employee_id": employee_project.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device_project),
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["out_of_scope"] is False

    resp_bad = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device_project),
    )
    assert resp_bad.status_code == 200
    assert resp_bad.json()["out_of_scope"] is True


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
    assert data["geofence_rule_violation"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "geofence"


def test_geofence_missing_coordinates(client, company, device, employee, roster):
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
        },
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["geofence_ok"] is None
    assert data["geofence_rule_violation"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.geofence_ok is None
    assert not PunchException.objects.filter(event=ev).exists()


def test_geofence_device_without_fence(client, company, device, employee, roster):
    device.latitude = None
    device.longitude = None
    device.radius_m = None
    device.save()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.0,
            "lon": 55.0,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["geofence_ok"] is True
    assert not PunchException.objects.filter(event_id=data["event_id"]).exists()


def test_roster_fallback_flag_false_within_shift(client, company, device, employee, roster):
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["roster_fallback"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.roster_fallback is False


def test_roster_fallback_flag_true_outside_shift(client, company, device, employee, roster):
    ts = datetime(2024, 7, 1, 14, 0, tzinfo=dt_timezone.utc)  # 18:00 local
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["roster_fallback"] is True
    assert data["roster_date"] == "2024-07-01"
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.roster_fallback is True
    assert ev.roster_date == date(2024, 7, 1)


def test_roster_fallback_true_without_roster(client, company, device, employee):
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["roster_date"] is None
    assert data["roster_fallback"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.roster_date is None
    assert ev.roster_fallback is True


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


def test_external_id_is_device_scoped(client, company, device, employee, roster, branch):
    device2 = AttendanceDevice.objects.create(company=company, name="dev2", api_key="k2", branch=branch)
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    payload = {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat(), "external_id": "abc"}
    r1 = client.post("/api/capture/punch", payload, **auth_headers(device))
    r2 = client.post("/api/capture/punch", payload, **auth_headers(device2))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["event_id"] != r2.json()["event_id"]
    assert PunchEvent.objects.filter(external_id="abc").count() == 2


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
    assert data["face_mismatch"] is False


def test_face_match_multiple_results(client, company, device, employee, roster, monkeypatch):
    """Ensure the highest-similarity match is chosen when multiple results are returned."""

    def fake_put_capture_to_s3(company_id, device_id, bytes_):
        return ("k", "h")

    def fake_search(company_id, image_bytes, threshold):
        return {
            "FaceMatches": [
                {"Similarity": 90.0, "Face": {"ExternalImageId": str(employee.id)}},
                {"Similarity": 95.0, "Face": {"ExternalImageId": str(employee.id)}},
            ]
        }

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
    assert data["face_confidence"] == pytest.approx(0.95, rel=1e-3)
    assert data["face_mismatch"] is False


def test_face_low_confidence_rejected(client, company, device, employee, face_roster, monkeypatch):
    """Reject when similarity is below FACE_MIN_CONF rule."""

    ShiftRule.objects.create(
        shift=face_roster.shift,
        kind=ShiftRule.Kind.FACE_MIN_CONF,
        value="0.95",
    )
    FaceEnrollment.objects.create(
        employee=employee, collection_id="c1", face_ids=["f1"], status="active"
    )

    def fake_put_capture_to_s3(company_id, device_id, bytes_):
        return ("k", "h")

    def fake_search(company_id, image_bytes, threshold):
        # Simulate a match below the threshold -> no results
        assert threshold == 0.95
        return {"FaceMatches": []}

    monkeypatch.setattr("capture.views.put_capture_to_s3", fake_put_capture_to_s3)
    monkeypatch.setattr("capture.views.search_face_by_image", fake_search)

    img_b64 = base64.b64encode(b"img").decode()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "image_b64": img_b64,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["accepted"] is False
    assert data["notes"] == "face_required_no_match"
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "face_required_no_match"


def test_face_invalid_parameter_exception_treated_as_no_match(
    client, company, device, employee, face_roster, monkeypatch
):
    """Handle Rekognition errors when no faces are present."""

    FaceEnrollment.objects.create(
        employee=employee, collection_id="c1", face_ids=["f1"], status="active"
    )

    def fake_put_capture_to_s3(company_id, device_id, bytes_):
        return ("k", "h")

    def fake_search(company_id, image_bytes, threshold):
        error_response = {
            "Error": {
                "Code": "InvalidParameterException",
                "Message": "There are no faces in the image",
            }
        }
        raise ClientError(error_response, "SearchFacesByImage")

    monkeypatch.setattr("capture.views.put_capture_to_s3", fake_put_capture_to_s3)
    monkeypatch.setattr("capture.views.search_face_by_image", fake_search)

    img_b64 = base64.b64encode(b"img").decode()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "image_b64": img_b64,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["accepted"] is False
    assert data["notes"] == "face_required_no_match"
    assert data["face_mismatch"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "face_required_no_match"


def _mismatch_setup(monkeypatch, employee_other):
    def fake_put_capture_to_s3(company_id, device_id, bytes_):
        return ("k", "h")

    def fake_search(company_id, image_bytes, threshold):
        return {"FaceMatches": [{"Similarity": 99.0, "Face": {"ExternalImageId": str(employee_other.id)}}]}

    monkeypatch.setattr("capture.views.put_capture_to_s3", fake_put_capture_to_s3)
    monkeypatch.setattr("capture.views.search_face_by_image", fake_search)


def test_face_mismatch_rejected_when_required(
    client, company, device, employee, employee_other, face_roster, monkeypatch
):
    _mismatch_setup(monkeypatch, employee_other)
    FaceEnrollment.objects.create(employee=employee, collection_id="c1", face_ids=["f1"], status="active")
    img_b64 = base64.b64encode(b"img").decode()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "image_b64": img_b64,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["accepted"] is False
    assert data["face_mismatch"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "face_required_no_match"


def test_face_mismatch_accepted_when_not_required(
    client, company, device, employee, employee_other, roster, monkeypatch
):
    _mismatch_setup(monkeypatch, employee_other)
    img_b64 = base64.b64encode(b"img").decode()
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "image_b64": img_b64,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["face_mismatch"] is True
    assert data["notes"] == "face_mismatch"
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "face_mismatch"


def test_face_required_no_enrollment(client, company, device, employee, face_roster):
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
    assert ev.exception.kind == "no_enrollment"


@pytest.mark.parametrize("status", ["revoked", "pending"])
def test_face_required_inactive_enrollment(client, company, device, employee, face_roster, status):
    FaceEnrollment.objects.create(employee=employee, collection_id="c1", face_ids=["f1"], status=status)
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "no_enrollment"


def test_geofence_required_rule_enforced(client, company, device, employee, roster):
    device.latitude = Decimal("25.0")
    device.longitude = Decimal("55.0")
    device.radius_m = 100
    device.save()
    ShiftRule.objects.create(
        shift=roster.shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
        value="50",
    )
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.0,
            "lon": 55.0,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["accepted"] is False
    assert data["geofence_ok"] is None
    assert data["geofence_rule_violation"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.geofence_rule_violation is True
    assert ev.exception.kind == "geofence_rule"
    assert ev.exception.details["reason"] == "radius_exceeds_rule"


def test_geofence_required_missing_device_geofence(client, company, device, employee, roster):
    device.latitude = None
    device.longitude = None
    device.radius_m = None
    device.save()
    ShiftRule.objects.create(
        shift=roster.shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
        value="50",
    )
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.0,
            "lon": 55.0,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["geofence_ok"] is None
    assert data["geofence_rule_violation"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "geofence_rule"
    assert ev.exception.details["reason"] == "missing_device_geofence"


def test_geofence_required_zero_device_radius(client, company, device, employee, roster):
    device.latitude = Decimal("25.0")
    device.longitude = Decimal("55.0")
    device.radius_m = 0
    device.save()
    ShiftRule.objects.create(
        shift=roster.shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
        value="50",
    )
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.0,
            "lon": 55.0,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["geofence_ok"] is None
    assert data["geofence_rule_violation"] is True
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.details["reason"] == "missing_device_geofence"


def test_geofence_rule_within_limit(client, company, device, employee, roster):
    device.latitude = Decimal("25.0")
    device.longitude = Decimal("55.0")
    device.radius_m = 50
    device.save()
    ShiftRule.objects.create(
        shift=roster.shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
        value="50",
    )
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.0,
            "lon": 55.0,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["geofence_ok"] is True
    assert data["geofence_rule_violation"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert not PunchException.objects.filter(event=ev).exists()


def test_geofence_rule_coordinates_outside(client, company, device, employee, roster):
    device.latitude = Decimal("25.0")
    device.longitude = Decimal("55.0")
    device.radius_m = 50
    device.save()
    ShiftRule.objects.create(
        shift=roster.shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
        value="50",
    )
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
    assert data["geofence_rule_violation"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert ev.exception.kind == "geofence"


def test_geofence_rule_invalid_value_ignored(client, company, device, employee, roster):
    device.latitude = Decimal("25.0")
    device.longitude = Decimal("55.0")
    device.radius_m = 50
    device.save()
    ShiftRule.objects.create(
        shift=roster.shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
        value="notanint",
    )
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {
            "employee_id": employee.id,
            "action": "in",
            "timestamp": ts.isoformat(),
            "lat": 25.0,
            "lon": 55.0,
        },
        **auth_headers(device),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["geofence_ok"] is True
    assert data["geofence_rule_violation"] is False
    ev = PunchEvent.objects.get(id=data["event_id"])
    assert not PunchException.objects.filter(event=ev).exists()

def test_device_last_seen_updated(client, company, device, employee, roster):
    old = timezone.now() - timedelta(days=1)
    device.last_seen = old
    device.save(update_fields=["last_seen"])
    ts = datetime(2024, 7, 1, 9, 0, tzinfo=dt_timezone.utc)
    resp = client.post(
        "/api/capture/punch",
        {"employee_id": employee.id, "action": "in", "timestamp": ts.isoformat()},
        **auth_headers(device),
    )
    assert resp.status_code == 200
    device.refresh_from_db()
    assert device.last_seen is not None
    assert device.last_seen > old


@pytest.mark.django_db
def test_create_enrollment_link_ensures_collection(
    monkeypatch, client, company, employee
):
    called = {}

    def fake_ensure(cid):
        called["cid"] = cid

    monkeypatch.setattr("capture.views.ensure_collection", fake_ensure)
    monkeypatch.setattr(
        "capture.views.ActionRolePermission.has_permission", lambda *a, **k: True
    )
    monkeypatch.setattr("capture.views.IsCompanyMember.has_permission", lambda *a, **k: True)
    monkeypatch.setattr("capture.views.scope_queryset", lambda qs, user: qs)
    client.force_authenticate(user=employee)
    url = f"/api/companies/{company.id}/manage/employees/{employee.id}/face/enrollment-link/"
    resp = client.post(url, {"expires_in_hours": 1})
    assert resp.status_code == 200
    assert called["cid"] == company_collection_id(company.id)
