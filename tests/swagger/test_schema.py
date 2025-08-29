import io
from pathlib import Path
from django.core.management import call_command


def test_openapi_schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", "--file", str(out))
    generated = out.read_text()
    expected = Path(__file__).with_name("openapi.yaml").read_text()
    assert generated == expected
