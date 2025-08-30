from django.core.management import call_command
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone

from pagasys.models import Company, Branch, Department, Project, TradeLicense, Employee
from capture.models import AttendanceDevice, EnrollmentLink, PunchEvent
from pagasys.policy.permissions import (
    COMPANY_ADMIN,
    PAYROLL_MANAGER,
    BRANCH_MANAGER,
    DEPT_MANAGER,
    PROJECT_MANAGER,
    EMPLOYEE_ROLE,
)


class CaptureAPITests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        User = get_user_model()
        self.company = Company.objects.create(name="C1")
        self.branch1 = Branch.objects.create(company=self.company, name="B1")
        self.branch2 = Branch.objects.create(company=self.company, name="B2")
        self.department1 = Department.objects.create(branch=self.branch1, name="D1")
        self.department2 = Department.objects.create(branch=self.branch2, name="D2")
        self.project1 = Project.objects.create(branch=self.branch1, name="P1", start_date="2024-01-01")
        self.license1 = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.license1.branches.set([self.branch1, self.branch2])

        roles = [
            COMPANY_ADMIN,
            PAYROLL_MANAGER,
            BRANCH_MANAGER,
            DEPT_MANAGER,
            PROJECT_MANAGER,
            EMPLOYEE_ROLE,
        ]
        self.users = {}
        for role in roles:
            user = User.objects.create_user(
                username=role.replace(" ", "_").lower(),
                password="pw",
                trade_license=self.license1,
                department=None if role == PROJECT_MANAGER else self.department1,
                project=self.project1 if role == PROJECT_MANAGER else None,
                hire_date="2024-01-01",
                employment_type="permanent",
                visa_type="company",
            )
            user.groups.add(Group.objects.get(name=role))
            self.users[role] = user

        self.other_employee = User.objects.create_user(
            username="other_emp",
            password="pw",
            trade_license=self.license1,
            department=self.department2,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.other_employee.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

        self.device1 = AttendanceDevice.objects.create(
            company=self.company, name="dev1", api_key="k1", branch=self.branch1
        )
        self.device2 = AttendanceDevice.objects.create(
            company=self.company, name="dev2", api_key="k2", branch=self.branch2
        )
        self.company2 = Company.objects.create(name="C2")
        self.branch_other = Branch.objects.create(company=self.company2, name="B3")
        self.device_other = AttendanceDevice.objects.create(
            company=self.company2, name="devx", api_key="k3", branch=self.branch_other
        )
        self.event1 = PunchEvent.objects.create(
            device=self.device1,
            company=self.company,
            employee=self.users[EMPLOYEE_ROLE],
            device_ts=timezone.now(),
        )
        self.event_outside = PunchEvent.objects.create(
            device=self.device2,
            company=self.company,
            employee=self.other_employee,
            device_ts=timezone.now(),
        )
        PunchEvent.objects.create(
            device=self.device_other,
            company=self.company2,
            device_ts=timezone.now(),
        )
        self.client = APIClient()

    def test_rbac_device_list(self):
        url = f"/api/companies/{self.company.id}/devices/"
        for role, user in self.users.items():
            self.client.force_authenticate(user)
            res = self.client.get(url)
            expected = 200 if role != EMPLOYEE_ROLE else 403
            self.assertEqual(res.status_code, expected, role)

    def test_device_assignment_scope(self):
        bm = self.users[BRANCH_MANAGER]
        self.client.force_authenticate(bm)
        url = f"/api/companies/{self.company.id}/devices/"
        res = self.client.post(
            url, {"name": "nb", "branch": self.branch1.id}, format="json"
        )
        self.assertEqual(res.status_code, 201)
        res = self.client.post(
            url, {"name": "nb2", "branch": self.branch2.id}, format="json"
        )
        self.assertEqual(res.status_code, 403)

    def test_enrollment_link_create_and_void(self):
        admin = self.users[COMPANY_ADMIN]
        emp = self.users[EMPLOYEE_ROLE]
        self.client.force_authenticate(admin)
        base = f"/api/companies/{self.company.id}/manage/employees/{emp.id}/face/enrollment-link/"
        res = self.client.post(base, {}, format="json")
        self.assertEqual(res.status_code, 200)
        token = res.data["token"]
        link = EnrollmentLink.objects.get(token=token)
        self.assertTrue(link.is_valid)
        res = self.client.delete(base)
        self.assertEqual(res.status_code, 204)
        link.refresh_from_db()
        self.assertFalse(link.is_valid)
        res = self.client.post(
            f"/api/companies/{self.company.id}/manage/employees/9999/face/enrollment-link/",
            {},
            format="json",
        )
        self.assertEqual(res.status_code, 404)
        bm = self.users[BRANCH_MANAGER]
        self.client.force_authenticate(bm)
        res = self.client.post(
            f"/api/companies/{self.company.id}/manage/employees/{self.other_employee.id}/face/enrollment-link/",
            {},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_enrollment_link_route_has_no_pk_segment(self):
        admin = self.users[COMPANY_ADMIN]
        emp = self.users[EMPLOYEE_ROLE]
        self.client.force_authenticate(admin)
        url = f"/api/companies/{self.company.id}/manage/employees/{emp.id}/face/enrollment-link/"
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.client.post(
            f"/api/companies/{self.company.id}/manage/0/employees/{emp.id}/face/enrollment-link/",
            {},
            format="json",
        )
        self.assertEqual(res.status_code, 404)

    def test_punch_event_listing_scope(self):
        bm = self.users[BRANCH_MANAGER]
        url = f"/api/companies/{self.company.id}/punch-events/"
        self.client.force_authenticate(bm)
        res = self.client.get(url)
        ids = [item["id"] for item in res.data["results"]]
        self.assertIn(self.event1.id, ids)
        self.assertNotIn(self.event_outside.id, ids)
        res = self.client.get(f"/api/companies/{self.company2.id}/punch-events/")
        self.assertEqual(res.status_code, 403)
        pm = self.users[PROJECT_MANAGER]
        self.client.force_authenticate(pm)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["results"], [])

    def test_rotate_key_permissions(self):
        url = f"/api/companies/{self.company.id}/devices/{self.device1.id}/rotate-key/"
        for role, expected in [
            (COMPANY_ADMIN, 200),
            (PAYROLL_MANAGER, 200),
            (BRANCH_MANAGER, 200),
            (DEPT_MANAGER, 404),
            (PROJECT_MANAGER, 404),
            (EMPLOYEE_ROLE, 403),
        ]:
            self.client.force_authenticate(self.users[role])
            res = self.client.post(url)
            self.assertEqual(res.status_code, expected, role)
