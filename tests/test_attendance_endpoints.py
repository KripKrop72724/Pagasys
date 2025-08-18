from datetime import date, time, timedelta
import os
import sys
from pathlib import Path
import hmac
import hashlib
from django.utils import timezone
import django

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()

from rest_framework.test import APIClient
from pagasys.models import Company, Branch, Department, Employee
from pagasys.models_attendance import (
    ShiftTemplate,
    RosterEntry,
    AttDay,
    LeaveType,
    LeaveRequest,
    LeaveDay,
    Device,
)


def setup_data():
    company = Company.objects.create(name="C1")
    branch = Branch.objects.create(company=company, name="B1")
    dept = Department.objects.create(branch=branch, name="D1")
    shift = ShiftTemplate.objects.create(
        company=company,
        name="Day",
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=0,
    )
    admin = Employee.objects.create_superuser(
        username="admin",
        password="pass",
        department=dept,
        hire_date=date(2024, 1, 1),
        employment_type="permanent",
        visa_type="personal",
    )
    emp = Employee.objects.create_user(
        username="emp",
        password="pass",
        department=dept,
        hire_date=date(2024, 1, 1),
        employment_type="permanent",
        visa_type="personal",
    )
    lt = LeaveType.objects.create(company=company, name="Sick", pay_percent=50)
    return {
        "company": company,
        "branch": branch,
        "department": dept,
        "shift": shift,
        "admin": admin,
        "emp": emp,
        "leave_type": lt,
    }


def test_roster_bulk_endpoint_json(db):
    data = setup_data()
    client = APIClient()
    client.force_authenticate(user=data["admin"])
    url = "/api/attendance/roster/bulk/"
    payload = [
        {
            "employee_id": data["emp"].id,
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "shift_id": data["shift"].id,
        },
        {
            "employee_id": 9999,
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
            "shift_id": data["shift"].id,
        },
    ]
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 207
    assert resp.data["results"][0]["status"] == "ok"
    assert RosterEntry.objects.filter(employee=data["emp"]).count() == 2


def test_roster_bulk_endpoint_csv(db):
    data = setup_data()
    client = APIClient()
    client.force_authenticate(user=data["admin"])
    url = "/api/attendance/roster/bulk/"
    csv_body = (
        "employee_id,start_date,end_date,shift_id\n"
        f"{data['emp'].id},2024-01-03,2024-01-03,{data['shift'].id}\n"
    )
    resp = client.post(url, csv_body, content_type="text/csv")
    assert resp.status_code == 200
    assert RosterEntry.objects.filter(employee=data["emp"], date=date(2024, 1, 3)).exists()


def test_timesheet_report(db):
    data = setup_data()
    emp = data["emp"]
    shift = data["shift"]
    lt = data["leave_type"]
    # Roster entries
    RosterEntry.objects.create(employee=emp, date=date(2024, 1, 1), shift=shift)
    RosterEntry.objects.create(employee=emp, date=date(2024, 1, 2), shift=shift)
    # AttDay entries
    AttDay.objects.create(
        employee=emp,
        date=date(2024, 1, 1),
        status="present",
        shift=shift,
        work_minutes=300,
        late_minutes=10,
        early_leave_minutes=20,
        ot125_minutes=30,
        ot150_minutes=40,
    )
    AttDay.objects.create(
        employee=emp,
        date=date(2024, 1, 2),
        status="missing",
        shift=shift,
        notes={"missing_out": True},
    )
    # Leave on Jan 1 for 60 minutes at 50%
    lr = LeaveRequest.objects.create(
        employee=emp,
        leave_type=lt,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        status="approved",
    )
    LeaveDay.objects.create(request=lr, date=date(2024,1,1), minutes=60, pay_percent=50)

    client = APIClient()
    client.force_authenticate(user=data["admin"])
    url = f"/api/attendance/reports/timesheet/?company={data['company'].id}&month=2024-01"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    result = body["results"][0]
    assert result["scheduled_minutes"] == 900
    assert result["work_minutes"] == 300
    assert result["late_minutes"] == 10
    assert result["early_leave_minutes"] == 20
    assert result["ot125_minutes"] == 30
    assert result["ot150_minutes"] == 40
    assert result["leave_minutes"]["Sick"] == 30
    assert result["anomalies"] == 1

    # CSV export
    resp_csv = client.get(url + "&export=csv")
    from django.http import StreamingHttpResponse

    assert isinstance(resp_csv, StreamingHttpResponse)
    content = b"".join(resp_csv.streaming_content).decode()
    assert "employee_id" in content


