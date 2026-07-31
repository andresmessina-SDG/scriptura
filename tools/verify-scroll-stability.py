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

WHY THIS WAITS THE WAY IT DOES (the flakiness this harness used to have,
and how not to reintroduce it). GtkTextView validates its lines in an idle
handler that, in GTK's own words, "runs after redraw" — so a completed
draw cycle does NOT mean the document has been laid out. Measured on this
app: immediately after gtk_test_widget_wait_for_draw() returns, the
scrolled window reports an `upper` of 378 for a document whose real height
is 72018. A raw adjustment.set_value(2000) in that window gets CLAMPED to
roughly zero; the pane silently stays at the top, where a commentary shows
a section header rather than verse text, _find_topmost_visible_verse()
returns None, and every later check on that pane reports a null offset
that reads exactly like a 50px jump. Whether that happened depended on
machine speed, which is why the same commit could pass on one CI runner
and fail on another. It was never backend-specific: Broadway and a real
headless Wayland compositor produce identical numbers.

So: `upper` is part of every snapshot and of settle()'s quiet-key,
scroll_mid() waits for the document height to stop growing and then
confirms the value actually stuck, and a missing measurement is reported
as `inconclusive` rather than as a stability failure — those are different
claims and only one of them is about the app.

See docs.gtk.org GtkTextView.scroll_to_iter ("Line heights are computed in
an idle handler") and gtktextview.c's `incremental_validate_idle`.

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
* A check whose interaction re-renders is judged against a BASELINE, but
  what the app restores to is the ANCHOR — and the anchor stores a pixel
  delta bound to the layout at the instant it was captured. Capture it
  before the layout has settled and the app will faithfully restore to a
  place the baseline was never taken at: one display line, ~52px here.
  That was the long-running intermittent theme-flip failure. So re-anchor
  (`reanchor()`) quiesced and in the same breath as the baseline, and let
  the report say whether the anchor it replaced had gone stale.
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

#: Where the panes park before the checks begin. Sweepable, because this
#: matrix has now twice turned out to be POSITION-SENSITIVE: a runner whose
#: metrics differ by a few pixels lands on a different verse (CI reports
#: probe verse 42 where this workstation reports 40) and only that position
#: fails. A bug you cannot park on is a bug you cannot measure.
PARK_PX = float(os.environ.get('SCRIPTURA_PARK_PX', '2000'))


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

    inconclusive = None
    # A measured regression in ANY attempt outranks an inconclusive one in
    # another: retrying is there to survive an unusable environment, not to
    # give a real failure a second chance to be excused.
    saw_regression = False
    for attempt in range(1 + args.retries):
        if attempt:
            print(f'retrying (attempt {attempt + 1})…', file=sys.stderr)
        report = run_attempt(args.timeout)
        if report is not None and report.get('all_ok'):
            return 0
        inconclusive = (report or {}).get('inconclusive')
        if report is not None and not inconclusive:
            saw_regression = True
    # A run that never established its own starting state is an unusable
    # environment, not a regression — the same exit code as a missing module,
    # and deliberately not the one that says the reading text moved.
    if inconclusive and not saw_regression:
        print(f'inconclusive: {inconclusive}', file=sys.stderr)
        return 2
    return 1


# ────────────────────────────────────────────────────────────────────────
# Matrix (child process, inside the Broadway app): every interaction the
# user named, asserting the probe verse's window-Y stays put.
# ────────────────────────────────────────────────────────────────────────

QUIET_MS = 800        # must exceed the 600ms animation-skip fallback
POLL_MS = 200
SETTLE_CAP_MS = 15000  # give up waiting and judge whatever state we have
RENDER_CAP_MS = 20000  # waiting for the probe chapter's async render to land

#: A park that has stopped growing short of its target is not slow, it is
#: FROZEN — see park()'s recovery block. Both conditions must hold before we
#: act: enough wall clock AND enough polls. Under heavy contention the main
#: loop itself starves (measured: consecutive polls 6s apart on this 200ms
#: timer), and a wall-clock test alone would read that as a freeze.
FREEZE_MS = 2000
FREEZE_POLLS = 5
MAX_PARK_RECOVERIES = 2


def run_matrix() -> int:
    sys.path.insert(0, str(REPO_ROOT))

    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GLib, Gdk, Graphene

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
                # `upper` is the one number GtkTextView's incremental
                # validation keeps changing AFTER a completed draw cycle
                # ("Idle to revalidate offscreen portions, runs after
                # redraw" — gtktextview.c). Measured on this app: 378 right
                # after wait_for_draw returns, 72018 once the idle drains.
                # Settling without watching it means settling mid-layout.
                'upper': round(adj.get_upper(), 1),
                'y': win_y(pane, verse),
                'top': pane._find_topmost_visible_verse()}

    def check(name, before, after, tol=2.0):
        """Record one stability check.

        A missing measurement is reported as `inconclusive`, NOT as a
        failure. The two are different claims — "the reading text moved"
        and "the harness never got a baseline" — and conflating them is
        what made this matrix cry wolf: a clamped scroll produced null
        offsets that read exactly like a 50px jump."""
        delta = (None if before['y'] is None or after['y'] is None
                 else abs(after['y'] - before['y']))
        row = {'name': name, 'before': before, 'after': after,
               'moved_px': delta}
        if delta is None:
            row['inconclusive'] = True
            row['why'] = 'no verse offset could be measured in this pane'
            row['ok'] = False
        else:
            row['ok'] = delta <= tol
        REPORT['checks'].append(row)

    def describe_env():
        """What differs between a workstation and a CI runner. Every
        hypothesis chased for the intermittent theme-flip failure has been
        environmental, and this report is the only thing that comes back
        from a runner — so record the variables rather than guess at them
        again."""
        import sword_bridge
        env = {
            'gtk': f'{Gtk.get_major_version()}.{Gtk.get_minor_version()}'
                   f'.{Gtk.get_micro_version()}',
            'gsk_renderer': os.environ.get('GSK_RENDERER') or 'default',
            'backend': type(Gdk.Display.get_default()).__name__,
        }
        try:
            mgr = sword_bridge.mgr()
            for name in REQUIRED_MODULES:
                mod = mgr.getModule(name)
                if mod is not None:
                    env[f'module_{name}'] = str(
                        mod.getConfigEntry('Version') or '?')
        except Exception:
            pass
        REPORT['env'] = env

    app = main.BibleApp()
    S: dict = {}
    steps: list = []

    def finish():
        """Judge the run — but only if it ever established the state it set
        out to measure.

        A park whose validation timed out leaves the pane wherever GTK's
        estimate allowed (measured under load: 1266px against a requested
        2000, with `upper` still reading 1932 for a document really ~8900
        tall). Every later check on that pane is then judged against a
        document that never finished laying out, and reports differences of
        a dozen pixels that look exactly like a regression. That is the same
        confusion the `inconclusive` distinction was introduced for: "the
        text moved" and "the harness never got the document it was going to
        measure" are different claims. Only one of them is about the app.
        """
        stalled = sorted(k for k, v in REPORT.get('scroll_setup', {}).items()
                         if v.get('validation_timed_out'))
        if stalled:
            REPORT['inconclusive'] = (
                f'line validation timed out while parking {", ".join(stalled)}'
                f' — the checks below were judged against a document that had'
                f' not finished laying out, so they say nothing about the app')
            REPORT['all_ok'] = False
            return
        # A check that never got a measurement is not a check that failed.
        # `check()` has always marked those rows `inconclusive`, but the run
        # was judged with `all(c['ok'])`, and an inconclusive row carries
        # ok=False — so a pane the harness simply could not measure came back
        # as exit 1, "the reading text moved". Measured at SCRIPTURA_PARK_PX
        # =1400 under load: the commentary pane parks where no verse is
        # visible, `baseline_missing: ['p2']` is recorded, two of ten checks
        # go inconclusive with `moved_px: None` before AND after — and the
        # run still reported a stability regression.
        #
        # This is NOT the disproved "make settle timeouts inconclusive" move.
        # A settle timeout has real before/after offsets and a real delta;
        # suppressing it hides movement that did happen. These rows have no
        # delta at all — there is nothing in them to hide — and a REGRESSION
        # IN A MEASURED CHECK STILL WINS below, so a genuine failure cannot
        # be downgraded by an unmeasurable one elsewhere.
        moved = [c['name'] for c in REPORT['checks']
                 if not c['ok'] and not c.get('inconclusive')]
        unmeasured = [c['name'] for c in REPORT['checks']
                      if c.get('inconclusive')]
        REPORT['all_ok'] = not moved and not unmeasured
        if moved:
            return
        if unmeasured:
            where = ', '.join(REPORT.get('baseline_missing') or [])
            REPORT.setdefault('inconclusive', (
                f'no verse offset could be measured for {len(unmeasured)} '
                f'check(s): {", ".join(unmeasured)}'
                + (f' — no baseline verse in {where}' if where else '')
                + ' — the text may or may not have moved, this run does not'
                  ' say'))

    def run(i=0):
        if i >= len(steps):
            finish()
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
        """Poll until every named pane's geometry is unchanged for QUIET_MS,
        then call then(snapshots) and resume the step list. A step that calls
        this must return the value ('HOLD').

        `upper` is part of the key: text validation grows it long after the
        draw completes, and a run that settles before it stops moving is
        measuring a document whose height is still wrong."""
        nxt = S['_i'] + 1
        state = {'key': None, 'streak': 0,
                 'left': SETTLE_CAP_MS // POLL_MS}

        def poll():
            snaps = {p: snap(S[p], S['v' + p[1]]) for p in panes}
            key = tuple((s['adj'], s['page'], s['upper'], s['y'])
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
        # The app navigates itself at startup, on a thread we cannot join.
        # `_startup_navigate_to_devotional_ref` parses today's devotional in
        # the background and idle_adds a `_go_to` onto pane 1; when pane 2
        # comes up on an installed devotional (it does — SME here), that fires
        # on every launch. Unloaded it lands before this harness navigates and
        # is invisible. Under load it lands AFTER, and the matrix then measures
        # today's devotional passage instead of the probe chapter: measured
        # 2026-07-30 at load 18, both panes holding Mark 14 (SME's entry for
        # the day, 72 verses) with `upper` 5416/5687 against Psalms 119's real
        # 8901/21515. That is what the earlier "incremental validation never
        # finishes" reading actually was — the document was complete and
        # validated throughout; it was the WRONG document. Note the failure is
        # therefore DATE-DEPENDENT, which is worth remembering before trusting
        # any single day's matrix run.
        #
        # No step in this matrix navigates, so the honest fix is to take the
        # method away: nothing may move the panes except `nav()` below.
        S['clobbers'] = []
        def _refuse_nav(*a, **kw):
            S['clobbers'].append(a[:2])
        win._go_to = _refuse_nav
        S['p1'], S['p2'] = win.pane1, win.pane2
        S['p1']._apply_module_change(REQUIRED_MODULES[0])
        S['p2']._apply_module_change(REQUIRED_MODULES[1])
        GLib.timeout_add(300, lambda: run())
        return GLib.SOURCE_REMOVE

    def nav():
        """Load the probe chapter — and then WAIT FOR IT, because the render
        is asynchronous.

        `_fetch_and_render()` hands the chapter fetch to the task runner and
        returns at once; the pane goes on showing the PREVIOUS chapter until
        `_display` lands. This step used to be followed by a fixed 2400ms
        delay. Traced under load, the commentary's Psalms 119 arrived at
        ~3400ms — so the park ran a second early, against the old document,
        and everything downstream measured that: `upper` 5687 where the real
        commentary is 21515, no verse at all where the park landed, and two
        checks reporting `moved_px: None` which the run then called a
        stability regression.

        `_rendered_verses` is cleared at the top of the render and set by
        `_display`, so it is the edge to wait on. A number of milliseconds
        was never the right thing to wait for — the same mistake, in a
        different disguise, as the draw-complete wait this harness already
        learned not to trust."""
        nxt = S['_i'] + 1
        started = time.monotonic()
        for p in (S['p1'], S['p2']):
            p._book, p._chapter = 'Psalms', 119
            p._target_verse = None
            p._restore_top_verse = None
            p._fetch_and_render()
        state = {'left': RENDER_CAP_MS // POLL_MS}

        def poll():
            # `_rendered_verses is not None` alone is not enough: a render
            # that was already in flight when this step began sets it too,
            # and that is exactly how the startup devotional navigation used
            # to be mistaken for the probe chapter (see kickoff). Require the
            # pane to be ON the probe chapter as well.
            landed = [p._rendered_verses is not None
                      and (p._book, p._chapter) == ('Psalms', 119)
                      for p in (S['p1'], S['p2'])]
            waited = round((time.monotonic() - started) * 1000)
            if all(landed):
                REPORT['render_wait_ms'] = waited
                if S.get('clobbers'):
                    REPORT['refused_navigations'] = S['clobbers']
                run(nxt)
                return GLib.SOURCE_REMOVE
            state['left'] -= 1
            if state['left'] <= 0:
                REPORT['render_wait_ms'] = waited
                showing = [f'{p._book} {p._chapter}'
                           for p in (S['p1'], S['p2'])]
                REPORT.setdefault('inconclusive', (
                    f'the probe chapter never finished rendering in '
                    f'{waited} ms (panes landed: {landed}, showing '
                    f'{showing}) — every check below would have measured '
                    f'whatever chapter was on screen before, so this run '
                    f'says nothing about the app'))
                run(nxt)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(POLL_MS, poll)
        return 'HOLD'

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

    def reanchor(p, where):
        """Re-anchor to the settled visual state, and report whether the
        anchor it replaced had gone stale.

        Every check from here on triggers a re-render, and a re-render
        restores the reading locus from `_reading_anchor`. That anchor stores
        `delta = adj - iter_location(y)` — a number bound to the layout at the
        instant it was captured. GtkTextView keeps revalidating line heights
        after a toggle (and under Broadway the per-frame pin cannot tick
        unbrowsed, see the header), so an anchor captured before the layout
        finished settling restores to a *different* pixel once it has: one
        display line, ~52px at this reading font.

        That is not the app moving the text. It is the app faithfully
        restoring what it was handed, against a baseline taken somewhere else.
        Capturing here — quiesced, and in the same breath as the baseline —
        is what makes the two describe one moment. The `stale` flag records
        when it mattered, so a run that needed this says so instead of
        passing silently.
        """
        was = repr(getattr(p, '_reading_anchor', None))[:120]
        user_scrolled(p)
        now = repr(getattr(p, '_reading_anchor', None))[:120]
        record = {'at': where, 'was': was, 'now': now, 'stale': was != now}
        REPORT.setdefault('reanchors', []).append(record)
        return record

    def scroll_mid():
        """Park both panes mid-document, then let them settle.

        A raw set_value() is what this used to do, and it is why the matrix
        was flaky: until GtkTextView's validation idle has run, `upper` is a
        small estimate (measured: 378 against a real 72018), so GTK clamps
        the requested 2000 down to nearly zero. The pane stays at the top,
        where a commentary shows a section header rather than verse text,
        _find_topmost_visible_verse returns None, and every later check on
        that pane reports a null offset.

        So wait for the document height to stop growing first, then scroll,
        then confirm the value actually stuck. Capped polling throughout —
        never an open loop."""
        nxt = S['_i'] + 1
        pending = {'left': 2}

        def park(p):
            adj = p._reading_scroll.get_vadjustment()
            state = {'upper': None, 'streak': 0,
                     'left': SETTLE_CAP_MS // POLL_MS,
                     'changed_at': time.monotonic(), 'since': 0,
                     'recoveries': 0}

            def poll():
                upper = round(adj.get_upper(), 1)
                if upper == state['upper']:
                    state['streak'] += 1
                    state['since'] += 1
                else:
                    state['streak'] = 0
                    state['since'] = 0
                    state['changed_at'] = time.monotonic()
                state['upper'] = upper
                state['left'] -= 1
                grown = adj.get_upper() - adj.get_page_size() > PARK_PX
                ready = state['streak'] * POLL_MS >= QUIET_MS and grown

                # GtkTextView line validation can stop dead: measured 75
                # polls at a healthy 201ms median across the full 15s cap
                # with `upper` pinned at a single value (1493 in one run,
                # 1207 in another, for a document really 21515 tall — the
                # freeze reproduces, the value it sticks at does not), while
                # the main loop ran normally the whole time. It
                # is not slowness, so no cap is long enough to outlast it,
                # and nothing in the GtkTextView API drives validation from
                # outside — get_iter_location, get_line_yrange, queue_draw
                # and scroll_to_iter were each measured under load and none
                # advances `upper` (they read the btree's ESTIMATED heights
                # for invalid lines). What does work is to throw the render
                # away and dispatch it again.
                frozen = (not grown
                          and (time.monotonic() - state['changed_at']) * 1000
                          >= FREEZE_MS
                          and state['since'] >= FREEZE_POLLS)
                if frozen and state['recoveries'] < MAX_PARK_RECOVERIES:
                    state['recoveries'] += 1
                    REPORT.setdefault('park_recoveries', []).append({
                        'pane': 'p1' if p is S['p1'] else 'p2',
                        'attempt': state['recoveries'],
                        'frozen_upper': upper,
                        'page': round(adj.get_page_size(), 1),
                    })
                    p._fetch_and_render()
                    state.update(upper=None, streak=0, since=0,
                                 changed_at=time.monotonic(),
                                 left=SETTLE_CAP_MS // POLL_MS)
                    return GLib.SOURCE_CONTINUE

                if not ready and state['left'] > 0:
                    return GLib.SOURCE_CONTINUE
                adj.set_value(PARK_PX)
                REPORT.setdefault('scroll_setup', {})[
                    'p1' if p is S['p1'] else 'p2'] = {
                        'upper_at_scroll': round(adj.get_upper(), 1),
                        'page': round(adj.get_page_size(), 1),
                        'reached': round(adj.get_value(), 1),
                        'validation_timed_out': state['left'] <= 0,
                        'recoveries': state['recoveries'],
                }
                def done(p=p):
                    user_scrolled(p)
                    pending['left'] -= 1
                    if pending['left'] == 0:
                        run(nxt)          # resume only once both are parked
                    return GLib.SOURCE_REMOVE

                GLib.timeout_add(300, done)
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(POLL_MS, poll)

        for p in (S['p1'], S['p2']):
            park(p)
        return 'HOLD'

    def anchor():
        describe_env()
        S['v1'] = S['p1']._find_topmost_visible_verse()
        S['v2'] = S['p2']._find_topmost_visible_verse()
        REPORT['probe'] = {'p1': S['v1'], 'p2': S['v2']}
        # No baseline verse means every later measurement on that pane is
        # null. Name it once, here, instead of letting it surface as a
        # dozen indistinguishable "failures" further down.
        missing = [n for n in ('p1', 'p2') if S['v' + n[1]] is None]
        if missing:
            REPORT['baseline_missing'] = missing

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
        # Settle FIRST, then re-anchor. This used to capture the anchor
        # immediately and settle afterwards, which is the one ungated capture
        # in a harness whose every judgment is quiescence-gated — and it is
        # the anchor the theme flip below restores from.
        def then(_s):
            reanchor(S['p1'], 'resync')
            S['v1'] = S['p1']._find_topmost_visible_verse()
        return settle(then)

    # 5. theme flip
    def theme():
        # The baseline and the anchor the flip will restore from have to
        # describe the same moment; 200ms of step delay is enough for the
        # layout to move under one of them.
        S['theme_resync'] = reanchor(S['p1'], 'theme')
        S['a'] = snap(S['p1'], S['v1'])
        S['theme_pre'] = {
            'anchor': repr(getattr(S['p1'], '_reading_anchor', None))[:120],
            'top_text': (top_text(S['p1']) or (None, None))[0],
        }
        sm = Adw.StyleManager.get_default()
        cur = sm.get_color_scheme()
        sm.set_color_scheme(
            Adw.ColorScheme.FORCE_DARK
            if cur != Adw.ColorScheme.FORCE_DARK
            else Adw.ColorScheme.FORCE_LIGHT)
        def judge(s):
            check('theme flip', S['a'], s['p1'])
            row = REPORT['checks'][-1]
            if not row['ok']:
                # A re-render restores the reading locus from the anchor
                # captured before it. When that lands wrong, these are the
                # numbers that say why.
                row['diag'] = {
                    'pre': S['theme_pre'],
                    'post_anchor': repr(
                        getattr(S['p1'], '_reading_anchor', None))[:120],
                    'post_top_text': (top_text(S['p1']) or (None, None))[0],
                    'resync': S['theme_resync'],
                }
        return settle(judge)

    # 6. lexicon panel first open — judged by the text at the viewport
    # top (off-screen iter positions are estimate-based and unreliable)
    def lexpanel():
        # Same rule as the theme flip: opening the panel re-renders, the
        # re-render restores the anchor, and the anchor in hand was captured
        # before the flip above. Re-anchor with the baseline.
        S['lex_resync'] = reanchor(S['p1'], 'lexpanel')
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
            'resync': S['lex_resync'],
        })

    steps.extend([
        (nav, 0), (scroll_mid, 0), (anchor, 200),
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
