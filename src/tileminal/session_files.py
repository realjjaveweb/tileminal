"""Single tabs saved to and opened from session files, from the window menu or the command line."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from tileminal._gi import Gtk
from tileminal.files import replace_verified
from tileminal.i18n import _
from tileminal.model import renew_ids, validate_tab

if TYPE_CHECKING:
    from tileminal.window import TerminalWindow


def open_session_file(window: TerminalWindow) -> None:
    dialog = Gtk.FileChooserNative.new(
        _('Open Tilix Session'), window, Gtk.FileChooserAction.OPEN, _('_Open'), _('_Cancel')
    )
    json_filter = Gtk.FileFilter()
    json_filter.set_name(_('Tilix session (*.json)'))
    json_filter.add_pattern('*.json')
    dialog.add_filter(json_filter)
    if dialog.run() == Gtk.ResponseType.ACCEPT:
        load_session_file(window, dialog.get_filename())
    dialog.destroy()


def load_session_file(window: TerminalWindow, path: str) -> None:
    """Open a session file as a new tab of ``window``."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        validate_tab(data)
    except (OSError, ValueError) as e:
        show_error(window, _('Cannot open {name}').format(name=os.path.basename(path)), str(e))
        return
    # New ids keep two copies of the same file from sharing pane ids
    renew_ids(data['child'])
    data['uuid'] = str(uuid.uuid4())
    window.add_tab(layout=data)


def save_session_file(window: TerminalWindow) -> None:
    tab = window.current_tab()
    if tab is None:
        return
    dialog = Gtk.FileChooserNative.new(
        _('Save Tab as Tilix Session'), window, Gtk.FileChooserAction.SAVE, _('_Save'), _('_Cancel')
    )
    dialog.set_do_overwrite_confirmation(True)
    dialog.set_current_name('session.json')
    if dialog.run() == Gtk.ResponseType.ACCEPT:
        text = json.dumps(tab.to_data(with_size=True), indent=4) + '\n'
        try:
            replace_verified(Path(dialog.get_filename()), text)
        except OSError as e:
            show_error(window, _('Cannot save the session'), str(e))
    dialog.destroy()


def show_error(window: Gtk.Window, title: str, text: str) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=window,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text=title,
        secondary_text=text,
    )
    dialog.run()
    dialog.destroy()
