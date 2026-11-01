"""The book picker focuses its chosen book once, then stops.

Its idle callback returned the result of `grab_focus()`, which is True when
the focus moves, so GLib ran it again on every turn of the main loop: a dev
instance left open sat at 95% of a core for an hour and a half.
"""
import types

from gi.repository import GLib

import navigation


def _list(row):
    return types.SimpleNamespace(get_selected_row=lambda: row)


def test_a_focus_that_works_does_not_run_again():
    moved = []
    row = types.SimpleNamespace(grab_focus=lambda: moved.append(1) or True)
    assert navigation._focus_selected_row(_list(row)) == GLib.SOURCE_REMOVE
    assert moved == [1]


def test_no_chosen_book_is_fine():
    assert navigation._focus_selected_row(_list(None)) == GLib.SOURCE_REMOVE
