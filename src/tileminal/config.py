"""User settings, kept in ``config.json`` and created with the defaults on the first start."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tileminal.files import config_dir, replace_verified

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    'font': None,  # None: the desktop's monospace font
    'scrollback_lines': 10000,
    'color_scheme': 'dark',  # "dark", "light" or {"foreground", "background", "palette": [16 colours]}
    'cursor_shape': 'block',  # block, ibeam, underline
    'autosave_interval': 5,  # seconds
    'session_history': 10,  # previous session versions kept next to the session file
    'closed_history': 20,  # closed panes, tabs and windows that can be reopened
    'pane_headers': 'splits',  # title row per pane: "splits" (only when split) or "always"
}

_PALETTE = [
    '#171421',
    '#c01c28',
    '#26a269',
    '#a2734c',
    '#12488b',
    '#a347ba',
    '#2aa1b3',
    '#d0cfcc',
    '#5e5c64',
    '#f66151',
    '#33da7a',
    '#e9ad0c',
    '#2a7bde',
    '#c061cb',
    '#33c7de',
    '#ffffff',
]

COLOR_SCHEMES: dict[str, dict[str, Any]] = {
    'dark': {'foreground': '#d0cfcc', 'background': '#171421', 'palette': _PALETTE},
    'light': {'foreground': '#171421', 'background': '#ffffff', 'palette': _PALETTE},
}
DEFAULT_SCHEME = 'dark'


class Config:
    """Settings with defaults for anything missing. A broken file is reported and left for the
    user to fix; the defaults apply meanwhile."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / 'config.json'
        self.values: dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                replace_verified(self.path, json.dumps(DEFAULTS, indent=2) + '\n')
            except OSError as e:
                logger.warning('cannot write the default config: %s', e)
            return
        try:
            loaded = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(loaded, dict):
                raise ValueError('not a JSON object')
        except (OSError, ValueError) as e:
            logger.warning('ignoring %s: %s', self.path, e)
            return
        self.values.update(loaded)

    def __getitem__(self, key: str) -> Any:
        return self.values.get(key, DEFAULTS.get(key))

    def get_int(self, key: str, minimum: int = 0) -> int:
        """An integer setting, at least ``minimum``; the default when the value is not a number."""
        try:
            return max(minimum, int(self[key]))
        except (TypeError, ValueError):
            return int(DEFAULTS[key])

    def color_scheme(self) -> dict[str, Any]:
        """The colour scheme as ``{"foreground", "background", "palette"}``, completed from the default."""
        base = COLOR_SCHEMES[DEFAULT_SCHEME]
        scheme = self['color_scheme']
        if isinstance(scheme, str):
            scheme = COLOR_SCHEMES.get(scheme, base)
        if not isinstance(scheme, dict):
            scheme = base
        palette = scheme.get('palette')
        if not (isinstance(palette, list) and len(palette) in (8, 16)):
            palette = base['palette']
        return {
            'foreground': scheme.get('foreground', base['foreground']),
            'background': scheme.get('background', base['background']),
            'palette': palette,
        }
