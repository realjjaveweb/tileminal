"""The application: windows, the saved session and the recently closed list.

What gets restored on the next start:

* Logging out, rebooting, a crash, *Quit All* or the dock's *Quit*: everything.
* Closing the last window: that window, if it has splits or several tabs (a workspace);
  a single plain terminal starts fresh.
* Closing a pane, a tab or one of several windows: nothing; it goes to the recently closed list.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from tileminal import APP_ID, APP_NAME
from tileminal._gi import Gio, GLib, GLibUnix, Gtk
from tileminal.config import Config
from tileminal.files import HOME
from tileminal.i18n import _
from tileminal.layout import build_tree
from tileminal.pane import Pane
from tileminal.session import (
    SESSION_FORMAT,
    SESSION_VERSION,
    ClosedEntry,
    ClosedKind,
    Session,
    SessionStore,
    valid_closed,
)
from tileminal.session_files import load_session_file
from tileminal.style import apply_theme_variant, install_css
from tileminal.window import HORIZONTAL, TerminalWindow

logger = logging.getLogger(__name__)

# Windows closed within this time of each other belong to one "close everything" action
CLOSE_BURST_SECONDS = 2.0
# How long saving waits after shells were killed, which usually means the desktop is shutting down
SHUTDOWN_GRACE_SECONDS = 5


@dataclass
class CloseBurst:
    """Windows closing in quick succession, as the dock's *Quit* closes them one by one."""

    snapshot: Session
    last: float = field(default_factory=time.monotonic)
    count: int = 0
    closed_ids: list[str] = field(default_factory=list)


