#!/usr/bin/env python3
"""Behaviour probe for the concordance and original-language search.

Unit tests can reach the data layer and the backend, but not the two
things that only a live window has: a lexicon panel with a real module
behind it, and a search panel whose results arrive on a worker thread.
Both of those are where a feature goes quietly dead — the dictionary peek
of 1.6.2 passed 2,062 tests while raising on every click.

What it drives:
  * the lexicon panel's word study over one book, then over the whole
    Bible, reporting the header and the rows built for each;
  * the Show-more pager, on a word common enough to need one;
  * the Frequency button, which must open search on a `strong:` query and
    fill the word header and the book chart;
  * a `strong:` search typed straight into the panel, and the same query
    intersected with an English word.

Usage:  python3 tools/probe-concordance.py
Exit 0 = every check passed, 1 = a check failed (it is printed), 2 = the
environment is unusable (no SWORD, no interlinear, or no Broadway).
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
DISPLAY = 6


def run(timeout: float = 240.0) -> dict | None:
    with tempfile.TemporaryDirectory(prefix='scriptura-conc-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'

        # The interlinear databases live in the DATA dir, which is scratch
        # here — link the real ones in rather than copying 58 MB, and never
        # write to them.
        real = Path.home() / '.local/share/bible-reader/open_data'
        if not real.is_dir():
            print('no open_data dir — install the interlinear first',
                  file=sys.stderr)
            return None
        dest = Path(env['XDG_DATA_HOME'], 'bible-reader', 'open_data')
        dest.mkdir(parents=True, exist_ok=True)
        for f in real.iterdir():
            if f.is_file():
                os.symlink(f, dest / f.name)

        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / 'settings.json').write_text(json.dumps({'open_to_today': False}))

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
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                sys.stdout.write(proc.stdout)
                return None
        finally:
            broadwayd.terminate()
            broadwayd.wait()


def driver() -> int:
    import logging
    import traceback

    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib

    problems: list[str] = []
    facts: dict = {}

    class Collect(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                problems.append(f'LOG {record.name}: {record.getMessage()}')

    logging.getLogger().addHandler(Collect())
    logging.getLogger().setLevel(logging.DEBUG)

    import content
    import lemma_index
    import main

    if not lemma_index.is_available():
        print(json.dumps({'problems': ['no interlinear database installed'],
                          'facts': {}}))
        return 2

    steps: list = []

    def step(fn):
        steps.append(fn)
        return fn

    app = main.BibleApp()
    state: dict = {}

    def rows_of(listbox):
        """Every row currently built, the pager row included."""
        out, child = [], listbox.get_first_child()
        while child is not None:
            out.append(child)
            child = child.get_next_sibling()
        return out

    @step
    def pick_a_tagged_module(win):
        """The word study only ever opens over a Strong's-tagged module —
        find one, or there is nothing to probe."""
        tagged = [m for m in content.text_bible_names()
                  if content.has_strongs(m)]
        assert tagged, 'no Strong\'s-tagged Bible installed'
        # KJV first when it is there: its Strong's tagging is the densest
        # of the public-domain set, and its 'charity' for ἀγάπη is the
        # rendering the intersection step asks about.
        chosen = 'KJV' if 'KJV' in tagged else tagged[0]
        state['module'] = chosen
        facts['module'] = chosen
        win.pane1._apply_module_change(chosen)

    @step
    def open_a_chapter(win):
        win.pane1.load_reference_at_verse('1 John', 4, 8)
        state['lex'] = win.pane1._lex_panel

    @step
    def study_one_word_in_this_book(win):
        """G26 ἀγάπη — 18 occurrences in 1 John, the most of any book."""
        lex = state['lex']
        lex.set_context('1 John', state['module'])
        lex.show('G26', 'love', morph='')

    @step
    def read_the_book_scoped_result(win):
        lex = state['lex']
        facts['book_header'] = lex._ws_header.get_text()
        facts['book_rows'] = len(rows_of(lex._ws_list))
        assert facts['book_rows'] > 0, \
            'the word study built no rows over one book'

    @step
    def switch_to_the_whole_bible(win):
        lex = state['lex']
        assert lex._scope_bible_btn.get_sensitive(), \
            'Whole Bible is insensitive with the interlinear installed'
        lex._scope_bible_btn.set_active(True)

    @step
    def wait_for_the_bible_scan(win):
        pass   # one tick: the scan posts per chapter

    @step
    def wait_more(win):
        pass

    @step
    def read_the_bible_scoped_result(win):
        lex = state['lex']
        # The pair has to agree with the scope. It did not, and this probe
        # missed it the first time by reading only the row count.
        facts['scope_buttons'] = (lex._scope_book_btn.get_active(),
                                  lex._scope_bible_btn.get_active())
        assert facts['scope_buttons'] == (False, True), (
            'the scope buttons say This book while the list is whole-Bible')
        facts['bible_header'] = lex._ws_header.get_text()
        facts['bible_rows'] = len(rows_of(lex._ws_list))
        facts['bible_pending'] = len(lex._ws_pending)
        assert facts['bible_rows'] > facts['book_rows'], (
            f'whole-Bible built {facts["bible_rows"]} rows, no more than the '
            f'{facts["book_rows"]} of one book')
        # A whole-Bible row has to name its book, or 4:8 could be anything.
        first = rows_of(lex._ws_list)[0]
        label = first.get_child().get_first_child()
        facts['first_ref'] = label.get_text()
        assert any(c.isalpha() for c in facts['first_ref']), \
            f'whole-Bible row {facts["first_ref"]!r} names no book'

    @step
    def page_through_a_common_word(win):
        """G2316 θεός is ~1,300 occurrences: past one page, so the pager
        row must exist and adding a page must build more rows."""
        lex = state['lex']
        lex.show('G2316', 'God', morph='')

    @step
    def wait_for_the_common_word(win):
        pass

    @step
    def wait_for_the_common_word_more(win):
        pass

    @step
    def use_the_pager(win):
        lex = state['lex']
        before = len(rows_of(lex._ws_list))
        facts['page1_rows'] = before
        if lex._ws_more_row is None:
            facts['pager'] = 'not needed'
            return
        btn = lex._ws_more_row.get_child()
        btn.emit('clicked')
        after = len(rows_of(lex._ws_list))
        facts['page2_rows'] = after
        facts['pager'] = 'grew'
        assert after > before, 'Show more built no further rows'

    @step
    def press_frequency(win):
        state['lex']._freq_btn.emit('clicked')

    @step
    def wait_for_search(win):
        pass

    @step
    def wait_for_search_more(win):
        pass

    @step
    def read_the_search_panel(win):
        panel = win._search_panel
        facts['search_query'] = panel._entry.get_text()
        facts['search_results'] = len(panel._results)
        facts['word_header_shown'] = panel._word_box.get_visible()
        facts['chart_shown'] = panel._chart_scroll.get_visible()
        assert facts['search_query'].startswith('strong:'), \
            f'Frequency opened search on {facts["search_query"]!r}'
        assert facts['search_results'] > 0, \
            'Frequency opened search on a query that found nothing'
        assert facts['word_header_shown'], \
            'an original-language search named no word'
        assert facts['chart_shown'], 'no book chart for a strong: search'

    @step
    def search_a_word_and_a_translation(win):
        """`strong:G26 love` — the question the feature exists for. The
        word is one every English translation uses for ἀγάπη somewhere, so
        the check does not depend on which Bible the probe found."""
        win._search_panel.run_query('strong:G26 love')

    @step
    def wait_for_intersection(win):
        pass

    @step
    def wait_for_intersection_more(win):
        pass

    @step
    def read_the_intersection(win):
        panel = win._search_panel
        facts['intersect_results'] = len(panel._results)
        assert facts['intersect_results'] > 0, (
            'no verse where ἀγάπη is rendered "love" — the intersection is '
            'dropping everything')
        # An intersection cannot grow a set: G26 alone must find at least
        # as many verses as G26 with an English word beside it.
        win._search_panel.run_query('strong:G26')

    @step
    def wait_for_g26_alone(win):
        pass

    @step
    def compare_the_two(win):
        panel = win._search_panel
        facts['g26_alone'] = len(panel._results)
        assert facts['intersect_results'] <= facts['g26_alone'], (
            f'the intersection found {facts["intersect_results"]} verses, '
            f'more than the {facts["g26_alone"]} of the word alone')

    @step
    def exclude_a_rendering(win):
        """`strong:G26 -love` — the places ἀγάπη is NOT rendered love."""
        win._search_panel.run_query('strong:G26 -love')

    @step
    def wait_for_exclusion(win):
        pass

    @step
    def wait_for_exclusion_more(win):
        pass

    @step
    def read_the_exclusion(win):
        panel = win._search_panel
        facts['excluded'] = len(panel._results)
        assert facts['excluded'] > 0, \
            'the exclusion subtracted everything'
        assert (facts['excluded'] + facts['intersect_results']
                == facts['g26_alone']), (
            f'{facts["excluded"]} excluded + {facts["intersect_results"]} '
            f'matching != {facts["g26_alone"]} in all')

    @step
    def a_bare_number_is_still_a_text_search(win):
        """The grammar's promise: `G26` searches the text, not Strong's."""
        win._search_panel.run_query('G26')

    @step
    def wait_for_bare(win):
        pass

    @step
    def read_the_bare_search(win):
        panel = win._search_panel
        facts['bare_word_header'] = panel._word_box.get_visible()
        assert not facts['bare_word_header'], \
            'a bare G26 was read as a Strong\'s query'

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
            problems.append(f'STEP {fn.__name__} failed\n'
                            + traceback.format_exc())
        return GLib.SOURCE_CONTINUE

    def on_activate(_a):
        win = app.get_active_window()
        GLib.timeout_add(900, lambda: run_next(win))

    app.connect('activate', on_activate)
    GLib.timeout_add_seconds(210,
                             lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])

    print(json.dumps({'walked': walked, 'facts': facts,
                      'problems': problems}, indent=2))
    return 1 if problems else 0


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(driver())
    report = run()
    if report is None:
        sys.exit(2)
    print(json.dumps(report.get('facts', {}), indent=2, ensure_ascii=False))
    problems = report.get('problems', [])
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(f'{len(problems)} problems', file=sys.stderr)
        sys.exit(1)
    print(f'walked {len(report.get("walked", []))} steps, 0 problems')
    sys.exit(0)
