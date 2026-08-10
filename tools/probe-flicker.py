#!/usr/bin/env python3
"""Per-PAINTED-FRAME record of the reading position across a footnote toggle.

The toggle no longer moves the text where it lands, but the frames in between
are painted at the clamped position (`upper` collapses while GTK re-estimates
the document height, and the idle restore loses to redraw). This measures
those frames instead of reasoning about them.

Reports, for each toggle: the parked adjustment, every distinct value painted
after it, how many painted frames were off by more than TOL px, and the worst
offset.

Runs on the real display with a scratch XDG (never the user's config).

    python3 tools/probe-flicker.py --module BSB --ref "Psalms 119" --park 3367
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLL_MS = 100
SETTLE_POLLS = 4
CAP_MS = 30000
DRIVER_TIMEOUT = 240.0
TOL = 4.0
ROUNDS = 4


def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib, Gtk, Gdk, Gsk, Graphene
    import cairo

    import main

    out = Path(os.environ['PROBE_OUT'])
    book = os.environ['PROBE_BOOK']
    chapter = int(os.environ['PROBE_CHAPTER'])
    park = float(os.environ['PROBE_PARK'])
    app = main.BibleApp()
    R: dict = {'module': os.environ['PROBE_MODULE'], 'ref': f'{book} {chapter}',
               'toggles': []}
    S: dict = {'tries': 0, 'round': 0, 'frames': [], 'adj_frames': [],
               'recording': False}

    def buftext(pane):
        b = pane._buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def finish(tag):
        R['exit_tag'] = tag
        out.write_text(json.dumps(R, indent=1))
        app.quit()
        return GLib.SOURCE_REMOVE

    def settle(pane, then):
        st = {'last': None, 'same': 0, 'n': 0}

        def poll():
            st['n'] += 1
            t = buftext(pane)
            st['same'] = st['same'] + 1 if (t == st['last'] and t) else 0
            st['last'] = t
            if st['same'] >= SETTLE_POLLS or st['n'] * POLL_MS >= CAP_MS:
                then(t)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(POLL_MS, poll)

    def one_round(_ignored=None):
        pane = S['pane']
        adj = S['adj']
        if S['round'] >= ROUNDS:
            R['all_clean'] = all(t['bad_frames'] == 0 for t in R['toggles'])
            return finish('done')
        S['round'] += 1

        # Park the matrix's way: a raw set_value() before GtkTextView's
        # validation idle has run is clamped against an `upper` that is still
        # a small estimate, and the pane silently stays at the top. Wait for
        # the height to stop growing AND to exceed the target first, then
        # scroll, then let the pane capture its anchor as a reader's scroll
        # would.
        st = {'upper': None, 'streak': 0, 'left': 150}

        def wait_grown():
            upper = round(adj.get_upper(), 1)
            st['streak'] = st['streak'] + 1 if upper == st['upper'] else 0
            st['upper'] = upper
            st['left'] -= 1
            grown = adj.get_upper() - adj.get_page_size() > park
            if (st['streak'] * POLL_MS >= 400 and grown) or st['left'] <= 0:
                R.setdefault('park_setup', []).append({
                    'upper': upper, 'page': round(adj.get_page_size(), 1),
                    'grown': grown, 'timed_out': st['left'] <= 0})
                adj.set_value(park)
                # exactly what the matrix's user_scrolled() does: drop the
                # old locus, then record the new one
                pane._reading_anchor = None
                pane._capture_scroll_anchor()
                GLib.timeout_add(300, go)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(POLL_MS, wait_grown)

        view = pane._view

        def go():
            target = view.window_to_buffer_coords(
                Gtk.TextWindowType.TEXT, 0, 0)[1]
            S['frames'] = []
            S['adj_frames'] = []
            S['recording'] = True
            cur = bool(pane._show_footnotes)
            if os.environ.get('PROBE_VIA_BUTTON'):
                # The reader's own path: the f* toolbar button, which also
                # writes the setting and toggles the second pane.
                S['win'].fnote_toggle.set_active(not cur)
            else:
                pane.set_show_footnotes(not cur)

            def after(_text):
                # Keep recording a little past the settle, then report.
                def stop():
                    S['recording'] = False
                    vals = S['frames']
                    bad = [v for v in vals if abs(v - target) > TOL]
                    R['toggles'].append({
                        'direction': 'off' if cur else 'on',
                        'parked_at': round(target, 1),
                        'painted_frames': len(vals),
                        'distinct_values': sorted({round(v, 1) for v in vals}),
                        'bad_frames': len(bad),
                        'worst_offset_px': (round(max(abs(v - target)
                                                      for v in bad), 1)
                                            if bad else 0.0),
                        'landed_at': round(view.window_to_buffer_coords(
                            Gtk.TextWindowType.TEXT, 0, 0)[1], 1),
                        'adj_distinct': sorted({round(v, 1)
                                                for v in S['adj_frames']}),
                    })
                    GLib.timeout_add(500, one_round)
                    return GLib.SOURCE_REMOVE
                GLib.timeout_add(300, stop)
            settle(pane, after)
            return GLib.SOURCE_REMOVE

    def wait_arrived():
        S['tries'] += 1
        pane = S['win'].pane1
        if (getattr(pane, '_book', None) == book
                and int(getattr(pane, '_chapter', -1)) == chapter
                and buftext(pane).strip()):
            S['pane'] = pane
            sw = getattr(pane, '_reading_scroll', None)
            if sw is None:
                R['error'] = 'could not find the reading ScrolledWindow'
                return finish('no-scroller')
            S['adj'] = sw.get_vadjustment()
            R['upper'] = round(S['adj'].get_upper(), 1)
            R['page_size'] = round(S['adj'].get_page_size(), 1)

            # Record the vadjustment on every PAINTED frame.
            clock = S['win'].get_frame_clock()

            view = pane._view

            def painted_y():
                """What the TextView is actually SHOWING, not what the
                adjustment says. The hold deliberately overstates `upper`, and
                a value the adjustment accepts is not proof the widget painted
                there — window_to_buffer_coords reports the offset the text was
                drawn at."""
                return view.window_to_buffer_coords(
                    Gtk.TextWindowType.TEXT, 0, 0)[1]

            shots = Path(os.environ.get('PROBE_SHOTS', '')) \
                if os.environ.get('PROBE_SHOTS') else None
            paintable = Gtk.WidgetPaintable.new(S['win'])
            renderer = Gsk.CairoRenderer.new()
            renderer.realize(None)

            def grab(tag):
                """PNG of the window as it stands. The position probes above
                both read numbers the widget need not have obeyed; this reads
                what a reader would see."""
                w = S['win'].get_width()
                h = S['win'].get_height()
                snap = Gtk.Snapshot()
                paintable.snapshot(snap, w, h)
                node = snap.to_node()
                if node is None:
                    return
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
                ctx = cairo.Context(surf)
                node.draw(ctx)
                import hashlib
                data = bytes(surf.get_data())
                h = hashlib.sha1(data).hexdigest()[:10]
                R.setdefault('frame_hashes', []).append((tag, h))
                seen = S.setdefault('seen_hashes', {})
                if h not in seen:          # one PNG per DISTINCT frame
                    seen[h] = tag
                    surf.write_to_png(str(shots / f'{tag}_{h}.png'))

            def after_paint(_c):
                if S['recording']:
                    n = len(S['frames'])
                    S['frames'].append(painted_y())
                    S['adj_frames'].append(S['adj'].get_value())
                    if shots is not None and S['round'] == 2 and n < 30:
                        grab(f'f{n:02d}_y{int(painted_y())}')
            clock.connect('after-paint', after_paint)
            # A painted frame only happens if something asks for one; the
            # toggle does, but keep the clock alive so idle frames register.
            S['win'].add_tick_callback(lambda *_a: True)
            one_round()
            return GLib.SOURCE_REMOVE
        if S['tries'] * POLL_MS >= CAP_MS:
            R['error'] = f'never arrived at {book} {chapter}'
            return finish('no-arrival')
        return GLib.SOURCE_CONTINUE

    def kickoff():
        win = app.get_active_window()
        if win is None:
            return GLib.SOURCE_CONTINUE
        S['win'] = win
        win.set_default_size(int(os.environ.get('PROBE_W', 1200)),
                             int(os.environ.get('PROBE_H', 900)))

        def then_navigate(_settled):
            win.pane1.force_navigate(book, chapter, 1)
            GLib.timeout_add(POLL_MS, wait_arrived)
        settle(win.pane1, then_navigate)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(POLL_MS, kickoff)
    GLib.timeout_add(int(DRIVER_TIMEOUT * 1000) // 2,
                     lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])
    return 0


def orchestrate() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--module', default='BSB')
    parser.add_argument('--ref', default='Psalms 119')
    parser.add_argument('--park', type=float, default=3367.0)
    parser.add_argument('--settings', metavar='FILE')
    args = parser.parse_args()
    book, _, chapter = args.ref.rpartition(' ')

    with tempfile.TemporaryDirectory(prefix='scriptura-flicker-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env.pop('GDK_BACKEND', None)
        for var in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
            env[var] = 'http://127.0.0.1:1'
        report = Path(scratch, 'report.json')
        env.update(PROBE_OUT=str(report), PROBE_MODULE=args.module,
                   PROBE_BOOK=book, PROBE_CHAPTER=chapter,
                   PROBE_PARK=str(args.park))
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        base = {'open_to_today': False, 'split_pane_mode': False,
                'pane1_module': args.module, 'show_headings': True,
                'show_footnotes': True, 'smallcaps_divine': True,
                'oldstyle_numerals': True, 'colored_dropcap': True}
        if args.settings:
            base = json.loads(Path(args.settings).read_text())
            base.update(open_to_today=False, split_pane_mode=False,
                        pane1_module=args.module, show_footnotes=True)
        (cfg / 'settings.json').write_text(json.dumps(base))

        try:
            subprocess.run([sys.executable, __file__, '--driver'], env=env,
                           cwd=REPO_ROOT, timeout=DRIVER_TIMEOUT,
                           stdout=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            print('driver timed out', file=sys.stderr)
            return 1
        if not report.exists():
            print('driver produced no report', file=sys.stderr)
            return 1
        data = json.loads(report.read_text())

    print(json.dumps(data, indent=1))
    return 0 if data.get('all_clean') else 1


if __name__ == '__main__':
    sys.exit(run_driver() if '--driver' in sys.argv else orchestrate())
