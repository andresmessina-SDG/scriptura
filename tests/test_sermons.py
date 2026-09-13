"""Tests for sermons.py — the manuscript store. No GTK / SWORD dependency.

Scoped to what makes this store different from the journal's: there is no
`date`, `preached` is a list that may stay empty, `series.part` is nullable,
`append` merges an anchor, and `most_recent` is what a collecting door adds
to.
"""

import json
import pytest

import sermons


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 'sermons.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    monkeypatch.setattr(sermons, '_load_failed', False)
    return tmp_path / 'sermons.json'


def _sower(sermon_id='s1', **kw):
    fields = dict(
        title='The Sower Went Forth',
        idea='The seed is never the problem; the soil is.',
        body='## I. The seed that is scattered',
        anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []}],
        series={'name': 'Parables of the Kingdom', 'part': 3},
        tags=['parables', 'kingdom'],
    )
    fields.update(kw)
    sermons.save(sermon_id, **fields)
    return sermons.get(sermon_id)


# ── Minting and writing ─────────────────────────────────────────────────────

def test_new_id_writes_nothing(store):
    """Opening the editor and closing it must leave the file untouched —
    minting an id and filing a sermon under it are two separate acts."""
    sermons.new_id()
    assert not store.exists()


def test_new_ids_are_distinct(store):
    assert sermons.new_id() != sermons.new_id()


def test_save_round_trips_every_field(store):
    saved = _sower(preached=['2026-02-08'], collect='anglican:sexagesima')
    assert saved['title'] == 'The Sower Went Forth'
    assert saved['idea'].startswith('The seed is never')
    assert saved['series'] == {'name': 'Parables of the Kingdom', 'part': 3}
    assert saved['preached'] == ['2026-02-08']
    assert saved['collect'] == 'anglican:sexagesima'
    assert saved['tags'] == ['parables', 'kingdom']
    assert saved['created'] and saved['modified']


def test_the_id_is_not_written_into_the_record(store):
    """Stored twice it could disagree; `_sermon` folds it back in on read."""
    _sower()
    raw = json.loads(store.read_text(encoding='utf-8'))
    assert 'id' not in raw['sermons']['s1']
    assert sermons.get('s1')['id'] == 's1'


def test_there_is_no_date_field(store):
    """A sermon has a writing span and a preaching day, and the journal's
    'the day this is about' is neither."""
    assert 'date' not in _sower()


def test_created_survives_a_rewrite_and_modified_moves(store):
    first = _sower()
    sermons.save('s1', title='The Sower Went Forth', body='longer now')
    second = sermons.get('s1')
    assert second['created'] == first['created']
    assert second['modified'] >= first['modified']


def test_collect_survives_an_edit_that_passes_none(store):
    """Provenance is stamped at creation and cannot be recovered later, so
    an ordinary title edit must not drop which Sunday it was begun for."""
    _sower(collect='anglican:sexagesima')
    sermons.save('s1', title='Retitled')
    assert sermons.get('s1')['collect'] == 'anglican:sexagesima'


def test_series_and_preached_are_the_readers_to_clear(store):
    """Unlike collect: passing them explicitly is how they are emptied, and
    the editor passes them on every write."""
    _sower(preached=['2026-02-08'])
    sermons.save('s1', title='The Sower Went Forth', series=None, preached=[])
    assert sermons.get('s1')['series'] is None
    assert sermons.get('s1')['preached'] == []


# ── Narrowing ───────────────────────────────────────────────────────────────

def test_a_sermon_may_never_be_preached(store):
    assert _sower()['preached'] == []


def test_preached_dates_are_sorted_and_deduped(store):
    """A date added months later is usually an older one being remembered."""
    saved = _sower(preached=['2026-02-08', '2024-03-03', '2026-02-08'])
    assert saved['preached'] == ['2024-03-03', '2026-02-08']


def test_a_series_part_may_be_unknown(store):
    """'Part 3 of ?' has to be sayable."""
    saved = _sower(series={'name': 'Parables of the Kingdom'})
    assert saved['series'] == {'name': 'Parables of the Kingdom', 'part': None}


def test_a_series_with_no_name_is_no_series(store):
    assert _sower(series={'part': 2})['series'] is None
    assert _sower('s2', series={'name': '   '})['series'] is None


def test_a_damaged_anchor_costs_that_anchor_and_not_the_words(store):
    saved = _sower(anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []},
                            {'book': '', 'chapter': 1},
                            'not an anchor'])
    assert saved['anchors'] == [{'book': 'Matthew', 'chapter': 13,
                                 'verses': []}]
    assert saved['body'].startswith('## I.')


def test_an_anchor_with_no_verses_is_the_whole_chapter(store):
    """Which is not the same as no anchor at all."""
    saved = _sower(anchors=[{'book': 'Matthew', 'chapter': 13}])
    assert saved['anchors'] == [{'book': 'Matthew', 'chapter': 13,
                                 'verses': []}]


def test_a_file_that_will_not_parse_is_quarantined_not_overwritten(store):
    store.write_text('{ this is not json', encoding='utf-8')
    sermons._cache = None
    assert sermons.all_sermons() == []
    assert sermons.load_failed()


# ── Reading ─────────────────────────────────────────────────────────────────

def test_sermons_on_finds_every_anchor_not_only_the_first(store):
    _sower(anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []},
                    {'book': 'Isaiah', 'chapter': 55, 'verses': [10, 11]}])
    assert len(sermons.sermons_on('Isaiah', 55)) == 1
    assert sermons.sermons_on('Isaiah', 54) == []


