"""The split tree of a tab: panes inside nested splits, inside a tab."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from tileminal import APP_NAME
from tileminal._gi import GLib, Gtk, Pango
from tileminal.files import shorten_home
from tileminal.model import ACTIVE_PANE_KEY, AUTO_TAB_NAME, Node, node_ratio
from tileminal.pane import Pane

if TYPE_CHECKING:
    from tileminal.app import Application


class Split(Gtk.Paned):
    """Two panes or splits side by side (HORIZONTAL) or stacked (VERTICAL).

    The ratio is kept even before the split has a size, which is the case for restored splits,
    background tabs and splits whose other side is hidden by a maximized pane.
    """

    def __init__(self, orientation: Gtk.Orientation, child1: Gtk.Widget, child2: Gtk.Widget, ratio: float = 0.5):
        super().__init__(orientation=orientation)
        self.pending_ratio: float | None = ratio
        self.pack1(child1, True, False)
        self.pack2(child2, True, False)
        self.connect('size-allocate', self.on_size_allocate)
        self.connect('notify::position', self.on_position_changed)
        self.show()

    def span(self) -> int:
        allocation = self.get_allocation()
        size = allocation.width if self.get_orientation() == Gtk.Orientation.HORIZONTAL else allocation.height
        return size - self.style_get_property('handle-size')

    def both_visible(self) -> bool:
        child1, child2 = self.get_child1(), self.get_child2()
        return child1 is not None and child2 is not None and child1.get_visible() and child2.get_visible()

    def ratio(self) -> float:
        if self.pending_ratio is not None:
            return self.pending_ratio
        span = self.span()
        if span <= 0:
            return 0.5
        return min(0.95, max(0.05, self.get_position() / span))

    def freeze_ratio(self) -> None:
        """Keep the current ratio while a child is hidden; it is applied again once both are visible."""
        if self.pending_ratio is None:
            self.pending_ratio = self.ratio()

    def other(self, child: Gtk.Widget) -> Gtk.Widget:
        return self.get_child2() if self.get_child1() is child else self.get_child1()

    def on_size_allocate(self, *_args: object) -> None:
        if self.pending_ratio is None or self.span() < 20 or not self.both_visible():
            return

        def apply() -> bool:
            if self.pending_ratio is not None and self.span() >= 20 and self.both_visible():
                self.set_position(round(self.pending_ratio * self.span()))
                self.pending_ratio = None
            return GLib.SOURCE_REMOVE

        # Setting the position during the allocation itself would be overridden by GTK
        GLib.idle_add(apply)

    def on_position_changed(self, *_args: object) -> None:
        window = self.get_toplevel()
        if isinstance(window, Gtk.ApplicationWindow):
            window.app.schedule_save()

    def to_node(self, with_size: bool = False) -> Node:
        ratio = self.ratio()
        return {
            'type': 'Paned',
            'orientation': int(self.get_orientation()),
            'position': round(ratio * 100),
            'ratio': round(ratio, 4),
            'child1': self.get_child1().to_node(with_size),
            'child2': self.get_child2().to_node(with_size),
        }


class Tab(Gtk.Box):
    """One tab: the root of a split tree, plus the tab's name, focus and maximize state."""

    def __init__(self, root: Gtk.Widget, tab_id: str | None = None, name: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.uuid = tab_id or str(uuid.uuid4())
        self.name = name or AUTO_TAB_NAME
        self.active_pane: Pane | None = None
        self.maximized: Pane | None = None
        self.hidden: list[Gtk.Widget] = []
        self.label = Gtk.Label(label='', ellipsize=Pango.EllipsizeMode.END, max_width_chars=30)
        self.arrow: Gtk.MenuButton | None = None
        self.set_root(root)
        self.show()

    @property
    def root(self) -> Gtk.Widget | None:
        children = self.get_children()
        return children[0] if children else None

    def set_root(self, widget: Gtk.Widget) -> None:
        self.pack_start(widget, True, True, 0)

    def panes(self, widget: Gtk.Widget | None = None) -> list[Pane]:
        """The panes under ``widget`` (the whole tab by default), left to right and top to bottom."""
        widget = widget or self.root
        if isinstance(widget, Pane):
            return [widget]
        if isinstance(widget, Split):
            return self.panes(widget.get_child1()) + self.panes(widget.get_child2())
        return []

    def focused_pane(self) -> Pane | None:
        panes = self.panes()
        if self.active_pane in panes:
            return self.active_pane
        return panes[0] if panes else None

    def custom_name(self) -> str:
        """The name the user gave the tab, or '' when it shows the terminal title."""
        return '' if '${' in self.name else self.name

    def title(self) -> str:
        """The tab's name, with ${title} and ${directory} filled in from the focused pane."""
        pane = self.focused_pane()
        if pane is None:
            return APP_NAME
        if '${' not in self.name:
            return self.name
        text = self.name.replace('${title}', pane.title()).replace('${directory}', shorten_home(pane.cwd()))
        return text.strip() or pane.title()

    def to_data(self, with_size: bool = False) -> Node:
        root = self.root
        assert root is not None, 'a tab always has a pane until it is destroyed'
        node: Node = {
            'type': 'Session',
            'uuid': self.uuid,
            'name': self.name,
            'version': '1.0',
            'synchronizedInput': False,
            'width': self.get_allocated_width(),
            'height': self.get_allocated_height(),
            'child': root.to_node(with_size),
        }
        pane = self.focused_pane()
        if pane is not None:
            node[ACTIVE_PANE_KEY] = pane.uuid
        return node


def build_tree(app: Application, node: Node) -> Pane | Split:
    """Widgets for a saved layout; every terminal starts its shell in its saved directory."""
    if node['type'] == 'Terminal':
        title = node.get('title')
        return Pane(
            app,
            cwd=node.get('directory') or None,
            pane_id=node.get('uuid'),
            profile=node.get('profile'),
            custom_title=title if isinstance(title, str) else '',
        )
    orientation = Gtk.Orientation.HORIZONTAL if node['orientation'] == 0 else Gtk.Orientation.VERTICAL
    return Split(orientation, build_tree(app, node['child1']), build_tree(app, node['child2']), node_ratio(node))


def replace_child(parent: Gtk.Widget, old: Gtk.Widget, make_new: Callable[[], Gtk.Widget]) -> None:
    """Put ``make_new()`` where ``old`` was. ``old`` is detached first, so ``make_new`` can adopt it."""
    if isinstance(parent, Split):
        first = parent.get_child1() is old
        ratio = parent.ratio()
        parent.remove(old)
        new = make_new()
        if first:
            parent.pack1(new, True, False)
        else:
            parent.pack2(new, True, False)
        parent.pending_ratio = ratio
        parent.queue_resize()
    elif isinstance(parent, Tab):
        parent.remove(old)
        parent.set_root(make_new())
