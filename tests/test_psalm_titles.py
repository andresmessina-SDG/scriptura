"""Psalm superscriptions and Psalm 119's letters — Scripture, not headings.

SWORD moves every preverse title out of the verse text into the entry
attributes. Section headings were read back from there; the canonical
titles were filtered out with them and never drawn, so KJV, ASV, BSB and LEB
each lost all 116 superscriptions and KJV lost Psalm 119's letters.

They are parsed apart from the headings so the headings toggle, the sense
units and export never treat them as editorial matter, and they are set as
Scripture: italic, a shade smaller, on their own line, with the supplied words
inside turned upright as printed KJVs do.

No widgets beyond a TextBuffer: the pane's own method is borrowed onto a
stand-in, as in test_footnote_markers.
"""
import re

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango  # noqa: E402

from pane import BiblePane, _HEADING_TAG, _TITLE_TAG  # noqa: E402
from sword_bridge import _scripture_titles_from_raw, _titles_from_raw  # noqa: E402

# Real preverse blobs, trimmed: KJV Psalm 51, LEB Psalm 51, BSB Psalm 51,
# KJV Psalm 119:9.
KJV_51 = ('<title canonical="true" type="psalm"><w lemma="strong:H05329">To the '
          'chief Musician</w>, <w lemma="strong:H04210">A Psalm</w> '
          '<w lemma="strong:H01732">of David</w>.</title> ')
LEB_51 = ('<title type="x-s">A Prayer of Repentance and Plea for Mercy</title> '
          '<div sID="gen7716" type="x-p"/> <div eID="gen7716" type="x-p"/> '
          '<lg sID="gen7717"/> <lg eID="gen7717"/> '
          '<title canonical="true" type="psalm">For the <transChange '
          'type="added">music</transChange> director. A psalm of David.</title> '
          '<lg sID="gen7718"/> <l level="1" sID="gen7719"/>When Nathan the '
          'prophet came to him, after he had gone in to Bathsheba.'
          '<note placement="foot" swordFootnote="1"></note>'
          '<l eID="gen7719" level="1"/> <l level="1" sID="gen7720"/> ')
BSB_51 = ('<title type="parallel"> (<reference osisRef="2Sam.12.1-2Sam.12.12" '
          'type="parallel">2 Samuel 12:1–12</reference>) </title> '
          '<title canonical="true" type="psalm">For the choirmaster. A Psalm of '
          'David.</title> <lg sID="gen13115"/> <l level="1" sID="gen13116"/>')
KJV_119_9 = ('<title canonical="true" type="acrostic"><foreign xml:lang="hbo">'
             'ב BETH.</foreign></title> ')


def plain(markup):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', markup)).strip()


# ── parsing ──────────────────────────────────────────────────────────────

def test_superscription_is_read():
    assert [plain(t) for t in _scripture_titles_from_raw(KJV_51)] \
        == ['To the chief Musician, A Psalm of David.']


def test_acrostic_letter_is_read():
    assert [plain(t) for t in _scripture_titles_from_raw(KJV_119_9)] \
        == ['ב BETH.']


def test_superscription_keeps_its_supplied_word_markup():
    # The pane turns these upright inside the italic line; it needs the tag.
    assert 'transChange' in _scripture_titles_from_raw(LEB_51)[0]


def test_text_after_the_title_belongs_to_the_superscription():
    # LEB carries the rest of its superscription as a poetry line after the
    # title, still before verse 1 — half the superscription without this.
    (title,) = _scripture_titles_from_raw(LEB_51)
    assert plain(title) == ('For the music director. A psalm of David. When '
                            'Nathan the prophet came to him, after he had gone '
                            'in to Bathsheba.')


def test_section_and_parallel_titles_are_not_scripture():
    assert _scripture_titles_from_raw(
        '<title type="x-s">A Prayer of Repentance</title>') == []
    assert [plain(t) for t in _scripture_titles_from_raw(BSB_51)] \
        == ['For the choirmaster. A Psalm of David.']


