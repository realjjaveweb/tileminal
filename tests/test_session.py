import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from tileminal.session import SESSION_FORMAT, SESSION_VERSION, Session, SessionStore, valid_closed, validate_session


def terminal(directory: str = '/tmp') -> dict[str, Any]:
    return {'type': 'Terminal', 'uuid': 'pane', 'directory': directory}


def tab(child: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'type': 'Session', 'uuid': 'tab', 'name': '${title}', 'version': '1.0', 'child': child or terminal()}


def session(*directories: str) -> Session:
    tabs = [tab(terminal(d)) for d in directories] or [tab()]
    return {'format': SESSION_FORMAT, 'version': SESSION_VERSION, 'windows': [{'tabs': tabs}], 'closed': []}


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path, keep=3)


def reload(store: SessionStore) -> Session | None:
    return SessionStore(store.dir).load()


def test_complete_session_is_valid() -> None:
    validate_session(session('/tmp'))


def test_session_without_windows_is_valid() -> None:
    validate_session({'format': SESSION_FORMAT, 'windows': []})


@pytest.mark.parametrize(
    'data',
    [
        None,
        [],
        {'format': 'other', 'windows': []},
        {'format': SESSION_FORMAT},
        {'format': SESSION_FORMAT, 'windows': [{'tabs': []}]},
    ],
)
def test_invalid_sessions(data: Any) -> None:
    with pytest.raises(ValueError):
        validate_session(data)


def test_valid_closed_drops_damaged_entries() -> None:
    good = {'id': '1', 'kind': 'pane', 'label': 'api', 'closedAt': 5, 'data': terminal()}
    entries = [
        good,
        {'id': '2', 'kind': 'pane', 'label': 'x', 'data': {'type': 'Unknown'}},
        {'id': '3', 'kind': 'teleporter', 'label': 'x', 'data': {}},
        {'kind': 'tab', 'label': 'no id', 'data': tab()},
        'not an entry',
    ]
    assert valid_closed(entries) == [good]
    assert valid_closed(None) == []


def test_save_and_load(store: SessionStore) -> None:
    assert store.save(session('/srv'))
    assert reload(store) == session('/srv')


def test_unchanged_session_is_not_written_again(store: SessionStore) -> None:
    store.save(session('/srv'))
    assert not store.save(session('/srv'))
    assert store.history() == []


def test_previous_versions_go_to_history(store: SessionStore) -> None:
    for directory in ('/a', '/b', '/c'):
        store.save(session(directory))
    assert [json.loads(path.read_text()) for path in store.history()] == [session('/a'), session('/b')]


def test_history_is_pruned(store: SessionStore) -> None:
    for index in range(10):
        store.save(session(f'/dir{index}'))
    assert len(store.history()) == 3


def test_damaged_session_falls_back_to_history(store: SessionStore) -> None:
    store.save(session('/good'))
    store.save(session('/newer'))
    store.path.write_text('{"format": "tileminal-session", "windows": [')
    assert reload(store) == session('/good')


def test_nothing_saved_yet(store: SessionStore) -> None:
    assert store.load() is None


def test_invalid_session_is_never_written(store: SessionStore) -> None:
    store.save(session('/good'))
    with pytest.raises(ValueError):
        store.save({'format': SESSION_FORMAT, 'windows': [{'tabs': []}]})
    assert reload(store) == session('/good')


def test_failed_write_keeps_the_previous_session(store: SessionStore) -> None:
    store.save(session('/good'))
    with mock.patch('tileminal.session.write_verified', side_effect=OSError('disk full')), pytest.raises(OSError):
        store.save(session('/lost'))
    assert reload(store) == session('/good')
    assert [path.name for path in store.dir.iterdir() if '.tmp-' in path.name] == []
