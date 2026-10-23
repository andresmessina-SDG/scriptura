"""Tests for plan_session.PlanSession — stepping through a plan day."""

from plan_session import PlanSession

DAY = [('Matthew', 12, 22, 12, 50), ('Luke', 7, 36, 8, 3)]


def test_a_passage_opens_at_its_first_verse_and_lights_its_verses():
    s = PlanSession('p', 10, DAY)
    assert s.target() == ('Matthew', 12, 22)
    assert s.lit() == ('Matthew', 12, 22, 50)
    assert s.where() == 'Day 11 · Matthew 12:22–50 · 1 of 2'


def test_the_end_of_a_passage_offers_the_next_by_where_it_opens():
    s = PlanSession('p', 10, DAY)
    assert s.step() == 'next'
    assert s.offer() == 'Next: Luke 7:36 →'
    s.advance()
    assert s.target() == ('Luke', 7, 36)
    assert s.lit() == ('Luke', 7, 36, 0)          # on to the chapter's end


def test_a_passage_over_two_chapters_continues_into_the_second():
    s = PlanSession('p', 10, DAY, index=1)
    assert s.step() == 'continue'
    assert s.offer() == 'Continue: Luke 8 →'
    s.advance()
    assert s.target() == ('Luke', 8, 0)
    assert s.lit() == ('Luke', 8, 0, 3)
    assert s.step() == 'done'
    assert s.offer() == 'Mark day 11 read'


def test_paging_on_inside_the_passage_is_held_and_elsewhere_is_not():
    s = PlanSession('p', 10, DAY, index=1)
    assert s.holds('Luke', 8)
    assert not s.holds('Luke', 9)
    assert not s.holds('Matthew', 12)
    s.follow(8)
    assert s.lit() == ('Luke', 8, 0, 3)


def test_a_chapter_plan_steps_through_whole_chapters():
    s = PlanSession('p', 2, [('Genesis', 3, 0, 4, 0), ('Psalms', 4, 0, 4, 0)])
    assert s.target() == ('Genesis', 3, 0)
    assert s.lit() == ('Genesis', 3, 0, 0)
    assert s.offer() == 'Continue: Genesis 4 →'
    s.advance()
    assert s.offer() == 'Next: Psalms 4 →'
    s.advance()
    assert s.where() == 'Day 3 · Psalms 4 · 2 of 2'
    assert s.step() == 'done'


def test_a_one_passage_day_names_no_count():
    s = PlanSession('p', 0, [('John', 3, 1, 3, 21)])
    assert s.where() == 'Day 1 · John 3:1–21'


# ── The window's side: following the reader, and letting go ─────────────────

class _Pane:
    def __init__(self):
        self.lit = 'unset'

    def set_lit_passage(self, lit, on_end=None, on_left=None):
        self.lit = lit


class _Pill:
    def __init__(self):
        self.where = None
        self.shown = False

    def show_where(self, text):
        self.where = text

    def dismiss(self):
        self.shown = False


def _window():
    from types import SimpleNamespace
    import window
    win = SimpleNamespace(pane1=_Pane(), pane2=_Pane(), _plan_pill=_Pill(),
                          _plan_session=PlanSession('p', 10, DAY, index=1))
    for name in ('_on_plan_left', '_end_plan_session', '_light_plan_passage',
                 '_on_plan_end_seen'):
        setattr(win, name, getattr(window.BibleWindow, name).__get__(win))
    return win


def test_paging_into_the_passages_next_chapter_carries_the_session():
    win = _window()
    win._on_plan_left('Luke', 8)
    assert win._plan_session.chapter == 8
    assert win.pane1.lit == win.pane2.lit == ('Luke', 8, 0, 3)


def test_going_anywhere_else_ends_the_session_and_lifts_the_veil():
    win = _window()
    win._on_plan_left('Romans', 1)
    assert win._plan_session is None
    assert win.pane1.lit is None and win.pane2.lit is None


def test_a_refused_move_ends_the_session_rather_than_naming_a_passage():
    """A module without the book refuses the move with a toast; a pill
    left naming Genesis over the chapter still on screen would be wrong."""
    import window
    win = _window()
    win._current_loc = ('Matthew', 1)
    win._go_to = lambda book, chapter, verse=None: None      # refused
    win._plan_session = PlanSession('p', 2, [('Genesis', 3, 0, 4, 0)])
    window.BibleWindow._plan_session_go(win)
    assert win._plan_session is None
    assert win.pane1.lit is None
