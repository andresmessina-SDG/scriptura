"""When the reading-tools cluster stays open, and when it gets out of the way.

The אΩ anchor keeps ※ and f* folded behind it and blooms them on hover. The
rule is the pointer's: when the pointer leaves, the cluster folds — down to
whichever tools are switched on, which stay on show to account for the marks
they put in the text. Two things make that harder than it looks. A click
parks keyboard focus on the button it activated and leaves it there, so any
rule that honours parked focus pins the cluster open until something
unrelated is clicked — twice now, once through a click latch and once
through an unconditional hold on a focused member. And the bloom opens
leftward, putting ※ and f* *before* the anchor in tab order, so the cluster
has to move focus itself.

No display: the methods are borrowed off the real class onto stand-ins, the
way tests/test_reading_audio.py borrows the audio state machines.
"""
import gi

gi.require_version('Gdk', '4.0')
from gi.repository import Gdk

from window import BibleWindow


class FakeToggle:
    def __init__(self, active=False, sensitive=True):
        self.active = active
        self.sensitive = sensitive
        self.focused = False

    def get_active(self):
        return self.active

    def set_active(self, value):
        self.active = value

    def get_sensitive(self):
        return self.sensitive

    def grab_focus(self):
        self.focused = True
        return True


class FakeRevealer:
    def __init__(self, child):
        self.child = child
        self.revealed = False

    def get_child(self):
        return self.child

    def set_reveal_child(self, value):
        self.revealed = value

    def get_reveal_child(self):
        return self.revealed


class FakeController:
    def __init__(self, present=False):
        self.present = present

    contains_pointer = contains_focus = property(lambda self: lambda: self.present)


class FakeWindow:
    """The cluster's collaborators, with the real methods bound on."""

    def __init__(self, *, pointer=False, focus_in_cluster=False,
                 focus_visible=False, bloomed=True):
        self.xref_toggle = FakeToggle()
        self.fnote_toggle = FakeToggle()
        self.lex_toggle = FakeToggle()
        self._tools_revealers = [FakeRevealer(self.xref_toggle),
                                 FakeRevealer(self.fnote_toggle)]
        self._tools_hover = FakeController(pointer)
        self._tools_focus = FakeController(focus_in_cluster)
        self._tools_fold_timer = 0
        self._tools_bloomed = bloomed
        self._focus_visible = focus_visible
        self._focus = None
        self._apply_tools_reveal()

    def shown(self, toggle):
        """Is this tool's chip on screen?"""
        return next(r.get_reveal_child() for r in self._tools_revealers
                    if r.get_child() is toggle)

    def get_focus(self):
        return self._focus

    def get_focus_visible(self):
        return self._focus_visible

    def _tools_arm_fold(self, *_a):
        pass

    for _name in ('_tools_fold', '_tools_bloom', '_apply_tools_reveal',
                  '_tools_members', '_tools_focus_member', '_on_tools_key'):
        locals()[_name] = getattr(BibleWindow, _name)
    del _name


NO_MODS = Gdk.ModifierType(0)


# ── The reported bug: a click used to pin the cluster open forever ──────────

def test_click_focus_alone_does_not_hold_the_cluster_open():
    """Focus parked by a click is not a reason to stay open — that was the
    bug: the cluster never folded again until focus happened to move."""
    win = FakeWindow(focus_in_cluster=True, focus_visible=False)
    win._focus = win.lex_toggle
    win._tools_fold()
    assert win.shown(win.xref_toggle) is False


def test_keyboard_focus_does_hold_the_cluster_open():
    win = FakeWindow(focus_in_cluster=True, focus_visible=True)
    win._focus = win.lex_toggle
    win._tools_fold()
    assert win.shown(win.xref_toggle) is True


def test_a_click_on_a_bloomed_member_does_not_pin_it_open_either():
    """The same bug from the other side: clicking ※ parks focus *inside* the
    bloom. Holding open for that is what made the cluster wait for a click
    somewhere else before it would fold."""
    win = FakeWindow(focus_in_cluster=True, focus_visible=False)
    win._focus = win.xref_toggle
    win._tools_fold()
    assert win.shown(win.xref_toggle) is False


def test_folding_hands_focus_to_the_anchor_first():
    """Folding unmaps ※ and f*; focus parked on one has to go somewhere, and
    the anchor is the member that stays visible."""
    win = FakeWindow(focus_in_cluster=True, focus_visible=False)
    win._focus = win.fnote_toggle
    win._tools_fold()
    assert win.lex_toggle.focused is True


