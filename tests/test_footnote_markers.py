"""Showing and hiding footnote markers without rebuilding the chapter.

The markers are ordinary characters, so the toggle used to change the buffer's
text and could only be done by re-rendering. That rebuild is what the reading
position has to be held through, and the hold is where the flicker lived. So
the markers are now always rendered and the setting flips one tag's
`invisible` — the text still changes for a reader, but nothing is rebuilt.

Two things have to hold for that to be honest: the markers must really stop
being drawn (GTK excludes invisible characters from `get_text` without hidden
chars, which is the same rule the view lays out by), and the find bar must not
match against markers a reader cannot see.

No widgets beyond a TextBuffer: the pane's own methods are borrowed onto a
stand-in, as in test_numeral_style.
"""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402

from pane import BiblePane, _FN_MARKER_TAG  # noqa: E402
from pane_search import _buffer_slice_without_markers  # noqa: E402


class Pane:
    """Enough pane to hold a rendered chapter's markers."""

    _fn_marker_tag = BiblePane._fn_marker_tag
    _restyle_footnote_markers = BiblePane._restyle_footnote_markers
    set_show_footnotes = BiblePane.set_show_footnotes

    def __init__(self, show=True):
        self._buffer = Gtk.TextBuffer()
        self._show_footnotes = show
        self.rerenders = 0

    def _rerender_keeping_place(self):
        self.rerenders += 1


def render(pane, text='In the beginning', marker='a', trailing=' God created'):
    """A verse with one marker in it, tagged the way _apply_footnote_tags does."""
    buf = pane._buffer
    buf.set_text('')
    buf.insert(buf.get_end_iter(), text)
    start = buf.get_end_iter().get_offset()
    buf.insert(buf.get_end_iter(), marker)
    tag = pane._fn_marker_tag()
    buf.apply_tag(tag, buf.get_iter_at_offset(start),
                  buf.get_iter_at_offset(start + len(marker)))
    buf.insert(buf.get_end_iter(), trailing)
    return buf


def visible(buf):
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)


def everything(buf):
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)


def test_hiding_the_markers_does_not_rebuild_the_chapter():
    pane = Pane(show=True)
    render(pane)
    pane.set_show_footnotes(False)
    assert pane.rerenders == 0, 'the toggle re-rendered instead of restyling'


def test_hiding_the_markers_takes_them_out_of_the_text():
    pane = Pane(show=True)
    buf = render(pane)
    assert visible(buf) == 'In the beginninga God created'
    pane.set_show_footnotes(False)
    assert visible(buf) == 'In the beginning God created'
    # Still there, just not drawn — that is what makes the toggle cheap.
    assert everything(buf) == 'In the beginninga God created'


def test_showing_them_again_brings_them_back():
    pane = Pane(show=False)
    buf = render(pane)
    assert visible(buf) == 'In the beginning God created'
    pane.set_show_footnotes(True)
    assert visible(buf) == 'In the beginninga God created'
    assert pane.rerenders == 0


def test_a_chapter_with_no_markers_falls_back_to_a_render():
    """Nothing adopted to flip — a chapter rendered before the tag existed, or
    a surface that never rendered one. The render is what picks the flag up."""
    pane = Pane(show=True)
    pane._buffer.set_text('In the beginning God created')
    pane.set_show_footnotes(False)
    assert pane.rerenders == 1


def test_setting_it_to_what_it_already_is_does_nothing():
    pane = Pane(show=True)
    render(pane)
    pane.set_show_footnotes(True)
    assert pane.rerenders == 0
    assert pane._buffer.get_tag_table().lookup(_FN_MARKER_TAG) is not None


def test_the_find_bar_does_not_match_a_marker_a_reader_cannot_see():
    """The markers are single letters sitting mid-sentence, so they join words
    that were never joined on the page. Blanked rather than removed, because
    the find bar maps match offsets straight onto buffer offsets."""
    pane = Pane(show=True)
    buf = render(pane, text='In the beginnin', marker='g', trailing=' God')
    assert 'beginning' in everything(buf), 'the marker really does join a word'
    assert 'beginning' not in _buffer_slice_without_markers(buf)


