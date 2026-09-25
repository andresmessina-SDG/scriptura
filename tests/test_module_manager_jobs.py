"""The Module Manager's one-operation gate belongs to the process, not to a
window.

A download outlives the window that started it: Esc closes the window and
the worker thread runs on. When the gate lived on the window, the window
opened next thought nothing was running, offered the same Download again,
and a second copy raced the first over one temp file; and when the first
landed, nobody told the panes.

These drive `_run_async` on a stand-in window, so no display is needed.
"""
import socket
import threading
import time
import urllib.error

import pytest
from gi.repository import GLib

import module_manager
from module_manager import ModuleManagerWindow


class _Win:
    _run_async = ModuleManagerWindow._run_async
    _join_current = ModuleManagerWindow._join_current

    def __init__(self):
        self._closed = False
        self.log = []

    def _flash(self, message):
        self.log.append(('flash', message))

    def _set_busy(self, busy, status='', show_bar=True):
        self.log.append(('busy', busy, status))

    def _set_error(self, message, retry=None):
        self.log.append(('error', message, retry is not None))

    def _set_progress(self, text, frac=None):
        self.log.append(('progress', text, frac))

    def _modules_changed(self):
        self.log.append('changed')

    def _populate(self):
        self.log.append('populate')


@pytest.fixture(autouse=True)
def _no_operation_left_over():
    module_manager._current = None
    yield
    module_manager._current = None


def _pump_until(cond, timeout=5):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while not cond() and time.time() < end:
        ctx.iteration(False)
        time.sleep(0.005)
    assert cond()


def test_a_second_window_cannot_start_while_the_first_one_runs():
    release = threading.Event()
    first, second = _Win(), _Win()
    assert first._run_async(release.wait, lambda err: None, busy_msg='A')
    started = []
    assert not second._run_async(lambda: started.append(1),
                                 lambda err: None, busy_msg='B')
    assert second.log[0][0] == 'flash'
    release.set()
    _pump_until(lambda: module_manager._current is None)
    assert started == []


def test_a_download_that_lands_after_its_window_closed_still_tells_the_panes():
    release = threading.Event()
    first = _Win()
    done = []
    first._run_async(release.wait, done.append, busy_msg='Downloading A…')
    first._closed = True                     # Esc, mid-download
    reopened = _Win()
    reopened._join_current()                 # what __init__ does
    assert ('busy', True, 'Downloading A…') in reopened.log

    GLib.idle_add(module_manager._report, 'Downloading A… 50%', 0.5)
    _pump_until(lambda: any(e[0] == 'progress' for e in reopened.log
                            if isinstance(e, tuple)))
    release.set()
    _pump_until(lambda: module_manager._current is None)

    assert done == []                        # the closed window's rows are gone
    assert 'changed' in first.log            # …but the panes hear of it
    assert ('busy', False, '') in reopened.log
    assert 'populate' in reopened.log


def test_the_reader_sees_a_sentence_not_the_exception():
    win = _Win()
    done = []

    def offline():
        raise urllib.error.URLError(socket.gaierror(-3, 'Temporary failure'))
    win._run_async(offline, done.append, busy_msg='A')
    _pump_until(lambda: done)
    assert 'Errno' not in done[0]
    assert 'internet' in done[0]
    assert ('error', done[0], False) in win.log