def test_the_pointer_still_holds_it_open():
    win = FakeWindow(pointer=True)
    win._tools_fold()
    assert win.shown(win.xref_toggle) is True


def test_the_pointer_leaving_is_enough_to_fold_it():
    """The whole rule: nothing else has to happen — no click elsewhere, no
    Escape, no second hover."""
    win = FakeWindow(pointer=False)
    win._tools_fold()
    assert win.shown(win.xref_toggle) is False


# ── Arrow navigation (the bloom opens leftward, so tab order needs help) ────

def test_arrows_walk_the_cluster_in_visual_order():
    win = FakeWindow()
    win._focus = win.lex_toggle
    assert win._on_tools_key(None, Gdk.KEY_Left, 0, NO_MODS) is True
    assert win.fnote_toggle.focused is True


def test_arrows_stop_at_the_ends_rather_than_wrapping():
    win = FakeWindow()
    win._focus = win.xref_toggle                  # already leftmost
    win._on_tools_key(None, Gdk.KEY_Left, 0, NO_MODS)
    assert win.xref_toggle.focused is True
    assert win.fnote_toggle.focused is False


def test_an_insensitive_footnote_toggle_is_not_a_stop():
    """f* goes insensitive when no loaded translation has notes; arrowing
    should skip it rather than land on a dead control."""
    win = FakeWindow()
    win.fnote_toggle.sensitive = False
    win._focus = win.lex_toggle
    win._on_tools_key(None, Gdk.KEY_Left, 0, NO_MODS)
    assert win.xref_toggle.focused is True
    assert win.fnote_toggle.focused is False


def test_tab_leaves_the_cluster_as_a_whole():
    """Tab parks on the edge member and declines the event, so GTK's own
    focus machinery carries it out of the box instead of stepping within."""
    win = FakeWindow()
    win._focus = win.xref_toggle
    assert win._on_tools_key(None, Gdk.KEY_Tab, 0, NO_MODS) is False
    assert win.lex_toggle.focused is True

    win = FakeWindow()
    win._focus = win.lex_toggle
    assert win._on_tools_key(None, Gdk.KEY_ISO_Left_Tab, 0, NO_MODS) is False
    assert win.xref_toggle.focused is True


def test_modified_arrows_are_left_alone():
    win = FakeWindow()
    win._focus = win.lex_toggle
    handled = win._on_tools_key(None, Gdk.KEY_Left, 0,
                                Gdk.ModifierType.CONTROL_MASK)
    assert handled is False


# ── The fold takes away only what is off ────────────────────────────────────

def test_a_tool_that_is_on_stays_on_show_through_the_fold():
    """The reason there is no badge on the anchor: a tool that is on says so
    itself, in its own glyph, and says WHICH one."""
    win = FakeWindow(bloomed=True)
    win.xref_toggle.active = True
    win._apply_tools_reveal()
    win._tools_fold()
    assert win.shown(win.xref_toggle) is True
    assert win.shown(win.fnote_toggle) is False


def test_an_insensitive_tool_folds_away_even_when_active():
    """Active but insensitive puts no markers in the text (no loaded
    translation has notes), so there is nothing for it to account for."""
    win = FakeWindow(bloomed=True)
    win.fnote_toggle.active = True
    win.fnote_toggle.sensitive = False
    win._tools_fold()
    assert win.shown(win.fnote_toggle) is False


def test_switching_a_tool_on_while_folded_brings_its_chip_back():
    win = FakeWindow(bloomed=False)
    assert win.shown(win.fnote_toggle) is False
    win.fnote_toggle.active = True
    win._apply_tools_reveal()
    assert win.shown(win.fnote_toggle) is True


def test_the_bloom_shows_both_whatever_their_state():
    win = FakeWindow(bloomed=False)
    win._tools_bloom()
    assert win.shown(win.xref_toggle) is True
    assert win.shown(win.fnote_toggle) is True


def test_folding_leaves_focus_alone_on_a_tool_that_stays():
    """The focus handoff exists because folding unmaps the focused chip. A
    chip that is on is not unmapped, so nothing needs moving."""
    win = FakeWindow(focus_in_cluster=True, focus_visible=False)
    win.xref_toggle.active = True
    win._focus = win.xref_toggle
    win._tools_fold()
    assert win.lex_toggle.focused is False
    assert win.shown(win.xref_toggle) is True
