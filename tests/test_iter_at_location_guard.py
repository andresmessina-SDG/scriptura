"""The pointer over the gap below a paragraph must not kill the app.

GTK 4.22 aborts the process from `get_iter_at_location` when the point is in
a line's `pixels-below-lines` space and the line hides any text — footnote
markers and headings, both hidden by default in the reading view. The abort
cannot be caught, so the sweep runs in its own process on a Broadway display
of its own, and the test reads the exit status.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SWEEP = r'''
import sys
import resource
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import gtk_utils
from reading_view import BibleTextView
from writing_page import _WritingView

app = Gtk.Application()

def activate(app):
    win = Gtk.Window(application=app, default_width=600, default_height=900)
    sw = Gtk.ScrolledWindow()
    win.set_child(sw)
    kind, script = sys.argv[2:4]
    if kind == 'reading':
        view = BibleTextView()
    elif kind == 'writing':
        class Editor:
            def _draw_page(self, *args):
                pass
        editor = Editor()
        view = _WritingView(editor)
    else:
        view = Gtk.TextView()
    view.set_wrap_mode(Gtk.WrapMode.WORD)
    view.set_pixels_above_lines(5)
    view.set_pixels_below_lines(8)
    sw.set_child(view)
    buf = view.get_buffer()
    hidden = buf.create_tag('hidden', invisible=True)
    for _ in range(4):
        for k in range(10):
            words = ('For God so loved the world' if script == 'latin'
                     else 'Ἐν ἀρχῇ — בְּרֵאשִׁית — Dios amó')
            buf.insert(buf.get_end_iter(), f'{k + 1} {words} ')
            if script == 'anchors':
                start = buf.get_end_iter().get_offset()
                anchor = buf.create_child_anchor(buf.get_end_iter())
                view.add_child_at_anchor(Gtk.Label(label='note'), anchor)
                buf.apply_tag(hidden, buf.get_iter_at_offset(start),
                              buf.get_end_iter())
            else:
                buf.insert_with_tags(buf.get_end_iter(), 'α', hidden)
            buf.insert(buf.get_end_iter(), 'that he gave his only Son. ')
        start = buf.get_end_iter().get_offset()
        buf.insert(buf.get_end_iter(), '\n\nA Heading\n')
        if script != 'anchors':
            buf.apply_tag(hidden, buf.get_iter_at_offset(start), buf.get_end_iter())
    win.present()

    def sweep():
        for y in range(0, 1400):
            for x in range(0, 600, 40):
                if kind == 'helper':
                    gtk_utils.iter_at_location(view, x, y)
                else:
                    view.get_iter_at_location(x, y)
        print('swept', flush=True)
        app.quit()
    GLib.timeout_add(500, sweep)

app.connect('activate', activate)
app.run([])
'''


@pytest.mark.skipif(shutil.which('gtk4-broadwayd') is None,
                    reason='needs gtk4-broadwayd')
@pytest.mark.parametrize('kind', ['helper', 'reading', 'writing'])
@pytest.mark.parametrize('script', ['latin', 'multilingual', 'anchors'])
def test_no_point_below_a_line_with_hidden_text_aborts(kind, script):
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, XDG_RUNTIME_DIR=tmp, GDK_BACKEND='broadway',
                   BROADWAY_DISPLAY=':47')
        env.pop('WAYLAND_DISPLAY', None)
        env.pop('DISPLAY', None)
        server = subprocess.Popen(['gtk4-broadwayd', ':47'], env=env,
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if any(n.startswith('broadway') for n in os.listdir(tmp)):
                    break
                time.sleep(0.1)
            run = subprocess.run([sys.executable, '-c', _SWEEP, REPO, kind, script],
                                 env=env, capture_output=True, text=True,
                                 timeout=120)
        finally:
            server.terminate()
            server.wait()
    assert run.returncode == 0 and 'swept' in run.stdout, run.stderr[-2000:]
