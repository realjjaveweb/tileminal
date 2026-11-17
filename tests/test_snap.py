import os
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from tileminal import snap


@pytest.fixture(autouse=True)
def fresh_state() -> Iterator[None]:
    snap._original.clear()
    yield
    snap._original.clear()


def test_outside_a_snap_nothing_changes() -> None:
    with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}, clear=True):
        snap.prepare()
        assert snap.shell_command(['/bin/bash']) == ['/bin/bash']
        assert dict(os.environ) == {'PATH': '/usr/bin'}


def test_shells_get_the_users_environment_back(tmp_path: Path) -> None:
    root = str(tmp_path)
    (tmp_path / 'usr/lib/x86_64-linux-gnu').mkdir(parents=True)
    environment = {
        'SNAP': root,
        'SNAP_NAME': 'tileminal',
        'PATH': f'{root}/usr/bin:{root}/bin:/usr/local/bin:/usr/bin',
        'XDG_DATA_DIRS': '/usr/share',
        'GTK_MODULES': 'canberra-gtk-module',
        'HOME': '/var/lib/someone',
    }
    with mock.patch.dict(os.environ, environment, clear=True):
        snap.prepare()
        assert os.environ['GI_TYPELIB_PATH'].startswith(root)
        assert 'GTK_MODULES' not in os.environ
        command = snap.shell_command(['/bin/bash'])

    assert command[0] == '/usr/bin/env'
    assert command[-1] == '/bin/bash'
    options = command[1:-1]
    assert 'PATH=/usr/local/bin:/usr/bin' in options
    assert 'XDG_DATA_DIRS=/usr/share' in options
    assert 'GTK_MODULES=canberra-gtk-module' in options
    unset = {options[i + 1] for i, option in enumerate(options) if option == '-u'}
    assert {'SNAP', 'SNAP_NAME', 'GI_TYPELIB_PATH', 'GDK_PIXBUF_MODULE_FILE'} <= unset
    assert not any(option.startswith('HOME') for option in options)
