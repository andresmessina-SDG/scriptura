"""Tests for sword_bridge.py — focused on the pure-Python helpers that do
not touch the SWORD library (OSIS parsing, TSK cross-ref text parsing,
.conf file parsing, morphology decoders). The import path requires the
`Sword` Python binding to be installed, but no SWMgr is created during
these tests."""

import pytest

import sword_bridge


# ── parse_osis_ref ───────────────────────────────────────────────────────────

def test_parse_osis_ref_plain():
    assert sword_bridge.parse_osis_ref('Eph.1.3') == ('Ephesians', 1, 3)


def test_parse_osis_ref_with_bible_prefix():
    assert sword_bridge.parse_osis_ref('Bible:Eph.1.3') == ('Ephesians', 1, 3)


def test_parse_osis_ref_with_extra_path_segments():
    # OSIS allows more parts (e.g. word-level); we use the first three.
    assert sword_bridge.parse_osis_ref('Eph.1.3.4') == ('Ephesians', 1, 3)


def test_parse_osis_ref_unknown_book():
    assert sword_bridge.parse_osis_ref('Bogus.1.1') is None


def test_parse_osis_ref_too_few_parts():
    assert sword_bridge.parse_osis_ref('Eph.1') is None


def test_parse_osis_ref_non_numeric():
    assert sword_bridge.parse_osis_ref('Eph.one.three') is None


def test_osis_books_table_covers_canon():
    # Spot-check: every English book name should appear at least once.
    canon_books = {
        'Genesis', 'Exodus', 'Psalms', 'Isaiah', 'Matthew',
        'Romans', 'Hebrews', 'Revelation', '1 Corinthians', '1 John',
    }
    mapped = set(sword_bridge._OSIS_BOOKS.values())
    assert canon_books.issubset(mapped)


# ── _parse_cross_ref_text — TSK-style parsing ────────────────────────────────

def test_parse_cross_ref_text_simple_list():
    refs = sword_bridge._parse_cross_ref_text('Ge 1:2; Ps 33:6')
    # (book, chapter, verse, label)
    books_chapters_verses = [(r[0], r[1], r[2]) for r in refs]
    assert ('Genesis', 1, 2) in books_chapters_verses
    assert ('Psalms', 33, 6) in books_chapters_verses


def test_parse_cross_ref_text_same_book_chapter_continuation():
    # "Ps 33:6; 136:5" — second ref shares the book from the first.
    refs = sword_bridge._parse_cross_ref_text('Ps 33:6; 136:5')
    assert ('Psalms', 33, 6) in [(r[0], r[1], r[2]) for r in refs]
    assert ('Psalms', 136, 5) in [(r[0], r[1], r[2]) for r in refs]


def test_parse_cross_ref_text_hyphen_range_emits_each_verse():
    # "1Jn 5:7-8" → both v7 and v8 appear.
    refs = sword_bridge._parse_cross_ref_text('1Jn 5:7-8')
    verses = sorted({r[2] for r in refs if r[0] == '1 John' and r[1] == 5})
    assert verses == [7, 8]


def test_parse_cross_ref_text_en_dash_range_also_supported():
    refs = sword_bridge._parse_cross_ref_text('Ge 1:1–3')
    verses = sorted({r[2] for r in refs if r[0] == 'Genesis' and r[1] == 1})
    assert verses == [1, 2, 3]


def test_parse_cross_ref_text_range_capped_to_prevent_runaway():
    # 1-500 would otherwise emit 500 refs. Implementation caps at 200.
    refs = sword_bridge._parse_cross_ref_text('Ps 119:1-500')
    psalm119 = [r for r in refs if r[0] == 'Psalms' and r[1] == 119]
    assert len(psalm119) <= 200


def test_parse_cross_ref_text_comma_extras():
    refs = sword_bridge._parse_cross_ref_text('Ge 1:1, 3, 5')
    verses = sorted({r[2] for r in refs if r[0] == 'Genesis' and r[1] == 1})
    assert verses == [1, 3, 5]


def test_parse_cross_ref_text_bare_verses_continue_in_same_chapter():
    # After "Ge 1:1", a bare "3" should be Ge 1:3.
    refs = sword_bridge._parse_cross_ref_text('Ge 1:1; 3')
    assert ('Genesis', 1, 1) in [(r[0], r[1], r[2]) for r in refs]
    assert ('Genesis', 1, 3) in [(r[0], r[1], r[2]) for r in refs]


def test_parse_cross_ref_text_unknown_abbrev_skipped():
    refs = sword_bridge._parse_cross_ref_text('Zzz 1:1; Ge 1:1')
    # Zzz silently dropped; Ge is found.
    assert ('Genesis', 1, 1) in [(r[0], r[1], r[2]) for r in refs]


def test_parse_cross_ref_text_empty_string():
    assert sword_bridge._parse_cross_ref_text('') == []


def test_parse_cross_ref_text_compact_abbrev():
    # "1Co 3:16" — no space between digit prefix and abbrev.
    refs = sword_bridge._parse_cross_ref_text('1Co 3:16')
    assert ('1 Corinthians', 3, 16) in [(r[0], r[1], r[2]) for r in refs]


def test_cross_ref_abbrevs_table_covers_common_books():
    # Spot-check the abbreviation map.
    expected = {'ge': 'Genesis', 'ps': 'Psalms', '1co': '1 Corinthians',
                '1jn': '1 John', 'rev': 'Revelation'}
    for k, v in expected.items():
        assert sword_bridge._CROSS_REF_ABBREVS.get(k) == v


