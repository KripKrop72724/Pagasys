from .base import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Bump the punch capture rate limit for tests to avoid hitting the
# django-ratelimit blocker during the suite.  The default value in the
# base settings is quite low (30 requests/minute) which is useful in
# production but causes the test suite – which exercises the endpoint
# extensively – to be throttled.  Setting a very high limit ensures that
# tests can run without interference while leaving the production
# behaviour untouched.
CAPTURE_PUNCH_RATE_LIMIT = "10000/m"
