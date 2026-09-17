"""What the app does between launch and the session ending.

The daily copy ran only at `startup`, so an app left open across days made
none; and nothing handled SIGTERM, so a session ending the process lost
whatever the editors still had queued. Both are answered from main.py.
"""

import signal
import types

from gi.repository import Gio, GLib

import backup
import main


def _app(windows=()):
    closed, quit_ = [], []
    app = types.SimpleNamespace(
        get_flags=lambda: Gio.ApplicationFlags.FLAGS_NONE,
        get_windows=lambda: list(windows),
        quit=lambda: quit_.append(True),
        set_inactivity_timeout=lambda _ms: None)
    return app, closed, quit_


def test_startup_arms_a_daily_tick(monkeypatch):
    armed = []
    monkeypatch.setattr(GLib, 'timeout_add_seconds',
                        lambda secs, fn, *a: armed.append((secs, fn, a)) or 1)
    monkeypatch.setattr(backup, 'daily_copy', lambda: None)
    app, _c, _q = _app()
    main._on_startup(app)
    assert len(armed) == 1
    secs, fn, args = armed[0]
    assert secs == main._DAILY_TICK_S


def test_the_tick_takes_the_copy_and_stays_armed(monkeypatch):
    took = []
    monkeypatch.setattr(backup, 'daily_copy', lambda: took.append(1))
    assert main._daily_tick() is GLib.SOURCE_CONTINUE
    assert took == [1]


def test_a_signal_closes_the_windows_before_quitting():
    """Closing runs each window's close-request — where the editors flush —
    and only then does the app quit."""
    order = []
    win = types.SimpleNamespace(close=lambda: order.append('close'))
    app, _c, _q = _app([win])
    app.quit = lambda: order.append('quit')
    assert main._on_session_end(app) is GLib.SOURCE_REMOVE
    assert order == ['close', 'quit']


def test_main_listens_for_the_session_ending(monkeypatch):
    heard = []
    monkeypatch.setattr(GLib, 'unix_signal_add',
                        lambda prio, sig, fn, *a: heard.append(sig) or 1)
    app, _c, _q = _app()
    main._listen_for_session_end(app)
    assert set(heard) == {signal.SIGTERM, signal.SIGHUP, signal.SIGINT}
