from django.apps import AppConfig
from django.contrib import admin


class PagasysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pagasys"

    def ready(self):
        """Brand the Django admin with the Pagasys name."""
        admin.site.site_header = "Pagasys Payroll administration"
        admin.site.site_title = "Pagasys Payroll admin"
        admin.site.index_title = "Pagasys Payroll administration"
