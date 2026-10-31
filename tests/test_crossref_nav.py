"""A cross-reference chip goes the window's way when pane 1 follows it.

In single-pane view the chip moved pane 1 on its own (force_navigate): no
Back entry, and the header kept naming the chapter the reader had left.
Pane 2 in split view, and a pane 1 locked to its place, still move alone.
"""
import types

import gi

gi.require_version('Gtk', '4.0')
from window import BibleWindow  # noqa: E402


class _Toggle:
    def __init__(self, active):
        self.active = active

    def get_active(self):
        return self.active


def _pane(visible=True, navigable=True, locked=False):
    p = types.SimpleNamespace(moved=[], _sync_btn=_Toggle(locked))
    p.get_visible = lambda: visible
    p._is_verse_navigable = lambda: navigable
    p.force_navigate = lambda *a: p.moved.append(a)
    return p


def _win(pane1, pane2):
    w = types.SimpleNamespace(pane1=pane1, pane2=pane2, went=[])
    w._go_to = lambda *a: w.went.append(a)
    return w


def test_single_pane_chip_goes_the_window_way():
    w = _win(_pane(), _pane(visible=False))
    BibleWindow._on_crossref_clicked(w, 'Romans', 5, 8)
    assert w.went == [('Romans', 5, 8)]
    assert w.pane1.moved == []


def test_split_view_chip_moves_pane_two_alone():
    w = _win(_pane(), _pane())
    BibleWindow._on_crossref_clicked(w, 'Romans', 5, 8)
    assert w.pane2.moved == [('Romans', 5, 8)]
    assert w.went == []


def test_a_locked_pane_one_moves_alone():
    w = _win(_pane(locked=True), _pane(visible=False))
    BibleWindow._on_crossref_clicked(w, 'Romans', 5, 8)
    assert w.pane1.moved == [('Romans', 5, 8)]
    assert w.went == []
