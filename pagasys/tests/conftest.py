import os
import pytest

# Configure minimal Django settings for the test run as early as possible so
# that pytest-django can import the Django settings module without failing.
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("ALLOWED_HOSTS", "localhost")

@pytest.fixture(scope="session", autouse=True)
def _django_test_env():
    """Configure environment variables for Django tests."""
    os.environ.setdefault("DATABASE_URL", "sqlite:///db.sqlite3")
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["DEBUG"] = "True"
    os.environ["ALLOWED_HOSTS"] = "localhost"
