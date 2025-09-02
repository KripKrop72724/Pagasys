from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from PIL import Image
import tempfile

from pagasys.models import Company, Branch, Department, TradeLicense


def _create_image(name="logo.png"):
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")

class CompanyAPITests(TestCase):
    """Ensure company endpoints expose contact fields."""

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        user_company = Company.objects.create(name="UserCo")
        branch = Branch.objects.create(company=user_company, name="B1")
        department = Department.objects.create(branch=branch, name="D1")
        license = TradeLicense.objects.create(
            company=user_company,
            license_no="L1",
            issued_date="2024-01-01",
            expiry_date="2099-01-01",
            max_visas=1,
        )
        license.branches.set([branch])
        self.user = User.objects.create_user(
            username="api", password="pass", is_staff=True, is_superuser=True,
            trade_license=license, department=department,
            hire_date="2024-01-01", employment_type="permanent", visa_type="company",
        )
        self.client.force_authenticate(self.user)

    def test_contact_fields_crud(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            payload = {
                "name": "CompA",
                "timezone": "Asia/Dubai",
                "address": "123 Main",
                "logo": _create_image(),
                "email": "a@b.com",
                "phone": "+1",
                "website": "http://example.com",
                "bank_account_number": "AE000000000000000001234567",
            }
            res = self.client.post("/api/companies/", payload, format="multipart")
            self.assertEqual(res.status_code, 201)
            comp_id = res.data["id"]

            res = self.client.get(f"/api/companies/{comp_id}/")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data["address"], payload["address"])
            self.assertTrue(res.data["logo"].endswith("logo.png"))
            self.assertEqual(res.data["email"], payload["email"])
            self.assertEqual(res.data["phone"], payload["phone"])
            self.assertEqual(res.data["website"], payload["website"])
            self.assertEqual(
                res.data["bank_account_number"], payload["bank_account_number"]
            )

            res = self.client.patch(
                f"/api/companies/{comp_id}/",
                {"address": "456 Ave", "bank_account_number": "AE999"},
                format="json",
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data["address"], "456 Ave")
            self.assertEqual(res.data["bank_account_number"], "AE999")

    def test_filter_by_bank_account_number(self):
        Company.objects.create(name="BankCo", bank_account_number="AC123")
        res = self.client.get("/api/companies/?bank_account_number=AC123")
        self.assertEqual(res.status_code, 200)
        ids = [c["id"] for c in res.data["results"]]
        self.assertEqual(ids, [Company.objects.get(name="BankCo").id])
