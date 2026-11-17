"""Runs Tileminal with a scripted scenario; started by test_ui.py on a headless display.

    python3 driver.py SCENARIO

A scenario is a generator: it does something, then yields a ``Wait`` for what has to happen
before it continues. There are no fixed sleeps: every wait names its condition and fails with
that name when it takes too long. Results are printed as ``RESULT {json}`` lines.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from tileminal._gi import Gdk, GLib, Gtk  # noqa: E402
from tileminal.app import Application  # noqa: E402
from tileminal.layout import Split  # noqa: E402
from tileminal.pane import Pane  # noqa: E402
from tileminal.session_files import load_session_file  # noqa: E402
from tileminal.window import TerminalWindow  # noqa: E402

POLL_MS = 50
TIMEOUT_SECONDS = 15.0
# GLib's "call me again" / "stop calling me" for timeouts, as plain booleans mypy can check
KEEP_POLLING, STOP_POLLING = True, False


@dataclass
class Wait:
    """Continue once ``condition`` holds; fail the scenario after ``timeout`` seconds."""

    what: str
    condition: Callable[[], bool]
    timeout: float = TIMEOUT_SECONDS
    started: float = field(default_factory=time.monotonic)


Scenario = Callable[[Application], Iterator[Wait]]
SCENARIOS: dict[str, Scenario] = {}
# Synthetic events must stay alive while GTK uses them
_events: list[Gdk.Event] = []


def scenario(function: Scenario) -> Scenario:
    SCENARIOS[function.__name__] = function
    return function


def report(**values: Any) -> None:
    print('RESULT ' + json.dumps(values), flush=True)


# --- what the app looks like


def tree(node: dict[str, Any]) -> Any:
    """A saved layout reduced to what the tests compare: pane ids, orientations and ratios."""
    if node['type'] == 'Terminal':
        return node['uuid']
    return [node['orientation'], round(node['ratio'], 2), tree(node['child1']), tree(node['child2'])]


def layouts(app: Application) -> list[list[Any]]:
    """Every window's tabs, as trees; windows sorted so their order does not matter."""
    windows = [[tree(tab['child']) for tab in window['tabs']] for window in app.serialize()['windows']]
    return sorted(windows, key=json.dumps)


def closed(app: Application) -> list[str]:
    return [entry['kind'] for entry in app.closed]


def first(app: Application) -> TerminalWindow:
    return app.windows()[0]


def panes(window: TerminalWindow) -> list[Pane]:
    tab = window.current_tab()
    assert tab is not None
    return tab.panes()


def splits(widget: Gtk.Widget | None) -> list[Split]:
    if not isinstance(widget, Split):
        return []
    return [widget, *splits(widget.get_child1()), *splits(widget.get_child2())]


def settled(app: Application) -> bool:
    """Every shell is running, and the visible tabs are laid out with their split ratios applied."""
    for window in app.windows():
        for tab in window.tabs():
            if any(pane.child_pid is None for pane in tab.panes()):
                return False
        current = window.current_tab()
        if current is None or any(not pane.get_mapped() for pane in current.panes()):
            return False
        if any(split.pending_ratio is not None for split in splits(current.root)):
            return False
    return bool(app.windows())


def until_settled(app: Application) -> Wait:
    return Wait('the shells to start and the panes to be laid out', lambda: settled(app))


def three_panes(window: TerminalWindow) -> None:
    """One pane on the left, two stacked on the right."""
    window.split(window.active_pane(), Gtk.Orientation.HORIZONTAL)
    window.split(window.active_pane(), Gtk.Orientation.VERTICAL)


def logout(app: Application) -> None:
    """What happens when the desktop session ends."""
    app.on_signal()


# --- restore


@scenario
def restore_save(app: Application) -> Iterator[Wait]:
    window = first(app)
    three_panes(window)
    window.add_tab(cwd='/usr')
    window.notebook.set_current_page(0)
    yield until_settled(app)

    pane = panes(window)[0]
    pane.term.feed_child(b'cd /tmp\n')
    root = window.tabs()[0].root
    assert isinstance(root, Split)
    root.set_position(round(root.span() * 0.3))
    yield Wait('the shell to change to /tmp', lambda: pane.cwd() == '/tmp')

    app.save_now()
    report(layouts=layouts(app), directories=[each.cwd() for each in panes(window)])
    logout(app)


@scenario
def restore_load(app: Application) -> Iterator[Wait]:
    window = first(app)
    report(layouts=layouts(app), directories=[pane.cwd() for pane in panes(window)])
    count = len(panes(window))
    panes(window)[-1].term.feed_child(b'exit\n')
    yield Wait('the pane of the exited shell to close', lambda: len(panes(window)) == count - 1)
    report(after_exit=layouts(app))
    logout(app)


