"""The pane's find bar finds words in the chapter on screen, and nowhere else.
The whole-Bible search is the header's; the two keep one job each."""

import types

import pytest

from pane_search import PaneSearch


@pytest.fixture
def find():
    """`Gdk.Display.get_default()`, never `Gtk.init_check()` alone — the
    latter returns True with no display and building widgets then
    segfaults."""
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds real widgets')
    view = Gtk.TextView()
    buf = view.get_buffer()
    buf.set_text('Grace and peace. Peace, then grace. Grace.')
    scrolls = []
    pane = types.SimpleNamespace(
        _buffer=buf, view=view, _reading_anchor='old place',
        _mark_programmatic_scroll=lambda: scrolls.append('mark'),
        _schedule_anchor_capture=lambda ms=250: scrolls.append('capture'))
    ps = PaneSearch(pane)
    ps.build_button()
    ps.build_revealer()
    ps.scrolls = scrolls
    return ps


def _ranges(ps, name):
    buf = ps._pane._buffer
    tag = buf.get_tag_table().lookup(name)
    out, it = [], buf.get_start_iter()
    if tag is None:
        return out
    while True:
        if it.starts_tag(tag):
            s = it.get_offset()
            it.forward_to_tag_toggle(tag)
            out.append((s, it.get_offset()))
        if not it.forward_to_tag_toggle(tag):
            return out


def test_typing_highlights_the_chapter_and_counts(find):
    find._live_highlight('grace')
    assert find.results == [(0, 5), (29, 34), (36, 41)]
    assert _ranges(find, '_search_hl') == [(0, 5), (29, 34), (36, 41)]
    assert find._status.get_text() == '3 in this chapter'
    assert find._next_btn.get_sensitive()


def test_enter_steps_through_the_chapter_and_wraps(find):
    find._live_highlight('grace')
    assert find.step() is True
    assert _ranges(find, '_search_hl_cur') == [(0, 5)]
    assert find._status.get_text() == '1 of 3'
    find.step(); find.step(); find.step()           # past the last
    assert _ranges(find, '_search_hl_cur') == [(0, 5)]
    find.step(prev=True)                            # before the first
    assert _ranges(find, '_search_hl_cur') == [(36, 41)]
    assert find.scrolls, 'a step is marked as a programmatic scroll'


def test_the_current_match_is_not_also_soft(find):
    """The two bands would stack into a muddier colour."""
    find._live_highlight('grace')
    find.step()
    assert (0, 5) not in _ranges(find, '_search_hl')
    assert _ranges(find, '_search_hl') == [(29, 34), (36, 41)]


def test_match_case(find):
    find._case_btn.set_active(True)
    find._live_highlight('Grace')
    assert find.results == [(0, 5), (36, 41)]


def test_no_match_says_so_and_stepping_does_nothing(find):
    find._live_highlight('mercy')
    assert find.results == []
    assert find._status.get_text() == 'No matches'
    assert find.step() is False


def test_the_bar_follows_the_reader_to_the_next_chapter(find):
    """After a render, an open bar searches the new chapter for its query."""
    find._rev.set_reveal_child(True)
    find._entry.set_text('peace')
    find._pane._buffer.set_text('Peace I leave with you.')
    find.apply_highlight()
    assert find.results == [(0, 5)]


def test_the_panel_query_wins_over_the_bar(find):
    """The window's search panel navigated here: its words are shown."""
    find._rev.set_reveal_child(True)
    find._entry.set_text('peace')
    find.stash_pending_highlight('then', False)
    find.apply_highlight()
    assert _ranges(find, '_search_hl') == [(24, 28)]


def test_a_step_is_a_new_reading_place(find):
    """Otherwise a later resize or re-render re-asserts the old anchor and
    throws the reader back to where they were before the jump."""
    find._live_highlight('grace')
    find.step()
    assert find._pane._reading_anchor is None
    assert 'capture' in find.scrolls


def test_a_panel_jump_drops_the_old_chapters_matches(find):
    """Offsets from the chapter before are nonsense in this one; F3 would
    step to them."""
    find._rev.set_reveal_child(True)
    find._entry.set_text('grace')
    find._live_highlight('grace')
    find._pane._buffer.set_text('Peace I leave with you.')
    find.stash_pending_highlight('peace', False)
    find.apply_highlight()
    assert find.results == []
    assert find.step() is False
    assert not find._next_btn.get_sensitive()
