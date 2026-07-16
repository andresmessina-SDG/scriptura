"""TaskRunner latest-wins / finalizer semantics.

No display needed — the runner is pure GLib + threading. Workers are
sequenced with events so the races under test are deterministic; the
main context is pumped non-blocking until the expected delivery lands.
"""
import threading
import time

from gi.repository import GLib

import tasks


def _pump_until(predicate, timeout_s=3.0):
    """Iterate the default main context until predicate() or timeout."""
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        ctx.iteration(False)
        time.sleep(0.001)
    return predicate()


def _drain(ms=60):
    """Pump for a fixed window so anything wrongly queued gets its chance."""
    end = time.monotonic() + ms / 1000
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.001)


def _no_error(exc):
    raise AssertionError(f'on_error called: {exc!r}')


def test_apply_runs_with_result():
    r = tasks.TaskRunner()
    got = []
    r.submit('k', lambda t: 41 + 1, got.append, on_error=_no_error)
    assert _pump_until(lambda: got == [42])


def test_newer_submission_drops_older_apply():
    r = tasks.TaskRunner()
    release = threading.Event()
    got = []
    r.submit('k', lambda t: release.wait(2) and 'old' or 'old',
             got.append, on_error=_no_error)
    r.submit('k', lambda t: 'new', got.append, on_error=_no_error)
    release.set()
    assert _pump_until(lambda: 'new' in got)
    _drain()  # the old apply must never land, even late
    assert got == ['new']


def test_distinct_keys_do_not_interfere():
    r = tasks.TaskRunner()
    got = []
    r.submit('a', lambda t: 'a', got.append, on_error=_no_error)
    r.submit('b', lambda t: 'b', got.append, on_error=_no_error)
    assert _pump_until(lambda: sorted(got) == ['a', 'b'])


def test_raised_work_reaches_on_error_not_apply():
    r = tasks.TaskRunner()
    got, errs = [], []

    def work(task):
        raise RuntimeError('boom')

    r.submit('k', work, got.append, on_error=errs.append)
    assert _pump_until(lambda: len(errs) == 1)
    assert isinstance(errs[0], RuntimeError)
    _drain()
    assert got == []


def test_stale_error_is_dropped_too():
    r = tasks.TaskRunner()
    release = threading.Event()
    got, errs = [], []

    def failing(task):
        release.wait(2)
        raise RuntimeError('stale boom')

    r.submit('k', failing, got.append, on_error=errs.append)
    r.submit('k', lambda t: 'new', got.append, on_error=errs.append)
    release.set()
    assert _pump_until(lambda: got == ['new'])
    _drain()
    assert errs == []


def test_cancel_drops_pending_apply():
    r = tasks.TaskRunner()
    release = threading.Event()
    got = []
    r.submit('k', lambda t: release.wait(2) and 'x' or 'x',
             got.append, on_error=_no_error)
    r.cancel('k')
    release.set()
    _drain(120)
    assert got == []


def test_cancel_unknown_key_is_noop():
    tasks.TaskRunner().cancel('never-submitted')


def test_worker_sees_supersession_via_is_current():
    r = tasks.TaskRunner()
    release = threading.Event()
    seen = []

    def work(task):
        release.wait(2)
        seen.append(task.is_current())
        return None

    r.submit('k', work, lambda _v: None, on_error=_no_error)
    r.submit('k', lambda t: None, lambda _v: None, on_error=_no_error)
    release.set()
    assert _pump_until(lambda: len(seen) == 1)
    assert seen == [False]


def test_post_streams_while_current_and_drops_after():
    r = tasks.TaskRunner()
    gate = threading.Event()
    batches = []

    def work(task):
        task.post(batches.append, 'first')
        gate.wait(2)          # superseded while parked here
        task.post(batches.append, 'late')
        return None

    r.submit('k', work, lambda _v: None, on_error=_no_error)
    assert _pump_until(lambda: batches == ['first'])
    r.submit('k', lambda t: None, lambda _v: None, on_error=_no_error)
    gate.set()
    _drain(120)  # the late batch fires its idle, and must be dropped
    assert batches == ['first']


def test_module_level_default_runner():
    got = []
    tasks.submit('test-default', lambda t: 'ok', got.append,
                 on_error=_no_error)
    assert _pump_until(lambda: got == ['ok'])
