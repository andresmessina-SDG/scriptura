"""The marks a verse wears, and the order they go on in.

The render loop used to inline these as seven consecutive `if`s, so every new
per-verse feature meant another branch in the middle of the one loop where an
ordering mistake is hardest to see. They are now `_VERSE_DECORATIONS`, walked
by `_decorate_verse`.

Two things have to hold, and neither is visible in a rendered chapter until it
is already wrong. The ORDER is load-bearing twice: the artifact marker inserts
a character, so it must land before `vnum` measures the block's end, and
`strong_words` reads the text up to the end, so it must come after everything
that adds to it. And the COMMENTARY GATE has to stay on every entry but
`vnum` — a commentary renders one block per section, and a mark meant for a
verse lands on the wrong text there.

No widgets: the pane's methods are borrowed onto a stand-in, as in
test_theme_ink.
"""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402

from pane import (BiblePane, _VERSE_DECORATIONS,  # noqa: E402
                  _VerseDecoration, _VerseRender)


class Pane:
    """Just enough pane to record which decorations fired."""

    _decorate_verse = BiblePane._decorate_verse
    _apply_vnum_tags = BiblePane._apply_vnum_tags

    def __init__(self, commentary=False, lexicon=True):
        self._buffer = Gtk.TextBuffer()
        self._lexicon_enabled = lexicon
        self._on_word_click = (lambda *a: None) if lexicon else None
        self.fired = []

    # Every applier the registry can reach, recording instead of acting.
    def _apply_dropcap_tag(self, *a):
        self.fired.append('dropcap')

    def _apply_footnote_tags(self, *a):
        self.fired.append('footnotes')

    def _apply_poetry_line_tags(self, *a):
        self.fired.append('poetry_lines')

    def _insert_artifact_marker(self, *a):
        self.fired.append('artifact_marker')

    def _insert_lineage_marker(self, *a):
        self.fired.append('lineage_marker')

    def _apply_anno_tags(self, *a, **k):
        self.fired.append('annotations')

    def _tag_strong_words(self, *a):
        self.fired.append('strong_words')


def _loaded(pane, commentary=False):
    """A verse record with every decoration's condition satisfied."""
    pane._buffer.set_text('In the beginning God created')
    r = _VerseRender(1, 1, '<w>In</w>', commentary)
    r.start_mark = pane._buffer.create_mark(
        None, pane._buffer.get_start_iter(), True)
    r.text_mark = pane._buffer.create_mark(
        None, pane._buffer.get_iter_at_offset(3), True)
    r.anno = {'highlight': 'yellow'}
    r.has_artifact = True
    r.has_lineage = True
    r.cap_index = 0
    r.fn_markers = [(4, '1', 'a')]
    r.vnotes = {'1': ('t', 'body')}
    r.poetry_lines = {0: 1}
    return r


ORDER = ('dropcap', 'footnotes', 'poetry_lines', 'artifact_marker',
         'lineage_marker', 'vnum', 'annotations', 'strong_words')


def test_the_registry_is_the_order_the_loop_applied():
    assert tuple(d.name for d in _VERSE_DECORATIONS) == ORDER


def test_the_lineage_marker_also_lands_before_vnum():
    """Same reason as the artifact marker below: it INSERTS a character, and
    a chapter can carry both."""
    names = [d.name for d in _VERSE_DECORATIONS]
    assert names.index('lineage_marker') < names.index('vnum')


def test_the_artifact_marker_lands_before_vnum_measures_the_block():
    """It INSERTS a character. Tagged after it, `vnum` would stop short of the
    marker and the verse would end one character early — which is what
    `_verse_ranges` reads back for the highlight band and the indicator."""
    names = [d.name for d in _VERSE_DECORATIONS]
    assert names.index('artifact_marker') < names.index('vnum')


def test_strong_words_runs_last():
    """It reads from `text_mark` to the buffer end, so anything that appends
    to the verse has to have appended already."""
    assert _VERSE_DECORATIONS[-1].name == 'strong_words'


def test_a_bible_verse_wears_every_mark():
    p = Pane()
    p._decorate_verse(_loaded(p))
    assert p.fired == [n for n in ORDER if n != 'vnum']
    assert p._buffer.get_tag_table().lookup('vnum_1') is not None


def test_a_commentary_section_wears_only_its_anchor():
    """One block per section, its own `Verse N` header instead of a number,
    and no user annotations — so every mark but the anchor is a mark on the
    wrong text."""
    p = Pane()
    p._decorate_verse(_loaded(p, commentary=True))
    assert p.fired == []
    assert p._buffer.get_tag_table().lookup('vnum_1') is not None


def test_every_entry_but_the_anchor_excludes_commentaries():
    """Stated against the registry rather than a run, so a new entry that
    forgets the gate fails here even if nothing exercises it yet."""
    r = _VerseRender(1, 1, '', is_commentary=True)
    r.has_artifact = True
    r.has_lineage = True
    r.cap_index = 0
    r.fn_markers = [(0, '1', 'a')]
    r.poetry_lines = {0: 1}
    r.anno = {'highlight': 'yellow'}
    p = Pane()
    on = [d.name for d in _VERSE_DECORATIONS if d.on(p, r)]
    assert on == ['vnum']


def test_a_grouped_section_answers_to_every_verse_in_its_range():
    """MHC returns one block for a whole section; navigating to any verse in
    it has to land here."""
    p = Pane()
    p._buffer.set_text('The whole section text')
    r = _VerseRender(3, 7, '', is_commentary=True)
    r.start_mark = p._buffer.create_mark(
        None, p._buffer.get_start_iter(), True)

    p._apply_vnum_tags(r)

    table = p._buffer.get_tag_table()
    assert [v for v in range(1, 10) if table.lookup(f'vnum_{v}')] == [3, 4, 5, 6, 7]


def test_the_lexicon_switch_still_gates_strong_words():
    p = Pane(lexicon=False)
    p._decorate_verse(_loaded(p))
    assert 'strong_words' not in p.fired


def test_an_unannotated_verse_is_skipped_not_cleared():
    """On a fresh buffer there is nothing to clear, and the per-verse call was
    the chapter render's main scaling cost."""
    p = Pane()
    r = _loaded(p)
    r.anno = {}
    p._decorate_verse(r)
    assert 'annotations' not in p.fired


def test_a_decoration_with_no_condition_is_always_on():
    d = _VerseDecoration('always', lambda p, r: None)
    assert d.on(None, _VerseRender(1, 1, '', False)) is True
