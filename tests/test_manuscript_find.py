"""Find and replace inside a journal entry or a sermon manuscript."""

import pytest

import manuscript_find as mf


# ── The matching rule ───────────────────────────────────────────────────────

def test_matching_ignores_case():
    assert mf.find_all('Grace upon grace. GRACE', 'grace') == [
        (0, 5), (11, 16), (18, 23)]


def test_the_query_is_literal_never_a_pattern():
    """"v. 3 (ESV)" is a thing a preacher types; as a pattern it matches
    nothing it looks like."""
    assert mf.find_all('see v. 3 (ESV) and v 3 ESV', 'v. 3 (ESV)') == [(4, 14)]


def test_offsets_are_characters_so_they_fit_the_buffer():
    """A GtkTextBuffer counts characters, not bytes: Cyrillic and accents
    before a match must not move it."""
    text = 'Благодать и благодать — él'
    assert mf.find_all(text, 'БЛАГОДАТЬ') == [(0, 9), (12, 21)]
    assert mf.find_all(text, 'él') == [(24, 26)]


def test_an_empty_query_finds_nothing():
    assert mf.find_all('anything', '') == []


def test_stepping_wraps_at_both_ends():
    matches = [(2, 4), (10, 12), (20, 22)]
    assert mf.next_index(matches, 0) == 0
    assert mf.next_index(matches, 11) == 2
    assert mf.next_index(matches, 21) == 0             # past the last
    assert mf.next_index(matches, 10, backwards=True) == 0
    assert mf.next_index(matches, 2, backwards=True) == 2   # before the first
    assert mf.next_index([], 5) is None


# ── The bar on a real buffer ────────────────────────────────────────────────

@pytest.fixture
def bar():
    """`Gdk.Display.get_default()`, never `Gtk.init_check()` alone — the
    latter returns True with no display and building widgets then
    segfaults."""
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds real widgets')
    view = Gtk.TextView()
    view.get_buffer().set_text('Grace and peace. Peace, then grace.')
    return mf.FindBar(view)


def _text(bar):
    buf = bar._buf
    return buf.get_text(*buf.get_bounds(), False)


def _selected(bar):
    a, b = bar._buf.get_selection_bounds()
    return a.get_offset(), b.get_offset()


def test_opening_on_a_selection_searches_for_it(bar):
    buf = bar._buf
    buf.select_range(buf.get_iter_at_offset(10), buf.get_iter_at_offset(15))
    bar.open()
    assert bar.entry.get_text() == 'peace'
    assert bar._matches == [(10, 15), (17, 22)]
    assert bar._count.get_text() == '1 of 2'


def test_next_and_previous_wrap_and_select(bar):
    bar._buf.place_cursor(bar._buf.get_start_iter())
    bar.entry.set_text('grace')
    bar.open()
    assert _selected(bar) == (0, 5)
    bar.step()
    assert _selected(bar) == (29, 34)
    bar.step()
    assert _selected(bar) == (0, 5)
    bar.step(backwards=True)
    assert _selected(bar) == (29, 34)
    assert bar._count.get_text() == '2 of 2'
    # The current match is marked apart from the others, not only selected:
    # a selection is drawn faintly while the find field has the keyboard.
    buf = bar._buf
    assert buf.get_iter_at_offset(30).has_tag(bar._current_tag)
    assert not buf.get_iter_at_offset(1).has_tag(bar._current_tag)


def test_replace_changes_only_the_match_on_show(bar):
    """If the reader has clicked away, the first press shows the match
    again; only the second changes it."""
    bar._buf.place_cursor(bar._buf.get_start_iter())
    bar.entry.set_text('peace')
    bar.open()
    bar.replace_entry.set_text('joy')
    bar._buf.place_cursor(bar._buf.get_start_iter())      # clicked away
    bar.replace()
    assert _text(bar) == 'Grace and peace. Peace, then grace.'
    bar.replace()
    assert _text(bar) == 'Grace and joy. Peace, then grace.'
    assert _selected(bar) == (15, 20)                      # on to the next


def test_replace_all_is_one_undo(bar):
    bar.entry.set_text('grace')
    bar.open()
    bar.replace_entry.set_text('mercy')
    assert bar.replace_all() == 2
    assert _text(bar) == 'mercy and peace. Peace, then mercy.'
    assert bar._count.get_text() == 'Replaced 2 matches'
    bar._buf.undo()
    assert _text(bar) == 'Grace and peace. Peace, then grace.'


def test_closing_clears_the_marks(bar):
    bar.entry.set_text('peace')
    bar.open()
    buf = bar._buf
    assert buf.get_iter_at_offset(11).has_tag(bar._tag)
    assert bar.close() is True
    assert not buf.get_iter_at_offset(11).has_tag(bar._tag)
    assert bar.close() is False                            # Esc goes on


def test_replace_all_is_one_edit_and_keeps_the_cursor(bar):
    """An edit per match cost the buffer's undo a step each: 4,320 uses of
    "the" in an 8,500-word manuscript took 2.4 s to replace and 4.9 s to
    undo, the window frozen for both. The whole page goes in one delete and
    one insert, and the cursor stays where it was, moved by what changed
    before it."""
    buf = bar._buf
    buf.place_cursor(buf.get_iter_at_offset(17))      # on "Peace, then grace."
    bar.entry.set_text('grace')
    bar.open()                        # selects the next match: cursor at 29
    assert buf.get_iter_at_mark(buf.get_insert()).get_offset() == 29
    bar.replace_entry.set_text('mercy')
    edits = []
    buf.connect('insert-text', lambda *_a: edits.append('insert'))
    buf.connect('delete-range', lambda *_a: edits.append('delete'))
    assert bar.replace_all() == 2
    assert _text(bar) == 'mercy and peace. Peace, then mercy.'
    assert edits == ['delete', 'insert']
    # "Grace" → "mercy" is the same length, so the cursor is where it was.
    assert buf.get_iter_at_mark(buf.get_insert()).get_offset() == 29
    bar.replace_entry.set_text('')
    bar.entry.set_text('mercy')
    bar.replace_all()
    assert _text(bar) == ' and peace. Peace, then .'
    # Five letters gone before it; the word it stood on is gone too, so it
    # sits where that word began.
    assert buf.get_iter_at_mark(buf.get_insert()).get_offset() == 24
