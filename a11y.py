"""Accessibility helpers.

Icon-only controls (a button that shows only a symbolic icon, no text label)
have no accessible name by default, so Orca and other screen readers announce
them as a bare "button". A tooltip is *not* a reliable substitute — AT-SPI does
not expose tooltip text as the accessible name. Each such control needs an
explicit ``Gtk.AccessibleProperty.LABEL``.

``set_accessible_label`` is the single house helper for that. The label should
be the bare action name ("Search", "Bookmark"); any keyboard shortcut or extra
hint stays in the tooltip/description, not the label.
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


def set_accessible_label(widget: Gtk.Widget, label: str) -> None:
    """Give an icon-only control an explicit AT-SPI accessible name."""
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])
