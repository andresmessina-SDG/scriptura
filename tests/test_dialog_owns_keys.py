"""While a dialog is up, the window's capture-phase key handler stands
aside. It used to see the dialog's keys first: Escape over Preferences
dismissed the Today page behind it and left the dialog open."""

import types

from gi.repository import Gdk

import window


class _Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f'the window acted behind the dialog: {name}')


def test_escape_is_left_to_an_open_dialog():
    win = types.SimpleNamespace(get_visible_dialog=lambda: object(),
                                pane1=_Untouchable(), pane2=_Untouchable())
    assert window.BibleWindow._on_key_press(
        win, None, Gdk.KEY_Escape, 0, 0) is False


def test_presentation_keys_are_left_to_an_open_dialog():
    win = types.SimpleNamespace(get_visible_dialog=lambda: object(),
                                _present_view=_Untouchable())
    for key in (Gdk.KEY_space, Gdk.KEY_Right, Gdk.KEY_Home):
        assert window.BibleWindow._on_key_press(win, None, key, 0, 0) is False
