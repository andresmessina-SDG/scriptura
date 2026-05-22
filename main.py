import os
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, Gio
from window import BibleWindow


APP_ID = 'org.codeberg.andresmessina.BibleReader'


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


class BibleApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.connect('activate', self._on_activate)

    def _on_activate(self, app):
        _register_icon_search_path()
        self._present_main_or_welcome(app)

    def _present_main_or_welcome(self, app):
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
            BibleWindow(application=app).present()
            return
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
