"""Tileminal itself, run on a headless GTK display (Broadway).

Each test starts the app once or several times with scenarios from driver.py, sharing one state
folder between the runs, the way a user would close and reopen it.

Tests run in parallel (``-n auto``) and never touch each other or the user's own setup: every test
has its own home, config, state, data and cache folders and a plain bash, every app start gets its
own D-Bus session, and every parallel worker its own display.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

DRIVER = Path(__file__).with_name('driver.py')

pytestmark = pytest.mark.skipif(
    not (shutil.which('broadwayd') and shutil.which('dbus-run-session')),
    reason='needs broadwayd (libgtk-3-bin) and dbus-run-session (dbus)',
)


# Each parallel worker (gw0, gw1, ...) takes display numbers from its own block, so two workers never try
# the same one at the same time
DISPLAYS_PER_WORKER = 4
FIRST_DISPLAY = 40


def display_in_use(number: int) -> bool:
    """Whether a display server answers on ``number``. A new server would take the number over
    instead of failing, so this has to be checked before starting one."""
    runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    path = Path(runtime) / f'broadway{number + 1}.socket'
    if not path.exists():
        return False
    with contextlib.closing(socket.socket(socket.AF_UNIX)) as connection:
        try:
            connection.connect(str(path))
        except OSError:
            return False  # left over from a server that is gone
    return True


def start_display() -> tuple[subprocess.Popen[str], str]:
    """A headless display on a free number; returns once it accepts connections."""
    worker = int(os.environ.get('PYTEST_XDIST_WORKER', 'gw0').removeprefix('gw') or 0)
    first = FIRST_DISPLAY + worker * DISPLAYS_PER_WORKER
    for number in range(first, first + DISPLAYS_PER_WORKER):
        if display_in_use(number):
            continue
        server = subprocess.Popen(
            ['broadwayd', f':{number}'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        assert server.stdout is not None
        # It prints "Listening on ..." once it is ready, or exits when it can't start (e.g. a port in use)
        ready, _, _ = select.select([server.stdout], [], [], 10)
        if ready and server.stdout.readline().startswith('Listening on'):
            return server, str(number)
        server.kill()
        server.wait()
    raise RuntimeError(f'no free Broadway display number between {first} and {first + DISPLAYS_PER_WORKER - 1}')


@pytest.fixture(scope='module')
def display() -> Iterator[str]:
    server, number = start_display()
    yield number
    server.terminate()
    server.wait()


@pytest.fixture
def run(display: str, tmp_path: Path) -> Any:
    """Run a scenario; returns its RESULT lines merged into one dict."""

    def run_scenario(name: str) -> dict[str, Any]:
        home = tmp_path / 'home'
        home.mkdir(exist_ok=True)
        environment = dict(
            os.environ,
            GDK_BACKEND='broadway',
            BROADWAY_DISPLAY=f':{display}',
            # The shells in the test terminals must not read the user's shell setup or write to their history
            HOME=str(home),
            SHELL='/bin/bash',
            XDG_CONFIG_HOME=str(tmp_path / 'config'),
            XDG_STATE_HOME=str(tmp_path / 'state'),
            XDG_DATA_HOME=str(tmp_path / 'data'),
            XDG_CACHE_HOME=str(tmp_path / 'cache'),
        )
        result = subprocess.run(
            ['dbus-run-session', '--', sys.executable, str(DRIVER), name],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert 'Traceback' not in result.stderr, result.stderr
        values: dict[str, Any] = {}
        for line in result.stdout.splitlines():
            if line.startswith('RESULT '):
                values.update(json.loads(line[len('RESULT ') :]))
        assert 'error' not in values, f'{name}: {values["error"]}'
        # An app that ends before its scenario starts reports nothing; show how it ended instead
        assert values, f'{name}: no result, exit code {result.returncode}\n{result.stderr[-3000:]}'
        return values

    return run_scenario


def test_layout_and_directories_survive_a_logout(run: Any) -> None:
    saved = run('restore_save')
    restored = run('restore_load')
    assert restored['layouts'] == saved['layouts']
    assert restored['directories'] == saved['directories']
    assert '/tmp' in restored['directories']
    assert saved['layouts'][0][0][1] == 0.3
    # A shell that exits closes its pane
    assert len(json.dumps(restored['after_exit'])) < len(json.dumps(restored['layouts']))


def test_closing_rules(run: Any) -> None:
    closed_pane = run('close_pane_then_window')
    assert closed_pane['closed'] == ['pane']
    # Closing the last window with a split keeps it for the next start
    assert run('report_state')['layouts'] == closed_pane['layouts']
    # A last window with a single plain terminal starts fresh; it is in the closed list
    run('close_plain_window')
    fresh = run('report_state')
    assert len(fresh['layouts']) == 1
    assert isinstance(fresh['layouts'][0][0], str)
    assert fresh['closed'][0] == 'window'


def test_reopen_closed_tab(run: Any) -> None:
    result = run('reopen')
    assert result['closed'] == []
    assert len(result['after_close'][0]) == len(result['before'][0]) - 1
    assert result['after_reopen'] == result['before']


def test_quit_all_keeps_every_window(run: Any) -> None:
    quit_result = run('quit_all')
    assert run('report_state') == {'layouts': quit_result['layouts'], 'closed': []}


def test_dock_quit_keeps_every_window(run: Any) -> None:
    quit_result = run('dock_quit')
    assert len(quit_result['layouts']) == 3
    assert run('report_state') == {'layouts': quit_result['layouts'], 'closed': []}


def test_dragging_panes(run: Any) -> None:
    result = run('drag_panes')
    start: list[Any] = result['start'][0][0]
    left, (top_right, bottom_right) = start[2], start[3][2:]
    assert result['start'][0][0] == [0, 0.5, left, [1, 0.5, top_right, bottom_right]]
    assert result['swapped'][0][0] == [0, 0.5, left, [1, 0.5, bottom_right, top_right]]
    assert result['side_by_side'][0][0] == [0, 0.5, left, [0, 0.5, top_right, bottom_right]]
    # Taking the left pane out leaves the right column; it then goes below the top right pane
    assert result['below'][0][0] == [0, 0.5, [1, 0.5, top_right, left], bottom_right]
    assert result['title_click_focuses'] is True


def test_shortcuts(run: Any) -> None:
    result = run('shortcuts')
    assert result['split'] == [True, True, [3]]
    assert result['alt_left_moves'] is True
    assert result['new_tab'] == [True, [3, 1]]
    assert result['previous_tab'] == [True, 0]
    assert result['close'] == [True, [2, 1]]
    assert result['zoom'] == 1.1
    assert result['zoom_reset'] == 1.0
    assert result['typing_passes_through'] is False


def test_session_file_round_trip(run: Any) -> None:
    result = run('session_file')
    assert result == {'tabs': 2, 'same_shape': True}


def test_missing_desktop_schema_does_not_abort(tmp_path: Path) -> None:
    """GSettings aborts the whole process for an unknown schema instead of raising, so a system without the
    GNOME schemas (minimal installs, CI runners) must be handled before it is asked."""
    empty = tmp_path / 'empty'
    empty.mkdir()
    source = Path(__file__).resolve().parents[2] / 'src'
    code = (
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'from tileminal.style import desktop_setting; '
        "print(desktop_setting('monospace-font-name'), desktop_setting('no-such-key'))"
    )
    result = subprocess.run(
        [sys.executable, '-c', code, str(source)],
        env=dict(os.environ, XDG_DATA_DIRS=str(empty), XDG_DATA_HOME=str(empty), GSETTINGS_SCHEMA_DIR=str(empty)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'None None'
