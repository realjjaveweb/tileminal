"""Moving panes within a tab: by dragging a pane's title row, or directly with ``move``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tileminal._gi import GLib, Gtk
from tileminal.geometry import Rect, Zone, drop_zone_at
from tileminal.layout import Split, replace_child

if TYPE_CHECKING:
    from tileminal.pane import Pane
    from tileminal.window import TerminalWindow


def widget_rect(widget: Gtk.Widget, relative_to: Gtk.Widget) -> Rect | None:
    """Where ``widget`` is, in the coordinates of ``relative_to``; None when it is not laid out."""
    origin = widget.translate_coordinates(relative_to, 0, 0)
    if origin is None:
        return None
    x, y = origin
    return Rect(x, y, x + widget.get_allocated_width(), y + widget.get_allocated_height())


class PaneMover:
    """Belongs to a window. While a pane is dragged, the other panes of its tab show where it would go."""

    def __init__(self, window: TerminalWindow) -> None:
        self.window = window
        self.dragging: Pane | None = None

    def begin(self, source: Pane) -> None:
        self.dragging = source
        self._show_drop_zones(source, True)

    def update(self, source: Pane, x: int, y: int) -> None:
        target, zone = self.target_at(source, x, y)
        for pane in self._tab_panes(source):
            pane.drop_zone.set_zone(zone if pane is target else None)

    def drop(self, source: Pane, x: int, y: int) -> None:
        target, zone = self.target_at(source, x, y)
        self.dragging = None
        self._show_drop_zones(source, False)
        if target is not None and zone is not None:
            self.move(source, target, zone)

    def target_at(self, source: Pane, x: int, y: int) -> tuple[Pane | None, Zone | None]:
        """The pane under a window point (other than the dragged one) and the zone of it."""
        for pane in self._tab_panes(source):
            # The terminal area is always laid out, unlike the drop zone that only shows while dragging
            rect = widget_rect(pane.body, self.window) if pane is not source and pane.get_mapped() else None
            if rect is None:
                continue
            # The pane's title row counts as part of its top edge
            header = pane.header.get_allocated_height() if pane.header.get_visible() else 0
            if rect.left <= x < rect.right and rect.top - header <= y < rect.bottom:
                zone = drop_zone_at(x - rect.left, max(0, y - rect.top), rect.right - rect.left, rect.bottom - rect.top)
                return pane, zone
        return None, None

    def move(self, source: Pane, target: Pane, zone: Zone) -> None:
        """Put ``source`` on one side of ``target``, or swap the two for the middle zone."""
        tab = target.tab
        if source is target or tab is None or source.tab is not tab:
            return
        self.window.unmaximize(tab)
        if zone == 'center':
            placeholder = Gtk.Box()
            replace_child(source.get_parent(), source, lambda: placeholder)
            replace_child(target.get_parent(), target, lambda: source)
            replace_child(placeholder.get_parent(), placeholder, lambda: target)
            placeholder.destroy()
        else:
            # Take the pane out (its sibling takes over the split), then split the target
            parent = source.get_parent()
            sibling = parent.other(source)
            parent.remove(source)
            parent.remove(sibling)
            replace_child(parent.get_parent(), parent, lambda: sibling)
            parent.destroy()
            orientation = Gtk.Orientation.HORIZONTAL if zone in ('left', 'right') else Gtk.Orientation.VERTICAL
            first, second = (source, target) if zone in ('left', 'top') else (target, source)
            replace_child(target.get_parent(), target, lambda: Split(orientation, first, second))
        tab.active_pane = source
        self.window.update_indicators()
        GLib.idle_add(self.window.focus_active)
        self.window.app.schedule_save()

    def _tab_panes(self, source: Pane) -> list[Pane]:
        tab = source.tab
        return tab.panes() if tab is not None else []

    def _show_drop_zones(self, source: Pane, active: bool) -> None:
        for pane in self._tab_panes(source):
            pane.drop_zone.set_zone(None)
            pane.drop_zone.set_visible(active and pane is not source)
