"""Tests for bookmarks.py — JSON-backed bookmark list with malformed-entry
filtering. Pure-Python; no GTK / SWORD."""

import json

import pytest

import bookmarks


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect _FILE to a temp location and reset module-level state."""
    monkeypatch.setattr(bookmarks, '_FILE', str(tmp_path / 'bookmarks.json'))
    monkeypatch.setattr(bookmarks, '_load_failed', False)
    return tmp_path


# ── Empty / no-file behaviour ────────────────────────────────────────────────

def test_get_all_with_no_file_returns_empty(isolated):
    assert bookmarks.get_all() == []


def test_load_failed_is_false_when_no_file(isolated):
    bookmarks.get_all()
    assert bookmarks.load_failed() is False


# ── Add / round-trip ────────────────────────────────────────────────────────

def test_add_chapter_bookmark(isolated):
    added = bookmarks.add('Genesis', 1)
    assert added is True
    data = bookmarks.get_all()
    assert len(data) == 1
    assert data[0]['book'] == 'Genesis'
    assert data[0]['chapter'] == 1
    assert data[0]['verse'] is None
    assert data[0]['label'] == 'Genesis 1'


def test_add_verse_bookmark_includes_verse_in_label(isolated):
    bookmarks.add('John', 3, 16)
    bm = bookmarks.get_all()[0]
    assert bm['verse'] == 16
    assert bm['label'] == 'John 3:16'


def test_add_is_most_recent_first(isolated):
    bookmarks.add('Genesis', 1)
    bookmarks.add('Exodus', 1)
    bookmarks.add('Leviticus', 1)
    books = [b['book'] for b in bookmarks.get_all()]
    assert books == ['Leviticus', 'Exodus', 'Genesis']


def test_add_duplicate_returns_false_and_does_not_insert(isolated):
    assert bookmarks.add('John', 3, 16) is True
    assert bookmarks.add('John', 3, 16) is False
    assert len(bookmarks.get_all()) == 1


def test_chapter_and_verse_bookmark_are_distinct(isolated):
    """A whole-chapter bookmark and a verse bookmark for the same chapter
    are different entries (verse=None vs verse=16)."""
    bookmarks.add('John', 3)
    bookmarks.add('John', 3, 16)
    assert len(bookmarks.get_all()) == 2


# ── Remove ───────────────────────────────────────────────────────────────────

def test_remove_by_index(isolated):
    bookmarks.add('Genesis', 1)
    bookmarks.add('Exodus', 1)
    bookmarks.remove(0)  # remove most-recent (Exodus)
    remaining = [b['book'] for b in bookmarks.get_all()]
    assert remaining == ['Genesis']


def test_remove_out_of_range_is_noop(isolated):
    bookmarks.add('Genesis', 1)
    bookmarks.remove(5)
    bookmarks.remove(-1)
    assert len(bookmarks.get_all()) == 1


# ── Persistence: written file is reloadable ──────────────────────────────────

def test_save_writes_json_to_disk(isolated):
    bookmarks.add('John', 3, 16)
    content = json.loads((isolated / 'bookmarks.json').read_text())
    assert content[0]['book'] == 'John'
    assert content[0]['verse'] == 16


def test_get_all_reads_from_disk(isolated):
    # Hand-write a file; bookmarks.py should pick it up.
    (isolated / 'bookmarks.json').write_text(
        json.dumps([{'book': 'Psalms', 'chapter': 23,
                     'verse': None, 'label': 'Psalms 23'}]))
    data = bookmarks.get_all()
    assert len(data) == 1
    assert data[0]['book'] == 'Psalms'


def test_atomic_write_does_not_leave_tmp_file(isolated):
    bookmarks.add('Genesis', 1)
    # The .tmp suffix from the atomic write should be gone.
    assert not (isolated / 'bookmarks.json.tmp').exists()


# ── Malformed-entry filtering ────────────────────────────────────────────────

def test_load_drops_entries_missing_book_or_chapter(isolated):
    (isolated / 'bookmarks.json').write_text(json.dumps([
        {'book': 'Genesis', 'chapter': 1, 'verse': None, 'label': 'OK'},
        {'book': 'Genesis'},                         # missing chapter
        {'chapter': 1},                              # missing book
        'not-a-dict',                                # wrong type
        {'book': 'John', 'chapter': 3, 'label': 'John 3'},  # OK (verse optional)
    ]))
    result = bookmarks.get_all()
    assert len(result) == 2
    assert {e['book'] for e in result} == {'Genesis', 'John'}


def test_corrupt_json_falls_back_to_empty(isolated):
    (isolated / 'bookmarks.json').write_text('this is not json at all')
    assert bookmarks.get_all() == []


def test_corrupt_json_sets_load_failed_flag(isolated):
    (isolated / 'bookmarks.json').write_text('{ broken')
    bookmarks.get_all()
    assert bookmarks.load_failed() is True


def test_valid_file_does_not_set_load_failed(isolated):
    (isolated / 'bookmarks.json').write_text(json.dumps([
        {'book': 'Genesis', 'chapter': 1, 'verse': None, 'label': 'Genesis 1'}
    ]))
    bookmarks.get_all()
    assert bookmarks.load_failed() is False


def test_load_failed_attempts_load_before_reading_flag(isolated):
    """load_failed() should trigger _load() if it hasn't run yet — the
    flag is meaningless without an actual load attempt."""
    (isolated / 'bookmarks.json').write_text('garbage')
    # Don't call get_all() first; load_failed() must do it.
    assert bookmarks.load_failed() is True


# ── UTF-8 preservation ──────────────────────────────────────────────────────

def test_save_preserves_non_ascii_labels(isolated, monkeypatch):
    """Labels currently come from book + chapter (ASCII), but the writer
    is configured ensure_ascii=False — verify by injecting via add()
    using a non-ASCII book name."""
    bookmarks.add('Génesis', 1)
    content = (isolated / 'bookmarks.json').read_text(encoding='utf-8')
    assert 'Génesis' in content


# ── Remove returns the entry; restore undoes it ─────────────────────────────

def test_remove_returns_entry_and_restore_reinserts(isolated):
    bookmarks.add('John', 3, 16)
    bookmarks.add('Genesis', 1)   # list is now [Genesis, John]
    removed = bookmarks.remove(0)
    assert removed['book'] == 'Genesis'
    assert [b['book'] for b in bookmarks.get_all()] == ['John']

    bookmarks.restore(0, removed)
    assert [b['book'] for b in bookmarks.get_all()] == ['Genesis', 'John']


def test_remove_stale_index_returns_none(isolated):
    assert bookmarks.remove(5) is None


def test_restore_clamps_index(isolated):
    bookmarks.add('John', 3, 16)
    bookmarks.restore(99, {'book': 'Genesis', 'chapter': 1,
                           'verse': None, 'label': 'Genesis 1'})
    assert [b['book'] for b in bookmarks.get_all()] == ['John', 'Genesis']
