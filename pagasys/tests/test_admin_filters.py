from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase

from pagasys.admin import (
    CompanyAdmin,
    BranchAdmin,
    DesignationAdmin,
    TradeLicenseAdmin,
    DepartmentAdmin,
    ProjectAdmin,
    EmployeeAdmin,
    RosterEntryAdmin,
)
from pagasys.models import (
    Company,
    Branch,
    Department,
    Project,
    Designation,
    TradeLicense,
    RosterEntry,
)
from .test_models import ModelFactoryMixin


class AdminFilterConfigTests(TestCase):
    """Verify list_filter is configured for all admin classes."""

    def test_list_filter_attributes(self):
        expected = {
            CompanyAdmin: ["name"],
            BranchAdmin: ["company", "work_calendar", "name"],
            DesignationAdmin: ["company", "name", "level"],
            TradeLicenseAdmin: [
                "company",
                "branches",
                "name",
                "license_no",
                "establishment_card_number",
                "issued_date",
                "expiry_date",
                "max_visas",
            ],
            DepartmentAdmin: ["branch", "name"],
            ProjectAdmin: ["branch", "name", "start_date", "end_date"],
            RosterEntryAdmin: [
                "employee__department__branch",
                "employee",
                "shift",
                "is_rest_day",
                "is_holiday",
                "was_holiday",
            ],
        }
        for admin_class, fields in expected.items():
            with self.subTest(admin=admin_class.__name__):
                self.assertEqual(list(admin_class.list_filter), fields)

        self.assertTrue(set(EmployeeAdmin.list_filter).issuperset(
            {"trade_license", "department", "project", "designation", "visa_type", "employment_type"}
        ))


class BranchFilterBehaviourTests(ModelFactoryMixin, TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.other_company = self.create_company("Other")
        self.branch = self.create_branch(self.company, name="B1")
        self.other_branch = self.create_branch(self.other_company, name="B2")
        self.department = self.create_department(self.branch)
        self.license = self.create_license(company=self.company, branches=[self.branch])

        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.user)

    def _get_ids(self, response):
        return list(response.context["cl"].queryset.values_list("id", flat=True))

    def test_filter_by_company(self):
        url = reverse("admin:pagasys_branch_changelist")
        res = self.client.get(url, {"company__id__exact": self.company.id})
        self.assertEqual(self._get_ids(res), [self.branch.id])

    def test_invalid_filter_returns_empty(self):
        url = reverse("admin:pagasys_branch_changelist")
        res = self.client.get(url, {"company__id__exact": 9999})
        self.assertEqual(self._get_ids(res), [])


class RosterEntryBranchFilterTests(ModelFactoryMixin, TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.branch1 = self.create_branch(self.company, name="B1")
        self.branch2 = self.create_branch(self.company, name="B2")
        self.department1 = self.create_department(self.branch1)
        self.department2 = self.create_department(self.branch2)
        self.license = self.create_license(
            company=self.company, branches=[self.branch1, self.branch2], max_visas=2
        )

        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department1,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.user)

        self.shift = self.create_shift_template(self.company, name="S1")
        self.entry1 = RosterEntry.objects.create(
            employee=self.user,
            date="2024-07-01",
            shift=self.shift,
        )
        self.emp2 = User.objects.create_user(
            username="e2",
            password="pass",
            trade_license=self.license,
            department=self.department2,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.entry2 = RosterEntry.objects.create(
            employee=self.emp2,
            date="2024-07-01",
            shift=self.shift,
        )

    def _get_ids(self, response):
        return list(response.context["cl"].queryset.values_list("id", flat=True))

    def test_filter_by_branch(self):
        url = reverse("admin:pagasys_rosterentry_changelist")
        res = self.client.get(
            url, {"employee__department__branch__id__exact": self.branch2.id}
        )
        self.assertEqual(self._get_ids(res), [self.entry2.id])

