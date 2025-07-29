from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from rest_framework.test import APIClient
from django.test import TestCase

from .test_models import ModelFactoryMixin
from pagasys.models import Company, Branch, Department, TradeLicense, Project


class OtherModelFilterTests(ModelFactoryMixin, TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        User = get_user_model()
        self.company = Company.objects.create(name="C1")
        self.company2 = Company.objects.create(name="C2")
        self.branch1 = Branch.objects.create(company=self.company, name="B1")
        self.branch2 = Branch.objects.create(company=self.company2, name="B2")
        self.department1 = Department.objects.create(branch=self.branch1, name="D1")
        self.department2 = Department.objects.create(branch=self.branch2, name="D2")
        self.project1 = Project.objects.create(branch=self.branch1, name="P1", start_date="2024-01-01")
        self.project2 = Project.objects.create(branch=self.branch2, name="P2", start_date="2024-01-02")
        self.license1 = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=1,
        )
        self.license1.branches.set([self.branch1])
        self.license2 = TradeLicense.objects.create(
            company=self.company2,
            license_no="L2",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=2,
        )
        self.license2.branches.set([self.branch2])

        self.user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license1,
            department=self.department1,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_authenticate(self.user)

    def _ids(self, res):
        return set(obj["id"] for obj in res.data["results"])

    def test_branch_filter_by_company(self):
        url = f"/api/branches/?company={self.company2.id}"
        res = self.client.get(url)
        self.assertEqual(self._ids(res), {self.branch2.id})

    def test_department_filter_chain(self):
        url = f"/api/departments/?branch={self.branch1.id}&name=D1"
        res = self.client.get(url)
        self.assertEqual(self._ids(res), {self.department1.id})

    def test_license_invalid_company(self):
        res = self.client.get("/api/licenses/?company=9999")
        self.assertEqual(res.status_code, 400)

    def test_project_multiple_filters(self):
        url = f"/api/projects/?branch={self.branch2.id}&name=P2"
        res = self.client.get(url)
        self.assertEqual(self._ids(res), {self.project2.id})

    def test_license_filter_by_max_visas(self):
        res = self.client.get("/api/licenses/?max_visas=2")
        self.assertEqual(self._ids(res), {self.license2.id})

    def test_project_filter_by_start_date(self):
        res = self.client.get("/api/projects/?start_date=2024-01-01")
        self.assertEqual(self._ids(res), {self.project1.id})

