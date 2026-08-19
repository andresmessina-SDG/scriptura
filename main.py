import gettext
import locale
import logging
import os
import sys
from urllib.parse import unquote
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, Gio


APP_ID = 'io.github.andresmessina_SDG.Scriptura'
# gettext domain — must match i18n.gettext('scriptura') in po/meson.build and
# the installed scriptura.mo, or translations won't load.
GETTEXT_DOMAIN = 'scriptura'


def _setup_logging():
    """Configure the 'scriptura' logger tree. Users debugging SWORD or
    persistence issues can crank verbosity with SCRIPTURA_LOG_LEVEL=DEBUG."""
    level_name = os.environ.get('SCRIPTURA_LOG_LEVEL', 'WARNING').upper()
    level = getattr(logging, level_name, logging.WARNING)
    root = logging.getLogger('scriptura')
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(name)s [%(levelname)s] %(message)s'))
        root.addHandler(handler)
    root.propagate = False


_setup_logging()


def _setup_gettext():
    """Install `_()` as a builtin for the whole app. localedir is resolved
    relative to this file (installed at {prefix}/share/scriptura/, locale at
    {prefix}/share/locale — same __file__-relative trick as the icon search
    path). A missing localedir is fine: gettext falls back to the untranslated
    strings. Done before importing the UI so module-level strings translate."""
    import i18n
    localedir = i18n.localedir()
    # A reader's chosen UI language, when they have overridden the desktop.
    # LANGUAGE is the GNU gettext override and outranks LC_MESSAGES, so it
    # steers the catalogue while leaving dates, numbers and sorting on the
    # desktop's locale — which is what a Spanish reader on an English system
    # actually wants. Must be set before the domain is bound below: gettext
    # resolves the catalogue once, at install time.
    try:
        import settings
        chosen = settings.get('ui_language')
    except Exception:
        chosen = None
    if chosen:
        os.environ['LANGUAGE'] = chosen
    try:
        locale.setlocale(locale.LC_ALL, '')
        locale.bindtextdomain(GETTEXT_DOMAIN, localedir)
        locale.textdomain(GETTEXT_DOMAIN)
    except (locale.Error, AttributeError):
        pass
    # Bind the domain for the gettext module's own functions too, so the
    # importable helpers in i18n.py (which alias gettext.gettext/ngettext)
    # resolve the same catalog as the installed builtins. mypy-strict modules
    # import from i18n.py; the (ignore_errors) UI modules use the builtins.
    gettext.bindtextdomain(GETTEXT_DOMAIN, localedir)
    gettext.textdomain(GETTEXT_DOMAIN)
    # names=['ngettext'] also installs ngettext() as a builtin for correct
    # plural handling (languages with >2 plural forms can't use "+ 's'").
    gettext.install(GETTEXT_DOMAIN, localedir, names=['ngettext'])
    # book_label() (i18n.py) translates a canonical English book name for
    # display; install it as a builtin too so the UI modules call it the same
    # unqualified way they call _() / ngettext().
    import builtins
    import i18n
    builtins.book_label = i18n.book_label


_setup_gettext()

import mpris  # noqa: E402
from styles import load_app_css  # noqa: E402
from window import BibleWindow  # noqa: E402  (after logging setup)


def _parse_bible_uri(uri):
    """Extract a reference string from a bible: URI. Supports both
    URL-encoded space (`bible:John%203:16`) and the casual `+` form
    (`bible:John+3:16`). Returns the reference string or None."""
    if not uri.startswith('bible:'):
        return None
    body = uri[len('bible:'):]
    if not body:
        return None
    return unquote(body).replace('+', ' ').strip() or None


def _register_icon_search_path():
    """Add our `data/icons/` directory to the default icon theme search
    path so GTK finds the bundled app icon (otherwise the About dialog
    and any other icon lookups fall back to GNOME's generic placeholder).

    In a Flatpak install the icon ends up under /app/share/icons/...
    and is picked up automatically, so this only matters for development
    / direct-source runs."""
    here = os.path.dirname(os.path.abspath(__file__))
    icons_dir = os.path.join(here, 'data', 'icons')
    if not os.path.isdir(icons_dir):
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    theme = Gtk.IconTheme.get_for_display(display)
    theme.add_search_path(icons_dir)


# The icon set the app is drawn against. Every desktop resolves a name like
# `starred-symbolic` out of whatever theme the user runs, so the same button
# is a flat glyph on one machine and a coloured cartoon on the next. Pinning
# one set is the only way the app looks like itself everywhere.
_PINNED_ICON_THEME = 'Adwaita'

