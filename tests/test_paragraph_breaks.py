"""Paragraph breaks in Bible text.

Every Bible ran each chapter as one block outside poetry: the KJV's ¶
milestone was stripped with the other tags, and a paragraph closed at a
verse's end lost its blank line to the verse's own strip. A verse now opens
a paragraph when the KJV marks it, or when the verse before closes one; the
break is half a line, the stanza gap.

No widgets beyond a TextBuffer: the pane's own methods are borrowed onto a
stand-in, as in test_psalm_titles.
"""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402

from pane import BiblePane, _HEADING_TAG, _PARA_END_RE, _PARA_OPEN_RE  # noqa: E402

# Real rendered verses, trimmed: KJV Matthew 5:13 and 5:14, LEB 5:2,
# SBLGNT 5:2, RusSynodalLIO 5:2, the KJV2006 eBible 5:13, LEB with a break
# inside a verse.
KJV_13 = ('<q marker="" who="Jesus"><milestone marker="¶" type="x-p"/>'
          '<w savlm="strong:G4771" src="1">Ye</w> are the salt')
KJV_14 = '<q marker="" who="Jesus"><w savlm="strong:G4771">Ye</w> are the light'
LEB_2 = 'And opening his mouth he began to teach them, saying,  <div eID="gen25712" type="x-p"/>'
SBLGNT_2 = ('<w>λέγων</w><seg type="x-punct">·</seg><div eID="gen29" '
            'type="paragraph"/> <div sID="gen30" type="paragraph"/>')
LIO_2 = ('И Он, отверзши уста Свои, учил их, говоря:  <div eID="gen3435" '
         'type="paragraph"/> <div eID="gen3434" type="section"/>')
KJV2006_13 = '<q who="Jesus">¶ Ye are the salt of the earth'
MID = 'the end. <div eID="g1" type="x-p"/> <div sID="g2" type="x-p"/>And then'


def test_kjv_milestone_opens_a_paragraph():
    assert _PARA_OPEN_RE.match(KJV_13)
    assert not _PARA_OPEN_RE.match(KJV_14)


def test_bare_pilcrow_opens_a_paragraph():
    assert _PARA_OPEN_RE.match(KJV2006_13)


def test_paragraph_closed_at_verse_end():
    for verse in (LEB_2, SBLGNT_2, LIO_2):
        assert _PARA_END_RE.search(verse), verse


def test_break_inside_a_verse_is_not_a_verse_end():
    assert not _PARA_END_RE.search(MID)
    assert not _PARA_OPEN_RE.match(MID)


def test_section_close_alone_is_not_a_paragraph():
    assert not _PARA_END_RE.search('text <div eID="g" type="section"/>')


class Pane:
    """Enough pane to break a paragraph in a buffer."""

    _break_paragraph = BiblePane._break_paragraph
    _halve_blank_lines = BiblePane._halve_blank_lines

    def __init__(self, text=''):
        self._buffer = Gtk.TextBuffer()
        self._buffer.set_text(text)
        self._poetry_tags = {0: self._buffer.create_tag('poetry_gap')}

    def _ensure_poetry_tags(self):
        pass

    def text(self):
        b = self._buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def gap_lines(self):
        """Indices of the lines that wear the half-line gap."""
        gap = self._poetry_tags[0]
        out = []
        for n in range(self._buffer.get_line_count()):
            _ok, it = self._buffer.get_iter_at_line(n)
            if it.has_tag(gap):
                out.append(n)
        return out


def test_break_drops_the_separating_space_and_halves_the_gap():
    pane = Pane(' 12 before you. ')
    pane._break_paragraph(pane._buffer.get_char_count())
    assert pane.text() == ' 12 before you.\n\n'
    assert pane.gap_lines() == [1]


def test_no_break_where_the_line_already_ended():
    # A heading or a closed poetry line leaves the buffer at a line start.
    pane = Pane('Salt and Light\n')
    pane._break_paragraph(pane._buffer.get_char_count())
    assert pane.text() == 'Salt and Light\n'
    assert pane.gap_lines() == []


def test_blank_line_inside_a_verse_gets_the_same_gap():
    pane = Pane(' 4 Heading line\n')
    mark = pane._buffer.create_mark(None, pane._buffer.get_end_iter(), True)
    pane._buffer.insert(pane._buffer.get_end_iter(), ' 5 the end.\n\nAnd then ')
    pane._halve_blank_lines(mark)
    assert pane.gap_lines() == [2]


def test_a_hidden_heading_keeps_the_line_break():
    # Headings off hides the heading's newlines with it, and BSB Matthew
    # 5:12-13 ran on as one line. The first newline stays out of the hidden
    # range, so the paragraph still starts a line.
    pane = Pane(' 12 before you. ')
    heads_from = pane._buffer.get_char_count()
    hidden = pane._buffer.create_tag(_HEADING_TAG, invisible=True)
    pane._buffer.insert_with_tags(pane._buffer.get_end_iter(),
                                  '\n\nSalt and Light\n', hidden)
    pane._break_paragraph(heads_from)
    first = pane._buffer.get_iter_at_offset(heads_from)
    assert first.get_char() == '\n'
    assert not first.has_tag(hidden)
    second = first.copy()
    second.forward_char()
    assert second.has_tag(hidden)
