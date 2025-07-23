from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.apps import apps


class Command(BaseCommand):
    help = "Create default role groups with model permissions"

    # Mapping of role to (models, perms)
    ROLE_CONFIG = {
        "Super Admin": {
            "models": [
                "Company",
                "Branch",
                "Designation",
                "TradeLicense",
                "Department",
                "Project",
                "Employee",
            ],
            "perms": ["add", "change", "delete", "view"],
        },
        "Company Admin": {
            "models": [
                "Branch",
                "Designation",
                "TradeLicense",
                "Department",
                "Project",
                "Employee",
            ],
            "perms": ["add", "change", "view"],
        },
        "Branch Manager": {
            "models": ["Department", "Project", "Employee"],
            "perms": ["add", "change", "view"],
        },
        "Payroll Manager": {
            "models": ["Employee", "Payslip"],
            "perms": ["add", "change", "view"],
        },
        "Department Manager": {
            "models": ["Employee"],
            "perms": ["change", "view"],
        },
        "Project Manager": {
            "models": ["Employee"],
            "perms": ["change", "view"],
        },
        "Employee": {
            "models": ["Employee", "Payslip"],
            "perms": ["view"],
        },
    }

    def handle(self, *args, **options):
        for role, cfg in self.ROLE_CONFIG.items():
            group, _ = Group.objects.get_or_create(name=role)
            perms = []
            for model_label in cfg["models"]:
                try:
                    model_cls = apps.get_model("pagasys", model_label)
                except LookupError:
                    model_cls = None
                if model_cls is not None:
                    ct = ContentType.objects.get_for_model(model_cls)
                else:
                    ct, _ = ContentType.objects.get_or_create(app_label="pagasys", model=model_label.lower())
                for action in cfg["perms"]:
                    codename = f"{action}_{ct.model}"
                    perm, _ = Permission.objects.get_or_create(
                        codename=codename,
                        content_type=ct,
                        defaults={"name": f"Can {action} {model_label}"},
                    )
                    perms.append(perm)
            group.permissions.set(perms)
            self.stdout.write(f"Synced permissions for {role}")
        self.stdout.write(self.style.SUCCESS("Group initialization complete"))
