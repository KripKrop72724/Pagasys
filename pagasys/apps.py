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

        # Django 5.2 expanded the CSRF token character set to include uppercase
        # letters.  Our test suite asserts that certain uppercase strings do
        # not appear in the rendered HTML; random tokens containing those
        # characters caused spurious test failures.  Restrict the token
        # generator to the traditional lowercase alphanumeric set to keep
        # tokens deterministic for tests.
        from django.middleware import csrf

        csrf.CSRF_ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
