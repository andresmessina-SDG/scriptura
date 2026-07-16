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
- Reduced motion: Adw animations already honor the desktop
  `gtk-enable-animations` setting (verified: `follow-enable-animations-
  setting` defaults on). Paths that don't inherit it (hand-rolled
  timers, CSS-independent choreography) gate on `should_animate()`.

Timed curves only — no springs; restraint over expressiveness.
"""

from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

# Durations (ms).
DURATION_MICRO = 100        # hover-reveal row actions, icon/opacity state
DURATION_SHORT = 150        # stack crossfades, popover page swaps
DURATION_STANDARD = 200     # revealer slide-ins/outs, panels, bars, exits
DURATION_EMPHASIZED = 280   # the deliberately slower enter of a large surface

# Easing intents.
EASE_ENTER = Adw.Easing.EASE_OUT_CUBIC     # arriving: decelerate to rest
EASE_EXIT = Adw.Easing.EASE_IN_CUBIC       # leaving: accelerate away
EASE_MOVE = Adw.Easing.EASE_IN_OUT_CUBIC   # on-screen repositioning
EASE_FADE = Adw.Easing.LINEAR              # color/opacity: never overshoot


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
