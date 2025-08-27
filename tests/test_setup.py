from pathlib import Path
import yaml


def test_entrypoint_exists():
    entrypoint = Path('entrypoint.sh')
    assert entrypoint.exists(), 'entrypoint.sh should exist'
    content = entrypoint.read_text()
    assert 'RUN_MIGRATIONS' not in content, 'entrypoint should not run migrations'
    assert 'exec "$@"' in content, 'entrypoint should forward commands'


def test_predeploy_hook_runs_migrations():
    hook = Path('.platform/hooks/predeploy/10_run_migrations.sh')
    assert hook.exists(), 'predeploy hook should exist'
    content = hook.read_text()
    expected = 'docker-compose run --rm web python manage.py migrate --noinput'
    assert expected in content, 'hook should run migrations via docker-compose'
    assert 'RDS_HOSTNAME' in content, 'hook should construct DATABASE_URL from RDS vars'


def test_cmd_uses_port_env():
    dockerfile = Path('Dockerfile').read_text()
    assert '${PORT:-8000}' in dockerfile, 'Dockerfile CMD should use PORT env'


def test_docker_compose_uses_entrypoint():
    for fname in ['docker-compose.local.yml', 'docker-compose.eb.yml']:
        data = yaml.safe_load(Path(fname).read_text())
        assert 'command' not in data['services']['web'], (
            f'web service in {fname} should rely on image CMD'
        )


def test_requirements_pinned():
    req_txt = Path('requirements.txt').read_text().splitlines()
    assert any(line.startswith('gunicorn==') for line in req_txt), 'gunicorn must be pinned'
    assert any(line.startswith('whitenoise==') for line in req_txt), 'whitenoise must be pinned'
    # ensure sub dependency present
    assert any(line.startswith('asgiref==') for line in req_txt), 'sub dependencies should be pinned'


def test_whitenoise_configured():
    settings = Path('config/settings/base.py').read_text()
    assert 'whitenoise.middleware.WhiteNoiseMiddleware' in settings, 'whitenoise middleware missing'
    assert 'STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"' in settings
