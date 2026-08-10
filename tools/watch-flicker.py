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
import hashlib
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gsk', '4.0')
import cairo                          # noqa: E402
from gi.repository import Gtk, GLib, Gsk   # noqa: E402

import main                            # noqa: E402

LOG = Path(os.environ.get('FLICKER_LOG', '/tmp/flicker-watch.log'))
#: Set to a directory to also hash every painted frame and keep one PNG per
#: distinct one — the instrument for a blink the numbers cannot see.
SHOTS = os.environ.get('FLICKER_SHOTS')


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

    # Which code moved the adjustment is the open question: a frame lands
    # 208px low while the hold is still live and the hold's own reassert is
    # not the one writing it. Name the caller instead of inferring it.
    def on_value(_a):
        # Only around a rebuild — plain wheel scrolling would bury the log.
        at = state['display_at']
        if sw._hold_value is None and (at is None
                                       or time.perf_counter() - at > 1.0):
            return
        stack = [f.name for f in traceback.extract_stack()[-6:-1]]
        log.write(f'{time.perf_counter() - t0:8.3f}  value -> '
                  f'{adj.get_value():.1f}  via {" < ".join(reversed(stack))}\n')
        log.flush()
    adj.connect('value-changed', on_value)

    orig_release = sw.release_scroll_hold

    def logged_release():
        held = sw._hold_value
        orig_release()
        log.write(f'{time.perf_counter() - t0:8.3f}  RELEASE (was {held})\n')
        log.flush()
    sw.release_scroll_hold = logged_release

    orig_anchor = pane._apply_scroll_anchor

    def logged_anchor(anchor):
        log.write(f'{time.perf_counter() - t0:8.3f}  apply_scroll_anchor '
                  f'{anchor}\n')
        log.flush()
        return orig_anchor(anchor)
    pane._apply_scroll_anchor = logged_anchor

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

    # Position, buffer length and adjustment can all be identical between two
    # frames that LOOK different. When those numbers are clean and a blink is
    # still visible, only the pixels can say what changed: hash every painted
    # frame, keep one PNG per distinct hash.
    shots = Path(SHOTS) if SHOTS else None
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
        paintable = Gtk.WidgetPaintable.new(win)
        renderer = Gsk.CairoRenderer.new()
        renderer.realize(None)
        seen = {}

        def grab(_clock):
            w, h = win.get_width(), win.get_height()
            if w <= 0 or h <= 0:
                return
            snap = Gtk.Snapshot()
            paintable.snapshot(snap, w, h)
            node = snap.to_node()
            if node is None:
                return
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            node.draw(cairo.Context(surf))
            digest = hashlib.sha1(bytes(surf.get_data())).hexdigest()[:10]
            t = time.perf_counter() - t0
            if digest not in seen:
                seen[digest] = t
                surf.write_to_png(str(shots / f'{t:08.3f}_{digest}.png'))
            log.write(f'{t:8.3f}  frame {digest}'
                      f'{"" if seen[digest] == t else "  (seen before)"}\n')
            log.flush()

        win.get_frame_clock().connect('after-paint', grab)

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
