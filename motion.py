"""Motion tokens — the temporal companion to the spatial design language.

The stylesheet's spatial grammar (4px grid, radii 4/6/10/20/999) has a
time-domain counterpart: four duration tiers and four easing intents,
applied consistently instead of re-typed literals. Durations follow the
app's measured clusters snapped to the Apple/Material/libadwaita
consensus; easing expresses enter-vs-exit intent (decelerate arriving,
accelerate leaving, symmetric for on-screen moves, no curve on fades).

Two rules the tokens encode:
- Asymmetry: an exit is never longer than its enter; enters take
  EASE_ENTER, exits EASE_EXIT.
- Two desktop switches, two strengths. `gtk-enable-animations` off
  means no animation at all; Adw animations follow it themselves
  (`follow-enable-animations-setting` defaults on), hand-rolled
  timers gate on `should_animate()`. `gtk-interface-reduced-motion`
  (GNOME Settings > Accessibility > Reduce motion, GTK 4.22) asks for
  less motion, not none: nothing Scriptura moves across the screen
  should slide, rise or pulse, while fades and colour changes stay
  (WCAG 2.3.3 does not count them as motion). No Adw animation follows
  it, and GTK 4.22's own Stack and Revealer do not either, so every
  spatial move gates on `should_move()` and every sliding Stack or
  Revealer goes through `follow_reduced_motion()`.

Timed curves only — no springs; restraint over expressiveness.
"""

from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import weakref

from gi.repository import Adw, Gtk

# Durations (ms).
DURATION_MICRO = 100        # hover-reveal row actions, icon/opacity state
DURATION_SHORT = 150        # stack crossfades, popover page swaps
DURATION_STANDARD = 200     # revealer slide-ins/outs, panels, bars, exits
DURATION_EMPHASIZED = 280   # the deliberately slower enter of a large surface

# The Family Tree's chart morphs sit outside the four tiers on purpose:
# dozens of nodes and lines travel at once, and the eye needs longer to
# follow each one to its new place than to watch a panel arrive. Both
# were tuned by eye on the chart; nothing else uses them.
DURATION_CHART_FOLD = 520   # the root folding open or shut, whole travel
DURATION_CHART_MORPH = 700  # the chart re-arranging (family / literalness)

# Easing intents.
EASE_ENTER = Adw.Easing.EASE_OUT_CUBIC     # arriving: decelerate to rest
EASE_EXIT = Adw.Easing.EASE_IN_CUBIC       # leaving: accelerate away
EASE_MOVE = Adw.Easing.EASE_IN_OUT_CUBIC   # on-screen repositioning
EASE_FADE = Adw.Easing.LINEAR              # color/opacity: never overshoot

# Feedback time (the companion to the transition times above): show a
# busy indicator only once an operation outlasts this — under ~500ms a
# flashed spinner distracts more than it informs (Nielsen). Used by
# gtk_utils.DelayedSpinner.
SPINNER_DELAY_MS = 500

# The arrival flash, the "you are here" after a jump: on at once, since it
# is feedback; held long enough to be found; then faded out over
# DURATION_EMPHASIZED, linear, because a cue that has done its job should
# leave gently. One set of numbers for the Bible pane and the gallery.
FLASH_HOLD_MS = 700

# A verse jump glides only when it is near. GTK already animates every
# scroll_to_mark (200ms ease-out, however far); past this many screens that
# is a blur that shows nothing, so the jump lands in one frame instead.
GLIDE_MAX_PAGES = 1.5

# Intent times. A rich hover preview fires only after the cursor has
# *stopped* on the word — 650ms is the Wikipedia-hovercard dwell,
# conservative enough that crossing a line of text never twitches the
# reading surface. Dismissal tolerates the diagonal move onto the card
# with a short grace.
HOVER_DWELL_MS = 650
HOVER_GRACE_MS = 300

# Find-as-you-type debounce (Gtk.SearchEntry.set_search_delay): 200ms is
# the local-search sweet spot — under the ~300ms natural typing pause,
# above per-keystroke churn.
SEARCH_DEBOUNCE_MS = 200

