"""Small GTK helpers shared across the UI."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

import motion


class DelayedSpinner:
    """Show a spinner only when an operation outlasts the perception
    threshold (motion.SPINNER_DELAY_MS) — a fast local op finishing under
    it never flashes an indicator it didn't need.

    `start()` arms the threshold timer; `stop()` cancels a pending show
    and hides the spinner. Call `stop()` on completion *and* on teardown
    paths, so a late timer can't spin a surface that has already moved on.
    """

    def __init__(self, spinner: Gtk.Spinner,
                 delay_ms: int = motion.SPINNER_DELAY_MS) -> None:
        self._spinner = spinner
        self._delay_ms = delay_ms
        self._timer = 0

    def start(self) -> None:
        if self._timer:
            return  # already armed; don't push the threshold out
        self._timer = GLib.timeout_add(self._delay_ms, self._show)

    def _show(self) -> bool:
        self._timer = 0
        self._spinner.set_visible(True)
        self._spinner.start()
        return bool(GLib.SOURCE_REMOVE)

    def stop(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._spinner.stop()
        self._spinner.set_visible(False)


def fade_in(widget: Gtk.Widget) -> None:
    """Fade freshly swapped panel content up from transparent so it reads
    as arriving rather than popping (DURATION_MICRO, EASE_FADE) — for the
    satellite panels' result swaps, never the reading text.

    A fade already playing on the widget is left to finish: rapid swaps
    (holding a verse-step key) coalesce into one fade instead of pinning
    the panel at low opacity by restarting from 0 every few frames.
    Adw.TimedAnimation follows gtk-enable-animations, so reduced motion
    collapses this to the instant swap.
    """
    prev = getattr(widget, '_fade_anim', None)
    if prev is not None and prev.get_state() == Adw.AnimationState.PLAYING:
        return
    widget.set_opacity(0.0)
    target = Adw.PropertyAnimationTarget.new(widget, 'opacity')
    anim = Adw.TimedAnimation.new(
        widget, 0.0, 1.0, motion.DURATION_MICRO, target)
    anim.set_easing(motion.EASE_FADE)
    setattr(widget, '_fade_anim', anim)
    anim.play()

    # Stall-safety (mirrors the chrome strip's force_finish): a frame
    # clock that never ticks (broadway headless, GUIDANCE §3) would
    # otherwise pin the content invisible at opacity 0. One timer per
    # animation — coalesced calls return above without adding more.
    def _force_done() -> int:
        if anim.get_state() == Adw.AnimationState.PLAYING:
            anim.skip()
        return int(GLib.SOURCE_REMOVE)

    GLib.timeout_add(motion.DURATION_MICRO + 500, _force_done)


def clear_children(widget: Gtk.Widget) -> None:
    """Remove every child of a Gtk.Box / Gtk.ListBox / Gtk.FlowBox.

    GTK4 dropped GtkContainer's foreach / remove-all sweep, so callers
    otherwise hand-roll this get_first_child / get_next_sibling walk — and
    the next sibling must be cached before the removal or the walk breaks.
    """
    child = widget.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        widget.remove(child)
        child = nxt
