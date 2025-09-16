from pathlib import Path

import yaml
from django.core.management import call_command


def test_openapi_schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", "--file", str(out))
    generated = yaml.safe_load(out.read_text())
    expected = yaml.safe_load(Path(__file__).with_name("openapi.yaml").read_text())

    path_to_ignore = "/api/companies/{company_id}/roster/schedule-range/"
    generated_paths = generated.get("paths", {})
    expected_paths = expected.get("paths", {})
    generated_paths.pop(path_to_ignore, None)
    expected_paths.pop(path_to_ignore, None)

    assert generated == expected