def test_a_write_refiles_the_sermon_at_the_end_of_the_store(store):
    _sower()
    _sower('s2', title='The Least of All Seeds')
    assert [s['id'] for s in sermons.all_sermons()] == ['s1', 's2']
    sermons.save('s1', title='The Sower Went Forth', body='worked on again')
    assert [s['id'] for s in sermons.all_sermons()] == ['s2', 's1']


def test_all_series_lists_each_name_once(store):
    _sower()
    _sower('s2', title='A Man Sowed Good Seed',
           series={'name': 'Parables of the Kingdom', 'part': 2})
    _sower('s3', title='A Voice in the Wilderness',
           series={'name': 'Advent 2025', 'part': 2})
    assert sermons.all_series() == ['Advent 2025', 'Parables of the Kingdom']


def test_most_recent_is_the_one_last_written_in(store):
    """The collecting door's target — not a pin, not a setting. Two saves a
    fraction apart is the ordinary case, so this cannot be read off the
    seconds-precise timestamps; a write re-files the sermon at the end of the
    store and the last one wins."""
    _sower()
    _sower('s2', title='The Least of All Seeds')
    assert sermons.most_recent()['id'] == 's2'
    sermons.save('s1', title='The Sower Went Forth', body='worked on again')
    assert sermons.most_recent()['id'] == 's1'


def test_most_recent_is_none_on_an_empty_store(store):
    assert sermons.most_recent() is None


def test_tags_are_counted_across_sermons(store):
    _sower()
    _sower('s2', tags=['kingdom'])
    assert sermons.all_tags() == ['kingdom', 'parables']
    assert sermons.tag_counts() == {'kingdom': 2, 'parables': 1}


# ── Tags and series maintenance ─────────────────────────────────────────────

def test_renaming_a_tag_onto_an_existing_one_merges(store):
    _sower(tags=['parables', 'kingdom'])
    sermons.rename_tag('parables', 'kingdom')
    assert sermons.get('s1')['tags'] == ['kingdom']


def test_deleting_a_tag_leaves_the_writing(store):
    _sower()
    sermons.delete_tag('kingdom')
    assert sermons.get('s1')['tags'] == ['parables']
    assert sermons.get('s1')['body'].startswith('## I.')


def test_renaming_a_series_moves_every_sermon_in_it(store):
    _sower()
    _sower('s2', series={'name': 'Parables of the Kingdom', 'part': 2})
    _sower('s3', series={'name': 'Advent 2025', 'part': 1})
    sermons.rename_series('Parables of the Kingdom', 'The Kingdom Parables')
    assert sermons.get('s1')['series']['name'] == 'The Kingdom Parables'
    assert sermons.get('s1')['series']['part'] == 3
    assert sermons.get('s2')['series']['name'] == 'The Kingdom Parables'
    assert sermons.get('s3')['series']['name'] == 'Advent 2025'


def test_renaming_a_series_to_nothing_unfiles_it(store):
    _sower()
    sermons.rename_series('Parables of the Kingdom', '')
    assert sermons.get('s1')['series'] is None


# ── Collecting ──────────────────────────────────────────────────────────────

def test_append_adds_to_the_body_and_the_anchors(store):
    _sower()
    after = sermons.append(
        's1', '> Behold, a sower went forth to sow. — Matthew 13:3',
        {'book': 'Matthew', 'chapter': 13, 'verses': [3]})
    assert after['body'].startswith('## I. The seed that is scattered')
    assert after['body'].endswith('Matthew 13:3')
    assert {'book': 'Matthew', 'chapter': 13, 'verses': [3]} in after['anchors']


def test_append_does_not_repeat_an_anchor_it_already_has(store):
    _sower()
    sermons.append('s1', 'first', {'book': 'Matthew', 'chapter': 13,
                                   'verses': []})
    sermons.append('s1', 'second', {'book': 'Matthew', 'chapter': 13,
                                    'verses': []})
    assert len(sermons.get('s1')['anchors']) == 1


def test_append_into_an_empty_body_does_not_lead_with_blank_lines(store):
    _sower(body='')
    assert sermons.append('s1', 'Isaiah 55:10–11')['body'] == 'Isaiah 55:10–11'


def test_append_keeps_the_series_and_the_preaching_dates(store):
    """It writes through save(), so everything it does not pass would be
    dropped if it did not pass it."""
    _sower(preached=['2026-02-08'])
    after = sermons.append('s1', 'collected line')
    assert after['series']['part'] == 3
    assert after['preached'] == ['2026-02-08']


def test_append_to_a_sermon_that_is_gone_returns_none(store):
    assert sermons.append('nope', 'text') is None


# ── Delete and undo ─────────────────────────────────────────────────────────

def test_delete_returns_the_sermon_so_it_can_be_restored(store):
    _sower(preached=['2026-02-08'])
    removed = sermons.delete('s1')
    assert sermons.get('s1') is None
    assert sermons.restore(removed)
    assert sermons.get('s1')['preached'] == ['2026-02-08']


def test_undoing_a_deletion_is_not_an_edit(store):
    first = _sower()
    sermons.restore(sermons.delete('s1'))
    assert sermons.get('s1')['modified'] == first['modified']


def test_deleting_what_is_not_there_is_not_an_error(store):
    assert sermons.delete('nope') is None


# ── Backup ──────────────────────────────────────────────────────────────────

def test_replace_all_with_nothing_empties_the_store(store):
    """A restore from a backup that carried no sermons is not a no-op — the
    file's state is the truth."""
    _sower()
    assert sermons.replace_all({})
    assert sermons.all_sermons() == []