def test_masking_a_marker_keeps_every_other_offset_where_it_was():
    pane = Pane(show=True)
    buf = render(pane)
    masked = _buffer_slice_without_markers(buf)
    raw = buf.get_slice(buf.get_start_iter(), buf.get_end_iter(), True)
    assert len(masked) == len(raw)
    assert masked.index('God') == raw.index('God')


def test_markers_are_masked_whether_or_not_they_are_shown():
    # Hidden markers are still in the buffer, and the find bar reads the buffer.
    pane = Pane(show=False)
    buf = render(pane, text='In the beginnin', marker='g', trailing=' God')
    assert 'beginning' not in _buffer_slice_without_markers(buf)


def test_a_buffer_that_never_had_markers_is_returned_untouched():
    pane = Pane(show=True)
    pane._buffer.set_text('In the beginning God created')
    assert (_buffer_slice_without_markers(pane._buffer)
            == 'In the beginning God created')


class Targets:
    """The click/hover target resolution, with only what it reads."""

    _targets_at_iter = BiblePane._targets_at_iter

    def __init__(self, show):
        self._show_footnotes = show


def _marked_buffer():
    """'alpha' + a hidden-capable marker + ' beta', tagged as the render does."""
    pane = Pane(show=True)
    buf = pane._buffer
    buf.insert(buf.get_end_iter(), 'alpha')
    start = buf.get_end_iter().get_offset()
    buf.insert(buf.get_end_iter(), 'a')
    tag = buf.create_tag('fnote:1:1')
    buf.apply_tag(tag, buf.get_iter_at_offset(start),
                  buf.get_iter_at_offset(start + 1))
    buf.apply_tag(pane._fn_marker_tag(), buf.get_iter_at_offset(start),
                  buf.get_iter_at_offset(start + 1))
    buf.insert(buf.get_end_iter(), ' beta')
    return buf, start


def test_a_marker_beside_the_click_is_a_target_when_shown():
    buf, start = _marked_buffer()
    # The letter just before the marker: the probe looks one char each way.
    targets, _it = Targets(True)._targets_at_iter(
        buf.get_iter_at_offset(start - 1))
    assert targets['fnote'] == '1:1'


def test_a_hidden_marker_beside_the_click_is_not_a_target():
    """The markers stay in the buffer when switched off, and the probe looks
    one character to each side — so a click on the letter beside a hidden
    marker opened a note the reader had turned off."""
    buf, start = _marked_buffer()
    targets, _it = Targets(False)._targets_at_iter(
        buf.get_iter_at_offset(start - 1))
    assert targets['fnote'] is None


def test_clicking_a_hidden_marker_itself_is_not_a_target():
    buf, start = _marked_buffer()
    targets, _it = Targets(False)._targets_at_iter(
        buf.get_iter_at_offset(start))
    assert targets['fnote'] is None


class Announcer:
    """The accessible verse-state line, with only what it reads."""

    _verse_state_text = BiblePane._verse_state_text

    def __init__(self, show):
        self._show_footnotes = show
        self._book = 'Genesis'
        self._chapter = 1
        self._module = 'BSB'
        self._module_type = 'Biblical Texts'
        self._chapter_footnotes = {(1, '1'): ('note', 'a body', 'a')}


def test_footnotes_are_announced_when_they_are_shown(monkeypatch):
    import pane
    monkeypatch.setattr(pane.annotations, 'get_annotations',
                        lambda *a, **k: {})
    assert 'has footnotes' in Announcer(True)._verse_state_text(1)


def test_footnotes_a_reader_turned_off_are_not_announced(monkeypatch):
    """The map is populated whether or not the markers are drawn, so this read
    it and told an AT user about a note they could neither see nor reach."""
    import pane
    monkeypatch.setattr(pane.annotations, 'get_annotations',
                        lambda *a, **k: {})
    assert 'has footnotes' not in Announcer(False)._verse_state_text(1)
