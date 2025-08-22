from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from rest_framework.test import APIClient

from pagasys.models import (
    Company, Branch, Department, Designation, TradeLicense, Employee
)


class EmployeeFilteringOrderingTests(TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.client = APIClient()
        User = get_user_model()
        self.company = Company.objects.create(name="FilterCo")
        self.branch = Branch.objects.create(company=self.company, name="FB1")
        self.dept1 = Department.objects.create(branch=self.branch, name="D1")
        self.dept2 = Department.objects.create(branch=self.branch, name="D2")
        self.designation = Designation.objects.create(company=self.company, name="Eng")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="LICF",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.license.branches.set([self.branch])

        self.other_company = Company.objects.create(name="OtherCo")
        other_branch = Branch.objects.create(company=self.other_company, name="OB1")
        other_dept = Department.objects.create(branch=other_branch, name="OD1")
        self.other_license = TradeLicense.objects.create(
            company=self.other_company,
            license_no="LICO",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=10,
        )
        self.other_license.branches.set([other_branch])

        ca_group = Group.objects.get(name="Company Admin")
        self.user = User.objects.create_user(
            username="ca",
            password="pass",
            is_staff=True,
            trade_license=self.license,
            department=self.dept1,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.user.groups.add(ca_group)

        def make_emp(username, dept, first, last, hire):
            return User.objects.create_user(
                username=username,
                password="pass",
                trade_license=self.license,
                department=dept,
                designation=self.designation,
                first_name=first,
                last_name=last,
                hire_date=hire,
                employment_type="permanent",
            )

        self.emp_a = make_emp("a", self.dept1, "Alice", "Zephyr", "2024-01-05")
        self.emp_b = make_emp("b", self.dept2, "Bob", "Yellow", "2024-01-03")
        self.emp_c = make_emp("c", self.dept2, "Carol", "Xavier", "2024-01-01")

        self.temp_emp = User.objects.create_user(
            username="temp",
            password="pass",
            trade_license=self.license,
            department=self.dept1,
            designation=self.designation,
            first_name="Temp",
            last_name="Worker",
            hire_date="2024-02-01",
            employment_type="temporary",
        )

        self.other_emp = User.objects.create_user(
            username="other",
            password="pass",
            trade_license=self.other_license,
            department=other_dept,
            designation=self.designation,
            first_name="Other",
            last_name="Company",
            hire_date="2024-01-10",
            employment_type="permanent",
        )

    def _get_ids(self, res):
        return [obj["id"] for obj in res.data["results"]]

    def test_filter_multiple_fields(self):
        self.client.force_authenticate(self.user)
        url = f"/api/employees/?department={self.dept2.id}&designation={self.designation.id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        ids = set(self._get_ids(res))
        self.assertEqual(ids, {self.emp_b.id, self.emp_c.id})

    def test_filter_by_branch(self):
        self.client.force_authenticate(self.user)
        res = self.client.get(f"/api/employees/?branch={self.branch.id}")
        self.assertEqual(res.status_code, 200)
        ids = set(self._get_ids(res))
        self.assertEqual(
            ids,
            {
                self.emp_a.id,
                self.emp_b.id,
                self.emp_c.id,
                self.temp_emp.id,
                self.user.id,
            },
        )

    def test_invalid_filter_returns_empty(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/employees/?department=9999")
        self.assertEqual(res.status_code, 400)

    def test_ordering(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/employees/?ordering=last_name,-hire_date")
        self.assertEqual(res.status_code, 200)
        ids = [i for i in self._get_ids(res) if i != self.user.id]
        self.assertEqual(
            ids,
            [
                self.temp_emp.id,
                self.emp_c.id,
                self.emp_b.id,
                self.emp_a.id,
            ],
        )

    def test_filter_by_employment_type(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/employees/?employment_type=temporary")
        self.assertEqual(res.status_code, 200)
        ids = set(self._get_ids(res))
        self.assertEqual(ids, {self.temp_emp.id})

    def test_filter_by_company(self):
        self.client.force_authenticate(self.user)
        url = f"/api/employees/?trade_license__company={self.company.id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        ids = set(self._get_ids(res))
        expected = {
            self.user.id,
            self.emp_a.id,
            self.emp_b.id,
            self.emp_c.id,
            self.temp_emp.id,
        }
        self.assertEqual(ids, expected)
