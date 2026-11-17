"""Saved layouts as plain data.

A tab is stored as a "Session" object, the same structure as the session files in the menu::

    {"type": "Session", "uuid", "name", "version": "1.0", "child": <node>}

and a node is either a terminal or a split of two nodes::

    {"type": "Terminal", "uuid", "directory", "title"?}
    {"type": "Paned", "orientation": 0 | 1, "ratio": 0..1, "position": 0..100, "child1", "child2"}

Orientation 0 puts the children side by side, 1 stacks them.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from tileminal import APP_SLUG
from tileminal.files import HOME

Node = dict[str, Any]

# Session files name a profile for each terminal; this is the well-known id of the default one
DEFAULT_PROFILE_ID = '2b7c4080-0ddd-46c5-8f23-563fd3ba789d'
# A tab name meaning "use the terminal title"; a name without variables is a custom name
AUTO_TAB_NAME = '${title}'
ACTIVE_PANE_KEY = APP_SLUG + 'ActivePane'

_MAX_DEPTH = 64


def validate_node(node: Any, depth: int = 0) -> int:
    """Check a layout node; returns the number of terminals in it. Raises ``ValueError``."""
    if depth > _MAX_DEPTH or not isinstance(node, dict):
        raise ValueError('bad layout node')
    kind = node.get('type')
    if kind == 'Terminal':
        if not isinstance(node.get('directory', ''), str):
            raise ValueError('bad terminal directory')
        return 1
    if kind == 'Paned':
        if node.get('orientation') not in (0, 1):
            raise ValueError('bad split orientation')
        if not isinstance(node.get('ratio', node.get('position', 50)), (int, float)):
            raise ValueError('bad split ratio')
        return validate_node(node.get('child1'), depth + 1) + validate_node(node.get('child2'), depth + 1)
    raise ValueError(f'unknown layout node type {kind!r}')


def validate_tab(tab: Any) -> int:
    """Check a session object; returns the number of terminals. Raises ``ValueError``."""
    if not isinstance(tab, dict) or tab.get('type') != 'Session':
        raise ValueError('not a session object')
    return validate_node(tab.get('child'))


def node_ratio(node: Node) -> float:
    """A split's ratio, from its percentage when there is none, kept within sensible bounds."""
    ratio = node.get('ratio')
    if not isinstance(ratio, (int, float)):
        ratio = node.get('position', 50) / 100
    return min(0.95, max(0.05, float(ratio)))


def node_panes(node: Node) -> list[Node]:
    """The terminals of a layout, left to right and top to bottom."""
    if node.get('type') == 'Terminal':
        return [node]
    return node_panes(node['child1']) + node_panes(node['child2'])


def pane_name(node: Node) -> str:
    """Short name of a saved terminal: its own title, else the last part of its directory."""
    title = node.get('title')
    if isinstance(title, str) and title:
        return title
    directory = str(node.get('directory') or HOME)
    if directory == HOME:
        return '~'
    return os.path.basename(directory.rstrip('/')) or '/'


def renew_ids(node: Node) -> None:
    """Give every terminal in a layout a new id, so two copies of one layout never share ids."""
    if node.get('type') == 'Terminal':
        node['uuid'] = str(uuid.uuid4())
    else:
        renew_ids(node['child1'])
        renew_ids(node['child2'])
