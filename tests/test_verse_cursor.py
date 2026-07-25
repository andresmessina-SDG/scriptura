"""VerseCursor: stepping, tier changes, and what it refuses to swallow.

The cursor drives real pane machinery, so these tests give it a stand-in pane
rather than a display. The parts that need a live buffer — word spans,
activation, the announcements — are asserted against the real app by
tools/verify-a11y.py.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk

from verse_cursor import VerseCursor


class FakeTagTable:
    def __init__(self, verses):
        self._verses = verses

    def foreach(self, fn, data):
        for v in self._verses:
            fn(FakeTag(f'vnum_{v}'), data)


class FakeTag:
    def __init__(self, name):
        self._name = name

    def get_property(self, _p):
        return self._name


class FakeBuffer:
    def __init__(self, verses):
        self._table = FakeTagTable(verses)

    def get_tag_table(self):
        return self._table


class FakeView:
    """Stands in for the reading view — announcements are posted against it."""

    class _Display:
        class __gtype__:
            name = 'GdkWaylandDisplay'

    def __init__(self):
        self.announced = []

    def get_display(self):
        return self._Display()

    def announce(self, message, _priority):
        self.announced.append(message)


class FakePane:
    """Records the calls the cursor makes so the order can be asserted."""

    def __init__(self, verses=(1, 2, 3, 4, 5), navigable=True, selected=None,
                 module_type='Biblical Texts'):
        self._module_type = module_type
        self._view = FakeView()
        self._rendered_headings = {}
        self._show_headings = True
        self._buffer = FakeBuffer(verses)
        self._navigable = navigable
        self._selected_verse = selected
        self._on_verse_select = None
        self.calls = []

    def _is_verse_navigable(self):
        return self._navigable

    def _find_topmost_visible_verse(self):
        return None

    def _set_current_verse_indicator(self, v):
        self.calls.append(('indicator', v))

    def _scroll_to_verse(self, v):
        self.calls.append(('scroll', v))

    def _announce_verse_state(self, v):
        self.calls.append(('announce', v))


def press(cursor, keyval, state=0):
    return cursor.on_key(None, keyval, 0, state)


# ── verse tier ───────────────────────────────────────────────────────────

def test_first_press_places_the_cursor_without_jumping():
    # The reader is on verse 3; the first Down should land there, not on 4.
    pane = FakePane(selected=3)
    c = VerseCursor(pane)
    assert press(c, Gdk.KEY_Down) is True
    assert c.verse == 3


def test_first_press_falls_back_to_the_first_verse():
    c = VerseCursor(FakePane())
    press(c, Gdk.KEY_Down)
    assert c.verse == 1


def test_down_and_up_step_one_verse():
    c = VerseCursor(FakePane(selected=3))
    press(c, Gdk.KEY_Down)      # places on 3
    press(c, Gdk.KEY_Down)
    assert c.verse == 4
    press(c, Gdk.KEY_Up)
    assert c.verse == 3


def test_chapter_edges_release_the_key_for_scrolling():
    pane = FakePane(selected=5)
    c = VerseCursor(pane)
    press(c, Gdk.KEY_Down)      # places on 5, the last verse
    assert press(c, Gdk.KEY_Down) is False
    assert c.verse == 5
    c2 = VerseCursor(FakePane(selected=1))
    press(c2, Gdk.KEY_Up)       # places on 1
    assert press(c2, Gdk.KEY_Up) is False


def test_placing_a_verse_scrolls_through_the_pane_path():
    # Never a raw adjustment write — the scroll invariant depends on this.
    pane = FakePane(selected=2)
    c = VerseCursor(pane)
    press(c, Gdk.KEY_Down)
    assert ('scroll', 2) in pane.calls
    assert ('indicator', 2) in pane.calls
    assert ('announce', 2) in pane.calls


def test_cross_pane_selection_is_broadcast_like_a_click():
    pane = FakePane(selected=2)
    seen = []
    pane._on_verse_select = lambda p, v: seen.append(v)
    c = VerseCursor(pane)
    press(c, Gdk.KEY_Down)
    assert seen == [2]


# ── what the cursor must not swallow ─────────────────────────────────────

def test_modifier_combinations_pass_through():
    # Alt+Down is next-book; Ctrl+F opens find. Both are window actions.
    c = VerseCursor(FakePane())
    assert press(c, Gdk.KEY_Down, Gdk.ModifierType.ALT_MASK) is False
    assert press(c, Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK) is False
    assert press(c, Gdk.KEY_Down, Gdk.ModifierType.CONTROL_MASK) is False


def test_unowned_keys_pass_through():
    c = VerseCursor(FakePane())
    for keyval in (Gdk.KEY_Tab, Gdk.KEY_Page_Down, Gdk.KEY_Home, Gdk.KEY_a):
        assert press(c, keyval) is False


def test_non_bible_panes_have_no_cursor():
    # Commentaries render sections, not numbered verses.
    c = VerseCursor(FakePane(navigable=False))
    assert press(c, Gdk.KEY_Down) is False
    assert c.verse is None


def test_escape_is_left_alone_at_the_verse_tier():
    # Escape closes search / the jump bar; only the word tier claims it.
    c = VerseCursor(FakePane(selected=2))
    press(c, Gdk.KEY_Down)
    assert press(c, Gdk.KEY_Escape) is False


# ── state hygiene ────────────────────────────────────────────────────────

def test_sync_to_follows_a_pointer_selection():
    c = VerseCursor(FakePane())
    c.sync_to(4)
    assert c.verse == 4
    press(c, Gdk.KEY_Down)
    assert c.verse == 5


def test_clear_drops_state_for_a_module_change():
    c = VerseCursor(FakePane(selected=2))
    press(c, Gdk.KEY_Down)
    c.clear()
    assert c.verse is None
    assert c.in_word_tier is False


# ── sense-unit tier ──────────────────────────────────────────────────────

class UnitPane(FakePane):
    """A pane whose chapter carries section headings at known verses."""

    def __init__(self, headings, verses=(1, 2, 3, 4, 5, 6, 7, 8, 9), **kw):
        super().__init__(verses=verses, **kw)
        self._rendered_headings = headings
        self._show_headings = True


def test_next_unit_jumps_to_the_following_heading():
    c = VerseCursor(UnitPane({1: ['A'], 4: ['B'], 7: ['C']}, selected=2))
    assert press(c, Gdk.KEY_bracketright) is True
    assert c.verse == 4


def test_next_unit_at_the_last_unit_releases_the_key():
    c = VerseCursor(UnitPane({1: ['A'], 4: ['B']}, selected=5))
    assert press(c, Gdk.KEY_bracketright) is False


def test_previous_unit_returns_to_the_top_of_the_current_one_first():
    # Mid-unit, [ goes to this unit's own start, as a document reader does.
    c = VerseCursor(UnitPane({1: ['A'], 4: ['B'], 7: ['C']}, selected=6))
    assert press(c, Gdk.KEY_bracketleft) is True
    assert c.verse == 4


def test_previous_unit_from_a_unit_start_leaves_for_the_one_before():
    c = VerseCursor(UnitPane({1: ['A'], 4: ['B'], 7: ['C']}, selected=4))
    press(c, Gdk.KEY_bracketleft)
    assert c.verse == 1


def test_previous_unit_at_the_first_unit_releases_the_key():
    c = VerseCursor(UnitPane({1: ['A'], 4: ['B']}, selected=1))
    assert press(c, Gdk.KEY_bracketleft) is False


def test_unit_keys_are_silent_without_headings():
    # Graceful absence: KJV and friends carry no units to jump between.
    c = VerseCursor(UnitPane({}, selected=3))
    assert press(c, Gdk.KEY_bracketright) is False
    assert press(c, Gdk.KEY_bracketleft) is False


def test_unit_keys_follow_the_headings_toggle():
    pane = UnitPane({1: ['A'], 4: ['B']}, selected=2)
    pane._show_headings = False
    c = VerseCursor(pane)
    assert press(c, Gdk.KEY_bracketright) is False


def test_unit_jump_ignores_headings_on_unrendered_verses():
    # A heading pinned to a verse this chapter never rendered must not
    # become a stop the cursor cannot resolve.
    c = VerseCursor(UnitPane({1: ['A'], 99: ['ghost']}, selected=1))
    assert press(c, Gdk.KEY_bracketright) is False


def test_unit_jump_places_the_cursor_when_none_is_set():
    pane = UnitPane({3: ['A'], 6: ['B']})
    pane._selected_verse = None
    c = VerseCursor(pane)
    assert press(c, Gdk.KEY_bracketright) is True
    assert c.verse == 3


def test_unit_jump_scrolls_through_the_pane_path():
    pane = UnitPane({1: ['A'], 4: ['B']}, selected=1)
    c = VerseCursor(pane)
    press(c, Gdk.KEY_bracketright)
    assert ('scroll', 4) in pane.calls
    assert ('announce', 4) in pane.calls


def test_unit_jump_leaves_the_word_tier():
    pane = UnitPane({1: ['A'], 4: ['B']}, selected=1)
    c = VerseCursor(pane)
    c._word = (0, 3)
    press(c, Gdk.KEY_bracketright)
    assert c.in_word_tier is False


def test_unit_keys_do_not_fire_on_commentary_panes():
    """Commentaries are verse-navigable and their modules carry heading
    attributes, but no headings are drawn there — MHCC's are per-verse
    boilerplate. Jumping between them swallowed the key to move one verse
    with nothing on screen to show for it."""
    pane = UnitPane({1: ['Chapter Outline'], 2: ['Chapter 14'], 3: ['x']},
                    selected=1)
    pane._module_type = 'Commentaries'
    c = VerseCursor(pane)
    assert press(c, Gdk.KEY_bracketright) is False
    assert press(c, Gdk.KEY_bracketleft) is False
    assert c.verse is None


def test_unit_keys_still_fire_on_bible_panes():
    pane = UnitPane({1: ['A'], 4: ['B']}, selected=1)
    assert pane._module_type == 'Biblical Texts'
    c = VerseCursor(pane)
    assert press(c, Gdk.KEY_bracketright) is True
    assert c.verse == 4
