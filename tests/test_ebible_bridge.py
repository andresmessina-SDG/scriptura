"""Tests for ebible_bridge.py — USFM parsing + SQLite-backed verse storage.

Pure-Python: redirects the module-level _DB path to a tmp file so the
SQLite layer is testable without touching real user data. No network
calls — download_translation_sync / download_catalog_sync are not tested
here (they need real eBible.org reachability)."""

import sqlite3

import pytest

import ebible_bridge as eb


# ── PREFIX guard ────────────────────────────────────────────────────────────

def test_is_ebible_module():
    assert eb.is_ebible_module('eBible: WEB')
    assert eb.is_ebible_module('eBible: ')  # prefix alone still matches
    assert not eb.is_ebible_module('KJVA')
    assert not eb.is_ebible_module('')
    assert not eb.is_ebible_module(None)
    assert not eb.is_ebible_module(123)


# ── _apply_char — USFM inline marker → HTML ─────────────────────────────────

def test_apply_char_words_of_jesus():
    out = eb._apply_char(r'He said, \wj Truly I say to you\wj* now.')
    assert '<q who="Jesus">Truly I say to you</q>' in out


def test_apply_char_translator_addition():
    out = eb._apply_char(r'The Lord \add is\add* my shepherd.')
    assert '<transChange type="added">is</transChange>' in out


def test_apply_char_italic_emphasis():
    assert '<i>love</i>' in eb._apply_char(r'\em love\em*')
    assert '<i>faith</i>' in eb._apply_char(r'\it faith\it*')


def test_apply_char_strong_word_attribute_keeps_text():
    """USFM \\w word|strong="G1234"\\w* should leave plain word behind."""
    out = eb._apply_char(r'\w God|strong="G2316"\w* loves us')
    assert 'God' in out
    assert 'strong' not in out
    assert '\\' not in out


def test_apply_char_strong_word_without_attribute_keeps_text():
    out = eb._apply_char(r'\w Jesus\w* wept')
    assert 'Jesus wept' == out


def test_apply_char_strips_unknown_markers():
    out = eb._apply_char(r'plain \unknown text \unknown* here')
    assert '\\' not in out
    assert 'plain' in out and 'here' in out


def test_apply_char_collapses_whitespace_but_preserves_newlines():
    out = eb._apply_char('a   b\n   c')
    assert out == 'a b\nc'


def test_apply_char_strips_published_verse_number_spans():
    out = eb._apply_char(r'\va 2\va* And the Lord said')
    assert 'And the Lord said' in out
    assert '2' not in out  # the alt verse number is dropped


# ── _parse_usfm — small end-to-end samples ──────────────────────────────────

def _parse(s):
    return eb._parse_usfm(s)


def test_parse_basic_verse():
    usfm = r'''\id GEN Genesis
\c 1
\v 1 In the beginning God created the heavens and the earth.
\v 2 The earth was without form, and void.
'''
    verses = _parse(usfm)
    assert verses[('Genesis', 1, 1)].startswith('In the beginning')
    assert 'without form' in verses[('Genesis', 1, 2)]


def test_parse_verse_range_marker():
    """\\v 1-2 keys off the first number and drops the range suffix
    rather than leaking "-2" into the verse text."""
    usfm = '\\id GEN Genesis\n\\c 1\n\\v 1-2 In the beginning God created.\n'
    verses = _parse(usfm)
    assert verses[('Genesis', 1, 1)] == 'In the beginning God created.'


def test_parse_book_code_resolution():
    """USFM book codes are uppercased and looked up in _BOOK."""
    usfm = '\\id jhn John\n\\c 3\n\\v 16 For God so loved the world.\n'
    verses = _parse(usfm)
    assert ('John', 3, 16) in verses


def test_parse_skips_metadata_lines():
    usfm = r'''\id GEN
\h Genesis
\toc1 The First Book of Moses
\mt1 The First Book of Moses
\c 1
\v 1 In the beginning.
'''
    verses = _parse(usfm)
    # Only the verse survives — none of the metadata becomes content.
    assert list(verses.keys()) == [('Genesis', 1, 1)]
    assert verses[('Genesis', 1, 1)] == 'In the beginning.'


