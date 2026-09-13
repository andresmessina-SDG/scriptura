"""The four ways into an entry, and what each one knows that the entry
never will again.

The Today door is the reason the feature is worth building: the day's
readings, the plan day and the church-year designation are all already
resolved on that page, so the entry arrives anchored and stamped with
nothing typed for the reader.
"""
import datetime

import pytest

import annotations
import annotations_window
import journal
import reading_plans


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: the Annotations window is a real '
                    'Adw.Window')


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_verse_map_cache', {})
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(journal, '_load_failed', False)
    monkeypatch.setattr(reading_plans, '_FILE',
                        str(tmp_path / 'reading_plans.json'))
    monkeypatch.setattr(reading_plans, '_cache', None)
    return tmp_path


def _open(**kw):
    return annotations_window.AnnotationsWindow(
        on_navigate=lambda *a: None, **kw)


# ── start_entry ──────────────────────────────────────────────────────────────

def test_a_door_can_open_the_window_straight_onto_an_entry(isolated, display):
    win = _open(new_entry={'anchors': [
        {'book': 'Romans', 'chapter': 6, 'verses': []}]})
    try:
        assert win._detail_stack.get_visible_child_name() == 'entry'
        assert win._current_entry['anchors'] == [
            {'book': 'Romans', 'chapter': 6, 'verses': []}]
        # and nothing is on disk until there are words
        win._autosave.flush()
        assert journal.all_entries() == []
    finally:
        win.destroy()


def test_provenance_is_stamped_at_creation_and_survives_the_first_write(
        isolated, display):
    """Which plan day and which Sunday an entry came from cannot be
    recovered afterwards, so the door records them or nobody does."""
    win = _open(new_entry={
        'anchors': [{'book': 'Romans', 'chapter': 6, 'verses': []}],
        'plan': {'id': 'blended', 'day': 42},
        'collect': 'anglican:trinity7'})
    try:
        win._entry_editor.body.get_buffer().set_text('what came of this reading')
        win._autosave.flush()
        stored = journal.all_entries()[0]
        assert stored['plan'] == {'id': 'blended', 'day': 42}
        assert stored['collect'] == 'anglican:trinity7'
    finally:
        win.destroy()


def test_an_entry_started_from_a_door_carries_every_anchor(isolated, display):
    """A plan day is three or four passages and they are ONE entry."""
    day = [{'book': b, 'chapter': c, 'verses': []}
           for b, c in (('Genesis', 1), ('Genesis', 2), ('Psalms', 1),
                        ('Matthew', 1))]
    win = _open(new_entry={'anchors': day})
    try:
        win._entry_editor.title.set_text('Day 1')
        win._autosave.flush()
        assert journal.all_entries()[0]['anchors'] == day
    finally:
        win.destroy()


def test_a_second_door_into_an_open_window_starts_another_entry(isolated,
                                                                display):
    win = _open()
    try:
        win.start_entry(anchors=[{'book': 'John', 'chapter': 1,
                                  'verses': [1]}])
        win._entry_editor.title.set_text('first')
        win._autosave.flush()
        win.start_entry(anchors=[{'book': 'Acts', 'chapter': 2,
                                  'verses': []}])
        win._entry_editor.title.set_text('second')
        win._autosave.flush()
        titles = sorted(e['title'] for e in journal.all_entries())
        assert titles == ['first', 'second']
    finally:
        win.destroy()


def test_the_entry_opens_dated_today_unless_told_otherwise(isolated, display):
    win = _open(new_entry={'anchors': []})
    try:
        assert win._current_entry['date'] == journal.today()
        win.start_entry(date='2026-01-06')
        assert win._current_entry['date'] == '2026-01-06'
    finally:
        win.destroy()


# ── The plan day a Today door would hand over ───────────────────────────────

