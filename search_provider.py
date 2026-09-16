"""Look up a verse from the GNOME desktop.

GNOME Shell asks every search provider about what the reader types in
Activities. This one answers a reference — "John 3:16", «Иоанна 3:16» — with
the verse in the translation the reader last had open, and Enter opens the
app there through the same path a `bible:` link takes.

Only a book name followed by a chapter counts. A bare word never does: the
Shell sends every keystroke of every search here, and "gen" typed on the way
to an app's name must not answer with Genesis.

The Shell finds this through two files installed beside the desktop file: a
search-provider `.ini` naming the bus and object path, and a D-Bus service
file that starts the app with `--gapplication-service` when it is not
running. In that mode the app opens no window and quits once idle.
"""

import re
from urllib.parse import quote

from gi.repository import Gio, GLib

import content
import passage_export
import settings
import sword_bridge
import window
from overlays import match_book

OBJECT_PATH = '/io/github/andresmessina_SDG/Scriptura/SearchProvider'

_XML = """
<node>
  <interface name="org.gnome.Shell.SearchProvider2">
    <method name="GetInitialResultSet">
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg type="as" name="previous_results" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg type="as" name="identifiers" direction="in"/>
      <arg type="aa{sv}" name="metas" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg type="s" name="identifier" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
  </interface>
</node>
"""

# A result line is one line in the Shell; past this it is cut anyway.
_DESCRIPTION_CHARS = 160

_REFERENCE = re.compile(r'^(.+?)\s+(\d+)(?::(\d+))?$')


def parse(terms):
    """`(book, chapter, verse or None)` for a reference, else None."""
    m = _REFERENCE.match(' '.join(terms).strip())
    if not m:
        return None
    query = m.group(1).lower().replace(' ', '')
    # Two letters at least: "a 1" is not a reference to Amos.
    if sum(ch.isalpha() for ch in query) < 2:
        return None
    book = match_book(query, window.BOOKS)
    if book is None:
        return None
    chapter = int(m.group(2))
    if not 1 <= chapter <= sword_bridge.chapter_count_in(None, book):
        return None
    return book, chapter, int(m.group(3)) if m.group(3) else None


def identifier(ref):
    """The canonical English reference, which `bible:` links also take."""
    book, chapter, verse = ref
    return f'{book} {chapter}' + (f':{verse}' if verse else '')


def _module():
    bibles = content.text_bible_names()
    chosen = settings.get('pane1_module')
    if chosen in bibles:
        return chosen
    return bibles[0] if bibles else None


def results(terms):
    """The identifiers to show: one reference, or none when the terms are
    not one or the reader has no Bible holding that verse."""
    ref = parse(terms)
    if ref is None or _text(ref) is None:
        return []
    return [identifier(ref)]


def _text(ref):
    module = _module()
    if module is None:
        return None
    book, chapter, verse = ref
    text = passage_export.verse_text(
        module, book, chapter, [verse] if verse else None)
    return text or None


def meta(ident):
    """The Shell's row for an identifier `results` gave."""
    ref = parse(ident.split())
    if ref is None:
        return None
    text = _text(ref) or ''
    if len(text) > _DESCRIPTION_CHARS:
        text = text[:_DESCRIPTION_CHARS].rsplit(' ', 1)[0] + '…'
    book, chapter, verse = ref
    return {
        'id': ident,
        'name': f'{book_label(book)} {chapter}' + (f':{verse}' if verse else ''),
        'description': text,
    }


class SearchProvider:
    """The D-Bus object. Every call holds the app for its length, which is
    what keeps a service-mode app alive between keystrokes."""

    def __init__(self, app):
        self._app = app
        self._registration = 0

    def register(self, connection):
        node = Gio.DBusNodeInfo.new_for_xml(_XML)
        self._registration = connection.register_object(
            OBJECT_PATH, node.interfaces[0], self._on_call, None, None)

    def unregister(self, connection):
        if self._registration:
            connection.unregister_object(self._registration)
            self._registration = 0

    def _on_call(self, _connection, _sender, _path, _iface, method, params,
                 invocation):
        self._app.hold()
        try:
            args = params.unpack()
            if method == 'GetInitialResultSet':
                reply = GLib.Variant('(as)', (results(args[0]),))
            elif method == 'GetSubsearchResultSet':
                reply = GLib.Variant('(as)', (results(args[1]),))
            elif method == 'GetResultMetas':
                metas = []
                for ident in args[0]:
                    row = meta(ident)
                    if row is not None:
                        metas.append({k: GLib.Variant('s', v)
                                      for k, v in row.items()})
                reply = GLib.Variant('(aa{sv})', (metas,))
            elif method == 'ActivateResult':
                self._open(args[0])
                reply = None
            elif method == 'LaunchSearch':
                ref = parse(args[0])
                if ref is None:
                    self._app.activate()
                else:
                    self._open(identifier(ref))
                reply = None
            else:
                invocation.return_dbus_error(
                    'org.freedesktop.DBus.Error.UnknownMethod', method)
                return
            invocation.return_value(reply)
        finally:
            self._app.release()

    def _open(self, ident):
        self._app.open(
            [Gio.File.new_for_uri('bible:' + quote(ident))], '')
