#!/usr/bin/env python3
"""Where do the two place probes lose the reading position?

`_capture_scroll_anchor()` (pixel-exact locus) and `_find_topmost_visible_verse()`
(coarse fallback) can BOTH return None at the same scroll position, and when
they do nothing restores the reading position across a re-render — the measured
cause of the text jumping on a settings toggle (GUIDANCE 5.0).

This parks the real reading view at many scroll offsets and asks both probes at
each one, at rest, with no toggle involved. It reports every miss together with
the state that explains it, so a miss is diagnosed rather than guessed at.

Success test: a locus from at least one probe at EVERY park.

    python3 tools/probe-place.py --module BSB --ref "Matthew 5"
    python3 tools/probe-place.py --module BSB --ref "Psalms 119" --step 41
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLL_MS = 100
SETTLE_POLLS = 4
CAP_MS = 30000
DRIVER_TIMEOUT = 300.0
#: Milliseconds to let GTK validate the new scroll position before probing.
PARK_SETTLE_MS = 160


def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib, Gtk

    import main

    out = Path(os.environ['PROBE_OUT'])
    book = os.environ['PROBE_BOOK']
    chapter = int(os.environ['PROBE_CHAPTER'])
    step = float(os.environ['PROBE_STEP'])
    app = main.BibleApp()
    R: dict = {'module': os.environ['PROBE_MODULE'], 'ref': f'{book} {chapter}',
               'step': step, 'parks': []}
    S: dict = {'tries': 0}

    def buftext(pane):
        b = pane._buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def finish(tag):
        R['exit_tag'] = tag
        misses = [p for p in R['parks']
                  if p['anchor'] is None and p['top_verse'] is None]
        R['parks_probed'] = len(R['parks'])
        R['blind_parks'] = len(misses)
        R['all_placed'] = bool(R['parks']) and not misses
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

    def diagnose(pane):
        """The state that explains a miss, read the same way the probes read
        it: the iter the reading top resolves to, whether GTK's own
        coordinate lookup answered there, and how far a walk has to go to
        reach a verse tag (the capture gives up after 32 hops)."""
        view = pane._view
        scroll = pane._scroll
        x = max(40, view.get_left_margin() + 20)
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, x, 1)
        located, _it = view.get_iter_at_location(bx, by)
        it, _by = scroll._iter_at_reading_top(1)
        tags = sorted(t.get_property('name') or '<anon>' for t in it.get_tags())
        hops = 0
        walk = it.copy()
        while hops <= 200:
            if any((t.get_property('name') or '').startswith('vnum_')
                   for t in walk.get_tags()):
                break
            hops += 1
            if not walk.forward_to_tag_toggle(None):
                hops = -1  # ran out of buffer without meeting a verse
                break
        return {'get_iter_at_location_ok': located,
                'top_line': it.get_line(),
                'top_tags': tags,
                'hops_to_verse': hops,
                'rendered_verses_none': scroll._rendered_verses is None,
                'realized': view.get_realized()}

    def sweep():
        pane = S['pane']
        adj = S['adj']
        view = pane._view
        parks = S['parks']

        def one():
            if not parks:
                return finish('done')
            park = parks.pop(0)
            adj.set_value(park)

            def probe():
                # A reader's scroll drops the held locus; re-deriving it from
                # geometry is exactly what the restore path has to do.
                pane._reading_anchor = None
                anchor = pane._capture_scroll_anchor()
                pane._reading_anchor = None
                top_verse = pane._find_topmost_visible_verse()
                row = {'park': round(park, 1),
                       'painted_y': round(view.window_to_buffer_coords(
                           Gtk.TextWindowType.TEXT, 0, 0)[1], 1),
                       'anchor': anchor,
                       'top_verse': top_verse,
                       'first_visible': pane._first_visible_verse()}
                if anchor is None or top_verse is None:
                    row['why'] = diagnose(pane)
                R['parks'].append(row)
                one()
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(PARK_SETTLE_MS, probe)
            return GLib.SOURCE_REMOVE
        one()

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
            S['adj'] = adj = sw.get_vadjustment()

            # The height must stop growing before the parks mean anything: a
            # set_value() against a still-estimated `upper` is clamped, and
            # the pane silently stays where it was.
            st = {'upper': None, 'streak': 0, 'left': 150}

            def wait_grown():
                upper = round(adj.get_upper(), 1)
                st['streak'] = st['streak'] + 1 if upper == st['upper'] else 0
                st['upper'] = upper
                st['left'] -= 1
                if st['streak'] * POLL_MS >= 400 or st['left'] <= 0:
                    R['upper'] = upper
                    R['page_size'] = round(adj.get_page_size(), 1)
                    top = max(0.0, upper - adj.get_page_size())
                    n = 0
                    parks = []
                    while n * step <= top:
                        parks.append(n * step)
                        n += 1
                    R['park_count'] = len(parks)
                    R['timed_out_growing'] = st['left'] <= 0
                    S['parks'] = parks
                    sweep()
                    return GLib.SOURCE_REMOVE
                return GLib.SOURCE_CONTINUE
            GLib.timeout_add(POLL_MS, wait_grown)
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
    parser.add_argument('--ref', default='Matthew 5')
    parser.add_argument('--step', type=float, default=37.0,
                        help='pixels between parks (a prime-ish step lands in '
                             'inter-line gaps rather than marching in time '
                             'with the line height)')
    parser.add_argument('--settings', metavar='FILE')
    parser.add_argument('--quiet', action='store_true',
                        help='print the summary and the misses, not every park')
    args = parser.parse_args()
    book, _, chapter = args.ref.rpartition(' ')

    with tempfile.TemporaryDirectory(prefix='scriptura-place-') as scratch:
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
                   PROBE_STEP=str(args.step))
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        base = {'open_to_today': False, 'split_pane_mode': False,
                'pane1_module': args.module, 'show_headings': True,
                'show_footnotes': True, 'smallcaps_divine': True,
                'oldstyle_numerals': True, 'colored_dropcap': True}
        if args.settings:
            base = json.loads(Path(args.settings).read_text())
            base.update(open_to_today=False, split_pane_mode=False,
                        pane1_module=args.module)
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

    if args.quiet:
        parks = data.pop('parks', [])
        data['misses'] = [p for p in parks
                          if p['anchor'] is None or p['top_verse'] is None]
    print(json.dumps(data, indent=1))
    return 0 if data.get('all_placed') else 1


if __name__ == '__main__':
    sys.exit(run_driver() if '--driver' in sys.argv else orchestrate())
