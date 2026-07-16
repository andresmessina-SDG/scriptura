"""App-wide keyed latest-wins task runner.

Every async surface in the app has the same shape: run work off the main
thread, marshal the result back through the main loop, and drop it if a
newer request superseded it meanwhile. Half a dozen features grew private
copies of that pattern (thread + generation counter + idle finalizer),
and several re-learned the same failure mode separately: if the worker
raises and the finalizer never runs, the surface strands forever on its
spinner. This module is the single shared copy.

Semantics:

- ``submit(key, work, apply, on_error)`` runs ``work(task)`` on a daemon
  thread. ``apply(result)`` runs on the main loop only if no newer
  submission (or ``cancel``) for the same key landed in between — latest
  wins. A superseded worker finishes silently; its apply is dropped, the
  thread itself is not interrupted.
- ``on_error`` is required, not optional: when ``work`` raises, the
  exception is logged and ``on_error(exc)`` runs on the main loop under
  the same staleness rule. The API will not let a raised worker strand
  the UI mid-"Searching…" — put the spinner-stop/header-reset finalizer
  in both callbacks (or make ``on_error`` delegate to ``apply`` with an
  empty result, the house fallback).
- Keys are plain caller-namespaced strings and must include the owning
  instance for per-widget surfaces (``f'peek:{id(pane)}'``) — two panes'
  lookups must not cancel each other.
- ``work`` receives its :class:`Task` so a long scan can bail out early
  (``task.is_current()``) and stream partial results to the main loop
  (``task.post(fn, ...)``) under the same guard, instead of growing a
  private staleness check.

Callbacks given to ``apply``/``on_error``/``post`` run on the main loop;
they may touch widgets. ``work`` runs on a worker thread; it must not.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, TypeVar

from gi.repository import GLib

_log = logging.getLogger(__name__)

T = TypeVar('T')


class Task:
    """Handle for one submission — the staleness token made explicit."""

    def __init__(self, runner: 'TaskRunner', key: str, gen: int) -> None:
        self._runner = runner
        self._key = key
        self._gen = gen

    def is_current(self) -> bool:
        """True while no newer submission/cancel for the key has landed.
        Safe from any thread; long workers poll it to bail out early."""
        return self._runner._is_current(self._key, self._gen)

    def post(self, fn: Callable[..., Any], *args: Any) -> None:
        """Run ``fn(*args)`` on the main loop, dropped if superseded.

        Staleness is checked when the callback fires, not when it is
        posted — a batch already queued when a newer submission lands is
        still dropped. For streaming partial results from ``work``.
        """
        def _cb() -> bool:
            if self.is_current():
                fn(*args)
            return bool(GLib.SOURCE_REMOVE)
        GLib.idle_add(_cb)


class TaskRunner:
    """Keyed latest-wins scheduler; see the module docstring."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gens: dict[str, int] = {}

    def submit(self, key: str, work: Callable[[Task], T],
               apply: Callable[[T], None],
               on_error: Callable[[BaseException], None]) -> Task:
        with self._lock:
            gen = self._gens.get(key, 0) + 1
            self._gens[key] = gen
        task = Task(self, key, gen)

        def _worker() -> None:
            try:
                result = work(task)
            except BaseException as exc:
                _log.exception('task %r failed', key)
                GLib.idle_add(self._deliver, task, on_error, exc)
                return
            GLib.idle_add(self._deliver, task, apply, result)

        threading.Thread(target=_worker, daemon=True).start()
        return task

    def cancel(self, key: str) -> None:
        """Drop the pending apply/on_error for ``key``; the worker thread,
        if still running, finishes silently. A no-op for unknown keys."""
        with self._lock:
            if key in self._gens:
                self._gens[key] += 1

    def _is_current(self, key: str, gen: int) -> bool:
        with self._lock:
            return self._gens.get(key) == gen

    def _deliver(self, task: Task, callback: Callable[[Any], None],
                 payload: Any) -> bool:
        if task.is_current():
            callback(payload)
        return bool(GLib.SOURCE_REMOVE)


_default = TaskRunner()
submit = _default.submit
cancel = _default.cancel
