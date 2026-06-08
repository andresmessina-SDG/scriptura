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


APP_ID = 'page.codeberg.andresmessina.Scriptura'
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
    localedir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'locale')
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


_setup_gettext()

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

    def _on_activate(self, app):
        _register_icon_search_path()
        load_app_css()
        self._present_main_or_welcome(app, startup_ref=self._argv_ref)

    def _on_open(self, app, files, _n_files, _hint):
        """Fired when invoked with a URI (e.g. `bible:John+3:16`).
        We prefer the argv-derived ref because Gio.File may not
        preserve custom URI schemes; fall back to Gio.File only if
        argv didn't yield a ref."""
        _register_icon_search_path()
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
