"""The download queue (downloads.py) and the Module Manager's use of it.

A download outlives the window that started it: Esc closes the window and
the worker runs on. When the state lived on the window, the window opened
next offered the same Download again, a second copy raced the first over
one temp file, and when the first landed nobody told the panes. The queue
belongs to the process now: one job per key, one worker per host.

No display needed: nothing here builds a widget.
"""
import threading
import time

import pytest
from gi.repository import GLib

import downloads
import transfer
from module_manager import ModuleManagerWindow


def _pump_until(cond, timeout=5):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while not cond() and time.time() < end:
        ctx.iteration(False)
        time.sleep(0.002)
    assert cond()


@pytest.fixture(autouse=True)
def _queue_drained():
    yield
    for job in downloads.active():
        downloads.cancel(job.key)
        job._cancel.set()
    _pump_until(lambda: not downloads.busy())


def _blocked(release, ran=None):
    def work(job):
        if ran is not None:
            ran.append(job.key)
        while not release.is_set():
            job.progress(1, 10)          # a cancel lands here
            time.sleep(0.005)
    return work


def test_the_same_work_is_never_queued_twice():
    release = threading.Event()
    first = downloads.submit('pack:x', 'X', downloads.PACKS, _blocked(release))
    again = downloads.submit('pack:x', 'X', downloads.PACKS, _blocked(release))
    assert again is first
    release.set()
    _pump_until(lambda: first.state == downloads.DONE)


def test_one_host_at_a_time_but_hosts_side_by_side():
    release = threading.Event()
    ran = []
    big = downloads.submit('pack:big', 'Big', downloads.PACKS,
                           _blocked(release, ran))
    downloads.submit('pack:next', 'Next', downloads.PACKS,
                     _blocked(release, ran))
    _pump_until(lambda: big.state == downloads.RUNNING)
    bible = downloads.submit('ebible:x', 'X', downloads.EBIBLE,
                             lambda job: ran.append(job.key))
    _pump_until(lambda: bible.state == downloads.DONE)
    # The Bible from another host came in beside the pack; the second pack
    # waits its turn behind the first.
    assert ran == ['pack:big', 'ebible:x']
    assert downloads.get('pack:next').state == downloads.QUEUED
    release.set()
    _pump_until(lambda: not downloads.busy())
    assert ran == ['pack:big', 'ebible:x', 'pack:next']


def test_cancel_stops_a_running_job_and_drops_a_queued_one():
    release = threading.Event()
    ran = []
    running = downloads.submit('pack:a', 'A', downloads.PACKS,
                               _blocked(release, ran))
    queued = downloads.submit('pack:b', 'B', downloads.PACKS,
                              _blocked(release, ran))
    _pump_until(lambda: running.state == downloads.RUNNING)
    downloads.cancel('pack:b')
    assert queued.state == downloads.CANCELLED
    downloads.cancel('pack:a')
    _pump_until(lambda: running.state == downloads.CANCELLED)
    assert ran == ['pack:a']
    assert not downloads.busy()


def test_a_job_that_lands_with_no_window_open_still_finishes():
    """on_finish is where the panes hear of it; no listener is needed."""
    finished = []
    job = downloads.submit('sword:KJV', 'KJV', downloads.CROSSWIRE,
                           lambda job: None, on_finish=finished.append)
    _pump_until(lambda: finished)
    assert finished == [job]
    assert job.state == downloads.DONE


def test_a_failure_keeps_its_error_and_can_be_tried_again():
    calls = []

    def flaky(job):
        calls.append(1)
        if len(calls) == 1:
            raise OSError('reset')
    job = downloads.submit('ebible:y', 'Y', downloads.EBIBLE, flaky)
    _pump_until(lambda: not job.active)
    assert job.state == downloads.FAILED
    assert isinstance(job.error, OSError)
    second = job.again()
    _pump_until(lambda: not second.active)
    assert second.state == downloads.DONE


def test_backend_reads_report_to_the_running_job():
    import io

    def work(job):
        transfer.read(io.BytesIO(b'x' * 200_000))
    job = downloads.submit('sword:Z', 'Z', downloads.CROSSWIRE, work)
    _pump_until(lambda: not job.active)
    assert job.done == 200_000


@pytest.mark.parametrize('done,total,expected', [
    (1, 4, 0.25),
    (1024, 0, None),     # size unknown: the bar pulses
    (0, 4, None),        # nothing yet
    (4, 4, None),        # the tail after the last byte: a full bar reads as hung
])
def test_fraction(done, total, expected):
    job = downloads.Job('k', 't', downloads.PACKS, None)
    job.done, job.total = done, total
    assert job.fraction == expected


# ── The Module Manager's side ───────────────────────────────────────────────

class _Win:
    _submit = ModuleManagerWindow._submit

    def __init__(self, told):
        self._closed = False
        self._on_modules_changed = lambda: told.append('panes')


def test_the_panes_hear_of_a_success_after_the_window_closed():
    told = []
    win = _Win(told)
    release = threading.Event()
    job = win._submit('pack:catena', 'Catena', _blocked(release))
    win._closed = True                          # Esc, mid-download
    release.set()
    _pump_until(lambda: not job.active)
    assert told == ['panes']


def test_a_cancelled_job_tells_no_one():
    told = []
    win = _Win(told)
    release = threading.Event()
    job = win._submit('pack:imagery', 'Imagery', _blocked(release))
    _pump_until(lambda: job.state == downloads.RUNNING)
    downloads.cancel('pack:imagery')
    _pump_until(lambda: not job.active)
    assert job.state == downloads.CANCELLED
    assert told == []


# ── A big download that ends out of sight gets a notification ───────────────

@pytest.mark.parametrize('total,state,window_active,sent', [
    (525 << 20, downloads.DONE, False, True),
    (525 << 20, downloads.FAILED, False, True),
    (1 << 20, downloads.DONE, False, False),       # small: ends before anyone looks away
    (525 << 20, downloads.DONE, True, False),      # the reader is watching it
    (525 << 20, downloads.CANCELLED, False, False),
])
def test_notify_only_for_a_big_download_nobody_is_watching(
        monkeypatch, total, state, window_active, sent):
    import module_manager
    notes = []

    class _App:
        def send_notification(self, nid, note):
            notes.append(nid)

    class _Watching:
        def is_active(self):
            return window_active
    monkeypatch.setattr(module_manager.Gio.Application, 'get_default',
                        lambda: _App())
    monkeypatch.setattr(module_manager, '_windows', [_Watching()])
    job = downloads.Job('pack:imagery', 'Bible Imagery', downloads.PACKS,
                        None, done_text='Bible Imagery installed')
    job.total, job.state = total, state
    job.error = OSError('x')
    module_manager._notify(job)
    assert notes == (['download-pack:imagery'] if sent else [])
