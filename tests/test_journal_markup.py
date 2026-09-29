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
    for src in ('a ** b', 'a * b', 'x*', '**'):
        assert md.spans(src) == [], src


def test_emphasis_needs_something_inside_it():
    assert _tags('a ** b **', 'md-strong') == []


# ── Line roles ───────────────────────────────────────────────────────────────

def test_a_heading_takes_the_whole_line():
    src = '# The Sixth Sunday'
    assert _text(src, _tags(src, 'md-heading')) == ['# The Sixth Sunday']
    assert _text(src, _tags(src, 'md-marker')) == ['# ']


def test_levels_four_to_six_are_one_subheading():
    """A study guide's `####` sections, and our own export's — it pushes an
    entry's `##` down to `####` — showed as literal hashes."""
    for src in ('#### Arrival', '##### Arrival', '###### Arrival'):
        assert _text(src, _tags(src, 'md-subheading')) == [src], src
        assert _tags(src, 'md-heading') == [], src
        assert _text(src, _tags(src, 'md-marker')) == [src[:-len('Arrival')]]


def test_seven_hashes_are_not_a_heading():
    assert md.spans('####### Arrival') == []


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


def test_an_abbreviation_may_carry_a_full_stop():
    """Chicago, SBL in print and every study guide write "Rom. 10:9"."""
    names = dict(NAMES, **{'1 Cor': '1 Corinthians'})
    for src, want in (('Rom. 10:9', ('Romans', 10, 9)),
                      ('Rom.10:9', ('Romans', 10, 9)),
                      ('1 Cor. 15:20', ('1 Corinthians', 15, 20))):
        found = md.reference_spans(src, names)
        assert [f[2:] for f in found] == [want], src
        assert src[found[0][0]:found[0][1]] == src, src


def test_a_sentence_ending_on_a_name_is_not_a_reference():
    """Without a verse after it, a full stop ends the sentence."""
    assert md.reference_spans('we read John. 3 of us stayed', NAMES) == []
    assert md.reference_spans('see Rom. 8 again', NAMES) == []


def test_a_relative_verse_takes_the_passage_above():
    src = 'Luke 8:41-56. In v. 48 he says it; vv. 45-46 come first.'
    names = {'Luke': 'Luke'}
    found = md.reference_spans(src, names)
    assert [f[2:] for f in found] == [
        ('Luke', 8, 41), ('Luke', 8, 48), ('Luke', 8, 45)]
    assert [src[a:b] for a, b, *_ in found] == ['Luke 8:41', 'v. 48', 'vv. 45']


def test_a_relative_verse_follows_the_nearest_passage_above():
    src = 'John 3:1, v. 5, then Rom 6:3 and v. 4'
    assert [f[2:] for f in md.reference_spans(src, NAMES)] == [
        ('John', 3, 1), ('John', 3, 5), ('Romans', 6, 3), ('Romans', 6, 4)]


def test_a_relative_verse_with_nothing_above_links_nothing():
    """Never a guess: no passage named yet, no link — not even to one named
    further down."""
    assert md.reference_spans('v. 48 first, then John 3:16', NAMES) == [
        (18, 27, 'John', 3, 16)]
    assert md.reference_spans('in v. 48', NAMES) == []


def test_a_word_ending_in_v_is_not_a_relative_verse():
    assert [f[2:] for f in md.reference_spans(
        'John 3:1 and Rev. 2 then Lev. 3', NAMES)] == [('John', 3, 1)]


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
    assert md.line_marker('#### Arrival') == '#### '
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


# ── Rules ────────────────────────────────────────────────────────────────────

def test_three_or_more_of_one_mark_is_a_rule():
    for src in ('---', '***', '___', '- - -', '* * *', '-----'):
        assert _tags(src, 'md-rule') == [(0, len(src))], src
        assert _tags(src, 'md-marker') == [(0, len(src))], src


def test_a_rule_is_not_a_list_or_emphasis():
    """`* * *` would otherwise be a bullet whose text is two stars."""
    assert _tags('* * *', 'md-bullet') == []
    for src in ('--', '-- x', '- item', '**', '-*-'):
        assert _tags(src, 'md-rule') == [], src


# ── Pasting from a web page ──────────────────────────────────────────────────

def test_paste_keeps_what_the_subset_can_say():
    html = ('<h2>Arrival</h2><p>Jesus <b>went</b> with <i>him</i>.</p>'
            '<ul><li>one</li><li>two</li></ul>'
            '<blockquote><p>Go in peace.</p></blockquote><hr>'
            '<ol><li>first</li><li>second</li></ol>')
    assert md.from_html(html) == (
        '## Arrival\n\nJesus **went** with *him*.\n\n- one\n- two\n\n'
        '> Go in peace.\n\n---\n\n1. first\n2. second')


def test_paste_closes_emphasis_against_the_words():
    """'** went **' is notation the subset will not read back."""
    assert md.from_html('<p>Jesus<b> went </b>on</p>') == 'Jesus **went** on'


