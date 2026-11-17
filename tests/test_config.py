import json
from pathlib import Path

import pytest

from tileminal.config import COLOR_SCHEMES, DEFAULTS, Config


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / 'tileminal' / 'config.json'


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_first_start_writes_the_defaults(path: Path) -> None:
    config = Config(path)
    assert json.loads(path.read_text()) == DEFAULTS
    assert config['scrollback_lines'] == DEFAULTS['scrollback_lines']


def test_user_values_win_and_missing_ones_default(path: Path) -> None:
    write(path, '{"scrollback_lines": 500}')
    config = Config(path)
    assert config['scrollback_lines'] == 500
    assert config['cursor_shape'] == DEFAULTS['cursor_shape']


def test_broken_file_is_left_alone(path: Path) -> None:
    write(path, '{"scrollback_lines": ')
    assert Config(path)['scrollback_lines'] == DEFAULTS['scrollback_lines']
    assert path.read_text() == '{"scrollback_lines": '


def test_get_int(path: Path) -> None:
    write(path, '{"scrollback_lines": "many", "closed_history": -5, "session_history": "7"}')
    config = Config(path)
    assert config.get_int('scrollback_lines') == DEFAULTS['scrollback_lines']
    assert config.get_int('closed_history') == 0
    assert config.get_int('session_history', 1) == 7


@pytest.mark.parametrize('name', ['dark', 'light'])
def test_built_in_schemes(path: Path, name: str) -> None:
    write(path, json.dumps({'color_scheme': name}))
    assert Config(path).color_scheme() == COLOR_SCHEMES[name]


def test_unknown_scheme_falls_back_to_dark(path: Path) -> None:
    write(path, '{"color_scheme": "unknown"}')
    assert Config(path).color_scheme() == COLOR_SCHEMES['dark']


def test_own_scheme_is_completed_from_the_default(path: Path) -> None:
    write(path, '{"color_scheme": {"background": "#000000", "palette": ["#111111"]}}')
    scheme = Config(path).color_scheme()
    assert scheme['background'] == '#000000'
    assert scheme['foreground'] == COLOR_SCHEMES['dark']['foreground']
    assert scheme['palette'] == COLOR_SCHEMES['dark']['palette']
