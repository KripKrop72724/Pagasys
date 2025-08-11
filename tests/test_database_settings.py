import importlib
import os
import sys


def load_settings(env_vars):
    # Clear cached modules
    for mod in [m for m in list(sys.modules) if m.startswith('config.settings')]:
        del sys.modules[mod]
    for key, value in env_vars.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    from config.settings import base as settings
    return settings


def test_database_uses_url():
    settings = load_settings({'DATABASE_URL': 'postgres://u:p@h:5432/db'})
    db = settings.DATABASES['default']
    assert db['NAME'] == 'db'
    assert db['USER'] == 'u'
    assert db['HOST'] == 'h'
    assert db['OPTIONS']['sslmode'] == 'require'


def test_database_uses_individual_settings():
    settings = load_settings({
        'DATABASE_URL': None,
        'DB_NAME': 'pagasys',
        'DB_USER': 'user',
        'DB_PASSWORD': 'pass',
        'DB_HOST': 'host',
        'DB_PORT': '5433',
    })
    db = settings.DATABASES['default']
    assert db['NAME'] == 'pagasys'
    assert db['PORT'] == '5433'
    assert db['OPTIONS']['sslmode'] == 'require'


def test_database_defaults_port_5432():
    settings = load_settings({
        'DATABASE_URL': None,
        'DB_NAME': 'pagasys',
        'DB_USER': 'user',
        'DB_PASSWORD': 'pass',
        'DB_HOST': 'host',
        'DB_PORT': None,
    })
    db = settings.DATABASES['default']
    assert db['PORT'] == '5432'
