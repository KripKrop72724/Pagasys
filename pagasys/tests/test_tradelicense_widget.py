from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.urls import reverse

from pagasys.models import Company, Branch, Department, TradeLicense
from pagasys.admin import TradeLicenseAdmin, BranchSelectMultiple


class TradeLicenseWidgetTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.factory = RequestFactory()

        self.c1 = Company.objects.create(name="C1")
        self.c2 = Company.objects.create(name="C2")
        self.b1 = Branch.objects.create(company=self.c1, name="B1")
        self.b2 = Branch.objects.create(company=self.c2, name="B2")
        dept = Department.objects.create(branch=self.b1, name="D1")

        self.lic = TradeLicense.objects.create(
            company=self.c1,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2025-01-01",
            max_visas=1,
        )
        self.lic.branches.set([self.b1])

        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.lic,
            department=dept,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.admin_user)

    def test_formfield_uses_custom_widget(self):
        admin = TradeLicenseAdmin(TradeLicense, self.site)
        request = self.factory.get("/")
        request.user = self.admin_user
        field = TradeLicense._meta.get_field("branches")
        formfield = admin.formfield_for_manytomany(field, request)
        self.assertIsInstance(formfield.widget, BranchSelectMultiple)

    def test_branch_options_have_company_attribute(self):
        url = reverse("admin:pagasys_tradelicense_add")
        res = self.client.get(url)
        self.assertContains(res, f'data-company="{self.c1.id}"')
        self.assertContains(res, f'data-company="{self.c2.id}"')

    def test_script_waits_for_page_load(self):
        with open("pagasys/static/pagasys/js/tradelicense_admin.js") as fh:
            content = fh.read()
        self.assertIn("window.addEventListener('load'", content)
