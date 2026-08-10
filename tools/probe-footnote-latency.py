#!/usr/bin/env python3
"""Where does a footnote toggle's wall time go?

Copies verify-render-paths.py's scaffolding (broadwayd + scratch XDG) and
replaces its trigger loop with a stage-timed footnote toggle:

    setter -> fetch start -> fetch done -> _display -> first frame after

Usage: python3 tools/probe-footnote-latency.py [--module BSB] [--ref "Psalms 119"]
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
DISPLAY = 9
POLL_MS = 100
SETTLE_POLLS = 4
CAP_MS = 30000
DRIVER_TIMEOUT = 240.0
ROUNDS = 3


def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib

    import main
    import sword_bridge

    out = Path(os.environ['PROBE_OUT'])
    book = os.environ['PROBE_BOOK']
    chapter = int(os.environ['PROBE_CHAPTER'])
    app = main.BibleApp()
    R: dict = {'module': os.environ['PROBE_MODULE'], 'ref': f'{book} {chapter}',
               'rounds': []}
    S: dict = {'tries': 0, 'round': 0, 'stage': {}}

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

    # ── instrument the stages ───────────────────────────────────────────
    def instrument(pane):

        for name in ('load_chapter', 'chapter_footnotes', 'chapter_headings'):
            orig = getattr(sword_bridge, name)

            def wrap(*a, _o=orig, _n=name, **kw):
                st = S['stage']
                t0 = time.perf_counter()
                if 'fetch_start' not in st:
                    st['fetch_start'] = t0
                r = _o(*a, **kw)
                st[f'sword_{_n}'] = (time.perf_counter() - t0) * 1000
                st['fetch_end'] = time.perf_counter()
                return r
            setattr(sword_bridge, name, wrap)

        orig_display = pane._display

        def timed_display(*a, **kw):
            st = S['stage']
            st['display_start'] = time.perf_counter()
            r = orig_display(*a, **kw)
            st['display_end'] = time.perf_counter()
            return r
        pane._display = timed_display

        for name in ('_restore_scroll_anchor', '_apply_restore_anchor',
                     '_restore_reading_place'):
            fn = getattr(pane, name, None)
            if fn is None:
                continue

            def wrapr(*a, _f=fn, _n=name, **kw):
                st = S['stage']
                t0 = time.perf_counter()
                r = _f(*a, **kw)
                st.setdefault('restore_ms', []).append(
                    (_n, round((time.perf_counter() - t0) * 1000, 1)))
                return r
            setattr(pane, name, wrapr)

    def one_round(_ignored=None):
        pane, win = S['pane'], S['win']
        if S['round'] >= ROUNDS:
            return finish('done')
        S['round'] += 1
        S['stage'] = {}
        st = S['stage']
        cur = bool(pane._show_footnotes)
        st['t0'] = time.perf_counter()
        pane.set_show_footnotes(not cur)

        def after(_text):
            # First frame drawn after the text landed.
            def on_tick(_w, _clock):
                st['frame'] = time.perf_counter()
                ms = lambda a, b: (round((st[b] - st[a]) * 1000, 1)
                                   if a in st and b in st else None)
                R['rounds'].append({
                    'direction': 'off' if cur else 'on',
                    'setter_to_fetch_ms': ms('t0', 'fetch_start'),
                    'fetch_ms': ms('fetch_start', 'fetch_end'),
                    'fetch_to_display_ms': ms('fetch_end', 'display_start'),
                    'display_ms': ms('display_start', 'display_end'),
                    'display_to_frame_ms': ms('display_end', 'frame'),
                    'total_ms': ms('t0', 'frame'),
                    'sword': {k: round(v, 1) for k, v in st.items()
                              if k.startswith('sword_')},
                    'restore': st.get('restore_ms'),
                })
                GLib.timeout_add(400, one_round)
                return GLib.SOURCE_REMOVE
            win.add_tick_callback(on_tick)
        settle(pane, after)

    def wait_arrived():
        S['tries'] += 1
        pane = S['win'].pane1
        if (getattr(pane, '_book', None) == book
                and int(getattr(pane, '_chapter', -1)) == chapter
                and buftext(pane).strip()):
            S['pane'] = pane
            R['chars'] = len(buftext(pane))
            R['tags'] = pane._buffer.get_tag_table().get_size()
            instrument(pane)
            if os.environ.get('PROBE_WARMUP'):
                # Simulate a long session: many chapters rendered into the
                # same buffer before the toggle is measured.
                tour = [('John', c) for c in range(1, 12)] + \
                       [('Psalms', c) for c in (1, 23, 51)] + \
                       [('Genesis', c) for c in (1, 2, 3)]
                st2 = {'i': 0}

                def step():
                    if st2['i'] >= len(tour):
                        pane.force_navigate(book, chapter, 1)
                        R['tags_after_tour'] = \
                            pane._buffer.get_tag_table().get_size()
                        GLib.timeout_add(1200, one_round)
                        return GLib.SOURCE_REMOVE
                    b, c = tour[st2['i']]
                    st2['i'] += 1
                    pane.force_navigate(b, c, 1)
                    return GLib.SOURCE_CONTINUE
                GLib.timeout_add(700, step)
                return GLib.SOURCE_REMOVE
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
        win.set_default_size(1200, 900)

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
    parser.add_argument('--settings', metavar='FILE',
                        help='copy this settings.json into the scratch config')
    parser.add_argument('--native', action='store_true',
                        help='run on the real display, not broadway')
    args = parser.parse_args()

    import shutil
    if not args.native and shutil.which('gtk4-broadwayd') is None:
        print('gtk4-broadwayd not found', file=sys.stderr)
        return 2
    book, _, chapter = args.ref.rpartition(' ')

    with tempfile.TemporaryDirectory(prefix='scriptura-fn-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        if args.native:
            env.pop('GDK_BACKEND', None)
            for k in ('WAYLAND_DISPLAY', 'DISPLAY', 'XDG_RUNTIME_DIR'):
                if k in os.environ:
                    env[k] = os.environ[k]
        else:
            env['GDK_BACKEND'] = 'broadway'
            env['BROADWAY_DISPLAY'] = f':{DISPLAY}'
        for var in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
            env[var] = 'http://127.0.0.1:1'
        report = Path(scratch, 'report.json')
        env.update(PROBE_OUT=str(report), PROBE_MODULE=args.module,
                   PROBE_BOOK=book, PROBE_CHAPTER=chapter)
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        if args.settings:
            src = json.loads(Path(args.settings).read_text())
            src['open_to_today'] = False
            (cfg / 'settings.json').write_text(json.dumps(src))
        else:
            (cfg / 'settings.json').write_text(json.dumps({
                'open_to_today': False, 'split_pane_mode': False,
                'pane1_module': args.module, 'show_headings': True,
                'show_footnotes': True, 'smallcaps_divine': True,
                'oldstyle_numerals': True, 'colored_dropcap': True,
            }))

        if args.native:
            subprocess.run([sys.executable, __file__, '--driver'], env=env,
                           cwd=REPO_ROOT, timeout=DRIVER_TIMEOUT,
                           stdout=subprocess.DEVNULL)
            if not report.exists():
                print('driver produced no report', file=sys.stderr)
                return 1
            print(json.dumps(json.loads(report.read_text()), indent=1))
            return 0
        broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'], env=env,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            sock = Path(env['XDG_RUNTIME_DIR'], f'broadway{DISPLAY + 1}.socket')
            deadline = time.monotonic() + 5.0
            while not sock.exists():
                if broadwayd.poll() is not None or time.monotonic() > deadline:
                    print('broadwayd failed to start', file=sys.stderr)
                    return 2
                time.sleep(0.05)
            subprocess.run([sys.executable, __file__, '--driver'], env=env,
                           cwd=REPO_ROOT, timeout=DRIVER_TIMEOUT,
                           stdout=subprocess.DEVNULL)
            if not report.exists():
                print('driver produced no report', file=sys.stderr)
                return 1
            data = json.loads(report.read_text())
        finally:
            broadwayd.terminate()
            broadwayd.wait()

    print(json.dumps(data, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(run_driver() if '--driver' in sys.argv else orchestrate())
