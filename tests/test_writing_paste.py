"""Reading a paste off the clipboard.

On Wayland the clipboard hands over a pipe from the app that copied, and a
pipe gives what has arrived so far, not all there is. OnlyOffice puts its
whole document on the clipboard as a data blob beside the HTML, so a long
sermon copied from it is hundreds of kilobytes, written in pieces.
"""
import os
import threading
import time

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk  # noqa: E402

import writing_page  # noqa: E402


class _Clipboard:
    def __init__(self, stream):
        self.stream = stream

    def read_finish(self, _result):
        return self.stream, 'text/html'


class _Editor:
    """What the paste touches on the editor."""

    _on_html_spliced = writing_page.WritingPageMixin._on_html_spliced
    _paste_html = writing_page.WritingPageMixin._paste_html

    def __init__(self):
        self.buffer = Gtk.TextBuffer()
        self.body = self

    def get_buffer(self):
        return self.buffer

    def scroll_mark_onscreen(self, _mark):
        pass


def _pipe_writing(data, chunk=4096):
    """A stream on a real pipe, filled in pieces by another thread, as an
    app on the other end of the clipboard fills it."""
    read_fd, write_fd = os.pipe()

    def write():
        with os.fdopen(write_fd, 'wb') as out:
            for i in range(0, len(data), chunk):
                out.write(data[i:i + chunk])
                out.flush()
                time.sleep(0.001)

    threading.Thread(target=write, daemon=True).start()
    return Gio.UnixInputStream.new(read_fd, True)


def test_a_long_paste_arrives_whole():
    items = ''.join(f'<li><p><span style="font-size:10pt">Point {i}</span>'
                    f'</p></li>' for i in range(1, 2001))
    html = f'<ul>{items}</ul><p>THE LAST LINE</p>'.encode()
    assert len(html) > 100_000
    editor = _Editor()
    writing_page.WritingPageMixin._on_html_read(
        editor, _Clipboard(_pipe_writing(html)), None)
    # The read runs on the main loop, as it does in the app.
    context, end = GLib.MainContext.default(), time.monotonic() + 10
    while (editor.buffer.get_char_count() == 0
           and time.monotonic() < end):
        context.iteration(False)
    text = editor.buffer.get_text(*editor.buffer.get_bounds(), True)
    assert text.startswith('- Point 1\n')
    assert '- Point 2000' in text
    assert text.endswith('THE LAST LINE')
