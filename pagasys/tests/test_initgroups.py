from django.core.management import call_command
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase


class InitGroupsCommandTests(TestCase):
    def setUp(self):
        # ensure no groups exist before running command
        Group.objects.all().delete()
        Permission.objects.all().delete()
        ContentType.objects.filter(app_label="pagasys", model="payslip").delete()

    def _run_command(self):
        call_command("initgroups", verbosity=0)

    def test_groups_created_with_correct_permissions(self):
        self._run_command()

        expected = {
            "Super Admin": {
                "perms": {"add", "change", "delete", "view"},
                "models": [
                    "company",
                    "branch",
                    "designation",
                    "tradelicense",
                    "department",
                    "project",
                    "employee",
                ],
            },
            "Company Admin": {
                "perms": {"add", "change", "view"},
                "models": [
                    "branch",
                    "designation",
                    "tradelicense",
                    "department",
                    "project",
                    "employee",
                ],
            },
            "Branch Manager": {
                "perms": {"add", "change", "view"},
                "models": ["department", "project", "employee"],
            },
            "Payroll Manager": {
                "perms": {"add", "change", "view"},
                "models": ["employee", "payslip"],
            },
            "Department Manager": {
                "perms": {"change", "view"},
                "models": ["employee"],
            },
            "Project Manager": {
                "perms": {"change", "view"},
                "models": ["employee"],
            },
            "Employee": {
                "perms": {"view"},
                "models": ["employee", "payslip"],
            },
        }

        for name, cfg in expected.items():
            group = Group.objects.get(name=name)
            perms = group.permissions.all()
            models = cfg["models"]
            actions = cfg["perms"]
            expected_codenames = {
                f"{action}_{model}" for model in models for action in actions
            }
            self.assertEqual({p.codename for p in perms}, expected_codenames)

    def test_command_idempotent(self):
        self._run_command()
        first_counts = {g.name: g.permissions.count() for g in Group.objects.all()}
        self._run_command()
        for g in Group.objects.all():
            self.assertEqual(g.permissions.count(), first_counts[g.name])
