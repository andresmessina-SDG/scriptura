"""Tests for catena_reader's display helpers — the (now pass-through) author
split, the category display-name lookup, and the sentence-boundary preview
cut. Suffix/title normalization moved into the pack build (see
test_catena_build). Pure functions; no widgets are built."""

import catena_reader
from catena_reader import (_author_label, _author_parts, _category_name,
                           _preview)


def test_author_parts_passes_stored_suffix_through():
    # The pack normalizes suffixes at build time now; the reader just reads
    # the stored field (already stripped and parenthesized).
    e = {'author': '1 Corinthians', 'author_suffix': '(10:23-33)'}
    assert _author_parts(e) == ('1 Corinthians', '(10:23-33)')
    assert _author_label(e) == '1 Corinthians (10:23-33)'


def test_author_parts_absent_suffix():
    assert _author_parts({'author': 'Irenaeus'}) == ('Irenaeus', '')
    assert _author_label(
        {'author': 'Irenaeus', 'author_suffix': None}) == 'Irenaeus'


def test_category_name_translates_known_shortens_display():
    # The DB key is the full upstream category; the display name is shorter.
    assert _category_name('Eastern & Byzantine Theology') == 'Eastern & Byzantine'
    assert _category_name('Western & Medieval Theology') == 'Western & Medieval'


def test_category_name_passes_unknown_value_through():
    assert _category_name('Uncategorized') == 'Uncategorized'


def test_preview_prefers_sentence_boundary():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 70) + '. ' + 'b' * 200
    p = _preview(text)
    assert p == 'a' * (n - 70) + '.'


def test_preview_falls_back_to_word_cut():
    text = 'word ' * 200
    p = _preview(text)
    assert p.endswith('…')
    assert len(p) <= catena_reader._PREVIEW_CHARS + 1


def test_preview_ignores_too_early_sentence_break():
    text = 'Short. ' + 'a' * 400
    assert _preview(text).endswith('…')


def test_preview_word_cut_sheds_clause_punctuation():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 8) + ' flesh, and more words beyond the window'
    p = _preview(text)
    assert p.endswith('flesh…')


def test_preview_word_cut_sheds_dangling_dash_and_its_space():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 9) + ' earth - the Lord, the God of hosts'
    p = _preview(text)
    assert p.endswith('earth…')


def test_preview_never_doubles_a_source_ellipsis():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 9) + ' earth … and more words beyond the window'
    p = _preview(text)
    assert p.endswith('earth …')
    assert not p.endswith('……')
