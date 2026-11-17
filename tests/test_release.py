"""The version number lives in the package; the release notes and app metadata have to match it."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from tileminal import APP_ID, __version__

ROOT = Path(__file__).resolve().parent.parent


def test_changelog_has_the_current_version() -> None:
    headings = re.findall(r'^## (\S+)', (ROOT / 'CHANGELOG.md').read_text(), re.MULTILINE)
    assert headings[0] == __version__


def test_app_metadata_lists_the_current_version() -> None:
    metainfo = ET.parse(ROOT / 'data' / f'{APP_ID}.metainfo.xml').getroot()
    assert metainfo.findtext('id') == APP_ID
    releases = [release.get('version') for release in metainfo.iter('release')]
    assert releases[0] == __version__


def test_data_files_are_named_after_the_app_id() -> None:
    for suffix in ('.desktop', '.svg', '.metainfo.xml'):
        assert (ROOT / 'data' / f'{APP_ID}{suffix}').exists()
