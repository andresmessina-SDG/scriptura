"""Reduced motion, and the arrival flash that fades.

GNOME's Reduce motion (`gtk-interface-reduced-motion`, GTK 4.22) asks for
less motion, not none: what travels cuts or crossfades, fades stay. Nothing
in GTK 4.22 or libadwaita 1.9 does this for an app's own Stacks, Revealers,
animations or stylesheet, so motion.py does (MOTION_RESEARCH M1).
"""
import os
import re
import time

import pytest

import motion
import reading_view as rv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: GtkSettings and widgets')


@pytest.fixture
def reduced(display):
    """Set the desktop preference for one test, then put it back."""
    from gi.repository import Gtk
    settings = Gtk.Settings.get_default()
    before = settings.get_property('gtk-interface-reduced-motion')

    def set_(reduce):
        settings.set_property(
            'gtk-interface-reduced-motion',
            Gtk.ReducedMotion.REDUCE if reduce
            else Gtk.ReducedMotion.NO_PREFERENCE)

    yield set_
    settings.set_property('gtk-interface-reduced-motion', before)


def test_should_move_follows_the_desktop_preference(reduced):
    reduced(True)
    assert motion.reduce_motion()
    assert not motion.should_move()
    reduced(False)
    assert not motion.reduce_motion()
    assert motion.should_move() == motion.should_animate()


def test_a_sliding_revealer_cuts_while_reduced_and_slides_again_after(
        reduced):
    from gi.repository import Gtk
    reduced(False)
    rev = Gtk.Revealer()
    rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
    motion.follow_reduced_motion(rev)
    assert rev.get_transition_type() == Gtk.RevealerTransitionType.SLIDE_DOWN
    reduced(True)
    assert rev.get_transition_type() == Gtk.RevealerTransitionType.NONE
    reduced(False)
    assert rev.get_transition_type() == Gtk.RevealerTransitionType.SLIDE_DOWN


def test_a_revealer_built_while_reduced_starts_cut(reduced):
    from gi.repository import Gtk
    reduced(True)
    rev = Gtk.Revealer()
    rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
    motion.follow_reduced_motion(rev)
    assert rev.get_transition_type() == Gtk.RevealerTransitionType.NONE
    reduced(False)
    assert rev.get_transition_type() == Gtk.RevealerTransitionType.SLIDE_UP


def test_a_stack_crossfades_only_when_its_pages_share_a_size(reduced):
    """GTK's own rule from 4.23.2: a crossfade between pages of different
    sizes jumps anyway, so a non-homogeneous stack cuts."""
    from gi.repository import Gtk
    reduced(False)
    even = Gtk.Stack()
    even.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    motion.follow_reduced_motion(even)
    uneven = Gtk.Stack(vhomogeneous=False)
    uneven.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    motion.follow_reduced_motion(uneven)
    fade = Gtk.Stack()
    fade.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    motion.follow_reduced_motion(fade)
    reduced(True)
    assert even.get_transition_type() == Gtk.StackTransitionType.CROSSFADE
    assert uneven.get_transition_type() == Gtk.StackTransitionType.NONE
    assert fade.get_transition_type() == Gtk.StackTransitionType.CROSSFADE
    reduced(False)
    assert (even.get_transition_type()
            == Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)


def test_the_stylesheet_media_query_follows_the_desktop(reduced):
    """GTK 4.22 answers `prefers-reduced-motion` from the provider's own
    property; styles.py binds it, or the @media block never applies."""
    from gi.repository import Gtk
    import styles
    provider = Gtk.CssProvider()
    styles._follow_reduced_motion(provider)
    reduced(True)
    assert (provider.get_property('prefers-reduced-motion')
            == Gtk.ReducedMotion.REDUCE)
    reduced(False)
    assert (provider.get_property('prefers-reduced-motion')
            == Gtk.ReducedMotion.NO_PREFERENCE)


def test_every_sliding_transition_follows_reduced_motion():
    """A new slide that skips follow_reduced_motion keeps sliding for a
    reader who asked it not to. Counted per file, from the source."""
    slide = re.compile(r'(Revealer|Stack)TransitionType\.SLIDE')
    missing = []
    for name in sorted(os.listdir(ROOT)):
        if not name.endswith('.py'):
            continue
        with open(os.path.join(ROOT, name), encoding='utf-8') as f:
            src = f.read()
        slides = len(slide.findall(src))
        if name == 'motion.py':
            continue
        follows = src.count('motion.follow_reduced_motion(')
        if slides > follows:
            missing.append(f'{name}: {slides} slides, {follows} followed')
    assert not missing, '\n'.join(missing)


