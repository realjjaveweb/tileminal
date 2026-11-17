"""Running as a snap.

The snap brings its own Python, GTK and VTE; ``prepare`` points them at the libraries inside the snap
before GTK is loaded. Shells started in the terminal must not see any of that, so ``shell_command``
starts them with the user's own environment.
"""

from __future__ import annotations

import glob
import os

_original: dict[str, str | None] = {}


def in_snap() -> bool:
    return bool(os.environ.get('SNAP'))


def _set(name: str, value: str | None) -> None:
    _original.setdefault(name, os.environ.get(name))
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def prepare() -> None:
    """Set up the bundled GTK. Does nothing outside a snap, and only runs once."""
    snap = os.environ.get('SNAP')
    if not snap or _original:
        return
    libs = sorted(glob.glob(f'{snap}/usr/lib/*-linux-gnu*'))
    if not libs:
        return
    lib = libs[0]
    _set('GI_TYPELIB_PATH', f'{lib}/girepository-1.0')
    _set('GDK_PIXBUF_MODULE_FILE', f'{lib}/gdk-pixbuf-2.0/2.10.0/loaders.cache')
    _set('GIO_MODULE_DIR', f'{lib}/gio/modules')
    _set('GTK_PATH', f'{lib}/gtk-3.0')
    _set('GTK_EXE_PREFIX', f'{snap}/usr')
    # Modules of the desktop's GTK are built against its libraries, not the ones in the snap
    _set('GTK_MODULES', None)
    # Themes, icons and settings schemas still come from the desktop
    host_dirs = os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    _set('XDG_DATA_DIRS', f'{snap}/usr/share:{host_dirs}')


def _without_snap(value: str, snap: str) -> str:
    return ':'.join(part for part in value.split(':') if part and not part.startswith(snap))


def shell_command(argv: list[str]) -> list[str]:
    """``argv`` as is outside a snap; inside one, wrapped so it runs with the user's own environment."""
    snap = os.environ.get('SNAP')
    if not snap:
        return argv
    args = ['/usr/bin/env']
    for name, value in _original.items():
        args += ['-u', name] if value is None else [f'{name}={value}']
    for name, value in os.environ.items():
        if name in _original:
            continue
        if name == 'SNAP' or name.startswith('SNAP_'):
            args += ['-u', name]
        elif snap in value:
            # e.g. PATH with the snap's folders added in front
            cleaned = _without_snap(value, snap)
            args += [f'{name}={cleaned}'] if cleaned else ['-u', name]
    return [*args, *argv]