class Application(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name(APP_NAME)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.add_main_option(
            'fresh', 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, _('Start without restoring the last session'), None
        )
        self.add_main_option(
            'working-directory',
            ord('w'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            _('Open a new window in this directory'),
            'DIR',
        )
        self.add_main_option(
            'session',
            ord('s'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING_ARRAY,
            _('Open a session file as a tab (repeatable)'),
            'FILE',
        )
        self.config = Config()
        self.store = SessionStore(keep=self.config.get_int('session_history', 1))
        self.closed: list[ClosedEntry] = []
        self.started = False
        # Once frozen, nothing is saved any more: the app is quitting and the saved state is final
        self.frozen = False
        self.hold_until = 0.0
        self.burst: CloseBurst | None = None
        self._save_source: int | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        Gtk.IconTheme.get_default().append_search_path(str(resources.files('tileminal') / 'icons'))
        apply_theme_variant(self.config)
        install_css()

        reopen = Gio.SimpleAction.new('reopen', GLib.VariantType.new('s'))
        reopen.connect('activate', lambda _action, value: self.reopen(value.get_string()))
        self.add_action(reopen)
        for name, callback in {
            'new-window': self.new_window,
            'clear-closed': self.clear_closed,
            'open-config': self.open_config,
            'reload-config': self.reload_config,
            # The desktop's "Quit" for the app (e.g. on the dock icon) activates this action too
            'quit': self.quit_all,
        }.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _action, _param, cb=callback: cb())
            self.add_action(action)

        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            if GLibUnix is not None:
                GLibUnix.signal_add(GLib.PRIORITY_HIGH, signum, self.on_signal)
            else:
                GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, self.on_signal)
        GLib.timeout_add_seconds(self.config.get_int('autosave_interval', 1), self.on_autosave)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict().end().unpack()
        base = command_line.get_cwd() or HOME
        cwd = os.path.normpath(os.path.join(base, options.get('working-directory') or '.'))
        sessions = [os.path.normpath(os.path.join(base, path)) for path in options.get('session') or []]

        if not self.started:
            self.started = True
            explicit = bool(sessions) or 'working-directory' in options
            self.restore(fresh=bool(options.get('fresh')), open_window=not explicit)
            # An explicit directory (e.g. "Open in Terminal") gets its own window next to the restored ones
            if 'working-directory' in options:
                self.new_window(cwd)
        elif not sessions:
            self.new_window(cwd)

        if sessions:
            window = self.new_window(cwd)
            placeholder = window.tabs()[0]
            for path in sessions:
                load_session_file(window, path)
            if window.notebook.get_n_pages() > 1:
                window.close_tab(placeholder, remember=False)
        return 0

    def restore(self, fresh: bool, open_window: bool) -> None:
        """Bring back the saved windows (unless ``fresh``) and the recently closed list."""
        data = self.store.load()
        if data:
            self.closed = valid_closed(data.get('closed'))[: self.config.get_int('closed_history')]
        windows = [] if fresh or not data else data['windows']
        for window in windows:
            TerminalWindow(self, data=window).present()
        if not windows and open_window:
            self.new_window()

    def new_window(self, cwd: str | None = None) -> TerminalWindow:
        window = TerminalWindow(self, cwd=cwd or HOME)
        window.present()
        self.schedule_save()
        return window

    def windows(self) -> list[TerminalWindow]:
        """The open terminal windows, without the ones that are closing."""
        return [w for w in self.get_windows() if isinstance(w, TerminalWindow) and not w.closing]

    def all_panes(self) -> list[Pane]:
        return [pane for window in self.windows() for tab in window.tabs() for pane in tab.panes()]

    # --- saving

    def serialize(self) -> Session:
        windows = [window.to_dict() for window in self.windows()]
        return {
            'format': SESSION_FORMAT,
            'version': SESSION_VERSION,
            'windows': [window for window in windows if window['tabs']],
            'closed': self.closed,
        }

    def save_now(self, force: bool = False) -> None:
        if self.frozen or not self.started or (time.monotonic() < self.hold_until and not force):
            return
        self.write(self.serialize())

    def write(self, data: Session) -> None:
        try:
            self.store.save(data)
        except (OSError, ValueError) as e:
            logger.warning('saving the session failed, the previous one is kept: %s', e)

    def schedule_save(self, delay: int = 300) -> None:
        """Save soon; several changes in a row are saved once."""
        if self._save_source:
            GLib.source_remove(self._save_source)

        def run() -> bool:
            self._save_source = None
            self.save_now()
            return GLib.SOURCE_REMOVE

        self._save_source = GLib.timeout_add(delay, run)

    def on_autosave(self) -> bool:
        self.save_now()
        return GLib.SOURCE_CONTINUE

    def freeze(self) -> None:
        """Stop saving for good and let every shell end without its pane closing."""
        self.frozen = True
        for pane in self.all_panes():
            pane.closing = True

    # --- closing

    def pane_exited(self, pane: Pane, by_signal: bool) -> bool:
        if by_signal:
            # Give a shutdown a few seconds to finish before the saved layout shrinks
            self.hold_until = time.monotonic() + SHUTDOWN_GRACE_SECONDS
        if pane.window is not None:
            pane.window.close_pane(pane)
        return GLib.SOURCE_REMOVE

    def window_closing(self, window: TerminalWindow) -> None:
        if self.frozen:
            return
        last = len(self.windows()) <= 1
        tabs = window.tabs()

        now = time.monotonic()
        if self.burst is None or now - self.burst.last > CLOSE_BURST_SECONDS:
            self.burst = CloseBurst(snapshot=self.serialize())
        self.burst.last = now
        self.burst.count += 1
        if last and self.burst.count > 1:
            # Several windows closed at once ended the app: that was a quit, everything is kept
            self.closed = [entry for entry in self.closed if entry['id'] not in self.burst.closed_ids]
            snapshot = dict(self.burst.snapshot, closed=self.closed)
            self.freeze()
            self.write(snapshot)
            return

        if last and (len(tabs) > 1 or any(len(tab.panes()) > 1 for tab in tabs)):
            # The last window is a workspace: quitting keeps it for the next start
            self.save_now(force=True)
            self.freeze()
            return

        if tabs:
            tab = window.current_tab()
            entry_id = self.remember_closed('window', tab.title() if tab else APP_NAME, window.to_dict())
            if entry_id:
                self.burst.closed_ids.append(entry_id)
        for tab in tabs:
            for pane in tab.panes():
                pane.closing = True
        window.closing = True
        if last:
            self.save_now(force=True)
            self.freeze()
        else:
            self.schedule_save()

    def quit_all(self) -> None:
        """Quit with every window, tab and split kept for the next start."""
        self.save_now(force=True)
        self.freeze()
        self.quit()

    def on_signal(self) -> bool:
        # Logout or shutdown: the last autosave stays as it is
        self.freeze()
        self.quit()
        return GLib.SOURCE_REMOVE

    # --- recently closed

    def remember_closed(self, kind: ClosedKind, label: str, data: dict[str, Any]) -> str | None:
        """Add a closed pane, tab or window to the recently closed list; returns its id."""
        if self.frozen:
            return None
        entry: ClosedEntry = {
            'id': str(uuid.uuid4()),
            'kind': kind,
            'label': label,
            'closedAt': int(time.time()),
            'data': data,
        }
        self.closed = [entry, *self.closed][: self.config.get_int('closed_history')]
        self.schedule_save()
        return entry['id']

    def clear_closed(self) -> None:
        self.closed = []
        self.schedule_save()

    def reopen(self, entry_id: str | None = None) -> None:
        """Bring back a closed pane, tab or window; the most recently closed one without an id."""
        if entry_id:
            entry = next((e for e in self.closed if e['id'] == entry_id), None)
        else:
            entry = self.closed[0] if self.closed else None
        if entry is None:
            return
        self.closed = [e for e in self.closed if e is not entry]
        active = self.get_active_window()
        if isinstance(active, TerminalWindow) and not active.closing:
            window: TerminalWindow | None = active
        else:
            window = next(iter(self.windows()), None)
        kind, data = entry['kind'], entry['data']
        if kind == 'window' or window is None:
            if kind == 'pane':
                data = {'tabs': [{'type': 'Session', 'child': data}]}
            elif kind == 'tab':
                data = {'tabs': [data]}
            TerminalWindow(self, data=data).present()
        elif kind == 'tab':
            window.add_tab(layout=data)
        else:
            # A closed pane comes back next to the focused pane
            window.split(window.active_pane(), HORIZONTAL, new=build_tree(self, data))
        self.schedule_save()

    # --- config

    def open_config(self) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(str(self.config.path), None), None)
        except GLib.Error as e:
            logger.warning('cannot open %s: %s', self.config.path, e.message)

    def reload_config(self) -> None:
        self.config = Config(self.config.path)
        self.store.keep = self.config.get_int('session_history', 1)
        apply_theme_variant(self.config)
        install_css()
        for pane in self.all_panes():
            pane.apply_config()
        for window in self.windows():
            window.update_indicators()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format='%(name)s: %(message)s')
    return Application().run(sys.argv)
