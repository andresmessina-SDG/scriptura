"""The rule that ends a rebuild's scroll hold.

A content toggle empties the buffer, GTK collapses the vadjustment's `upper`
to its estimate for the lines it has not validated, and the clamp that follows
paints the chapter top. `hold_scroll` pins the position through that, so the
only question that matters is when the pin comes off.

It must not come off on the strength of a tall `upper`. A tall `upper` reads
the same before GTK has collapsed anything as it does after the rebuild has
finished, and a live log caught exactly that: released at upper=27462, and
four frames later the chapter top at upper=836. The restore is the end signal.

No widgets: the hold's methods are borrowed onto a stand-in, as in
test_focus_unit.
"""
from pane import _ReadingScrolledWindow


class FakeAdjustment:
    def __init__(self, value, upper, page):
        self._value, self._upper, self._page = value, upper, page
        self.handler = None

    def get_value(self):
        return self._value

    def set_value(self, v):
        self._value = v

    def get_upper(self):
        return self._upper

    def set_upper(self, v):
        self._upper = v

    def get_page_size(self):
        return self._page

    def connect(self, _signal, cb):
        self.handler = cb
        return 1

    def disconnect(self, _id):
        self.handler = None

    def collapse_to(self, upper):
        """What GTK does from its validation idle: a short height, and the
        value clamped against it."""
        self._upper = upper
        self._value = min(self._value, max(0.0, upper - self._page))


class Hold:
    hold_scroll = _ReadingScrolledWindow.hold_scroll
    release_scroll_hold = _ReadingScrolledWindow.release_scroll_hold
    _release_hold = _ReadingScrolledWindow._release_hold
    _reassert_held_scroll = _ReadingScrolledWindow._reassert_held_scroll
    _on_adj_changed = _ReadingScrolledWindow._on_adj_changed

    def __init__(self, adj):
        self.adj = adj
        self._hold_value = None
        self._hold_handler = None
        self._faked_upper = None
        self._in_hold = False

    def get_vadjustment(self):
        return self.adj


    @property
    def held(self):
        return self._hold_value is not None


def _deep_in_psalm_119():
    """His measured numbers: parked at 9773.8 in a 27462px document."""
    return Hold(FakeAdjustment(value=9773.8, upper=27462.0, page=663.0))


def test_a_tall_upper_does_not_end_the_hold():
    # The reassert that runs before GTK has collapsed anything sees the
    # document's real, pre-rebuild height. That is not a finished rebuild.
    hold = _deep_in_psalm_119()
    hold.hold_scroll()
    hold._reassert_held_scroll()
    assert hold.held


def test_the_collapse_after_that_reassert_is_still_guarded():
    hold = _deep_in_psalm_119()
    hold.hold_scroll()
    hold._reassert_held_scroll()          # tall: nothing to undo
    hold.adj.collapse_to(836.0)           # the collapse the log caught
    hold._reassert_held_scroll()
    assert hold.adj.get_value() == 9773.8, 'the chapter top would be painted'


def test_the_restore_ends_the_hold():
    hold = _deep_in_psalm_119()
    hold.hold_scroll()
    hold.adj.collapse_to(836.0)
    hold._reassert_held_scroll()
    hold.release_scroll_hold()
    assert not hold.held
    assert hold.adj.handler is None, 'the changed handler outlived the hold'


def test_a_released_hold_stops_fighting_the_adjustment():
    # Once released, a later collapse must be left alone — otherwise the hold
    # would pin the scrollbar against a navigation that means to land
    # somewhere else.
    hold = _deep_in_psalm_119()
    hold.hold_scroll()
    hold.release_scroll_hold()
    hold.adj.collapse_to(836.0)
    hold._reassert_held_scroll()
    assert hold.adj.get_value() == 173.0


def test_our_own_faked_height_is_never_read_as_the_real_one():
    hold = _deep_in_psalm_119()
    hold.hold_scroll()
    hold.adj.collapse_to(836.0)
    hold._reassert_held_scroll()          # fakes upper to carry the position
    assert hold.adj.get_upper() == 9773.8 + 663.0
    hold._reassert_held_scroll()          # reads back what it wrote
    assert hold.held
