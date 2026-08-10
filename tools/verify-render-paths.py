#!/usr/bin/env python3
"""Render-path classifier — which toggles change the TEXT, and which only its
attributes.

Fourth harness, and the one item 22 (STRUCTURAL Step 5, T5) is built against.
The scroll matrix asserts that text never moves, verify-today.py asserts the
Today page behaves, verify-window-tree.py asserts construction shape. This one
asserts what the reading buffer is made of.

Why it exists. Every content toggle currently rebuilds the whole chapter
(`set_text('')` → rebuild markup → re-insert → restore anchor), and the entire
scroll-anchor apparatus exists to recover the reading position afterwards.
Making a toggle incremental is only safe where the text is genuinely unchanged
and only its attributes differ — so that question has to be measured, not
assumed. It was assumed once, in STRUCTURAL_ANALYSIS's original T5, and the
guess was half wrong: footnote markers ARE text.

What it does. For each trigger, it flips the setting, waits for the render to
land, and compares the buffer's text against the state before. It reports
`_display` call counts and durations, and asserts each trigger's expected
class.

    identical text  → attribute-only → an incremental-update CANDIDATE
    changed text    → structural     → must keep re-rendering

Definition of done for item 22: the three candidates below reach
`display_calls: 0` while staying `text_identical`. Nothing here asserts that
yet, because today they are all 1 — this tool is what will show the change.

Default reference is BSB Genesis 2, chosen because it carries section
headings, footnotes AND the divine name, so every trigger has something to act
on. A chapter missing one of those will legitimately report a mismatch: BSB
Psalm 119 is marked with no sections, so the headings toggle reads "identical"
there and means nothing.

Usage:  python3 tools/verify-render-paths.py [--module BSB] [--ref "Genesis 2"]

Exit 0 = every trigger matched its expected class, 1 = a mismatch or the
chapter never rendered, 2 = the environment is unusable (no module, no
broadwayd).
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
DISPLAY = 8   # private XDG_RUNTIME_DIR per run, so a fixed number never collides
POLL_MS = 150
SETTLE_POLLS = 4          # text unchanged this many polls = the render landed
CAP_MS = 25000
DRIVER_TIMEOUT = 180.0

#: (label, pane setter, pane attribute, expected `text_identical`).
#: True  = attribute-only, an incremental candidate.
#: False = structural; the text itself changes, leave it re-rendering.
#: Triggers that must never call `_display`, whatever happens to the text.
#: A rebuild here is a regression: it empties and refills the buffer, and the
#: reading position then has to be held through GTK's re-estimation of the
#: document height — the flicker the scroll hold exists to fight.
NO_REBUILD = ('theme flip', 'oldstyle numerals', 'coloured dropcap',
              'poetry flush', 'footnotes')

TRIGGERS = [
    ('theme flip',        None,                     None,                True),
    ('oldstyle numerals', 'set_oldstyle_numerals',  '_oldstyle_nums',    True),
    ('coloured dropcap',  'set_colored_dropcap',    '_colored_dropcap',  True),
    ('poetry flush',      'set_poetry_flush',       '_poetry_flush',     True),
    ('section headings',  'set_show_headings',      '_show_headings',    False),
    # Footnotes change the visible text — the markers appear — but they are
    # applied by flipping one tag's `invisible`, not by re-rendering. So the
    # text is expected to differ while _display must stay at 0; see NO_REBUILD.
    ('footnotes',         'set_show_footnotes',     '_show_footnotes',   False),
    ('divine smallcaps',  'set_divine_smallcaps',   '_smallcaps_divine', False),
]


# ── Driver: runs inside the app's process ───────────────────────────────────

def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, GLib

    import main

    out = Path(os.environ['PROBE_OUT'])
    book = os.environ['PROBE_BOOK']
    chapter = int(os.environ['PROBE_CHAPTER'])
    app = main.BibleApp()
    R: dict = {'module': os.environ['PROBE_MODULE'],
               'ref': f'{book} {chapter}', 'triggers': []}
    S: dict = {'tries': 0, 'i': 0, 'calls': []}

    def buftext(pane):
        b = pane._buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def first_diff(a, b, span=34):
        """WHAT differs, not merely that something does — a length-preserving
        change (smallcaps case-folds LORD→Lord) is invisible in a char count."""
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return {'at': i, 'before': a[max(0, i - 8):i + span],
                        'after': b[max(0, i - 8):i + span]}
        return None if a == b else {'at': min(len(a), len(b)), 'tail': True}

    def finish(tag):
        R['exit_tag'] = tag
        out.write_text(json.dumps(R, indent=1))
        app.quit()
        return GLib.SOURCE_REMOVE

    def settle(pane, then):
        """Poll until the buffer text stops changing. Capped, never open."""
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

    def record(label, setter, before_text, before_tags, text, pane, expect):
        got = (text == before_text)
        R['triggers'].append({
            'trigger': label,
            'via': setter or '_on_theme_changed',
            'text_identical': got,
            'expected_identical': expect,
            'ok': got == expect,
            # By whether it REBUILT, not by whether the text moved: footnotes
            # change the text and still do not re-render.
            'class': ('attribute-only' if not S['calls']
                      else 'structural'),
            'char_delta': len(text) - len(before_text),
            'display_calls': len(S['calls']),
            'display_ms': list(S['calls']),
            'tags_before': before_tags,
            'tags_after': pane._buffer.get_tag_table().get_size(),
            'first_diff': first_diff(before_text, text),
        })

    def next_trigger(_ignored=None):
        pane = S['pane']
        if S['i'] >= len(TRIGGERS):
            R['all_ok'] = all(t['ok'] for t in R['triggers'])
            return finish('done')
        label, setter, attr, expect = TRIGGERS[S['i']]
        S['i'] += 1
        S['calls'] = []
        before_text = buftext(pane)
        before_tags = pane._buffer.get_tag_table().get_size()

        if setter is None:                       # the theme flip
            sm = Adw.StyleManager.get_default()
            was = sm.get_color_scheme()
            sm.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT if sm.get_dark()
                                else Adw.ColorScheme.FORCE_DARK)

            def after_theme(text):
                record(label, setter, before_text, before_tags, text, pane,
                       expect)
                sm.set_color_scheme(was)
                settle(pane, next_trigger)
            return settle(pane, after_theme)

        cur = bool(getattr(pane, attr))
        getattr(pane, setter)(not cur)

        def after(text):
            record(label, setter, before_text, before_tags, text, pane, expect)
            getattr(pane, setter)(cur)           # put it back
            settle(pane, next_trigger)
        settle(pane, after)

    def start_measuring():
        pane = S['pane']
        orig = pane._display

        def timed(*a, **kw):
            t0 = time.perf_counter()
            r = orig(*a, **kw)
            S['calls'].append(round((time.perf_counter() - t0) * 1000, 1))
            return r
        pane._display = timed
        R['baseline_chars'] = len(buftext(pane))
        R['baseline_tags'] = pane._buffer.get_tag_table().get_size()
        next_trigger()

    def wait_arrived():
        S['tries'] += 1
        pane = S['win'].pane1
        # Gate on the chapter ASKED FOR, never on "text is present": the pane
        # renders its startup chapter first, and a probe that begins there
        # measures a different document and reports confident nonsense.
        if (getattr(pane, '_book', None) == book
                and int(getattr(pane, '_chapter', -1)) == chapter
                and buftext(pane).strip()):
            S['pane'] = pane
            start_measuring()
            return GLib.SOURCE_REMOVE
        if S['tries'] * POLL_MS >= CAP_MS:
            R['error'] = (f'never arrived at {book} {chapter}; pane shows '
                          f'{getattr(pane, "_book", None)} '
                          f'{getattr(pane, "_chapter", None)}')
            return finish('no-arrival')
        return GLib.SOURCE_CONTINUE

    def kickoff():
        win = app.get_active_window()
        if win is None:
            return GLib.SOURCE_CONTINUE
        S['win'] = win
        win.set_default_size(1200, 900)

        # Let the app finish its OWN startup navigation before asking for a
        # chapter, or the request is silently undone and the pane lands back
        # on its startup reference.
        def then_navigate(_settled):
            # NOT load_reference: it returns early while a pane's sync button
            # is active ("Following", the default), recording the window's
            # location without moving. force_navigate moves it regardless.
            win.pane1.force_navigate(book, chapter, 1)
            GLib.timeout_add(POLL_MS, wait_arrived)
        settle(win.pane1, then_navigate)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(POLL_MS, kickoff)
    GLib.timeout_add(int(DRIVER_TIMEOUT * 1000) // 2,
                     lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])
    return 0


# ── Orchestrator ────────────────────────────────────────────────────────────

def orchestrate() -> int:
    parser = argparse.ArgumentParser(
        description='Classify each render trigger as attribute-only or '
                    'structural.')
    parser.add_argument('--module', default='BSB')
    parser.add_argument('--ref', default='Genesis 2',
                        help='book and chapter, e.g. "Genesis 2"')
    parser.add_argument('--json', metavar='FILE',
                        help='also write the full report here')
    args = parser.parse_args()

    import shutil
    if shutil.which('gtk4-broadwayd') is None:
        print('gtk4-broadwayd not found (Fedora package gtk4)', file=sys.stderr)
        return 2
    book, _, chapter = args.ref.rpartition(' ')
    if not book or not chapter.isdigit():
        print(f'--ref must be "Book Chapter", got {args.ref!r}', file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix='scriptura-render-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'
        # Offline: nothing here needs the network, and a feed fetch landing in
        # one run and not the next is noise. SWORD modules live in ~/.sword,
        # outside XDG, so they still resolve under the scratch dirs — which is
        # what keeps the user's real settings.json untouched.
        for var in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
            env[var] = 'http://127.0.0.1:1'
        report = Path(scratch, 'report.json')
        env.update(PROBE_OUT=str(report), PROBE_MODULE=args.module,
                   PROBE_BOOK=book, PROBE_CHAPTER=chapter)

        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        # Every trigger starts ON, so each flip turns something OFF and has a
        # visible effect to measure.
        (cfg / 'settings.json').write_text(json.dumps({
            'open_to_today': False, 'split_pane_mode': False,
            'pane1_module': args.module, 'show_headings': True,
            'show_footnotes': True, 'smallcaps_divine': True,
            'oldstyle_numerals': True, 'colored_dropcap': True,
            'poetry_flush': False,
        }))

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
        finally:
            broadwayd.terminate()
            broadwayd.wait()

    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=1))
    return present(data)


def present(data: dict) -> int:
    if data.get('error'):
        print(data['error'], file=sys.stderr)
        return 1
    print(f"{data['module']} {data['ref']} — {data['baseline_chars']} chars, "
          f"{data['baseline_tags']} tags\n")
    print(f"{'trigger':<18} {'class':<15} {'_display':>9}  {'ms':>7}  result")
    for t in data['triggers']:
        ms = ', '.join(str(x) for x in t['display_ms']) or '—'
        print(f"{t['trigger']:<18} {t['class']:<15} "
              f"{t['display_calls']:>9}  {ms:>7}  "
              f"{'ok' if t['ok'] else 'MISMATCH'}")
    rebuilt = [t for t in data['triggers']
               if t['trigger'] in NO_REBUILD and t['display_calls']]
    for t in rebuilt:
        print(f"\n{t['trigger']}: must not re-render, but called _display "
              f"{t['display_calls']}x")
    bad = [t for t in data['triggers'] if not t['ok']]
    for t in bad:
        print(f"\n{t['trigger']}: expected "
              f"{'attribute-only' if t['expected_identical'] else 'structural'}"
              f", measured {t['class']}")
        fd = t.get('first_diff')
        if fd and 'before' in fd:
            print(f"  before: {fd['before']!r}\n  after:  {fd['after']!r}")
    if rebuilt:
        return 1
    if bad:
        print('\nA chapter lacking headings, footnotes or the divine name will '
              'mismatch\nlegitimately — check the reference before the code.')
        return 1
    cands = [t['trigger'] for t in data['triggers']
             if t['expected_identical'] and t['display_calls']]
    print('\nevery trigger matched its expected class')
    if cands:
        print('still re-rendering (item 22 targets): ' + ', '.join(cands))
    return 0


if __name__ == '__main__':
    sys.exit(run_driver() if '--driver' in sys.argv else orchestrate())
