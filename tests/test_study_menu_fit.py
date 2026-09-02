"""The right-click study menu, and whether it can be shown at all.

A GTK popover is placed below what it points at, flipped above when that
will not fit, and — when neither fits — popped straight back down without a
word. His screenshots caught the result: in a 686x709 window the menu is
498px tall against a 607px view, and a right-click anywhere from y=180 to
y=340 opened nothing at all, while the same verse answered above and below
that band.

The fix is not a position but a minimum: inside a scroller the menu can be
smaller than its natural height, so GTK always has somewhere to put it. That
is what these measure — the natural height is still the whole menu, and the
minimum is small enough to fit a short window.
"""

import pytest

import annotation_dialogs


def _gtk():
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    return Gtk


def _menu(monkeypatch, verses=(10,)):
    """The popover show_study_menu parents onto a stand-in view."""
    Gtk = _gtk()
    monkeypatch.setattr(annotation_dialogs.annotations, 'get_annotations',
                        lambda *a: {})

    class _Pane:
        _module, _book, _chapter = 'KJV', 'Genesis', 11
        _view = Gtk.TextView()
        _buffer = _view.get_buffer()

    pane = _Pane()
    # Built, not shown: `popup()` on a popover whose parent has no root
    # segfaults, and the size is knowable without a window.
    popover = annotation_dialogs.build_study_menu(pane, list(verses), 100, 100)
    return Gtk, popover


def test_the_menu_can_be_smaller_than_it_wants_to_be(monkeypatch):
    """The whole defect in one number. GTK can only place a popover it can
    fit, and 498px of menu fits nowhere in a 607px column: not below a click
    at y=340, not above it either.

    The popover itself measures 0 until it is shown — it is a GtkNative and
    sizes its own surface — so the number that decides this is the child's,
    which is what the popover asks for."""
    Gtk, popover = _menu(monkeypatch)
    minimum, natural, _a, _b = popover.get_child().measure(
        Gtk.Orientation.VERTICAL, -1)
    assert natural > 300, (
        f'the menu is only {natural}px tall — if it really is this short, '
        'this guard has stopped testing anything')
    assert minimum <= 220, (
        f'the menu cannot shrink: {minimum}px minimum against {natural}px '
        'natural, so a short window has nowhere to put it and shows nothing')


def test_the_whole_menu_is_still_offered_where_there_is_room(monkeypatch):
    """The guard on the guard: shrinking must not cost the reader rows on a
    normal screen. The scroller propagates its natural height, so where the
    space exists the menu is its full self."""
    Gtk, popover = _menu(monkeypatch)
    scroller = popover.get_child()
    assert isinstance(scroller, Gtk.ScrolledWindow)
    assert scroller.get_propagate_natural_height()
    inner = scroller.get_child()
    rows_natural = inner.measure(Gtk.Orientation.VERTICAL, -1)[1]
    asked_natural = scroller.measure(Gtk.Orientation.VERTICAL, -1)[1]
    assert asked_natural >= rows_natural, (
        f'the scroller asks for {asked_natural}px against {rows_natural}px of '
        'menu, so rows are cut even on a screen with room for them')