# --- closing


@scenario
def close_pane_then_window(app: Application) -> Iterator[Wait]:
    window = first(app)
    three_panes(window)
    yield until_settled(app)
    window.close_pane(panes(window)[2])
    report(layouts=layouts(app), closed=closed(app))
    # The last window still has a split: quitting this way keeps it
    window.close()


@scenario
def close_plain_window(app: Application) -> Iterator[Wait]:
    window = first(app)
    for pane in panes(window)[1:]:
        window.close_pane(pane)
    report(panes_left=len(panes(window)))
    window.close()
    yield from ()


@scenario
def report_state(app: Application) -> Iterator[Wait]:
    report(layouts=layouts(app), closed=closed(app))
    logout(app)
    yield from ()


@scenario
def reopen(app: Application) -> Iterator[Wait]:
    window = first(app)
    window.add_tab(cwd='/usr')
    three_panes(window)
    yield until_settled(app)
    before = layouts(app)
    tab = window.current_tab()
    assert tab is not None
    window.close_tab(tab)
    report(before=before, after_close=layouts(app), closed=closed(app))
    app.reopen()
    report(after_reopen=layouts(app), closed=closed(app))
    logout(app)


# --- quitting


@scenario
def quit_all(app: Application) -> Iterator[Wait]:
    three_panes(first(app))
    app.new_window(cwd='/usr')
    yield until_settled(app)
    report(layouts=layouts(app))
    app.activate_action('quit', None)


@scenario
def dock_quit(app: Application) -> Iterator[Wait]:
    three_panes(first(app))
    app.new_window(cwd='/usr')
    app.new_window(cwd='/etc')
    yield until_settled(app)
    report(layouts=layouts(app))
    # The dock's "Quit" closes the windows one after another
    for window in list(app.windows()):
        window.close()


# --- rearranging


def button_event(kind: Gdk.EventType, widget: Gtk.Widget, window: TerminalWindow, x: int, y: int) -> Any:
    event = Gdk.Event.new(kind)
    _events.append(event)
    detail = event.motion if kind == Gdk.EventType.MOTION_NOTIFY else event.button
    local_x, local_y = window.translate_coordinates(widget, x, y)
    _, origin_x, origin_y = widget.get_window().get_origin()
    detail.type = kind
    detail.x, detail.y = float(local_x), float(local_y)
    detail.x_root, detail.y_root = float(origin_x + local_x), float(origin_y + local_y)
    if kind != Gdk.EventType.MOTION_NOTIFY:
        detail.button = 1
    return detail


