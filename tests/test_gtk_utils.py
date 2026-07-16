"""DelayedSpinner threshold semantics.

No display needed: the helper only calls set_visible/start/stop on the
spinner, so a duck-typed fake records the calls while GLib timers run on
the default main context.
"""
from gi.repository import GLib

from gtk_utils import DelayedSpinner


class FakeSpinner:
    def __init__(self):
        self.visible = False
        self.spinning = False

    def set_visible(self, visible):
        self.visible = visible

    def start(self):
        self.spinning = True

    def stop(self):
        self.spinning = False


def _pump(ms):
    """Run the default main context until `ms` have elapsed."""
    done = []
    GLib.timeout_add(ms, lambda: done.append(1) and GLib.SOURCE_REMOVE)
    ctx = GLib.MainContext.default()
    while not done:
        ctx.iteration(True)


def test_fast_op_never_shows_spinner():
    s = FakeSpinner()
    d = DelayedSpinner(s, delay_ms=30)
    d.start()
    d.stop()  # op finished under the threshold
    _pump(80)
    assert not s.visible and not s.spinning


def test_slow_op_shows_after_threshold():
    s = FakeSpinner()
    d = DelayedSpinner(s, delay_ms=20)
    d.start()
    assert not s.visible  # not yet — the threshold gates it
    _pump(60)
    assert s.visible and s.spinning
    d.stop()
    assert not s.visible and not s.spinning


def test_start_while_pending_keeps_original_threshold():
    s = FakeSpinner()
    d = DelayedSpinner(s, delay_ms=20)
    d.start()
    d.start()  # re-arm attempt must not add a second timer
    _pump(60)
    assert s.visible
    d.stop()
    _pump(40)  # a stray second timer would re-show it
    assert not s.visible and not s.spinning


def test_stop_is_safe_when_never_started():
    s = FakeSpinner()
    DelayedSpinner(s, delay_ms=20).stop()
    assert not s.visible and not s.spinning
