#!/usr/bin/env python3
"""Welcome-flow harness — installs a bundle for real and opens the window.

The onboarding work of 2026-08-13 gave the welcome window a job it never
had: each bundle names the pair of modules the reading window should open
on, written to settings once the install lands. That has unit tests. The
path that calls it had never run — no bundle had ever been downloaded and
installed end to end, so nothing proved the recorded pair survives a real
install and reaches the panes.

This runs it: a scratch HOME and scratch XDG dirs, the real welcome window
under Broadway, a real click on a real card, real downloads from CrossWire
and GitHub, and then the real BibleWindow the handoff builds.

It asserts:

  1. the welcome window is what a fresh profile opens on;
  2. every module in the bundle arrives — SWORD modules, the commentary
     pack, the open-data sources — each asked of the bridge that owns it;
  3. settings.json ON DISK records the opening pair the bundle names;
  4. the reading window opens on that pair, with two different texts in the
     split (the defect that started this: it showed one Bible twice);
  5. nothing covers the panes at launch, so the one first-run hint is spent
     on the reading surface.

Nothing is stubbed and no state is shared with the real profile: HOME is a
temporary directory, so ~/.sword is created inside it. The one departure
from a true first run is BIBLE_READER_FORCE_WELCOME=1, needed on any machine
carrying distro SWORD modules in /usr/share/sword (this one has two) —
without it the app correctly skips welcome and there is nothing to drive.
That flag only chooses the window; it changes no part of the install path.

Usage:  python3 tools/verify-welcome-install.py [--bundle reading|study|full]

`reading` is one small Bible — the fast pass, and the only bundle that
exercises the single-pane branch. `study` is the recommended one and the
only pass that covers all four install kinds; it downloads ~100 MB.

Exit 0 = all checks passed, 1 = a check failed, 2 = the environment is
unusable. Prints a JSON report.
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
# Orchestrator: scratch HOME + scratch XDG + broadwayd
# ────────────────────────────────────────────────────────────────────────

def run_attempt(bundle: str, timeout: float) -> dict | None:
    # Deliberately not the scratchpad dir: XDG_RUNTIME_DIR holds the Broadway
    # socket and a long prefix blows the 108-byte AF_UNIX path limit.
    with tempfile.TemporaryDirectory(prefix='scriptura-welcome-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        # ~/.sword is HOME-based and hard-coded in sword_bridge, so isolating
        # the install means isolating HOME. The real library is untouched.
        home = Path(scratch, 'home')
        home.mkdir(mode=0o700)
        env['HOME'] = str(home)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'
        env['BIBLE_READER_FORCE_WELCOME'] = '1'
        env['SCRIPTURA_WELCOME_BUNDLE'] = bundle
        # The driver gives up a little before the orchestrator does, so a slow
        # download reports what it managed rather than dying without a word.
        env['SCRIPTURA_INSTALL_CAP_S'] = str(max(30.0, timeout - 45))

        broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'],
                                     env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            socket = Path(env['XDG_RUNTIME_DIR'],
                          f'broadway{DISPLAY + 1}.socket')
            deadline = time.monotonic() + 5.0
            while not socket.exists():
                if broadwayd.poll() is not None or time.monotonic() > deadline:
                    print('broadwayd failed to start', file=sys.stderr)
                    return None
                time.sleep(0.05)
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
            broadwayd.terminate()
            broadwayd.wait()


def orchestrate() -> int:
    parser = argparse.ArgumentParser(
        description='Install a welcome bundle for real and open the window.')
    # Read the ids from welcome.py rather than listing them: a bundle added
    # without touching this file would otherwise be the one bundle nobody
    # could verify, which is exactly when verification matters.
    sys.path.insert(0, str(REPO_ROOT))
    from welcome import _BUNDLES
    parser.add_argument('--bundle', default='reading',
                        choices=tuple(b['id'] for b in _BUNDLES),
                        help='which bundle card to click (default: reading)')
    parser.add_argument('--timeout', type=float, default=900,
                        help='wall clock limit in seconds (default: 900)')
    args = parser.parse_args()

    import importlib.util
    if importlib.util.find_spec('Sword') is None:
        print('python3-sword is not installed', file=sys.stderr)
        return 2
    if shutil.which('gtk4-broadwayd') is None:
        print('gtk4-broadwayd not found (Fedora package gtk4)', file=sys.stderr)
        return 2

    report = run_attempt(args.bundle, args.timeout)
    if report is None:
        return 1
    return 0 if report.get('all_ok') else 1


# ────────────────────────────────────────────────────────────────────────
# Driver (child process, inside the Broadway app)
# ────────────────────────────────────────────────────────────────────────

POLL_MS = 1000
SETTLE_MS = 1500


def _walk(widget):
    """Every descendant of `widget`, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _card_for(win, title, Gtk):
    """The real card button for a bundle, found by its title label.

    Clicking the button the user clicks — rather than calling the handler —
    keeps the chooser's own wiring inside the test.
    """
    for w in _walk(win):
        if isinstance(w, Gtk.Button) and w.has_css_class('card'):
            for inner in _walk(w):
                if isinstance(inner, Gtk.Label) and inner.get_text() == title:
                    return w
    return None


