#!/bin/sh
# Installs Tileminal for the current user: a `tileminal` command, the app menu entry and the icon.
# Nothing else is copied; the command runs the code from this folder.
#
#   sh install.sh              install, and ask whether to pin it to the dock
#   sh install.sh --pin        install and pin it to the dock without asking
#   sh install.sh --no-pin     install without asking about the dock
#   sh install.sh --uninstall  remove all of it again (settings and the saved session stay)
set -eu

app_id=io.github.realjjaveweb.Tileminal
here=$(cd "$(dirname "$0")" && pwd)
data_home=${XDG_DATA_HOME:-$HOME/.local/share}
bin_dir=$HOME/.local/bin
command=$bin_dir/tileminal
desktop=$data_home/applications/$app_id.desktop
icon=$data_home/icons/hicolor/scalable/apps/$app_id.svg

refresh() {
    update-desktop-database -q "$data_home/applications" 2>/dev/null || true
    gtk-update-icon-cache -q -t "$data_home/icons/hicolor" 2>/dev/null || true
}

# Adds (add) or removes (remove) the app on the GNOME dock; does nothing on other desktops
dock() {
    gsettings get org.gnome.shell favorite-apps >/dev/null 2>&1 || return 0
    favorites=$(gsettings get org.gnome.shell favorite-apps)
    updated=$(python3 -c '
import ast, sys
action, app, text = sys.argv[1:]
apps = ast.literal_eval(text.removeprefix("@as "))
apps = [a for a in apps if a != app] + ([app] if action == "add" else [])
print(repr(apps))
' "$1" "$app_id.desktop" "$favorites")
    gsettings set org.gnome.shell favorite-apps "$updated"
}

case "${1:-}" in
    --uninstall)
        rm -f "$command" "$desktop" "$icon"
        dock remove
        refresh
        echo "Tileminal uninstalled."
        exit 0
        ;;
    --pin) pin=yes ;;
    --no-pin) pin=no ;;
    '') pin=ask ;;
    *)
        echo "Unknown option: $1 (see the top of install.sh)" >&2
        exit 2
        ;;
esac

python3 -c "
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Vte', '2.91')
from gi.repository import Gtk, Vte
" 2>/dev/null || {
    echo "GTK 3 and VTE for Python are missing. On Ubuntu or Debian:" >&2
    echo "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91" >&2
    exit 1
}

mkdir -p "$bin_dir" "$(dirname "$desktop")" "$(dirname "$icon")"
# Downloads (e.g. a zip from GitHub) can lose the executable flag
chmod +x "$here/tileminal"
ln -sf "$here/tileminal" "$command"
cp "$here/data/$app_id.desktop" "$desktop"
cp "$here/data/$app_id.svg" "$icon"
refresh
echo "Tileminal installed: find it in the app menu, or run 'tileminal'."

if [ "$pin" = ask ] && [ -t 0 ] && gsettings get org.gnome.shell favorite-apps >/dev/null 2>&1; then
    printf 'Pin Tileminal to the dock? [Y/n] '
    read -r answer
    case "$answer" in
        [nN]*) pin=no ;;
        *) pin=yes ;;
    esac
fi
if [ "$pin" = yes ]; then
    dock add
    echo "Pinned to the dock."
fi

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) echo "Note: $bin_dir is not in PATH yet; it is after logging in again." ;;
esac