# ── decode_robinson — Greek morphology ───────────────────────────────────────

def test_decode_robinson_none_input():
    assert sword_bridge.decode_robinson(None) is None
    assert sword_bridge.decode_robinson('') is None


def test_decode_robinson_no_prefix_returns_none():
    assert sword_bridge.decode_robinson('V-PAI-3S') is None


def test_decode_robinson_verb_present_active_indicative():
    # V-PAI-3S = Verb · Present · Active · Indicative · 3rd Person · Singular
    result = sword_bridge.decode_robinson('robinson:V-PAI-3S')
    assert result is not None
    assert 'Verb' in result
    assert 'Present' in result
    assert 'Active' in result
    assert 'Indicative' in result


def test_decode_robinson_verb_second_aorist_prefix():
    # 2A prefix: 2nd Aorist
    result = sword_bridge.decode_robinson('robinson:V-2AAI-3S')
    assert result is not None
    assert '2' in result and 'Aorist' in result


def test_decode_robinson_participle_with_case_number_gender():
    # V-PAP-NSM = Verb · Present · Active · Participle · Nom · Sg · Masc
    result = sword_bridge.decode_robinson('robinson:V-PAP-NSM')
    assert 'Participle' in result
    assert 'Nominative' in result
    assert 'Singular' in result
    assert 'Masculine' in result


def test_decode_robinson_noun_case_number_gender():
    # N-GSM = Noun · Genitive · Singular · Masculine
    result = sword_bridge.decode_robinson('robinson:N-GSM')
    assert 'Noun' in result
    assert 'Genitive' in result
    assert 'Singular' in result
    assert 'Masculine' in result


# ── decode_hebrew_morph — Hebrew morphology ──────────────────────────────────

def test_decode_hebrew_morph_none_input():
    assert sword_bridge.decode_hebrew_morph(None) is None
    assert sword_bridge.decode_hebrew_morph('') is None


def test_decode_hebrew_morph_basic_noun():
    # HNcms — Hebrew prefix + Noun (common, masculine, singular).
    # POS letters in OSHB are uppercase (N, V, A, P, R, S, T, etc.).
    result = sword_bridge.decode_hebrew_morph('HNcms')
    assert result is not None
    assert 'Noun' in result
    assert 'Masculine' in result
    assert 'Singular' in result


def test_decode_hebrew_morph_with_prefix():
    # OSHM prefix variant should be handled.
    result = sword_bridge.decode_hebrew_morph('oshm:HNcms')
    assert result is not None
    assert 'Noun' in result


def test_decode_hebrew_morph_multi_word():
    # Two morphs separated by space — joined with ' + '.
    result = sword_bridge.decode_hebrew_morph('HNcms HNcfp')
    assert result is not None
    assert '+' in result
    # Both should be decoded as Noun.
    assert result.count('Noun') == 2


def test_decode_hebrew_morph_verb():
    # HVqp3ms — Hebrew + Verb (qal, perfect, 3rd person, masculine, singular).
    result = sword_bridge.decode_hebrew_morph('HVqp3ms')
    assert result is not None
    assert 'Verb' in result
    assert 'Qal' in result


# ── _parse_conf — SWORD .conf file parsing ───────────────────────────────────

def test_parse_conf_basic(tmp_path):
    p = tmp_path / 'mod.conf'
    p.write_text(
        '[KJV]\n'
        'Description=King James Version\n'
        'Category=Biblical Texts\n'
        'Lang=en\n',
        encoding='utf-8',
    )
    info = sword_bridge._parse_conf(str(p))
    assert info['name'] == 'KJV'
    assert info['description'] == 'King James Version'
    assert info['category'] == 'Biblical Texts'
    assert info['lang'] == 'en'


def test_parse_conf_strips_bom(tmp_path):
    p = tmp_path / 'mod.conf'
    p.write_bytes(
        '﻿[KJV]\nDescription=King James Version\n'.encode('utf-8'))
    info = sword_bridge._parse_conf(str(p))
    # Without BOM stripping, name would be e.g. "﻿KJV".
    assert info['name'] == 'KJV'


def test_parse_conf_line_continuation(tmp_path):
    p = tmp_path / 'mod.conf'
    # Trailing backslash continues to the next line.
    p.write_text(
        '[MOD]\n'
        'Description=Part one \\\n'
        'and part two together\n',
        encoding='utf-8',
    )
    info = sword_bridge._parse_conf(str(p))
    assert info['description'] == 'Part one and part two together'


def test_parse_conf_collects_features(tmp_path):
    p = tmp_path / 'mod.conf'
    p.write_text(
        '[MOD]\n'
        'Feature=StrongsNumbers\n'
        'Feature=Morphology\n',
        encoding='utf-8',
    )
    info = sword_bridge._parse_conf(str(p))
    assert info['features'] == {'StrongsNumbers', 'Morphology'}


def test_parse_conf_missing_file_returns_empty(tmp_path):
    info = sword_bridge._parse_conf(str(tmp_path / 'does_not_exist.conf'))
    assert info == {}


def test_parse_conf_ignores_unknown_keys(tmp_path):
    p = tmp_path / 'mod.conf'
    p.write_text(
        '[MOD]\n'
        'Description=A description\n'
        'GlobalOptionFilter=OSISFootnotes\n'
        'UnknownKey=ignored\n',
        encoding='utf-8',
    )
    info = sword_bridge._parse_conf(str(p))
    assert 'description' in info
    # Unknown keys silently dropped.
    assert 'globaloptionfilter' not in info
    assert 'unknownkey' not in info
