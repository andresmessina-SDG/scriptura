"""Tests for search_controller.py — shared dispatch, truncation parsing, the
cross-module 'all Bibles' union, and the SearchRunner stale-result guard.

The runner now rides the shared tasks runner (whose semantics have their own
suite in test_tasks); here the guard is exercised end-to-end through
SearchRunner's public API, pumping the default GLib main context."""

import threading
import time

from gi.repository import GLib

import search_controller as sc


def test_split_truncation_none():
    rows, t = sc.split_truncation([('John', 3, 16, 'x'), ('Genesis', 1, 1, 'y')])
    assert t is False
    assert len(rows) == 2


def test_split_truncation_sentinel():
    rows, t = sc.split_truncation([('John', 3, 16, 'x'), ('', 0, 0, '')])
    assert t is True
    assert rows == [('John', 3, 16, 'x')]


def test_search_all_union_dedup_and_canonical_order(monkeypatch):
    monkeypatch.setattr(sc, 'bible_modules', lambda: ['A', 'B'])
    data = {
        'A': [('Genesis', 1, 1, 'beginning A'), ('John', 3, 16, 'loved A')],
        'B': [('John', 3, 16, 'loved B'), ('Genesis', 1, 1, 'beginning B'),
              ('Psalms', 23, 1, 'shepherd B')],
    }
    monkeypatch.setattr(sc, 'search_backend', lambda m, q, c, **k: data[m])

    res = sc.search_all_bibles('x', False)
    refs = [(b, ch, v) for (b, ch, v, _t) in res]
    # Deduped to unique references, sorted canonical (Gen=1, Ps=19, John=43).
    assert refs == [('Genesis', 1, 1), ('Psalms', 23, 1), ('John', 3, 16)]
    # Snippet comes from the first translation that matched (A wins the shared).
    text = {(b, ch, v): t for (b, ch, v, t) in res}
    assert text[('Genesis', 1, 1)] == 'beginning A'
    assert text[('John', 3, 16)] == 'loved A'
    assert text[('Psalms', 23, 1)] == 'shepherd B'


def test_search_all_preserves_truncation(monkeypatch):
    monkeypatch.setattr(sc, 'bible_modules', lambda: ['A'])
    monkeypatch.setattr(sc, 'search_backend',
                        lambda m, q, c, **k: [('John', 3, 16, 'x'), ('', 0, 0, '')])
    res = sc.search_all_bibles('x', False)
    assert res[-1][0] == ''     # sentinel preserved for the UI


def _pump_until(predicate, timeout_s=3.0):
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        ctx.iteration(False)
        time.sleep(0.001)
    return predicate()


def test_runner_drops_stale_generation():
    r = sc.SearchRunner()
    got = []
    release = threading.Event()

    def slow_search():
        release.wait(2)
        return [('John', 3, 16, 'old')]

    r.run(slow_search, lambda rows, t: got.append(rows))
    r.run(lambda: [('John', 3, 16, 'new')], lambda rows, t: got.append(rows))
    release.set()
    assert _pump_until(lambda: [('John', 3, 16, 'new')] in got)
    _pump_until(lambda: False, timeout_s=0.06)  # let a wrong 'old' land
    assert got == [[('John', 3, 16, 'new')]]


def test_runner_raised_search_delivers_empty():
    # A raising search must still reach on_done (empty), never strand the UI.
    r = sc.SearchRunner()
    got = []

    def boom():
        raise RuntimeError('backend failure')

    r.run(boom, lambda rows, t: got.append((rows, t)))
    assert _pump_until(lambda: got == [([], False)])
