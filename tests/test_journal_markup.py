"""The Markdown subset and the reference parser.

Pure text in, spans out — no display needed, which is the point of keeping
the rules out of the window.
"""
import pytest

import journal_markup as md


def _tags(text, tag):
    return [(a, b) for a, b, t in md.spans(text) if t == tag]


def _text(src, spans_):
    return [src[a:b] for a, b in spans_]


# ── Emphasis ─────────────────────────────────────────────────────────────────

def test_strong_and_its_markers():
    src = 'a **bold** word'
    assert _text(src, _tags(src, 'md-strong')) == ['bold']
    assert _text(src, _tags(src, 'md-marker')) == ['**', '**']


def test_emphasis_and_its_markers():
    src = 'a *quiet* word'
    assert _text(src, _tags(src, 'md-emphasis')) == ['quiet']
    assert _text(src, _tags(src, 'md-marker')) == ['*', '*']


def test_strong_is_not_read_as_two_italics():
    """The inner pair of '**bold**' must not match the emphasis rule."""
    src = '**bold**'
    assert _text(src, _tags(src, 'md-strong')) == ['bold']
    assert _tags(src, 'md-emphasis') == []


def test_emphasis_does_not_cross_a_line_break():
    """A stray '*' three paragraphs up must not italicise the rest of the
    entry — the failure that makes live styling feel broken."""
    src = 'an orphan * here\nand a word there'
    assert _tags(src, 'md-emphasis') == []
    assert _tags(src, 'md-strong') == []


def test_a_lone_asterisk_styles_nothing():
    for src in ('a ** b', 'a * b', '***', 'x*'):
        assert md.spans(src) == [], src


def test_emphasis_needs_something_inside_it():
    assert _tags('a ** b **', 'md-strong') == []


# ── Line roles ───────────────────────────────────────────────────────────────

def test_a_heading_takes_the_whole_line():
    src = '# The Sixth Sunday'
    assert _text(src, _tags(src, 'md-heading')) == ['# The Sixth Sunday']
    assert _text(src, _tags(src, 'md-marker')) == ['# ']


def test_a_blockquote_takes_the_whole_line():
    """An entry is long enough that a quoted passage wants to look quoted —
    the whole reason §6.5 asked for any of this."""
    src = '> For God so loved the world'
    assert _text(src, _tags(src, 'md-quote')) == [src]


def test_both_bullet_characters_make_a_list():
    for src in ('- one thing', '* one thing'):
        assert _text(src, _tags(src, 'md-bullet')) == [src], src


def test_a_star_bullet_is_not_also_an_italic():
    """The '*' opening a bullet would otherwise start an emphasis and
    swallow the rest of the line the moment anyone typed a list."""
    src = '* a bullet with *one* emphasis'
    assert _text(src, _tags(src, 'md-bullet')) == [src]
    assert _text(src, _tags(src, 'md-emphasis')) == ['one']


def test_line_roles_carry_across_a_multi_line_body():
    src = '# Title\n\nplain\n> quoted\n- listed'
    assert _text(src, _tags(src, 'md-heading')) == ['# Title']
    assert _text(src, _tags(src, 'md-quote')) == ['> quoted']
    assert _text(src, _tags(src, 'md-bullet')) == ['- listed']


def test_offsets_are_characters_not_bytes():
    """Gtk.TextBuffer.get_iter_at_offset speaks characters; a Cyrillic body
    would land every span in the wrong place if these were bytes."""
    src = 'слово **жирное** здесь'
    assert _text(src, _tags(src, 'md-strong')) == ['жирное']


# ── References ───────────────────────────────────────────────────────────────

NAMES = {'John': 'John', '1 John': '1 John', 'Juan': 'John',
         'От Иоанна': 'John', 'Romans': 'Romans', 'Rom': 'Romans',
         'Psalms': 'Psalms', 'Ps': 'Psalms'}


def test_a_reference_in_prose_is_found():
    assert md.reference_spans('as in John 3:16 today', NAMES) == [
        (6, 15, 'John', 3, 16)]


def test_the_localized_name_is_found_too():
    """A reader writing in their own language writes the book's own name —
    which is why the localized full names are what this is built on."""
    assert md.reference_spans('véase Juan 3:16', NAMES)[0][2:] == ('John', 3, 16)
    assert md.reference_spans('в От Иоанна 3:16', NAMES)[0][2:] == (
        'John', 3, 16)


def test_the_longest_spelling_wins():
    """'1 John 1:1' must not be read as 'John 1:1' with a stray 1 in front."""
    assert md.reference_spans('1 John 1:1', NAMES) == [(0, 10, '1 John', 1, 1)]


def test_a_chapter_alone_is_a_reference():
    assert md.reference_spans('read Rom 8 again', NAMES)[0][2:] == (
        'Romans', 8, None)


def test_a_full_stop_separator_works():
    assert md.reference_spans('Juan 3.16', NAMES)[0][2:] == ('John', 3, 16)


def test_a_bare_book_name_is_not_a_reference():
    assert md.reference_spans('John said nothing', NAMES) == []


def test_a_sentence_ending_period_is_not_a_verse():
    """'…ends at John 3.' is a chapter and a full stop, not John 3:<nothing>
    and not a parse failure."""
    found = md.reference_spans('it ends at John 3.', NAMES)
    assert found and found[0][2:] == ('John', 3, None)
    assert found[0][1] == len('it ends at John 3')


def test_a_name_inside_a_longer_word_is_not_a_reference():
    assert md.reference_spans('Johnson 3:16 Ltd', NAMES) == []


