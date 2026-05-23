#!/bin/sh
#
# Wrapper for Flatpak. The .desktop file's Exec= invokes this name
# (page.codeberg.andresmessina.Scriptura → /app/bin/page.codeberg.andresmessina.Scriptura,
# resolved by Flatpak's wrapper). Python's local-imports-from-script's-dir
# behavior means we just point at main.py and the other modules
# (window.py, pane.py, paths.py, etc.) load cleanly from the same
# /app/share/scriptura/ directory.

exec python3 /app/share/scriptura/main.py "$@"
