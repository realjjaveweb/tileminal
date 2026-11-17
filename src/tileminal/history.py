"""The Recently Closed popover: closed panes, tabs and windows as an expandable tree."""

from __future__ import annotations

import time
from html import escape
from typing import TYPE_CHECKING

from tileminal._gi import Gtk, Pango
from tileminal.files import HOME, shorten_home
from tileminal.i18n import _, ngettext
from tileminal.model import Node
from tileminal.session import ClosedEntry

if TYPE_CHECKING:
    from tileminal.app import Application

ENTRY_ID, MARKUP = 0, 1


def dim(markup: str) -> str:
    return f'<span alpha="60%">{markup}</span>'


KIND_NAMES = {'pane': _('Pane'), 'tab': _('Tab'), 'window': _('Window')}


def entry_heading(entry: ClosedEntry) -> str:
    when = time.strftime('%H:%M', time.localtime(entry['closedAt']))
    kind = KIND_NAMES[entry['kind']]
    if entry['kind'] == 'window':
        count = len(entry['data']['tabs'])
        kind = ngettext('Window, {count} tab', 'Window, {count} tabs', count).format(count=count)
    return f'<b>{escape(entry["label"])}</b>  {dim(escape(f"{kind} · {when}"))}'


def pane_markup(node: Node) -> str:
    """A pane's folder, after its own name when it has one."""
    directory = escape(shorten_home(node.get('directory') or HOME))
    title = node.get('title')
    return f'{escape(title)}  {dim(directory)}' if title else directory


def split_markup(node: Node) -> str:
    return dim(_('side by side') if node['orientation'] == 0 else _('stacked'))


class HistoryPopover(Gtk.Popover):
    """Every closed entry is a top-level row; below it are its tabs, splits and panes.
    Clicking any row reopens the entry it belongs to."""

    def __init__(self, app: Application, relative_to: Gtk.Widget) -> None:
        super().__init__(relative_to=relative_to, position=Gtk.PositionType.BOTTOM)
        self.app = app
        self.connect('closed', lambda _popover: self.destroy())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        heading = Gtk.Label(label=_('Recently Closed'), xalign=0)
        heading.get_style_context().add_class('dim-label')
        box.pack_start(heading, False, False, 0)

        if app.closed:
            box.pack_start(self._tree(app.closed), True, True, 0)
            clear = Gtk.Button(label=_('Clear List'), halign=Gtk.Align.END, relief=Gtk.ReliefStyle.NONE)
            clear.connect('clicked', self.on_clear)
            box.pack_start(clear, False, False, 0)
        else:
            empty = Gtk.Label(label=_('Nothing closed yet'), margin=12)
            empty.get_style_context().add_class('dim-label')
            box.pack_start(empty, False, False, 0)
        self.add(box)
        box.show_all()

    def _tree(self, entries: list[ClosedEntry]) -> Gtk.Widget:
        store = Gtk.TreeStore(str, str)
        for entry in entries:
            row = store.append(None, [entry['id'], entry_heading(entry)])
            self._add_children(store, row, entry)

        view = Gtk.TreeView(model=store, headers_visible=False, activate_on_single_click=True, enable_search=False)
        renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        view.append_column(Gtk.TreeViewColumn('', renderer, markup=MARKUP))
        view.get_selection().set_mode(Gtk.SelectionMode.NONE)
        view.expand_all()
        view.connect('row-activated', self.on_row_activated)

        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True, max_content_height=520
        )
        scroller.set_size_request(440, -1)
        scroller.add(view)
        return scroller

    def _add_children(self, store: Gtk.TreeStore, parent: Gtk.TreeIter, entry: ClosedEntry) -> None:
        kind, data, entry_id = entry['kind'], entry['data'], entry['id']
        if kind == 'window':
            for tab in data['tabs']:
                name = tab.get('name') or ''
                label = name if name and '${' not in name else _('Tab')
                tab_row = store.append(parent, [entry_id, escape(label)])
                self._add_node(store, tab_row, tab['child'], entry_id)
        elif kind == 'tab':
            self._add_node(store, parent, data['child'], entry_id)
        else:
            store.append(parent, [entry_id, pane_markup(data)])

    def _add_node(self, store: Gtk.TreeStore, parent: Gtk.TreeIter, node: Node, entry_id: str) -> None:
        if node.get('type') == 'Terminal':
            store.append(parent, [entry_id, pane_markup(node)])
            return
        split_row = store.append(parent, [entry_id, split_markup(node)])
        self._add_node(store, split_row, node['child1'], entry_id)
        self._add_node(store, split_row, node['child2'], entry_id)

    def on_row_activated(self, view: Gtk.TreeView, path: Gtk.TreePath, _column: Gtk.TreeViewColumn) -> None:
        entry_id = view.get_model()[path][ENTRY_ID]
        self.popdown()
        self.app.reopen(entry_id)

    def on_clear(self, _button: Gtk.Button) -> None:
        self.app.clear_closed()
        self.popdown()
