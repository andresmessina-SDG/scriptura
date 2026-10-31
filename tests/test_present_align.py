"""Tests for present_align — the pure verse-number join behind bilingual
(parallel) presentation. No GTK / no display."""

import present_align
from present_align import align, project, coalesce


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


def test_equivalent_verses_align_after_mapping_numbered_titles():
    primary = project([(1, 'Lord'), (2, 'Many')], lambda v: v, lambda v: v)
    synodal = project([(1, 'Title'), (2, 'Господи'), (3, 'многие')],
                      lambda v: v - 1, lambda v: v + 1)
    assert align(primary.verses, synodal.verses) == [
        (0, None, 'Title'), (1, 'Lord', 'Господи'), (2, 'Many', 'многие')]


def test_a_title_that_reverse_maps_to_one_is_separate_from_the_body():
    vulgate = project([(1, 'Title'), (2, 'Domine'), (3, 'multi')],
                      lambda v: max(1, v - 1), lambda v: v + 1)
    assert vulgate.verses == [(0, 'Title'), (1, 'Domine'), (2, 'multi')]
    assert vulgate.source_to_app == {1: 0, 2: 1, 3: 2}


def test_many_to_one_mapping_preserves_every_source_line_in_order():
    projected = project([(1, 'First'), (2, 'Part one'), (3, 'Part two')],
                        lambda v: min(v, 2), lambda v: v)
    assert projected.verses == [(1, 'First'), (2, 'Part one<br/>Part two')]
    assert projected.parts[2] == [(2, 'Part one'), (3, 'Part two')]


def test_a_two_line_title_is_preserved_in_one_preface_row():
    projected = project([(1, 'Title one'), (2, 'Title two'), (3, 'Body')],
                        lambda v: max(0, v - 2), lambda v: v + 2)
    assert projected.verses == [(0, 'Title one<br/>Title two'), (1, 'Body')]


def test_forward_mapping_rescues_a_body_line_reverse_mapped_to_zero():
    projected = project([(1, 'Shepherd'), (2, 'Pastures')],
                        lambda v: 0 if v == 1 else v, lambda v: v)
    assert projected.verses == [(1, 'Shepherd'), (2, 'Pastures')]


def test_combined_verse_coalesces_both_sides_without_repeating_or_losing_text():
    a = project([(5, 'Rejoice'), (6, 'Sing')], lambda v: v, lambda v: v)
    b = project([(6, 'Rejoice and sing')], lambda v: 5, lambda v: 6,
                app_verses=[5, 6])
    left, right = coalesce(a, b)
    assert left.parts == {5: [(5, 'Rejoice'), (6, 'Sing')]}
    assert right.parts == {5: [(6, 'Rejoice and sing')]}
    assert left.aliases == right.aliases == {6: 5}
    assert left.source_to_app[6] == right.source_to_app[6] == 5


def test_a_forward_alias_does_not_hide_an_existing_reverse_mapped_verse():
    projected = project([(10, 'Not leave my soul'), (11, 'Path of life')],
                        lambda v: v, lambda v: 10, app_verses=[10, 11])
    assert projected.aliases == {}
    assert projected.verses == [(10, 'Not leave my soul'), (11, 'Path of life')]


def test_an_omitted_verse_is_not_assumed_to_be_part_of_its_neighbour():
    projected = project([(1, 'First'), (3, 'Third')], lambda v: v, lambda v: v)
    assert projected.aliases == {}
    assert align([(1, 'One'), (2, 'Two'), (3, 'Three')], projected.verses)[1] == (
        2, 'Two', None)
