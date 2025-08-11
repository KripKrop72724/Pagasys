from pathlib import Path
import yaml


def load_compose(path: str):
    return yaml.safe_load(Path(path).read_text())


def test_compose_files_no_version():
    for fname in ["docker-compose.local.yml", "docker-compose.eb.yml"]:
        text = Path(fname).read_text().lstrip()
        assert not text.startswith("version:"), f"{fname} should omit version key"


def test_local_compose_contains_postgres():
    data = load_compose("docker-compose.local.yml")
    assert "postgres" in data["services"], "local compose must define postgres"
    postgres = data["services"]["postgres"]
    assert any(v.startswith("postgres_data:") for v in postgres.get("volumes", [])), "postgres volume missing"
    hc = postgres.get("healthcheck")
    assert hc and "test" in hc, "postgres healthcheck missing"


def test_eb_compose_has_only_web():
    data = load_compose("docker-compose.eb.yml")
    assert list(data["services"].keys()) == ["web"], "EB compose should define only web service"
    assert "postgres" not in data["services"], "EB compose must not include postgres"


def test_web_healthcheck_uses_healthz():
    for fname in ["docker-compose.local.yml", "docker-compose.eb.yml"]:
        data = load_compose(fname)
        hc = data["services"]["web"]["healthcheck"]
        test_cmd = hc.get("test")
        target = test_cmd[-1] if isinstance(test_cmd, list) else test_cmd
        assert "healthz" in target, f"web healthcheck in {fname} should target /healthz"
