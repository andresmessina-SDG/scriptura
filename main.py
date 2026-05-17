import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio
from window import BibleWindow


class BibleApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='org.example.biblereader',
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.connect('activate', self._on_activate)

    def _on_activate(self, app):
        win = BibleWindow(application=app)
        win.present()


def main():
    app = BibleApp()
    app.run()


if __name__ == '__main__':
    main()
