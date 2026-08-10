"""The figure style of verse and chapter numbers, switched without a render.

Old-style and lining figures are one OpenType feature over spans the render
already marks, so the toggle need not rebuild the chapter — but the feature
arrives on a tag `insert_markup` named after its own value, which is no more
mutable than the colour tags next door. Same answer: adopt the spans into a tag
of ours and set the feature on that.

No widgets: the pane's own methods are borrowed onto a stand-in, as in
test_focus_unit.
"""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk  # noqa: E402

from pane import BiblePane, _numeral_features  # noqa: E402


class Pane:
    """Enough pane to hold a rendered chapter's numerals."""

    _NUMERAL_TAG = BiblePane._NUMERAL_TAG
    _adopt_numerals = BiblePane._adopt_numerals
    _restyle_numerals = BiblePane._restyle_numerals
    _tag_ranges = BiblePane._tag_ranges

    def __init__(self, oldstyle=True):
        self._buffer = Gtk.TextBuffer()
        self._oldstyle_nums = oldstyle
        self._reading_anchor = None
        self.applied = []

    def _capture_scroll_anchor(self):
        return None

    def _apply_scroll_anchor(self, anchor):
        self.applied.append(anchor)


def features(buf):
    """The feature actually in force at each character — the last tag that
    sets one, which is how GTK resolves it."""
    out = []
    for off in range(buf.get_char_count()):
        val = None
        for tag in buf.get_iter_at_offset(off).get_tags():
            if tag.get_property('font-features-set'):
                val = tag.get_property('font-features')
        out.append(val)
    return out


def tag_names(buf):
    names = []
    buf.get_tag_table().foreach(lambda t, _d=None:
                                names.append(t.get_property('name')), None)
    return names


def _chapter(oldstyle=True):
    p = Pane(oldstyle=oldstyle)
    ff = _numeral_features(oldstyle)
    p._buffer.insert_markup(
        p._buffer.get_end_iter(),
        f'<span font_features="{ff}">Genesis 2</span>\n'
        f'<span foreground="gray" font_features="{ff}"> 1 </span>Thus'
        f'<span foreground="gray" font_features="{ff}"> 2 </span>And',
        -1)
    return p


def test_adoption_leaves_the_figures_as_they_were():
    p = _chapter(oldstyle=True)
    before = features(p._buffer)

    p._adopt_numerals(True)

    assert features(p._buffer) == before
    assert p._NUMERAL_TAG in tag_names(p._buffer)
    assert not [n for n in tag_names(p._buffer)
                if (n or '').startswith('font_features')]


def test_the_heading_and_every_verse_number_are_carried_over():
    """The chapter heading and each verse number arrive on ONE parser tag —
    adopting a single range would leave the rest on the old figures."""
    p = _chapter(oldstyle=True)
    p._adopt_numerals(True)
    ours = p._buffer.get_tag_table().lookup(p._NUMERAL_TAG)
    assert len(p._tag_ranges(ours)) == 3


def test_restyling_switches_the_figures_in_place():
    p = _chapter(oldstyle=True)
    p._adopt_numerals(True)
    text_before = p._buffer.get_text(p._buffer.get_start_iter(),
                                     p._buffer.get_end_iter(), False)

    p._oldstyle_nums = False
    assert p._restyle_numerals() is True

    assert set(f for f in features(p._buffer) if f) == {'lnum=1'}
    assert p._buffer.get_text(p._buffer.get_start_iter(),
                              p._buffer.get_end_iter(), False) == text_before


def test_a_surface_with_no_numerals_asks_for_a_render():
    """A devotional or a generic book has nothing adopted. Answering True
    there would silently drop the setting until the next navigation."""
    p = Pane()
    p._buffer.insert(p._buffer.get_end_iter(), 'Morning and Evening')
    assert p._restyle_numerals() is False


def test_restyling_does_not_touch_the_scroll():
    """The figures do not reflow the line, measured on three faces — so this
    path must leave the reading position alone entirely. Re-asserting an
    anchor here threw the reader 2504px up Psalm 119."""
    p = _chapter(oldstyle=True)
    p._adopt_numerals(True)
    p._reading_anchor = (2, 5, 12.0)

    p._oldstyle_nums = False
    p._restyle_numerals()

    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)
    assert p.applied == []