def test_several_references_in_one_body():
    found = md.reference_spans(
        'compare Romans 6:3 with Ps 23 and John 1:1', NAMES)
    assert [f[2:] for f in found] == [
        ('Romans', 6, 3), ('Psalms', 23, None), ('John', 1, 1)]


def test_no_names_means_no_references():
    """An interface language whose table has not been built yet must not
    crash the body styling."""
    assert md.reference_spans('John 3:16', {}) == []


def test_the_span_covers_exactly_the_reference():
    src = 'see John 3:16 today'
    a, b, _bk, _c, _v = md.reference_spans(src, NAMES)[0]
    assert src[a:b] == 'John 3:16'


# ── The one-line preview ─────────────────────────────────────────────────────

def test_plain_joins_the_paragraphs_and_drops_the_notation():
    """What a list row shows. A row caps its label at two lines, but the cap
    counts SOFT wraps — so an entry of six paragraphs drew six paragraphs and
    the row grew to the length of the writing."""
    body = ('# On Genesis 1\n\n'
            'The first light is **not** the sun.\n\n'
            '> And God said, Let there be light.\n\n'
            '- the order of the days\n')
    assert md.plain(body) == (
        'On Genesis 1 The first light is not the sun. '
        'And God said, Let there be light. the order of the days')


def test_plain_leaves_prose_alone():
    assert md.plain('a plain line') == 'a plain line'


def test_plain_keeps_a_star_that_marks_nothing():
    """An unpaired '*' is not notation, so the preview must not eat it."""
    assert md.plain('2 * 2') == '2 * 2'


def test_preview_parses_only_the_head_of_a_long_entry():
    """A row's label shows two lines; parsing a sermon to fill them cost
    0.30ms an entry against 0.06, and the list renders 200 rows at a time."""
    body = 'word ' * 400
    assert len(md.preview(body)) <= md._PREVIEW_SCAN
    assert md.preview('# short').startswith('short')


# ── Localized abbreviations, from SWORD's own tables ─────────────────────────

def test_sword_carries_a_curated_abbreviation_table():
    """Not invented here: SWORD's locale files map an uppercased spelling to
    an OSIS id, per language. Skipped where SWORD's data is not installed —
    the parser then keeps full names only, which is what it had before."""
    import sword_bridge
    table = sword_bridge.book_abbreviations('es')
    if not table:
        pytest.skip('no SWORD locale data on this machine')
    assert table['JN'] == 'John'
    assert table['GN'] == 'Genesis'


def test_an_unreadable_locale_file_is_survived(tmp_path, monkeypatch):
    """The recovery path itself raised. It logged through `_log`, which this
    module does not have — so a locale in an unexpected encoding turned a
    handled read error into a NameError, out through the reference parser and
    into the restyle timer that calls it. Every reference link in the entry
    being written stops appearing, and nothing on screen says why.
    """
    import sword_bridge
    bad = tmp_path / 'bad.conf'
    bad.write_bytes(b'[Book Abbrevs]\nJN=John\n\xff\xfe not utf-8\n')
    monkeypatch.setattr(sword_bridge, '_locale_files', lambda lang: [bad])
    monkeypatch.setattr(sword_bridge, '_ABBREV_CACHE', {})
    assert sword_bridge.book_abbreviations('xx') == {}


def test_a_russian_abbreviation_reaches_the_matcher():
    import sword_bridge
    if not sword_bridge.book_abbreviations('ru'):
        pytest.skip('no SWORD locale data on this machine')
    names = dict(sword_bridge.book_abbreviations('ru'))
    got = md.reference_spans('см. Ин. 3:16 и далее', names)
    assert [r[2:] for r in got] == [('John', 3, 16)]


def test_an_unknown_language_keeps_the_full_names():
    import sword_bridge
    assert sword_bridge.book_abbreviations('zz-not-a-language') == {}


# ── What Enter carries on ────────────────────────────────────────────────────

def test_list_marker_reads_the_three_that_continue():
    assert md.list_marker('- one') == '- '
    assert md.list_marker('* one') == '* '
    assert md.list_marker('1. one') == '1. '
    assert md.list_marker('12) one') == '12) '
    assert md.list_marker('> quoted') == '> '


def test_a_heading_opens_no_run():
    assert md.list_marker('# Sermon') == ''
    assert md.list_marker('plain prose') == ''


def test_line_marker_reads_the_heading_too():
    """What a new marker has to replace, rather than sit in front of."""
    assert md.line_marker('## Point one') == '## '
    assert md.line_marker('1. one') == '1. '
    assert md.line_marker('plain prose') == ''


def test_the_next_marker_counts_on():
    assert md.next_marker('1. one') == '2. '
    assert md.next_marker('9. nine') == '10. '
    assert md.next_marker('3) three') == '4) '
    assert md.next_marker('- one') == '- '
    assert md.next_marker('# Sermon') == ''


def test_renumber_closes_the_gap_an_inserted_item_left():
    assert md.renumber(['1. one', '2. ', '2. two', '3. three']) == \
        ['1. one', '2. ', '3. two', '4. three']


def test_renumber_keeps_the_run_s_own_first_number():
    assert md.renumber(['3. three', '4. ', '4. four']) == \
        ['3. three', '4. ', '5. four']


def test_renumber_never_numbers_a_line_that_was_not():
    assert md.renumber(['1. one', 'prose']) == ['1. one', 'prose']


def test_what_enter_writes_is_notation_the_renderer_reads():
    """A marker the subset cannot read back would leave the reader looking
    at a literal '2.' in the middle of a list."""
    for line in ('- one', '1. one', '> quoted'):
        made = md.next_marker(line) + 'next'
        assert 'md-bullet' in {t for _a, _b, t in md.spans(made)} or \
            'md-quote' in {t for _a, _b, t in md.spans(made)}
