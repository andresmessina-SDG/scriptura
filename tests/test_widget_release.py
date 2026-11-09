"""Thrown-away widgets are freed.

Random use grew memory by about 15 MB a minute: every study menu and every
copy of the book picker's contents stayed alive. Two causes: a handler that
captures a widget of its own tree makes a cycle through GTK that Python's
collector cannot break, and the popover-arrow hook gave each popover's
surface a strong reference back to the popover.
"""
import gc
import weakref

import gi
import pytest

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gtk  # noqa: E402

import gtk_utils  # noqa: E402


@pytest.fixture
def display():
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display to make widgets')


def _tree():
    """A box whose button's handler reaches the box, as the study menu's
    buttons reach their popover."""
    box = Gtk.Box()
    stack = Gtk.Stack()
    btn = Gtk.Button(label='Back')
    btn.connect('clicked', lambda _b: (stack.set_visible_child_name('a'),
                                       box.set_visible(False)))
    box.append(btn)
    box.append(stack)
    return box, [weakref.ref(box), weakref.ref(btn), weakref.ref(stack)]


def _alive(refs):
    gc.collect()
    return sum(r() is not None for r in refs)


def test_a_released_tree_is_freed(display):
    holder = Gtk.Box()
    kept, freed = [], []
    for released, refs in ((False, kept), (True, freed)):
        for _ in range(10):
            box, r = _tree()
            refs += r
            holder.append(box)
            if released:
                gtk_utils.release_tree(box)
            holder.remove(box)
            del box
    assert _alive(kept) > 0          # the leak this guards against
    assert _alive(freed) == 0


def test_the_arrow_hook_holds_its_popover_weakly(display):
    connected = []

    class _Surface:
        def connect(self, signal, fn, data):
            connected.append(data)

    pop = Gtk.Popover()
    pop.get_surface = lambda: _Surface()
    gtk_utils._on_widget_realize(pop)
    gtk_utils._on_widget_realize(pop)        # a second showing
    assert all(isinstance(d, weakref.ref) for d in connected)
    ref = weakref.ref(pop)
    del pop
    assert _alive([ref]) == 0