def test_paste_reads_google_docs_styles():
    """Docs says bold with font-weight:700 on a span, and wraps the whole
    paste in a <b> that it marks font-weight:normal."""
    html = ('<b style="font-weight:normal" id="docs-internal-guid-x"><p>'
            '<span style="font-weight:700">Bold</span> plain '
            '<span style="font-style:italic">slanted</span></p></b>')
    assert md.from_html(html) == '**Bold** plain *slanted*'


def test_paste_drops_what_it_cannot_say():
    html = ('<style>p{color:red}</style><script>x()</script>'
            '<p><a href="https://example.com">a link</a> and '
            '<img src="x.png"> <span style="color:blue">colour</span></p>')
    assert md.from_html(html) == 'a link and colour'


def test_paste_writes_verse_numbers_as_superscripts():
    """Bible sites set verse numbers in <sup>; run into the text they read
    as "16For God"."""
    assert md.from_html('<p><sup>16</sup>For God so loved</p>') == \
        '¹⁶For God so loved'


def test_paste_keeps_line_breaks_inside_a_paragraph():
    assert md.from_html('<p>one<br>two</p>') == 'one\ntwo'


def test_paste_collapses_html_whitespace():
    assert md.from_html('<p>  one\n   two  </p>') == 'one two'


#: What OnlyOffice put on the clipboard for a Heading and two bullets,
#: trimmed of its data blob and border noise: no <h1>, only a larger size.
_ONLYOFFICE = (
    '<p style="margin-top:8pt;margin-bottom:4pt" class="docData;DOCY;v5;1;B">'
    '<span style="font-family:\'Arial\';font-size:16pt;color:#0f4761">'
    '<b>How to use maps</b></span></p>'
    '<ul style="padding-left:40px"><li style="list-style-type: disc">'
    '<p style="margin-left:36pt;text-indent:-18pt">'
    '<span style="font-family:\'Arial\';font-size:10pt"><b>Compass rose:</b>'
    '</span><span style="font-family:\'Arial\';font-size:10pt"> the symbol '
    'on a map that shows direction.</span></p></li>'
    '<li style="list-style-type: disc"><p style="margin-left:36pt">'
    '<span style="font-family:\'Arial\';font-size:12pt">A compass is '
    'numbered in degrees.</span></p></li></ul>')


def test_paste_keeps_bullets_whose_text_sits_in_a_paragraph():
    """OnlyOffice, Word and Google Docs all write <li><p>…</p></li>; the
    <p> cleared the bullet before any of its words arrived."""
    assert md.from_html('<ul><li><p>one</p></li><li><p>two</p></li></ul>'
                        '<p>after</p>') == '- one\n- two\n\nafter'
    assert md.from_html('<ol><li><p>first</p></li><li><p>second</p></li>'
                        '</ol>') == '1. first\n2. second'


def test_paste_reads_a_heading_from_its_size_when_it_has_no_tag():
    assert md.from_html(_ONLYOFFICE) == (
        '# How to use maps\n\n'
        '- **Compass rose:** the symbol on a map that shows direction.\n'
        '- A compass is numbered in degrees.')


def test_paste_ranks_untagged_headings_against_the_body():
    """Word's own sizes over its 11pt body: 20, 16 and 14pt."""
    def p(size, text):
        return f'<p><span style="font-size:{size}pt">{text}</span></p>'
    html = (p(20, 'One') + p(11, 'Body text here.') + p(16, 'Two')
            + p(14, 'Three') + p(11, 'More body text, and then some.'))
    assert md.from_html(html) == (
        '# One\n\nBody text here.\n\n## Two\n\n### Three\n\n'
        'More body text, and then some.')


def test_a_manuscript_set_large_throughout_has_no_headings():
    """Sermon manuscripts are often 14pt from top to bottom; size alone,
    measured against nothing, would make every paragraph a heading."""
    html = ''.join(f'<p><span style="font-size:14pt">{t}</span></p>'
                   for t in ('The sower went out.', 'And some fell.'))
    assert md.from_html(html) == 'The sower went out.\n\nAnd some fell.'


def test_a_web_page_copied_with_its_styles_gains_no_headings():
    """A browser copies computed styles, in px: a page's large intro
    paragraph is design, and its real headings arrive as <h2>."""
    html = ('<h2 style="font-size: 28px">Arrival</h2>'
            '<p style="font-size: 22px">A short, larger intro.</p>'
            '<p style="font-size: 16px">The body of the article, which runs '
            'on for longer than the intro does.</p>')
    assert md.from_html(html) == (
        '## Arrival\n\nA short, larger intro.\n\n'
        'The body of the article, which runs on for longer than the intro '
        'does.')


def test_a_libreoffice_line_set_large_by_hand_is_a_heading():
    """LibreOffice's clipboard, exported from a document whose heading was
    made by enlarging a line, not by a Heading style."""
    html = ('<p><font face="Liberation Serif, serif"><font size="3" '
            'style="font-size: 12pt">Some fell upon stony places.</font>'
            '</font></p><p><font face="Liberation Serif, serif"><font '
            'size="5" style="font-size: 20pt"><b>The rock</b></font></font>'
            '</p><p><font size="3" style="font-size: 12pt">Where they had '
            'not much earth.</font></p>')
    assert md.from_html(html) == (
        'Some fell upon stony places.\n\n# The rock\n\n'
        'Where they had not much earth.')


