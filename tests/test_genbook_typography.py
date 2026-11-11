"""Tests for the Generic Books reading-page helpers — the synopsis fence and
the script-run font forcing. All pure functions over HTML/markup strings, so
no widget tree is needed.

The fixtures below are shortened transcriptions of real CCEL Institutes
entries, including the three kinds of source noise measured across the
module: an empty paragraph, an OCR'd lowercase ell for "1.", and an item
that lost its period.
"""

import re

from genbook_reader import _split_synopsis
from pane import _HEBREW_RUN, _html_to_markup


def test_installed_owen_summary_is_separated_without_guessing_other_books():
    from genbook_reader import _split_opening_summary
    html = '<p>The Spirit — means of mortification.</p><p>The next principle.</p>'
    summary, body = _split_opening_summary(html, 'CWPMortification', '/Chapter III')
    assert summary == '<p>The Spirit — means of mortification.</p>'
    assert body == '<p>The next principle.</p>'
    assert _split_opening_summary(html, 'CWPMortification', '/Preface') == ('', html)
    assert _split_opening_summary(html, 'Unrelated', '/Chapter III') == ('', html)


def test_explicit_summary_role_works_for_other_editions():
    from genbook_reader import _split_opening_summary
    html = '<p type="x-summary">The argument.</p><p>The body.</p>'
    assert _split_opening_summary(html, 'AnotherBook', '/Opening') == (
        '<p>The argument.</p>', '<p>The body.</p>')


def test_summary_links_and_body_alignment_survive_the_page_layout():
    import types
    import pytest
    from gi.repository import Gtk, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('builds a reading view; no display here')
    from genbook_reader import GenbookReader
    from pane import BiblePane, theme_ink
    buf = Gtk.TextBuffer()
    view = Gtk.TextView(buffer=buf, justification=Gtk.Justification.FILL)
    pane = types.SimpleNamespace(
        module='CWPMortification', _is_genbook=True, _buffer=buf, view=view,
        _cancel_all_flashes=lambda: None, _clear_chapter_scoped_tags=lambda: None,
        _place_changed=lambda: None,
        _search=types.SimpleNamespace(on_book_render=lambda: False),
        _scroll=types.SimpleNamespace(restore_text_mark=lambda mark, delta=0:
                                      view.scroll_to_mark(mark, 0, True, 0, 0)),
        _INK_ORDER=BiblePane._INK_ORDER,
        _MARKUP_FG_PREFIX=BiblePane._MARKUP_FG_PREFIX)
    pane._paper_ink = lambda dark: {**theme_ink(dark),
                                   '_ink_muted': '#334455', '_ink_link': '#112233'}
    pane._tag_ranges = lambda tag: BiblePane._tag_ranges(pane, tag)
    pane._adopt_theme_ink = lambda dark: BiblePane._adopt_theme_ink(pane, dark)
    pane._insert_ref_segment = lambda *args: BiblePane._insert_ref_segment(pane, *args)
    reader = GenbookReader(pane, _html_to_markup)
    reader._display([('/Chapter III', 'Chapter III', 0)], '/Chapter III',
                    '<p>The Spirit, <reference osisRef="Bible:Ezek.11.19">Ezek 11:19</reference>.</p>'
                    '<p>The next principle.</p>', pane.module)
    text = buf.get_text(*buf.get_bounds(), True)
    assert text.strip() == 'Chapter III\n\nThe Spirit, Ezek 11:19.\n\nThe next principle.'
    summary = buf.get_tag_table().lookup('gb-opening-summary')
    assert summary.props.justification == Gtk.Justification.LEFT
    assert summary.props.scale == 0.9
    assert summary in buf.get_iter_at_offset(text.index('The Spirit')).get_tags()
    assert summary not in buf.get_iter_at_offset(text.index('The next')).get_tags()
    assert view.props.justification == Gtk.Justification.FILL
    assert buf.get_tag_table().lookup('devref:Bible:Ezek.11.19') in \
        buf.get_iter_at_offset(text.index('Ezek')).get_tags()
    colour = Gdk.RGBA(); colour.parse('#112233')
    assert buf.get_tag_table().lookup('_ink_link').props.foreground_rgba.equal(colour)
    colour.parse('#334455')
    assert buf.get_tag_table().lookup('_ink_muted').props.foreground_rgba.equal(colour)
    gap = buf.get_tag_table().lookup('gb-paragraph-gap')
    assert gap.props.scale == 0.5
    assert gap in buf.get_iter_at_offset(text.index('\n\n') + 1).get_tags()


def test_paragraph_gap_tags_keep_child_anchor_offsets():
    import types
    from gi.repository import Gtk
    from genbook_reader import GenbookReader
    buf = Gtk.TextBuffer()
    buf.create_child_anchor(buf.get_end_iter())
    buf.insert(buf.get_end_iter(), '\nSummary\n\nBody')
    before = buf.get_slice(*buf.get_bounds(), True)
    GenbookReader(types.SimpleNamespace(_buffer=buf), _html_to_markup)._set_paragraph_gaps()
    assert buf.get_slice(*buf.get_bounds(), True) == before
    offset = before.index('\n\n') + 1
    assert buf.get_tag_table().lookup('gb-paragraph-gap') in \
        buf.get_iter_at_offset(offset).get_tags()


