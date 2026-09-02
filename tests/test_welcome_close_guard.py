"""The welcome window's guard against being closed mid-install.

`_install_worker` runs on a daemon thread with no cancellation point, so a
close during the download ends the process wherever it happened to be: part
of a library on disk, no opening pair recorded, and nothing said about it.
The titlebar close button was live through the whole download.

Most of this is display-free — the handler is small and its state is one
flag — but the last test needs a real window, because a handler nothing
connects is the failure the rest would miss.
"""

import pytest

import welcome


def _win(**state):
    win = welcome.WelcomeWindow.__new__(welcome.WelcomeWindow)
    for key, value in state.items():
        setattr(win, key, value)
    return win


def test_a_close_outside_the_install_is_allowed():
    """The chooser page has nothing to lose; a prompt there is furniture."""
    assert welcome.WelcomeWindow._on_close_request(_win(), None) is False


def test_a_close_during_the_install_is_held_and_asks():
    asked = []
    win = _win(_installing=True, _ask_stop_install=lambda: asked.append(1))
    assert welcome.WelcomeWindow._on_close_request(win, None) is True
    assert asked, 'the window blocked the close without saying why'


def test_keeping_the_download_leaves_the_guard_up():
    closed = []
    win = _win(_installing=True, close=lambda: closed.append(1))
    welcome.WelcomeWindow._on_stop_confirm(win, None, 'keep')
    assert win._installing is True
    assert not closed


def test_stopping_closes_without_asking_the_same_question_again():
    closed = []
    win = _win(_installing=True, close=lambda: closed.append(1))
    welcome.WelcomeWindow._on_stop_confirm(win, None, 'stop')
    assert closed, 'the confirmed close never reached close()'
    assert win._installing is False
    assert welcome.WelcomeWindow._on_close_request(win, None) is False


def test_the_guard_comes_off_when_the_download_ends(monkeypatch):
    """The handoff closes the window itself. If the flag outlived the
    install, the app would ask a newcomer whether to stop a download that
    had already finished — and the error page would trap them."""
    monkeypatch.setattr(welcome.sword_bridge, 'module_names', lambda: ['BSB'])
    monkeypatch.setattr(welcome.sword_bridge, 'module_type',
                        lambda _m: 'Biblical Texts')
    monkeypatch.setattr(welcome.GLib, 'timeout_add', lambda *a, **k: 0)

    class _Stub:
        def set_text(self, _t): pass
        def stop(self): pass
        def set_visible(self, _v): pass

    win = _win(_installing=True, _status=_Stub(), _spinner=_Stub(),
               _record_opening_pair=lambda _b: None)
    welcome.WelcomeWindow._finish_install(win, [], {'opens': ('BSB', None)})
    assert win._installing is False


def test_the_window_actually_connects_the_guard(monkeypatch):
    """A handler nothing connects is exactly the state this bug was in."""
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    win = welcome.WelcomeWindow(on_ready=lambda: None)
    assert win.emit('close-request') is False

    asked = []
    win._installing = True
    monkeypatch.setattr(win, '_ask_stop_install', lambda: asked.append(1),
                        raising=False)
    assert win.emit('close-request') is True
    assert asked
