import subprocess
import sys
from textwrap import dedent


def run_flake8(code: str):
    process = subprocess.run(
        [sys.executable, "-m", "flake8", "-"],
        input=code,
        text=True,
        capture_output=True,
    )
    return process.returncode, process.stdout.strip()


def test_datetime_now_flagged():
    code = dedent(
        """
        import datetime
        datetime.datetime.now()
        """
    )
    rc, output = run_flake8(code)
    assert rc == 1
    assert "TZ001" in output


def test_date_today_flagged():
    code = dedent(
        """
        from datetime import date
        date.today()
        """
    )
    rc, output = run_flake8(code)
    assert rc == 1
    assert "TZ003" in output


def test_timezone_now_allowed():
    code = dedent(
        """
        from django.utils import timezone
        timezone.now()
        """
    )
    rc, output = run_flake8(code)
    assert rc == 0
    assert output == ""
