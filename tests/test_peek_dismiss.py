"""An open peek closes when the text under it moves.

A peek points at words. After a scroll it pointed at other words; after a
chapter change at another chapter, and a note peek's Edit then wrote the
note onto the new chapter's verse of the same number (John 3:2's note
landed on John 4:2).
"""
import types

import gi

gi.require_version('Gtk', '4.0')
from pane import BiblePane  # noqa: E402
from pane_peek import PeekController  # noqa: E402


def _peek(parent_is_view=True, visible=True):
    view = object()
    pop = types.SimpleNamespace(get_visible=lambda: visible,
                                get_parent=lambda: view if parent_is_view else object())
    c = types.SimpleNamespace(pop=pop, _view=view, _scroll_at=100.0, closed=[])
    c.dismiss = lambda: c.closed.append(True)
    return c


def test_a_scroll_closes_the_peek():
    c = _peek()
    PeekController.on_reading_scroll(c, 160.0)
    assert c.closed


def test_layout_settle_does_not():
    c = _peek()
    PeekController.on_reading_scroll(c, 101.5)
    assert not c.closed


def test_a_peek_on_another_widget_stays():
    # The lexicon panel's verse peek does not sit on the reading text.
    c = _peek(parent_is_view=False)
    PeekController.on_reading_scroll(c, 400.0)
    assert not c.closed


class _Noop:
    """Callable, and every attribute is another no-op."""

    def __call__(self, *a):
        return self

    def __getattr__(self, name):
        return self


class _Pane:
    """Any other attribute is a no-op, so _fetch_and_render runs to the end."""

    def __init__(self):
        self.closed = []
        self._peek = types.SimpleNamespace(dismiss=lambda: self.closed.append(1))
        self._is_devotional = True

    def __getattr__(self, name):
        return _Noop()


def test_a_new_render_closes_the_peek():
    p = _Pane()
    BiblePane._fetch_and_render(p)
    assert p.closed


def test_a_dismiss_between_self_heal_shows_holds():
    # A relayout can take the peek down and queue a reshow 60 ms later. A
    # dismiss in that gap finds nothing showing; the reshow must not bring
    # the peek back.
    shown = []
    pop = types.SimpleNamespace(get_visible=lambda: False,
                                popup=lambda: shown.append(1),
                                set_opacity=lambda v: None)
    c = types.SimpleNamespace(pop=pop, _dict_user_closed=False,
                              _hover_gloss_range=None,
                              _dict_arm_reveal=lambda p: None)
    assert PeekController.dismiss(c) is False
    PeekController._dict_reshow(c, pop)
    assert not shown
