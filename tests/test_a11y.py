"""a11y helpers: announcement throttling and highlight naming.

The parts that need no display. The role/relation/announcement *wiring* —
which needs real widgets — is asserted by tools/verify-a11y.py.
"""
import a11y
import annotation_dialogs


class FakeDisplay:
    """A non-Broadway display — announcing is safe against it."""
    class __gtype__:
        name = 'GdkWaylandDisplay'


class FakeAccessible:
    """Stands in for a widget: records what was announced against it."""

    def __init__(self, display=None):
        self.announced = []
        self._display = FakeDisplay() if display is None else display

    def get_display(self):
        return self._display

    def announce(self, message, priority):
        self.announced.append(message)

    def update_property(self, _props, values):
        self.properties = values


class BroadwayDisplay:
    class __gtype__:
        name = 'GdkBroadwayDisplay'


def test_announce_is_suppressed_on_broadway():
    # gtk_accessible_announce segfaults there; the harnesses drive Broadway.
    w = FakeAccessible(display=BroadwayDisplay())
    a11y.announce(w, 'No matches')
    assert w.announced == []


# ── announce / status ────────────────────────────────────────────────────

def test_announce_skips_empty_message():
    w = FakeAccessible()
    a11y.announce(w, '')
    assert w.announced == []


def test_announce_passes_message_through():
    w = FakeAccessible()
    a11y.announce(w, 'No matches')
    assert w.announced == ['No matches']


# ── ProgressAnnouncer ────────────────────────────────────────────────────

def test_progress_announces_the_first_message_immediately():
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer()
    p.progress(w, 'Indexing 1/66')
    assert w.announced == ['Indexing 1/66']


def test_first_message_survives_a_freshly_booted_machine(monkeypatch):
    """time.monotonic() counts from an arbitrary epoch — boot, on Linux.

    A machine up for two seconds returns 2.0, which is less than the
    throttle interval, so a 0.0 "never announced" sentinel swallowed the
    first message of every run. It reproduced only on fresh CI containers;
    a workstation with days of uptime never saw it."""
    monkeypatch.setattr(a11y.time, 'monotonic', lambda: 2.0)
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=5.0)
    p.progress(w, 'Indexing 1/66')
    assert w.announced == ['Indexing 1/66']


def test_throttle_still_holds_on_a_freshly_booted_machine(monkeypatch):
    clock = {'t': 2.0}
    monkeypatch.setattr(a11y.time, 'monotonic', lambda: clock['t'])
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=5.0)
    p.progress(w, 'Indexing 1/66')
    clock['t'] = 3.0                      # within the interval
    p.progress(w, 'Indexing 2/66')
    assert w.announced == ['Indexing 1/66']
    clock['t'] = 9.0                      # past it
    p.progress(w, 'Indexing 3/66')
    assert w.announced == ['Indexing 1/66', 'Indexing 3/66']


def test_progress_throttles_the_flood():
    # 66 books' worth of progress must not become 66 interruptions.
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=60.0)
    for i in range(1, 67):
        p.progress(w, f'Indexing {i}/66')
    assert w.announced == ['Indexing 1/66']


def test_progress_lets_a_later_message_through_once_the_interval_passes():
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=0.0)
    p.progress(w, 'Indexing 1/66')
    p.progress(w, 'Indexing 2/66')
    assert w.announced == ['Indexing 1/66', 'Indexing 2/66']


def test_progress_never_repeats_identical_text():
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=0.0)
    p.progress(w, 'Indexing 1/66')
    p.progress(w, 'Indexing 1/66')
    assert w.announced == ['Indexing 1/66']


def test_done_beats_the_throttle():
    # The result of a search must never be the message that got dropped.
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=60.0)
    p.progress(w, 'Indexing 1/66')
    p.done(w, '12 verses found')
    assert w.announced == ['Indexing 1/66', '12 verses found']


def test_reset_reopens_the_window():
    w = FakeAccessible()
    p = a11y.ProgressAnnouncer(interval=60.0)
    p.progress(w, 'Indexing 1/66')
    p.reset()
    p.progress(w, 'Indexing 2/66')
    assert w.announced == ['Indexing 1/66', 'Indexing 2/66']


# ── highlight naming (what a verse announcement says) ────────────────────

def test_highlight_name_covers_every_offered_swatch():
    # Whatever the picker can store, the announcement must be able to name.
    for hex_value, _css, name in annotation_dialogs.highlight_swatches():
        assert annotation_dialogs.highlight_name(hex_value) == name


def test_highlight_name_is_none_for_no_highlight():
    assert annotation_dialogs.highlight_name(None) is None
    assert annotation_dialogs.highlight_name('#123456') is None
