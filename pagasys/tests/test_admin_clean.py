from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from pagasys.models import Company, Branch, Department, TradeLicense
from pagasys.admin import TradeLicenseAdmin


class AdminFullCleanTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.company = Company.objects.create(name="C")
        self.branch = Branch.objects.create(company=self.company, name="B1")
        self.department = Department.objects.create(branch=self.branch, name="D1")
        self.license = TradeLicense.objects.create(
            company=self.company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        self.license.branches.set([self.branch])
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

    def _get_request(self):
        req = self.factory.post("/")
        req.user = self.user
        return req

    def test_save_model_runs_full_clean(self):
        admin = TradeLicenseAdmin(TradeLicense, self.site)
        obj = TradeLicense(
            company=self.company,
            license_no="BAD",
            issued_date="2025-01-01",
            expiry_date="2024-01-01",
            max_visas=1,
        )
        form = type("F", (), {"add_error": lambda *a, **k: None, "cleaned_data": {"branches": [self.branch]}})()
        with self.assertRaises(ValidationError):
            admin.save_model(self._get_request(), obj, form, False)
        self.assertFalse(TradeLicense.objects.filter(license_no="BAD").exists())

    def test_save_model_saves_valid(self):
        admin = TradeLicenseAdmin(TradeLicense, self.site)
        obj = TradeLicense(
            company=self.company,
            license_no="NEW",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        form = type("F", (), {"add_error": lambda *a, **k: None, "cleaned_data": {"branches": [self.branch]}})()
        admin.save_model(self._get_request(), obj, form, False)
        self.assertTrue(TradeLicense.objects.filter(license_no="NEW").exists())

    def test_branch_company_mismatch_rejected(self):
        admin = TradeLicenseAdmin(TradeLicense, self.site)
        other = Company.objects.create(name="O")
        other_branch = Branch.objects.create(company=other, name="BO")
        data = {
            "company": self.company.id,
            "license_no": "BAD2",
            "issued_date": "2024-01-01",
            "expiry_date": "2099-01-01",
            "max_visas": 1,
            "branches": [other_branch.id],
        }
        obj = TradeLicense(
            company=self.company,
            license_no="BAD2",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        form = type("F", (), {"add_error": lambda *a, **k: None, "cleaned_data": {"branches": [other_branch]}})()
        with self.assertRaises(ValidationError):
            admin.save_model(self._get_request(), obj, form, False)

    def test_update_company_with_old_branch_fails(self):
        admin = TradeLicenseAdmin(TradeLicense, self.site)
        other = Company.objects.create(name="O2")
        data = {
            "company": other.id,
            "license_no": self.license.license_no,
            "issued_date": "2024-01-01",
            "expiry_date": "2099-01-01",
            "max_visas": 1,
            "branches": [self.branch.id],
        }
        form = type("F", (), {"add_error": lambda *a, **k: None, "cleaned_data": {"branches": [self.branch]}})()
        obj = TradeLicense(
            company=other,
            license_no=self.license.license_no,
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        with self.assertRaises(ValidationError):
            admin.save_model(self._get_request(), obj, form, True)

    def test_media_includes_js(self):
        admin = TradeLicenseAdmin(TradeLicense, self.site)
        media = admin.media
        self.assertIn("tradelicense_admin.js", "".join(media._js))