def test_att_event_ingest_hmac_and_duplicates(db):
    data = setup_data()
    company = data["company"]
    emp = data["emp"]
    admin = data["admin"]
    device = Device.objects.create(
        company=company, name="Dev", device_type="kiosk", hmac_secret="sekrit"
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    ts = timezone.now().isoformat()
    item = {
        "employee_id": emp.id,
        "ts": ts,
        "direction": "IN",
        "device_id": device.id,
        "provider": "faceprov",
    }
    sig = hmac.new(
        key=device.hmac_secret.encode("utf-8"),
        msg=f"{emp.id}|{ts}|IN|{device.id}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    item["payload_sig"] = sig
    url = "/api/attendance/events/ingest/"
    resp = client.post(url, [item], format="json")
    assert resp.status_code == 201
    assert resp.json() == {"created": 1, "duplicates": 0}
    resp2 = client.post(url, [item], format="json")
    assert resp2.status_code == 201
    assert resp2.json() == {"created": 0, "duplicates": 1}


def test_att_event_ingest_bad_sig(db):
    data = setup_data()
    company = data["company"]
    emp = data["emp"]
    admin = data["admin"]
    device = Device.objects.create(
        company=company, name="Dev", device_type="kiosk", hmac_secret="sekrit"
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    ts = timezone.now().isoformat()
    item = {
        "employee_id": emp.id,
        "ts": ts,
        "direction": "IN",
        "device_id": device.id,
        "provider": "faceprov",
        "payload_sig": "bad",
    }
    resp = client.post("/api/attendance/events/ingest/", [item], format="json")
    assert resp.status_code == 403


def test_att_event_ingest_inactive_device(db):
    data = setup_data()
    company = data["company"]
    emp = data["emp"]
    admin = data["admin"]
    device = Device.objects.create(
        company=company,
        name="Dev",
        device_type="kiosk",
        hmac_secret="sekrit",
        is_active=False,
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    ts = timezone.now().isoformat()
    sig = hmac.new(
        key=device.hmac_secret.encode("utf-8"),
        msg=f"{emp.id}|{ts}|IN|{device.id}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    item = {
        "employee_id": emp.id,
        "ts": ts,
        "direction": "IN",
        "device_id": device.id,
        "provider": "faceprov",
        "payload_sig": sig,
    }
    resp = client.post("/api/attendance/events/ingest/", [item], format="json")
    assert resp.status_code == 400


def test_att_event_ingest_skew(db):
    data = setup_data()
    company = data["company"]
    emp = data["emp"]
    admin = data["admin"]
    device = Device.objects.create(
        company=company, name="Dev", device_type="kiosk", hmac_secret="sekrit"
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    ts = (timezone.now() + timedelta(minutes=11)).isoformat()
    sig = hmac.new(
        key=device.hmac_secret.encode("utf-8"),
        msg=f"{emp.id}|{ts}|IN|{device.id}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    item = {
        "employee_id": emp.id,
        "ts": ts,
        "direction": "IN",
        "device_id": device.id,
        "provider": "faceprov",
        "payload_sig": sig,
    }
    resp = client.post("/api/attendance/events/ingest/", [item], format="json")
    assert resp.status_code == 400


def test_roster_bulk_cross_company(db):
    data = setup_data()
    company2 = Company.objects.create(name="C2")
    branch2 = Branch.objects.create(company=company2, name="B2")
    dept2 = Department.objects.create(branch=branch2, name="D2")
    shift_other = ShiftTemplate.objects.create(
        company=company2,
        name="Day2",
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=0,
    )
    client = APIClient()
    client.force_authenticate(user=data["admin"])
    url = "/api/attendance/roster/bulk/"
    payload = [
        {
            "employee_id": data["emp"].id,
            "start_date": "2024-01-05",
            "end_date": "2024-01-05",
            "shift_id": shift_other.id,
        }
    ]
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 207
    assert resp.json()["results"][0]["status"] == "error"


def test_att_day_branch_filter(db):
    data = setup_data()
    company = data["company"]
    branch2 = Branch.objects.create(company=company, name="B2")
    dept2 = Department.objects.create(branch=branch2, name="D2")
    emp2 = Employee.objects.create_user(
        username="emp2",
        password="pass",
        department=dept2,
        hire_date=date(2024, 1, 1),
        employment_type="permanent",
        visa_type="personal",
    )
    shift = data["shift"]
    AttDay.objects.create(employee=data["emp"], date=date(2024, 1, 1), status="present", shift=shift)
    AttDay.objects.create(employee=emp2, date=date(2024, 1, 1), status="present", shift=shift)
    client = APIClient()
    client.force_authenticate(user=data["admin"])
    url = f"/api/attendance/days/?branch={data['branch'].id}"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["employee"] == data["emp"].id
