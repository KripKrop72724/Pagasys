import re
from pathlib import Path

def test_multi_stage_build():
    dockerfile = Path('Dockerfile').read_text().lower()
    # should define a builder and runtime stage
    assert dockerfile.count('from') >= 2, 'Dockerfile should use multi-stage build'
    assert 'as builder' in dockerfile, 'builder stage missing'
    assert 'copy --from=builder' in dockerfile, 'runtime stage should copy from builder'


def test_dockerignore_entries():
    dockerignore = Path('.dockerignore').read_text().splitlines()
    required = {'venv/', '.venv/', '__pycache__/', '.git/', '.env', 'node_modules/'}
    found = {line.strip() for line in dockerignore}
    for item in required:
        assert item in found, f".dockerignore missing {item}"
