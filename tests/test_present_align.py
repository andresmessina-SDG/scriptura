"""Tests for present_align — the pure verse-number join behind bilingual
(parallel) presentation. No GTK / no display."""

import present_align
from present_align import align


def test_empty_both():
    assert align([], []) == []


def test_fully_matching():
    a = [(1, 'a1'), (2, 'a2')]
    b = [(1, 'b1'), (2, 'b2')]
    assert align(a, b) == [(1, 'a1', 'b1'), (2, 'a2', 'b2')]


def test_a_only_when_b_empty():
    assert align([(1, 'a1'), (2, 'a2')], []) == [
        (1, 'a1', None), (2, 'a2', None)]


def test_b_only_when_a_empty():
    assert align([], [(1, 'b1')]) == [(1, None, 'b1')]


def test_interleaved_gaps():
    # a omits 2 (critical text); b omits 3. Outer join keeps every verse.
    a = [(1, 'a1'), (3, 'a3')]
    b = [(1, 'b1'), (2, 'b2')]
    assert align(a, b) == [
        (1, 'a1', 'b1'),
        (2, None, 'b2'),
        (3, 'a3', None),
    ]


def test_orders_by_verse_number():
    a = [(3, 'a3'), (1, 'a1')]
    b = [(2, 'b2')]
    assert [v for v, _a, _b in align(a, b)] == [1, 2, 3]


def test_duplicate_verse_first_wins():
    a = [(1, 'first'), (1, 'second')]
    assert align(a, []) == [(1, 'first', None)]


def test_module_exposes_public_api():
    assert hasattr(present_align, 'align')
