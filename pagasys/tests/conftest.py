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
    # Force a local SQLite database to avoid external connections. The
    # optional PYTEST_DATABASE_URL variable can override this when running
    # the suite in environments that provide a database service.
    os.environ["DATABASE_URL"] = os.getenv(
        "PYTEST_DATABASE_URL", "sqlite:///db.sqlite3"
    )
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["DEBUG"] = "True"
    os.environ["ALLOWED_HOSTS"] = "localhost"

