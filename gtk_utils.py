"""Small GTK helpers shared across the UI."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

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