def test_parse_strips_footnotes_and_cross_refs():
    usfm = r'''\id GEN
\c 1
\v 1 In the beginning\f + footnote text \f* God created\x + cross ref \x*.
'''
    verses = _parse(usfm)
    text = verses[('Genesis', 1, 1)]
    assert 'footnote' not in text
    assert 'cross ref' not in text
    assert 'In the beginning' in text
    assert 'God created' in text


def test_parse_section_heading_attached_to_next_verse():
    usfm = r'''\id GEN
\c 1
\s1 The Creation
\v 1 In the beginning God created.
'''
    verses = _parse(usfm)
    assert verses[('Genesis', 1, 1)].startswith('<title>The Creation</title>')
    assert 'In the beginning' in verses[('Genesis', 1, 1)]


def test_parse_red_letter_through_full_pipeline():
    usfm = r'''\id JHN
\c 3
\v 16 \wj For God so loved the world\wj*, that he gave his only Son.
'''
    verses = _parse(usfm)
    assert '<q who="Jesus">For God so loved the world</q>' in verses[('John', 3, 16)]


def test_parse_poetry_lines_indented():
    usfm = r'''\id PSA
\c 23
\v 1 The LORD is my shepherd.
\q1 I shall not want.
\q2 He maketh me to lie down.
'''
    verses = _parse(usfm)
    text = verses[('Psalms', 23, 1)]
    # Poetry lines are prefixed with newline + em-space indent.
    assert 'shepherd' in text
    assert 'shall not want' in text
    assert 'lie down' in text
    assert '\n' in text


def test_parse_multiple_books_in_one_file():
    """USFM normally has one book per file, but the parser should still
    handle a sequence correctly if it sees one."""
    usfm = r'''\id GEN
\c 1
\v 1 First.
\id EXO
\c 1
\v 1 Names of children.
'''
    verses = _parse(usfm)
    assert verses[('Genesis', 1, 1)] == 'First.'
    assert verses[('Exodus', 1, 1)] == 'Names of children.'


def test_parse_paragraph_marker_with_inline_text():
    """\\p sometimes carries text on the same line — it must attach to
    the currently open verse."""
    usfm = r'''\id JHN
\c 1
\v 1 In the beginning was the Word,
\p and the Word was with God.
'''
    verses = _parse(usfm)
    assert 'In the beginning' in verses[('John', 1, 1)]
    assert 'with God' in verses[('John', 1, 1)]


def test_parse_empty_input_yields_nothing():
    assert _parse('') == {}


def test_parse_only_metadata_yields_nothing():
    assert _parse('\\id GEN\n\\h Genesis\n\\mt1 Genesis\n') == {}


