"""The saved session: all windows with their tabs and splits, and the recently closed list.

``session.json`` is only ever replaced by a version that was written completely and read back.
The version it replaces moves to ``history/``, which keeps the last few, and an unreadable
``session.json`` falls back to the newest readable one from there.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from tileminal import APP_SLUG
from tileminal.files import fsync_dir, replace_verified, state_dir, write_verified
from tileminal.model import validate_node, validate_tab

logger = logging.getLogger(__name__)

SESSION_FORMAT = APP_SLUG + '-session'
SESSION_VERSION = 1
ClosedKind = Literal['pane', 'tab', 'window']
Session = dict[str, Any]


class ClosedEntry(TypedDict):
    """A closed pane, tab or window in the recently closed list."""

    id: str
    kind: ClosedKind
    label: str
    closedAt: int  # noqa: N815 - stored as is in the session file
    data: dict[str, Any]


def validate_window(window: Any) -> None:
    tabs = window.get('tabs') if isinstance(window, dict) else None
    if not isinstance(tabs, list) or not tabs:
        raise ValueError('window without tabs')
    for tab in tabs:
        validate_tab(tab)


def validate_session(data: Any) -> None:
    """Raises ``ValueError`` unless ``data`` is a complete session."""
    if not isinstance(data, dict) or data.get('format') != SESSION_FORMAT:
        raise ValueError('not a session file')
    windows = data.get('windows')
    if not isinstance(windows, list):
        raise ValueError('no window list')
    for window in windows:
        validate_window(window)


def valid_closed(entries: Any) -> list[ClosedEntry]:
    """The usable entries of a saved recently-closed list; damaged ones are dropped."""
    result: list[ClosedEntry] = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            kind, data = entry['kind'], entry['data']
            if kind == 'pane':
                validate_node(data)
            elif kind == 'tab':
                validate_tab(data)
            elif kind == 'window':
                validate_window(data)
            else:
                raise ValueError(f'unknown kind {kind!r}')
            if not isinstance(entry.get('label'), str) or not isinstance(entry.get('id'), str):
                raise ValueError('entry without label or id')
        except (KeyError, TypeError, ValueError):
            continue
        result.append(cast(ClosedEntry, {'closedAt': 0, **entry}))
    return result


class SessionStore:
    """``session.json`` in ``directory``, plus its previous versions in ``directory/history``."""

    def __init__(self, directory: Path | None = None, keep: int = 10) -> None:
        self.dir = directory or state_dir()
        self.path = self.dir / 'session.json'
        self.history_dir = self.dir / 'history'
        self.keep = keep
        self._last_text: str | None = None

    def history(self) -> list[Path]:
        """Previous versions, oldest first."""
        try:
            paths = list(self.history_dir.iterdir())
        except OSError:
            return []
        return sorted(p for p in paths if p.name.startswith('session-') and p.suffix == '.json')

    def load(self) -> Session | None:
        """The saved session, or the newest readable previous version when it is damaged."""
        for path in [self.path, *reversed(self.history())]:
            try:
                text = path.read_text(encoding='utf-8')
                data: Session = json.loads(text)
                validate_session(data)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as e:
                logger.warning('skipping unreadable session %s: %s', path, e)
                continue
            if path == self.path:
                self._last_text = text
            else:
                logger.warning('restoring from history: %s', path)
            return data
        return None

    def save(self, data: Session) -> bool:
        """Write the session if it changed. Returns whether a new version was written.

        Raises ``ValueError`` for an incomplete session and ``OSError`` when writing fails; the
        previous version is untouched in both cases.
        """
        validate_session(data)
        text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
        if text == self._last_text:
            return False
        # Only text that survives a round trip may replace the real file
        validate_session(json.loads(text))

        self.history_dir.mkdir(parents=True, exist_ok=True)
        tmp = write_verified(self.path, text)
        try:
            if self.path.exists():
                self._keep_previous()
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        fsync_dir(self.dir)
        self._last_text = text
        self.prune()
        return True

    def _keep_previous(self) -> None:
        now = time.time_ns()
        stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime(now // 1_000_000_000)) + f'-{now % 1_000_000_000:09d}'
        previous = self.history_dir / f'session-{stamp}.json'
        try:
            # A hard link keeps the old file as it is, without copying it
            os.link(self.path, previous)
        except OSError:
            replace_verified(previous, self.path.read_text(encoding='utf-8'))
        fsync_dir(self.history_dir)

    def prune(self) -> None:
        """Delete all but the newest ``keep`` previous versions."""
        old = self.history()
        for path in old[: max(0, len(old) - self.keep)]:
            with contextlib.suppress(OSError):
                path.unlink()
