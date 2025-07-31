import os
import pytest

# Configure minimal Django settings for the test run as early as possible so
# that pytest-django can import the Django settings module without failing.
# Use fixed settings for tests to avoid interference from any existing
# environment configuration. The optional PYTEST_DATABASE_URL can override
# the database location when needed (e.g. CI provides a database service).
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DEBUG"] = "True"
os.environ["ALLOWED_HOSTS"] = "localhost"
os.environ["DATABASE_URL"] = os.getenv("PYTEST_DATABASE_URL", "sqlite:///db.sqlite3")

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

