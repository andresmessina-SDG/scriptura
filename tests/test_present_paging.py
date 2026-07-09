"""Tests for present_paging — the pure pagination + step-index math behind
presentation mode. No GTK / no display: this is the headless-testable core the
view layers pixel measurement on top of."""

import present_paging
from present_paging import paginate, Stepper, tighten_capacity


# ── paginate ────────────────────────────────────────────────────────────────

def test_empty():
    assert paginate([], 100) == []


def test_verse_at_a_time_capacity_zero():
    assert paginate([3, 3, 3], 0) == [(0, 1), (1, 2), (2, 3)]


def test_verse_at_a_time_negative_capacity():
    assert paginate([5, 5], -1) == [(0, 1), (1, 2)]


def test_greedy_grouping_respects_capacity():
    # 4+4=8 fits 10; +4=12 overflows → new page; last 4 alone.
    assert paginate([4, 4, 4, 4], 10) == [(0, 2), (2, 4)]


def test_exact_fit_stays_on_page():
    assert paginate([5, 5], 10) == [(0, 2)]


def test_one_over_splits():
    assert paginate([5, 6], 10) == [(0, 1), (1, 2)]


def test_oversized_single_item_gets_own_page():
    # A lone item heavier than capacity is never dropped or split.
    assert paginate([50], 10) == [(0, 1)]


def test_oversized_item_between_normal_ones():
    # 3 fits; 99 overflows → own page; 3 starts the next.
    assert paginate([3, 99, 3], 10) == [(0, 1), (1, 2), (2, 3)]


def test_pages_cover_every_item_contiguously():
    weights = [2, 7, 1, 4, 9, 3, 3]
    pages = paginate(weights, 10)
    assert pages[0][0] == 0
    assert pages[-1][1] == len(weights)
    for (a, b), (c, _d) in zip(pages, pages[1:]):
        assert b == c  # no gaps, no overlap
        assert a < b   # every page non-empty


# ── Stepper ───────────────────────────────────────────────────────────────

def test_stepper_starts_at_zero():
    s = Stepper()
    assert s.index == 0
    assert s.count == 0


def test_next_prev_within_bounds():
    s = Stepper()
    s.set_count(3)
    assert s.next() is True and s.index == 1
    assert s.next() is True and s.index == 2
    assert s.next() is False and s.index == 2   # clamped at last, no wrap
    assert s.prev() is True and s.index == 1
    assert s.prev() is True and s.index == 0
    assert s.prev() is False and s.index == 0   # clamped at first


def test_home_and_end():
    s = Stepper()
    s.set_count(5)
    s.next(); s.next()
    assert s.index == 2
    assert s.home() is True and s.index == 0
    assert s.home() is False                     # already there
    assert s.end() is True and s.index == 4
    assert s.end() is False


def test_at_start_at_end_flags():
    s = Stepper()
    s.set_count(2)
    assert s.at_start and not s.at_end
    s.next()
    assert s.at_end and not s.at_start


def test_set_count_clamps_current_index():
    s = Stepper()
    s.set_count(10)
    s.end()
    assert s.index == 9
    s.set_count(4)          # re-paginate shrinks page count under the cursor
    assert s.index == 3     # clamped, not blank/out-of-range


def test_go_to_clamps():
    s = Stepper()
    s.set_count(5)
    assert s.go_to(3) is True and s.index == 3
    assert s.go_to(99) is True and s.index == 4   # clamped to last
    assert s.go_to(-2) is True and s.index == 0   # clamped to first
    assert s.go_to(0) is False                    # already there


def test_set_count_zero_is_safe():
    s = Stepper()
    s.set_count(3)
    s.next()
    s.set_count(0)
    assert s.index == 0 and s.count == 0
    assert s.next() is False
    assert s.home() is False


# ── tighten_capacity (overflow correction) ──────────────────────────────────

def test_tighten_returns_none_when_fits():
    assert tighten_capacity(1000, 800, 800) is None    # exactly fits
    assert tighten_capacity(1000, 800, 500) is None    # room to spare


def test_tighten_shrinks_proportionally_on_overflow():
    # content twice the viewport → budget roughly halved (× 0.9 margin)
    new = tighten_capacity(1000, 400, 800)
    assert new is not None and new < 1000
    assert new == int(1000 * 400 / 800 * 0.90)


def test_tighten_is_monotonic_and_floored():
    # a wildly-too-tall page still yields a usable (>=1) budget
    assert tighten_capacity(10, 10, 100000) == 1


def test_tighten_guards_bad_inputs():
    assert tighten_capacity(0, 400, 800) is None
    assert tighten_capacity(1000, 0, 800) is None


def test_tighten_converges_when_iterated():
    # Simulate the view loop: height ∝ verses-on-page ∝ capacity. Shrinking the
    # budget shrinks the page until it fits; the loop must terminate.
    cap, viewport = 1000, 400
    for _ in range(50):
        natural = cap                      # taller pages hold more, ~linear
        nxt = tighten_capacity(cap, viewport, natural)
        if nxt is None:
            break
        assert nxt < cap                   # always makes progress
        cap = nxt
    assert cap <= viewport                 # settled within the viewport


def test_module_exposes_public_api():
    assert hasattr(present_paging, 'paginate')
    assert hasattr(present_paging, 'Stepper')
    assert hasattr(present_paging, 'tighten_capacity')
