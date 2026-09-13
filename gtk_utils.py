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


class DelayedPulse:
    """DelayedSpinner's rule for a busy indicator the app draws itself.

    The spoken-reading controls report their fetch on the progress line they
    already own — a pulsing band under the toolbar, a sweep around the Today
    disc — so there is no Gtk.Spinner to show and hide. The timing is the
    same: `show` runs once when an operation outlasts the perception
    threshold, `tick` follows it immediately and then every `interval_ms`,
    and `stop()` calls `hide`. An operation that finishes under the threshold
    leaves the surface untouched.

    The pulse is not suppressed under reduced motion. A busy indicator has no
    end state to collapse to, and Gtk.Spinner does the same.
    """

    def __init__(self, show, tick, hide,
                 delay_ms: int = motion.SPINNER_DELAY_MS,
                 interval_ms: int = 80) -> None:
        self._show = show
        self._tick = tick
        self._hide = hide
        self._delay_ms = delay_ms
        self._interval_ms = interval_ms
        self._timer = 0

    def start(self) -> None:
        if self._timer:
            return  # already armed; don't push the threshold out
        self._timer = GLib.timeout_add(self._delay_ms, self._begin)

    def _begin(self) -> bool:
        self._show()
        self._tick()
        self._timer = GLib.timeout_add(self._interval_ms, self._pulse)
        return bool(GLib.SOURCE_REMOVE)

    def _pulse(self) -> bool:
        self._tick()
        return bool(GLib.SOURCE_CONTINUE)

    def stop(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._hide()


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


class Autosave:
    """Debounced write-behind for a field the reader is typing in.

    The reader never presses Save. Every edit calls `schedule()`, which
    restarts a single timer; the write happens once typing pauses. Leaving
    the field, closing the editor and closing the window all `flush()`,
    so the last few keystrokes are never the ones that go missing.

    Debouncing is not a nicety here. A store write is a whole-file
    json.dump + fsync + os.replace, and saving per keystroke would pay
    that for every letter. `motion.AUTOSAVE_DELAY_MS` is the pause it
    waits for.

    `flush()` writes only when a write is actually pending, so the focus
    handlers can call it freely — a reader tabbing through a form they
    did not edit rewrites nothing. `cancel()` drops a pending write
    without performing it, which is what deleting the thing being edited
    wants.
    """

    def __init__(self, save, delay_ms: int = motion.AUTOSAVE_DELAY_MS):
        self._save = save
        self._delay = delay_ms
        self._source: int | None = None

    @property
    def pending(self) -> bool:
        return self._source is not None

    def schedule(self) -> None:
        """Note an edit: (re)start the timer."""
        self.cancel()
        self._source = GLib.timeout_add(self._delay, self._fire)

    def _fire(self) -> int:
        self._source = None
        self._save()
        return int(GLib.SOURCE_REMOVE)

    def flush(self) -> None:
        """Write now if a write is pending; otherwise do nothing."""
        if self._source is None:
            return
        self.cancel()
        self._save()

    def cancel(self) -> None:
        """Drop a pending write without performing it."""
        if self._source is not None:
            GLib.source_remove(self._source)
            self._source = None
