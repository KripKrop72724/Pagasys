import os
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
def _django_test_env(docker_services):
    docker_services.start("postgres")
    port = docker_services.port_for("postgres", 5432)
    docker_services.wait_until_responsive(timeout=30.0, pause=0.5, check=lambda: wait_for_port(port))

    db_url = f"postgresql://pagasys:pagasys@localhost:{port}/pagasys"
    os.environ["DATABASE_URL"] = db_url
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["DEBUG"] = "True"
    os.environ["ALLOWED_HOSTS"] = "localhost"