def test_headings_still_skip_the_superscription():
    # The two readers split one blob; neither may take the other's title.
    assert _titles_from_raw(LEB_51) == ['A Prayer of Repentance and Plea for Mercy']


def test_empty_title_is_dropped():
    assert _scripture_titles_from_raw('<title type="psalm">  </title>') == []


# ── setting it in the reading text ───────────────────────────────────────

def title(raw):
    """The title the pane is handed: the parsed body, not the raw blob."""
    (body,) = _scripture_titles_from_raw(raw)
    return body


class Pane:
    """Enough pane to set a title into a buffer."""

    _insert_scripture_title = BiblePane._insert_scripture_title

    def __init__(self, text=''):
        self._buffer = Gtk.TextBuffer()
        self._buffer.set_text(text)
        self._smallcaps_divine = True
        self._show_headings = False

    def text(self):
        b = self._buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def iter_at(self, word):
        return self._buffer.get_iter_at_offset(self.text().index(word))


def style_at(it):
    """The italic/upright style that wins at `it` — highest-priority tag."""
    style = Pango.Style.NORMAL
    for tag in it.get_tags():
        if tag.get_property('style-set'):
            style = tag.get_property('style')
    return style


def test_title_takes_its_own_line_under_the_chapter_heading():
    pane = Pane('Psalms 51\n')
    pane._insert_scripture_title(title(KJV_51), False)
    assert pane.text() == 'Psalms 51\nTo the chief Musician, A Psalm of David.\n'


def test_title_mid_chapter_breaks_the_line_before_it():
    # Psalm 119:9 starts mid-paragraph in KJV; the letter must not run on
    # after "utterly." on the same line.
    pane = Pane('O forsake me not utterly. ')
    pane._insert_scripture_title(title(KJV_119_9), False)
    assert pane.text().startswith('O forsake me not utterly. \n')
    assert pane.text().endswith('BETH.\n')


def test_title_is_italic_and_supplied_words_are_upright():
    pane = Pane()
    pane._insert_scripture_title(title(LEB_51), False)
    assert style_at(pane.iter_at('For the')) == Pango.Style.ITALIC
    assert style_at(pane.iter_at('music')) == Pango.Style.NORMAL
    assert style_at(pane.iter_at('director')) == Pango.Style.ITALIC


def test_title_is_never_hidden_with_the_headings():
    pane = Pane()
    pane._insert_scripture_title(title(KJV_51), False)
    heading = pane._buffer.get_tag_table().lookup(_HEADING_TAG)
    if heading is not None:
        assert not pane._buffer.get_start_iter().has_tag(heading)


def test_acrostic_line_stays_left_to_right():
    # A line opening on a Hebrew letter is laid out right-to-left by GTK —
    # "א ALEPH." drew reversed against the right edge. A left-to-right mark
    # ahead of the letter keeps the line's direction with the reading text.
    pane = Pane()
    pane._insert_scripture_title(title(KJV_119_9), False)
    assert pane.text() == '‎ב BETH.\n'


def test_superscription_gets_no_direction_mark():
    pane = Pane()
    pane._insert_scripture_title(title(KJV_51), False)
    assert '‎' not in pane.text()


def test_hebrew_letter_is_set_in_the_hebrew_face():
    pane = Pane()
    pane._insert_scripture_title(title(KJV_119_9), False)
    families = [t.get_property('family') or ''
                for t in pane.iter_at('ב').get_tags()
                if t.get_property('family-set')]
    assert any('Hebrew' in f for f in families)


def test_title_row_is_named_for_the_place_probes():
    # The coarse "topmost verse" probe finds no verse on a title row, by
    # design; the scroll-stability sweep tells that row apart by this tag.
    pane = Pane('Psalms 51\n')
    pane._insert_scripture_title(title(KJV_51), False)
    tag = pane._buffer.get_tag_table().lookup(_TITLE_TAG)
    assert pane.iter_at('To the chief').has_tag(tag)
    assert not pane._buffer.get_start_iter().has_tag(tag)
