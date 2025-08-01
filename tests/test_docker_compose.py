from pathlib import Path
import yaml


def load_compose():
    return yaml.safe_load(Path('docker-compose.yml').read_text())


def test_compose_version_defined():
    compose_text = Path('docker-compose.yml').read_text().lstrip()
    assert compose_text.startswith('version:'), 'docker-compose version missing'


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
