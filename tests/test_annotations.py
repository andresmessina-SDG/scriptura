"""Tests for annotations.py — per-verse JSON persistence with migration
from the old single-string highlight format. No GTK / SWORD dependency."""

import json
import pytest

import annotations


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect ANNOTATIONS_FILE to a temp file and reset the cache."""
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE', str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    return tmp_path


# ── Basic save/load round-trips ──────────────────────────────────────────────

def test_save_and_get_highlight(isolated):
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    data = annotations.get_annotations('KJVA', 'Genesis', 1)
    assert data['1']['highlight'] == '#ffff00'


def test_save_underline(isolated):
    annotations.save_underline('KJVA', 'Genesis', 1, 1, True)
    data = annotations.get_annotations('KJVA', 'Genesis', 1)
    assert data['1']['underline'] is True


def test_save_note(isolated):
    annotations.save_note('KJVA', 'John', 3, 16, 'God so loved')
    assert annotations.get_annotations('KJVA', 'John', 3)['16']['note'] == 'God so loved'


def test_save_tags_strips_whitespace_and_empties(isolated):
    annotations.save_tags('KJVA', 'Psalms', 23, 1, ['shepherd', ' guidance ', '', None])
    tags = annotations.get_annotations('KJVA', 'Psalms', 23)['1']['tags']
    assert tags == ['shepherd', 'guidance']


def test_multiple_attributes_coexist(isolated):
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#90ee90')
    annotations.save_underline('KJVA', 'Genesis', 1, 1, True)
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'creation')
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['origin', 'doctrine'])
    a = annotations.get_annotations('KJVA', 'Genesis', 1)['1']
    assert a == {
        'highlight': '#90ee90',
        'underline': True,
        'note': 'creation',
        'tags': ['origin', 'doctrine'],
    }


# ── Migration from legacy single-string format ───────────────────────────────

def test_migration_from_string_to_dict(isolated):
    """Old annotations stored just the highlight color as a string for the
    verse; new ops should migrate to the dict shape without losing data."""
    # Simulate legacy file content.
    legacy = {'KJVA/Genesis/1': {'1': '#ffff00'}}
    isolated.joinpath('annotations.json').write_text(json.dumps(legacy))
    annotations._cache = None  # force reload

    # Saving underline triggers migration.
    annotations.save_underline('KJVA', 'Genesis', 1, 1, True)
    a = annotations.get_annotations('KJVA', 'Genesis', 1)['1']
    assert a['highlight'] == '#ffff00'  # preserved
    assert a['underline'] is True       # newly added


def test_corrupt_file_falls_back_to_empty_dict(isolated):
    isolated.joinpath('annotations.json').write_text('this is not JSON')
    annotations._cache = None
    assert annotations.get_annotations('KJVA', 'Genesis', 1) == {}


def test_non_dict_top_level_falls_back_to_empty(isolated):
    isolated.joinpath('annotations.json').write_text('["a", "b"]')
    annotations._cache = None
    assert annotations.get_annotations('KJVA', 'Genesis', 1) == {}


# ── Chapter notes ────────────────────────────────────────────────────────────

def test_save_and_get_chapter_note(isolated):
    annotations.save_chapter_note('KJVA', 'Genesis', 1, 'Creation account')
    assert annotations.get_chapter_note('KJVA', 'Genesis', 1) == 'Creation account'


def test_save_chapter_note_tags(isolated):
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'shepherd psalm')
    annotations.save_chapter_note_tags('KJVA', 'Psalms', 23, ['comfort', 'shepherd'])
    data = annotations.get_chapter_note_data('KJVA', 'Psalms', 23)
    assert data == {'note': 'shepherd psalm', 'tags': ['comfort', 'shepherd']}


def test_empty_chapter_note_with_no_tags_is_removed(isolated):
    annotations.save_chapter_note('KJVA', 'Genesis', 1, 'something')
    annotations.save_chapter_note('KJVA', 'Genesis', 1, '')   # clear text
    annotations.save_chapter_note_tags('KJVA', 'Genesis', 1, [])
    assert annotations.get_chapter_note('KJVA', 'Genesis', 1) is None


def test_legacy_chapter_note_string_is_normalised(isolated):
    legacy = {'KJVA/Genesis/1': {'chapter_note': 'legacy string note'}}
    isolated.joinpath('annotations.json').write_text(json.dumps(legacy))
    annotations._cache = None
    data = annotations.get_chapter_note_data('KJVA', 'Genesis', 1)
    assert data == {'note': 'legacy string note', 'tags': []}


# ── delete_annotation ────────────────────────────────────────────────────────

def test_delete_verse_annotation(isolated):
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    annotations.save_highlight('KJVA', 'Genesis', 1, 2, '#90ee90')
    annotations.delete_annotation('KJVA', 'Genesis', 1, 1)
    chap = annotations.get_annotations('KJVA', 'Genesis', 1)
    assert '1' not in chap
    assert '2' in chap


def test_delete_chapter_note(isolated):
    annotations.save_chapter_note('KJVA', 'Genesis', 1, 'a note')
    annotations.delete_annotation('KJVA', 'Genesis', 1, None)
    assert annotations.get_chapter_note('KJVA', 'Genesis', 1) is None


def test_delete_nonexistent_is_safe(isolated):
    # Should not raise.
    annotations.delete_annotation('KJVA', 'Genesis', 1, 99)
    annotations.delete_annotation('KJVA', 'Bogus', 1, 1)


# ── get_all_tags aggregation ─────────────────────────────────────────────────

def test_get_all_tags_deduplicates_and_sorts(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['origin', 'doctrine'])
    annotations.save_tags('KJVA', 'Psalms', 23, 1, ['comfort', 'doctrine'])
    annotations.save_tags('KJVA', 'John', 3, 16, ['salvation', 'comfort'])
    tags = annotations.get_all_tags()
    assert tags == ['comfort', 'doctrine', 'origin', 'salvation']


def test_get_all_tags_empty_when_no_annotations(isolated):
    assert annotations.get_all_tags() == []


# ── Persistence — written file is reloadable ─────────────────────────────────

def test_save_reloads_from_disk(isolated):
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#bdd5e8')
    # Force a fresh load from disk.
    annotations._cache = None
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['highlight'] == '#bdd5e8'


def test_save_writes_utf8_without_escaping(isolated):
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'Anständig')
    # File should contain the literal accented character, not a \u escape.
    content = isolated.joinpath('annotations.json').read_text(encoding='utf-8')
    assert 'Anständig' in content


# ── Tag management (rename / merge / delete / counts) ─────────────────────────

def test_get_tag_counts(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['origin', 'doctrine'])
    annotations.save_tags('KJVA', 'John', 3, 16, ['salvation', 'doctrine'])
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'shepherd psalm')
    annotations.save_chapter_note_tags('KJVA', 'Psalms', 23, ['comfort', 'doctrine'])
    counts = annotations.get_tag_counts()
    assert counts == {'origin': 1, 'doctrine': 3, 'salvation': 1, 'comfort': 1}


def test_get_tag_counts_empty(isolated):
    assert annotations.get_tag_counts() == {}


def test_rename_tag_simple(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['origin', 'doctrine'])
    annotations.save_tags('KJVA', 'John', 3, 16, ['origin', 'salvation'])
    annotations.rename_tag('origin', 'beginnings')
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['beginnings', 'doctrine']
    assert annotations.get_annotations('KJVA', 'John', 3)['16']['tags'] == ['beginnings', 'salvation']


def test_rename_tag_merges_when_target_exists(isolated):
    # 'creation' and 'origin' both present on same verse → merge dedupes.
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['creation', 'origin', 'doctrine'])
    annotations.rename_tag('origin', 'creation')
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['creation', 'doctrine']


def test_rename_tag_touches_chapter_notes(isolated):
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'shepherd psalm')
    annotations.save_chapter_note_tags('KJVA', 'Psalms', 23, ['comfort', 'old'])
    annotations.rename_tag('old', 'new')
    data = annotations.get_chapter_note_data('KJVA', 'Psalms', 23)
    assert data['tags'] == ['comfort', 'new']


def test_rename_tag_no_op_for_empty_or_same(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['a', 'b'])
    annotations.rename_tag('', 'x')
    annotations.rename_tag('a', '')
    annotations.rename_tag('a', 'a')
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['a', 'b']


def test_rename_tag_missing_tag_does_nothing(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['a', 'b'])
    annotations.rename_tag('nonexistent', 'x')
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['a', 'b']


def test_delete_tag(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['origin', 'doctrine'])
    annotations.save_tags('KJVA', 'John', 3, 16, ['origin', 'salvation'])
    annotations.delete_tag('origin')
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['doctrine']
    assert annotations.get_annotations('KJVA', 'John', 3)['16']['tags'] == ['salvation']


def test_delete_tag_clears_chapter_note_tags(isolated):
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'shepherd')
    annotations.save_chapter_note_tags('KJVA', 'Psalms', 23, ['comfort', 'drop'])
    annotations.delete_tag('drop')
    data = annotations.get_chapter_note_data('KJVA', 'Psalms', 23)
    assert data['tags'] == ['comfort']


def test_delete_tag_empty_is_noop(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['a', 'b'])
    annotations.delete_tag('')
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['a', 'b']


def test_rename_tag_persists_to_disk(isolated):
    annotations.save_tags('KJVA', 'Genesis', 1, 1, ['a', 'b'])
    annotations.rename_tag('a', 'c')
    annotations._cache = None  # force reload
    assert annotations.get_annotations('KJVA', 'Genesis', 1)['1']['tags'] == ['c', 'b']
