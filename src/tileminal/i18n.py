"""Translations. Strings shown in the UI go through ``_`` (and ``ngettext`` for counts).

Translations live in ``locale/<language>/LC_MESSAGES/tileminal.mo`` inside the package; without
one for the desktop's language the English text is shown.
"""

from __future__ import annotations

import gettext
from importlib import resources

from tileminal import APP_SLUG

_translation = gettext.translation(APP_SLUG, localedir=str(resources.files('tileminal') / 'locale'), fallback=True)

_ = _translation.gettext
ngettext = _translation.ngettext
