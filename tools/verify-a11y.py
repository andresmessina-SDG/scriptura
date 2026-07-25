#!/usr/bin/env python3
"""Accessibility harness — asserts the real app's accessible tree.

Third companion to tools/verify-scroll-stability.py and tools/verify-today.py.
Those two check what the app *shows*; this checks what it *tells* — the
semantics AT-SPI clients (Orca) read, none of which is visible on screen and
so none of which a screenshot can catch.

It runs the app under GTK's `test` accessibility backend and uses GTK's own
assertion API — gtk_test_accessible_has_role / _has_property / _has_relation
— which reads the same GtkATContext the AT-SPI backend publishes from. That
makes the checks exact and display-independent; what it does NOT prove is how
Orca chooses to *speak* the result. **Real Orca remains the final oracle**
(GUIDANCE §1); this is the regression net under it.

**Why a compositor and not Broadway.** The other two harnesses drive the app
under gtk4-broadwayd. This one can't: on GTK 4.22.4 `gtk_accessible_announce()`
*segfaults* under the Broadway backend — reproducibly, varying by widget type
and a11y backend (GtkWindow and GtkButton crash, GtkLabel and GtkTextView
don't; GTK_A11Y=none is safe because announcing becomes a no-op). Under a real
Wayland compositor every one of those cases is safe, and so is the app. So the
bug is Broadway's, not the app's, and not something users can hit — but it does
mean announcements can only be exercised on a real compositor. `mutter
--headless --virtual-monitor` supplies one offscreen, without putting a window
on anyone's desktop. Where mutter is unavailable (a CI container with no DRM
device), the harness falls back to Broadway and reports the announcement checks
as **skipped** rather than failed — the role/relation half still runs there.

Two things are measured, not just asserted, and reported without gating:
the count of icon-only controls still lacking an accessible name, and the
roles the reading subsystems report — raw material for the next a11y pass.

What it asserts (exit 1 if any fail):

  1. every reading pane is a labelled GROUP, and its toolbar a labelled
     TOOLBAR — not the `generic` a bare Gtk.Box reports. GROUP rather than
     a landmark because GTK4's AT-SPI backend emits none: REGION, MAIN,
     NAVIGATION and BANNER all arrive as `filler`, measured against a live
     AT-SPI tree. GROUP maps to `grouping`;
  2. the reading TextView is a labelled DOCUMENT;
  3. the per-pane find bar is a labelled TOOLBAR whose counter is a STATUS
     region, and the counter DESCRIBES the search entry (the relation
     PyGObject silently drops if the value isn't a Gtk.AccessibleList);
  4. the window search panel's count label is a STATUS, the entry CONTROLS
     the results list, and the results list is named;
  5. status text is actually announced — driving the real handlers for
     "Searching…", a match count, and a verse's annotation state puts the
     expected messages through the live-region path;
  6. a verse announcement names its annotation state ("… highlighted
     yellow, has note"), which is A3's whole point: the highlight band is
     painted pixels and otherwise invisible to AT;
  7. the keyboard verse cursor reaches the gestures that used to be
     pointer-only (WCAG 2.1.1): arrows step verses and words against a real
     rendered chapter, Enter opens the study menu, and modifier
     combinations are passed through to the window's own shortcuts.

Usage:  python3 tools/verify-a11y.py

Exit 0 = asserted checks passed, 1 = a check failed, 2 = the environment is
unusable (no python3-sword, or Broadway wouldn't start). Prints a JSON report.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY = 7  # private XDG_RUNTIME_DIR per run, so a fixed number never collides


# ────────────────────────────────────────────────────────────────────────
# Orchestrator: scratch env + broadwayd + retry
# ────────────────────────────────────────────────────────────────────────

WAYLAND_NAME = 'scriptura-a11y'


def start_display(env: dict) -> tuple[subprocess.Popen | None, bool]:
    """Bring up a display for the driver.

    Returns (process, announcements_usable). Prefers a real headless mutter —
    the only place gtk_accessible_announce() can be exercised safely — and
    falls back to Broadway, where the announcement checks get skipped."""
    if shutil.which('mutter'):
        proc = subprocess.Popen(
            ['mutter', '--headless', f'--wayland-display={WAYLAND_NAME}',
             '--virtual-monitor', '1280x720'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        socket = Path(env['XDG_RUNTIME_DIR'], WAYLAND_NAME)
        deadline = time.monotonic() + 10.0
        while not socket.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.terminate()
                proc.wait()
                break
            time.sleep(0.05)
        else:
            env['GDK_BACKEND'] = 'wayland'
            env['WAYLAND_DISPLAY'] = WAYLAND_NAME
            return proc, True

    proc = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'], env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    socket = Path(env['XDG_RUNTIME_DIR'], f'broadway{DISPLAY + 1}.socket')
    deadline = time.monotonic() + 5.0
    while not socket.exists():
        if proc.poll() is not None or time.monotonic() > deadline:
            print('no display: neither mutter nor broadwayd started',
                  file=sys.stderr)
            proc.terminate()
            proc.wait()
            return None, False
        time.sleep(0.05)
    env['GDK_BACKEND'] = 'broadway'
    env['BROADWAY_DISPLAY'] = f':{DISPLAY}'
    return proc, False


def run_attempt(timeout: float) -> dict | None:
    with tempfile.TemporaryDirectory(prefix='scriptura-a11y-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        # The `test` a11y backend builds the same GtkATContext the AT-SPI
        # backend publishes, without needing a session a11y bus — so the
        # assertions work in a CI container. (Fedora's GTK 4.22 rejects
        # GTK_A11Y=atspi outright; `test` and `none` are the accepted names.)
        env['GTK_A11Y'] = 'test'

        display, can_announce = start_display(env)
        if display is None:
            return None
        env['SCRIPTURA_A11Y_CAN_ANNOUNCE'] = '1' if can_announce else '0'
        try:
            try:
                proc = subprocess.run(
                    [sys.executable, __file__, '--driver'],
                    env=env, cwd=REPO_ROOT, timeout=timeout,
                    stdout=subprocess.PIPE, text=True)
            except subprocess.TimeoutExpired:
                print(f'driver timed out after {timeout:.0f}s', file=sys.stderr)
                return None
            sys.stdout.write(proc.stdout)
            try:
                report = json.loads(proc.stdout)
            except json.JSONDecodeError:
                return None
            return report if isinstance(report, dict) else None
        finally:
            display.terminate()
            display.wait()


def orchestrate() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the app's accessible tree (roles, relations, "
                    'live-region announcements).')
    parser.add_argument('--retries', type=int, default=1,
                        help='reruns allowed on failure (Broadway flakiness)')
    parser.add_argument('--timeout', type=float, default=90,
                        help='per-attempt wall clock limit in seconds')
    args = parser.parse_args()

    import importlib.util
    if importlib.util.find_spec('Sword') is None:
        print('python3-sword is not installed', file=sys.stderr)
        return 2
    if shutil.which('gtk4-broadwayd') is None:
        print('gtk4-broadwayd not found (Fedora package gtk4)', file=sys.stderr)
        return 2

    for attempt in range(1 + args.retries):
        if attempt:
            print(f'retrying (attempt {attempt + 1})…', file=sys.stderr)
        report = run_attempt(args.timeout)
        if report is not None and report.get('all_ok'):
            return 0
    return 1


# ────────────────────────────────────────────────────────────────────────
# Driver (child process, inside the Broadway app)
# ────────────────────────────────────────────────────────────────────────

WAIT_CAP_MS = 10000
POLL_MS = 300


def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, GLib

    import a11y
    import main

    REPORT: dict = {'checks': [], 'skipped': [], 'measured': {}}
    S: dict = {}
    app = main.BibleApp()
    # Broadway segfaults inside gtk_accessible_announce (see module docstring);
    # only a real compositor can exercise the live-region path.
    can_announce = os.environ.get('SCRIPTURA_A11Y_CAN_ANNOUNCE') == '1'
    REPORT['announcements_exercised'] = can_announce

    def add(name, ok, **extra):
        REPORT['checks'].append({'name': name, 'ok': bool(ok), **extra})

    def skip(name, why):
        REPORT['skipped'].append({'name': name, 'why': why})

    def finish(tag):
        REPORT['exit_tag'] = tag
        REPORT['all_ok'] = (bool(REPORT['checks'])
                            and all(c['ok'] for c in REPORT['checks']))
        print(json.dumps(REPORT, indent=1))
        app.quit()
        return False

    # ── assertion helpers ────────────────────────────────────────────────

    def role_of(widget):
        return widget.get_accessible_role().value_nick

    def has_role(name, widget, role):
        ok = Gtk.test_accessible_has_role(widget, role)
        add(name, ok, want=role.value_nick, got=role_of(widget))
        return ok

    def has_label(name, widget):
        ok = Gtk.test_accessible_has_property(
            widget, Gtk.AccessibleProperty.LABEL)
        add(name, ok)
        return ok

    def has_relation(name, widget, relation):
        ok = Gtk.test_accessible_has_relation(widget, relation)
        add(name, ok, relation=relation.value_nick)
        return ok

    # ── the announcement recorder ────────────────────────────────────────
    # Announcements leave no trace on the widget tree, so the only way to
    # prove they fire is to watch the one funnel every caller goes through.
    spoken: list = []
    real_announce = a11y.announce

    def recording_announce(widget, message, urgent=False):
        if message:
            spoken.append(message)
        real_announce(widget, message, urgent=urgent)

    a11y.announce = recording_announce

    def check_window():
        win = S.get('win')
        R = Gtk.AccessibleRole
        Rel = Gtk.AccessibleRelation

        panes = [p for p in (getattr(win, 'pane1', None),
                             getattr(win, 'pane2', None)) if p is not None]
        add('panes_found', bool(panes), count=len(panes))
        if not panes:
            return finish('no-panes')

        pane = panes[0]

        # 1. landmarks + toolbars — the widgets that were `generic` before.
        for i, p in enumerate(panes, 1):
            # GROUP, not REGION: GTK4 emits no landmark roles — REGION
            # arrives at AT-SPI as `filler`. Verified against a live tree.
            has_role(f'pane{i}_is_group', p, R.GROUP)
            has_label(f'pane{i}_named', p)
        has_role('pane_toolbar_is_toolbar', pane._toolbar, R.TOOLBAR)
        has_label('pane_toolbar_named', pane._toolbar)

        # 2. the reading surface itself.
        has_role('reading_view_is_document', pane._view, R.DOCUMENT)
        has_label('reading_view_named', pane._view)

        # 3. the per-pane find bar. Building the revealer is what wires it,
        #    and the pane does that at construction.
        search = pane._search
        has_role('find_counter_is_status', search._status, R.STATUS)
        has_relation('find_entry_described_by_counter',
                     search._entry, Rel.DESCRIBED_BY)
        has_relation('find_prev_controls_view', search._prev_btn, Rel.CONTROLS)
        find_bar = search._status.get_parent()
        has_role('find_bar_is_toolbar', find_bar, R.TOOLBAR)
        has_label('find_bar_named', find_bar)

        # 4. the window search panel.
        panel = getattr(win, '_search_panel', None)
        if panel is not None:
            has_role('search_count_is_status', panel._count_label, R.STATUS)
            has_relation('search_entry_controls_results',
                         panel._entry, Rel.CONTROLS)
            has_label('search_results_named', panel._results_list)
        else:
            add('search_panel_found', False)

        # 5. status text reaches the live region. Drive the real helper the
        #    app uses everywhere rather than a stand-in.
        if can_announce:
            spoken.clear()
            a11y.status(search._status, 'Searching…')
            add('status_helper_announces', 'Searching…' in spoken,
                spoken=list(spoken))

            spoken.clear()
            search._results = [('Genesis', 1, 1, 'x'), ('Genesis', 1, 2, 'y')]
            search._idx = -1
            stepped = search.step(prev=False)
            add('find_step_announces_position',
                stepped and any(' of ' in m for m in spoken),
                spoken=list(spoken))
        else:
            skip('status_helper_announces', 'no compositor (Broadway)')
            skip('find_step_announces_position', 'no compositor (Broadway)')

        # 6. a verse announcement carries its annotation state (A3). Written
        #    against the pane's own store so the check is real, not a mock.
        spoken.clear()
        state = None
        try:
            import annotations
            annotations.save_highlight(pane._module, pane._book,
                                       pane._chapter, 1, '#ffff00')
            annotations.save_note(pane._module, pane._book,
                                  pane._chapter, 1, 'a note')
            state = pane._verse_state_text(1)
            if can_announce:
                pane._announce_verse_state(1)
        except Exception as exc:  # pragma: no cover - reported, not raised
            add('verse_state_built', False, error=repr(exc))
        if state is not None:
            add('verse_state_names_reference',
                f'{pane._chapter}:1' in state, state=state)
            add('verse_state_names_highlight',
                'highlight' in state.lower(), state=state)
            add('verse_state_names_note', 'note' in state.lower(), state=state)
            if can_announce:
                add('verse_state_announced', bool(spoken), spoken=list(spoken))
                # And it must land on the view as a description too, so the
                # state survives the announcement passing.
                add('verse_state_on_view_description',
                    Gtk.test_accessible_has_property(
                        pane._view, Gtk.AccessibleProperty.DESCRIPTION))
            else:
                skip('verse_state_announced', 'no compositor (Broadway)')
                skip('verse_state_on_view_description',
                     'no compositor (Broadway)')

        # 7. the keyboard verse cursor, against a real rendered chapter.
        import gi as _gi
        _gi.require_version('Gdk', '4.0')
        from gi.repository import Gdk

        cur = getattr(pane, '_cursor', None)
        if cur is None:
            add('verse_cursor_present', False)
        else:
            def press(keyval, state=0):
                return cur.on_key(None, keyval, 0, state)

            verses = cur._verses()
            add('cursor_sees_rendered_verses', len(verses) > 1,
                count=len(verses))

            cur.clear()
            placed = press(Gdk.KEY_Down)
            first = cur.verse
            add('cursor_places_on_first_press', placed and first is not None,
                verse=first)
            press(Gdk.KEY_Down)
            add('cursor_steps_forward', cur.verse != first,
                was=first, now=cur.verse)
            press(Gdk.KEY_Up)
            add('cursor_steps_back', cur.verse == first, now=cur.verse)

            # Modifiers belong to the window's actions, never to the cursor.
            add('cursor_releases_alt_arrow',
                press(Gdk.KEY_Down, Gdk.ModifierType.ALT_MASK) is False)
            add('cursor_releases_ctrl_f',
                press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK) is False)

            # Word tier over real rendered text.
            spans = cur._word_spans()
            add('cursor_finds_words_in_verse', len(spans) > 1,
                count=len(spans))
            # The word tier must not walk out of its verse: a span past the
            # verse end would let Enter look up a word from the next one.
            vr = pane._verse_ranges(cur.verse)
            if vr and spans:
                lo, hi = vr[1].get_offset(), vr[2].get_offset()
                stray = [sp for sp in spans if sp[0] < lo or sp[1] > hi]
                add('cursor_words_stay_inside_the_verse', not stray,
                    verse_range=[lo, hi], stray=stray[:3],
                    first=spans[0], last=spans[-1])
            else:
                add('cursor_words_stay_inside_the_verse', False)
            entered = press(Gdk.KEY_Right)
            add('cursor_enters_word_tier', entered and cur.in_word_tier)
            first_word = cur._word
            press(Gdk.KEY_Right)
            add('cursor_steps_words', cur._word != first_word)
            add('cursor_escape_leaves_word_tier',
                press(Gdk.KEY_Escape) and not cur.in_word_tier)

            if can_announce:
                spoken.clear()
                press(Gdk.KEY_Down)
                add('cursor_move_announces_verse', bool(spoken),
                    spoken=list(spoken))
                spoken.clear()
                press(Gdk.KEY_Right)
                add('cursor_word_announces_action',
                    any('Enter' in m for m in spoken), spoken=list(spoken))
                press(Gdk.KEY_Escape)
            else:
                skip('cursor_move_announces_verse', 'no compositor (Broadway)')
                skip('cursor_word_announces_action',
                     'no compositor (Broadway)')

            # Enter on a verse must reach the study menu — the action that
            # was right-click-only.
            def view_children():
                out, ch = [], pane._view.get_first_child()
                while ch is not None:
                    out.append(ch)
                    ch = ch.get_next_sibling()
                return out

            before = view_children()
            opened = press(Gdk.KEY_Return)
            new = [w for w in view_children() if w not in before]
            add('cursor_enter_opens_study_menu', opened and bool(new),
                added=[type(w).__name__ for w in new])
            for w in new:
                if isinstance(w, Gtk.Popover):
                    w.popdown()

        # ── measured, never gating ───────────────────────────────────────
        unnamed = []

        def walk(w, depth=0):
            if depth > 14 or w is None:
                return
            if isinstance(w, (Gtk.Button, Gtk.ToggleButton, Gtk.MenuButton)):
                labelled = Gtk.test_accessible_has_property(
                    w, Gtk.AccessibleProperty.LABEL)
                icon_only = (isinstance(w, Gtk.Button)
                             and isinstance(w.get_child(), Gtk.Image))
                if icon_only and not labelled:
                    unnamed.append(w.get_buildable_id() or repr(w))
            child = w.get_first_child()
            while child is not None:
                walk(child, depth + 1)
                child = child.get_next_sibling()

        try:
            walk(win)
        except Exception:
            pass
        REPORT['measured']['icon_only_controls_without_a_name'] = len(unnamed)
        REPORT['measured']['pane_roles'] = {
            'pane': role_of(pane), 'view': role_of(pane._view),
            'toolbar': role_of(pane._toolbar),
        }
        return finish('done')

    # ── startup polling ──────────────────────────────────────────────────
    S['waited'] = 0

    def poll():
        wins = app.get_windows()
        if wins:
            S['win'] = wins[0]
            # One more turn of the loop so the panes finish building.
            GLib.timeout_add(POLL_MS, check_window)
            return False
        S['waited'] += POLL_MS
        if S['waited'] > WAIT_CAP_MS:
            add('window_appeared', False)
            finish('no-window')
            return False
        return True

    def kickoff():
        GLib.timeout_add(POLL_MS, poll)
        return False

    GLib.idle_add(kickoff)
    # Safety net: never let a frame-clock or network stall hold the run open.
    GLib.timeout_add_seconds(75, lambda: finish('safety-timeout'))
    app.run([])
    return 0


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(run_driver())
    sys.exit(orchestrate())
