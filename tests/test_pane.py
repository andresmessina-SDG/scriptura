"""Tests for the small pure helpers on BiblePane that don't need a live
widget tree. _resolve_present_verse is called via the class on a stand-in
`self` so we don't have to construct GTK objects."""

from pane import BiblePane


def _resolve(present, target):
    obj = type('Stub', (), {})()
    obj._present_verses = present
    return BiblePane._resolve_present_verse(obj, target)


def test_resolve_present_verse_exact_match():
    assert _resolve([1, 2, 3], 2) == 2


def test_resolve_present_verse_bridge_inner_falls_back():
    # \v 1-2 stores text under verse 1 only; a jump to 2 lands on 1.
    assert _resolve([1, 3, 4], 2) == 1


def test_resolve_present_verse_no_earlier_returns_request():
    # Nothing before the target — leave it unchanged (caller no-ops).
    assert _resolve([5, 6], 2) == 2


def test_resolve_present_verse_unset_returns_request():
    obj = type('Stub', (), {})()
    assert BiblePane._resolve_present_verse(obj, 7) == 7
