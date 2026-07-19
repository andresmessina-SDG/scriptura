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
