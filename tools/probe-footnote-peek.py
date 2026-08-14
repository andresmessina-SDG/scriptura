#!/usr/bin/env python3
"""Does every footnote marker in a chapter actually open its note?

Clicks each marker in reading order — the sequence a reader performs —
and reports whether the peek popover ends up visible, alongside the two
numbers that decide it: what the popover asks for in height, and the room
available on the side it opens.

The failure this exists for: a popover taller than the window is never
placed. GTK closes it the instant it is shown, the self-heal reshows it,
and after twelve rounds the note is unopenable — while a short note two
lines below opens first time, so the fault reads as arbitrary. It first
appeared on SpaPlatense (Straubinger), whose notes are a running
commentary rather than translation apologies: 2,377 characters on Psalm
51:13, ten of eighteen markers dead.

Runs on a headless mutter by default, and that matters: broadway gives a
popover no frame clock, so the reveal animation stalls at opacity 0 and
every peek looks broken whether it is or not (GUIDANCE §4). `--broadway`
is there for a machine with no mutter, where the opacity column is noise
and only `visible` means anything.

    python3 tools/probe-footnote-peek.py --module SpaPlatense --ref "Psalms 51"

Exit 0 = every marker opened · 1 = at least one did not · 2 = no display.
JSON to stdout only.
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
BROADWAY_DISPLAY = 9
WAYLAND_NAME = 'scriptura-fnpeek'
POLL_MS = 100
SETTLE_POLLS = 4
CAP_MS = 30000
SCROLL_MS = 250          # let the scroll land before reading pixel coords
OPEN_MS = 500            # ... and the popover settle before judging it
DRIVER_TIMEOUT = 300.0


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
    app = main.BibleApp()
    R: dict = {'module': os.environ['PROBE_MODULE'], 'ref': f'{book} {chapter}',
               'clicks': []}
    S: dict = {'tries': 0, 'events': []}

    def buftext(pane):
        b = pane._buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def finish(tag):
        R['exit_tag'] = tag
        clicks = R['clicks']
        R['opened'] = sum(1 for c in clicks if c['visible'])
        R['markers'] = len(clicks)
        R['failed'] = [c['letter'] for c in clicks if not c['visible']]
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

    def marker_runs(pane):
        """Every fnote:-tagged run in the buffer, in document order."""
        buf = pane._buffer
        runs = []
        it = buf.get_start_iter()
        while True:
            fn = [t.get_property('name') or '' for t in it.get_tags()]
            fn = [n for n in fn if n.startswith('fnote:')]
            if fn:
                start, end = it.copy(), it.copy()
                end.forward_char()
                while True:
                    nn = [t.get_property('name') or '' for t in end.get_tags()]
                    if not any(n.startswith('fnote:') for n in nn):
                        break
                    if not end.forward_char():
                        break
                runs.append({'tag': fn[0],
                             'letter': buf.get_text(start, end, False),
                             'offset': start.get_offset()})
                it = end
                continue
            if not it.forward_char():
                break
        return runs

    def watch(pane):
        """Record the popover's transitions — a failing peek shows as a
        popup/closed cycle repeating until the self-heal gives up."""
        pop = getattr(pane, '_dict_pop', None)
        if pop is None or getattr(pane, '_probe_watched', False):
            return
        pane._probe_watched = True
        pop.connect('closed', lambda _p: S['events'].append('closed'))
        for name in ('popup', 'popdown'):
            orig = getattr(pop, name)

            def wrap(*a, _o=orig, _n=name, **kw):
                S['events'].append(_n)
                return _o(*a, **kw)
            setattr(pop, name, wrap)

    def note_chars(pane, tag):
        verse, n = tag.split(':')[1:]
        entry = pane._chapter_footnotes.get((int(verse), n))
        return len(entry[1]) if entry else None

    def click(pane, run, then):
        buf, view = pane._buffer, pane._view
        view.scroll_to_iter(buf.get_iter_at_offset(run['offset']),
                            0.3, True, 0.0, 0.4)

        def after_scroll():
            r = view.get_iter_location(buf.get_iter_at_offset(run['offset']))
            wx, wy = view.buffer_to_window_coords(
                Gtk.TextWindowType.WIDGET,
                int(r.x + r.width / 2), int(r.y + r.height / 2))
            S['events'] = []
            # GTK's own order: the dict gesture is CAPTURE (it dismisses an
            # open peek), the left gesture BUBBLE (it opens the new one).
            pane._on_dict_click(None, 1, wx, wy)
            pane._on_left_click(None, 1, wx, wy)
            pane._on_left_release(None, 1, wx, wy)

            def judge():
                watch(pane)
                pop = getattr(pane, '_dict_pop', None)
                child = pop.get_child() if pop is not None else None
                root = pane.get_root()
                win_h = root.get_height() if root is not None else 0
                then({
                    'letter': run['letter'],
                    'tag': run['tag'],
                    'note_chars': note_chars(pane, run['tag']),
                    'wanted_h': (child.measure(Gtk.Orientation.VERTICAL, 320)[1]
                                 if child is not None else None),
                    'room_below': win_h - wy,
                    'room_above': wy,
                    'visible': bool(pop and pop.get_visible()),
                    'opacity': round(pop.get_opacity(), 3) if pop else None,
                    # None on the first click: the popover is created
                    # lazily, so there is nothing to watch until it exists.
                    'reshows': (S['events'].count('popup') - 1
                                if 'popup' in S['events'] else None),
                    'events': list(S['events']),
                })
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(OPEN_MS, judge)
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(SCROLL_MS, after_scroll)

    def run_sequence(pane):
        runs = marker_runs(pane)
        if not runs:
            R['error'] = 'no footnote markers rendered'
            return finish('no-markers')
        watch(pane)
        st = {'i': 0}

        def step(result=None):
            if result is not None:
                R['clicks'].append(result)
            if st['i'] >= len(runs):
                return finish('done')
            run = runs[st['i']]
            st['i'] += 1
            click(pane, run, step)
        step()

    def wait_arrived():
        S['tries'] += 1
        pane = S['win'].pane1
        if (getattr(pane, '_book', None) == book
                and int(getattr(pane, '_chapter', -1)) == chapter
                and buftext(pane).strip()):
            settle(pane, lambda _t: run_sequence(pane))
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


def start_display(env: dict, broadway: bool):
    """(process, socket) for the display the driver will use, or (None, None).

    A real compositor by default — a popover's reveal needs a frame clock,
    and broadway never gives it one.
    """
    import shutil
    if not broadway and shutil.which('mutter'):
        proc = subprocess.Popen(
            ['mutter', '--headless', f'--wayland-display={WAYLAND_NAME}',
             '--virtual-monitor', '1280x900'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        env['GDK_BACKEND'] = 'wayland'
        env['WAYLAND_DISPLAY'] = WAYLAND_NAME
        return proc, Path(env['XDG_RUNTIME_DIR'], WAYLAND_NAME)
    if shutil.which('gtk4-broadwayd') is None:
        return None, None
    proc = subprocess.Popen(
        ['gtk4-broadwayd', f':{BROADWAY_DISPLAY}'], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env['GDK_BACKEND'] = 'broadway'
    env['BROADWAY_DISPLAY'] = f':{BROADWAY_DISPLAY}'
    return proc, Path(env['XDG_RUNTIME_DIR'],
                      f'broadway{BROADWAY_DISPLAY + 1}.socket')


def orchestrate() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--module', default='SpaPlatense')
    parser.add_argument('--ref', default='Psalms 51')
    parser.add_argument('--broadway', action='store_true',
                        help='force broadway (no mutter available); the '
                             'opacity column then means nothing')
    args = parser.parse_args()

    book, _, chapter = args.ref.rpartition(' ')
    with tempfile.TemporaryDirectory(prefix='scriptura-fnpeek-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        for var in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
            env[var] = 'http://127.0.0.1:1'
        report = Path(scratch, 'report.json')
        env.update(PROBE_OUT=str(report), PROBE_MODULE=args.module,
                   PROBE_BOOK=book, PROBE_CHAPTER=chapter)
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / 'settings.json').write_text(json.dumps({
            'open_to_today': False, 'split_pane_mode': False,
            'pane1_module': args.module, 'show_headings': True,
            'show_footnotes': True, 'smallcaps_divine': True,
            'oldstyle_numerals': True, 'colored_dropcap': True,
        }))

        server, sock = start_display(env, args.broadway)
        if server is None:
            print('no display: neither mutter nor broadwayd started',
                  file=sys.stderr)
            return 2
        try:
            deadline = time.monotonic() + 12.0
            while not sock.exists():
                if server.poll() is not None or time.monotonic() > deadline:
                    print('display server failed to start', file=sys.stderr)
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
            server.terminate()
            server.wait()

    print(json.dumps(data, indent=1))
    return 0 if data.get('markers') and not data.get('failed') else 1


if __name__ == '__main__':
    sys.exit(run_driver() if '--driver' in sys.argv else orchestrate())
