#!/usr/bin/env python3
"""Run the real app, and record what the reading view PAINTS, frame by frame.

The driven probes could not reproduce the flicker Andres sees, so this stops
driving and starts watching: the app runs normally, on the real config, and
every painted frame appends the offset the text was drawn at, the adjustment's
own value (the two disagree while a rebuild is held), and the buffer length.

    python3 tools/watch-flicker.py            # then use the app as usual
    tail -f /tmp/.../flicker-watch.log

Each line: seconds since start, painted y, adjustment value, buffer chars,
and a marker when _display runs.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, GLib   # noqa: E402

import main                            # noqa: E402

LOG = Path(os.environ.get('FLICKER_LOG', '/tmp/flicker-watch.log'))


def install(win, log):
    pane = win.pane1
    view = pane._view
    adj = pane._reading_scroll.get_vadjustment()
    t0 = time.perf_counter()
    state = {'last': None, 'display_at': None}

    # Whether the hold engaged at all is the question the driven probes could
    # not answer: they never reproduced the top-flash, while a live session
    # showed it twice. Log the decision itself, not only its effect.
    sw = pane._reading_scroll
    orig_hold = sw.hold_scroll
    orig_reassert = sw._reassert_held_scroll

    def logged_hold():
        orig_hold()
        log.write(f'{time.perf_counter() - t0:8.3f}  hold_scroll -> '
                  f'{sw._hold_value}\n')
        log.flush()
    sw.hold_scroll = logged_hold

    def logged_reassert():
        before = sw._hold_value
        orig_reassert()
        if before is not None:
            log.write(f'{time.perf_counter() - t0:8.3f}  reassert hold='
                      f'{before} -> {sw._hold_value} upper={adj.get_upper():.1f} '
                      f'val={adj.get_value():.1f}\n')
            log.flush()
    sw._reassert_held_scroll = logged_reassert

    orig_rerender = pane._rerender_keeping_place

    def logged_rerender():
        orig_rerender()
        log.write(f'{time.perf_counter() - t0:8.3f}  rerender_keeping_place '
                  f'anchor={pane._restore_anchor} '
                  f'top_verse={pane._restore_top_verse}\n')
        log.flush()
    pane._rerender_keeping_place = logged_rerender

    orig_display = pane._display

    def timed_display(*a, **kw):
        state['display_at'] = time.perf_counter()
        log.write(f'{time.perf_counter() - t0:8.3f}  _display ENTER\n')
        r = orig_display(*a, **kw)
        log.write(f'{time.perf_counter() - t0:8.3f}  _display LEAVE\n')
        log.flush()
        return r
    pane._display = timed_display

    def after_paint(_clock):
        y = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, 0, 0)[1]
        v = adj.get_value()
        b = pane._buffer.get_char_count()
        row = (round(y), round(v), b)
        if row == state['last']:
            return                      # only transitions are interesting
        state['last'] = row
        log.write(f'{time.perf_counter() - t0:8.3f}  painted_y={y:<8.1f} '
                  f'adj={v:<8.1f} upper={adj.get_upper():<9.1f} chars={b}\n')
        log.flush()

    win.get_frame_clock().connect('after-paint', after_paint)
    # Keep the clock ticking so quiet frames still register.
    win.add_tick_callback(lambda *_a: True)
    log.write('watching\n')
    log.flush()


def run():
    app = main.BibleApp()
    log = LOG.open('w')
    state = {'done': False}

    def poll():
        if state['done']:
            return GLib.SOURCE_REMOVE
        win = app.get_active_window()
        if win is None or not hasattr(win, 'pane1'):
            return GLib.SOURCE_CONTINUE
        state['done'] = True
        install(win, log)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(200, poll)
    app.run([])
    log.close()
    return 0


if __name__ == '__main__':
    sys.exit(run())
