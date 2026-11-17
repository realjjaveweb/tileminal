"""The terminal window: header bar, tabs, splitting and closing panes, keyboard shortcuts."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from tileminal import APP_NAME
from tileminal._gi import Gdk, Gio, GLib, Gtk, Pango
from tileminal.dragging import PaneMover, widget_rect
from tileminal.files import HOME
from tileminal.geometry import Direction, nearest
from tileminal.history import HistoryPopover
from tileminal.i18n import _
from tileminal.layout import Split, Tab, build_tree, replace_child
from tileminal.model import ACTIVE_PANE_KEY, AUTO_TAB_NAME, Node
from tileminal.pane import Pane
from tileminal.session_files import open_session_file, save_session_file
from tileminal.widgets import arrow_button, icon_button, rename_popover

if TYPE_CHECKING:
    from tileminal.app import Application

HORIZONTAL, VERTICAL = Gtk.Orientation.HORIZONTAL, Gtk.Orientation.VERTICAL
CTRL, SHIFT, ALT = Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SHIFT_MASK, Gdk.ModifierType.MOD1_MASK
DEFAULT_SIZE = (1000, 650)
ZOOM_KEYS = {'plus': 1, 'equal': 1, 'kp_add': 1, 'minus': -1, 'kp_subtract': -1, '0': 0, 'kp_0': 0}


class TerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Application, data: dict[str, Any] | None = None, cwd: str | None = None) -> None:
        super().__init__(application=app)
        self.app = app
        self.mover = PaneMover(self)
        self.normal_size = DEFAULT_SIZE
        # Set once the window is on its way out, so it is no longer part of the saved session
        self.closing = False

        self.header = Gtk.HeaderBar(show_close_button=True)
        self.set_titlebar(self.header)
        self._build_title()
        self._build_header_buttons()
        self._add_actions()

        self.notebook = Gtk.Notebook(scrollable=True, show_border=False)
        self.notebook.connect('switch-page', self.on_switch_page)
        self.notebook.connect('page-reordered', lambda *_args: self.app.schedule_save())
        self.notebook.connect('page-added', lambda *_args: self.update_tabs_visibility())
        self.notebook.connect('page-removed', lambda *_args: self.update_tabs_visibility())
        self.add(self.notebook)

        self.connect('key-press-event', self.on_key_press)
        self.connect('delete-event', self.on_delete)
        self.connect('configure-event', self.on_configure)
        self.connect('window-state-event', lambda *_args: self.app.schedule_save())

        if data:
            self._restore(data)
        else:
            self.add_tab(cwd=cwd)
        self.set_default_size(*self.normal_size)
        self.notebook.show()
        self.header.show_all()
        GLib.idle_add(self.focus_active)

    def _build_title(self) -> None:
        # With a single tab there is no tab bar, so the tab's rename arrow sits next to the window title
        menu = Gio.Menu()
        menu.append(_('Rename…'), 'win.rename-tab')
        self.title_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END)
        self.title_label.get_style_context().add_class('title')
        self.title_arrow = arrow_button(menu)
        box = Gtk.Box(spacing=2)
        box.pack_start(self.title_label, False, False, 0)
        box.pack_start(self.title_arrow, False, False, 0)
        box.show_all()
        self.title_arrow.set_no_show_all(True)
        self.header.set_custom_title(box)

    def _build_header_buttons(self) -> None:
        for icon, tooltip, action in (
            ('tileminal-split-right-symbolic', _('Split Right (Ctrl+Shift+E)'), 'win.split-right'),
            ('tileminal-split-down-symbolic', _('Split Down (Ctrl+Shift+O)'), 'win.split-down'),
            ('tileminal-tab-new-symbolic', _('New Tab (Ctrl+Shift+T)'), 'win.new-tab'),
        ):
            if action == 'win.new-tab':
                self.header.pack_start(Gtk.Separator(orientation=VERTICAL))
            button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            button.set_tooltip_text(tooltip)
            button.set_action_name(action)
            self.header.pack_start(button)

        menu = Gio.Menu()
        for section in (
            [(_('New Window'), 'app.new-window'), (_('Recently Closed'), 'win.show-closed')],
            [
                (_('Open Tilix Session…'), 'win.open-session-file'),
                (_('Save Tab as Tilix Session…'), 'win.save-session-file'),
            ],
            [(_('Zoom In'), 'win.zoom-in'), (_('Zoom Out'), 'win.zoom-out'), (_('Normal Size'), 'win.zoom-reset')],
            [(_('Open Config File'), 'app.open-config'), (_('Reload Config'), 'app.reload-config')],
            [(_('Quit All'), 'app.quit')],
        ):
            items = Gio.Menu()
            for label, action in section:
                items.append(label, action)
            menu.append_section(None, items)
        menu_button = Gtk.MenuButton(menu_model=menu)
        menu_button.set_image(Gtk.Image.new_from_icon_name('tileminal-menu-symbolic', Gtk.IconSize.BUTTON))
        self.header.pack_end(menu_button)

        self.history_button = Gtk.Button.new_from_icon_name('tileminal-history-symbolic', Gtk.IconSize.BUTTON)
        self.history_button.set_tooltip_text(_('Recently Closed'))
        self.history_button.set_action_name('win.show-closed')
        self.header.pack_end(self.history_button)

    def _add_actions(self) -> None:
        actions: dict[str, Callable[[], object]] = {
            'new-tab': lambda: self.add_tab(cwd=self.current_cwd()),
            'rename-tab': lambda: self.rename_tab(self.current_tab()),
            'show-closed': lambda: HistoryPopover(self.app, self.history_button).popup(),
            'split-right': lambda: self.split(self.active_pane(), HORIZONTAL),
            'split-down': lambda: self.split(self.active_pane(), VERTICAL),
            'close-pane': lambda: self.close_pane(self.active_pane()),
            'open-session-file': lambda: open_session_file(self),
            'save-session-file': lambda: save_session_file(self),
            'zoom-in': lambda: self.zoom(1),
            'zoom-out': lambda: self.zoom(-1),
            'zoom-reset': lambda: self.zoom(0),
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _action, _param, cb=callback: cb())
            self.add_action(action)

    def _restore(self, data: dict[str, Any]) -> None:
        width, height = data.get('width'), data.get('height')
        if isinstance(width, int) and isinstance(height, int) and width > 100 and height > 100:
            self.normal_size = (width, height)
        for tab in data['tabs']:
            self.add_tab(layout=tab, focus=False)
        index = data.get('activeTab', 0)
        if isinstance(index, int) and 0 <= index < self.notebook.get_n_pages():
            self.notebook.set_current_page(index)
        if data.get('maximized'):
            self.maximize()

    # --- tabs

    def tabs(self) -> list[Tab]:
        return [self.notebook.get_nth_page(i) for i in range(self.notebook.get_n_pages())]

    def current_tab(self) -> Tab | None:
        page = self.notebook.get_current_page()
        return self.notebook.get_nth_page(page) if page >= 0 else None

    def active_pane(self) -> Pane | None:
        tab = self.current_tab()
        return tab.focused_pane() if tab else None

    def current_cwd(self) -> str:
        pane = self.active_pane()
        return pane.cwd() if pane else HOME

    def add_tab(self, cwd: str | None = None, layout: Node | None = None, focus: bool = True) -> Tab:
        if layout:
            tab = Tab(build_tree(self.app, layout['child']), tab_id=layout.get('uuid'), name=layout.get('name'))
            wanted = layout.get(ACTIVE_PANE_KEY)
            tab.active_pane = next((pane for pane in tab.panes() if pane.uuid == wanted), None)
        else:
            tab = Tab(Pane(self.app, cwd=cwd))
        index = self.notebook.append_page(tab, self._tab_label(tab))
        self.notebook.set_tab_reorderable(tab, True)
        self.notebook.child_set_property(tab, 'tab-expand', True)
        if focus:
            self.notebook.set_current_page(index)
            GLib.idle_add(self.focus_active)
        self.update_titles()
        self.app.schedule_save()
        return tab

    def _tab_label(self, tab: Tab) -> Gtk.Widget:
        """Title with a rename arrow in the middle, close button on the right."""
        actions = Gio.SimpleActionGroup()
        rename = Gio.SimpleAction.new('rename', None)
        rename.connect('activate', lambda _action, _param: self.rename_tab(tab))
        actions.add_action(rename)
        menu = Gio.Menu()
        menu.append(_('Rename…'), 'tab.rename')
        tab.arrow = arrow_button(menu)

        title = Gtk.Box(spacing=2)
        title.pack_start(tab.label, False, False, 0)
        title.pack_start(tab.arrow, False, False, 0)
        box = Gtk.Box(spacing=2)
        box.set_center_widget(title)
        close = icon_button('tileminal-close-symbolic', _('Close Tab'), lambda: self.close_tab(tab))
        box.pack_end(close, False, False, 0)

        events = Gtk.EventBox(visible_window=False)
        events.insert_action_group('tab', actions)
        events.add(box)
        events.connect('button-press-event', lambda _widget, event: self.on_tab_label_press(tab, event))
        events.show_all()
        return events

    def on_tab_label_press(self, tab: Tab, event: Gdk.EventButton) -> bool:
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.rename_tab(tab)
            return True
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 2:
            self.close_tab(tab)
            return True
        return False

    def rename_tab(self, tab: Tab | None) -> None:
        if tab is None:
            return
        self.notebook.set_current_page(self.notebook.page_num(tab))
        anchor = tab.arrow if self.notebook.get_show_tabs() else self.title_arrow

        def accept(text: str) -> None:
            tab.name = text or AUTO_TAB_NAME
            self.update_titles()
            self.app.schedule_save()

        pane = tab.focused_pane()
        placeholder = pane.title() if pane else ''
        rename_popover(anchor, tab.custom_name(), placeholder, accept, lambda: GLib.idle_add(self.focus_active))

    def close_tab(self, tab: Tab, remember: bool = True) -> None:
        index = self.notebook.page_num(tab)
        if index < 0:
            return
        if remember and tab.root is not None:
            self.app.remember_closed('tab', tab.title(), tab.to_data())
        for pane in tab.panes():
            pane.closing = True
        self.notebook.remove_page(index)
        tab.destroy()
        if not self.notebook.get_n_pages():
            self.close()
            return
        self.app.schedule_save()
        GLib.idle_add(self.focus_active)

    def move_tab(self, step: int) -> None:
        tab, count = self.current_tab(), self.notebook.get_n_pages()
        if tab is None or count < 2:
            return
        self.notebook.reorder_child(tab, (self.notebook.page_num(tab) + step) % count)
        self.app.schedule_save()

    def update_tabs_visibility(self) -> None:
        many = self.notebook.get_n_pages() > 1
        self.notebook.set_show_tabs(many)
        self.title_arrow.set_visible(not many)

    def on_switch_page(self, *_args: object) -> None:
        GLib.idle_add(self.focus_active)
        self.app.schedule_save()

    def focus_active(self) -> bool:
        pane = self.active_pane()
        if pane is not None:
            pane.term.grab_focus()
        self.update_indicators()
        return False

    # --- panes

    def split(self, pane: Pane | None, orientation: Gtk.Orientation, new: Pane | Split | None = None) -> None:
        """Split ``pane`` and put ``new`` (a fresh terminal in the same directory by default) next to it."""
        tab = pane.tab if pane is not None else None
        if pane is None or tab is None:
            return
        self.unmaximize(tab)
        added = new or Pane(self.app, cwd=pane.cwd())
        replace_child(pane.get_parent(), pane, lambda: Split(orientation, pane, added))
        focused = tab.panes(added)[0]
        focused.term.grab_focus()
        tab.active_pane = focused
        self.update_indicators()
        self.app.schedule_save()

    def close_pane(self, pane: Pane | None) -> None:
        """Close one pane; its neighbour takes its place. The last pane of a tab closes the tab."""
        if pane is None:
            return
        tab = pane.tab
        self.unmaximize(tab)
        parent = pane.get_parent()
        if isinstance(parent, Split):
            self.app.remember_closed('pane', pane.title(), pane.to_node())
            pane.closing = True
            sibling = parent.other(pane)
            parent.remove(sibling)
            replace_child(parent.get_parent(), parent, lambda: sibling)
            parent.destroy()
            if tab is not None:
                tab.active_pane = tab.panes(sibling)[0]
            GLib.idle_add(self.focus_active)
            self.app.schedule_save()
        elif tab is not None:
            self.close_tab(tab)

    def toggle_maximize(self, pane: Pane) -> None:
        """Let one pane fill its tab, or bring the others back."""
        tab = pane.tab
        if tab is None:
            return
        if tab.maximized:
            self.unmaximize(tab)
            return
        # Hide the other side of every split on the way up; their ratios are kept for later
        child, parent = pane, pane.get_parent()
        while isinstance(parent, Split):
            parent.freeze_ratio()
            other = parent.other(child)
            other.hide()
            tab.hidden.append(other)
            child, parent = parent, parent.get_parent()
        tab.maximized = tab.active_pane = pane
        pane.term.grab_focus()
        self.update_indicators()

    def unmaximize(self, tab: Tab | None) -> None:
        if tab is None or tab.maximized is None:
            return
        for widget in tab.hidden:
            widget.show()
        tab.hidden = []
        tab.maximized = None
        self.update_indicators()

    def zoom(self, step: int) -> None:
        pane = self.active_pane()
        if pane is not None:
            pane.zoom(step)

    def focus_direction(self, direction: Direction) -> None:
        pane, tab = self.active_pane(), self.current_tab()
        current = widget_rect(pane, self) if pane is not None else None
        if tab is None or current is None:
            return
        candidates = []
        for other in tab.panes():
            rect = widget_rect(other, self) if other is not pane and other.get_mapped() else None
            if rect is not None:
                candidates.append((other, rect))
        target = nearest(current, candidates, direction)
        if target is not None:
            target.focus()

    # --- titles and indicators

    def update_titles(self) -> None:
        for tab in self.tabs():
            text = tab.title()
            tab.label.set_text(text)
            tab.label.set_tooltip_text(text)
            for number, each in enumerate(tab.panes(), 1):
                title = each.title()
                each.header.label.set_text(f'{number}: {title}')
                each.header.label.set_tooltip_text(title)
        current, pane = self.current_tab(), self.active_pane()
        parts = [pane.title()] if pane else []
        # A renamed tab shows its name in the window title too, also when the tab bar is hidden
        if current is not None and current.custom_name():
            parts.insert(0, current.title())
        # The program name comes first, so it is always clear which app a window belongs to
        title = f'{APP_NAME}: ' + ' - '.join(parts) if parts else APP_NAME
        self.set_title(title)
        self.title_label.set_text(title)

    def update_indicators(self) -> None:
        """Pane headers, the focus outline and the maximize buttons, for every tab."""
        always = self.app.config['pane_headers'] == 'always'
        for tab in self.tabs():
            panes = tab.panes()
            focused = tab.focused_pane()
            split = len(panes) > 1
            for pane in panes:
                style = pane.get_style_context()
                for name, on in (('split', split), ('active', pane is focused)):
                    if on:
                        style.add_class(name)
                    else:
                        style.remove_class(name)
                pane.header.set_visible(split or always)
                pane.header.set_maximized(tab.maximized is pane)
        self.update_titles()

    # --- keys

    def on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        state = event.state & (CTRL | SHIFT | ALT)
        key = (Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)) or '').lower()
        if state == CTRL | SHIFT:
            action = self._ctrl_shift_shortcuts().get(key)
            if action is not None:
                action()
                return True
        elif state == CTRL:
            if key in ZOOM_KEYS:
                self.zoom(ZOOM_KEYS[key])
                return True
            count = self.notebook.get_n_pages()
            if key in ('page_up', 'page_down') and count > 1:
                step = -1 if key == 'page_up' else 1
                self.notebook.set_current_page((self.notebook.get_current_page() + step) % count)
                return True
        elif state == ALT:
            if key in ('left', 'right', 'up', 'down'):
                self.focus_direction(cast(Direction, key))
                return True
            if len(key) == 1 and key in '123456789' and int(key) <= self.notebook.get_n_pages():
                self.notebook.set_current_page(int(key) - 1)
                return True
        return False

    def _ctrl_shift_shortcuts(self) -> dict[str, Callable[[], object]]:
        pane = self.active_pane()
        shortcuts: dict[str, Callable[[], object]] = {
            'e': lambda: self.split(pane, HORIZONTAL),
            'o': lambda: self.split(pane, VERTICAL),
            'w': lambda: self.close_pane(pane),
            't': lambda: self.add_tab(cwd=self.current_cwd()),
            'n': lambda: self.app.new_window(cwd=self.current_cwd()),
            'q': self.close,
            'z': self.app.reopen,
            'page_up': lambda: self.move_tab(-1),
            'page_down': lambda: self.move_tab(1),
            'plus': lambda: self.zoom(1),
        }
        if pane is not None:
            shortcuts['c'] = pane.copy
            shortcuts['v'] = pane.paste
        return shortcuts

    # --- window state

    def on_configure(self, *_args: object) -> bool:
        if not self.is_maximized():
            self.normal_size = tuple(self.get_size())
        self.app.schedule_save(delay=1000)
        return False

    def on_delete(self, *_args: object) -> bool:
        self.app.window_closing(self)
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            'width': self.normal_size[0],
            'height': self.normal_size[1],
            'maximized': self.is_maximized(),
            'activeTab': max(0, self.notebook.get_current_page()),
            'tabs': [tab.to_data() for tab in self.tabs() if tab.root is not None],
        }