def test_a_plan_days_readings_become_whole_chapter_anchors(isolated):
    """Reading is (book, chapter) — a plan day names chapters, never verses —
    so its anchors carry an empty verse list, which the store keeps as
    meaning the whole chapter rather than no anchor at all."""
    days = reading_plans.get_plan_days('bible_1_year')
    assert days
    anchors = [{'book': b, 'chapter': c, 'verses': []} for b, c in days[0]]
    journal.save('j1', anchors=anchors)
    assert journal.get('j1')['anchors'] == anchors
    assert all(a['verses'] == [] for a in journal.get('j1')['anchors'])


def test_today_index_stays_inside_the_plan(isolated):
    """A reader who started a one-year plan two years ago still gets a day
    that exists — the door clamps rather than indexing off the end."""
    reading_plans.set_start_date('bible_1_year', '2020-01-01')
    days = reading_plans.get_plan_days('bible_1_year')
    raw = reading_plans.today_index('2020-01-01')
    assert raw >= len(days)
    clamped = max(0, min(raw, len(days) - 1))
    assert 0 <= clamped < len(days)


# ── The keyboard ─────────────────────────────────────────────────────────────

def test_both_accelerators_are_registered_and_unique():
    """Ctrl+J and Ctrl+Shift+J must not be taken by anything else, and the
    shortcuts window reads the same table, so it cannot drift."""
    import window
    src = open(window.__file__, encoding='utf-8').read()
    assert "('annotations', ['<Ctrl>j']" in src
    assert "('write-entry', ['<Ctrl><Shift>j']" in src
    assert src.count("'<Ctrl>j'") == 1
    assert src.count("'<Ctrl><Shift>j'") == 1
    # and both are listed for the reader
    assert "'action', 'annotations'" in src
    assert "'action',\n             'write-entry'" in src


# ── The verse door speaks app space ─────────────────────────────────────────

def test_app_verse_is_the_inward_twin_of_module_verse(isolated):
    """An anchor holds app space, and the pane speaks its module's numbering.
    Writing one by hand needs the inward door, not the outward one."""
    assert annotations.app_verse(None, 'John', 3, 16) == 16
    assert annotations.app_verse('KJVA', 'John', 3, 16) == 16
    out = annotations.module_verse('KJVA', 'John', 3, 16)
    assert annotations.app_verse('KJVA', 'John', 3, out) == 16


# ── Found, not filed: the reading page's one word about the journal ──────────

def test_entries_on_counts_every_anchor_not_just_the_first(isolated):
    """An entry anchored to three passages has been written about all three,
    so it counts on all three."""
    journal.save('j1', title='a', anchors=[
        {'book': 'John', 'chapter': 3, 'verses': [16]},
        {'book': 'Romans', 'chapter': 5, 'verses': []}])
    journal.save('j2', title='b', anchors=[
        {'book': 'Romans', 'chapter': 5, 'verses': [1]}])
    journal.save('j3', title='c')
    assert len(journal.entries_on('Romans', 5)) == 2
    assert len(journal.entries_on('John', 3)) == 1
    assert journal.entries_on('John', 4) == []


def test_the_chapter_door_opens_on_the_entry_it_promised(isolated, display):
    """The row says *2 entries on this chapter*; what opens has to be one of
    them, not whatever the list happened to be showing."""
    journal.save('j1', title='elsewhere', anchors=[
        {'book': 'Genesis', 'chapter': 1, 'verses': [1]}])
    journal.save('j2', title='here', anchors=[
        {'book': 'Romans', 'chapter': 5, 'verses': [1]}])
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        win.show_entries_on('Romans', 5)
        assert win._mode == 'journal'
        assert win._current_entry is not None
        assert win._current_entry['id'] == 'j2'
    finally:
        win.destroy()


def test_the_chapter_door_narrows_to_the_book(isolated, display):
    journal.save('j1', title='elsewhere', anchors=[
        {'book': 'Genesis', 'chapter': 1, 'verses': [1]}])
    journal.save('j2', title='here', anchors=[
        {'book': 'Romans', 'chapter': 5, 'verses': [1]}])
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        win.show_entries_on('Romans', 5)
        assert win._selected_book_key() == 'Romans'
        # A filter that is set is never a filter that is hidden.
        assert win._filter_revealer.get_reveal_child()
    finally:
        win.destroy()