# ...except these. Window controls belong to the desktop, not to us: a KDE
# reader should close this window with the button every other window on
# their screen has. They are the one part of the chrome the platform owns.
_PLATFORM_ICONS = (
    'window-close-symbolic', 'window-minimize-symbolic',
    'window-maximize-symbolic', 'window-restore-symbolic',
)

# The generated theme's name. It holds nothing but the platform icons above
# and inherits the pinned set for everything else, so lookup order is
# ours → Adwaita → hicolor (where our own scriptura-* icons live).
_OVERLAY_THEME = 'ScripturaIcons'

_INDEX_THEME = """[Icon Theme]
Name={name}
Comment=Window controls from the desktop; every other icon from {pinned}
Inherits={pinned},hicolor
Directories=scalable/actions,16x16/actions

[scalable/actions]
Context=Actions
Size=16
MinSize=8
MaxSize=512
Type=Scalable

[16x16/actions]
Context=Actions
Size=16
Type=Fixed
"""


def _build_icon_overlay(theme, source_theme):
    """Write a theme holding the desktop's window controls and nothing else.

    Returns the directory to prepend to the search path, or None when there
    is nothing to carry over (the desktop already runs the pinned set, or
    its controls could not be read).

    The copy is what makes the exception possible: a resource path and a
    plain search path both LOSE to the active theme — measured — so the
    only lookup that can win is a theme that comes first and inherits the
    rest. It must not be named after the pinned theme either: the first
    index.theme found defines that theme's whole directory list, so an
    overlay called Adwaita would truncate Adwaita to whatever it declares.
    """
    import shutil
    from paths import cache_dir
    root = os.path.join(cache_dir(), 'icon-overlay')
    dest = os.path.join(root, _OVERLAY_THEME)
    carried = []
    try:
        # Resolve against the desktop's own theme, before anything is pinned.
        for name in _PLATFORM_ICONS:
            paintable = theme.lookup_icon(
                name, None, 16, 1, Gtk.TextDirection.NONE, 0)
            gfile = paintable.get_file() if paintable else None
            path = gfile.get_path() if gfile else None
            if not path or not os.path.isfile(path):
                continue          # only in a resource, or absent — let it fall
            ext = os.path.splitext(path)[1].lower()
            if ext not in ('.svg', '.png'):
                continue
            sub = 'scalable/actions' if ext == '.svg' else '16x16/actions'
            out_dir = os.path.join(dest, sub)
            os.makedirs(out_dir, exist_ok=True)
            shutil.copyfile(path, os.path.join(out_dir, name + ext))
            carried.append(name)
        if not carried:
            return None
        with open(os.path.join(dest, 'index.theme'), 'w', encoding='utf-8') as f:
            f.write(_INDEX_THEME.format(name=_OVERLAY_THEME,
                                        pinned=_PINNED_ICON_THEME))
    except OSError:
        logging.getLogger('scriptura.icons').exception(
            'could not build the icon overlay from %s', source_theme)
        return None
    return root


_repinning = False


def _pin_icon_theme(*_args):
    """Draw every icon from one set, except the ones the desktop owns.

    Without this the app's iconography is whatever theme the reader
    happens to run — the same toolbar reads as clean line art on one
    machine and as colour cartoons on another. Pinning covers GTK's own
    lookups too (dropdown arrows, entry clear buttons), which renaming our
    icons could never reach.

    Also runs whenever the desktop pushes a new icon theme: that value
    overwrites ours, so without re-pinning a mid-session theme change
    quietly undoes all of this.
    """
    global _repinning
    display = Gdk.Display.get_default()
    gtk_settings = Gtk.Settings.get_default()
    if display is None or gtk_settings is None or _repinning:
        return
    desktop_theme = gtk_settings.get_property('gtk-icon-theme-name')
    if desktop_theme in (_OVERLAY_THEME, _PINNED_ICON_THEME):
        # Already pinned, or the desktop runs the pinned set anyway — which
        # is the usual case inside the Flatpak, where the runtime ships it
        # and the host's theme is not visible at all.
        _watch_icon_theme(gtk_settings)
        return
    theme = Gtk.IconTheme.get_for_display(display)
    overlay = _build_icon_overlay(theme, desktop_theme)
    _repinning = True
    try:
        if overlay is None:
            # Nothing to preserve — pin the set directly. The window
            # controls come from it too, which is the honest outcome when
            # the desktop's own could not be read.
            gtk_settings.set_property('gtk-icon-theme-name',
                                      _PINNED_ICON_THEME)
        else:
            if overlay not in theme.get_search_path():
                theme.set_search_path(
                    [overlay] + list(theme.get_search_path()))
            gtk_settings.set_property('gtk-icon-theme-name', _OVERLAY_THEME)
    finally:
        _repinning = False
    _watch_icon_theme(gtk_settings)


