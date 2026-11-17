# Changelog

## 1.0.0 - 2026-11-17

First release.

- Tabs, windows and splits with draggable dividers
- Pane title rows with rename, split, maximize and close; drag a pane by its title to move or swap it
- Names for windows, tabs and panes, defaulting to the terminal title
- Session restore of every window, tab, split and working directory after logout, reboot or a crash
- Quit All, and the dock's Quit, keep everything; closing the last window keeps it when it has splits or tabs
- Recently Closed panes, tabs and windows, shown as a tree of their tabs, splits and folders
- Session files: save a tab to a file, open one as a tab
- Session file written atomically after a read-back check, with the previous versions kept
- Settings file with font, colours, cursor, scrollback and history sizes
- Installer with optional pinning to the dock, and a snap package recipe
- Ready for translations (gettext), with a template of all UI texts
