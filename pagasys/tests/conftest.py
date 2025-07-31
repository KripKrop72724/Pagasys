import socket
import pytest


def wait_for_port(port: int) -> bool:
    s = socket.socket()
    try:
        s.connect(("localhost", port))
    except OSError:
        return False
    else:
        s.close()
        return True


@pytest.fixture(scope="session", autouse=True)
def _django_test_env(monkeypatch, docker_services):
    docker_services.start("postgres")
    port = docker_services.port_for("postgres", 5432)
    docker_services.wait_until_responsive(timeout=30.0, pause=0.5, check=lambda: wait_for_port(port))

    db_url = f"postgresql://pagasys:pagasys@localhost:{port}/pagasys"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DEBUG", "True")
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost")
