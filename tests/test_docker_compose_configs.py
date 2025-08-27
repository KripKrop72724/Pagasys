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


def test_eb_compose_services():
    data = load_compose("docker-compose.eb.yml")
    assert set(data["services"].keys()) == {"caddy", "web", "redis", "worker"}, (
        "EB compose should define caddy, web, redis and worker services"
    )
    assert "postgres" not in data["services"], "EB compose must not include postgres"


def test_web_healthcheck_uses_healthz():
    for fname in ["docker-compose.local.yml", "docker-compose.eb.yml"]:
        data = load_compose(fname)
        hc = data["services"]["web"]["healthcheck"]
        test_cmd = hc.get("test")
        target = test_cmd[-1] if isinstance(test_cmd, list) else test_cmd
        assert "healthz" in target, f"web healthcheck in {fname} should target /healthz"


def extract_env(service):
    env = service.get("environment", {})
    if isinstance(env, list):
        return {item.split("=", 1)[0]: item.split("=", 1)[1] if "=" in item else None for item in env}
    return env


def test_migration_flag_and_commands():
    for fname in ["docker-compose.local.yml", "docker-compose.eb.yml"]:
        data = load_compose(fname)
        web = data["services"]["web"]
        worker = data["services"]["worker"]

        assert "command" not in web, f"web service in {fname} should use default CMD"
        web_env = extract_env(web)
        if fname.endswith("local.yml"):
            assert web_env.get("RUN_MIGRATIONS") == "1", f"web in {fname} must set RUN_MIGRATIONS=1"
        else:
            assert web_env.get("RUN_MIGRATIONS") in (None, "0"), f"web in {fname} must not enable migrations"

        worker_env = extract_env(worker)
        assert "RUN_MIGRATIONS" not in worker_env, f"worker in {fname} must not set RUN_MIGRATIONS"
        cmd = worker.get("command", "")
        assert str(cmd).startswith("celery"), f"worker command in {fname} should start with celery"
