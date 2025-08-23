import os
import sys

import pytest


def reload_settings(env=None):
    env = env or {}
    for mod in [m for m in list(sys.modules) if m.startswith('config.settings')]:
        del sys.modules[mod]
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    from config.settings import base as reloaded
    return reloaded


def test_default_includes_0_0_0_0():
    s = reload_settings({'ALLOWED_HOSTS': None})
    assert '0.0.0.0' in s.ALLOWED_HOSTS


def test_env_override_allows_custom_hosts():
    s = reload_settings({'ALLOWED_HOSTS': 'example.com,0.0.0.0'})
    assert s.ALLOWED_HOSTS == ['example.com', '0.0.0.0']


@pytest.mark.django_db
def test_request_with_zero_host(client):
    response = client.get('/healthz/', HTTP_HOST='0.0.0.0')
    assert response.status_code == 200
