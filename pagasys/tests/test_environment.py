import os
from django.conf import settings


def test_uses_sqlite_by_default():
    """DATABASE_URL should default to sqlite for isolated tests."""
    # Provided by conftest
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    # Django may use an in-memory database for tests, so just ensure it's sqlite
    assert os.environ["DATABASE_URL"].startswith("sqlite:")
