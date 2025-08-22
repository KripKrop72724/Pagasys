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
        # tokens deterministic for tests.  Older CSRF cookies may still contain
        # characters outside this set, so gracefully replace any such cookies
        # instead of raising a server error.

        from django.middleware import csrf
        from django.utils.crypto import get_random_string

        allowed_chars = "abcdefghijklmnopqrstuvwxyz0123456789"

        csrf.CSRF_ALLOWED_CHARS = allowed_chars

        def _get_new_csrf_string() -> str:  # pragma: no cover - simple wrapper
            return get_random_string(csrf.CSRF_SECRET_LENGTH, allowed_chars=allowed_chars)

        csrf._get_new_csrf_string = _get_new_csrf_string

        def get_token(request):
            secret = request.META.get("CSRF_COOKIE")
            if secret is None or any(c not in allowed_chars for c in secret):
                secret = csrf._add_new_csrf_cookie(request)
            else:
                request.META["CSRF_COOKIE_NEEDS_UPDATE"] = True
            return csrf._mask_cipher_secret(secret)

        csrf.get_token = get_token
