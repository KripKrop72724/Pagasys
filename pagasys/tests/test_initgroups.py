from django.core.management import call_command
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from pagasys.policy.permissions import (
    COMPANY_ADMIN,
    BRANCH_MANAGER,
    PAYROLL_MANAGER,
    DEPT_MANAGER,
    PROJECT_MANAGER,
    EMPLOYEE_ROLE,
)


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
            COMPANY_ADMIN: {
                "perms": {"add", "change", "view"},
                "models": [
                    "branch",
                    "designation",
                    "tradelicense",
                    "department",
                    "project",
                    "employee",
                    "workcalendar",
                    "holiday",
                    "shifttemplate",
                    "shiftrule",
                    "rosterentry",
                    "leavetype",
                ],
            },
            BRANCH_MANAGER: {
                "perms": {"add", "change", "view"},
                "models": ["department", "project", "employee", "rosterentry"],
            },
            PAYROLL_MANAGER: {
                "perms": {"add", "change", "view"},
                "models": [
                    "employee",
                    "payslip",
                    "workcalendar",
                    "holiday",
                    "shifttemplate",
                    "shiftrule",
                    "rosterentry",
                    "leavetype",
                ],
            },
            DEPT_MANAGER: {
                "perms": {"change", "view"},
                "models": ["employee"],
            },
            PROJECT_MANAGER: {
                "perms": {"change", "view"},
                "models": ["employee"],
            },
            EMPLOYEE_ROLE: {
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
