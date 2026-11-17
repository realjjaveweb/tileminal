"""The oldest supported Python version is set by ``requires-python``; every tool setting that repeats
it has to agree, so raising the minimum can't be done halfway."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = (ROOT / 'pyproject.toml').read_text()


def setting(pattern: str, text: str = PYPROJECT) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f'not found: {pattern}'
    return match.group(1)


def minimum() -> str:
    """The version from ``requires-python = ">=3.x"``."""
    return setting(r'^requires-python = ">=(3\.\d+)"')


def test_formatter_targets_the_minimum() -> None:
    assert setting(r'^target-version = \["py3(\d+)"\]') == minimum().split('.')[1]


def test_type_checker_checks_against_the_minimum() -> None:
    assert setting(r'^python_version = "(3\.\d+)"') == minimum()


def test_ci_tests_the_minimum() -> None:
    workflow = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
    versions = re.findall(r'"(3\.\d+)"', setting(r'^\s*python: \[(.*)\]', workflow))
    oldest = min(versions, key=lambda version: int(version.split('.')[1]))
    assert oldest == minimum()
