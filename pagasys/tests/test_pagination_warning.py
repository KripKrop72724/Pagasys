import warnings
from django.core.management import call_command
from django.core.paginator import UnorderedObjectListWarning
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from pagasys.models import (
    Company, Branch, Designation, TradeLicense,
    Department, Project, Employee,
)


class PaginationWarningTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        User = get_user_model()
        self.company = Company.objects.create(name="Acme")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.project = Project.objects.create(branch=self.branch, name="P1", start_date="2024-01-01")
        self.designation = Designation.objects.create(company=self.company, name="Eng")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="LIC1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch])
        self.user = User.objects.create_user(
            username="admin",
            password="pass",
            is_staff=True,
            is_superuser=True,
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        groups = [
            "Company Admin",
            "Branch Manager",
            "Department Manager",
            "Project Manager",
            "Payroll Manager",
        ]
        for name in groups:
            grp, _ = Group.objects.get_or_create(name=name)
            self.user.groups.add(grp)
        self.client.force_authenticate(self.user)

        # create additional objects for pagination safety
        Company.objects.create(name="Other")
        Branch.objects.create(company=self.company, name="B2")
        Designation.objects.create(company=self.company, name="Tech")
        lic2 = TradeLicense.objects.create(
            company=self.company,
            license_no="LIC2",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=5,
        )
        lic2.branches.set([self.branch])
        Department.objects.create(branch=self.branch, name="D2")
        Project.objects.create(branch=self.branch, name="P2", start_date="2024-01-01")
        User.objects.create_user(
            username="emp1",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )
        User.objects.create_user(
            username="emp2",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-03",
            employment_type="permanent",
            visa_type="company",
        )

    def _check_endpoint(self, url):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", UnorderedObjectListWarning)
            res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(
            any(isinstance(rec.message, UnorderedObjectListWarning) for rec in w),
            f"UnorderedObjectListWarning for {url}",
        )

    def test_all_list_endpoints_ordered(self):
        endpoints = [
            "/api/companies/",
            "/api/branches/",
            "/api/designations/",
            "/api/licenses/",
            "/api/departments/",
            "/api/projects/",
            "/api/employees/",
        ]
        for url in endpoints:
            self._check_endpoint(url)

    def test_all_query_param_returns_full_collection(self):
        base_url = "/api/companies/"
        paginated = self.client.get(base_url, {"page_size": 1})
        self.assertEqual(paginated.status_code, 200)
        payload = paginated.json()
        self.assertIn("results", payload)
        self.assertEqual(len(payload["results"]), 1)
        self.assertNotEqual(payload.get("next"), None)

        unpaginated = self.client.get(base_url, {"page_size": 1, "all": "true"})
        self.assertEqual(unpaginated.status_code, 200)
        data = unpaginated.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), Company.objects.count())

    def test_all_query_param_requires_boolean(self):
        response = self.client.get("/api/companies/", {"all": "maybe"})
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("errors", payload)
        self.assertIn("all", payload["errors"])


class ModelOrderingTests(TestCase):
    def test_meta_ordering_defined(self):
        models = [
            Company,
            Branch,
            Designation,
            TradeLicense,
            Department,
            Project,
            Employee,
        ]
        for model in models:
            self.assertTrue(
                getattr(model._meta, "ordering", None),
                f"{model.__name__} missing ordering",
            )
