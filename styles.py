"""Application stylesheet loader.

All static CSS for Scriptura lives in `data/style.css`. This module
loads it once at application startup. Per-pane dynamic CSS (font
family, size, line spacing, user-chosen text color) stays in pane.py
because it depends on runtime settings — see `BiblePane._update_font_css`.
"""

from __future__ import annotations

import logging
import os

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gtk

_log = logging.getLogger('scriptura.styles')

_STYLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'data', 'style.css')

_loaded = False


def load_app_css() -> None:
    """Load `data/style.css` into the default display's style provider list.
    Idempotent — only attaches the provider once per process. Safe to call
    before a Gdk.Display exists (no-op in that case)."""
    global _loaded
    if _loaded:
        return
    display = Gdk.Display.get_default()
    if display is None:
        # Called too early. The caller is main.py after Adw.Application
        # is constructed; if we somehow land here without a display, bail
        # rather than crash — startup will continue, just unstyled.
        _log.warning('no default display when loading CSS — skipping')
        return
    if not os.path.isfile(_STYLE_PATH):
        _log.error('stylesheet missing: %s', _STYLE_PATH)
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(_STYLE_PATH)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _loaded = True
