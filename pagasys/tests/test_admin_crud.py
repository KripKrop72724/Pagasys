from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from PIL import Image
import tempfile

from pagasys.models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
)

from .test_models import ModelFactoryMixin


def _create_image(name="img.png"):
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


class AdminCRUDTests(ModelFactoryMixin, TestCase):
    """Verify basic CRUD flows for all admin models."""

    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.project = self.create_project(self.branch)
        self.designation = self.create_designation(self.company)
        self.license = self.create_license(
            company=self.company, branches=[self.branch], license_no="LICX", max_visas=5
        )

        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.superuser)
        # Ensure requests simulate the deployment host
        self.client.defaults["HTTP_HOST"] = "0.0.0.0"

    def _assert_deleted(self, model, obj_id):
        self.assertFalse(model.objects.filter(id=obj_id).exists())

    def test_company_crud(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            add_url = reverse("admin:pagasys_company_add")
            res = self.client.post(
                add_url,
                {
                    "name": "NewCo",
                    "timezone": "Asia/Dubai",
                    "address": "123 Main",
                    "logo": _create_image("logo.png"),
                    "email": "info@co.com",
                    "phone": "+1",
                    "website": "http://co.com",
                    "bank_account_number": "AC1",
                },
            )
            self.assertEqual(res.status_code, 302)
            comp = Company.objects.get(name="NewCo")

            change_url = reverse("admin:pagasys_company_change", args=[comp.id])
            res = self.client.post(
                change_url,
                {
                    "name": "NewCo2",
                    "timezone": "Asia/Dubai",
                    "address": "456 Ave",
                    "logo": _create_image("logo2.png"),
                    "email": "contact@co.com",
                    "phone": "+2",
                    "website": "http://co2.com",
                    "bank_account_number": "AC2",
                },
            )
            self.assertEqual(res.status_code, 302)
            comp.refresh_from_db()
            self.assertEqual(comp.name, "NewCo2")
            self.assertEqual(comp.address, "456 Ave")
            self.assertTrue(comp.logo.name.endswith("logo2.png"))
            self.assertEqual(comp.email, "contact@co.com")
            self.assertEqual(comp.phone, "+2")
            self.assertEqual(comp.website, "http://co2.com")
            self.assertEqual(comp.bank_account_number, "AC2")

            delete_url = reverse("admin:pagasys_company_delete", args=[comp.id])
            res = self.client.post(delete_url, {"post": "yes"})
            self.assertEqual(res.status_code, 302)
            self._assert_deleted(Company, comp.id)

    def test_branch_crud(self):
        add_url = reverse("admin:pagasys_branch_add")
        res = self.client.post(
            add_url,
            {"company": self.company.id, "name": "B2", "address": "Addr1"},
        )
        self.assertEqual(res.status_code, 302)
        obj = Branch.objects.get(name="B2")

        change_url = reverse("admin:pagasys_branch_change", args=[obj.id])
        res = self.client.post(
            change_url,
            {"company": self.company.id, "name": "B3", "address": "Addr2"},
        )
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "B3")
        self.assertEqual(obj.address, "Addr2")

        delete_url = reverse("admin:pagasys_branch_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Branch, obj.id)

    def test_designation_crud(self):
        add_url = reverse("admin:pagasys_designation_add")
        res = self.client.post(
            add_url, {"company": self.company.id, "name": "Des1", "level": "1"}
        )
        self.assertEqual(res.status_code, 302)
        obj = Designation.objects.get(name="Des1")

        change_url = reverse("admin:pagasys_designation_change", args=[obj.id])
        res = self.client.post(
            change_url,
            {"company": self.company.id, "name": "Des2", "level": "2"},
        )
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "Des2")

        delete_url = reverse("admin:pagasys_designation_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Designation, obj.id)

    def test_tradelicense_crud(self):
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            add_url = reverse("admin:pagasys_tradelicense_add")
            data = {
                "company": self.company.id,
                "name": "License 1",
                "license_no": "LNEW",
                "establishment_card_number": "EC1",
                "license_document": SimpleUploadedFile(
                    "lic.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
                "max_visas": 1,
                "branches": [],
            }
            res = self.client.post(add_url, data)
            self.assertEqual(res.status_code, 302)
            obj = TradeLicense.objects.get(license_no="LNEW")
            self.assertIsNone(obj.issued_date)
            self.assertIsNone(obj.expiry_date)
            self.assertEqual(list(obj.branches.all()), [])

            change_url = reverse("admin:pagasys_tradelicense_change", args=[obj.id])
            data["name"] = "License 2"
            data["license_no"] = "LNEW2"
            data["establishment_card_number"] = "EC2"
            data["license_document"] = SimpleUploadedFile(
                "lic2.pdf", b"%PDF-1.4", content_type="application/pdf"
            )
            data["branches"] = []
            res = self.client.post(change_url, data)
            self.assertEqual(res.status_code, 302)
            obj.refresh_from_db()
            self.assertEqual(obj.name, "License 2")
            self.assertEqual(obj.license_no, "LNEW2")
            self.assertEqual(obj.establishment_card_number, "EC2")
            self.assertTrue(obj.license_document.name.endswith("lic2.pdf"))

            delete_url = reverse("admin:pagasys_tradelicense_delete", args=[obj.id])
            res = self.client.post(delete_url, {"post": "yes"})
            self.assertEqual(res.status_code, 302)
            self._assert_deleted(TradeLicense, obj.id)

    def test_department_crud(self):
        add_url = reverse("admin:pagasys_department_add")
        res = self.client.post(add_url, {"branch": self.branch.id, "name": "D2"})
        self.assertEqual(res.status_code, 302)
        obj = Department.objects.get(name="D2")

        change_url = reverse("admin:pagasys_department_change", args=[obj.id])
        res = self.client.post(change_url, {"branch": self.branch.id, "name": "D3"})
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "D3")

        delete_url = reverse("admin:pagasys_department_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Department, obj.id)

    def test_project_crud(self):
        add_url = reverse("admin:pagasys_project_add")
        res = self.client.post(
            add_url, {"branch": self.branch.id, "name": "P2", "start_date": "2024-01-02"}
        )
        self.assertEqual(res.status_code, 302)
        obj = Project.objects.get(name="P2")

        change_url = reverse("admin:pagasys_project_change", args=[obj.id])
        res = self.client.post(
            change_url,
            {"branch": self.branch.id, "name": "P3", "start_date": "2024-01-03"},
        )
        self.assertEqual(res.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "P3")

        delete_url = reverse("admin:pagasys_project_delete", args=[obj.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Project, obj.id)

    def test_employee_crud(self):
        add_url = reverse("admin:pagasys_employee_add")
        data = {
            "username": "empadd",
            "usable_password": "true",
            "password1": "strongpass",
            "password2": "strongpass",
            "first_name": "John",
            "middle_name": "Q",
            "last_name": "Public",
            "trade_license": self.license.id,
            "department": self.department.id,
            "hire_date": "2024-02-01",
            "employment_type": "permanent",
            "visa_type": "company",
            "special_notes": "VIP",
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        emp = Employee.objects.get(username="empadd")
        self.assertEqual(emp.special_notes, "VIP")
        self.assertEqual(emp.middle_name, "Q")

        change_url = reverse("admin:pagasys_employee_change", args=[emp.id])
        res = self.client.get(change_url)
        self.assertEqual(res.status_code, 200)

        delete_url = reverse("admin:pagasys_employee_delete", args=[emp.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Employee, emp.id)

    def test_workcalendar_crud(self):
        add_url = reverse("admin:pagasys_workcalendar_add")
        res = self.client.post(add_url, {"company": self.company.id, "name": "Cal1"})
        self.assertEqual(res.status_code, 302)
        cal = WorkCalendar.objects.get(name="Cal1")

        change_url = reverse("admin:pagasys_workcalendar_change", args=[cal.id])
        res = self.client.post(change_url, {"company": self.company.id, "name": "Cal2"})
        self.assertEqual(res.status_code, 302)
        cal.refresh_from_db()
        self.assertEqual(cal.name, "Cal2")

        delete_url = reverse("admin:pagasys_workcalendar_delete", args=[cal.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(WorkCalendar, cal.id)

    def test_holiday_crud(self):
        cal = WorkCalendar.objects.create(company=self.company, name="HC")
        add_url = reverse("admin:pagasys_holiday_add")
        data = {"calendar": cal.id, "date": "2024-01-01", "name": "H1", "is_public": True}
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        hol = Holiday.objects.get(name="H1")

        change_url = reverse("admin:pagasys_holiday_change", args=[hol.id])
        data["name"] = "H2"
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        hol.refresh_from_db()
        self.assertEqual(hol.name, "H2")

        delete_url = reverse("admin:pagasys_holiday_delete", args=[hol.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(Holiday, hol.id)

    def test_shifttemplate_crud(self):
        add_url = reverse("admin:pagasys_shifttemplate_add")
        data = {
            "company": self.company.id,
            "name": "S1",
            "start_time": "09:00",
            "end_time": "17:00",
            "break_minutes": 0,
            "grace_in_min": 0,
            "grace_out_min": 0,
            "late_after_min": 0,
            "early_leave_before_min": 0,
            "rounding_min": 0,
        }
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        st = ShiftTemplate.objects.get(name="S1")

        change_url = reverse("admin:pagasys_shifttemplate_change", args=[st.id])
        data_change = data | {"name": "S2"}
        res = self.client.post(change_url, data_change)
        self.assertEqual(res.status_code, 302)
        st.refresh_from_db()
        self.assertEqual(st.name, "S2")

        delete_url = reverse("admin:pagasys_shifttemplate_delete", args=[st.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(ShiftTemplate, st.id)

    def test_shiftrule_crud(self):
        shift = self.create_shift_template(self.company, name="SR")
        add_url = reverse("admin:pagasys_shiftrule_add")
        data = {"shift": shift.id, "kind": ShiftRule.Kind.GEOFENCE_REQUIRED, "value": "10"}
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        rule = ShiftRule.objects.get(shift=shift, kind=ShiftRule.Kind.GEOFENCE_REQUIRED)

        change_url = reverse("admin:pagasys_shiftrule_change", args=[rule.id])
        data["value"] = "20"
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        rule.refresh_from_db()
        self.assertEqual(rule.value, "20")

        delete_url = reverse("admin:pagasys_shiftrule_delete", args=[rule.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(ShiftRule, rule.id)

    def test_rosterentry_crud(self):
        emp = get_user_model().objects.create_user(
            username="r1",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        shift = self.create_shift_template(self.company, name="RST")
        add_url = reverse("admin:pagasys_rosterentry_add")
        data = {"employees": [emp.id], "date": "2024-07-01", "shift": shift.id}
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        entry = RosterEntry.objects.get(employee=emp, date="2024-07-01")

        change_url = reverse("admin:pagasys_rosterentry_change", args=[entry.id])
        change_data = {"employee": emp.id, "date": "2024-07-02", "shift": shift.id}
        res = self.client.post(change_url, change_data)
        self.assertEqual(res.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(str(entry.date), "2024-07-02")

        delete_url = reverse("admin:pagasys_rosterentry_delete", args=[entry.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(RosterEntry, entry.id)

    def test_leavetype_crud(self):
        add_url = reverse("admin:pagasys_leavetype_add")
        data = {"company": self.company.id, "code": "AL", "name": "Annual", "paid_pct": 100}
        res = self.client.post(add_url, data)
        self.assertEqual(res.status_code, 302)
        lt = LeaveType.objects.get(code="AL")

        change_url = reverse("admin:pagasys_leavetype_change", args=[lt.id])
        data["name"] = "Annual Leave"
        data["paid_pct"] = 50
        res = self.client.post(change_url, data)
        self.assertEqual(res.status_code, 302)
        lt.refresh_from_db()
        self.assertEqual(lt.name, "Annual Leave")

        delete_url = reverse("admin:pagasys_leavetype_delete", args=[lt.id])
        res = self.client.post(delete_url, {"post": "yes"})
        self.assertEqual(res.status_code, 302)
        self._assert_deleted(LeaveType, lt.id)


class FieldValidationEdgeCaseTests(ModelFactoryMixin, TestCase):
    """Ensure model validations handle edge cases appropriately."""

    def setUp(self):
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)

    def test_company_name_length(self):
        with self.assertRaises(ValidationError):
            Company(name="" * 0).full_clean()
        with self.assertRaises(ValidationError):
            Company(name="x" * 256).full_clean()

    def test_branch_required_fields(self):
        with self.assertRaises(ValidationError):
            Branch(name="B", company=None).full_clean()
        with self.assertRaises(ValidationError):
            Branch(company=self.company, name="x" * 256).full_clean()

    def test_department_required_fields(self):
        with self.assertRaises(ValidationError):
            Department(name="", branch=self.branch).full_clean()
        with self.assertRaises(ValidationError):
            Department(name="x" * 256, branch=self.branch).full_clean()

    def test_project_required_fields(self):
        with self.assertRaises(ValidationError):
            Project(branch=self.branch, name="", start_date="2024-01-01").full_clean()
        with self.assertRaises(ValidationError):
            Project(branch=None, name="P", start_date="2024-01-01").full_clean()

    def test_designation_edge_cases(self):
        with self.assertRaises(ValidationError):
            Designation(company=self.company, name="x" * 101).full_clean()
        with self.assertRaises(ValidationError):
            Designation(company=None, name="D").full_clean()

