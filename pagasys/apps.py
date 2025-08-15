from django.apps import AppConfig
from django.contrib import admin


class PagasysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pagasys"

    def ready(self):
        """Brand the Django admin and load attendance models."""
        admin.site.site_header = "Pagasys Payroll administration"
        admin.site.site_title = "Pagasys Payroll admin"
        admin.site.index_title = "Pagasys Payroll administration"
        # Import attendance models so Django registers them without touching
        # the existing core HR structure.
        from . import models_attendance  # noqa: F401
