import json

from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase
from django.contrib.auth import get_user_model

from pagasys.models import Employee
from .test_models import ModelFactoryMixin


class RosterWidgetTests(ModelFactoryMixin, TestCase):
    def setUp(self):
        call_command("initgroups", verbosity=0)
        self.company = self.create_company()
        self.branch = self.create_branch(self.company)
        self.department = self.create_department(self.branch)
        self.license = self.create_license(
            company=self.company, branches=[self.branch], max_visas=5
        )
        self.employee = Employee.objects.create_user(
            username="emp1",
            password="pass",
            department=self.department,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            password="pass",
            trade_license=self.license,
            department=self.department,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        self.client.force_login(self.admin_user)

    def test_add_form_uses_autocomplete_widget(self):
        url = reverse("admin:pagasys_rosterentry_add")
        res = self.client.get(url)
        self.assertContains(res, 'id="id_branch"')
        self.assertContains(res, "data-forward")
        self.assertNotContains(res, "pagasys/js/roster_admin.js")

    def test_employee_autocomplete_filters_by_branch(self):
        branch2 = self.create_branch(self.company, name="B2")
        dept2 = self.create_department(branch2)
        Employee.objects.create_user(
            username="emp2",
            password="pass",
            department=dept2,
            trade_license=self.license,
            hire_date="2024-01-01",
            employment_type="permanent",
            visa_type="company",
        )
        url = reverse("admin:pagasys_employee_autocomplete")
        params = {
            "term": "",
            "app_label": "pagasys",
            "model_name": "rosterentry",
            "field_name": "employee",
            "forward": "branch",
            "branch": self.branch.id,
        }
        res = self.client.get(url, params)
        data = json.loads(res.content)
        ids = [int(r["id"]) for r in data["results"]]
        self.assertIn(self.employee.id, ids)
