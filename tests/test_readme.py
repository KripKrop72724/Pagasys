from pathlib import Path


def test_readme_mentions_healthz():
    readme = Path('README.md').read_text()
    assert '/healthz' in readme


def test_readme_mentions_exposed_port():
    readme = Path('README.md').read_text().lower()
    assert 'exposes this port' in readme or 'expose 8000' in readme
