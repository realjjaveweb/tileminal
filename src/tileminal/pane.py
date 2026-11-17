"""One terminal: the VTE widget, its title row and the drop zone shown while dragging."""

from __future__ import annotations

import os
import uuid
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from tileminal._gi import Gdk, Gio, GLib, Gtk, Pango, Vte
from tileminal.files import HOME, shorten_home
from tileminal.geometry import Zone
from tileminal.i18n import _
from tileminal.model import DEFAULT_PROFILE_ID, Node
from tileminal.snap import shell_command
from tileminal.style import CURSOR_SHAPES, colors, font
from tileminal.widgets import arrow_button, icon_button, rename_popover

if TYPE_CHECKING:
    from tileminal.app import Application
    from tileminal.layout import Tab
    from tileminal.window import TerminalWindow

PCRE2_MULTILINE = 0x00000400
# VTE 0.78 replaced the title and directory signals with "terminal properties"; older VTE has only the former
HAS_TERMPROPS = hasattr(Vte, 'TERMPROP_XTERM_TITLE')
URL_REGEX = r"(?:https?|ftp|file)://[^\s<>\"'`]*[^\s<>\"'`.,;:!?)\]}]"


class PaneHeader(Gtk.EventBox):
    """Title row: "N: title", a rename arrow, and split, maximize and close buttons.

    Clicking the title focuses the pane. Dragging it moves the pane within its tab; the drag is
    tracked here instead of with GTK drag and drop: the header keeps the pointer until the button
    is released, and the window works out which pane is under it.
    """

    def __init__(self, pane: Pane) -> None:
        super().__init__()
        self.pane = pane
        self.press: tuple[float, float] | None = None
        self.dragging = False
        self.get_style_context().add_class('tileminal-pane-header')
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON_MOTION_MASK
        )

        actions = Gio.SimpleActionGroup()
        rename = Gio.SimpleAction.new('rename', None)
        rename.connect('activate', lambda _action, _param: pane.rename())
        actions.add_action(rename)
        pane.insert_action_group('pane', actions)
        menu = Gio.Menu()
        menu.append(_('Rename…'), 'pane.rename')

        box = Gtk.Box()
        self.add(box)
        self.label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, margin_start=6)
        self.label.get_style_context().add_class('title')
        self.arrow = arrow_button(menu)
        box.pack_start(self.label, False, False, 0)
        box.pack_start(self.arrow, False, False, 0)

        self.maximize_button = icon_button('tileminal-maximize-symbolic', _('Maximize'), pane.toggle_maximize)
        for button in (
            icon_button('tileminal-close-symbolic', _('Close'), pane.close),
            self.maximize_button,
            icon_button('tileminal-split-down-symbolic', _('Split Down'), lambda: pane.split(Gtk.Orientation.VERTICAL)),
            icon_button(
                'tileminal-split-right-symbolic', _('Split Right'), lambda: pane.split(Gtk.Orientation.HORIZONTAL)
            ),
        ):
            box.pack_end(button, False, False, 0)

        self.connect('button-press-event', self.on_press)
        self.connect('motion-notify-event', self.on_motion)
        self.connect('button-release-event', self.on_release)
        self.show_all()
        self.set_no_show_all(True)

    def set_maximized(self, maximized: bool) -> None:
        icon = 'tileminal-restore-symbolic' if maximized else 'tileminal-maximize-symbolic'
        self.maximize_button.get_image().set_from_icon_name(icon, Gtk.IconSize.MENU)
        self.maximize_button.set_tooltip_text(_('Restore') if maximized else _('Maximize'))

    def _window_point(self, event: Gdk.EventButton | Gdk.EventMotion) -> tuple[int, int] | None:
        window = self.pane.window
        return self.translate_coordinates(window, int(event.x), int(event.y)) if window else None

    def on_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        self.press = (event.x_root, event.y_root)
        self.dragging = False
        self.pane.focus()
        return True

    def on_motion(self, _widget: Gtk.Widget, event: Gdk.EventMotion) -> bool:
        if self.press is None:
            return False
        window, point = self.pane.window, self._window_point(event)
        if window is None or point is None:
            return True
        if not self.dragging:
            threshold = Gtk.Settings.get_default().get_property('gtk-dnd-drag-threshold')
            moved = max(abs(event.x_root - self.press[0]), abs(event.y_root - self.press[1]))
            tab = self.pane.tab
            if moved < threshold or tab is None or len(tab.panes()) < 2:
                return True
            self.dragging = True
            self._set_cursor('grabbing')
            window.mover.begin(self.pane)
        window.mover.update(self.pane, *point)
        return True

    def on_release(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if self.press is None or event.button != 1:
            return False
        dragging, self.press, self.dragging = self.dragging, None, False
        if dragging:
            self._set_cursor(None)
            window, point = self.pane.window, self._window_point(event)
            if window is not None and point is not None:
                window.mover.drop(self.pane, *point)
        return True

    def _set_cursor(self, name: str | None) -> None:
        gdk_window = self.get_window()
        if gdk_window is not None:
            cursor = Gdk.Cursor.new_from_name(gdk_window.get_display(), name) if name else None
            gdk_window.set_cursor(cursor)


class DropZone(Gtk.DrawingArea):
    """Laid over a pane while another pane of the tab is dragged; highlights where the dragged pane
    would go: an edge puts it on that side, the middle swaps the two panes."""

    def __init__(self) -> None:
        super().__init__()
        self.zone: Zone | None = None
        self.set_no_show_all(True)
        self.connect('draw', self.on_draw)

    def set_zone(self, zone: Zone | None) -> None:
        if zone != self.zone:
            self.zone = zone
            self.queue_draw()

    def on_draw(self, _widget: Gtk.Widget, cr: Any) -> bool:
        if not self.zone:
            return False
        width, height = self.get_allocated_width(), self.get_allocated_height()
        x, y, w, h = {
            'left': (0, 0, width / 2, height),
            'right': (width / 2, 0, width / 2, height),
            'top': (0, 0, width, height / 2),
            'bottom': (0, height / 2, width, height / 2),
            'center': (width * 0.3, height * 0.3, width * 0.4, height * 0.4),
        }[self.zone]
        fg = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.16)
        cr.rectangle(x, y, w, h)
        cr.fill_preserve()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
        cr.set_line_width(2)
        cr.stroke()
        return False


