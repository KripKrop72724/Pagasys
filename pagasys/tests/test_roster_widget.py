import json
import subprocess
import textwrap

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

    def test_add_form_includes_branch_filter_and_script(self):
        url = reverse("admin:pagasys_rosterentry_add")
        res = self.client.get(url)
        self.assertContains(res, 'id="id_branch"')
        self.assertContains(res, f'data-branch="{self.branch.id}"')
        self.assertContains(res, "pagasys/js/roster_admin.js")

    def test_script_has_select_all_and_load_event(self):
        with open("pagasys/static/pagasys/js/roster_admin.js") as fh:
            content = fh.read()
        self.assertIn("window.addEventListener('load'", content)
        self.assertIn("Select all", content)
        self.assertIn("DOMContentLoaded", content)

    def test_branch_filter_applies_visibility(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const domReadyHandlers = [];
            let loadHandler = null;

            function Option(value, branch) {{
              this.value = value;
              this.dataset = branch ? {{ branch: String(branch) }} : {{}};
              this.hidden = false;
              this.selected = false;
            }}

            const branchEl = {{
              value: '',
              _handlers: {{}},
              addEventListener(event, fn) {{ this._handlers[event] = fn; }},
              parentNode: {{ insertBefore(){{}} }},
            }};

            function createSelect(options) {{
              return {{
                options,
                parentNode: {{ insertBefore(){{}} }},
                addEventListener() {{}},
              }};
            }}

            const sourceOptions = [
              new Option('emp1', '{self.branch.id}'),
              new Option('emp2', '999'),
            ];

            const elements = {{
              'id_branch': branchEl,
              'id_employees': createSelect(sourceOptions),
            }};

            const document = {{
              getElementById(id) {{ return elements[id]; }},
              createElement(tag) {{ return {{ type: tag, parentNode: {{ insertBefore(){{}} }}, addEventListener(){{}}, textContent:'' }}; }},
              addEventListener(evt, fn) {{ if (evt === 'DOMContentLoaded') domReadyHandlers.push(fn); }},
            }};

            const window = {{
              addEventListener(evt, fn) {{ if (evt === 'load') loadHandler = fn; }},
            }};

            const code = fs.readFileSync('pagasys/static/pagasys/js/roster_admin.js', 'utf8');
            vm.runInNewContext(code, {{ document, window }});

            domReadyHandlers.forEach(fn => fn());

            elements['id_employees_from'] = createSelect(
              sourceOptions.map(opt => new Option(opt.value))
            );
            elements['id_employees'].options = [];

            loadHandler();

            branchEl.value = '{self.branch.id}';
            branchEl._handlers.change();

            const result = elements['id_employees_from'].options.map(opt => ({{
              value: opt.value,
              hidden: opt.hidden,
              branch: opt.dataset.branch,
            }}));
            console.log(JSON.stringify(result));
            """
        )
        res = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)
        visible = [opt["value"] for opt in data if not opt["hidden"]]
        assert visible == ["emp1"]
