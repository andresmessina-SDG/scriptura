"""Tests for backup.py — one-file study-data export/restore across the
annotations, journal, sermons, bookmarks, and reading-plan stores. No GTK /
SWORD dependency."""

import datetime
import json
import pytest

import annotations
import backup
import bookmarks
import journal
import reading_plans
import sermons


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect all five stores to temp files and reset module caches."""
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 'sermons.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    monkeypatch.setattr(bookmarks, '_FILE', str(tmp_path / 'bookmarks.json'))
    monkeypatch.setattr(reading_plans, '_FILE',
                        str(tmp_path / 'reading_plans.json'))
    monkeypatch.setattr(reading_plans, '_cache', None)
    return tmp_path


def _populate():
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    annotations.save_note('KJVA', 'John', 3, 16, 'God so loved')
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'shepherd psalm')
    journal.save('e1', date='2026-09-10', title='Trinity VII',
                 body='What came of this reading.',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': [16]}])
    sermons.save('s1', title='The Sower Went Forth',
                 idea='The seed is never the problem; the soil is.',
                 body='## I. The seed that is scattered',
                 anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []}],
                 series={'name': 'Parables of the Kingdom', 'part': 3},
                 preached=['2026-02-08'])
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
    assert doc['annotations']['Genesis/1']['1']['highlight'] == '#ffff00'
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


def test_restore_reports_a_store_that_could_not_be_written(isolated):
    # Point the annotations store at a path that cannot be written: the
    # write fails, the in-memory cache still shows the restored data, and
    # restore() must be the thing that says so.
    unwritable = isolated / 'nodir' / 'annotations.json'
    annotations.ANNOTATIONS_FILE = str(unwritable)
    doc = backup.validate({'format': backup.FORMAT, 'version': 1,
                           'annotations': {'KJVA/John/3': {'notes': {}}},
                           'bookmarks': [], 'reading_plans': {}})
    assert backup.restore(doc) == ['annotations']
    assert not unwritable.exists()


def test_restore_reports_nothing_when_all_stores_write(isolated):
    doc = backup.validate(backup.collect())
    assert backup.restore(doc) == []


def test_counts(isolated):
    _populate()
    c = backup.counts(backup.collect())
    # Gen 1:1 highlight + John 3:16 note + Psalms 23 chapter note
    assert c == {'annotations': 3, 'journal': 1, 'sermons': 1,
                 'bookmarks': 2, 'plan_days': 2}


def test_validate_rejects_damaged_plan_inner_shapes(isolated):
    for plans in ({'start_dates': []},
                  {'completed': 'oops'},
                  {'completed': {'canonical': 'abc'}}):
        doc = {'format': backup.FORMAT, 'version': 1,
               'annotations': {}, 'bookmarks': [], 'reading_plans': plans}
        with pytest.raises(ValueError):
            backup.validate(doc)


# ── Version 2: the journal joined the bundle ────────────────────────────────

def test_a_v1_file_restores_with_an_empty_journal(isolated):
    """A backup written before the journal existed is not damaged — it is a
    backup from a Scriptura that had none, and the file's state is the truth
    the other three sections restore by too."""
    _populate()
    doc = {'format': backup.FORMAT, 'version': 1, 'exported': '2026-01-01',
           'annotations': {}, 'bookmarks': [], 'reading_plans': {}}
    assert backup.validate(doc) is doc
    assert backup.counts(doc)['journal'] == 0
    assert backup.restore(doc) == []
    assert journal.all_entries() == []


def test_a_v2_file_round_trips_the_journal(isolated):
    _populate()
    doc = json.loads(json.dumps(backup.collect()))
    journal.replace_all({})
    assert journal.all_entries() == []

    assert backup.restore(backup.validate(doc)) == []
    entries = journal.all_entries()
    assert len(entries) == 1
    assert entries[0]['title'] == 'Trinity VII'
    assert entries[0]['anchors'] == [
        {'book': 'John', 'chapter': 3, 'verses': [16]}]


def test_a_newer_file_is_refused_rather_than_half_read(isolated):
    """The whole point of the version bump: an older Scriptura must decline
    a newer file instead of silently dropping the sections it cannot see."""
    doc = {'format': backup.FORMAT, 'version': backup.VERSION + 1,
           'annotations': {}, 'journal': {}, 'bookmarks': [],
           'reading_plans': {}}
    with pytest.raises(ValueError):
        backup.validate(doc)


def test_a_damaged_journal_section_is_refused(isolated):
    doc = {'format': backup.FORMAT, 'version': 2, 'annotations': {},
           'journal': [], 'bookmarks': [], 'reading_plans': {}}
    with pytest.raises(ValueError):
        backup.validate(doc)


# ── Version 3: the sermons joined the bundle ────────────────────────────────

def test_a_v2_file_restores_with_no_sermons(isolated):
    """The same rule the journal arrived under: a backup written before
    sermons existed is not damaged, it is a backup from a Scriptura that had
    none."""
    _populate()
    doc = {'format': backup.FORMAT, 'version': 2, 'exported': '2026-01-01',
           'annotations': {}, 'journal': {}, 'bookmarks': [],
           'reading_plans': {}}
    assert backup.validate(doc) is doc
    assert backup.counts(doc)['sermons'] == 0
    assert backup.restore(doc) == []
    assert sermons.all_sermons() == []


def test_a_v3_file_round_trips_a_sermon(isolated):
    _populate()
    doc = json.loads(json.dumps(backup.collect()))
    sermons.replace_all({})
    assert sermons.all_sermons() == []

    assert backup.restore(backup.validate(doc)) == []
    restored = sermons.all_sermons()
    assert len(restored) == 1
    assert restored[0]['title'] == 'The Sower Went Forth'
    assert restored[0]['series'] == {'name': 'Parables of the Kingdom',
                                     'part': 3}
    assert restored[0]['preached'] == ['2026-02-08']


def test_a_damaged_sermons_section_is_refused(isolated):
    doc = {'format': backup.FORMAT, 'version': 3, 'annotations': {},
           'journal': {}, 'sermons': [], 'bookmarks': [], 'reading_plans': {}}
    with pytest.raises(ValueError):
        backup.validate(doc)


# ── daily copies ─────────────────────────────────────────────────────────────

def _day(n):
    return datetime.date(2026, 9, 1) + datetime.timedelta(days=n)


def test_daily_copy_restores_like_a_backup(isolated):
    _populate()
    folder = isolated / 'backups'
    folder.mkdir()
    path = backup.daily_copy(str(folder), _day(0))
    with open(path, encoding='utf-8') as f:
        doc = backup.validate(json.load(f))
    assert doc['exported'] == '2026-09-01'
    assert backup.counts(doc)['sermons'] == 1


def test_daily_copy_writes_once_a_day(isolated):
    folder = isolated / 'backups'
    folder.mkdir()
    assert backup.daily_copy(str(folder), _day(0)) is not None
    bookmarks.add('John', 1)
    # A second launch the same day keeps the morning's copy.
    assert backup.daily_copy(str(folder), _day(0)) is None
    with open(backup.newest_daily_copy(str(folder)), encoding='utf-8') as f:
        assert json.load(f)['bookmarks'] == []


def test_daily_copy_keeps_the_newest(isolated):
    folder = isolated / 'backups'
    folder.mkdir()
    (folder / 'notes.txt').write_text('not ours')
    for n in range(backup.DAILY_KEEP + 3):
        backup.daily_copy(str(folder), _day(n))
    names = sorted(p.name for p in folder.iterdir())
    assert 'notes.txt' in names
    copies = [n for n in names if n.endswith('.json')]
    assert len(copies) == backup.DAILY_KEEP
    assert copies[0] == f'scriptura-study-data-{_day(3).isoformat()}.json'
    assert backup.newest_daily_copy(str(folder)).endswith(
        f'{_day(backup.DAILY_KEEP + 2).isoformat()}.json')


def test_daily_copy_never_raises(isolated):
    assert backup.daily_copy(str(isolated / 'missing'), _day(0)) is None


def test_a_failed_copy_leaves_nothing_behind(isolated, monkeypatch):
    """A full disk stopped the write halfway. The half-written `.tmp` sat in
    the folder the Restore dialog opens on, and no pruning ever touched it:
    `_daily_copies` only counts `.json`."""
    folder = isolated / 'backups'
    folder.mkdir()

    def full_disk(*_args, **_kwargs):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(backup.json, 'dump', full_disk)
    assert backup.daily_copy(str(folder), _day(0)) is None
    assert backup.newest_daily_copy(str(folder)) is None
    assert sorted(p.name for p in folder.iterdir()) == []
