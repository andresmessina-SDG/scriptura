"""The download queue: every install, update and removal the Module Manager
starts, for the whole process.

A download outlives the window that started it, so its state lives here,
not on the window. Each job runs on its lane's one worker thread: one lane
per host (CrossWire is one fragile machine, and has been down four times this
year; hammering it with parallel requests would be rude), so a Bible from
eBible.org can arrive while the imagery pack is still coming from GitHub.
The same work never queues twice: submitting a key already queued or
running hands back the job in flight.

Listeners hear every change on the main loop. Progress is reported at most
ten times a second.
"""

import logging
import threading
import time

from gi.repository import GLib

import transfer

_log = logging.getLogger('scriptura.downloads')

# The lane a job runs on: one worker thread each.
CROSSWIRE = 'crosswire'     # SWORD modules and catalogues, imports
EBIBLE = 'ebible'           # eBible.org translations
PACKS = 'packs'             # the curated packs and open databases

QUEUED, RUNNING, DONE, FAILED, CANCELLED = (
    'queued', 'running', 'done', 'failed', 'cancelled')

_EMIT_EVERY = 0.1


class Job:
    """One operation. `work(job)` runs on the lane's worker thread; it may
    report bytes through `job.progress` (or transfer.read, which is bound to
    it) and a wordy step through `job.set_phase`. `on_finish(job)` runs on the
    main loop once the job has ended, however it ended.

    `row` False marks work with no row of its own (a catalogue refresh, an
    import), which a window shows on its own progress bar instead."""

    def __init__(self, key, title, lane, work, on_finish=None, row=True,
                 done_text=''):
        self.key = key
        self.title = title
        self.lane = lane
        self.work = work
        self.on_finish = on_finish
        self.row = row
        self.done_text = done_text
        self.state = QUEUED
        self.done = 0
        self.total = 0
        self.phase = ''
        self.error = None
        self._cancel = threading.Event()
        self._last_emit = 0.0

    @property
    def active(self):
        return self.state in (QUEUED, RUNNING)

    @property
    def fraction(self):
        """How far the bytes are, or None while there is no measure: before
        the first byte, when the size is unknown, and in the tail after the
        last byte (unpacking, parsing), where a bar frozen full would read as
        hung."""
        if self.total and 0 < self.done < self.total:
            return self.done / self.total
        return None

    def progress(self, done, total):
        """Worker thread: `done` of `total` bytes. Raises transfer.Cancelled
        once the reader has cancelled."""
        if self._cancel.is_set():
            raise transfer.Cancelled()
        self.done, self.total = done, total
        now = time.monotonic()
        if now - self._last_emit >= _EMIT_EVERY or done >= total > 0:
            self._last_emit = now
            GLib.idle_add(_emit, self)

    def set_phase(self, text):
        """Worker thread: name a step that has no byte count."""
        if self._cancel.is_set():
            raise transfer.Cancelled()
        self.phase = text
        GLib.idle_add(_emit, self)

    def again(self):
        """Submit the same work again (the Retry of a failed job)."""
        return submit(self.key, self.title, self.lane, self.work,
                      on_finish=self.on_finish, row=self.row,
                      done_text=self.done_text)


_jobs: dict = {}           # key -> Job, while queued or running
_queues: dict = {}         # lane -> [Job]
_workers: dict = {}        # lane -> Thread
_cond = threading.Condition()
_listeners: list = []


def submit(key, title, lane, work, on_finish=None, row=True, done_text=''):
    """Queue `work` (main loop only). A key already queued or running is not
    queued again; its job is returned instead."""
    job = _jobs.get(key)
    if job is not None:
        return job
    job = Job(key, title, lane, work, on_finish, row, done_text)
    _jobs[key] = job
    with _cond:
        _queues.setdefault(lane, []).append(job)
        if lane not in _workers:
            _workers[lane] = threading.Thread(
                target=_worker, args=(lane,), daemon=True,
                name=f'downloads-{lane}')
            _workers[lane].start()
        _cond.notify_all()
    _emit(job)
    return job


def get(key):
    """The job queued or running under `key`, or None."""
    return _jobs.get(key)


def active():
    return list(_jobs.values())


def busy():
    """Whether anything is queued or running."""
    return bool(_jobs)


def cancel(key):
    """Stop a job (main loop only). A queued one never starts; a running one
    stops at its next progress report."""
    job = _jobs.get(key)
    if job is None:
        return
    job._cancel.set()
    with _cond:
        queue = _queues.get(job.lane, [])
        waiting = job in queue
        if waiting:
            queue.remove(job)
    if waiting:
        job.state = CANCELLED
        _finish(job)


def listen(fn):
    """Call fn(job) on the main loop whenever a job changes."""
    _listeners.append(fn)


def unlisten(fn):
    if fn in _listeners:
        _listeners.remove(fn)


def _worker(lane):
    while True:
        with _cond:
            while not _queues[lane]:
                _cond.wait()
            job = _queues[lane].pop(0)
        job.state = RUNNING
        GLib.idle_add(_emit, job)
        transfer.bind(job.progress)
        try:
            job.work(job)
            outcome = DONE
        except transfer.Cancelled:
            outcome = CANCELLED
        except Exception as e:
            _log.error('%s failed: %r', job.key, e, exc_info=True)
            job.error = e
            outcome = FAILED
        finally:
            transfer.bind(None)
        GLib.idle_add(_finish, job, outcome)


def _finish(job, outcome=None):
    # The outcome is set here, on the main loop, in the same step that takes
    # the job off the list: nothing can see a finished job still listed as
    # in flight, and a Retry submitted from the error is a new job.
    if outcome is not None:
        job.state = outcome
    if _jobs.get(job.key) is job:
        del _jobs[job.key]
    if job.on_finish is not None:
        try:
            job.on_finish(job)
        except Exception:
            _log.exception('%s: finishing failed', job.key)
    _emit(job)
    return GLib.SOURCE_REMOVE


def _emit(job):
    for fn in list(_listeners):
        try:
            fn(job)
        except Exception:
            _log.exception('download listener failed')
    return GLib.SOURCE_REMOVE