# ── The arrival flash ────────────────────────────────────────────────────────

class _View:
    _FLASH_RGB = rv.BibleTextView._FLASH_RGB
    _FLASH_ALPHA = rv.BibleTextView._FLASH_ALPHA
    _flash_fade = 1.0


def test_the_flash_band_thins_as_it_fades():
    view = _View()
    assert rv._flash_colour(view) == 'rgba(232,120,32,0.440)'
    view._flash_fade = 0.5
    assert rv._flash_colour(view) == 'rgba(232,120,32,0.220)'
    view._flash_fade = 0.0
    assert rv._flash_colour(view) == 'rgba(232,120,32,0.000)'


def _flash_pane():
    """The flash's half of a BiblePane: a real buffer and BibleTextView,
    and the pane's own flash methods."""
    from gi.repository import Gtk
    import pane as pane_mod

    class Pane:
        _flash_verse = pane_mod.BiblePane._flash_verse
        _cancel_all_flashes = pane_mod.BiblePane._cancel_all_flashes

        def __init__(self):
            self._buffer = Gtk.TextBuffer()
            self._view = rv.BibleTextView(buffer=self._buffer)
            self._flash_timers = set()
            self._flash_anim = None
            self.announced = []

        def _announce_verse_state(self, verse):
            self.announced.append(verse)

    p = Pane()
    buf = p._buffer
    for v in (1, 2, 3):
        tag = buf.create_tag(f'vnum_{v}')
        buf.insert_with_tags(buf.get_end_iter(), f'Verse {v} text. ', tag)
    return p


def _flashed(p):
    tag = p._buffer.get_tag_table().lookup('_flash')
    if tag is None:
        return ''
    it = p._buffer.get_start_iter()
    out = ''
    while not it.is_end():
        if it.has_tag(tag):
            out += it.get_char()
        it.forward_char()
    return out


def _spin(ms):
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


