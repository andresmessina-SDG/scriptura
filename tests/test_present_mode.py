"""PresentController logic: source-pane selection, parallel eligibility, and
cross-chapter stepping (no GTK — fake panes + a stubbed chapter count)."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import present_mode
import sword_bridge


class _Pane:
    def __init__(self, passage, visible=True, module='KJV'):
        self._passage = passage
        self._visible = visible
        self._module = module

    def current_passage(self):
        return self._passage

    def get_visible(self):
        return self._visible


def _ctrl(pane1, pane2):
    win = types.SimpleNamespace(pane1=pane1, pane2=pane2)
    return present_mode.PresentController(win)


def test_source_pane_prefers_pane1_when_it_has_a_passage():
    c = _ctrl(_Pane(('John', 3, 'KJV', [])), _Pane(('Mark', 1, 'ASV', [])))
    assert c._present_source_pane() is c._win.pane1


def test_source_pane_falls_back_to_pane2():
    c = _ctrl(_Pane(None), _Pane(('Mark', 1, 'ASV', [])))
    assert c._present_source_pane() is c._win.pane2


def test_source_pane_defaults_to_pane1_when_neither_navigable():
    c = _ctrl(_Pane(None), _Pane(None))
    assert c._present_source_pane() is c._win.pane1


def test_bilingual_source_when_split_same_ref_different_modules():
    p1 = _Pane(('John', 3, 'KJV', []), module='KJV')
    p2 = _Pane(('John', 3, 'ASV', []), module='ASV')
    c = _ctrl(p1, p2)
    assert c._present_bilingual_source() == (p1, p2)


def test_bilingual_source_none_when_same_module():
    p1 = _Pane(('John', 3, 'KJV', []), module='KJV')
    p2 = _Pane(('John', 3, 'KJV', []), module='KJV')
    assert _ctrl(p1, p2)._present_bilingual_source() is None


def test_bilingual_source_none_on_different_reference():
    p1 = _Pane(('John', 3, 'KJV', []), module='KJV')
    p2 = _Pane(('John', 4, 'ASV', []), module='ASV')
    assert _ctrl(p1, p2)._present_bilingual_source() is None


def test_bilingual_source_none_when_single_pane():
    p1 = _Pane(('John', 3, 'KJV', []), module='KJV')
    p2 = _Pane(('John', 3, 'ASV', []), visible=False, module='ASV')
    assert _ctrl(p1, p2)._present_bilingual_source() is None


def test_adjacent_chapter_steps_and_crosses_books(monkeypatch):
    # Genesis has 50 chapters here; Exodus follows it in BOOKS.
    monkeypatch.setattr(sword_bridge, 'chapter_count', lambda b, m=None: 50)
    c = _ctrl(_Pane(None), _Pane(None))
    c._present_module = 'KJV'
    assert c._adjacent_chapter('Genesis', 5, +1) == ('Genesis', 6)
    assert c._adjacent_chapter('Genesis', 50, +1) == ('Exodus', 1)
    assert c._adjacent_chapter('Genesis', 5, -1) == ('Genesis', 4)
    # Very start of the canon: nothing before Genesis 1.
    assert c._adjacent_chapter('Genesis', 1, -1) is None
