"""Finding what you wrote, and the dot that says you wrote it.

§6.6: a plain in-memory substring pass over a list already loaded — no FTS
index work, deliberately. A reader's own notes are counted in hundreds.
"""
import datetime

import pytest

import annotations
import journal
import search_panel


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: the search panel is a real widget')


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_verse_map_cache', {})
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    return tmp_path


def _panel(on_open_entry=lambda _i: None):
    return search_panel.SearchPanel(
        on_result_clicked=lambda *a: None, on_close=lambda: None,
        on_open_entry=on_open_entry)


# ── The substring pass ───────────────────────────────────────────────────────

def test_a_notes_words_are_found(isolated, display):
    annotations.save_note(None, 'John', 3, 16, 'the hinge of the gospel')
    p = _panel()
    found = p._own_matches('hinge')
    assert [f['book'] for f in found] == ['John']


def test_an_entrys_title_and_body_are_found(isolated, display):
    journal.save('j1', title='Trinity VII', body='the collect for the day')
    p = _panel()
    assert p._own_matches('trinity')[0]['id'] == 'j1'
    assert p._own_matches('collect')[0]['id'] == 'j1'


def test_tags_are_searched_too(isolated, display):
    journal.save('j1', title='x', tags=['baptism'])
    p = _panel()
    assert p._own_matches('baptism')[0]['id'] == 'j1'


def test_the_match_is_case_insensitive(isolated, display):
    journal.save('j1', title='Trinity VII')
    p = _panel()
    assert p._own_matches('TRINITY')
    assert p._own_matches('trInItY')


def test_an_empty_query_matches_nothing(isolated, display):
    journal.save('j1', title='x')
    p = _panel()
    assert p._own_matches('') == []
    assert p._own_matches('   ') == []


def test_the_pass_is_capped(isolated, display):
    """Enough to answer "where did I write that", not enough to bury the
    scripture results underneath it."""
    for n in range(60):
        journal.save(f'j{n}', title=f'entry {n} about grace')
    p = _panel()
    assert len(p._own_matches('grace')) == search_panel.SearchPanel._OWN_CAP


# ── The sections ─────────────────────────────────────────────────────────────

def _rows(panel):
    out = []
    child = panel._results_list.get_first_child()
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


def _labels(panel):
    from gi.repository import Gtk
    out = []
    for row in _rows(panel):
        found = []

        def walk(w):
            if isinstance(w, Gtk.Label):
                found.append(w.get_text())
            c = w.get_first_child()
            while c is not None:
                walk(c)
                c = c.get_next_sibling()
        walk(row)
        out.append(found[0] if found else '')
    return out


def test_notes_and_entries_get_their_own_sections(isolated, display):
    annotations.save_note(None, 'John', 3, 16, 'about grace')
    journal.save('j1', title='On grace', body='more')
    p = _panel()
    p._own = p._own_matches('grace')
    p._populate_results([])
    labels = _labels(p)
    assert 'Your notes' in labels
    assert 'Your journal' in labels
    assert labels.index('Your notes') < labels.index('Your journal')


def test_a_section_with_nothing_in_it_is_not_drawn(isolated, display):
    journal.save('j1', title='On grace')
    p = _panel()
    p._own = p._own_matches('grace')
    p._populate_results([])
    labels = _labels(p)
    assert 'Your journal' in labels
    assert 'Your notes' not in labels


def test_the_journal_stays_out_when_there_is_nowhere_to_open_it(isolated,
                                                                display):
    """A panel with no way to open an entry must not offer one."""
    journal.save('j1', title='On grace')
    p = search_panel.SearchPanel(on_result_clicked=lambda *a: None,
                                 on_close=lambda: None)
    p._own = p._own_matches('grace')
    p._populate_results([])
    assert 'Your journal' not in _labels(p)


def test_an_entry_row_opens_the_entry_rather_than_navigating(isolated,
                                                             display):
    opened = []
    journal.save('j1', title='On grace')
    p = _panel(on_open_entry=opened.append)
    p._own = p._own_matches('grace')
    p._populate_results([])
    row = next(r for r in _rows(p) if hasattr(r, '_entry_id'))
    p._on_row_activated(p._results_list, row)
    assert opened == ['j1']


def test_own_matches_stay_out_of_the_f3_walk(isolated, display):
    """F3 steps through scripture; a verse-less entry has nowhere to step."""
    journal.save('j1', title='On grace')
    p = _panel()
    p._own = p._own_matches('grace')
    assert p._results == []
    assert p.step_result() is False


# ── The plan tile dot ────────────────────────────────────────────────────────

def test_the_written_days_are_gathered_from_the_entry_dates(isolated):
    journal.save('j1', date='2026-09-06', title='a')
    journal.save('j2', date='2026-09-09', title='b')
    journal.save('j3', date='2026-09-06', title='c')   # same day again
    written = {e['date'] for e in journal.all_entries() if e['date']}
    assert written == {'2026-09-06', '2026-09-09'}


def test_a_plan_day_maps_to_a_date_the_dot_can_match(isolated):
    """The tile's date is start + idx; the dot matches an entry's own date,
    which is the day it is ABOUT, not when it was typed."""
    start = datetime.date(2026, 9, 1)
    assert (start + datetime.timedelta(days=5)).isoformat() == '2026-09-06'


def test_the_dot_set_is_recomputed_not_cached_for_the_session(isolated):
    """Nothing else rebuilds the plan grid within a session, so an entry
    written just now has to be picked up when the journal window closes."""
    import window
    assert hasattr(window.BibleWindow, '_refresh_plan_dots')
    # It must not depend on the grid existing — the plan section is built
    # lazily, and closing the journal before ever opening it is normal.
    src = open(window.__file__, encoding='utf-8').read()
    body = src.split('def _refresh_plan_dots')[1].split('def ')[0]
    assert "getattr(self, '_plan_cells', None)" in body


def test_no_scripture_heading_over_nothing(isolated, display):
    """With a book filter on, the scripture half can be empty while the
    unfiltered search was not — and a heading over nothing is a heading
    that lies."""
    journal.save('j1', title='On grace')
    p = _panel()
    p._own = p._own_matches('grace')
    p._results = [('John', 3, 16, 'text')]      # the unfiltered search
    p._populate_results([])                     # what the filter left
    labels = _labels(p)
    assert 'Your journal' in labels
    assert 'Scripture' not in labels

    p._populate_results(p._results)
    assert 'Scripture' in _labels(p)
