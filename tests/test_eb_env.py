import json
import subprocess
import sys

import pytest

from scripts.eb_env import generate_option_settings


def test_generate_option_settings_happy_path(monkeypatch):
    url = "postgres://u:p@h:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    result = generate_option_settings(["DATABASE_URL"])
    assert result == [
        {
            "Namespace": "aws:elasticbeanstalk:application:environment",
            "OptionName": "DATABASE_URL",
            "Value": url,
        }
    ]


def test_generate_option_settings_missing_variable(monkeypatch):
    monkeypatch.delenv("DB_HOST", raising=False)
    with pytest.raises(KeyError):
        generate_option_settings(["DB_HOST"])


def test_generate_option_settings_invalid_name(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    with pytest.raises(ValueError):
        generate_option_settings(["1INVALID", "DB_HOST"])


def test_generate_option_settings_duplicate_and_empty_value(monkeypatch):
    monkeypatch.setenv("DB_PASS", "")
    monkeypatch.setenv("DB_PASS", "")
    result = generate_option_settings(["DB_PASS", "DB_PASS"])
    assert result == [
        {
            "Namespace": "aws:elasticbeanstalk:application:environment",
            "OptionName": "DB_PASS",
            "Value": "",
        }
    ]


def test_generate_option_settings_empty_name():
    with pytest.raises(ValueError):
        generate_option_settings(["", "DB_HOST"])


def test_cli_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_USER", "admin with spaces")
    out_file = tmp_path / "env.json"
    cmd = [
        sys.executable,
        "-m",
        "scripts.eb_env",
        "--names",
        "DB_USER",
        "--output",
        str(out_file),
    ]
    assert (
        subprocess.run(cmd, check=False).returncode == 0
    ), "CLI should exit with code 0"
    with open(out_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data == [
        {
            "Namespace": "aws:elasticbeanstalk:application:environment",
            "OptionName": "DB_USER",
            "Value": "admin with spaces",
        }
    ]
