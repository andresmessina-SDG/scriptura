"""The concordance's controls — the parts a data-layer test cannot see.

The scope pair is two hand-linked ToggleButtons, and GTK4 has no radio
group for them. Everything here is about that pair telling the truth
about what is in the list below it.
"""
import pytest

import lexicon_panel


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display')


@pytest.fixture
def panel(display):
    return lexicon_panel.LexiconPanel()


def _state(p):
    return (p._ws_scope, p._scope_book_btn.get_active(),
            p._scope_bible_btn.get_active())


def test_the_scope_starts_on_this_book(panel):
    assert _state(panel) == ('book', True, False)


def test_switching_scope_moves_both_buttons_with_it(panel):
    """Measured before the re-entrancy guard: turning the other button
    off re-entered the handler with the old scope still in place, read
    the pair as 'both off' and lit the button the reader had just left.
    The list went whole-Bible with *This book* still lit — the controls
    lying about what was below them."""
    panel._scope_bible_btn.set_active(True)
    assert _state(panel) == ('bible', False, True)
    panel._scope_book_btn.set_active(True)
    assert _state(panel) == ('book', True, False)


def test_the_pair_is_never_left_with_no_answer(panel):
    """Clicking the lit button again keeps it lit — a scope of neither
    would leave the scan with nothing to read."""
    panel._scope_book_btn.set_active(False)
    assert _state(panel) == ('book', True, False)


def test_clearing_the_list_clears_the_page_backlog(panel):
    """`show_loading` clears between two words. A previous whole-Bible
    scan's pending matches left behind would page into the next word."""
    panel._ws_pending = [('John', 3, 16, 'x')] * 5
    panel._ws_room = 0
    panel._clear_ws()
    assert panel._ws_pending == []
    assert panel._ws_room == lexicon_panel._WS_ROW_CAP