# ── SQLite-backed API (with isolated DB) ────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point _DB at a tmp file and clear the thread-local connection
    cache so the next _db() call opens against the new path."""
    monkeypatch.setattr(eb, '_DB', str(tmp_path / 'ebible.db'))
    # _conn_local is threading.local() — clear any cached conn so the
    # new test gets a fresh DB pointing at the tmp path.
    if hasattr(eb._conn_local, 'conn'):
        try:
            eb._conn_local.conn.close()
        except Exception:
            pass
        del eb._conn_local.conn

    # Seed: one translation with a handful of verses.
    conn = eb._db()
    conn.execute(
        'INSERT INTO translations VALUES (?,?,?,?,?,?)',
        ('engwebp', 'WEB', 'English', 'en', '© WEB', 'Public Domain'))
    conn.executemany(
        'INSERT INTO verses VALUES (?,?,?,?,?)',
        [('engwebp', 'John', 3, 16, 'For God so loved the world'),
         ('engwebp', 'John', 3, 17, 'For God did not send his Son to condemn'),
         ('engwebp', 'Genesis', 1, 1, 'In the beginning God created'),
         ('engwebp', 'Genesis', 1, 2, 'And the earth was without form')])
    conn.commit()
    yield tmp_path
    if hasattr(eb._conn_local, 'conn'):
        try:
            eb._conn_local.conn.close()
        except Exception:
            pass
        del eb._conn_local.conn


def test_installed_translations(db):
    rows = eb.installed_translations()
    assert len(rows) == 1
    tid, title, lang, code, copyr, lic = rows[0]
    assert tid == 'engwebp'
    assert title == 'WEB'
    assert code == 'en'


def test_module_names(db):
    assert eb.module_names() == ['eBible: WEB']


def test_installed_ids(db):
    assert eb.installed_ids() == {'engwebp'}


def test_module_language(db):
    assert eb.module_language('eBible: WEB') == 'en'


def test_module_language_unknown(db):
    assert eb.module_language('eBible: Nonexistent') == ''


def test_module_info_known(db):
    info = eb.module_info('eBible: WEB')
    assert info['language'] == 'en'
    assert info['copyright'] == '© WEB'
    assert info['license'] == 'Public Domain'
    assert info['type'] == 'eBible translation'


def test_module_info_unknown_still_returns_shape(db):
    info = eb.module_info('eBible: Nonexistent')
    # Shape contract: all expected keys present, even if empty.
    assert set(info.keys()) >= {'name', 'description', 'version', 'copyright',
                                 'license', 'about', 'language', 'type'}
    assert info['type'] == 'eBible translation'


def test_load_chapter(db):
    verses = eb.load_chapter('eBible: WEB', 'John', 3)
    assert verses == [(16, 'For God so loved the world'),
                      (17, 'For God did not send his Son to condemn')]


def test_load_chapter_missing_returns_empty(db):
    assert eb.load_chapter('eBible: WEB', 'Revelation', 22) == []


def test_search_case_insensitive(db):
    results = eb.search_module('eBible: WEB', 'GOD')
    books = {(b, c, v) for (b, c, v, _t) in results}
    assert ('John', 3, 16) in books
    assert ('John', 3, 17) in books
    assert ('Genesis', 1, 1) in books


def test_search_case_sensitive(db):
    # 'world' is lowercase in the seed.
    assert len(eb.search_module('eBible: WEB', 'world', case_sensitive=True)) == 1
    # 'World' (capital) shouldn't match.
    assert eb.search_module('eBible: WEB', 'World', case_sensitive=True) == []


def test_search_AND_across_words(db):
    """Both 'God' AND 'world' should land only on John 3:16."""
    results = eb.search_module('eBible: WEB', 'God world')
    assert len(results) == 1
    assert results[0][:3] == ('John', 3, 16)


def test_search_case_insensitive_non_ascii(db):
    """Case-insensitive search folds non-ASCII too — a lowercase Greek
    query matches a verse with a capital (accented) initial, which plain
    SQLite LIKE/LOWER (ASCII-only) would miss."""
    conn = eb._db()
    conn.execute('INSERT INTO verses VALUES (?,?,?,?,?)',
                 ('engwebp', 'John', 1, 1, 'Ἰησοῦς Χριστός'))
    conn.commit()
    results = eb.search_module('eBible: WEB', 'ἰησοῦς')
    assert ('John', 1, 1) in {(b, c, v) for (b, c, v, _t) in results}


def test_search_empty_query_returns_empty(db):
    assert eb.search_module('eBible: WEB', '') == []
    assert eb.search_module('eBible: WEB', '   ') == []


def test_remove_translation(db):
    eb.remove_translation('engwebp')
    assert eb.installed_ids() == set()
    assert eb.load_chapter('eBible: WEB', 'John', 3) == []


# ── catalog_entries — file-backed CSV cache ─────────────────────────────────

@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """Redirect the catalog CSV path."""
    monkeypatch.setattr(eb, '_CAT', str(tmp_path / 'catalog.csv'))
    return tmp_path


def test_catalog_entries_missing_file(catalog):
    assert eb.catalog_entries() == []


def test_catalog_entries_reads_csv(catalog):
    (catalog / 'catalog.csv').write_text(
        'translationId,shortTitle,languageName,languageCode\n'
        'engwebp,WEB,English,en\n'
        'spavbl,RVR,Spanish,es\n',
        encoding='utf-8')
    rows = eb.catalog_entries()
    assert len(rows) == 2
    assert rows[0]['translationId'] == 'engwebp'
    assert rows[1]['languageCode'] == 'es'


def test_catalog_entries_handles_utf8_bom(catalog):
    """eBible.org sometimes serves a UTF-8 BOM — DictReader needs the
    utf-8-sig encoding to not stick \\ufeff onto the first key."""
    (catalog / 'catalog.csv').write_bytes(
        b'\xef\xbb\xbftranslationId,shortTitle\nengwebp,WEB\n')
    rows = eb.catalog_entries()
    assert 'translationId' in rows[0]
    assert rows[0]['translationId'] == 'engwebp'
