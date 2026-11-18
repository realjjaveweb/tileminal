"""Turning settings into GTK things: colours, fonts, the dark header bar and the app's CSS."""

from __future__ import annotations

from tileminal._gi import Gdk, Gio, Gtk, Pango, Vte
from tileminal.config import COLOR_SCHEMES, DEFAULT_SCHEME, Config

CURSOR_SHAPES = {
    'block': Vte.CursorShape.BLOCK,
    'ibeam': Vte.CursorShape.IBEAM,
    'underline': Vte.CursorShape.UNDERLINE,
}

CSS = """
.tileminal-pane.split { border: 2px solid @theme_bg_color; }
/* Neutral and theme-aware: clearly visible, no accent colour */
.tileminal-pane.split.active { border-color: mix(@theme_fg_color, @theme_bg_color, 0.45); }
.tileminal-pane-header { background-color: @theme_bg_color; }
.tileminal-pane-header button { padding: 0 4px; min-height: 22px; min-width: 22px; }
.tileminal-pane-header label.title { font-size: 0.9em; opacity: 0.65; }
.tileminal-pane.active .tileminal-pane-header label.title { font-weight: bold; opacity: 1; }
button.tileminal-arrow { padding: 0 3px; min-width: 16px; min-height: 16px; }
notebook tab button.tileminal-arrow,
headerbar button.tileminal-arrow { padding: 0 2px; min-width: 16px; min-height: 16px; margin: 0; }
notebook > header.top > tabs > tab { padding: 2px 8px; }
notebook > header.top > tabs > tab:checked {
    box-shadow: inset 0 -3px mix(@theme_fg_color, @theme_bg_color, 0.45);
}
"""

_css_provider: Gtk.CssProvider | None = None


DESKTOP_SCHEMA = 'org.gnome.desktop.interface'


def desktop_setting(key: str) -> str | None:
    # GSettings does not raise for a missing schema or key, it aborts the whole process, so both are looked up
    # first. The GNOME schema is absent on minimal systems and on CI runners, and older versions lack some keys.
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(DESKTOP_SCHEMA, True) if source is not None else None
    if schema is None or not schema.has_key(key):
        return None
    try:
        return Gio.Settings.new(DESKTOP_SCHEMA).get_string(key)
    except Exception:  # e.g. a key of another type
        return None


def rgba(spec: object, fallback: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not (isinstance(spec, str) and color.parse(spec)):
        color.parse(fallback)
    return color


def colors(config: Config) -> tuple[Gdk.RGBA, Gdk.RGBA, list[Gdk.RGBA]]:
    """Foreground, background and palette of the configured scheme."""
    scheme, base = config.color_scheme(), COLOR_SCHEMES[DEFAULT_SCHEME]
    return (
        rgba(scheme['foreground'], base['foreground']),
        rgba(scheme['background'], base['background']),
        [rgba(color, '#000000') for color in scheme['palette']],
    )


def font(config: Config) -> Pango.FontDescription:
    return Pango.FontDescription.from_string(config['font'] or desktop_setting('monospace-font-name') or 'Monospace 11')


def is_dark(color: Gdk.RGBA) -> bool:
    return 0.2126 * color.red + 0.7152 * color.green + 0.0722 * color.blue < 0.5


def apply_theme_variant(config: Config) -> None:
    """A dark colour scheme gets the dark header bar, whatever the desktop style, so the window is all dark."""
    _, background, _ = colors(config)
    dark = is_dark(background) or desktop_setting('color-scheme') == 'prefer-dark'
    Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', dark)


def install_css() -> None:
    global _css_provider
    if _css_provider is None:
        _css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), _css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    _css_provider.load_from_data(CSS.encode())
