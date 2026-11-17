"""File locations and crash-safe writing."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from tileminal import APP_SLUG

HOME = os.path.expanduser('~')


def xdg_dir(variable: str, fallback: str) -> Path:
    """The app's folder inside an XDG base directory, e.g. ``~/.config/tileminal``."""
    base = os.environ.get(variable) or os.path.join(HOME, fallback)
    return Path(base) / APP_SLUG


def config_dir() -> Path:
    return xdg_dir('XDG_CONFIG_HOME', '.config')


def state_dir() -> Path:
    return xdg_dir('XDG_STATE_HOME', '.local/state')


def shorten_home(path: str) -> str:
    """A path inside the home folder written as ``~/...``."""
    if path == HOME:
        return '~'
    if path.startswith(HOME + os.sep):
        return '~' + path[len(HOME) :]
    return path


def fsync_dir(path: Path) -> None:
    """Make a rename inside ``path`` durable. Best effort: not every file system supports it."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_verified(path: Path, text: str) -> Path:
    """Write ``text`` to a temporary file next to ``path``, flush it to disk and read it back.

    Returns the temporary file, which the caller renames over ``path`` once it is ready to do so.
    Nothing is left behind when anything fails.
    """
    data = text.encode('utf-8')
    tmp = path.with_name(f'{path.name}.tmp-{os.getpid()}')
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if tmp.read_bytes() != data:
            raise OSError(f'{tmp} does not contain what was written')
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return tmp


def replace_verified(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` atomically; the old content stays if anything goes wrong."""
    os.replace(write_verified(path, text), path)
    fsync_dir(path.parent)
