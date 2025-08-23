from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse

from pagasys.models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
)

from .test_models import ModelFactoryMixin


class AdminBulkDeleteTests(ModelFactoryMixin, TestCase):
    """Ensure bulk delete action functions for all admin models."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.factory = RequestFactory()
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.project = self.create_project(self.branch)
        self.designation = self.create_designation(self.company)
        self.license = self.create_license(
            company=self.company, branches=[self.branch], license_no="LIC0", max_visas=5
        )
        self.shift = self.create_shift_template(self.company)
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.superuser)
        # Mimic container setup where requests arrive via 0.0.0.0
        self.client.defaults["HTTP_HOST"] = "0.0.0.0"

    def _assert_has_delete_action(self, model):
        ma = admin.site._registry[model]
        request = self.factory.get("/admin/")
        request.user = self.superuser
        actions = ma.get_actions(request)
        self.assertIn("delete_selected", actions)

    def _bulk_delete(self, model, objs):
        ids = [obj.id for obj in objs]
        url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        res = self.client.post(url, {"action": "delete_selected", "_selected_action": ids})
        self.assertEqual(res.status_code, 200)
        res = self.client.post(
            url, {"action": "delete_selected", "_selected_action": ids, "post": "yes"}
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(model.objects.filter(id__in=ids).count(), 0)

    def test_company_bulk_delete(self):
        objs = [self.create_company(f"C{i}") for i in range(2)]
        self._assert_has_delete_action(Company)
        self._bulk_delete(Company, objs)

    def test_branch_bulk_delete(self):
        objs = [self.create_branch(self.company, f"B{i}") for i in range(2)]
        self._assert_has_delete_action(Branch)
        self._bulk_delete(Branch, objs)

    def test_designation_bulk_delete(self):
        objs = [self.create_designation(self.company, f"D{i}") for i in range(2)]
        self._assert_has_delete_action(Designation)
        self._bulk_delete(Designation, objs)

    def test_tradelicense_bulk_delete(self):
        objs = [
            self.create_license(
                company=self.company, branches=[self.branch], license_no=f"LIC{i + 1}", max_visas=5
            )
            for i in range(2)
        ]
        self._assert_has_delete_action(TradeLicense)
        self._bulk_delete(TradeLicense, objs)

    def test_department_bulk_delete(self):
        objs = [self.create_department(self.branch, f"D{i}") for i in range(2)]
        self._assert_has_delete_action(Department)
        self._bulk_delete(Department, objs)

    def test_project_bulk_delete(self):
        objs = [self.create_project(self.branch, f"P{i}") for i in range(2)]
        self._assert_has_delete_action(Project)
        self._bulk_delete(Project, objs)

    def _create_employee(self, username):
        User = get_user_model()
        return User.objects.create_user(
            username=username,
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

    def test_employee_bulk_delete(self):
        objs = [self._create_employee(f"e{i}") for i in range(2)]
        self._assert_has_delete_action(Employee)
        self._bulk_delete(Employee, objs)

    def test_workcalendar_bulk_delete(self):
        objs = [WorkCalendar.objects.create(company=self.company, name=f"WC{i}") for i in range(2)]
        self._assert_has_delete_action(WorkCalendar)
        self._bulk_delete(WorkCalendar, objs)

    def test_holiday_bulk_delete(self):
        cal = WorkCalendar.objects.create(company=self.company, name="HC")
        objs = [
            Holiday.objects.create(calendar=cal, date=f"2024-01-0{i + 1}", name=f"H{i}")
            for i in range(2)
        ]
        self._assert_has_delete_action(Holiday)
        self._bulk_delete(Holiday, objs)

    def test_shifttemplate_bulk_delete(self):
        objs = [self.create_shift_template(self.company, name=f"S{i}") for i in range(2)]
        self._assert_has_delete_action(ShiftTemplate)
        self._bulk_delete(ShiftTemplate, objs)

    def test_shiftrule_bulk_delete(self):
        shift = self.create_shift_template(self.company, name="SR")
        objs = [
            ShiftRule.objects.create(shift=shift, kind=k, value="10")
            for k in [ShiftRule.Kind.GEOFENCE_REQUIRED, ShiftRule.Kind.FACE_MIN_CONF]
        ]
        self._assert_has_delete_action(ShiftRule)
        self._bulk_delete(ShiftRule, objs)

    def test_rosterentry_bulk_delete(self):
        emp = self._create_employee("rdel")
        objs = [
            RosterEntry.objects.create(employee=emp, date=f"2024-07-0{i + 1}", shift=self.shift)
            for i in range(2)
        ]
        self._assert_has_delete_action(RosterEntry)
        self._bulk_delete(RosterEntry, objs)

    def test_leavetype_bulk_delete(self):
        objs = [
            LeaveType.objects.create(company=self.company, code=f"L{i}", name=f"L{i}")
            for i in range(2)
        ]
        self._assert_has_delete_action(LeaveType)
        self._bulk_delete(LeaveType, objs)
