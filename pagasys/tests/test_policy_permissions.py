from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from pagasys.models import (
    Company,
    Branch,
    Department,
    TradeLicense,
    WorkCalendar,
    ShiftTemplate,
)


class PolicyEndpointPermissionTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B")
        self.department = Department.objects.create(branch=self.branch, name="D")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=5,
        )
        self.license.branches.set([self.branch])

        pm_group = Group.objects.get(name="Payroll Manager")
        bm_group = Group.objects.get(name="Branch Manager")
        UserModel = get_user_model()
        self.pm = UserModel.objects.create_user(
            username="pm",
            password="pass",
            is_staff=True,
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.pm.groups.add(pm_group)
        self.bm = UserModel.objects.create_user(
            username="bm",
            password="pass",
            is_staff=True,
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.bm.groups.add(bm_group)

        self.auth_client = APIClient()
        self.auth_client.force_authenticate(self.pm)
        self.unauth_client = APIClient()
        self.unauth_client.force_authenticate(self.bm)

        self.superuser = UserModel.objects.create_superuser(
            username="su",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.super_client = APIClient()
        self.super_client.force_authenticate(self.superuser)

        self.calendar = WorkCalendar.objects.create(
            company=self.company, name="Cal", is_default=True
        )
        self.shift_template = ShiftTemplate.objects.create(
            company=self.company,
            name="S1",
            start_time="09:00",
            end_time="17:00",
        )

    def _assert_bulk_flow(
        self, base, create_payload, update_payload, update_status=200, delete_status=200
    ):
        res = self.unauth_client.post(f"{base}bulk/", create_payload, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.super_client.post(f"{base}bulk/", create_payload, format="json")
        self.assertEqual(res.status_code, 201)
        ids = [obj["id"] for obj in res.data["created"]]
        res = self.unauth_client.patch(f"{base}bulk-update/", update_payload(ids), format="json")
        self.assertEqual(res.status_code, 403)
        res = self.super_client.patch(f"{base}bulk-update/", update_payload(ids), format="json")
        self.assertEqual(res.status_code, update_status)
        res = self.unauth_client.post(f"{base}bulk-delete/", ids, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.super_client.post(f"{base}bulk-delete/", ids, format="json")
        self.assertEqual(res.status_code, delete_status)

    def test_workcalendar_permissions(self):
        payload = {"company": self.company.id, "name": "NC"}
        res = self.unauth_client.post("/api/calendars/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.auth_client.post("/api/calendars/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        cal_id = res.data["id"]
        res = self.auth_client.patch(f"/api/calendars/{cal_id}/", {"name": "UC"}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.auth_client.delete(f"/api/calendars/{cal_id}/")
        self.assertEqual(res.status_code, 403)
        self._assert_bulk_flow(
            "/api/calendars/",
            [{"company": self.company.id, "name": "B1"}],
            lambda ids: [{"id": ids[0], "name": "B2"}],
        )

    def test_shift_template_permissions(self):
        payload = {
            "company": self.company.id,
            "name": "S2",
            "start_time": "08:00",
            "end_time": "16:00",
        }
        res = self.unauth_client.post("/api/shift-templates/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.auth_client.post("/api/shift-templates/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        st_id = res.data["id"]
        res = self.auth_client.patch(
            f"/api/shift-templates/{st_id}/", {"break_minutes": 30}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        res = self.auth_client.delete(f"/api/shift-templates/{st_id}/")
        self.assertEqual(res.status_code, 403)
        self._assert_bulk_flow(
            "/api/shift-templates/",
            [{"company": self.company.id, "name": "SB", "start_time": "09:00", "end_time": "17:00"}],
            lambda ids: [{"id": ids[0], "name": "SB2"}],
        )

    def test_shift_rule_permissions(self):
        payload = {
            "shift": self.shift_template.id,
            "kind": "night_ot_window",
            "value": "20:00-02:00",
            "weekdays": "",
            "active_from": None,
            "active_to": None,
        }
        res = self.unauth_client.post("/api/shift-rules/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.auth_client.post("/api/shift-rules/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        rule_id = res.data["id"]
        res = self.auth_client.patch(
            f"/api/shift-rules/{rule_id}/", {"value": "21:00-03:00"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        res = self.auth_client.delete(f"/api/shift-rules/{rule_id}/")
        self.assertEqual(res.status_code, 403)
        self._assert_bulk_flow(
            "/api/shift-rules/",
            [
                {
                    "shift": self.shift_template.id,
                    "kind": "night_ot_window",
                    "value": "22:00-04:00",
                    "weekdays": "",
                    "active_from": None,
                    "active_to": None,
                }
            ],
            lambda ids: [
                {
                    "id": ids[0],
                    "shift": self.shift_template.id,
                    "kind": "night_ot_window",
                    "value": "21:00-03:00",
                    "weekdays": "",
                    "active_from": None,
                    "active_to": None,
                }
            ],
            update_status=207,
            delete_status=200,
        )

    def test_holiday_permissions(self):
        payload = {
            "calendar": self.calendar.id,
            "date": "2024-02-01",
            "name": "H1",
        }
        res = self.unauth_client.post("/api/holidays/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.auth_client.post("/api/holidays/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        h_id = res.data["id"]
        res = self.auth_client.patch(
            f"/api/holidays/{h_id}/", {"name": "H2"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        res = self.auth_client.delete(f"/api/holidays/{h_id}/")
        self.assertEqual(res.status_code, 403)
        self._assert_bulk_flow(
            "/api/holidays/",
            [{"calendar": self.calendar.id, "date": "2024-03-01", "name": "HB"}],
            lambda ids: [{"id": ids[0], "name": "HB2"}],
        )

    def test_leave_type_permissions(self):
        payload = {"company": self.company.id, "code": "AL", "name": "Annual"}
        res = self.unauth_client.post("/api/leave-types/", payload, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.auth_client.post("/api/leave-types/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        lt_id = res.data["id"]
        res = self.auth_client.patch(
            f"/api/leave-types/{lt_id}/", {"name": "Annual Leave"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        res = self.auth_client.delete(f"/api/leave-types/{lt_id}/")
        self.assertEqual(res.status_code, 403)
        self._assert_bulk_flow(
            "/api/leave-types/",
            [{"company": self.company.id, "code": "SL", "name": "Sick"}],
            lambda ids: [{"id": ids[0], "name": "Sick Leave"}],
        )
