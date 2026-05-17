"""Tests for open_data.py — OSIS reference parsing and OpenBible / Dodson
file loaders. No GTK / SWORD dependency."""

import os
import pytest

import open_data


# ── _parse_osis_one ──────────────────────────────────────────────────────────

def test_parse_osis_one_single_verse():
    assert open_data._parse_osis_one('Gen.1.1') == ('Genesis', 1, 1)
    assert open_data._parse_osis_one('John.3.16') == ('John', 3, 16)


def test_parse_osis_one_alternate_book_keys():
    # Some OSIS variants use longer keys (Revelation vs Rev).
    assert open_data._parse_osis_one('Rev.21.6') == ('Revelation', 21, 6)
    assert open_data._parse_osis_one('Revelation.21.6') == ('Revelation', 21, 6)


def test_parse_osis_one_invalid_book():
    assert open_data._parse_osis_one('Bogus.1.1') is None


def test_parse_osis_one_wrong_segment_count():
    assert open_data._parse_osis_one('Gen.1') is None
    assert open_data._parse_osis_one('Gen.1.1.1') is None
    assert open_data._parse_osis_one('') is None


def test_parse_osis_one_non_numeric():
    assert open_data._parse_osis_one('Gen.one.1') is None
    assert open_data._parse_osis_one('Gen.1.xxx') is None


# ── _osis_to_vids ────────────────────────────────────────────────────────────

def test_osis_to_vids_single_verse():
    # Gen=1, Ch=1, V=1 → 01001001
    assert open_data._osis_to_vids('Gen.1.1') == ['01001001']


def test_osis_to_vids_same_chapter_range_expands():
    # Exod.20.1-Exod.20.5 → 5 vids
    vids = open_data._osis_to_vids('Exod.20.1-Exod.20.5')
    assert vids == ['02020001', '02020002', '02020003', '02020004', '02020005']


def test_osis_to_vids_cross_chapter_range_clips_to_start():
    # OpenBible rarely emits cross-chapter ranges, but if it does we keep
    # the start verse only (matches code comment intent).
    vids = open_data._osis_to_vids('Gen.1.31-Gen.2.3')
    assert vids == ['01001031']


def test_osis_to_vids_cross_book_range_clips_to_start():
    vids = open_data._osis_to_vids('Gen.50.26-Exod.1.1')
    assert vids == ['01050026']


def test_osis_to_vids_malformed_start_returns_empty():
    assert open_data._osis_to_vids('Bogus.1.1-Bogus.1.5') == []


def test_osis_to_vids_handles_whitespace():
    assert open_data._osis_to_vids('  Gen.1.1  ') == ['01001001']


def test_osis_to_vids_empty_string():
    assert open_data._osis_to_vids('') == []


# ── _osis_first_tuple ────────────────────────────────────────────────────────

def test_osis_first_tuple_single():
    assert open_data._osis_first_tuple('Ps.23.1') == ('Psalms', 23, 1)


def test_osis_first_tuple_range_returns_start():
    assert open_data._osis_first_tuple('Ps.23.1-Ps.23.6') == ('Psalms', 23, 1)


def test_osis_first_tuple_malformed_returns_none():
    assert open_data._osis_first_tuple('garbage') is None


# ── _vid / _parse_vid round-trip ─────────────────────────────────────────────

def test_vid_round_trip_genesis():
    assert open_data._parse_vid(open_data._vid('Genesis', 1, 1)) == ('Genesis', 1, 1)


def test_vid_round_trip_revelation():
    # Last book in the canon — index 66 → "66" prefix.
    assert open_data._parse_vid(open_data._vid('Revelation', 22, 21)) == (
        'Revelation', 22, 21)


def test_vid_pads_chapter_and_verse():
    # Format: BBCCCVVV (2-digit book, 3-digit chapter, 3-digit verse).
    assert open_data._vid('Genesis', 1, 1) == '01001001'
    assert open_data._vid('Psalms', 119, 176) == '19119176'


def test_parse_vid_invalid():
    assert open_data._parse_vid('garbage') is None
    assert open_data._parse_vid('99999999') is None  # book index out of range
    assert open_data._parse_vid('') is None


# ── File loaders ─────────────────────────────────────────────────────────────