# Write-behind debounce for a field the reader is typing in. Far longer
# than the search one, because the cost is different at both ends: a
# store write is a whole-file fsync + rename, and nothing on screen waits
# for it. 900ms sits above a sentence-level pause, so ordinary writing
# saves between thoughts rather than between words. Used by
# gtk_utils.Autosave.
AUTOSAVE_DELAY_MS = 900

# How long "Saved" stays under the sheet after a write before it fades.
# Long enough to be read at a glance up from the page, short enough that a
# writer who pauses every sentence does not watch it blink on and off.
SAVED_HOLD_MS = 1800

# Restyle debounce for work too heavy to do per keystroke. Scanning a body
# for scripture references means matching ~134 book spellings at every
# position: 0.8ms on a page, but 10ms on a sermon-length entry — over half a
# frame, paid on every letter. Emphasis and headings stay instant (0.12ms at
# the same length); the references settle a beat later, which is what they
# are, not feedback you need per keystroke.
RESTYLE_DELAY_MS = 300


def should_animate() -> bool:
    """Whether the desktop wants animations (`gtk-enable-animations`).

    Adw.Animation subclasses check this themselves; use this for motion
    that doesn't ride one, so hand-rolled choreography collapses to its
    end state under reduced motion.
    """
    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is None:
        return True
    return bool(gtk_settings.get_property('gtk-enable-animations'))


def reduce_motion() -> bool:
    """Whether the desktop asks for less motion
    (`gtk-interface-reduced-motion`, GTK 4.22). False on an older GTK."""
    gtk_settings = Gtk.Settings.get_default()
    if (gtk_settings is None or gtk_settings.find_property(
            'gtk-interface-reduced-motion') is None):
        return False
    return bool(gtk_settings.get_property('gtk-interface-reduced-motion')
                == Gtk.ReducedMotion.REDUCE)


def should_move() -> bool:
    """Whether something may travel across the screen: slide, rise,
    scroll itself, pulse. Under reduced motion it cuts to its end state
    instead; a fade that goes with it may stay."""
    return should_animate() and not reduce_motion()


# Sliding Stacks and Revealers, each with the transition it was built
# with, so reduced motion can be turned off again at runtime.
_followers: weakref.WeakKeyDictionary[Gtk.Widget, int] = (
    weakref.WeakKeyDictionary())
_watching = False

_SLIDES = frozenset((
    Gtk.RevealerTransitionType.SLIDE_UP,
    Gtk.RevealerTransitionType.SLIDE_DOWN,
    Gtk.RevealerTransitionType.SLIDE_LEFT,
    Gtk.RevealerTransitionType.SLIDE_RIGHT,
))


def follow_reduced_motion(widget: Gtk.Revealer | Gtk.Stack) -> None:
    """Give a Stack or Revealer the reduced form of its transition while
    the desktop asks for less motion. Call after set_transition_type.

    This copies what GTK itself does from 4.23.2 (the GNOME 51 runtime):
    a Revealer cuts; a Stack crossfades when it is homogeneous both ways
    and cuts when it is not, since a crossfade between pages of different
    sizes jumps anyway. On runtime 50 (GTK 4.22) nothing does it for us;
    after a move to 51 this is harmless and may go.
    """
    global _watching
    _followers[widget] = widget.get_transition_type()
    if not _watching:
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None and gtk_settings.find_property(
                'gtk-interface-reduced-motion') is not None:
            gtk_settings.connect('notify::gtk-interface-reduced-motion',
                                 _apply_all)
            _watching = True
    _apply(widget)


def _apply_all(*_args: object) -> None:
    for widget in list(_followers):
        _apply(widget)


def _apply(widget: Gtk.Widget) -> None:
    base = _followers.get(widget)
    if base is None:
        return
    if isinstance(widget, Gtk.Revealer):
        reduced = (Gtk.RevealerTransitionType.NONE
                   if base in _SLIDES else base)
    else:
        assert isinstance(widget, Gtk.Stack)
        if base in (Gtk.StackTransitionType.NONE,
                    Gtk.StackTransitionType.CROSSFADE):
            reduced = base
        elif widget.get_hhomogeneous() and widget.get_vhomogeneous():
            reduced = Gtk.StackTransitionType.CROSSFADE
        else:
            reduced = Gtk.StackTransitionType.NONE
    widget.set_transition_type(reduced if reduce_motion() else base)
