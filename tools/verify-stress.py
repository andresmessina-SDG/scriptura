#!/usr/bin/env python3
"""Stress harness — hammers the real app headless and fails on anything the
log calls an error.

Written after the 1.7.2 release sweep. 2,248 unit tests were green over a
tree with three interaction bugs in it: a restore raced the editor's
autosave and the old sermon came back on the next launch; Replace All was
one buffer edit per match and froze the window for seconds; a hand-edited
paper colour stopped the window being built. None of the three is visible
to a test that builds one widget. All three fell out of driving the whole
app hard for ten minutes.

This is that ten minutes, kept. Each scenario runs the real app on a hidden
Broadway display with scratch XDG dirs (and, where it installs or removes
modules, a scratch HOME), pushes one surface far past ordinary use, and
treats **any ERROR record, any GLib CRITICAL, any raised step and any
scenario assertion** as a failure. It does not assert appearances; the
other verify-* harnesses do that.

Every scenario adapts to the modules on the machine: it uses what is
installed and notes what it skipped, so it runs on CI's KJVA + MHCC and on a
full library alike.

Usage:  python3 tools/verify-stress.py [SCENARIO ...] [--out DIR] [--list]

Exit 0 = nothing reached the log, 1 = something did (it is printed),
2 = the environment is unusable (Broadway would not start).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY = 9  # private XDG_RUNTIME_DIR per run, so a fixed number never collides

# Scenario name → what the orchestrator seeds before the app starts.
#   settings: the settings.json to write
#   home:     'scratch' gives the app an empty HOME (system modules only),
#             'kjva' an empty HOME with the user's KJVA copied into ~/.sword
#   env:      extra environment
#   stores:   {filename: text} written into the config dir before launch
_JUNK_A = {'font_size': 'big', 'reading_width': [], 'color_scheme': 7,
           'pane1_module': {'a': 1}, 'pane2_module': '', 'last_book': 99,
           'last_chapter': 'three', 'split_pane_mode': 'yes',
           'window_width': -5, 'window_height': 'tall', 'window_maximized': 'no',
           'line_spacing': None, 'letter_spacing': 'wide', 'ui_language': 'xx',
           'recent_passages': 'John 3', 'church_calendar': 42,
           'show_footnotes': 'true', 'font_family': 3, 'reading_bg_default': 'Paper',
           'text_color_default': 12, 'evening_paper': 'dusk', 'dropcap_color': [],
           'hints_seen': 'all', 'plan_collapsed': 'x', 'reading_rate': 'fast'}
_JUNK_B = {k: [1, 2, 3] for k in _JUNK_A}
_JUNK_C = {k: 1e18 for k in _JUNK_A} | {'font_size': -1e18, 'reading_width': 0,
                                        'window_width': 1e18}
_STORE_JUNK = {'annotations.json': '[]', 'journal.json': '{"entries": 5}',
               'sermons.json': 'not json at all', 'bookmarks.json': '{"x": 1}',
               'reading_plans.json': '[1, 2]', 'search_history.json': '{}',
               'module_positions.json': 'null'}
SCENARIOS: dict[str, dict] = {
    'nav_storm': {},
    'module_zoo': {},
    'annotation_storm': {},
    'editor': {},
    'today': {'settings': {'open_to_today': True}},
    'search': {},
    'peek': {},
    'window_churn': {},
    'backup': {},
    'present': {},
    'plans': {'settings': {'open_to_today': True}},
    'appearance': {},
    'settings_junk_a': {'settings': _JUNK_A},
    'settings_junk_b': {'settings': _JUNK_B},
    'settings_junk_c': {'settings': _JUNK_C},
    'store_junk': {'stores': _STORE_JUNK},
    'modules': {'home': 'kjva'},
    'welcome': {'home': 'scratch', 'env': {'BIBLE_READER_FORCE_WELCOME': '1'}},
}


# ────────────────────────────────────────────────────────────────────────
# Orchestrator: scratch XDG (+ HOME) + broadwayd + the driver as its own process
# ────────────────────────────────────────────────────────────────────────

def _seed_home(kind: str, home: Path) -> None:
    home.mkdir()
    if kind != 'kjva':
        return
    real = Path(os.path.expanduser('~/.sword'))
    conf = real / 'mods.d' / 'kjva.conf'
    if not conf.exists():
        return
    (home / '.sword' / 'mods.d').mkdir(parents=True)
    shutil.copy(conf, home / '.sword' / 'mods.d' / 'kjva.conf')
    for line in conf.read_text(errors='replace').splitlines():
        if line.startswith('DataPath='):
            rel = line.split('=', 1)[1].strip().lstrip('./')
            src = real / rel
            if src.is_dir():
                shutil.copytree(src, home / '.sword' / rel)


def run(scenario: str, out_dir: Path | None, timeout: float = 420.0) -> dict:
    spec = SCENARIOS[scenario]
    with tempfile.TemporaryDirectory(prefix='scriptura-stress-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        # An isolated XDG_DATA_HOME hides the bundled fonts; link them in.
        fonts = Path(os.path.expanduser('~/.local/share/fonts/scriptura'))
        if fonts.is_dir():
            (Path(env['XDG_DATA_HOME']) / 'fonts').mkdir()
            os.symlink(fonts, Path(env['XDG_DATA_HOME']) / 'fonts' / 'scriptura')
        if spec.get('home'):
            _seed_home(spec['home'], Path(scratch, 'home'))
            env['HOME'] = str(Path(scratch, 'home'))
        env.update(spec.get('env', {}))
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'
        env['SCRIPTURA_STRESS_SCRATCH'] = scratch

        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        settings = {'ui_language': 'en', 'tips_enabled': False}
        settings.update(spec.get('settings', {}))
        (cfg / 'settings.json').write_text(json.dumps(settings))
        for name, text in spec.get('stores', {}).items():
            (cfg / name).write_text(text)
        # The store files live in the data dir on a fresh profile; seed both.
        data = Path(env['XDG_DATA_HOME'], 'bible-reader')
        data.mkdir(parents=True, exist_ok=True)
        for name, text in spec.get('stores', {}).items():
            (data / name).write_text(text)

        broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'],
                                     env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            socket = Path(env['XDG_RUNTIME_DIR'], f'broadway{DISPLAY + 1}.socket')
            deadline = time.monotonic() + 5.0
            while not socket.exists():
                if broadwayd.poll() is not None or time.monotonic() > deadline:
                    return {'scenario': scenario, 'ENV': 'broadwayd failed to start'}
                time.sleep(0.05)
            try:
                proc = subprocess.run(
                    [sys.executable, __file__, '--driver', scenario],
                    env=env, cwd=REPO_ROOT, timeout=timeout,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            except subprocess.TimeoutExpired as e:
                tail = e.stderr[-2000:] if isinstance(e.stderr, str) else \
                    (e.stderr or b'')[-2000:].decode(errors='replace')
                return {'scenario': scenario, 'problems': ['TIMEOUT: the driver did not finish'],
                        'n_problems': 1, 'stderr_tail': tail.splitlines()[-15:]}
            lines = proc.stdout.strip().splitlines()
            try:
                report = json.loads(lines[-1])
            except (IndexError, ValueError):
                report = {'scenario': scenario,
                          'problems': [f'CRASH: driver exited {proc.returncode} without a report'],
                          'n_problems': 1, 'stdout_tail': proc.stdout[-1500:]}
            report['returncode'] = proc.returncode
            if proc.returncode != 0 and not report.get('problems'):
                report['problems'] = [f'driver exited {proc.returncode}']
                report['n_problems'] = 1
            noise = ('Warning', 'Broadway', 'gdk_monitor_get_geometry')
            report['stderr_tail'] = [l for l in proc.stderr.splitlines()
                                     if l.strip() and not any(n in l for n in noise)][-15:]
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f'{scenario}.json').write_text(
                    json.dumps(report, indent=1, ensure_ascii=False))
            return report
        finally:
            broadwayd.terminate()
            broadwayd.wait()


# ────────────────────────────────────────────────────────────────────────
# Driver: runs inside the app process
# ────────────────────────────────────────────────────────────────────────

def driver(scenario: str) -> int:
    import logging
    import random
    import re
    import traceback
    import zipfile
    import io
    from collections import Counter
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, GLib

    problems: list[str] = []
    timings: dict[str, float] = {}
    notes: list = []
    skipped: list[str] = []
    allowed: list[re.Pattern] = []   # log lines a scenario expects by design

    def allow(pattern: str) -> None:
        allowed.append(re.compile(pattern))

    def is_allowed(text: str) -> bool:
        return any(p.search(text) for p in allowed)

    class Collect(logging.Handler):
        def emit(self, record):
            if record.levelno < logging.ERROR:
                return
            text = f'LOG {record.name}: {record.getMessage()}'
            if is_allowed(text):
                notes.append({'expected_log': text[:160]})
                return
            if record.exc_info:
                text += '\n' + ''.join(traceback.format_exception(*record.exc_info))
            problems.append(text)
    logging.getLogger().addHandler(Collect())
    logging.getLogger().setLevel(logging.DEBUG)

    def writer(level, fields, _n):
        text = GLib.log_writer_format_fields(level, fields, False)
        if (level <= GLib.LogLevelFlags.LEVEL_CRITICAL
                and 'Broadway' not in text
                and 'gdk_monitor_get_geometry' not in text):
            if is_allowed(text):
                notes.append({'expected_glib': text.strip()[:160]})
            else:
                problems.append('GLIB ' + text.strip())
        return GLib.LogWriterOutput.HANDLED
    GLib.log_set_writer_func(writer)

    import main
    import annotations
    import journal
    import sermons
    import bookmarks
    import backup
    import content
    import settings
    import sword_bridge
    import ebible_bridge
    import reading_plans
    import annotation_dialogs

    app = main.BibleApp()
    app.connect('startup', main._on_startup)
    rnd = random.Random(1972)
    BOOKS = list(sword_bridge._ALL_BOOKS)
    steps: list[tuple[int, object]] = []
    state: dict = {}

    def step(delay=120):
        def deco(fn):
            steps.append((delay, fn))
            return fn
        return deco

    def timed(name, fn):
        t = time.perf_counter()
        r = fn()
        timings[name] = round((time.perf_counter() - t) * 1000, 1)
        return r

    def check(cond, text):
        if not cond:
            problems.append('ASSERT ' + text)

    # ── what this machine has ────────────────────────────────────────────
    bibles = content.text_bible_names()
    readable = set(content.readable_module_names())

    def have(*names):
        """The first of `names` that is installed, else None (and a note)."""
        for n in names:
            if n in readable:
                return n
        skipped.append('none of ' + '/'.join(names))
        return None

    def bible_pool(*preferred):
        pool = [m for m in preferred if m in readable] or bibles[:4]
        return pool or ['KJV']

    # ── ported scenarios ─────────────────────────────────────────────────
    def nav_storm(win):
        mods = bible_pool('KJVA', 'BSB', 'RusSynodal', 'SpaRV1909', 'LEB', 'Vulgate', 'YLT')
        for i in range(120):
            b = rnd.choice(BOOKS)
            ch = rnd.randint(1, sword_bridge.chapter_count(b, None))
            v = rnd.choice([None, 1, 5, 200])

            @step(60)
            def go(win, b=b, ch=ch, v=v):
                win._go_to(b, ch, v)
            if i % 8 == 0:
                m = rnd.choice(mods)

                @step(60)
                def mod(win, m=m):
                    win.pane1._apply_module_change(m)
            if i % 11 == 0:
                @step(60)
                def fn(win):
                    win.pane1.set_show_footnotes(not win.pane1._show_footnotes)
            if i % 13 == 0:
                @step(60)
                def hd(win):
                    win.pane1.set_show_headings(not win.pane1._show_headings)
            if i % 17 == 0:
                @step(60)
                def split(win):
                    win._btn_split.set_active(not win._btn_split.get_active())
            if i % 7 == 0:
                @step(60)
                def back(win):
                    win._on_nav_back(None)
                    win._on_nav_fwd(None)
            if i % 19 == 0:
                w = rnd.choice([360, 520, 700, 900, 1400])

                @step(60)
                def width(win, w=w):
                    win.pane1.set_reading_width(w)
                    win.pane2.set_reading_width(w)
            if i % 23 == 0:
                s = rnd.choice([9, 14, 22, 36])

                @step(60)
                def font(win, s=s):
                    win.pane1.set_font_size(s)

        @step(1500)
        def settle(win):
            loc = tuple(win._current_loc)
            p = (win.pane1.book, win.pane1.chapter)
            if not win.pane1._sync_btn.get_active():
                check(loc[:2] == p, f'after storm: nav says {loc}, pane1 shows {p}')
            notes.append({'loc': loc, 'pane1': p, 'module': win.pane1.module})

    def module_zoo(win):
        zoo = [m for m in ('MHCC', 'MHC', 'Clarke', 'Institutes', 'Easton', 'Catena', 'TSK',
                           'Webster', 'StrongsGreek', 'MorphGNT', 'OSHB', 'SBLGNT', 'Vulgate',
                           'FreDAW', 'DarkNightOfTheSoul', 'Abbott', 'Concord', 'KJVA')
               if m in readable]
        zoo += [m for m in readable if m not in zoo and (
            m.startswith(ebible_bridge.PREFIX) or content.kind(m) in ('catena', 'imagery', 'interlinear'))][:6]
        # The Bible Family Tree: a pane document whose Card and Line both
        # read the other pane, so it goes through the same storm.
        zoo += [m for m in readable if content.type_key(m) == 'family']
        notes.append({'zoo': zoo})
        for m in zoo:
            @step(500)
            def mod(win, m=m):
                win.pane1._apply_module_change(m)

            @step(300)
            def nav(win, m=m):
                win._go_to('John', 3, 16)
                win.pane1.set_show_footnotes(True)
                win._bookmark_here()

            @step(300)
            def menu(win, m=m):
                verses = win.pane1.current_verses() or [1]
                pop = annotation_dialogs.build_study_menu(win.pane1, verses, 10, 10)
                pop.popup()
                GLib.timeout_add(80, lambda: (pop.popdown(), False)[1])

        @step(400)
        def pane2(win):
            win._btn_split.set_active(True)
            second = have('MHCC', 'MHC')
            if second:
                win.pane2._apply_module_change(second)
            win.pane1._apply_module_change(bible_pool('KJVA')[0])
        for b, ch in [('Genesis', 1), ('Psalms', 119), ('Tobit', 3), ('Revelation', 22),
                      ('Sirach', 51), ('Matthew', 5)]:
            @step(400)
            def go(win, b=b, ch=ch):
                win._go_to(b, ch, 1)

        @step(600)
        def present(win):
            win._toggle_present_mode()

        @step(600)
        def unpresent(win):
            win._toggle_present_mode()

        @step(400)
        def end(win):
            pass

    def annotation_storm(win):
        @step(300)
        def open_win(win):
            win._open_annotations()
            aw = win._annotations_win
            aw.is_active = lambda: False
            aw.get_visible = lambda: True
        chapters = [(rnd.choice(BOOKS), rnd.randint(1, 20)) for _ in range(120)]
        for i, (b, ch) in enumerate(chapters):
            @step(25)
            def mark(win, b=b, ch=ch, i=i):
                ch2 = min(ch, sword_bridge.chapter_count(b, None))
                v = rnd.randint(1, 12)
                annotations.save_highlight('KJVA', b, ch2, v, rnd.choice(['#ffff00', '#ff8800', '#88ff88']))
                if i % 3 == 0:
                    annotations.save_note('KJVA', b, ch2, v, f'note {i} ' + 'λόγος ' * (i % 7))
                if i % 4 == 0:
                    annotations.save_tags('KJVA', b, ch2, v, [f'tag{i % 9}', 'grace'])
                if i % 5 == 0:
                    annotations.save_underline('KJVA', b, ch2, v, True)
                if i % 10 == 0:
                    annotations.save_chapter_note('KJVA', b, ch2, f'chapter note {i}')

        @step(1500)
        def reload_cost(win):
            aw = win._annotations_win
            timed('reload_120_chapters_ms', aw._reload)
            timed('reload_again_ms', aw._reload)
            notes.append({'rows': len(aw._entries)})

        @step(200)
        def tags(win):
            annotations.rename_tag('grace', 'mercy')
            annotations.delete_tag('tag3')
            for i in range(60):
                journal.save(journal.new_id(), title=f'Entry {i}', body='Body ' * 50,
                             anchors=[{'book': 'John', 'chapter': 3, 'verses': [16]}] if i % 2 else [],
                             tags=['x'])
            for i in range(20):
                sermons.save(sermons.new_id(), title=f'Sermon {i}', body='## I\n' + 'word ' * 500,
                             anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []}],
                             series={'name': f'Series {i % 3}', 'part': i} if i % 2 else None)

        @step(800)
        def pages(win):
            aw = win._annotations_win
            aw.show_entries_on('John', 3)
            aw.show_sermons_on('Matthew', 13)

        @step(800)
        def restore_mid(win):
            doc = json.loads(json.dumps(backup.collect()))
            check(not backup.restore(doc), 'restore of a fresh collect failed')
            win._on_restore_confirm(None, 'replace', doc)

        @step(1200)
        def wipe(win):
            annotations.replace_all({})
            journal.replace_all({})
            sermons.replace_all({})

        @step(1200)
        def after_wipe(win):
            aw = win._annotations_win
            aw._reload()
            notes.append({'rows_after_wipe': len(aw._entries)})
            win.pane1._fetch_and_render()

        @step(800)
        def end(win):
            pass

    def editor(win):
        sid = sermons.new_id()
        body = '\n\n'.join(('The grace of God is the theme of the text and the hope of the church '
                            * 6 + f'({i}).') for i in range(120))
        sermons.save(sid, title='Sunday', body=body,
                     anchors=[{'book': 'Romans', 'chapter': 8, 'verses': []}])
        big = sermons.new_id()
        sermons.save(big, title='Long one',
                     body='\n\n'.join(('The grace of God ' * 12 + f'paragraph {i}.') for i in range(600)),
                     anchors=[])
        for i in range(40):
            journal.save(journal.new_id(), title=f'E{i}', body='grace ' * 20)

        @step(300)
        def open_win(win):
            win._open_annotations()
            win._annotations_win.is_active = lambda: True

        @step(500)
        def open_sermon(win):
            win._annotations_win.select_sermon(sid)

        @step(600)
        def find(win):
            ed = win._annotations_win._sermon_editor
            ed.find.open()
            ed.find.entry.set_text('the')

        @step(600)
        def counted(win):
            ed = win._annotations_win._sermon_editor
            notes.append({'matches_the': len(ed.find._matches)})
            timed('search_the_8k_words_ms', lambda: ed.find._search(True))
            timed('step_50_ms', lambda: [ed.find.step() for _ in range(50)])

        @step(300)
        def replace_all(win):
            ed = win._annotations_win._sermon_editor
            ed.find.replace_entry.set_text('a')
            notes.append({'replaced': timed('replace_all_8k_words_ms', ed.find.replace_all)})
            check(timings['replace_all_8k_words_ms'] < 500,
                  'Replace All over 8k words took over half a second')

        @step(600)
        def undo(win):
            buf = win._annotations_win._sermon_editor.body.get_buffer()
            timed('undo_ms', buf.undo)
            t = buf.get_text(*buf.get_bounds(), False)
            check(' the ' in t, 'undo did not revert Replace All')
            win._annotations_win._autosave.flush()

        @step(400)
        def typing(win):
            buf = win._annotations_win._sermon_editor.body.get_buffer()

            def type_it():
                for ch in 'Typing with the find bar open, one letter at a time. ':
                    buf.begin_user_action()
                    buf.insert_at_cursor(ch)
                    buf.end_user_action()
            timed('type_55_chars_find_open_ms', type_it)

        @step(1500)
        def modes(win):
            aw = win._annotations_win
            aw._toggle_writing_mode()
            aw._toggle_sidebar()

        @step(600)
        def modes_back(win):
            aw = win._annotations_win
            aw._toggle_writing_mode()
            aw._toggle_sidebar()
            aw._sermon_editor.find.close()

        @step(400)
        def big_one(win):
            timed('select_36k_word_sermon_ms', lambda: win._annotations_win.select_sermon(big))

        @step(800)
        def switch_entries(win):
            aw = win._annotations_win
            aw.show_entries_on('John', 3)
            ids = [e['id'] for e in journal.all_entries()]
            aw._entry_editor.find.open()
            aw._entry_editor.find.entry.set_text('grace')

            def sw():
                for i in ids[:40]:
                    aw.select_entry(i)
            timed('switch_40_entries_find_open_ms', sw)

        @step(1500)
        def end(win):
            pass

    def today(win):
        @step(400)
        def present_(win):
            check(win._today_view is not None, 'Today page absent with open_to_today True')
        for m in bible_pool('BSB', 'RusSynodal', 'SpaRV1909', 'KJVA'):
            @step(300)
            def mod(win, m=m):
                win.pane1._apply_module_change(m)
                if win._today_view is not None:
                    win._populate_today()
        for trad in ['western', 'orthodox', 'lutheran', None, 'garbage', 'western']:
            @step(200)
            def cal(win, trad=trad):
                settings.put('church_calendar', trad)
                if win._today_view is not None:
                    win._populate_today()

        @step(200)
        def papers(win):
            for p in win._papers():
                win._apply_paper(p[1])

        @step(400)
        def dismiss(win):
            win._dismiss_today(animate=False)
            win._go_to('Psalms', 23, 1)

        @step(800)
        def after(win):
            check(win._today_view is None, 'Today view still present after dismiss')
            win._go_to('John', 3, 16)
            win._refresh_panes('John', 3, 16)

        @step(600)
        def end(win):
            pass

    def search(win):
        queries = ['love', 'God so loved', '"in the beginning"', 'λόγος', 'Бог', 'Dios', 'G3056',
                   'H430', 'a', '', ' ', '*', '(', 'love AND grace', 'love OR', 'gra*',
                   '"unterminated', 'x' * 500, 'lo' + chr(0) + 've', 'the the the the',
                   'Jesus wept', 'Иисус плакал', 'amor', '3:16', 'John 3:16', 'ZZZZQQQ',
                   chr(0x1F600), 'Χριστός', 'and', 'faith']
        for q in queries:
            @step(250)
            def go(win, q=q):
                panel = win._search_panel
                panel._entry.set_text(q)
                panel._on_search()
        for m in bible_pool('BSB', 'RusSynodal', 'SpaRV1909') + ([have('MHCC')] if have('MHCC') else []):
            @step(400)
            def mod(win, m=m):
                win.pane1._apply_module_change(m)
                win._search_panel._entry.set_text('grace')
                win._search_panel._on_search()

        # The index under the reader's feet: gone, then garbage, then two
        # searches racing over one rebuild.
        @step(600)
        def index_gone(win):
            m = win.pane1.module
            path = sword_bridge._get_index_path(m)
            state['idx'] = path
            if os.path.exists(path):
                os.remove(path)
            win._search_panel._entry.set_text('grace')
            win._search_panel._on_search()

        @step(4000)
        def index_garbage(win):
            path = state.get('idx')
            if path and os.path.exists(path):
                with open(path, 'r+b') as f:
                    f.seek(0)
                    f.write(b'\0' * 4096)
            win._search_panel._entry.set_text('faith')
            win._search_panel._on_search()

        @step(3000)
        def index_race(win):
            path = state.get('idx')
            if path and os.path.exists(path):
                os.remove(path)
            for q in ('love', 'grace', 'faith'):
                win._search_panel._entry.set_text(q)
                win._search_panel._on_search()

        @step(4000)
        def all_bibles(win):
            import search_controller
            r = timed('search_all_bibles_ms', lambda: search_controller.search_all_bibles('love', False))
            notes.append({'all_bibles_hits': len(r) if isinstance(r, (list, tuple)) else str(type(r))})
        for txt in ['john 3:16', 'Jn 3', 'Иоанна 3', 'Juan 3', 'tobit 5', 'psalm 999', 'psalm -1',
                    '1 1 1', 'song of solomon 8:14', 'xyz 3', 'gen', 'Job', 'job 42:17',
                    'Revelation 22:21', ' ', 'a' * 300]:
            @step(120)
            def jump(win, txt=txt):
                e = Gtk.Entry()
                e.set_text(txt)
                win._on_jump_activate(e)

        @step(800)
        def end(win):
            pass

    def peek(win):
        @step(400)
        def go(win):
            win.pane1._apply_module_change(bible_pool('KJVA')[0])
            win._go_to('John', 3, 1)
        for i in range(30):
            @step(40)
            def pk(win, i=i):
                buf = win.pane1._buffer
                text = buf.get_text(*buf.get_bounds(), False)
                words = [w for w in text.split() if w.isalpha() and len(w) > 3]
                w = words[(i * 7) % len(words)]
                win.pane1._peek.show_dict_popup(w, text.find(w))
                if i % 5 == 4:
                    win.pane1.dismiss_dict_peek()
        fn_mod = have('BSB', 'LEB', 'NET') or next((m for m in bibles if content.has_footnotes(m)), None)

        @step(600)
        def footnotes(win):
            if fn_mod:
                win.pane1._apply_module_change(fn_mod)
            win.pane1.set_show_footnotes(True)
            win._go_to('John', 3, 1)

        @step(800)
        def fn_peeks(win):
            keys = [f'{v}:{n}' for (v, n) in (win.pane1._chapter_footnotes or {})]
            notes.append({'footnotes': len(keys)})
            buf = win.pane1._buffer
            for k in keys[:10]:
                win.pane1._peek.show_footnote_peek(k, buf.get_start_iter())
            win.pane1.dismiss_dict_peek()

        @step(300)
        def hide_while_open(win):
            keys = [f'{v}:{n}' for (v, n) in (win.pane1._chapter_footnotes or {})]
            if keys:
                win.pane1._peek.show_footnote_peek(keys[0], win.pane1._buffer.get_start_iter())
            win.pane1.set_show_footnotes(False)
            win.pane1._apply_module_change(bible_pool('RusSynodal', 'KJVA')[0])

        @step(400)
        def crossrefs(win):
            for v in (1, 16, 36, 99):
                win._on_crossref_clicked('John', 3, v)
        for m, b in (('SBLGNT', 'John'), ('OSHB', 'Genesis'), ('MorphGNT', 'John')):
            if m in readable:
                @step(800)
                def orig(win, m=m, b=b):
                    win.pane1._apply_module_change(m)
                    win._go_to(b, 1, 1)

        @step(800)
        def lexicon(win):
            for word in ('λόγος', 'God', 'grace'):
                win.pane1._peek.show_dict_popup(word, 0)

        @step(800)
        def end(win):
            win.pane1.dismiss_dict_peek()

    def window_churn(win):
        for i in range(12):
            @step(150)
            def open_close(win, i=i):
                win._open_annotations()
                aw = win._annotations_win
                if i % 2:
                    aw.set_mode('sermons')
                aw.close()

            @step(100)
            def after(win, i=i):
                check(annotations._on_change is None, f'change handler still set after close #{i}')
                check(win._annotations_win is None, f'annotations slot not cleared #{i}')
        for i in range(25):
            @step(30)
            def churn(win, i=i):
                win._toggle_menu(None)
                win._btn_split.set_active(i % 2 == 0)
                if i % 5 == 0:
                    win._set_present_mode(True)
                    win._set_present_mode(False)

        @step(400)
        def sheets(win):
            import export_dialog
            for i in range(8):
                export_dialog.ExportSheet(win.pane1, [1, 2, 3])._markdown()
                export_dialog.CardSheet(win.pane1, [16])._reference()

        @step(300)
        def bookmarks_(win):
            for i in range(40):
                win._bookmark_here()
            pop = Gtk.Popover()
            pop.set_parent(win.pane1.view)
            win._build_bookmark_content(pop)
            pop.unparent()
            while bookmarks.get_all():
                bookmarks.remove(0)

        @step(300)
        def restores(win):
            doc = json.loads(json.dumps(backup.collect()))
            for i in range(5):
                win._on_restore_confirm(None, 'replace', doc)

        @step(800)
        def end(win):
            win._btn_split.set_active(True)

    # ── new scenarios ────────────────────────────────────────────────────
    def backup_(win):
        sid = sermons.new_id()
        sermons.save(sid, title='Before', body='ORIGINAL BODY', anchors=[])

        @step(300)
        def open_win(win):
            win._open_annotations()
            win._annotations_win.is_active = lambda: True
            win._annotations_win.select_sermon(sid)

        @step(400)
        def take_copy(win):
            state['doc'] = json.loads(json.dumps(backup.collect()))
            state['doc']['sermons']['sermons'][sid]['body'] = 'RESTORED BODY FROM THE COPY'

        @step(300)
        def type_pending(win):
            buf = win._annotations_win._sermon_editor.body.get_buffer()
            buf.begin_user_action()
            buf.insert(buf.get_end_iter(), ' plus typing not yet saved')
            buf.end_user_action()
            check(win._annotations_win._autosave.pending, 'no autosave pending after typing')

        @step(200)
        def restore(win):
            win._on_restore_confirm(None, 'replace', state['doc'])

        @step(1500)
        def after(win):
            stored = sermons.get(sid)['body']
            check('RESTORED' in stored, f'restore lost to the pending autosave: store holds {stored!r}')

        # Payload shapes: every version this app ever wrote, and things that
        # are not backups at all. validate() must refuse the junk and
        # restore() must never leave a store half-replaced.
        @step(300)
        def shapes(win):
            good = backup.collect()
            v1 = {'format': backup.FORMAT, 'version': 1, 'annotations': good['annotations'],
                  'bookmarks': good.get('bookmarks', [])}
            v2 = {k: v for k, v in good.items() if k != 'sermons'} | {'version': 2}
            for name, doc in (('v1', v1), ('v2', v2), ('v3', good)):
                try:
                    backup.validate(json.loads(json.dumps(doc)))
                except ValueError as e:
                    problems.append(f'ASSERT a {name} backup was refused: {e}')
                failed = backup.restore(json.loads(json.dumps(doc)))
                check(not failed, f'{name} restore failed for {failed}')
            junk = [{'version': 99}, {'version': 'three'}, [], 'x', None, {},
                    {'version': 3, 'annotations': []}, {'version': 3, 'sermons': {'sermons': [1, 2]}},
                    {'version': 3, 'journal': {'entries': None}}]
            refused = 0
            for j in junk:
                try:
                    backup.validate(j)
                except ValueError:
                    refused += 1
                except Exception:
                    problems.append('validate raised something other than ValueError on '
                                    f'{str(j)[:60]}\n' + traceback.format_exc())
            notes.append({'junk_refused': f'{refused}/{len(junk)}'})
            check(refused == len(junk), 'validate accepted junk')
            check(sermons.get(sid) is not None, 'the sermon vanished across restores')

        @step(300)
        def huge(win):
            doc = json.loads(json.dumps(backup.collect()))
            for i in range(2000):
                doc['journal']['entries'][f'huge{i}'] = {
                    'id': f'huge{i}', 'title': 'T' * 200, 'body': 'λόγος ' * 400,
                    'created': '2026-01-01T00:00:00', 'modified': '2026-01-01T00:00:00',
                    'anchors': [], 'tags': ['a', 'b']}
            timed('restore_2000_entries_ms', lambda: win._on_restore_confirm(None, 'replace', doc))

        @step(2500)
        def copies(win):
            folder = os.path.join(os.environ['SCRIPTURA_STRESS_SCRATCH'], 'copies')
            os.makedirs(folder)
            for i in range(3):
                backup.daily_copy(folder)
            notes.append({'copies': len(os.listdir(folder)), 'newest': bool(backup.newest_daily_copy(folder))})
            Path(folder, 'garbage.json').write_text('{')
            Path(folder, 'scriptura-study-data-2020-01-01.json').write_text('not json')
            backup.newest_daily_copy(folder)
            # A folder that cannot be written logs, by design, and leaves no half file.
            # Root writes through a mode (CI runs its container as root), so
            # there is no read-only folder to test with there.
            if os.geteuid() == 0:
                skipped.append('read-only folder: running as root')
                return
            ro = os.path.join(os.environ['SCRIPTURA_STRESS_SCRATCH'], 'ro')
            os.makedirs(ro, mode=0o500)
            allow(r'daily copy failed')
            check(backup.daily_copy(ro) is None, 'daily_copy into a read-only folder returned a path')
            check(not os.listdir(ro), 'daily_copy left a file in a read-only folder')
            os.chmod(ro, 0o700)

        @step(600)
        def end(win):
            pass

    def present(win):
        mods = bible_pool('KJVA', 'BSB', 'RusSynodal')

        @step(400)
        def enter(win):
            win._set_present_mode(True)
            check(win._present._present_mode, 'present mode did not turn on')
        for i in range(30):
            b = rnd.choice(BOOKS)
            ch = rnd.randint(1, sword_bridge.chapter_count(b, None))

            @step(80)
            def go(win, b=b, ch=ch, i=i):
                win._present_jump(b, ch, rnd.choice([1, 5, 30]))
                if i % 4 == 0:
                    win._present_cross(rnd.choice([-1, 1]))
                if i % 6 == 0:
                    win.pane1._apply_module_change(rnd.choice(mods))
                if i % 7 == 0:
                    win._present_toggle_parallel(i % 14 == 0)
                if i % 9 == 0:
                    win.set_default_size(rnd.choice([640, 1024, 1920, 3840]), rnd.choice([400, 768, 2160]))
                if i % 11 == 0:
                    win.pane1.set_font_size(rnd.choice([12, 40, 72]))

        @step(600)
        def controls(win):
            win._sync_present_controls()
            win._present_update_controls(0)
            win._present_update_controls(10_000)

        @step(400)
        def leave(win):
            win._set_present_mode(False)
            check(not win._present._present_mode, 'present mode did not turn off')

        @step(400)
        def twice(win):
            for _ in range(6):
                win._toggle_present_mode()
            check(not win._present._present_mode, 'six toggles left present mode on')
        other = next((m for m in readable if m.startswith(ebible_bridge.PREFIX)), None) or have('MHCC')
        if other:
            @step(500)
            def non_sword(win, other=other):
                win.pane1._apply_module_change(other)
                win._set_present_mode(True)
                win._present_jump('John', 3, 16)

            @step(800)
            def back(win):
                win._set_present_mode(False)
                win.pane1._apply_module_change(mods[0])

        @step(600)
        def end(win):
            pass

    def plans(win):
        import datetime
        ids = [p['id'] for p in reading_plans.get_plans()]
        today_s = datetime.date.today()
        dates = [today_s.isoformat(), (today_s - datetime.timedelta(days=400)).isoformat(),
                 (today_s + datetime.timedelta(days=30)).isoformat(), '2020-02-30', '', 'yesterday',
                 (today_s - datetime.timedelta(days=3)).isoformat()]
        for pid in ids:
            for d in dates:
                @step(60)
                def plan(win, pid=pid, d=d):
                    reading_plans.set_plan(pid)
                    reading_plans.set_start_date(pid, d)
                    win._refresh_plan_ui()
                    if win._today_view is not None:
                        win._populate_today()

            @step(80)
            def act(win, pid=pid):
                win._on_plan_catch_up(None)
                win._on_plan_today_check(win._plan_today_check)
                win._on_plan_today_check(win._plan_today_check)
                reading_plans.mark_done_through(pid, 10_000)
                reading_plans.set_day_done(pid, -1, True)
                reading_plans.set_day_done(pid, 10_000, True)
                win._refresh_plan_ui()
                win._on_plan_reset(None)
                win._refresh_plan_ui()

        @step(300)
        def anchors(win):
            for pid in ids:
                total = len(reading_plans.get_plan_days(pid))
                for d in dates:
                    try:
                        reading_plans.plan_anchor(pid, d, total)
                    except ValueError:
                        pass   # a bad date is refused; the UI never sends one
            check(reading_plans.plan_anchor(ids[0], today_s.isoformat(), 0) == (0, False),
                  'plan_anchor with no days')

        @step(300)
        def file_junk(win):
            import paths
            Path(paths.reading_plans_path()).write_text('[1, 2, 3]')
            reading_plans._load.cache_clear() if hasattr(reading_plans._load, 'cache_clear') else None
            reading_plans.set_plan(ids[0])
            win._refresh_plan_ui()
            win._on_plan_open_today(None)

        @step(600)
        def end(win):
            pass

    def appearance(win):
        from gi.repository import Adw
        schemes = [('light', Adw.ColorScheme.FORCE_LIGHT), ('dark', Adw.ColorScheme.FORCE_DARK),
                   ('default', Adw.ColorScheme.DEFAULT)]
        for i in range(24):
            w, h = rnd.choice([(300, 200), (640, 480), (1024, 768), (1920, 1080), (3840, 2160), (5000, 300)])

            @step(70)
            def size(win, w=w, h=h, i=i):
                win.set_default_size(w, h)
                if i % 3 == 0:
                    scheme, adw = schemes[i % 3]
                    settings.put('color_scheme', scheme)
                    Adw.StyleManager.get_default().set_color_scheme(adw)
                    win._apply_mode_theme()
                if i % 4 == 0:
                    for p in win._papers():
                        win._apply_paper(p[1])
                if i % 5 == 0:
                    win.pane1.set_appearance(font_size=rnd.choice([1, 6, 200]),
                                             line_spacing=rnd.choice([0, 0.5, 5]),
                                             letter_spacing=rnd.choice([-5, 0, 20]),
                                             font_family=rnd.choice(['', 'Nonexistent Face', 'Serif', 'x' * 300]),
                                             font_bold=rnd.choice([True, False]),
                                             font_justify=rnd.choice([True, False]))
                    win.pane1.set_font_size(rnd.choice([9, 14, 36]))
                if i % 6 == 0:
                    win.pane1.set_reading_width(rnd.choice([100, 360, 5000]))
                    win.pane1.set_reading_margin(rnd.choice([0, 200]))
                if i % 7 == 0:
                    for setter in ('set_divine_smallcaps', 'set_oldstyle_numerals', 'set_colored_dropcap',
                                   'set_poetry_flush', 'set_mark_current_unit', 'set_focus_current_unit',
                                   'set_hover_preview', 'set_lexicon_enabled'):
                        getattr(win.pane1, setter)(i % 2 == 0)
                win._go_to(rnd.choice(BOOKS), 1, 1)

        @step(300)
        def evening(win):
            for s in (0.0, 0.5, 1.0, 5.0, -1.0, 0.0):
                win.pane1.set_evening_strength(s)
                win.pane2.set_evening_strength(s)

        @step(300)
        def languages(win):
            import i18n
            for code in ('es', 'ru', 'xx', None, 'en'):
                i18n.install_language(code)
                win._go_to('John', 3, 16)
                win._toggle_menu(None)
                win._toggle_menu(None)
            i18n.install_language('en')

        @step(600)
        def end(win):
            win.pane1.set_appearance(font_size=14, line_spacing=1.5, letter_spacing=0,
                                     font_family='', font_bold=False, font_justify=False)

    def settings_junk(win):
        # The app opened at all with every setting wrong-typed; now use it.
        @step(300)
        def use(win):
            win._go_to('John', 3, 16)
            win._toggle_menu(None)
            win._toggle_menu(None)
            win._btn_split.set_active(True)
            win._btn_split.set_active(False)
            for p in win._papers():
                win._apply_paper(p[1])
            win.pane1.set_font_size(14)

        @step(300)
        def surfaces(win):
            win._open_annotations()
            win._annotations_win.close()
            win._set_present_mode(True)
            win._set_present_mode(False)
            win._search_panel._entry.set_text('love')
            win._search_panel._on_search()
            win._bookmark_here()
            win._refresh_plan_ui()
            if win._today_view is not None:
                win._populate_today()

        @step(800)
        def saved(win):
            settings.flush()
            import paths
            data = json.loads(Path(paths.settings_path()).read_text())
            notes.append({'settings_written': len(data)})

        @step(400)
        def end(win):
            pass

    def store_junk(win):
        import paths
        allow(r'load failed|quarantin|unreadable|not a')

        @step(300)
        def stores(win):
            annotations.save_highlight('KJVA', 'John', 3, 16, '#ffff00')
            journal.save(journal.new_id(), title='after junk', body='x')
            sermons.save(sermons.new_id(), title='after junk', body='y', anchors=[])
            win._bookmark_here()
            reading_plans.set_plan('psalms_30_days')
            win._refresh_plan_ui()
            win._search_panel._entry.set_text('love')
            win._search_panel._on_search()
            win._open_annotations()
            check(len(annotations.get_all() if hasattr(annotations, 'get_all') else [1]) >= 1,
                  'the mark made after a junk store did not stick')

        @step(800)
        def quarantined(win):
            cfg = Path(paths.config_dir())
            data = Path(paths.data_dir())
            bad = [p.name for d in (cfg, data) if d.is_dir() for p in d.iterdir()
                   if 'unreadable' in p.name or p.suffix == '.bak']
            notes.append({'quarantined': bad})

        @step(400)
        def end(win):
            pass

    def modules(win):
        # HOME is a scratch copy holding only KJVA (plus whatever the system
        # ships), so installing and removing touch nothing real.
        sword_root = os.path.expanduser('~/.sword')
        allow(r'zip|conf|DataPath|not a module|No module')

        def kjva_zip():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                for p in Path(sword_root).rglob('*'):
                    if p.is_file():
                        z.write(p, p.relative_to(sword_root).as_posix())
            return buf.getvalue()

        @step(300)
        def inspect(win):
            if not os.path.exists(os.path.join(sword_root, 'mods.d', 'kjva.conf')):
                skipped.append('no KJVA to copy; module scenario runs on system modules only')
                return
            state['zip'] = kjva_zip()
            found = sword_bridge.inspect_module_zip(state['zip'])
            notes.append({'inspect': str(found)[:200]})
            for junk in (b'', b'PK\x03\x04garbage', state['zip'][:500], os.urandom(4096)):
                try:
                    sword_bridge.inspect_module_zip(junk)
                except Exception as e:
                    notes.append({'junk_zip_refused': type(e).__name__})
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                z.writestr('mods.d/evil.conf', '[Evil]\nDataPath=../../../evil/\nModDrv=zText\n')
                z.writestr('modules/x', 'x')
            try:
                sword_bridge.inspect_module_zip(buf.getvalue())
                sword_bridge.install_module_from_zip(buf.getvalue(), ['Evil'])
            except Exception as e:
                notes.append({'traversal_refused': type(e).__name__})
            check(not Path(sword_root, '..', 'evil').exists(), 'DataPath traversal wrote outside ~/.sword')
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                z.writestr('README', 'no conf here')
            try:
                sword_bridge.inspect_module_zip(buf.getvalue())
            except Exception as e:
                notes.append({'no_conf_refused': type(e).__name__})

        @step(300)
        def remove_shown(win):
            # Only the scratch copy is ours to remove. On CI the container
            # runs as root, installmgr writes to /usr/share/sword, and the
            # bridge rightly refuses to remove a system module.
            if 'KJVA' not in readable or 'zip' not in state:
                return
            win.pane1._apply_module_change('KJVA')
            win._go_to('John', 3, 16)
            sword_bridge.remove_module('KJVA')
            win._on_modules_changed()
            win._go_to('John', 4, 1)
            notes.append({'pane_after_remove': win.pane1.module})
            check('KJVA' not in content.readable_module_names(), 'KJVA still listed after removal')

        @step(800)
        def reinstall(win):
            if 'zip' not in state:
                return
            timed('install_from_zip_ms', lambda: sword_bridge.install_module_from_zip(state['zip'], ['KJVA']))
            sword_bridge.install_module_from_zip(state['zip'], ['KJVA'])   # twice: overwrite path
            win._on_modules_changed()
            check('KJVA' in content.readable_module_names(), 'KJVA missing after reinstall')
            win.pane1._apply_module_change('KJVA')
            win._go_to('John', 3, 16)

        @step(600)
        def ebible(win):
            import urllib.request
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                z.writestr('01-GENstress.usfm',
                           '\\id GEN\n\\c 1\n\\v 1 In the beginning \\w God|strong="H430"\\w* created.\n'
                           '\\v 2 And the earth\\f + \\fr 1:2 \\ft a note\\f* was without form.\n')
                z.writestr('44-JHNstress.usfm', '\\id JHN\n\\c 3\n\\v 16 For God so loved.\n')

            # A BytesIO reads in chunks, as a response does (downloads read
            # through transfer.read), and is a context manager already.
            urllib.request.urlopen = lambda req, timeout=None: io.BytesIO(
                buf.getvalue())
            ebible_bridge.download_translation_sync(
                'stress', {'translationId': 'stress', 'shortTitle': 'Stress', 'UpdateDate': '2026-01-01'})
            win._on_modules_changed()
            name = ebible_bridge.PREFIX + 'stress'
            check(name in content.readable_module_names(), 'the imported eBible is not readable')
            win.pane1._apply_module_change(name)
            win._go_to('Genesis', 1, 1)
            win.pane1.set_show_footnotes(True)

        @step(800)
        def ebible_use(win):
            name = ebible_bridge.PREFIX + 'stress'
            win._go_to('John', 3, 16)
            win._go_to('Revelation', 22, 1)        # a book the translation lacks
            win._search_panel._entry.set_text('God')
            win._search_panel._on_search()
            win._bookmark_here()
            annotations.save_highlight(name, 'Genesis', 1, 1, '#ffff00')

        @step(800)
        def ebible_remove_shown(win):
            name = ebible_bridge.PREFIX + 'stress'
            win.pane1._apply_module_change(name)
            ebible_bridge.remove_translation('stress')
            win._on_modules_changed()
            win._go_to('John', 3, 16)
            notes.append({'pane_after_ebible_remove': win.pane1.module})
            check(name not in content.readable_module_names(), 'removed eBible still listed')

        @step(600)
        def end(win):
            pass

    def welcome(win):
        # `win` here is the WelcomeWindow: the app opened it because HOME is
        # empty and BIBLE_READER_FORCE_WELCOME is set. The system modules make
        # the hand-off possible with the download stubbed out.
        import welcome as welcome_mod

        @step(300)
        def languages(win):
            notes.append({'languages': [c for c, _n in win._languages]})
            for code, _name in win._languages:
                win._on_language_card(None, code)
                bundles = welcome_mod.bundles_for(code)
                check(bool(bundles), f'no bundles for {code}')
                win._rebuild('choose')
                win._on_back_to_language(None) if getattr(win, '_back_to_lang', None) else None

        @step(300)
        def close_guard(win):
            win._installing = True
            win._on_close_request(win)          # asks; must not close
            win._installing = False
            check(win.get_visible(), 'the close guard let the window go while installing')

        @step(2500)
        def install(win):
            win._on_language_card(None, win._language)
            bundle = welcome_mod.bundles_for(win._language)[0]

            def fake_worker(bundle):
                time.sleep(0.2)
                GLib.idle_add(win._finish_install, [], bundle)
            win._install_worker = fake_worker
            win._on_card_clicked(None, bundle)

        @step(800)
        def handed_off(win):
            notes.append({'status': win._status.get_text(), 'bibles': content.text_bible_names(),
                          'windows': [type(w).__name__ for w in app.get_windows()]})
            main_win = next((w for w in app.get_windows() if w is not win), None)
            check(main_win is not None, 'no main window after the welcome hand-off')
            if main_win is not None:
                main_win._go_to('John', 3, 16)
                notes.append({'main_module': main_win.pane1.module})

        @step(600)
        def end(win):
            pass

    scenarios = {
        'nav_storm': nav_storm, 'module_zoo': module_zoo, 'annotation_storm': annotation_storm,
        'editor': editor, 'today': today, 'search': search, 'peek': peek,
        'window_churn': window_churn, 'backup': backup_, 'present': present, 'plans': plans,
        'appearance': appearance, 'settings_junk_a': settings_junk, 'settings_junk_b': settings_junk,
        'settings_junk_c': settings_junk, 'store_junk': store_junk, 'modules': modules,
        'welcome': welcome,
    }

    walked: list[str] = []

    def run_next(win):
        if not steps:
            GLib.timeout_add(600, lambda: (app.quit(), False)[1])
            return GLib.SOURCE_REMOVE
        delay, fn = steps.pop(0)
        walked.append(fn.__name__)
        try:
            fn(win)
        except Exception:
            problems.append(f'STEP {fn.__name__} raised\n' + traceback.format_exc())
        GLib.timeout_add(delay, lambda: run_next(win))
        return GLib.SOURCE_REMOVE

    def on_activate(_a):
        win = app.get_active_window()
        if win is None:
            problems.append('no window after activate')
            app.quit()
            return
        try:
            scenarios[scenario](win)
        except Exception:
            problems.append('SETUP raised\n' + traceback.format_exc())
        GLib.timeout_add(1500, lambda: run_next(win))
    app.connect('activate', on_activate)
    GLib.timeout_add_seconds(380, lambda: (problems.append('TIMEOUT inside driver'), app.quit(), False)[2])
    t0 = time.perf_counter()
    app.run([])
    print(json.dumps({
        'scenario': scenario, 'steps': len(walked),
        'seconds': round(time.perf_counter() - t0, 1),
        'timings': timings, 'notes': notes[:60], 'skipped': skipped,
        'problems': problems[:40], 'n_problems': len(problems),
        'problem_kinds': Counter(p.split('\n')[0][:90] for p in problems).most_common(8),
    }, ensure_ascii=False))
    return 0


# ────────────────────────────────────────────────────────────────────────

def main_() -> int:
    args = sys.argv[1:]
    if args[:1] == ['--driver']:
        return driver(args[1])
    if '--list' in args:
        print('\n'.join(SCENARIOS))
        return 0
    out_dir = None
    if '--out' in args:
        i = args.index('--out')
        out_dir = Path(args[i + 1])
        del args[i:i + 2]
    names = args or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print('unknown scenario(s): ' + ', '.join(unknown), file=sys.stderr)
        return 2
    worst = 0
    for name in names:
        t = time.monotonic()
        rep = run(name, out_dir)
        if 'ENV' in rep:
            print(f'{name:18} ENV  {rep["ENV"]}')
            return 2
        n = rep.get('n_problems', 0)
        flag = 'ok  ' if not n else 'FAIL'
        print(f'{name:18} {flag} {rep.get("steps", 0):4} steps {time.monotonic() - t:6.1f}s'
              + (f'  skipped: {"; ".join(rep["skipped"])[:80]}' if rep.get('skipped') else ''))
        for p in rep.get('problems', [])[:12]:
            print('    ' + p.replace('\n', '\n    ')[:1500])
        for line in rep.get('stderr_tail', []):
            if n:
                print('    stderr: ' + line[:300])
        worst = max(worst, 1 if n else 0)
    return worst


if __name__ == '__main__':
    sys.exit(main_())
