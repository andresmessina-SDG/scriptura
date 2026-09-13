"""Tests for journal.py — the entry store. No GTK / SWORD dependency.

An entry is a page, not a longer note: it has an id of its own, a date it is
*about*, and none, one or several anchors. What these hold is that everything
coming off disk is narrowed at the boundary, that a damaged field costs its
own value and nothing else, and that the two acts the editor needs — minting
an id, and writing one — stay separate.
"""

import json
import os

import pytest

import journal


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect JOURNAL_FILE to a temp file and reset the cache."""
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(journal, '_load_failed', False)
    return tmp_path


def _write(path, payload):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(payload if isinstance(payload, str) else json.dumps(payload))


# ── Minting is not writing ───────────────────────────────────────────────────

def test_new_id_writes_nothing(isolated):
    """Opening the editor and closing it again must leave the store exactly
    as it was — so the id is minted without touching disk."""
    journal.new_id()
    journal.new_id()
    assert not os.path.exists(journal.JOURNAL_FILE)
    assert journal.all_entries() == []


def test_ids_are_distinct(isolated):
    assert len({journal.new_id() for _ in range(200)}) == 200


# ── Round-trip ───────────────────────────────────────────────────────────────

def test_an_entry_round_trips(isolated):
    eid = journal.new_id()
    journal.save(eid, date='2026-09-10', title='Trinity VII',
                 body='What came of this reading.',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': [16, 17]}],
                 tags=['love', 'gospel'],
                 plan={'id': 'blended', 'day': 42},
                 collect='anglican:trinity7')
    journal._cache = None            # force a real read back off disk

    entry = journal.get(eid)
    assert entry is not None
    assert entry['id'] == eid
    assert entry['date'] == '2026-09-10'
    assert entry['title'] == 'Trinity VII'
    assert entry['body'] == 'What came of this reading.'
    assert entry['anchors'] == [
        {'book': 'John', 'chapter': 3, 'verses': [16, 17]}]
    assert entry['tags'] == ['love', 'gospel']
    assert entry['plan'] == {'id': 'blended', 'day': 42}
    assert entry['collect'] == 'anglican:trinity7'
    assert entry['created'] and entry['modified']


def test_the_id_is_not_written_into_the_entry(isolated):
    """It is the key it is filed under; stored twice it could disagree."""
    journal.save('e1', title='x')
    raw = json.load(open(journal.JOURNAL_FILE, encoding='utf-8'))
    assert 'id' not in raw['entries']['e1']
    assert raw['version'] == journal.SCHEMA_VERSION


def test_an_entry_with_no_anchors_is_legal(isolated):
    """A sermon, a conversation, a season. Not every reading ends at a
    verse, and a verse-less entry is not an orphan."""
    journal.save('e1', title='A sermon', body='Notes from the pulpit.')
    entry = journal.get('e1')
    assert entry['anchors'] == []


def test_several_anchors_are_normal(isolated):
    """A plan day is three or four passages, and they are one entry."""
    journal.save('e1', anchors=[
        {'book': 'Genesis', 'chapter': 1, 'verses': [1]},
        {'book': 'Psalms', 'chapter': 23, 'verses': []},
        {'book': 'John', 'chapter': 1, 'verses': [1, 2, 3]},
    ])
    assert len(journal.get('e1')['anchors']) == 3


def test_a_whole_chapter_anchor_keeps_its_empty_verse_list(isolated):
    """No verses is not the same as no anchor."""
    journal.save('e1', anchors=[{'book': 'Psalms', 'chapter': 23}])
    assert journal.get('e1')['anchors'] == [
        {'book': 'Psalms', 'chapter': 23, 'verses': []}]


def test_an_absent_date_becomes_today(isolated):
    journal.save('e1', title='x')
    assert journal.get('e1')['date'] == journal.today()


# ── Editing ──────────────────────────────────────────────────────────────────

def test_created_survives_an_edit_and_modified_moves(isolated):
    journal.save('e1', title='first')
    first = journal.get('e1')
    journal.save('e1', title='second')
    second = journal.get('e1')
    assert second['created'] == first['created']
    assert second['modified'] >= first['modified']
    assert second['title'] == 'second'


def test_the_date_is_the_readers_to_correct(isolated):
    """Writing up Sunday on Tuesday is the normal case; an entry whose date
    cannot be fixed is a log, not a journal."""
    journal.save('e1', date='2026-09-08')
    journal.save('e1', date='2026-09-06')
    assert journal.get('e1')['date'] == '2026-09-06'


def test_provenance_is_kept_when_the_editor_passes_none(isolated):
    """`plan` and `collect` are stamped at creation and cannot be recovered
    afterwards, so an ordinary edit must not drop them."""
    journal.save('e1', plan={'id': 'blended', 'day': 42},
                 collect='anglican:trinity7')
    journal.save('e1', title='edited in the ordinary way')
    entry = journal.get('e1')
    assert entry['plan'] == {'id': 'blended', 'day': 42}
    assert entry['collect'] == 'anglican:trinity7'


def test_emptying_the_body_is_an_edit_not_a_delete(isolated):
    journal.save('e1', body='something')
    journal.save('e1', body='')
    assert journal.get('e1') is not None
    assert journal.get('e1')['body'] == ''


# ── Delete and undo ──────────────────────────────────────────────────────────

def test_delete_returns_the_entry_for_undo(isolated):
    journal.save('e1', title='mistake', tags=['x'])
    removed = journal.delete('e1')
    assert removed['title'] == 'mistake'
    assert journal.get('e1') is None


def test_delete_of_nothing_returns_none(isolated):
    assert journal.delete('nope') is None


def test_restore_puts_it_back_unchanged(isolated):
    """Undoing a deletion is not an edit — the timestamps come back as they
    were."""
    journal.save('e1', title='mistake')
    before = journal.get('e1')
    removed = journal.delete('e1')
    assert journal.restore(removed)
    after = journal.get('e1')
    assert after == before


def test_restore_refuses_an_entry_with_no_id(isolated):
    assert journal.restore({'title': 'orphan'}) is False


# ── Tags ─────────────────────────────────────────────────────────────────────

def test_all_tags_is_sorted_and_deduplicated(isolated):
    journal.save('e1', tags=['gospel', 'love'])
    journal.save('e2', tags=['love', 'covenant'])
    assert journal.all_tags() == ['covenant', 'gospel', 'love']


def test_a_tag_repeated_in_one_entry_is_kept_once(isolated):
    journal.save('e1', tags=['love', 'love', ''])
    assert journal.get('e1')['tags'] == ['love']


# ── Narrowing: a damaged field costs its own value and nothing else ─────────

def test_a_bad_anchor_is_dropped_and_the_words_are_kept(isolated):
    _write(journal.JOURNAL_FILE, {'version': 1, 'entries': {'e1': {
        'title': 'kept', 'body': 'also kept',
        'anchors': [
            {'book': 'John', 'chapter': 3, 'verses': [16]},
            {'book': 'John'},                       # no chapter
            {'chapter': 3},                         # no book
            'not an anchor at all',
            {'book': 'John', 'chapter': '3'},       # chapter not an int
        ]}}})
    entry = journal.get('e1')
    assert entry['title'] == 'kept'
    assert entry['body'] == 'also kept'
    assert entry['anchors'] == [
        {'book': 'John', 'chapter': 3, 'verses': [16]}]


def test_junk_in_a_verse_list_is_dropped(isolated):
    _write(journal.JOURNAL_FILE, {'version': 1, 'entries': {'e1': {
        'anchors': [{'book': 'John', 'chapter': 3,
                     'verses': [16, 'x', None, 17, True]}]}}})
    assert journal.get('e1')['anchors'][0]['verses'] == [16, 17]


def test_a_bad_plan_stamp_becomes_none(isolated):
    for bad in ({'id': 'blended'}, {'day': 3}, {'id': 5, 'day': 3},
                {'id': 'blended', 'day': 'three'}, 'nonsense'):
        _write(journal.JOURNAL_FILE,
               {'version': 1, 'entries': {'e1': {'plan': bad}}})
        journal._cache = None
        assert journal.get('e1')['plan'] is None, bad


def test_an_entry_that_is_not_an_object_is_skipped(isolated):
    _write(journal.JOURNAL_FILE, {'version': 1, 'entries': {
        'e1': 'not an entry', 'e2': {'title': 'real'}}})
    entries = journal.all_entries()
    assert [e['title'] for e in entries] == ['real']


def test_a_non_dict_entries_section_becomes_empty(isolated):
    _write(journal.JOURNAL_FILE, {'version': 1, 'entries': ['nope']})
    assert journal.all_entries() == []
    assert not journal.load_failed()   # readable, just empty — not corrupt


# ── Corruption ───────────────────────────────────────────────────────────────

def test_an_unparseable_file_is_quarantined_not_overwritten(isolated):
    """Every store here loads into a cache and later writes that cache back,
    so without the quarantine the first save after a bad read destroys the
    only copy of what the reader wrote."""
    _write(journal.JOURNAL_FILE, '{ this is not json')
    assert journal.all_entries() == []
    assert journal.load_failed()
    assert os.path.exists(journal.JOURNAL_FILE + '.corrupt')

    journal.save('e1', title='after the corruption')
    kept = open(journal.JOURNAL_FILE + '.corrupt', encoding='utf-8').read()
    assert kept == '{ this is not json'


def test_a_json_array_is_treated_as_corrupt(isolated):
    _write(journal.JOURNAL_FILE, ['not', 'an', 'object'])
    assert journal.all_entries() == []
    assert journal.load_failed()
    assert os.path.exists(journal.JOURNAL_FILE + '.corrupt')


def test_an_unreadable_file_is_left_alone(isolated):
    """An OSError says nothing about the bytes — they may be perfectly
    good — so the file must not be moved aside."""
    _write(journal.JOURNAL_FILE, {'version': 1, 'entries': {}})
    os.chmod(journal.JOURNAL_FILE, 0o000)
    try:
        if os.access(journal.JOURNAL_FILE, os.R_OK):
            pytest.skip('running as a user that can read anything')
        assert journal.all_entries() == []
        assert journal.load_failed()
        assert not os.path.exists(journal.JOURNAL_FILE + '.corrupt')
    finally:
        os.chmod(journal.JOURNAL_FILE, 0o600)


# ── Writing to a place that cannot be written ───────────────────────────────

def test_a_failed_write_says_so_and_still_shows_in_the_app(isolated,
                                                           monkeypatch):
    monkeypatch.setattr(journal, 'JOURNAL_FILE',
                        str(isolated / 'no-such-dir' / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    assert journal.save('e1', title='typed but not landed') is False
    # The running app must reflect what the reader just wrote, even though
    # the file behind it is stale.
    assert journal.get('e1')['title'] == 'typed but not landed'


def test_a_run_of_failed_writes_is_reported_once(isolated, monkeypatch):
    reports = []
    previous = journal._on_save_error
    monkeypatch.setattr(journal, 'JOURNAL_FILE',
                        str(isolated / 'no-such-dir' / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    journal.set_save_error_handler(lambda: reports.append(1))
    try:
        for n in range(5):
            journal.save(f'e{n}', title='x')
        assert reports == [1]
    finally:
        journal._on_save_error = previous


# ── Backup surface ───────────────────────────────────────────────────────────

def test_replace_all_swaps_the_whole_store(isolated):
    journal.save('e1', title='before')
    assert journal.replace_all({'version': 1, 'entries': {
        'e2': {'title': 'after'}}})
    assert [e['id'] for e in journal.all_entries()] == ['e2']


def test_replace_all_with_nothing_empties_the_store(isolated):
    """A restore from a backup that carried no journal at all: the file's
    state is the truth, which is how the other three restore too."""
    journal.save('e1', title='before')
    assert journal.replace_all({})
    assert journal.all_entries() == []


def test_export_raw_is_the_on_disk_shape(isolated):
    journal.save('e1', title='x')
    raw = journal.export_raw()
    assert raw['version'] == journal.SCHEMA_VERSION
    assert 'e1' in raw['entries']
    json.dumps(raw)     # must survive the backup document
