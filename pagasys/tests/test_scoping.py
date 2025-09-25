from datetime import date, time

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from pagasys.policy.views import RosterViewSet
from pagasys.views import EmployeeViewSet

from pagasys.policy.permissions import IsCompanyMember
from pagasys.models import (
    Company,
    Branch,
    Department,
    Project,
    ShiftTemplate,
    RosterEntry,
    TradeLicense,
)
from pagasys.utils import scope_queryset, employee_company_q
from capture.models import AttendanceDevice


class CompanyScopedQuerysetTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.User = get_user_model()

        self.company = Company.objects.create(name="Primary Co")
        self.branch = Branch.objects.create(company=self.company, name="Primary Branch")
        self.department = Department.objects.create(branch=self.branch, name="Primary Dept")
        self.project = Project.objects.create(
            branch=self.branch,
            name="Project Alpha",
            start_date=date(2024, 1, 1),
        )

        self.other_company = Company.objects.create(name="Other Co")
        other_branch = Branch.objects.create(company=self.other_company, name="Other Branch")
        self.other_department = Department.objects.create(
            branch=other_branch, name="Other Dept"
        )

        self.shift = ShiftTemplate.objects.create(
            company=self.company,
            name="Day Shift",
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self.other_shift = ShiftTemplate.objects.create(
            company=self.other_company,
            name="Alt Shift",
            start_time=time(8, 0),
            end_time=time(16, 0),
        )

        self.company_admin = self.User.objects.create_user(
            username="company-admin",
            password="pass",
            department=self.department,
            hire_date=date(2024, 1, 1),
            employment_type="permanent",
            visa_type="personal",
            is_staff=True,
        )
        admin_group = Group.objects.get(name="Company Admin")
        self.company_admin.groups.add(admin_group)

        self.department_employee = self.User.objects.create_user(
            username="dept-emp",
            password="pass",
            department=self.department,
            hire_date=date(2024, 1, 2),
            employment_type="permanent",
            visa_type="personal",
        )
        self.project_employee = self.User.objects.create_user(
            username="proj-emp",
            password="pass",
            project=self.project,
            hire_date=date(2024, 1, 3),
            employment_type="permanent",
            visa_type="personal",
        )
        self.other_employee = self.User.objects.create_user(
            username="other-emp",
            password="pass",
            department=self.other_department,
            hire_date=date(2024, 1, 4),
            employment_type="permanent",
            visa_type="personal",
        )

        self.department_roster = RosterEntry(
            employee=self.department_employee,
            shift=self.shift,
            date=date(2024, 1, 10),
        )
        self.department_roster.full_clean()
        self.department_roster.save()

        self.project_roster = RosterEntry(
            employee=self.project_employee,
            shift=self.shift,
            date=date(2024, 1, 11),
        )
        self.project_roster.full_clean()
        self.project_roster.save()

        self.other_roster = RosterEntry(
            employee=self.other_employee,
            shift=self.other_shift,
            date=date(2024, 1, 12),
        )
        self.other_roster.full_clean()
        self.other_roster.save()

        self.factory = APIRequestFactory()
        self.company_view = type("View", (), {"kwargs": {"company_id": str(self.company.id)}})()
        self.other_company_view = type(
            "View", (), {"kwargs": {"company_id": str(self.other_company.id)}}
        )()
        self.permission = IsCompanyMember()

    def _roster_queryset_for(self, user):
        view = RosterViewSet()
        django_request = self.factory.get("/")
        force_authenticate(django_request, user=user)
        view.request = Request(django_request)
        view.action = "list"
        view.kwargs = {"company_id": str(self.company.id)}
        return view.filter_queryset(view.get_queryset())

    def _employee_queryset_for(self, user):
        view = EmployeeViewSet()
        django_request = self.factory.get("/")
        force_authenticate(django_request, user=user)
        view.request = Request(django_request)
        view.action = "list"
        return view.filter_queryset(view.get_queryset())

    def test_company_admin_sees_department_and_project_employees(self):
        qs = scope_queryset(self.User.objects.all(), self.company_admin)
        self.assertIn(self.department_employee, qs)
        self.assertIn(self.project_employee, qs)
        self.assertNotIn(self.other_employee, qs)

    def test_company_admin_sees_roster_entries_for_all_assignments(self):
        qs = scope_queryset(RosterEntry.objects.all(), self.company_admin)
        self.assertIn(self.department_roster, qs)
        self.assertIn(self.project_roster, qs)
        self.assertNotIn(self.other_roster, qs)

    def test_company_admin_roster_api_includes_trade_license_conflict(self):
        mismatch_license = TradeLicense.objects.create(
            company=self.other_company,
            license_no="OTHER-API-001",
            max_visas=5,
        )
        self.User.objects.filter(pk=self.company_admin.pk).update(
            visa_type="company", trade_license=mismatch_license
        )
        self.company_admin.refresh_from_db()

        qs = self._roster_queryset_for(self.company_admin)
        self.assertIn(self.department_roster, qs)
        self.assertIn(self.project_roster, qs)
        self.assertNotIn(self.other_roster, qs)

    def test_employee_company_q_includes_assignments_without_licenses(self):
        expected = {
            self.company_admin,
            self.department_employee,
            self.project_employee,
        }
        self.assertSetEqual(
            set(self.User.objects.filter(employee_company_q(self.company))),
            expected,
        )
        self.assertSetEqual(
            set(self.User.objects.filter(employee_company_q(self.company.id))),
            expected,
        )

    def test_employee_company_ignores_trade_license_when_assignment_present(self):
        mismatch_license = TradeLicense.objects.create(
            company=self.other_company,
            license_no="OTHER-001",
            max_visas=5,
        )
        self.department_employee.trade_license = mismatch_license
        self.assertEqual(self.department_employee.assignment_company, self.company)
        self.assertEqual(self.department_employee.company, self.company)

    def test_employee_company_logs_when_assignment_missing(self):
        rogue = self.User(
            username="rogue",
            hire_date=date(2024, 1, 5),
            employment_type="permanent",
            visa_type="personal",
        )
        with self.assertLogs("pagasys.models", level="WARNING") as captured:
            self.assertIsNone(rogue.company)
        self.assertTrue(
            any(
                "lacks department/project assignment for company resolution" in message
                for message in captured.output
            )
        )

    def test_is_company_member_accepts_assignment_company(self):
        request = self.factory.get("/")
        request.user = self.company_admin
        self.assertTrue(self.permission.has_permission(request, self.company_view))

    def test_is_company_member_rejects_mismatched_company(self):
        request = self.factory.get("/")
        request.user = self.company_admin
        self.assertFalse(self.permission.has_permission(request, self.other_company_view))
        self.assertEqual(
            self.permission.message, "User does not belong to the requested company."
        )

    def test_is_company_member_logs_when_assignment_missing(self):
        rogue = self.User(
            username="rogue-no-assignment",
            hire_date=date(2024, 2, 1),
            employment_type="permanent",
            visa_type="personal",
        )
        request = self.factory.get("/")
        request.user = rogue
        with self.assertLogs("pagasys.policy.permissions", level="WARNING") as captured:
            self.assertFalse(self.permission.has_permission(request, self.company_view))
        self.assertEqual(
            self.permission.message,
            "No department/project assignment available for company scoping.",
        )
        self.assertTrue(
            any("missing organisational assignment" in message for message in captured.output)
        )

    def test_employee_api_lists_department_assignment_without_license(self):
        qs = self._employee_queryset_for(self.company_admin)
        self.assertIn(self.department_employee, qs)
        self.assertIn(self.project_employee, qs)
        self.assertNotIn(self.other_employee, qs)

    def test_company_admin_scopes_attendance_devices_by_assignment_company(self):
        device = AttendanceDevice.objects.create(
            company=self.company,
            name="Device One",
            api_key="device-key-1",
            branch=self.branch,
        )
        other_device = AttendanceDevice.objects.create(
            company=self.other_company,
            name="Other Device",
            api_key="device-key-2",
        )
        qs = scope_queryset(AttendanceDevice.objects.all(), self.company_admin)
        self.assertIn(device, qs)
        self.assertNotIn(other_device, qs)
