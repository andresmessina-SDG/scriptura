"""OverlayManager logic: jump parsing + overlay mutual-exclusion (no real UI).

_parse_jump is pure (BOOKS + versification); _close_other_overlays is exercised
against fake split/revealer widgets that record their visibility calls."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import overlays


class _Split:
    def __init__(self):
        self.shown = None

    def set_show_sidebar(self, v):
        self.shown = v


class _Revealer:
    def __init__(self):
        self.revealed = None

    def set_reveal_child(self, v):
        self.revealed = v


def _mgr():
    win = types.SimpleNamespace(
        _menu_split=_Split(), _search_split=_Split(),
        _jump_revealer=_Revealer())
    return overlays.OverlayManager(win)


def test_close_other_overlays_keeps_only_the_named_one():
    m = _mgr()
    m._close_other_overlays(keep='search')
    assert m._win._menu_split.shown is False
    assert m._win._jump_revealer.revealed is False
    assert m._win._search_split.shown is None  # untouched — it's the kept one


def test_close_other_overlays_none_closes_all_three():
    m = _mgr()
    m._close_other_overlays()
    assert m._win._menu_split.shown is False
    assert m._win._search_split.shown is False
    assert m._win._jump_revealer.revealed is False


def test_parse_jump_exact_beats_prefix():
    m = _mgr()
    # "Job" must not silently become "Joshua".
    assert m._parse_jump('Job')[0] == 'Job'
    assert m._parse_jump('Job 5')[:2] == ('Job', 5)


def test_parse_jump_chapter_and_verse():
    m = _mgr()
    assert m._parse_jump('John 3:16') == ('John', 3, 16)
    assert m._parse_jump('John 3')[2] is None


def test_parse_jump_prefix_and_clamp():
    m = _mgr()
    # Prefix match; chapter beyond the book clamps to its last.
    assert m._parse_jump('Gen')[0] == 'Genesis'
    b, ch, _v = m._parse_jump('Genesis 999')
    assert b == 'Genesis' and ch == 50


def test_parse_jump_rejects_junk():
    m = _mgr()
    assert m._parse_jump('') is None
    assert m._parse_jump('Zzznotabook') is None
