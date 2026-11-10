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
    monkeypatch.setattr(main.gc, 'disable', lambda: None)
    monkeypatch.setattr(GLib, 'timeout_add', lambda ms, fn, *a: 1)
    app, _c, _q = _app()
    main._on_startup(app)
    assert len(armed) == 1
    secs, fn, args = armed[0]
    assert secs == main._DAILY_TICK_S


def test_startup_moves_garbage_collection_to_the_main_loop(monkeypatch):
    """Collected on a worker, a widget is freed off the main thread."""
    off, ticks = [], []
    monkeypatch.setattr(main.gc, 'disable', lambda: off.append(True))
    monkeypatch.setattr(GLib, 'timeout_add',
                        lambda ms, fn, *a: ticks.append((ms, fn)) or 1)
    monkeypatch.setattr(GLib, 'timeout_add_seconds', lambda *a: 1)
    monkeypatch.setattr(backup, 'daily_copy', lambda: None)
    main._on_startup(_app()[0])
    assert off == [True]
    assert ticks == [(main._GC_TICK_MS, main._collect_on_main_thread)]


def test_the_collector_follows_pythons_thresholds(monkeypatch):
    done = []
    monkeypatch.setattr(main.gc, 'collect', lambda gen: done.append(gen))
    monkeypatch.setattr(main.gc, 'get_threshold', lambda: (700, 10, 10))
    monkeypatch.setattr(main.gc, 'get_count', lambda: (5, 0, 0))
    assert main._collect_on_main_thread() is GLib.SOURCE_CONTINUE
    monkeypatch.setattr(main.gc, 'get_count', lambda: (701, 11, 3))
    main._collect_on_main_thread()
    assert done == [1]


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
    monkeypatch.setattr(main.GLibUnix, 'signal_add',
                        lambda prio, sig, fn, *a: heard.append(sig) or 1)
    app, _c, _q = _app()
    main._listen_for_session_end(app)
    assert set(heard) == {signal.SIGTERM, signal.SIGHUP, signal.SIGINT}
