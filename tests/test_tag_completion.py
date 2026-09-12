"""Suggesting the tags already in use.

Tags are one vocabulary across marks and entries, and a free-text field is
how one vocabulary quietly becomes three — prayer, prayers, Prayer. The tag
manager renames them afterwards; this is what stops them being made.
"""
import pytest

import annotations
import annotations_window
import journal


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


def _win():
    return annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)


def test_both_stores_feed_one_vocabulary(isolated, display):
    annotations.save_note(None, 'John', 3, 16, 'a mark')
    annotations.save_tags(None, 'John', 3, 16, ['covenant'])
    journal.save('j1', title='x', tags=['prayer'])
    win = _win()
    try:
        vocab = win._entry_editor._tag_vocabulary()
        assert 'covenant' in vocab and 'prayer' in vocab
    finally:
        win.destroy()


def test_the_fragment_being_typed_is_what_is_matched(isolated, display):
    journal.save('j1', title='x', tags=['prayer', 'providence'])
    win = _win()
    try:
        ed = win._entry_editor
        assert ed._tag_suggestions('faith, pra') == ['prayer']
        assert ed._tag_suggestions('pr') == ['prayer', 'providence']
    finally:
        win.destroy()


def test_a_tag_already_in_the_field_is_not_offered_again(isolated, display):
    journal.save('j1', title='x', tags=['prayer'])
    win = _win()
    try:
        assert win._entry_editor._tag_suggestions('prayer, pray') == []
    finally:
        win.destroy()


def test_an_exact_match_stops_suggesting_itself(isolated, display):
    """Nothing to offer once the word is spelled — the popover must go
    away rather than sit over the field repeating it back."""
    journal.save('j1', title='x', tags=['prayer'])
    win = _win()
    try:
        assert win._entry_editor._tag_suggestions('prayer') == []
    finally:
        win.destroy()


def test_a_fragment_inside_a_word_still_finds_it(isolated, display):
    journal.save('j1', title='x', tags=['prayer'])
    win = _win()
    try:
        assert win._entry_editor._tag_suggestions('yer') == ['prayer']
    finally:
        win.destroy()


def test_nothing_is_suggested_for_an_empty_fragment(isolated, display):
    journal.save('j1', title='x', tags=['prayer'])
    win = _win()
    try:
        ed = win._entry_editor
        assert ed._tag_suggestions('') == []
        assert ed._tag_suggestions('prayer, ') == []
    finally:
        win.destroy()


def test_accepting_a_tag_replaces_the_fragment(isolated, display):
    journal.save('j1', title='x', tags=['prayer'])
    win = _win()
    try:
        ed = win._entry_editor
        ed.tags.set_text('faith, pra')
        ed._accept_tag('prayer')
        assert ed.tags.get_text() == 'faith, prayer, '
    finally:
        win.destroy()


def test_the_mark_editor_completes_too(isolated, display):
    """One vocabulary means one behaviour on both pages."""
    journal.save('j1', title='x', tags=['covenant'])
    win = _win()
    try:
        assert win._mark_editor._tag_suggestions('cov') == ['covenant']
    finally:
        win.destroy()
