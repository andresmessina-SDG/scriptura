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
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import gtk_utils

app = Gtk.Application()

def activate(app):
    win = Gtk.Window(application=app, default_width=600, default_height=900)
    sw = Gtk.ScrolledWindow()
    win.set_child(sw)
    view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, pixels_below_lines=8)
    sw.set_child(view)
    buf = view.get_buffer()
    hidden = buf.create_tag('hidden', invisible=True)
    for _ in range(4):
        for k in range(10):
            buf.insert(buf.get_end_iter(), f'{k + 1} For God so loved the world ')
            buf.insert_with_tags(buf.get_end_iter(), 'a', hidden)
            buf.insert(buf.get_end_iter(), 'that he gave his only Son. ')
        start = buf.get_end_iter().get_offset()
        buf.insert(buf.get_end_iter(), '\n\nA Heading\n')
        buf.apply_tag(hidden, buf.get_iter_at_offset(start), buf.get_end_iter())
    win.present()

    def sweep():
        for y in range(0, 1400):
            for x in range(0, 600, 40):
                gtk_utils.iter_at_location(view, x, y)
        print('swept', flush=True)
        app.quit()
    GLib.timeout_add(500, sweep)

app.connect('activate', activate)
app.run([])
'''


@pytest.mark.skipif(shutil.which('gtk4-broadwayd') is None,
                    reason='needs gtk4-broadwayd')
def test_no_point_below_a_line_with_hidden_text_aborts():
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
            run = subprocess.run([sys.executable, '-c', _SWEEP, REPO],
                                 env=env, capture_output=True, text=True,
                                 timeout=120)
        finally:
            server.terminate()
            server.wait()
    assert run.returncode == 0 and 'swept' in run.stdout, run.stderr[-2000:]
