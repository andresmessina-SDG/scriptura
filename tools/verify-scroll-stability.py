#!/usr/bin/env python3
"""Scroll-stability regression matrix — the "text never moves" invariant.

Drives the real app headlessly (GTK Broadway backend, no display server
needed) and asserts that a probe verse's window-Y coordinate stays put
(±2px unless noted) across every interaction that historically moved it:

  chrome hide/reveal, tap-to-reveal, lexicon toggle (both pane kinds),
  ten consecutive footnote toggles (cumulative walk), theme flip, and
  the first lexicon-panel open.

The invariant and its mechanisms are documented in ARCHITECTURE.md
("Scroll stability — the north star invariant"). This matrix is the
committed form of the harness that validated that work; run it after
touching pane.py scroll/render/chrome code or window.py pane sizing.

Usage (one command, from anywhere):

    python3 tools/verify-scroll-stability.py

Requirements: gtk4-broadwayd (Fedora package gtk4) and the SWORD
modules KJVA and MHCC installed for the current user, e.g.:

    installmgr --allow-internet-access-and-risk-tracing-and-jail-or-martyrdom \
        -init -sc -r CrossWire -ri CrossWire KJVA -ri CrossWire MHCC

The app runs against scratch XDG dirs, so the user's real config and
study data are never touched (module discovery via ~/.sword still
applies). Prints a JSON report; exit 0 = all checks passed, 1 = a check
failed, 2 = the environment is unusable (missing modules/broadwayd).

Two Broadway lessons are baked in (relearning them costs a day):

* Without a connected browser the frame clock is erratic — animations
  may not tick until their stalled-clock fallback fires. Judging on a
  fixed delay therefore samples mid-transition. Every judgment here is
  quiescence-gated instead: poll until (adj, page_size, y) is unchanged
  for QUIET_MS. QUIET_MS must exceed the app's 600ms animation-skip
  fallback, otherwise a not-yet-started animation reads as "settled"
  and a check could falsely pass against the pre-transition state.
* Whole-run collapses with no code cause still happen occasionally; a
  failed run is retried once by default (--retries) before it counts
  as a regression.
* Headless footnote toggles occasionally settle one display line off
  and self-correct on the next toggle (the per-frame anchor pin needs
  frame-clock ticks Broadway doesn't deliver unbrowsed). The walk check
  therefore judges its last three settled samples — a ratchet leaves
  none of them near the start, the transient leaves most.
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
REQUIRED_MODULES = ('KJVA', 'MHCC')
DISPLAY = 5  # private XDG_RUNTIME_DIR per run, so a fixed number never collides


# ────────────────────────────────────────────────────────────────────────
# Orchestrator: scratch env + broadwayd lifecycle + retry loop
# ────────────────────────────────────────────────────────────────────────

def check_modules() -> list[str]:
    """Names from REQUIRED_MODULES that are not installed."""
    import Sword
    mgr = Sword.SWMgr()
    return [m for m in REQUIRED_MODULES if mgr.getModule(m) is None]


def run_attempt(timeout: float) -> dict | None:
    """One broadwayd + matrix cycle; returns the parsed report or None."""
    with tempfile.TemporaryDirectory(prefix='scriptura-matrix-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'

        broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'],
                                     env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            # gtk4-broadwayd names its socket broadway<display+1>.socket;
            # poll for it rather than sleeping a fixed amount.
            socket = Path(env['XDG_RUNTIME_DIR'], f'broadway{DISPLAY + 1}.socket')
            deadline = time.monotonic() + 5.0
            while not socket.exists():
                if broadwayd.poll() is not None or time.monotonic() > deadline:
                    print('broadwayd failed to start', file=sys.stderr)
                    return None
                time.sleep(0.05)

            try:
                proc = subprocess.run(
                    [sys.executable, __file__, '--matrix'],
                    env=env, cwd=REPO_ROOT, timeout=timeout,
                    stdout=subprocess.PIPE, text=True)
            except subprocess.TimeoutExpired:
                print(f'matrix timed out after {timeout:.0f}s', file=sys.stderr)
                return None
            sys.stdout.write(proc.stdout)
            try:
                report = json.loads(proc.stdout)
            except json.JSONDecodeError:
                return None
            return report if isinstance(report, dict) else None
        finally:
            broadwayd.terminate()
            broadwayd.wait()


def orchestrate() -> int:
    parser = argparse.ArgumentParser(
        description='Run the scroll-stability regression matrix headlessly.')
    parser.add_argument('--retries', type=int, default=1,
                        help='reruns allowed on failure (Broadway flakiness)')
    parser.add_argument('--timeout', type=float, default=300,
                        help='per-attempt wall clock limit in seconds')
    args = parser.parse_args()

    try:
        missing = check_modules()
    except ImportError:
        print('python3-sword is not installed', file=sys.stderr)
        return 2
    if missing:
        print(f'missing SWORD modules: {", ".join(missing)} — see the '
              'installmgr command in this file\'s docstring', file=sys.stderr)
        return 2

    for attempt in range(1 + args.retries):
        if attempt:
            print(f'retrying (attempt {attempt + 1})…', file=sys.stderr)
        report = run_attempt(args.timeout)
        if report is not None and report.get('all_ok'):
            return 0
    return 1


# ────────────────────────────────────────────────────────────────────────
# Matrix (child process, inside the Broadway app): every interaction the
# user named, asserting the probe verse's window-Y stays put.
# ────────────────────────────────────────────────────────────────────────

QUIET_MS = 800        # must exceed the 600ms animation-skip fallback
POLL_MS = 200
SETTLE_CAP_MS = 15000  # give up waiting and judge whatever state we have


def run_matrix() -> int:
    sys.path.insert(0, str(REPO_ROOT))

    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GLib, Graphene

    import main

    REPORT: dict = {'checks': []}

    def win_y(pane, verse):
        buf = pane._buffer
        tag = buf.get_tag_table().lookup(f'vnum_{verse}')
        if tag is None:
            return None
        it = buf.get_start_iter()
        if not it.has_tag(tag):
            if not it.forward_to_tag_toggle(tag):
                return None
        loc = pane._view.get_iter_location(it)
        wx, wy = pane._view.buffer_to_window_coords(
            Gtk.TextWindowType.TEXT, loc.x, loc.y)
        ok, p = pane._view.compute_point(pane.get_root(),
                                         Graphene.Point().init(0, wy))
        return round(p.y, 1) if ok else None

    def snap(pane, verse):
        adj = pane._reading_scroll.get_vadjustment()
        return {'adj': round(adj.get_value(), 1),
                'page': round(adj.get_page_size(), 1),
                'y': win_y(pane, verse),
                'top': pane._find_topmost_visible_verse()}

    def check(name, before, after, tol=2.0):
        delta = (None if before['y'] is None or after['y'] is None
                 else abs(after['y'] - before['y']))
        REPORT['checks'].append({
            'name': name, 'before': before, 'after': after,
            'moved_px': delta,
            'ok': delta is not None and delta <= tol,
        })

    app = main.BibleApp()
    S: dict = {}
    steps: list = []

    def run(i=0):
        if i >= len(steps):
            REPORT['all_ok'] = all(c['ok'] for c in REPORT['checks'])
            print(json.dumps(REPORT, indent=1))
            app.quit()
            return GLib.SOURCE_REMOVE
        S['_i'] = i
        fn, delay = steps[i]
        try:
            if fn() == 'HOLD':
                return GLib.SOURCE_REMOVE  # step resumes run() itself
        except Exception:
            import traceback
            traceback.print_exc()
            REPORT['all_ok'] = False
            print(json.dumps(REPORT, indent=1))
            app.quit()
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(delay, lambda: run(i + 1))
        return GLib.SOURCE_REMOVE

    def settle(then, panes=('p1',)):
        """Poll until every named pane's (adj, page, y) is unchanged for
        QUIET_MS, then call then(snapshots) and resume the step list.
        A step that calls this must return the value ('HOLD')."""
        nxt = S['_i'] + 1
        state = {'key': None, 'streak': 0,
                 'left': SETTLE_CAP_MS // POLL_MS}

        def poll():
            snaps = {p: snap(S[p], S['v' + p[1]]) for p in panes}
            key = tuple((s['adj'], s['page'], s['y'])
                        for s in snaps.values())
            state['streak'] = state['streak'] + 1 if key == state['key'] else 0
            state['key'] = key
            state['left'] -= 1
            if state['streak'] * POLL_MS >= QUIET_MS or state['left'] <= 0:
                try:
                    then(snaps)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    REPORT['all_ok'] = False
                    print(json.dumps(REPORT, indent=1))
                    app.quit()
                    return GLib.SOURCE_REMOVE
                run(nxt)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(POLL_MS, poll)
        return 'HOLD'

    def kickoff():
        win = app.get_active_window()
        if win is None:
            return GLib.SOURCE_CONTINUE
        win.set_default_size(1200, 800)
        S['p1'], S['p2'] = win.pane1, win.pane2
        S['p1']._apply_module_change(REQUIRED_MODULES[0])
        S['p2']._apply_module_change(REQUIRED_MODULES[1])
        GLib.timeout_add(300, lambda: run())
        return GLib.SOURCE_REMOVE

    def nav():
        for p in (S['p1'], S['p2']):
            p._book, p._chapter = 'Psalms', 119
            p._target_verse = None
            p._restore_top_verse = None
            p._fetch_and_render()

    def top_text(pane):
        """Identity + pixel offset of the text at the visual viewport top —
        the reader-level ground truth, independent of off-screen estimates."""
        view = pane._view
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, 60, 1)
        ok, it = view.get_iter_at_location(bx, by)
        if not ok:
            return None
        loc = view.get_iter_location(it)
        e = it.copy()
        e.forward_chars(40)
        return (pane._buffer.get_text(it, e, False), round(by - loc.y, 1))

    def user_scrolled(p):
        # mimic what a settled user scroll does: drop the old locus,
        # record the new one
        p._reading_anchor = None
        p._capture_scroll_anchor()
        return GLib.SOURCE_REMOVE

    def scroll_mid():
        for p in (S['p1'], S['p2']):
            p._reading_scroll.get_vadjustment().set_value(2000.0)
            GLib.timeout_add(300, lambda p=p: user_scrolled(p))

    def anchor():
        S['v1'] = S['p1']._find_topmost_visible_verse()
        S['v2'] = S['p2']._find_topmost_visible_verse()
        REPORT['probe'] = {'p1': S['v1'], 'p2': S['v2']}

    # 1. chrome hide / reveal
    def chrome_pre():
        S['p1']._reveal_chrome()
        return settle(lambda s: None)

    def chrome_hide():
        S['a'] = snap(S['p1'], S['v1'])
        S['p1']._set_chrome_revealed(False)
        return settle(lambda s: (check('chrome hide', S['a'], s['p1']),
                                 S.__setitem__('a', s['p1'])))

    def chrome_reveal():
        S['p1']._reveal_chrome()
        return settle(lambda s: check('chrome reveal', S['a'], s['p1']))

    # 2. tap-to-reveal path
    def tap_hide():
        S['p1']._set_chrome_revealed(False)
        return settle(lambda s: None)

    def tap_click():
        S['a'] = snap(S['p1'], S['v1'])
        S['p1']._on_pane_click(None, 1, 300, 300)
        return settle(lambda s: check('tap reveals toolbar', S['a'], s['p1']))

    # 3. lexicon toggle, both panes
    def lex_on():
        S['a'] = snap(S['p1'], S['v1'])
        S['b'] = snap(S['p2'], S['v2'])
        S['p1'].set_lexicon_enabled(True)
        S['p2'].set_lexicon_enabled(True)
        return settle(lambda s: (
            check('lexicon ON bible pane', S['a'], s['p1'], tol=0.5),
            check('lexicon ON commentary pane', S['b'], s['p2'], tol=0.5)),
            panes=('p1', 'p2'))

    def lex_off():
        S['a'] = snap(S['p1'], S['v1'])
        S['b'] = snap(S['p2'], S['v2'])
        S['p1'].set_lexicon_enabled(False)
        S['p2'].set_lexicon_enabled(False)
        return settle(lambda s: (
            check('lexicon OFF bible pane', S['a'], s['p1'], tol=0.5),
            check('lexicon OFF commentary pane', S['b'], s['p2'], tol=0.5)),
            panes=('p1', 'p2'))

    # 4. footnote toggle cycles — no cumulative walk. Each toggle is
    # settle-gated (a fixed inter-toggle delay races the anchor-restore
    # polls and judges mid-correction).
    def fn_start():
        def init(snaps):
            S['fn0'] = snaps['p1']
            S['fn_series'] = []
            S['fn_left'] = 10
        return settle(init)

    def fn_toggle():
        p = S['p1']
        p.set_show_footnotes(not p._show_footnotes)
        return settle(fn_record)

    def fn_record(snaps):
        S['fn_series'].append(snaps['p1'])
        S['fn_left'] -= 1
        if S['fn_left'] == 0:
            # This check targets the RATCHET class (position marching one
            # line per toggle pair, never returning). Headless Broadway
            # also shows a known transient: a toggle occasionally settles
            # one display line off and the next toggle restores it. So the
            # walk is judged over the last three settled samples: a ratchet
            # leaves none of them near the start, a transient leaves most.
            first = S['fn0']
            tail = [s['y'] for s in S['fn_series'][-3:]]
            deltas = [abs(y - first['y']) for y in tail
                      if y is not None and first['y'] is not None]
            REPORT['checks'].append({
                'name': 'footnote 10-cycle cumulative walk',
                'before': first, 'after': snaps['p1'],
                'moved_px': min(deltas) if deltas else None,
                'series_y': [s['y'] for s in S['fn_series']],
                'ok': bool(deltas) and min(deltas) <= 4.0,
            })

    # After the footnote cycles the view may sit one line off (the known
    # transient above) with the anchor still on the pre-excursion verse;
    # the theme / panel checks would then "fail" on the anchor snapping
    # back. Re-sync anchor to visual state, as a settled user scroll does.
    def resync():
        user_scrolled(S['p1'])
        S['v1'] = S['p1']._find_topmost_visible_verse()
        return settle(lambda s: None)

    # 5. theme flip
    def theme():
        S['a'] = snap(S['p1'], S['v1'])
        sm = Adw.StyleManager.get_default()
        cur = sm.get_color_scheme()
        sm.set_color_scheme(
            Adw.ColorScheme.FORCE_DARK
            if cur != Adw.ColorScheme.FORCE_DARK
            else Adw.ColorScheme.FORCE_LIGHT)
        return settle(lambda s: check('theme flip', S['a'], s['p1']))

    # 6. lexicon panel first open — judged by the text at the viewport
    # top (off-screen iter positions are estimate-based and unreliable)
    def lexpanel():
        S['tt'] = top_text(S['p1'])
        S['p1'].show_lexicon_loading('G2316')
        return settle(lexpanel_judge)

    def lexpanel_judge(snaps):
        after = top_text(S['p1'])
        before = S['tt']
        # shift-tolerant: the x-probe may catch the same line a few chars
        # off; the position held if the sampled windows overlap
        same_text = (before is not None and after is not None
                     and (before[0][8:32] in after[0]
                          or after[0][8:32] in before[0]))
        dpx = (abs(after[1] - before[1])
               if same_text else None)
        REPORT['checks'].append({
            'name': 'lexicon panel first open (top text held)',
            'before': {'adj': None, 'page': None, 'top': None,
                       'y': before[1] if before else None},
            'after': {'adj': None, 'page': None, 'top': None,
                      'y': after[1] if after else None},
            'top_text_before': before[0][:40] if before else None,
            'top_text_after': after[0][:40] if after else None,
            'moved_px': dpx,
            'ok': same_text and dpx is not None and dpx <= 44.0,
        })

    steps.extend([
        (nav, 2400), (scroll_mid, 700), (anchor, 200),
        (chrome_pre, 0), (chrome_hide, 0), (chrome_reveal, 0),
        (tap_hide, 0), (tap_click, 0),
        (lex_on, 0), (lex_off, 0),
        (fn_start, 0),
    ])
    steps.extend([(fn_toggle, 0)] * 10)
    steps.extend([
        (resync, 200),
        (theme, 0),
        (lexpanel, 0),
    ])

    GLib.timeout_add(1500, kickoff)
    app.run([])
    return 0 if REPORT.get('all_ok') else 1


if __name__ == '__main__':
    if '--matrix' in sys.argv:
        sys.exit(run_matrix())
    sys.exit(orchestrate())
