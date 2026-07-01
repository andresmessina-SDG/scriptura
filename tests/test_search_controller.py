"""Tests for search_controller.py — shared dispatch, truncation parsing, the
cross-module 'all Bibles' union, and the SearchRunner generation guard.

The threaded path isn't exercised here (needs a GLib loop); the union logic
and the stale-result guard — the parts worth protecting — are tested directly."""

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


def test_runner_drops_stale_generation():
    r = sc.SearchRunner()
    got = []
    r._gen = 5
    # A delivery tagged with an older generation is dropped.
    r._deliver(3, [('John', 3, 16, 'x')], lambda rows, t: got.append(rows))
    assert got == []
    # The current generation is delivered.
    r._deliver(5, [('John', 3, 16, 'x')], lambda rows, t: got.append(rows))
    assert got == [[('John', 3, 16, 'x')]]
