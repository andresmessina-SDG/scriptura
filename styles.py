"""Application stylesheet loader.

All static CSS for Scriptura lives in `data/style.css`. This module
loads it once at application startup. Per-pane dynamic CSS (font
family, size, line spacing, user-chosen text color) stays in pane.py
because it depends on runtime settings — see `BiblePane._update_font_css`.

`data/style-hc.css` rides alongside it, attached and detached as the desktop's
high-contrast setting changes.
"""

from __future__ import annotations

import logging
import os

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GObject, Gtk

_log = logging.getLogger('scriptura.styles')

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
_STYLE_PATH = os.path.join(_DATA, 'style.css')
_HC_PATH = os.path.join(_DATA, 'style-hc.css')

_loaded = False
_hc_provider: Gtk.CssProvider | None = None
_hc_attached = False


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
    _follow_reduced_motion(provider)
    provider.load_from_path(_STYLE_PATH)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _loaded = True
    _watch_high_contrast(display)


def _follow_reduced_motion(provider: Gtk.CssProvider) -> None:
    """Make `@media (prefers-reduced-motion: reduce)` in style.css live.

    GTK 4.22 answers that query from the PROVIDER's own
    `prefers-reduced-motion` property, which an application provider must
    set itself; the desktop's preference arrives on GtkSettings. Bound, the
    block follows the desktop switch while the app runs (measured)."""
    gtk_settings = Gtk.Settings.get_default()
    if (gtk_settings is None or provider.find_property(
            'prefers-reduced-motion') is None):
        return
    gtk_settings.bind_property(
        'gtk-interface-reduced-motion', provider, 'prefers-reduced-motion',
        GObject.BindingFlags.SYNC_CREATE)


def _watch_high_contrast(display: Gdk.Display) -> None:
    """Follow the desktop's high-contrast setting with `data/style-hc.css`.

    An app has to do this by hand. GTK 4.22 accepts
    `@media (prefers-contrast: more)` from an application provider without a
    parse error and then applies nothing inside it — measured at every provider
    priority — so the query that libadwaita's own stylesheet uses is not
    available to us."""
    global _hc_provider
    if not os.path.isfile(_HC_PATH):
        _log.error('high-contrast stylesheet missing: %s', _HC_PATH)
        return
    _hc_provider = Gtk.CssProvider()
    _hc_provider.load_from_path(_HC_PATH)
    manager = Adw.StyleManager.get_default()
    manager.connect('notify::high-contrast',
                    lambda *_args: _apply_high_contrast(display, manager))
    _apply_high_contrast(display, manager)


def _apply_high_contrast(display: Gdk.Display,
                         manager: Adw.StyleManager) -> None:
    global _hc_attached
    wanted = manager.get_high_contrast()
    if wanted == _hc_attached or _hc_provider is None:
        return
    if wanted:
        # One step above the base sheet: an hc rule then wins on provider
        # priority and does not have to out-specify what it corrects — which
        # matters, because .reading-page-flush is more specific than the
        # .reading-page edge the hc sheet puts back.
        Gtk.StyleContext.add_provider_for_display(
            display, _hc_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    else:
        Gtk.StyleContext.remove_provider_for_display(display, _hc_provider)
    _hc_attached = wanted



_reading_provider: Gtk.CssProvider | None = None

#: The reading size the surfaces below were drawn for before they followed
#: it (settings' default), so they look as before at that size.
_BASE_READING_PT = 12.5


def _ui_font_pt() -> float:
    gtk_settings = Gtk.Settings.get_default()
    name = gtk_settings.get_property('gtk-font-name') if gtk_settings else ''
    try:
        return float((name or '').rsplit(' ', 1)[1])
    except (IndexError, ValueError):
        return 11.0


def chip_pt(reading_pt: float, ui_pt: float) -> float:
    """Cross-reference chip size for a reading size. Never below the
    interface size, and above the default it grows as the square root, so
    twice the text gives 1.41 times the chips, not a giant bar."""
    return float(ui_pt * max(1.0, reading_pt / _BASE_READING_PT) ** 0.5)


def reading_size_css(reading_pt: float, ui_pt: float) -> str:
    pt = min(max(float(reading_pt), 8.0), 26.0)
    return (f'.peek-reading {{ font-size: {pt:g}pt; }} '
            '.crossref-bar button.xref-chip '
            f'{{ font-size: {chip_pt(pt, ui_pt):.1f}pt; }}')


def set_reading_size(reading_pt: float) -> None:
    """Size the text that sits beside the reading text to the reader's size:
    the footnote and note peeks' bodies in full, the cross-reference chips
    by chip_pt. They are not under the pane's own provider (a popover, a
    window-level bar), so they get one on the display."""
    global _reading_provider
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _reading_provider is None:
        _reading_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            display, _reading_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
    _reading_provider.load_from_data(
        reading_size_css(reading_pt, _ui_font_pt()).encode())
