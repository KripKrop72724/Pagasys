import csv
import io
from datetime import timedelta
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from capture.models import EnrollmentLink
from pagasys.admin import EmployeeAdmin
from pagasys.models import Branch, Company, Department, TradeLicense


class EmployeeAdminEnrollmentLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="Acme")
        self.branch = Branch.objects.create(company=self.company, name="HQ")
        self.department = Department.objects.create(branch=self.branch, name="IT")
        self.trade_license = TradeLicense.objects.create(
            company=self.company,
            license_no="TL-1",
            issued_date="2024-01-01",
            expiry_date="2030-01-01",
            max_visas=10,
        )
        self.trade_license.branches.set([self.branch])

        self.admin_user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.trade_license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )

        self.employee_1 = User.objects.create_user(
            username="emp1",
            password="pass",
            first_name="Alice",
            last_name="Example",
            email="emp1@example.com",
            trade_license=self.trade_license,
            department=self.department,
            hire_date="2024-01-02",
            employment_type="permanent",
            visa_type="company",
        )

        self.employee_2 = User.objects.create_user(
            username="emp2",
            password="pass",
            first_name="Bob",
            last_name="Sample",
            trade_license=self.trade_license,
            department=self.department,
            hire_date="2024-01-03",
            employment_type="permanent",
            visa_type="company",
        )

        self.site = AdminSite()
        self.factory = RequestFactory()

    def test_list_display_includes_id(self):
        admin = EmployeeAdmin(get_user_model(), self.site)
        self.assertIn("id", admin.list_display)
        self.assertEqual(admin.list_display[0], "id")

    def test_download_enrollment_links_csv(self):
        admin = EmployeeAdmin(get_user_model(), self.site)
        request = self.factory.post("/")
        request.user = self.admin_user

        queryset = get_user_model().objects.filter(
            pk__in=[self.employee_1.pk, self.employee_2.pk]
        )
        fixed_now = timezone.now()

        with mock.patch("pagasys.admin.timezone.now", return_value=fixed_now):
            response = admin.download_enrollment_links_csv(request, queryset)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("enrollment-links-", response["Content-Disposition"])

        content = response.content.decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(len(rows), 2)

        returned_ids = {int(row["Employee ID"]) for row in rows}
        self.assertEqual(returned_ids, {self.employee_1.id, self.employee_2.id})

        expected_expires_at = (fixed_now + timedelta(days=10)).isoformat()

        for row in rows:
            self.assertEqual(row["Status"], "created")
            self.assertTrue(row["Enrollment URL"])
            self.assertTrue(row["Token"])
            self.assertEqual(row["Expires at"], expected_expires_at)
            self.assertEqual(row["Max uses"], "1")

        links = EnrollmentLink.objects.filter(
            employee__in=[self.employee_1, self.employee_2]
        )
        self.assertEqual(links.count(), 2)
        expected_expires_at_dt = fixed_now + timedelta(days=10)
        for link in links:
            self.assertEqual(link.expires_at, expected_expires_at_dt)
            self.assertEqual(link.max_uses, 1)
