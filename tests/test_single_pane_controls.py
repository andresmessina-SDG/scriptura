"""Controls that only mean something with two panes leave with the second.

In single-pane view the pane lock and the swap button stayed on screen, the
swap dimmed, though neither can do anything without a pane beside it.
"""

import types

import pane
import window


class _Toggle:
    def __init__(self, active=False):
        self.active, self.visible = active, None

    def get_active(self):
        return self.active

    def set_visible(self, visible):
        self.visible = visible


def _pane(alone, locked=False, verse_keyed=True):
    return types.SimpleNamespace(
        _alone=alone, _sync_btn=_Toggle(locked),
        _is_verse_navigable=lambda: verse_keyed, _is_catena=False,
        _is_imagery=False, _is_interlinear=False)


def _lock_shown(fake):
    pane.BiblePane._update_sync_visible(fake)
    return fake._sync_btn.visible


def test_the_lock_shows_beside_another_pane():
    assert _lock_shown(_pane(alone=False)) is True


def test_a_pane_on_its_own_hides_the_lock():
    assert _lock_shown(_pane(alone=True)) is False


def test_a_lock_that_is_on_stays_visible_on_its_own():
    """Hidden, a locked pane would ignore navigation with no sign of why."""
    assert _lock_shown(_pane(alone=True, locked=True)) is True


def test_a_pane_that_never_follows_navigation_has_no_lock():
    assert _lock_shown(_pane(alone=False, verse_keyed=False)) is False


def test_single_pane_hides_the_swap_and_tells_both_panes():
    told = []
    fake = types.SimpleNamespace(
        _swap_btn=_Toggle(), _header_narrow=False,
        pane1=types.SimpleNamespace(set_alone=lambda a: told.append(a)),
        pane2=types.SimpleNamespace(set_alone=lambda a: told.append(a)))
    window.BibleWindow._show_split_controls(fake, False)
    assert fake._swap_btn.visible is False and told == [True, True]
    told.clear()
    window.BibleWindow._show_split_controls(fake, True)
    assert fake._swap_btn.visible is True and told == [False, False]