def test_a_bold_line_at_body_size_stays_bold():
    html = ('<p><span style="font-size:11pt"><b>Note:</b></span></p>'
            '<p><span style="font-size:11pt">Body.</span></p>')
    assert md.from_html(html) == '**Note:**\n\nBody.'


def test_paste_of_nothing_is_nothing():
    assert md.from_html('<p> </p><div></div>') == ''


_TABLE_ENTRY = ('Intro line.\n\n| Soil | Fruit |\n|---|---|\n'
                '| **path** | none |\n| good | a hundredfold |\n\nAfter.')


def test_a_table_previews_as_its_cells_row_by_row():
    """The row showed "| Soil | Fruit | |---|---| | path | none |"."""
    assert md.preview(_TABLE_ENTRY) == (
        'Intro line. Soil, Fruit · path, none · good, a hundredfold After.')


def test_a_tables_pipes_and_delimiter_row_are_not_words():
    """The count read 20 words in an entry of 10."""
    assert md.plain(_TABLE_ENTRY) == (
        'Intro line. Soil Fruit path none good a hundredfold After.')


def test_export_keeps_a_table_as_markdown():
    """Export writes .md, where the pipes ARE the table."""
    assert md.to_markdown(_TABLE_ENTRY) == _TABLE_ENTRY


def test_preview_leaves_out_headings_and_rules():
    """A row already leads with the title, and a manuscript's first heading
    is usually that title again: "The Sower Four soils Read Mark 4…"."""
    body = ('# The Sower\n\n## Four soils\n\nRead Mark 4:1-9.\n\n---\n\n'
            'Application.')
    assert md.preview(body) == 'Read Mark 4:1-9. Application.'


def test_preview_sets_list_items_apart():
    body = 'Four soils:\n\n1. the path\n2. rocky ground\n- among thorns\n\nThen.'
    assert md.preview(body) == 'Four soils: the path · rocky ground · among thorns Then.'


def test_preview_of_nothing_but_headings_keeps_them():
    assert md.preview('# Only a title\n\n## And a part') == 'Only a title And a part'


# ── Tables ───────────────────────────────────────────────────────────────────

_TABLE = ['| Book | Verse |', '|------|:-----:|', '| John | 3:16 |',
          '| | x |', 'after']


def test_a_table_is_a_header_a_rule_and_its_rows():
    assert md.table_kinds(_TABLE) == ['head', 'rule', 'row', 'row', '']


def test_a_lone_piped_line_is_prose():
    assert md.table_kinds(['a | b', 'no rule under it']) == ['', '']


def test_a_rule_needs_as_many_cells_as_its_header():
    assert md.table_kinds(['a | b | c', '---|---', 'd | e']) == ['', '', '']


def test_a_thematic_break_is_not_a_table_rule():
    assert md.table_kinds(['a | b', '---']) == ['', '']


def test_outer_pipes_are_optional():
    assert md.table_kinds(['a | b', '--- | ---', 'c | d']) == \
        ['head', 'rule', 'row']
    assert md.table_cells('a | b') == md.table_cells('a | b |')


def test_cells_are_their_words_with_the_spaces_trimmed():
    line = '| John | 3:16 |'
    assert [line[s:e] for _p, s, e in md.table_cells(line)] == \
        ['John', '3:16']


def test_an_empty_cell_is_kept_in_its_column():
    assert [(p, s, e) for p, s, e in md.table_cells('| | x |')] == \
        [(0, 1, 1), (2, 4, 5)]


def test_an_escaped_pipe_is_a_character():
    line = r'a \| b | c'
    assert [line[s:e] for _p, s, e in md.table_cells(line)] == \
        [r'a \| b', 'c']


def test_pipes_are_notation_and_a_header_is_strong():
    line = '| Book | **Verse** |'
    spans = md.table_spans(line, 'head')
    pipes = [line[a:b] for a, b, t in spans if t == 'md-pipe']
    assert pipes == ['| ', ' | ', ' |']
    assert ('md-strong', 'Book') in [(t, line[a:b]) for a, b, t in spans]
    markers = [line[a:b] for a, b, t in spans if t == 'md-marker']
    assert markers == ['**', '**']


def test_emphasis_does_not_pair_across_cells():
    line = '| *a | b* |'
    assert not [t for _a, _b, t in md.table_spans(line, 'row')
                if t == 'md-emphasis']


def test_the_rule_is_all_notation():
    line = '|---|---|'
    assert set(md.table_spans(line, 'rule')) == {
        (0, len(line), 'md-table-rule'), (0, len(line), 'md-pipe')}


def test_the_lead_is_what_hangs_in_the_margin():
    assert md.table_lead('| a | b |') == '| '
    assert md.table_lead('a | b') == ''


def test_a_new_row_has_the_header_s_columns():
    row, caret = md.new_table_row('| a | b | c |')
    assert len(md.table_cells(row)) == 3
    assert row[:caret] == '| '
