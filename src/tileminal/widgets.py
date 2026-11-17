"""Small building blocks shared by the window, the tabs and the panes."""

from __future__ import annotations

from collections.abc import Callable

from tileminal._gi import Gio, Gtk
from tileminal.i18n import _


def icon_button(icon: str, tooltip: str, callback: Callable[[], object]) -> Gtk.Button:
    """A flat button with a small icon."""
    button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_focus_on_click(False)
    button.set_tooltip_text(tooltip)
    button.connect('clicked', lambda _button: callback())
    return button


def arrow_button(menu: Gio.MenuModel) -> Gtk.MenuButton:
    """A small ⌄ button that opens ``menu``; only the arrow itself is clickable."""
    button = Gtk.MenuButton(menu_model=menu, relief=Gtk.ReliefStyle.NONE, focus_on_click=False)
    button.set_image(Gtk.Image.new_from_icon_name('tileminal-arrow-down-symbolic', Gtk.IconSize.MENU))
    button.get_style_context().add_class('tileminal-arrow')
    return button


def rename_popover(
    anchor: Gtk.Widget,
    current: str,
    placeholder: str,
    on_accept: Callable[[str], object],
    on_closed: Callable[[], object],
) -> None:
    """Ask for a new name below ``anchor``. An empty name means "use the terminal title"."""
    popover = Gtk.Popover(relative_to=anchor, position=Gtk.PositionType.BOTTOM)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
    entry = Gtk.Entry(text=current, width_chars=28)
    entry.set_placeholder_text(placeholder)
    hint = Gtk.Label(label=_('Empty shows the terminal title'), xalign=0)
    hint.get_style_context().add_class('dim-label')
    box.pack_start(entry, False, False, 0)
    box.pack_start(hint, False, False, 0)
    popover.add(box)

    def accept(_entry: Gtk.Entry) -> None:
        on_accept(entry.get_text().strip())
        popover.popdown()

    def closed(_popover: Gtk.Popover) -> None:
        popover.destroy()
        on_closed()

    entry.connect('activate', accept)
    popover.connect('closed', closed)
    box.show_all()
    popover.popup()
    entry.grab_focus()