class Pane(Gtk.Box):
    """A terminal running the user's shell, with its header and a thin overlay scrollbar."""

    def __init__(
        self,
        app: Application,
        cwd: str | None = None,
        pane_id: str | None = None,
        profile: str | None = None,
        custom_title: str = '',
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.uuid = pane_id or str(uuid.uuid4())
        self.profile = profile
        self.custom_title = custom_title
        # Set when the pane is closed on purpose, so the shell ending is not taken for an exit
        self.closing = False
        self.child_pid: int | None = None
        self.last_cwd = cwd if cwd and os.path.isdir(cwd) else HOME
        self.font_scale = 1.0
        self.get_style_context().add_class('tileminal-pane')

        self.term = Vte.Terminal(hexpand=True, vexpand=True)
        self.apply_config()
        self.term.set_mouse_autohide(True)
        self.term.set_allow_hyperlink(True)
        self.url_tag = self.term.match_add_regex(Vte.Regex.new_for_match(URL_REGEX, -1, PCRE2_MULTILINE), 0)
        self.term.match_set_cursor_name(self.url_tag, 'pointer')

        self.header = PaneHeader(self)
        # A scrolled window gives the thin overlay indicator that only grows when the pointer is on it
        scroller = Gtk.ScrolledWindow(overlay_scrolling=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.term)
        self.drop_zone = DropZone()
        self.body = Gtk.Overlay()
        self.body.add(scroller)
        self.body.add_overlay(self.drop_zone)
        self.pack_start(self.header, False, False, 0)
        self.pack_start(self.body, True, True, 0)

        self.term.connect('child-exited', self.on_child_exited)
        if HAS_TERMPROPS:
            self.term.connect('termprop-changed', self.on_termprop_changed)
        else:
            self.term.connect('window-title-changed', lambda _term: self.title_changed())
            self.term.connect('current-directory-uri-changed', lambda _term: self.title_changed())
        self.term.connect('focus-in-event', self.on_focus_in)
        self.term.connect('button-press-event', self.on_button_press)
        self.show_all()
        self.spawn()

    # --- where the pane is

    @property
    def window(self) -> TerminalWindow | None:
        top = self.get_toplevel()
        # The app's only kind of application window is the terminal window
        return top if isinstance(top, Gtk.ApplicationWindow) else None

    @property
    def tab(self) -> Tab | None:
        from tileminal.layout import Tab

        widget = self.get_parent()
        while widget is not None and not isinstance(widget, Tab):
            widget = widget.get_parent()
        return widget

    # --- terminal

    def apply_config(self) -> None:
        config = self.app.config
        self.term.set_font(font(config))
        self.term.set_font_scale(self.font_scale)
        self.term.set_scrollback_lines(config.get_int('scrollback_lines'))
        self.term.set_cursor_shape(CURSOR_SHAPES.get(config['cursor_shape'], Vte.CursorShape.BLOCK))
        self.term.set_colors(*colors(config))

    def spawn(self) -> None:
        shell = os.environ.get('SHELL') or '/bin/bash'
        if not os.access(shell, os.X_OK):
            shell = '/bin/bash'
        self.term.spawn_async(
            Vte.PtyFlags.DEFAULT,
            self.last_cwd,
            shell_command([shell]),
            [f'TERMINAL_PANE_ID={self.uuid}'],
            GLib.SpawnFlags.SEARCH_PATH,
            None,
            None,
            -1,
            None,
            self.on_spawned,
            None,
        )

    def on_spawned(self, _term: Vte.Terminal, pid: int, error: GLib.Error | None, *_user_data: object) -> None:
        if error:
            self.term.feed(f'\r\n{error.message}\r\n'.encode())
            return
        self.child_pid = pid

    def cwd(self) -> str:
        """The shell's working directory; the last known one once the shell is gone."""
        if self.child_pid:
            try:
                self.last_cwd = os.readlink(f'/proc/{self.child_pid}/cwd')
                return self.last_cwd
            except OSError:
                pass
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            uri = self.term.get_current_directory_uri()
        if uri:
            try:
                path = GLib.filename_from_uri(uri)[0]
            except GLib.Error:
                path = None
            if path and os.path.isdir(path):
                self.last_cwd = path
        return self.last_cwd

    def auto_title(self) -> str:
        if HAS_TERMPROPS:
            title, _length = self.term.get_termprop_string(Vte.TERMPROP_XTERM_TITLE)
        else:
            title = self.term.get_window_title()
        return title or shorten_home(self.cwd())

    def title(self) -> str:
        return self.custom_title or self.auto_title()

    def to_node(self, with_size: bool = False) -> Node:
        node: Node = {
            'type': 'Terminal',
            'uuid': self.uuid,
            'directory': self.cwd(),
            'profile': self.profile or DEFAULT_PROFILE_ID,
            'readOnly': False,
            'synchronizedInput': False,
        }
        if self.custom_title:
            node['title'] = self.custom_title
        if with_size:
            node['width'] = self.get_allocated_width()
            node['height'] = self.get_allocated_height()
        return node

    # --- actions

    def focus(self) -> None:
        tab, window = self.tab, self.window
        if tab is not None:
            tab.active_pane = self
        self.term.grab_focus()
        if window is not None:
            window.update_indicators()

    def split(self, orientation: Gtk.Orientation) -> None:
        if self.window is not None:
            self.window.split(self, orientation)

    def close(self) -> None:
        if self.window is not None:
            self.window.close_pane(self)

    def toggle_maximize(self) -> None:
        if self.window is not None:
            self.window.toggle_maximize(self)

    def rename(self) -> None:
        window = self.window
        if window is None:
            return

        def accept(text: str) -> None:
            self.custom_title = text
            window.update_titles()
            self.app.schedule_save()

        rename_popover(
            self.header.arrow, self.custom_title, self.auto_title(), accept, lambda: GLib.idle_add(window.focus_active)
        )

    def zoom(self, step: int) -> None:
        """Bigger for a positive step, smaller for a negative one, normal size for 0."""
        if step == 0:
            self.font_scale = 1.0
        else:
            self.font_scale = min(4.0, max(0.25, self.font_scale * (1.1 if step > 0 else 1 / 1.1)))
        self.term.set_font_scale(self.font_scale)

    def copy(self) -> None:
        if self.term.get_has_selection():
            self.term.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self) -> None:
        self.term.paste_clipboard()

    # --- events

    def on_child_exited(self, _term: Vte.Terminal, status: int) -> None:
        self.child_pid = None
        if self.closing:
            return
        # A shell killed by a signal is usually the desktop shutting down, not the user typing exit
        by_signal = status >= 0 and os.WIFSIGNALED(status)
        GLib.idle_add(self.app.pane_exited, self, by_signal)

    def on_termprop_changed(self, _term: Vte.Terminal, name: str) -> None:
        if name in (Vte.TERMPROP_XTERM_TITLE, Vte.TERMPROP_CURRENT_DIRECTORY_URI):
            self.title_changed()

    def title_changed(self) -> None:
        if self.window is not None:
            self.window.update_titles()

    def on_focus_in(self, *_args: object) -> bool:
        window, tab = self.window, self.tab
        if window is not None and tab is not None:
            tab.active_pane = self
            window.update_indicators()
        return False

    def link_at(self, event: Gdk.EventButton) -> str | None:
        link: str | None = self.term.hyperlink_check_event(event)
        if link:
            return link
        match, tag = self.term.match_check_event(event)
        return str(match) if match and tag == self.url_tag else None

    def on_button_press(self, _term: Vte.Terminal, event: Gdk.EventButton) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button == 1 and event.state & Gdk.ModifierType.CONTROL_MASK:
            link = self.link_at(event)
            if link:
                self.open_link(link)
                return True
        # Shift+right-click goes to the program in the terminal instead
        if event.button == 3 and not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.term.grab_focus()
            self.context_menu(event)
            return True
        return False

    def open_link(self, link: str) -> None:
        try:
            Gtk.show_uri_on_window(self.window, link, Gtk.get_current_event_time())
        except GLib.Error as e:
            message = _('Cannot open {link}: {error}').format(link=link, error=e.message)
            self.term.feed(f'\r\n{message}\r\n'.encode())

    def context_menu(self, event: Gdk.EventButton) -> None:
        menu = Gtk.Menu()
        link = self.link_at(event)

        def item(label: str, callback: Callable[[], object], sensitive: bool = True) -> None:
            entry = Gtk.MenuItem(label=label, use_underline=True, sensitive=sensitive)
            entry.connect('activate', lambda _item: callback())
            menu.append(entry)

        if link:
            item(_('_Open Link'), lambda: self.open_link(link))
            item(_('Copy _Link'), lambda: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(link, -1))
            menu.append(Gtk.SeparatorMenuItem())
        item(_('_Copy'), self.copy, self.term.get_has_selection())
        item(_('_Paste'), self.paste)
        menu.append(Gtk.SeparatorMenuItem())
        item(_('Split _Right'), lambda: self.split(Gtk.Orientation.HORIZONTAL))
        item(_('Split _Down'), lambda: self.split(Gtk.Orientation.VERTICAL))
        menu.append(Gtk.SeparatorMenuItem())
        item(_('Close _Pane'), self.close)
        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_pointer(event)