def test_one_flash_at_a_time_and_it_leaves_after_the_hold(display):
    p = _flash_pane()
    p._flash_verse(1)
    assert _flashed(p) == 'Verse 1 text. '
    p._flash_verse(3)
    assert _flashed(p) == 'Verse 3 text. ', 'the earlier band stayed on'
    assert p.announced == [1, 3]
    _spin(motion.FLASH_HOLD_MS // 2)
    assert _flashed(p) == 'Verse 3 text. ', 'the hold was cut short'
    # Past the hold the fade runs; an unmapped view has no frame clock, so
    # the fade finishes at once (or by the stall-safety) and the tag goes.
    _spin(motion.FLASH_HOLD_MS + motion.DURATION_EMPHASIZED + 600)
    assert _flashed(p) == ''
    assert p._view._flash_fade == 1.0
    assert not p._flash_timers and p._flash_anim is None


def test_a_reset_mid_flash_takes_it_off_at_once(display):
    p = _flash_pane()
    p._flash_verse(2)
    p._cancel_all_flashes()
    assert _flashed(p) == ''
    assert not p._flash_timers


# ── Verse jumps: near glides, far lands (MOTION_RESEARCH M3) ─────────────────

class _Loc:
    def __init__(self, y, height):
        self.y, self.height = y, height


def _keeper(target_y):
    """A ScrollKeeper over a real buffer and adjustment; the view stands
    in for geometry GTK would have validated by the glide's first frame."""
    from gi.repository import Gtk
    import pane_scroll

    class View:
        blank = False

        def get_iter_location(self, _it):
            return _Loc(target_y, 20)

        def set_blank(self, blank):
            self.blank = blank

        def get_height(self):
            return 500

        def get_top_margin(self):
            return 18

    class Scroll:
        mapped = True

        def __init__(self):
            self.adj = Gtk.Adjustment(lower=0, upper=20000, page_size=500)

        def get_vadjustment(self):
            return self.adj

        def get_mapped(self):
            return self.mapped

    class Pane:
        view = View()
        _buffer = Gtk.TextBuffer()
        _reading_scroll = Scroll()

    Pane._buffer.set_text('Verse text.')
    keeper = pane_scroll.ScrollKeeper(Pane())
    mark = Pane._buffer.create_mark(None, Pane._buffer.get_start_iter(), True)
    return keeper, Pane._reading_scroll.adj, mark


def _gtk_target(y):
    # GTK's aligned landing for within_margin 0.1, yalign 0.2, a 500px view.
    margin = int(500 * 0.1)
    return y + int(20 * 0.2 - (500 - 2 * margin) * 0.2) - margin + 18


def test_a_far_jump_lands_in_one_frame(reduced):
    reduced(False)
    keeper, adj, mark = _keeper(6000)
    keeper.land_jump(mark, 0.1, 0.2)
    adj.set_value(300)            # GTK's glide takes its first step
    assert adj.get_value() == _gtk_target(6000)


def test_a_window_opening_part_way_down_shows_no_text_until_it_lands(
        reduced):
    # A saved place or a bible: link: the chapter's top was painted first,
    # verse 1 for ~260ms before the leap to the reader's verse.
    reduced(False)
    keeper, adj, mark = _keeper(400)
    keeper.veil_until_landed()
    assert keeper._view.blank
    keeper.land_jump(mark, 0.1, 0.2)
    assert keeper._view.blank, 'lifted before the jump landed'
    adj.set_value(120)
    # Near as it is, an opening lands rather than gliding in from the top,
    # and the text comes back in the frame it lands in.
    assert adj.get_value() == _gtk_target(400)
    assert not keeper._view.blank


def test_an_opening_already_in_place_shows_its_text_at_once(reduced):
    # No move will come when the target is where the view stands (clamped to
    # the top), so the landing cannot be what lifts the paper.
    reduced(False)
    keeper, adj, mark = _keeper(10)
    keeper.veil_until_landed()
    keeper.land_jump(mark, 0.1, 0.2)
    assert adj.get_value() == 0
    assert not keeper._view.blank
    assert keeper._landing is None


def test_a_jump_that_never_starts_does_not_leave_the_paper_up(reduced):
    reduced(False)
    keeper, _adj, _mark = _keeper(400)
    keeper.veil_until_landed()
    keeper.unveil_unless_landing()      # no such verse: nothing to land
    assert not keeper._view.blank


def test_a_near_jump_keeps_the_glide(reduced):
    reduced(False)
    keeper, adj, mark = _keeper(400)
    keeper.land_jump(mark, 0.1, 0.2)
    adj.set_value(120)
    assert adj.get_value() == 120, 'the glide was cut short'


def test_under_reduced_motion_even_a_near_jump_lands(reduced):
    reduced(True)
    keeper, adj, mark = _keeper(400)
    keeper.land_jump(mark, 0.1, 0.2)
    adj.set_value(120)
    assert adj.get_value() == _gtk_target(400)


def test_a_landing_leaves_the_scroll_alone_once_the_reader_takes_it(
        reduced):
    reduced(True)
    keeper, adj, mark = _keeper(6000)
    keeper.land_jump(mark, 0.1, 0.2)
    keeper._last_scroll_input += 1   # a wheel tick
    adj.set_value(300)
    assert adj.get_value() == 300


def test_a_second_jump_replaces_the_first(reduced):
    reduced(True)
    keeper, adj, mark = _keeper(6000)
    keeper.land_jump(mark, 0.1, 0.2)
    keeper.land_jump(mark, 0.1, 0.2)
    adj.set_value(300)
    assert adj.get_value() == _gtk_target(6000)
    assert keeper._landing is None


def test_a_pane_hidden_mid_glide_is_left_to_gtk(reduced):
    """Hiding the pane makes GTK finish the glide from inside
    gtk_adjustment_enable_animation; a set_value there ended the frame
    clock's update twice (Gdk-CRITICAL in CI's nav_storm)."""
    reduced(True)
    keeper, adj, mark = _keeper(6000)
    keeper._reading_scroll.mapped = False
    keeper.land_jump(mark, 0.1, 0.2)
    adj.set_value(6100)            # GTK jumping to its own target
    assert adj.get_value() == 6100
    assert keeper._landing is None
