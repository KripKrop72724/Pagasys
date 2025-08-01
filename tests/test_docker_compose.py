from pathlib import Path
import yaml


def load_compose():
    return yaml.safe_load(Path('docker-compose.yml').read_text())


def test_compose_version_removed():
    compose_text = Path('docker-compose.yml').read_text().lstrip()
    assert not compose_text.startswith('version:'), 'docker-compose version should be removed'


def test_postgres_volume_mounted():
    data = load_compose()
    postgres = data['services']['postgres']
    assert 'volumes' in postgres, 'postgres service should mount a volume'
    assert any(v.startswith('postgres_data:') for v in postgres['volumes']), 'postgres volume mount incorrect'
    assert 'postgres_data' in data.get('volumes', {}), 'named volume not defined'


def test_healthchecks_present():
    data = load_compose()
    for service in ['web', 'postgres']:
        hc = data['services'][service].get('healthcheck')
        assert hc is not None, f'healthcheck missing for {service}'
        assert 'test' in hc, 'healthcheck missing test command'


def test_web_healthcheck_uses_healthz():
    data = load_compose()
    hc = data['services']['web']['healthcheck']
    test_cmd = hc.get('test')
    if isinstance(test_cmd, list):
        target = test_cmd[-1]
    else:
        target = test_cmd
    assert 'healthz' in target, 'web healthcheck should target /healthz'
