"""Adding, dropping and correcting an entry's passages.

Anchors used to be fixed at whichever door made the entry — Today, the verse
menu, Ctrl+Shift+J — so a sermon that turned out to be about Romans 5 could
not say so, and a wrongly anchored entry could only be deleted. These hold
the editing path, and the two things that have to move with it: the row the
sidebar sorts by, and the file.
"""
import pytest

import annotations
import annotations_window
import journal
import journal_markup


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
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(journal, '_load_failed', False)
    return tmp_path


def _open_on(entry_id):
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    win.set_mode('journal')
    row = win._list.get_first_child()
    while row is not None and not getattr(row, '_entry', None):
        row = row.get_next_sibling()
    win._list.select_row(row)
    return win


def _anchors(win):
    return win._entry_editor.row.get('anchors') or []


# ── The parser the field uses ────────────────────────────────────────────────

def test_parse_anchor_takes_what_the_body_links_take():
    names = {'John': 'John', 'Juan': 'John'}
    assert journal_markup.parse_anchor('Juan 3:16', names) == {
        'book': 'John', 'chapter': 3, 'verses': [16]}


def test_parse_anchor_reads_a_whole_chapter():
    assert journal_markup.parse_anchor('John 3', {'John': 'John'}) == {
        'book': 'John', 'chapter': 3, 'verses': []}


def test_parse_anchor_reads_a_range():
    """An anchor is the one thing in the feature that holds a span of
    verses, which is why the range is parsed here and not in the link
    matcher every caller unpacks."""
    got = journal_markup.parse_anchor('John 3:16-18', {'John': 'John'})
    assert got['verses'] == [16, 17, 18]


def test_parse_anchor_refuses_prose():
    assert journal_markup.parse_anchor('about grace', {'John': 'John'}) is None


# ── The editor ───────────────────────────────────────────────────────────────

def test_a_passage_can_be_added_to_an_entry_that_had_none(isolated, display):
    journal.save('j1', title='A sermon')
    win = _open_on('j1')
    try:
        ed = win._entry_editor
        ed._anchor_entry.set_text('Romans 5:1')
        ed._on_add_anchor(None)
        assert _anchors(win) == [
            {'book': 'Romans', 'chapter': 5, 'verses': [1]}]
        win._autosave.flush()
        assert journal.get('j1')['anchors'][0]['book'] == 'Romans'
    finally:
        win.destroy()


def test_the_row_follows_the_first_anchor(isolated, display):
    """The sidebar sorts and groups by the row's own place, so a row still
    claiming the old passage would sit in the wrong part of the canon."""
    journal.save('j1', title='A sermon')
    win = _open_on('j1')
    try:
        ed = win._entry_editor
        ed._anchor_entry.set_text('Romans 5:1')
        ed._on_add_anchor(None)
        assert ed.row['book'] == 'Romans'
        assert ed.row['chapter'] == 5
        assert ed.row['app_verse'] == 1
    finally:
        win.destroy()


def test_a_passage_can_be_taken_off(isolated, display):
    journal.save('j1', title='x', anchors=[
        {'book': 'John', 'chapter': 3, 'verses': [16]},
        {'book': 'Romans', 'chapter': 5, 'verses': []}])
    win = _open_on('j1')
    try:
        win._entry_editor._on_drop_anchor(None, 0)
        assert [a['book'] for a in _anchors(win)] == ['Romans']
        win._autosave.flush()
        assert [a['book'] for a in journal.get('j1')['anchors']] == ['Romans']
    finally:
        win.destroy()


def test_the_same_passage_is_not_added_twice(isolated, display):
    journal.save('j1', title='x', anchors=[
        {'book': 'John', 'chapter': 3, 'verses': [16]}])
    win = _open_on('j1')
    try:
        ed = win._entry_editor
        ed._anchor_entry.set_text('John 3:16')
        ed._on_add_anchor(None)
        assert len(_anchors(win)) == 1
    finally:
        win.destroy()


def test_prose_in_the_field_marks_it_and_adds_nothing(isolated, display):
    journal.save('j1', title='x')
    win = _open_on('j1')
    try:
        ed = win._entry_editor
        ed._anchor_entry.set_text('about grace')
        ed._on_add_anchor(None)
        assert _anchors(win) == []
        assert 'error' in ed._anchor_entry.get_css_classes()
    finally:
        win.destroy()


def test_the_add_chip_is_offered_on_an_entry_with_no_passage(isolated,
                                                             display):
    """The entry most likely to want a passage later is the one that has
    none, so the row cannot hide when it is empty."""
    journal.save('j1', title='x')
    win = _open_on('j1')
    try:
        ed = win._entry_editor
        assert ed._anchor_box.get_visible()
        assert ed._anchor_box.get_first_child() is not None
    finally:
        win.destroy()
