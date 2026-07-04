"""Tests for backup.py — one-file study-data export/restore across the
annotations, bookmarks, and reading-plan stores. No GTK / SWORD dependency."""

import json
import pytest

import annotations
import backup
import bookmarks
import reading_plans


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect all three stores to temp files and reset module caches."""
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(bookmarks, '_FILE', str(tmp_path / 'bookmarks.json'))
    monkeypatch.setattr(reading_plans, '_FILE',
                        str(tmp_path / 'reading_plans.json'))
    monkeypatch.setattr(reading_plans, '_cache', None)
    return tmp_path


def _populate():
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    annotations.save_note('KJVA', 'John', 3, 16, 'God so loved')
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'shepherd psalm')
    bookmarks.add('John', 3, 16)
    bookmarks.add('Genesis', 1)
    reading_plans.set_start_date('canonical', '2026-01-01')
    reading_plans.set_day_done('canonical', 0, True)
    reading_plans.set_day_done('canonical', 1, True)


# ── collect ──────────────────────────────────────────────────────────────────

def test_collect_document_shape(isolated):
    _populate()
    doc = backup.collect()
    assert doc['format'] == backup.FORMAT
    assert doc['version'] == backup.VERSION
    assert doc['annotations']['KJVA/Genesis/1']['1']['highlight'] == '#ffff00'
    assert len(doc['bookmarks']) == 2
    assert doc['reading_plans']['completed']['canonical'] == [0, 1]


def test_collect_is_json_serialisable(isolated):
    _populate()
    json.dumps(backup.collect())


# ── validate ─────────────────────────────────────────────────────────────────

def test_validate_accepts_own_output(isolated):
    _populate()
    doc = json.loads(json.dumps(backup.collect()))
    assert backup.validate(doc) is doc


def test_validate_rejects_foreign_json(isolated):
    with pytest.raises(ValueError):
        backup.validate({'some': 'json'})
    with pytest.raises(ValueError):
        backup.validate(['not', 'a', 'dict'])


def test_validate_rejects_newer_version(isolated):
    doc = backup.collect()
    doc['version'] = backup.VERSION + 1
    with pytest.raises(ValueError):
        backup.validate(doc)


def test_validate_rejects_damaged_sections(isolated):
    doc = backup.collect()
    doc['bookmarks'] = 'oops'
    with pytest.raises(ValueError):
        backup.validate(doc)


# ── restore ──────────────────────────────────────────────────────────────────

def test_round_trip_restores_everything(isolated):
    _populate()
    doc = json.loads(json.dumps(backup.collect()))

    # Wipe all three stores, then restore from the document.
    annotations.replace_all({})
    bookmarks.replace_all([])
    reading_plans.replace_all({})
    assert annotations.get_annotations('KJVA', 'Genesis', 1) == {}

    backup.restore(doc)
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['highlight'] == '#ffff00'
    assert annotations.get_chapter_note('KJVA', 'Psalms', 23) == 'shepherd psalm'
    assert [b['book'] for b in bookmarks.get_all()] == ['Genesis', 'John']
    assert reading_plans.get_completed('canonical') == {0, 1}
    assert reading_plans.get_active() == ('canonical', '2026-01-01')


def test_restore_replaces_not_merges(isolated):
    annotations.save_note('KJVA', 'John', 3, 16, 'keep me?')
    bookmarks.add('John', 3, 16)
    doc = {'format': backup.FORMAT, 'version': 1,
           'annotations': {}, 'bookmarks': [], 'reading_plans': {}}
    backup.restore(backup.validate(doc))
    assert annotations.get_annotations('KJVA', 'John', 3) == {}
    assert bookmarks.get_all() == []


def test_restore_missing_sections_treated_empty(isolated):
    _populate()
    backup.restore(backup.validate({'format': backup.FORMAT, 'version': 1}))
    assert bookmarks.get_all() == []


def test_counts(isolated):
    _populate()
    c = backup.counts(backup.collect())
    # Gen 1:1 highlight + John 3:16 note + Psalms 23 chapter note
    assert c == {'annotations': 3, 'bookmarks': 2, 'plan_days': 2}


def test_validate_rejects_damaged_plan_inner_shapes(isolated):
    for plans in ({'start_dates': []},
                  {'completed': 'oops'},
                  {'completed': {'canonical': 'abc'}}):
        doc = {'format': backup.FORMAT, 'version': 1,
               'annotations': {}, 'bookmarks': [], 'reading_plans': plans}
        with pytest.raises(ValueError):
            backup.validate(doc)
