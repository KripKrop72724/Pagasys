from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path
from django.utils import timezone
from unittest.mock import PropertyMock, patch

from pagasys.models import Branch, Company, Department, Employee, TradeLicense


def tz_view(request):
    return HttpResponse(timezone.get_current_timezone_name())


def error_view(request):
    raise ValueError("boom")


urlpatterns = [
    path("tz/", tz_view),
    path("err/", error_view),
]


@override_settings(ROOT_URLCONF=__name__)
class CompanyTimezoneMiddlewareTests(TestCase):
    def _create_employee_with_company(self, tz="Asia/Kolkata"):
        company = Company.objects.create(name="Comp", timezone=tz)
        branch = Branch.objects.create(company=company, name="B")
        dept = Department.objects.create(branch=branch, name="D")
        lic = TradeLicense.objects.create(
            company=company,
            license_no="LIC",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        lic.branches.set([branch])
        user = Employee.objects.create_user(
            username="u",
            password="pass",
            trade_license=lic,
            department=dept,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        return user, company

    def test_authenticated_user_timezone_activation(self):
        user, company = self._create_employee_with_company("Asia/Kolkata")
        self.client.force_login(user)
        res = self.client.get("/tz/")
        self.assertEqual(res.content.decode(), "Asia/Kolkata")
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_anonymous_user_default_timezone(self):
        res = self.client.get("/tz/")
        self.assertEqual(res.content.decode(), "UTC")
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_user_without_company_falls_back_to_default(self):
        user, _ = self._create_employee_with_company()
        with patch.object(Employee, "company", new_callable=PropertyMock, return_value=None):
            self.client.force_login(user)
            res = self.client.get("/tz/")
            self.assertEqual(res.content.decode(), "UTC")
            self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_invalid_timezone_falls_back_to_default(self):
        company = Company.objects.create(name="Bad", timezone="Invalid/Zone")
        branch = Branch.objects.create(company=company, name="B")
        dept = Department.objects.create(branch=branch, name="D")
        lic = TradeLicense.objects.create(
            company=company,
            license_no="LIC2",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        lic.branches.set([branch])
        user = Employee.objects.create_user(
            username="u3",
            password="pass",
            trade_license=lic,
            department=dept,
            hire_date="2024-01-01",
            employment_type="permanent",
        )
        self.client.force_login(user)
        res = self.client.get("/tz/")
        self.assertEqual(res.content.decode(), "UTC")
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_deactivates_after_exception(self):
        user, _ = self._create_employee_with_company()
        self.client.force_login(user)
        with self.assertRaises(ValueError):
            self.client.get("/err/")
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")
