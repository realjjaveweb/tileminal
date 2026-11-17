# Contributing

Bug reports, ideas and pull requests are welcome. For bigger changes, open an issue first so we can talk
about it before you spend time on it.

## Setup

The oldest supported Python version is `requires-python` in `pyproject.toml`; the type checker and CI
make sure the code doesn't use anything newer.

```sh
sudo apt install make git
git clone https://github.com/realjjaveweb/tileminal.git
cd tileminal
make setup
```

`make setup` installs GTK 3 and VTE with their Python bindings, the test runner, type checker, formatters and
linter, the headless display for the UI tests, dbus and the translation tools, all from the Ubuntu/Debian
repositories. On other distributions install the equivalents; `pip install pytest mypy black isort flake8`
covers the Python tools.

## Commands

| | |
| --- | --- |
| `make run` | start Tileminal from this folder, with its own settings and session (quit any running Tileminal first) |
| `make fix` | format the code, sort imports, refresh the translation template |
| `make check` | everything CI checks: formatting, lint, types, translation template, all tests |
| `make test` | all tests: `make test-unit` (quick, no GTK) and `make test-ui` (the app on a headless display) |

`make` on its own lists all commands. Before opening a pull request, run `make fix` and then `make check`.

## Tests

- `tests/` - unit tests for the parts without GTK (session file, layout model, geometry, config, snap
  environment). They need nothing but Python and pytest.
- `tests/ui/` - the real app on a headless display. `driver.py` runs scripted scenarios (split, drag,
  close, quit, restore...) and `test_ui.py` checks the results.

The UI tests run in parallel and are isolated from each other and from your own setup:

- every test has its own home, config, state, data and cache folders (under pytest's temporary folder),
  and its terminals run a plain `/bin/bash`, so your shell settings and history are never read or written;
- every app start gets its own D-Bus session, so it can't reach a running Tileminal or another test;
- every parallel worker starts its own headless display on the first free display number;
- scenarios never sleep for a fixed time: each step waits for a named condition ("the shells to start",
  "the shell to change to /tmp"...), so a slow or busy machine makes them slower, not flaky. A wait that
  takes over 15 seconds fails the test with what it was waiting for.

`make test` runs both; `python3 -m pytest tests/ui -k drag` runs a single UI test.

## Code layout

| | |
| --- | --- |
| `src/tileminal/app.py` | the application: windows, saving, what is restored, recently closed |
| `src/tileminal/window.py` | a window: header bar, tabs, splitting and closing panes, shortcuts |
| `src/tileminal/layout.py` | split tree widgets: `Split`, `Tab` |
| `src/tileminal/pane.py` | one terminal with its title row and drop zone |
| `src/tileminal/dragging.py` | moving panes by dragging their title row |
| `src/tileminal/history.py` | the Recently Closed popover |
| `src/tileminal/session_files.py` | saving a tab to a file and opening one |
| `src/tileminal/style.py`, `widgets.py` | colours, fonts, CSS, small shared widgets |
| `src/tileminal/session.py` | the session file: validation, safe saving, history (no GTK) |
| `src/tileminal/model.py`, `geometry.py` | saved layouts and screen math (no GTK) |
| `src/tileminal/config.py`, `files.py`, `snap.py` | settings, file locations, running as a snap (no GTK) |

Code style: black and isort decide formatting (line length 120, single quotes kept), type hints everywhere,
and comments explain why rather than what.

## Translations

UI texts go through `_()` (or `ngettext()` for counts); `make fix` updates the template after changing any.
To add a language:

```sh
cp po/tileminal.pot po/de.po          # then translate the msgstr lines
mkdir -p src/tileminal/locale/de/LC_MESSAGES
msgfmt -o src/tileminal/locale/de/LC_MESSAGES/tileminal.mo po/de.po
```
