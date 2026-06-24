"""Small GTK helpers shared across the UI."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


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