def drag(window: TerminalWindow, source: Pane, target: Pane, fraction_x: float, fraction_y: float) -> None:
    """Press on the source's title row, move over the target, release - like a user would."""
    header = source.header
    start_x, start_y = header.translate_coordinates(window, 20, 5)
    left, top = target.body.translate_coordinates(window, 0, 0)
    x = int(left + target.body.get_allocated_width() * fraction_x)
    y = int(top + target.body.get_allocated_height() * fraction_y)
    header.on_press(header, button_event(Gdk.EventType.BUTTON_PRESS, header, window, start_x, start_y))
    header.on_motion(header, button_event(Gdk.EventType.MOTION_NOTIFY, header, window, (start_x + x) // 2, y))
    header.on_motion(header, button_event(Gdk.EventType.MOTION_NOTIFY, header, window, x, y))
    header.on_release(header, button_event(Gdk.EventType.BUTTON_RELEASE, header, window, x, y))


@scenario
def drag_panes(app: Application) -> Iterator[Wait]:
    window = first(app)
    three_panes(window)
    yield until_settled(app)
    report(start=layouts(app))
    left, top_right, bottom_right = panes(window)

    drag(window, top_right, bottom_right, 0.5, 0.5)
    report(swapped=layouts(app))
    # Each drag needs the panes where the previous one put them
    yield until_settled(app)
    drag(window, bottom_right, top_right, 0.9, 0.5)
    report(side_by_side=layouts(app))
    yield until_settled(app)
    drag(window, left, top_right, 0.5, 0.95)
    report(below=layouts(app))
    yield until_settled(app)

    header = panes(window)[0].header
    x, y = header.translate_coordinates(window, 20, 5)
    header.on_press(header, button_event(Gdk.EventType.BUTTON_PRESS, header, window, x, y))
    header.on_release(header, button_event(Gdk.EventType.BUTTON_RELEASE, header, window, x, y))
    tab = window.current_tab()
    assert tab is not None
    report(title_click_focuses=tab.active_pane is panes(window)[0])
    logout(app)


def press_keys(window: TerminalWindow, name: str, modifiers: Gdk.ModifierType) -> bool:
    event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    _events.append(event)
    event.keyval = Gdk.keyval_from_name(name)
    event.state = modifiers
    return bool(window.on_key_press(window, event))


@scenario
def shortcuts(app: Application) -> Iterator[Wait]:
    window = first(app)
    ctrl, shift, alt = Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK, Gdk.ModifierType.MOD1_MASK

    def counts() -> list[int]:
        return [len(tab.panes()) for tab in window.tabs()]

    results: dict[str, Any] = {}
    results['split'] = [press_keys(window, 'E', ctrl | shift), press_keys(window, 'O', ctrl | shift), counts()]
    # Moving focus by direction needs the panes laid out
    yield until_settled(app)
    focused = window.active_pane()
    press_keys(window, 'Left', alt)
    results['alt_left_moves'] = window.active_pane() is not focused
    results['new_tab'] = [press_keys(window, 'T', ctrl | shift), counts()]
    results['previous_tab'] = [press_keys(window, 'Page_Up', ctrl), window.notebook.get_current_page()]
    results['close'] = [press_keys(window, 'W', ctrl | shift), counts()]
    pane = window.active_pane()
    assert pane is not None
    press_keys(window, 'plus', ctrl)
    results['zoom'] = round(pane.font_scale, 2)
    press_keys(window, '0', ctrl)
    results['zoom_reset'] = pane.font_scale
    results['typing_passes_through'] = press_keys(window, 'e', Gdk.ModifierType(0))
    report(**results)
    logout(app)


# --- session files


@scenario
def session_file(app: Application) -> Iterator[Wait]:
    window = first(app)
    three_panes(window)
    tab = window.current_tab()
    assert tab is not None
    path = Path(os.environ['XDG_STATE_HOME']) / 'tab.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tab.to_data(with_size=True)))
    load_session_file(window, str(path))
    saved, loaded = layouts(app)[0]
    report(tabs=len(window.tabs()), same_shape=json.dumps(shape(saved)) == json.dumps(shape(loaded)))
    # Quitting while shells are still starting is not what this test is about
    yield until_settled(app)
    logout(app)


def shape(node: Any) -> Any:
    """A tree without pane ids, which are new for every loaded file."""
    return [node[0], node[1], shape(node[2]), shape(node[3])] if isinstance(node, list) else 'pane'


# --- running


def run(app: Application, steps: Iterator[Wait]) -> None:
    """Advance the scenario whenever the condition it waits for holds."""
    waiting: list[Wait] = []

    def fail(message: str) -> bool:
        report(error=message)
        app.on_signal()
        return STOP_POLLING

    def poll() -> bool:
        try:
            while True:
                if waiting:
                    wait = waiting[0]
                    if not wait.condition():
                        if time.monotonic() - wait.started > wait.timeout:
                            return fail(f'timed out after {wait.timeout:.0f} s waiting for {wait.what}')
                        return KEEP_POLLING
                    waiting.clear()
                try:
                    waiting.append(next(steps))
                except StopIteration:
                    return STOP_POLLING
        except Exception as e:
            # A broken scenario ends the run right away instead of leaving the app open
            return fail(f'{type(e).__name__}: {e}')

    GLib.timeout_add(POLL_MS, poll)


def describe(app: Application) -> str:
    """What the app looks like, for a failure message."""
    windows = app.windows()
    all_panes = [pane for window in windows for tab in window.tabs() for pane in tab.panes()]
    running = sum(pane.child_pid is not None for pane in all_panes)
    return f'{len(windows)} windows, {len(all_panes)} panes, {running} shells running'


def main() -> int:
    app = Application()
    steps = SCENARIOS[sys.argv[1]]
    started = False
    last_seen = 'nothing yet'

    def start() -> bool:
        nonlocal started, last_seen
        last_seen = describe(app)
        if not settled(app):
            return KEEP_POLLING
        started = True
        run(app, steps(app))
        return STOP_POLLING

    def on_shutdown(_app: Application) -> None:
        if not started:
            report(error=f'the app ended before the scenario started; it had {last_seen}')

    # Every scenario starts with the restored (or new) windows ready
    GLib.timeout_add(POLL_MS, start)
    app.connect('shutdown', on_shutdown)
    return int(app.run(sys.argv[:1]))


if __name__ == '__main__':
    sys.exit(main())
