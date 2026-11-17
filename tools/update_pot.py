#!/usr/bin/env python3
"""Collects the translatable strings into po/tileminal.pot.

Translatable strings are the literal arguments of ``_()`` and ``ngettext()`` in src/tileminal.
Translators copy the template to po/<language>.po; ``msgfmt`` (from gettext) compiles it to
src/tileminal/locale/<language>/LC_MESSAGES/tileminal.mo.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / 'src' / 'tileminal'
TEMPLATE = ROOT / 'po' / 'tileminal.pot'

HEADER = '''msgid ""
msgstr ""
"Project-Id-Version: tileminal\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=INTEGER; plural=EXPRESSION;\\n"
'''


def quote(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def collect() -> dict[tuple[str, ...], list[str]]:
    """Message (singular, or singular and plural) -> where it is used."""
    messages: dict[tuple[str, ...], list[str]] = {}
    for path in sorted(SOURCES.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            count = {'_': 1, 'ngettext': 2}.get(node.func.id)
            texts = [arg.value for arg in node.args[: count or 0] if isinstance(arg, ast.Constant)]
            if count and len(texts) == count and all(isinstance(text, str) for text in texts):
                location = f'{path.relative_to(ROOT)}:{node.lineno}'
                messages.setdefault(tuple(texts), []).append(location)
    return messages


def render(messages: dict[tuple[str, ...], list[str]]) -> str:
    entries = [HEADER]
    for texts, locations in messages.items():
        lines = [f'#: {" ".join(locations)}', f'msgid {quote(texts[0])}']
        if len(texts) == 2:
            lines += [f'msgid_plural {quote(texts[1])}', 'msgstr[0] ""', 'msgstr[1] ""']
        else:
            lines.append('msgstr ""')
        entries.append('\n'.join(lines) + '\n')
    return '\n'.join(entries)


def main() -> int:
    text = render(collect())
    if '--check' in sys.argv:
        # For CI: fail when the template is out of date
        return 0 if TEMPLATE.exists() and TEMPLATE.read_text(encoding='utf-8') == text else 1
    TEMPLATE.write_text(text, encoding='utf-8')
    print(f'{TEMPLATE.relative_to(ROOT)}: {len(text.split(chr(10) + "msgid ")) - 1} messages')
    return 0


if __name__ == '__main__':
    sys.exit(main())