def _write_topics_file(tmp_path, rows):
    """Write a tab-separated topics file (header + data rows)."""
    path = tmp_path / 'topic-scores.txt'
    with open(path, 'w', encoding='utf-8') as f:
        f.write('Topic\tOSIS\tQuality Score\n')
        for row in rows:
            f.write('\t'.join(str(c) for c in row) + '\n')
    return path


def _write_xref_file(tmp_path, rows):
    """Write a tab-separated cross-references file (header + data rows)."""
    path = tmp_path / 'cross_references.txt'
    with open(path, 'w', encoding='utf-8') as f:
        f.write('From Verse\tTo Verse\tVotes\n')
        for row in rows:
            f.write('\t'.join(str(c) for c in row) + '\n')
    return path


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """Redirect open_data._DIR to a tmp path and reset the module's caches."""
    monkeypatch.setattr(open_data, '_DIR', str(tmp_path))
    monkeypatch.setattr(open_data, '_xref', None)
    monkeypatch.setattr(open_data, '_topics', None)
    monkeypatch.setattr(open_data, '_dodson', None)
    return tmp_path


def test_get_topics_missing_file_returns_empty(isolated_data):
    # No topic-scores.txt in the tmp dir.
    assert open_data.get_topics('Hosea', 3, 1) == []


def test_get_topics_finds_exact_verse(isolated_data):
    _write_topics_file(isolated_data, [
        ('forgiveness', 'Hos.3.1', 10),
        ('idolatry',    'Hos.3.1', 5),
    ])
    topics = open_data.get_topics('Hosea', 3, 1)
    # Sorted by score descending.
    assert topics == ['forgiveness', 'idolatry']


def test_get_topics_expands_range(isolated_data):
    # Exod.20.1-Exod.20.5 → topic applies to all 5 verses.
    _write_topics_file(isolated_data, [
        ('ten commandments', 'Exod.20.1-Exod.20.5', 7),
    ])
    assert open_data.get_topics('Exodus', 20, 1) == ['ten commandments']
    assert open_data.get_topics('Exodus', 20, 3) == ['ten commandments']
    assert open_data.get_topics('Exodus', 20, 5) == ['ten commandments']
    # Outside the range, no match.
    assert open_data.get_topics('Exodus', 20, 6) == []


def test_get_topics_skips_malformed_rows(isolated_data):
    _write_topics_file(isolated_data, [
        ('valid', 'Gen.1.1', 1),
        ('bad-book', 'Bogus.1.1', 1),
    ])
    assert open_data.get_topics('Genesis', 1, 1) == ['valid']


def test_get_cross_refs_missing_file_returns_none(isolated_data):
    assert open_data.get_cross_refs('Hosea', 3, 1) is None


def test_get_cross_refs_basic(isolated_data):
    _write_xref_file(isolated_data, [
        ('Gen.1.1', 'John.1.1', 100),
        ('Gen.1.1', 'Heb.11.3', 50),
    ])
    refs = open_data.get_cross_refs('Genesis', 1, 1)
    # Returned as (book, chapter, verse, label) tuples.
    assert len(refs) == 2
    labels = [r[3] for r in refs]
    assert 'John 1:1' in labels
    assert 'Hebrews 11:3' in labels


def test_get_cross_refs_from_range_emits_per_verse(isolated_data):
    # If From column is a range, the same target applies to each from-verse.
    _write_xref_file(isolated_data, [
        ('Exod.20.1-Exod.20.3', 'Deut.5.6', 1),
    ])
    for v in (1, 2, 3):
        refs = open_data.get_cross_refs('Exodus', 20, v)
        assert any(r[3] == 'Deuteronomy 5:6' for r in refs)


def test_get_cross_refs_to_range_uses_start_verse(isolated_data):
    _write_xref_file(isolated_data, [
        ('Gen.1.1', 'Heb.1.1-Heb.1.4', 1),
    ])
    refs = open_data.get_cross_refs('Genesis', 1, 1)
    assert refs == [('Hebrews', 1, 1, 'Hebrews 1:1')]


def test_has_topics_and_has_cross_refs(isolated_data):
    assert not open_data.has_topics()
    assert not open_data.has_cross_refs()
    _write_topics_file(isolated_data, [('t', 'Gen.1.1', 1)])
    _write_xref_file(isolated_data, [('Gen.1.1', 'John.1.1', 1)])
    assert open_data.has_topics()
    assert open_data.has_cross_refs()
