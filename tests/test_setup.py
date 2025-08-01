from pathlib import Path


def test_entrypoint_exists():
    entrypoint = Path('entrypoint.sh')
    assert entrypoint.exists(), 'entrypoint.sh should exist'
    content = entrypoint.read_text()
    assert 'gunicorn' in content, 'entrypoint should run gunicorn'


def test_entrypoint_uses_port_env():
    content = Path('entrypoint.sh').read_text()
    assert '--bind 0.0.0.0:${PORT:-8000}' in content


def test_docker_compose_uses_entrypoint():
    compose = Path('docker-compose.yml').read_text()
    assert '/entrypoint.sh' in compose, 'docker-compose should call entrypoint.sh'


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