def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib, Gtk

    import main
    from welcome import WelcomeWindow, _BUNDLES

    bundle_id = os.environ.get('SCRIPTURA_WELCOME_BUNDLE', 'reading')
    bundle = next(b for b in _BUNDLES if b['id'] == bundle_id)
    cap_s = float(os.environ.get('SCRIPTURA_INSTALL_CAP_S', '855'))
    want1, want2 = bundle['opens']

    REPORT: dict = {'bundle': bundle_id, 'checks': [], 'measured': {},
                    'progress': []}
    S: dict = {'started': time.monotonic()}
    app = main.BibleApp()

    def add(name, ok, **extra):
        REPORT['checks'].append({'name': name, 'ok': bool(ok), **extra})

    def finish(tag):
        REPORT['exit_tag'] = tag
        REPORT['elapsed_s'] = round(time.monotonic() - S['started'], 1)
        REPORT['all_ok'] = (bool(REPORT['checks'])
                            and all(c['ok'] for c in REPORT['checks']))
        print(json.dumps(REPORT, indent=1))
        app.quit()
        return GLib.SOURCE_REMOVE

    def fail(tag, exc):
        import traceback
        REPORT['error'] = f'{tag}: {exc}'
        REPORT['traceback'] = traceback.format_exc()
        return finish(tag)

    # ── 1. the fresh profile lands on welcome ─────────────────────────────
    def kickoff():
        wins = app.get_windows()
        if not wins:
            return GLib.SOURCE_CONTINUE
        win = wins[0]
        welcome = isinstance(win, WelcomeWindow)
        add('a fresh profile opens on the welcome window', welcome,
            window=type(win).__name__)
        if not welcome:
            return finish('no-welcome')
        S['welcome'] = win
        GLib.idle_add(click_card)
        return GLib.SOURCE_REMOVE

    # ── 2. click the card the user would click ────────────────────────────
    def click_card():
        try:
            card = _card_for(S['welcome'], bundle['title'], Gtk)
            if card is None:
                add(f'the {bundle_id} card exists', False)
                return finish('no-card')
            card.emit('clicked')
            GLib.timeout_add(POLL_MS, wait_install)
        except Exception as e:
            return fail('click', e)
        return GLib.SOURCE_REMOVE

    def note_progress():
        """Keep the status line's distinct values — the install's own trace."""
        try:
            text = S['welcome']._status.get_text()
        except Exception:
            return
        # Byte-count detail changes every tick; keep the step, not the bytes.
        step = text.split('…')[0]
        if step and (not REPORT['progress'] or REPORT['progress'][-1] != step):
            REPORT['progress'].append(step)

    def wait_install():
        try:
            note_progress()
            reading = next((w for w in app.get_windows()
                            if not isinstance(w, WelcomeWindow)), None)
            if reading is not None:
                S['reading'] = reading
                GLib.timeout_add(SETTLE_MS, inspect)
                return GLib.SOURCE_REMOVE
            # The install failed outright: welcome offers its way back.
            if S['welcome']._back_btn.get_visible():
                add('the install completes and hands off', False,
                    status=S['welcome']._status.get_text())
                return finish('install-failed')
            if time.monotonic() - S['started'] > cap_s:
                add('the install completes and hands off', False,
                    status=S['welcome']._status.get_text(), timed_out=True)
                return finish('cap')
            return GLib.SOURCE_CONTINUE
        except Exception as e:
            return fail('wait', e)

    # ── 3-5. what arrived, what was recorded, what opened ─────────────────
    def inspect():
        try:
            import catena_bridge
            import open_data
            import paths
            import sword_bridge

            add('the install completes and hands off', True)

            # What arrived, asked of the bridge that owns each kind.
            want_sword = [i for k, i, _l in bundle['items'] if k == 'sword']
            have_sword = set(sword_bridge.module_names())
            missing = [m for m in want_sword if m not in have_sword]
            add('every SWORD module in the bundle installed', not missing,
                wanted=len(want_sword), missing=missing)

            want_ebible = [i for k, i, _l in bundle['items'] if k == 'ebible']
            if want_ebible:
                import ebible_bridge
                have_ebible = {r[0] for r in
                               ebible_bridge.installed_translations()}
                missing_e = [t for t in want_ebible if t not in have_ebible]
                add('every eBible translation in the bundle installed',
                    not missing_e,
                    wanted=len(want_ebible), missing=missing_e)

            if any(k == 'catena' for k, _i, _l in bundle['items']):
                names = catena_bridge.module_names()
                add('the commentary pack installed', bool(names), names=names)

            probes = {'dodson': open_data.has_dodson,
                      'cross_references': open_data.has_cross_refs,
                      'topics': open_data.has_topics}
            for _k, ident, label in [i for i in bundle['items']
                                     if i[0] == 'opendata']:
                probe = probes.get(ident)
                if probe is not None:
                    add(f'open data installed: {label}', probe())

            # The recorded pair, read back off disk — persistence is the point.
            saved = json.loads(
                (Path(paths.config_dir()) / 'settings.json').read_text())
            REPORT['measured']['settings'] = {
                k: saved.get(k) for k in
                ('pane1_module', 'pane2_module', 'split_pane_mode')}
            recorded = (saved.get('pane1_module') == want1
                        and saved.get('pane2_module') == want2
                        and saved.get('split_pane_mode') is (want2 is not None))
            add('settings.json records the opening pair', recorded,
                expected={'pane1_module': want1, 'pane2_module': want2,
                          'split_pane_mode': want2 is not None})

            # The window the handoff built.
            win = S['reading']
            p1 = win.pane1._module
            p2 = win.pane2._module
            split = win.pane2.get_visible()
            REPORT['measured']['window'] = {
                'type': type(win).__name__, 'pane1': p1, 'pane2': p2,
                'split': split, 'identical': p1 == p2 and split,
                'today': win._today_view is not None}
            if want2 is None:
                opened = p1 == want1 and not split
            else:
                opened = p1 == want1 and p2 == want2 and split and p1 != p2
            add('the reading window opens on that pair', opened,
                pane1=p1, pane2=p2, split=split)
            add('the split never shows one text twice',
                not (split and p1 == p2))
            add('nothing covers the panes at launch',
                win._today_view is None)

            import settings
            REPORT['measured']['hints_seen'] = settings.get('hints_seen') or []
            return finish('done')
        except Exception as e:
            return fail('inspect', e)

    def safety():
        REPORT['error'] = 'safety timeout'
        return finish('safety')

    GLib.timeout_add(800, kickoff)
    GLib.timeout_add_seconds(int(cap_s) + 30, safety)
    app.run([])
    return 0 if REPORT.get('all_ok') else 1


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(run_driver())
    sys.exit(orchestrate())
