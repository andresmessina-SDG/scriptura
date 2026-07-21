#!/usr/bin/env python3
"""Today-page + spoken-audio harness — drives the real app headless.

Companion to tools/verify-scroll-stability.py, for the surface that one
skips: the Today landing page and its three spoken-reading players. The
audio arc was built without this — its visual/behaviour checks leaned on
stub objects and a human's eye because an ad-hoc real-app driver "hung".
It doesn't hang; it needs the same guards the scroll matrix already has,
which are baked in here:

  * a private XDG_RUNTIME_DIR per run, so a fixed Broadway display number
    can never collide with a stale server (a collision looks like a hang
    on connect);
  * a hard per-attempt timeout in the orchestrator and a safety force-quit
    inside the driver, so nothing can wait forever on a frame-clock or
    network condition Broadway never delivers to an unbrowsed window;
  * capped polling for every awaited state, never an open `while`.

What it asserts (exit 1 if any fail):

  1. the Today page builds and allocates a non-zero size;
  2. the Daily Strength "Listen" control is OFFERED from a seeded, entirely
     offline episode — proving the audio-index → control wiring without
     touching the network;
  3. pressing play through the app's own handler reaches a playing state,
     the progress advances, and stopping silences it — the real GStreamer
     pipeline, in-app, through the GLib loop.

Check 3 needs an MP3 encoder (lamemp3enc, Fedora gstreamer1-plugins-*) to
synthesise a test tone, because the app's player is MP3-only by design; if
none is present the playback check is reported "skipped", not failed.

It also MEASURES the listen-disc and epigraph geometry and reports the numbers
(never gating the exit) — raw material for the still-open "disc overlaps the
text on a narrow pane" fix.

Usage:  python3 tools/verify-today.py

Exit 0 = asserted checks passed, 1 = a check failed, 2 = the environment is
unusable (no python3-sword, or Broadway wouldn't start). Prints a JSON report.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY = 6  # private XDG_RUNTIME_DIR per run, so a fixed number never collides
EPISODE_URL = 'https://example.invalid/today.mp3'  # never fetched; seeded local


# ────────────────────────────────────────────────────────────────────────
# Orchestrator: scratch env + seeded offline episode + broadwayd + retry
# ────────────────────────────────────────────────────────────────────────

def make_test_mp3(dest: Path) -> bool:
    """Synthesise a short MP3 tone with GStreamer. False if no encoder."""
    if shutil.which('gst-launch-1.0') is None:
        return False
    try:
        subprocess.run(
            ['gst-launch-1.0', '-q', 'audiotestsrc', 'num-buffers=90', '!',
             'audioconvert', '!', 'lamemp3enc', '!', 'filesink',
             f'location={dest}'],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return dest.exists() and dest.stat().st_size > 0


def run_attempt(timeout: float) -> dict | None:
    with tempfile.TemporaryDirectory(prefix='scriptura-today-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'

        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / 'settings.json').write_text(json.dumps({'open_to_today': True}))

        # Seed today's Daily Strength episode entirely offline: the index entry
        # the sync reads, plus the already-"downloaded" file the player opens.
        cache = Path(env['XDG_CACHE_HOME'], 'bible-reader')
        (cache / 'devotional_audio').mkdir(parents=True, exist_ok=True)
        today = datetime.date.today()
        (cache / 'daily_strength_audio_index.json').write_text(json.dumps({
            'feed': 'seeded', 'episodes': {
                f'{today.month:02d}-{today.day:02d}':
                    [EPISODE_URL, 'Test Reading']}}))
        have_audio = make_test_mp3(cache / 'devotional_audio' / 'today.mp3')
        env['SCRIPTURA_TODAY_HAVE_AUDIO'] = '1' if have_audio else '0'

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
        description='Verify the Today page and its spoken-audio players.')
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

WAIT_CAP_MS = 8000
POLL_MS = 300


def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib

    import main

    have_audio = os.environ.get('SCRIPTURA_TODAY_HAVE_AUDIO') == '1'
    REPORT: dict = {'checks': [], 'geometry': {}}
    S: dict = {'phase': 'startup'}
    app = main.BibleApp()

    def add(name, ok, **extra):
        REPORT['checks'].append({'name': name, 'ok': bool(ok), **extra})

    def finish(tag):
        REPORT['exit_tag'] = tag
        REPORT['all_ok'] = (bool(REPORT['checks'])
                            and all(c['ok'] for c in REPORT['checks']))
        try:
            win = S.get('win')
            if win is not None:
                win._stop_today_listen()
        except Exception:
            pass
        print(json.dumps(REPORT, indent=1))
        app.quit()
        return GLib.SOURCE_REMOVE

    def fail(tag, exc):
        import traceback
        REPORT['error'] = f'{tag}: {exc}'
        REPORT['traceback'] = traceback.format_exc()
        return finish(tag)

    # ── wait for the window and the Today view ────────────────────────────
    def kickoff():
        win = app.get_active_window()
        if win is None:
            return GLib.SOURCE_CONTINUE
        S['win'] = win
        win.set_default_size(1200, 800)
        S['tries'] = 0
        GLib.timeout_add(POLL_MS, wait_ready)
        return GLib.SOURCE_REMOVE

    def wait_ready():
        try:
            win = S['win']
            tv = getattr(win, '_today_view', None)
            allocated = tv is not None and tv.get_width() > 0
            listen = tv is not None and tv._listen_card.get_visible()
            S['tries'] += 1
            # Ready when the page is laid out and the listen control has been
            # offered — or give up after the cap and judge what we have.
            if (allocated and listen) or S['tries'] * POLL_MS >= WAIT_CAP_MS:
                add('Today page builds and allocates',
                    tv is not None and tv.get_width() > 0
                    and tv.get_height() > 0,
                    width=(tv.get_width() if tv else None),
                    height=(tv.get_height() if tv else None))
                add('Daily Strength listen offered (offline episode)',
                    listen, today_listen_set=bool(
                        getattr(win, '_today_listen', None)))
                measure_geometry(tv)
                start_playback()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        except Exception as e:
            fail('wait_ready', e)
            return GLib.SOURCE_REMOVE

    # ── geometry snapshot (measured, never gated) ─────────────────────────
    def measure_geometry(tv):
        if tv is None:
            return
        try:
            card = tv._listen_card
            REPORT['geometry']['snapshot'] = {
                'view_w': tv.get_width(),
                'listen_card_w': card.get_width(),
                'listen_card_visible': card.get_visible(),
                'epigraph_visible': tv._epigraph_box.get_visible(),
            }
        except Exception as e:
            REPORT['geometry']['error'] = str(e)

    # ── playback: press play, watch it reach playing + advance, stop ──────
    def start_playback():
        if not have_audio:
            add('playback (press play → plays → stops)', True,
                skipped='no MP3 encoder (lamemp3enc) available')
            GLib.timeout_add(200, lambda: finish('done-no-audio'))
            return
        try:
            S['win']._on_today_listen()
        except Exception as e:
            fail('press-play', e)
            return
        S['polls'] = 0
        S['saw_playing'] = False
        S['progress_seen'] = []
        GLib.timeout_add(400, poll_play)

    def poll_play():
        try:
            win = S['win']
            player = getattr(win, '_today_player', None)
            playing = player is not None and player.playing
            prog = player.progress() if player is not None else None
            S['saw_playing'] = S['saw_playing'] or playing
            if prog is not None:
                S['progress_seen'].append(round(prog, 3))
            S['polls'] += 1
            # Enough once we've seen it playing AND progress has moved past 0,
            # or after a generous cap.
            advanced = any(p > 0.0 for p in S['progress_seen'])
            if (S['saw_playing'] and advanced) or S['polls'] >= 12:
                add('playback reaches playing state', S['saw_playing'],
                    progress_samples=S['progress_seen'])
                add('playback progress advances', advanced,
                    max_progress=max(S['progress_seen'] or [0.0]))
                win._stop_today_listen()
                GLib.timeout_add(300, verify_stopped)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        except Exception as e:
            fail('poll_play', e)
            return GLib.SOURCE_REMOVE

    def verify_stopped():
        win = S['win']
        player = getattr(win, '_today_player', None)
        add('stop silences playback',
            player is None or not player.playing)
        return finish('done')

    # Safety net: nothing may wait forever.
    GLib.timeout_add(60000, lambda: finish('SAFETY_TIMEOUT'))
    GLib.timeout_add(800, kickoff)
    app.run([])
    return 0 if REPORT.get('all_ok') else 1


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(run_driver())
    sys.exit(orchestrate())
