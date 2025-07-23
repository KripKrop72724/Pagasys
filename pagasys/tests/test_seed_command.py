from django.core.management import call_command
from django.contrib.auth.models import Group
from django.test import TestCase
from pagasys.models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
)


class SeedCommandTests(TestCase):
    def _run_seed(self):
        call_command("seed", verbosity=0)

    def test_seed_populates_models_and_admin(self):
        self._run_seed()

        # verify counts
        self.assertGreaterEqual(Company.objects.count(), 2)
        self.assertGreaterEqual(Branch.objects.count(), 4)
        self.assertGreaterEqual(Designation.objects.count(), 2)
        self.assertGreaterEqual(TradeLicense.objects.count(), 2)
        self.assertGreaterEqual(Department.objects.count(), 4)
        self.assertGreaterEqual(Project.objects.count(), 2)
        self.assertTrue(Employee.objects.filter(username="admin").exists())

        admin = Employee.objects.get(username="admin")
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("admin"))
        self.assertEqual(admin.email, "fytfytfyt420@gmail.com")

        expected_groups = {
            "Super Admin",
            "Company Admin",
            "Branch Manager",
            "Payroll Manager",
            "Department Manager",
            "Project Manager",
            "Employee",
        }
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), expected_groups)

    def test_seed_is_idempotent(self):
        self._run_seed()
        counts = {
            "companies": Company.objects.count(),
            "branches": Branch.objects.count(),
            "designations": Designation.objects.count(),
            "licenses": TradeLicense.objects.count(),
            "departments": Department.objects.count(),
            "projects": Project.objects.count(),
            "employees": Employee.objects.count(),
            "groups": Group.objects.count(),
        }
        self._run_seed()
        self.assertEqual(counts["companies"], Company.objects.count())
        self.assertEqual(counts["branches"], Branch.objects.count())
        self.assertEqual(counts["designations"], Designation.objects.count())
        self.assertEqual(counts["licenses"], TradeLicense.objects.count())
        self.assertEqual(counts["departments"], Department.objects.count())
        self.assertEqual(counts["projects"], Project.objects.count())
        self.assertEqual(counts["employees"], Employee.objects.count())
        self.assertEqual(counts["groups"], Group.objects.count())
