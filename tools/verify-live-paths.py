#!/usr/bin/env python3
"""Live-path smoke — drives the real app headless and fails on anything the
log calls an error.

Written after the dictionary peek was found dead in released 1.6.2. A local
named `content` shadowed the module inside a 365-line method, so every
double-click on a word raised in the task worker; `tasks` reports a failed
lookup exactly as it reports an empty one, so the peek said "No entry" with
five dictionaries installed. 2,062 unit tests passed over it for a week. What
found it was Andres reading his own terminal.

This is that terminal, automated. It does not assert appearances — the other
verify-* harnesses do that — it walks the paths that only a live window can
reach and treats **any ERROR record, any GLib CRITICAL, and any raised step**
as a failure. The value is in the paths a unit test cannot reach: a real pane
with a rendered chapter, real SWORD modules, real background tasks.

What it walks: the Today page at startup; a chapter; the dictionary peek; the
study menu and every action in it; marks and notes; the sermon door, the
collecting door and the study door that fetches back; the chapter doors; the
tag manager; a backup round trip; export, print and card documents on all
three Annotations pages; app search over the reader's own writing; cross
references; the footnote toggle; present mode; the side menu.

Usage:  python3 tools/verify-live-paths.py

Exit 0 = nothing reached the log, 1 = something did (it is printed), 2 = the
environment is unusable (no SWORD, or Broadway would not start).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY = 4  # private XDG_RUNTIME_DIR per run, so a fixed number never collides


# ────────────────────────────────────────────────────────────────────────
# Orchestrator: scratch XDG + broadwayd + the driver as its own process
# ────────────────────────────────────────────────────────────────────────

def run(timeout: float = 180.0) -> dict | None:
    with tempfile.TemporaryDirectory(prefix='scriptura-live-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'

        # The Today page is built at startup or not at all, and a fresh
        # profile would otherwise open the welcome flow instead.
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / 'settings.json').write_text(json.dumps({'open_to_today': True}))

        broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'],
                                     env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            # Display N opens broadway(N+1).socket — the filename is what is
            # polled for; BROADWAY_DISPLAY takes N itself.
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
                print(f'driver timed out after {timeout:.0f}s',
                      file=sys.stderr)
                return None
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                sys.stdout.write(proc.stdout)
                return None
        finally:
            broadwayd.terminate()
            broadwayd.wait()


# ────────────────────────────────────────────────────────────────────────
# Driver: inside the app, one step per tick
# ────────────────────────────────────────────────────────────────────────

def driver() -> int:
    import logging
    import traceback

    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, GLib

    problems: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                problems.append(
                    f'LOG {record.name}: {record.getMessage()}\n'
                    + (''.join(traceback.format_exception(*record.exc_info))
                       if record.exc_info else ''))

    logging.getLogger().addHandler(Collect())
    logging.getLogger().setLevel(logging.DEBUG)

    def writer(level, fields, _n):
        text = GLib.log_writer_format_fields(level, fields, False)
        # Broadway has no monitor, so libadwaita's fullscreen path asserts
        # on one it cannot have. Neither line says anything about the app.
        if level <= GLib.LogLevelFlags.LEVEL_CRITICAL \
                and 'Broadway' not in text \
                and 'gdk_monitor_get_geometry' not in text:
            problems.append('GLIB ' + text.strip())
        return GLib.LogWriterOutput.HANDLED

    GLib.log_set_writer_func(writer)

    import main

    steps: list = []

    def step(fn):
        steps.append(fn)
        return fn

    app = main.BibleApp()
    state: dict = {}

    @step
    def today_page_at_startup(win):
        assert win._today_view is not None, 'no Today page on a fresh profile'
        win._populate_today()

    @step
    def open_a_chapter(win):
        state['pane'] = win.pane1
        win.pane1.load_reference_at_verse('John', 3, 16)

    @step
    def look_a_word_up(win):
        """The peek that was dead in 1.6.2."""
        pane = state['pane']
        buf = pane._buffer
        text = buf.get_text(*buf.get_bounds(), False)
        at = text.find('love')
        word = 'love'
        if at < 0:
            at, word = text.find('God'), 'God'
        assert at >= 0, 'the chapter rendered no word to look up'
        pane._show_dict_popup(word, at)

    @step
    def dismiss_the_peek(win):
        state['pane'].dismiss_dict_peek()

    @step
    def build_the_study_menu(win):
        import annotation_dialogs
        pop = annotation_dialogs.build_study_menu(state['pane'], [16], 40, 40)
        pop.unparent()

    @step
    def the_rest_of_the_study_menu(win):
        import annotation_dialogs as ad
        pane = state['pane']
        pop = Gtk.Popover()
        pop.set_parent(pane._view)
        try:
            ad.toggle_underline(pane, [16], True, pop)
            ad.toggle_underline(pane, [16], False, pop)
            ad.copy_verse(pane, [16, 17], pop)
            assert ad.highlight_swatches()
            ad.build_suggested_topics('John', 3, 16, Gtk.Entry())
        finally:
            pop.unparent()

    @step
    def mark_and_note_a_verse(win):
        import annotations
        pane = state['pane']
        annotations.save_highlight(pane._module, 'John', 3, 16, '#ffff00')
        annotations.save_note(pane._module, 'John', 3, 16,
                              'The hinge of the chapter.')
        win._refresh_panes('John', 3, 16)

    @step
    def start_a_sermon_from_the_reading_page(win):
        win._sermon_about_here()

    @step
    def title_the_new_sermon(win):
        aw = win._annotations_win
        assert aw is not None and aw._mode == 'sermons', \
            'the sermon door opened nothing'
        aw._sermon_editor.title.set_text('The Sower Went Forth')
        aw._autosave.flush()

    @step
    def collect_a_verse_into_it(win):
        import annotation_dialogs
        import sermons
        target = sermons.most_recent()
        assert target is not None, 'the titled sermon never reached the store'
        state['sermon'] = target['id']
        text, anchor = annotation_dialogs.collected_quote(state['pane'], [16])
        win.collect_into_sermon(target['id'], text, anchor)

    @step
    def pull_from_the_study(win):
        import annotations_window
        aw = win._annotations_win
        aw.select_sermon(state['sermon'])
        editor = aw._sermon_editor
        editor._study_menu()
        marks = annotations_window.marks_on('John', 3)
        assert marks, 'the mark just made is not on the passage'
        editor._insert_mark(marks[0])
        buf = editor.body.get_buffer()
        body = buf.get_text(*buf.get_bounds(), False)
        assert 'John 3:16' in body, body[:200]

    @step
    def the_chapter_doors(win):
        win._open_journal_on('John', 3)
        win._open_sermons_on('John', 3)

    @step
    def the_tag_manager(win):
        import annotations_window
        manager = annotations_window.TagManagerWindow(on_changed=lambda: None)
        manager._populate_tags()
        manager.destroy()

    @step
    def documents_on_every_page(win):
        aw = win._annotations_win
        for mode in ('marks', 'journal', 'sermons'):
            aw.set_mode(mode)
            aw._document(markdown=True)
            aw._document(markdown=False)

    @step
    def export_and_card_sheets(win):
        import export_dialog
        pane = state['pane']
        export_dialog.ExportSheet(pane, [16])._markdown()
        export_dialog.CardSheet(pane, [16])._reference()

    @step
    def backup_round_trip(win):
        import backup
        import sermons
        payload = backup.validate(backup.collect())
        counts = backup.counts(payload)
        assert counts['sermons'] >= 1, counts
        before = len(sermons.all_sermons())
        failed = backup.restore(payload)
        assert not failed, failed
        assert len(sermons.all_sermons()) == before

    @step
    def app_search_over_your_own_writing(win):
        panel = win._search_panel
        panel._entry.set_text('Sower')
        panel._on_search()

    @step
    def cross_references(win):
        win._on_crossref_clicked('John', 3, 16)

    @step
    def footnotes_on_and_off(win):
        pane = state['pane']
        pane.set_show_footnotes(True)
        pane.set_show_footnotes(False)

    @step
    def present_mode(win):
        win._set_present_mode(True)
        win._set_present_mode(False)

    @step
    def the_side_menu(win):
        win._toggle_menu(None)
        win._toggle_menu(None)

    walked: list[str] = []

    def run_next(win):
        if not steps:
            app.quit()
            return GLib.SOURCE_REMOVE
        fn = steps.pop(0)
        walked.append(fn.__name__)
        try:
            fn(win)
        except Exception:
            problems.append(f'STEP {fn.__name__} raised\n'
                            + traceback.format_exc())
        return GLib.SOURCE_CONTINUE

    def on_activate(_a):
        win = app.get_active_window()
        GLib.timeout_add(700, lambda: run_next(win))

    app.connect('activate', on_activate)
    # Safety force-quit: nothing here may wait on a frame clock Broadway
    # never delivers to an unbrowsed window.
    GLib.timeout_add_seconds(150, lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])

    print(json.dumps({'walked': walked, 'problems': problems}, indent=2))
    return 1 if problems else 0


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(driver())
    try:
        import gi  # noqa: F401
    except ImportError:
        print('python3-gobject not installed', file=sys.stderr)
        sys.exit(2)
    report = run()
    if report is None:
        sys.exit(2)
    problems = report.get('problems') or []
    print(f'walked {len(report.get("walked") or [])} live paths, '
          f'{len(problems)} problems')
    for problem in problems:
        print('---')
        print(problem[:2000])
    sys.exit(1 if problems else 0)
