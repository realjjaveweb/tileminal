"""The GObject introspection libraries in the versions the app is written for.

Versions have to be chosen before the first import from ``gi.repository``, so every UI module
imports the libraries from here.
"""

import gi

from tileminal import snap

# Inside a snap the bundled libraries have to be set up before GTK is loaded
snap.prepare()

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('Vte', '2.91')

from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo, Vte  # noqa: E402

# Unix signal handling is moving from GLib to GLibUnix; some systems have the GLibUnix namespace
# without its signal helper in the Python bindings, so callers must check the function itself
try:
    gi.require_version('GLibUnix', '2.0')
    from gi.repository import GLibUnix  # noqa: E402
except (ImportError, ValueError):
    GLibUnix = None

__all__ = ['Gdk', 'Gio', 'GLib', 'GLibUnix', 'Gtk', 'Pango', 'PangoCairo', 'Vte']
