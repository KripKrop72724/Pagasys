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
    required = {
        'venv/',
        '.venv/',
        '__pycache__/',
        '.git/',
        '.env',
        'node_modules/',
        '.vscode/',
        '.idea/',
        'coverage/',
        'htmlcov/',
        '.pytest_cache/',
    }
    found = {line.strip() for line in dockerignore}
    for item in required:
        assert item in found, f".dockerignore missing {item}"


def test_dockerfile_not_ignored():
    dockerignore = Path('.dockerignore').read_text().splitlines()
    assert 'Dockerfile' not in {line.strip() for line in dockerignore}, (
        'Dockerfile should not be ignored in .dockerignore'
    )