def _watch_icon_theme(gtk_settings):
    if getattr(gtk_settings, '_scriptura_icon_watch', False):
        return
    gtk_settings._scriptura_icon_watch = True
    gtk_settings.connect('notify::gtk-icon-theme-name', _pin_icon_theme)


def _apply_manual_font_rendering():
    """Pin GTK to MANUAL font rendering (classic integer-hinted glyph
    placement) instead of the AUTOMATIC mode's fractional vertical
    positioning. The automatic path feeds fractional glyph rects into GSK's
    shared GPU glyph-atlas cache, which shaves the top row off caps and
    ascenders at certain font sizes on every GPU renderer (gl/ngl/vulkan).
    MANUAL sidesteps that while keeping GPU acceleration. Needs a display, so
    it is called from activate/open, not at import. Since GTK 4.16."""
    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    try:
        settings.set_property('gtk-font-rendering', Gtk.FontRendering.MANUAL)
    except (AttributeError, TypeError):
        pass  # older GTK without the enum/property — nothing to pin, no harm


def _scan_argv_for_bible_uri():
    """Return the first bible: ref found in sys.argv, or None.

    Custom URI schemes don't always round-trip cleanly through
    Gio.File.get_uri() — `Gio.File.new_for_uri('bible:John+3:16')`
    may interpret the colon as a path separator and mangle the URI.
    Scanning argv directly is the reliable path: when xdg-open
    launches us via the desktop file, the URI lands here verbatim."""
    for arg in sys.argv[1:]:
        ref = _parse_bible_uri(arg)
        if ref:
            return ref
    return None


class BibleApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=(Gio.ApplicationFlags.NON_UNIQUE
                   | Gio.ApplicationFlags.HANDLES_OPEN))
        # Parsed from argv at init time — applies to both the activate
        # path (no URI args) and the open path (URI args, where Gio may
        # still mangle the URI through Gio.File.get_uri()).
        self._argv_ref = _scan_argv_for_bible_uri()
        self.connect('activate', self._on_activate)
        self.connect('open', self._on_open)
        # Gives the desktop's media bus something to raise and to quit. It
        # opens no connection: the bus is only reached once a reading is
        # actually playing.
        mpris.attach(self)

    def _on_activate(self, app):
        _register_icon_search_path()
        _pin_icon_theme()
        _apply_manual_font_rendering()
        load_app_css()
        self._present_main_or_welcome(app, startup_ref=self._argv_ref)

    def _on_open(self, app, files, _n_files, _hint):
        """Fired when invoked with a URI (e.g. `bible:John+3:16`).
        We prefer the argv-derived ref because Gio.File may not
        preserve custom URI schemes; fall back to Gio.File only if
        argv didn't yield a ref."""
        _register_icon_search_path()
        _pin_icon_theme()
        _apply_manual_font_rendering()
        load_app_css()
        ref = self._argv_ref
        if not ref:
            for f in files:
                ref = _parse_bible_uri(f.get_uri())
                if ref:
                    break
        self._present_main_or_welcome(app, startup_ref=ref)

    def _present_main_or_welcome(self, app, startup_ref=None):
        import sword_bridge
        import ebible_bridge
        # BIBLE_READER_FORCE_WELCOME=1 forces the welcome window even
        # when modules exist — useful for testing on systems with
        # /usr/share/sword/ modules that can't be removed without sudo.
        force_welcome = bool(os.environ.get('BIBLE_READER_FORCE_WELCOME'))
        # Cheap probe — avoids paying SWMgr() init before first paint.
        # The first BiblePane render does the real SWORD load.
        has_modules = bool(sword_bridge.has_any_module()
                           or ebible_bridge.module_names())
        if has_modules and not force_welcome:
            BibleWindow(application=app, startup_ref=startup_ref).present()
            return
        # Welcome flow: a bible: URI without installed modules is ignored
        # (no place to navigate to until at least one Bible is installed).
        from welcome import WelcomeWindow
        WelcomeWindow(
            application=app,
            on_ready=lambda: BibleWindow(application=app).present(),
        ).present()


def main():
    app = BibleApp()
    app.run()


if __name__ == '__main__':
    main()