def test_owens_editorial_notes_do_not_join_the_prose_and_old_refs_link():
    import types
    from gi.repository import Gtk
    from genbook_reader import GenbookReader
    from pane import BiblePane
    pane = types.SimpleNamespace(_buffer=Gtk.TextBuffer())
    pane._insert_ref_segment = lambda *args: BiblePane._insert_ref_segment(pane, *args)
    reader = GenbookReader(pane, _html_to_markup)
    reader._insert_body(
        '<p>motives to<note n="unto">Auto-modernized</note> holiness, '
        '<reference osisRef="Rom.8.13">Romans 8:13</reference>, and '
        '<reference osisRef="Bible:John.3.16">John 3:16</reference>.</p>', False)
    text = pane._buffer.get_text(*pane._buffer.get_bounds(), False)
    assert text.strip() == 'motives to holiness, Romans 8:13, and John 3:16.'
    assert pane._buffer.get_tag_table().lookup('devref:Rom.8.13')
    assert pane._buffer.get_tag_table().lookup('devref:Bible:John.3.16')


def test_a_books_internal_reference_stays_plain_text():
    from genbook_reader import _BIBLE_REF
    assert not _BIBLE_REF.search(
        '<reference osisRef="DarkNight:Chapter1">Chapter 1</reference>')

_CHAPTER = (
    '<p>This chapter consists of two parts: 1. The former divides the work.</p> '
    '<p>Sections.</p> '
    '<p>1. The sum of true wisdom.</p> '
    '<p>2. Effects of the knowledge of God.</p> '
    '<p>3. Effects illustrated by the examples, 1. of patriarchs; 2. of angels.</p> '
    '<p>1. Our wisdom, in so far as it ought to be deemed true and solid '
    'Wisdom, consists almost entirely of two parts.</p> '
    '<p>2. On the other hand, it is evident that man never attains.</p>'
)


def _text(html):
    return re.sub(r'<[^>]+>', ' ', html)


def test_split_fences_on_the_restart_not_the_numbering():
    synopsis, rest = _split_synopsis(_CHAPTER)
    assert 'The sum of true wisdom' in _text(synopsis)
    assert 'Effects illustrated' in _text(synopsis)
    # The body restarts at 1 — that paragraph belongs to the body, not the
    # précis, even though both are "<p>N. …</p>".
    assert 'Our wisdom' in _text(rest)
    assert 'Our wisdom' not in _text(synopsis)


def test_split_absorbs_the_argument_paragraph():
    synopsis, rest = _split_synopsis(_CHAPTER)
    assert 'This chapter consists of two parts' in _text(synopsis)
    assert 'This chapter consists' not in _text(rest)


def test_split_drops_the_marker_paragraph():
    # The disclosure row names the block, so the bare "Sections." line
    # must not survive into either half.
    synopsis, rest = _split_synopsis(_CHAPTER)
    assert 'Sections.' not in _text(synopsis)
    assert 'Sections.' not in _text(rest)


def test_inline_numbering_inside_an_item_does_not_end_the_run():
    # Item 3 contains "1. of patriarchs" mid-sentence; only a paragraph-
    # leading restart is a fence.
    synopsis, _rest = _split_synopsis(_CHAPTER)
    assert 'of angels' in _text(synopsis)


def test_ocr_ell_for_one_still_fences():
    # Institutes III.21 transcribes its first item as "l." (lowercase ell).
    html = _CHAPTER.replace('<p>1. The sum', '<p>l. The sum')
    synopsis, rest = _split_synopsis(html)
    assert 'The sum of true wisdom' in _text(synopsis)
    assert 'Our wisdom' in _text(rest)


def test_unnumbered_item_does_not_end_the_run():
    # "4 Refutation…" (no period) appears mid-précis in IV.15.
    html = _CHAPTER.replace('<p>3. Effects illustrated by the examples, '
                            '1. of patriarchs; 2. of angels.</p>',
                            '<p>4 Refutation of those who share forgiveness.</p>')
    synopsis, rest = _split_synopsis(html)
    assert 'Refutation' in _text(synopsis)
    assert 'Our wisdom' in _text(rest)


def test_empty_paragraphs_are_skipped():
    html = _CHAPTER.replace('<p>2. Effects', '<p></p> <p>2. Effects')
    synopsis, rest = _split_synopsis(html)
    assert 'Effects of the knowledge' in _text(synopsis)
    assert 'Our wisdom' in _text(rest)


def test_a_leading_heading_is_never_absorbed():
    # Five entries defeat _strip_restated_title (footnote cruft in the
    # title); their surviving <h3> is on screen and must stay there.
    html = '<h3>CHAPTER 18. </h3> ' + _CHAPTER
    synopsis, rest = _split_synopsis(html)
    assert 'CHAPTER 18.' in rest
    assert 'CHAPTER 18.' not in synopsis


def test_module_without_a_marker_is_untouched():
    # Concord, Didache and the confessions have no précis at all.
    plain = '<p>1. The Lord is my shepherd.</p> <p>2. He maketh me to lie.</p>'
    assert _split_synopsis(plain) == ('', plain)


def test_marker_without_a_restart_is_untouched():
    # No body follows, so there is no fence to trust — leave the entry alone
    # rather than swallowing it into the disclosure.
    html = '<p>Sections.</p> <p>1. The sum of true wisdom.</p>'
    assert _split_synopsis(html) == ('', html)


def test_pointed_hebrew_is_forced_into_a_hebrew_serif():
    # A Latin reading face carries no niqqud/te'amim positioning.
    markup = _html_to_markup('<p>He said בְּרֵאשִׁ֖ית today.</p>', False)
    assert 'Noto Serif Hebrew' in markup
    assert markup.index('Noto Serif Hebrew') < markup.index('today')


def test_hebrew_run_never_starts_on_latin():
    # A stray combining mark sitting on Latin must not open a run.
    assert not _HEBREW_RUN.findall('Genesis 1:1 a֑b')
