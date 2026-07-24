"""Accessibility helpers — names, roles, relations, and live-region status.

Icon-only controls (a button that shows only a symbolic icon, no text label)
have no accessible name by default, so Orca and other screen readers announce
them as a bare "button". A tooltip is *not* a reliable substitute — AT-SPI does
not expose tooltip text as the accessible name. Each such control needs an
explicit ``Gtk.AccessibleProperty.LABEL``.

``set_accessible_label`` is the single house helper for that. The label should
be the bare action name ("Search", "Bookmark"); any keyboard shortcut or extra
hint stays in the tooltip/description, not the label.

Beyond names, this module carries the three other things AT needs and GTK will
not infer:

* **Roles** (``set_role``) — a composite built out of boxes reports as
  ``generic``, which tells a screen-reader user nothing. Naming the role makes
  the find bar a toolbar, the chip row a radio group, the reading column a
  document.
* **Relations** (``labelled_by`` / ``described_by`` / ``controls``) — the tie
  between a control and the region it governs, or a label and the field it
  names.
* **Live-region status** (``announce`` / ``status`` / ``ProgressAnnouncer``) —
  WCAG 2.2 §4.1.3 requires status messages to reach AT *without* moving focus.
  Text that only appears in a label is silent; it has to be announced.

PyGObject trap, paid for once: reference relations (LABELLED_BY, DESCRIBED_BY,
CONTROLS — the ones whose value is a list of widgets) cannot take a plain
Python list. ``update_relation`` marshals the value through a pointer GValue
and a bare list fails with ``g_value_get_pointer`` assertions, silently leaving
the relation unset. The value must be a ``Gtk.AccessibleList``, and only
``new_from_list`` works — ``new_from_array`` returns NULL from Python because
the array length is not marshalled. ``_ref_relation`` is the one place that
knows this; go through it.

GTK trap, also paid for once: on GTK 4.22 ``gtk_accessible_announce()``
**segfaults under the Broadway backend** — reproducibly, and differently per
widget type (a GtkWindow or GtkButton dies, a GtkLabel does not). Broadway is
what the headless harnesses in tools/ drive the app with, so an unguarded
announcement takes them and CI down while never affecting a real user, who runs
Wayland or X11. ``announce`` therefore no-ops on Broadway. Everywhere else it
is safe — verified against a real headless compositor by tools/verify-a11y.py.
"""
import time

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# Announcement priority. MEDIUM is the "polite" live region — queued behind
# whatever the user is reading, which is what status text should be. HIGH
# interrupts and is reserved for errors the user must not miss.
_POLITE = Gtk.AccessibleAnnouncementPriority.MEDIUM
_URGENT = Gtk.AccessibleAnnouncementPriority.HIGH


def set_accessible_label(widget: Gtk.Widget, label: str) -> None:
    """Give an icon-only control an explicit AT-SPI accessible name."""
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])


def set_accessible_description(widget: Gtk.Widget, description: str) -> None:
    """Attach the longer "what this is / what state it's in" string.

    The description is what Orca reads after the name — the place for verse
    annotation state or a hint that would bloat the name."""
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [description])


def set_role(widget: Gtk.Widget, role: Gtk.AccessibleRole) -> None:
    """Name a composite's role so it stops reporting as ``generic``.

    Settable after construction (verified on GTK 4.22): the role reaches the
    AT context as long as it is set while the UI is being built, before the
    widget is presented."""
    widget.set_property('accessible-role', role)


def _ref_relation(widget: Gtk.Widget, relation: Gtk.AccessibleRelation,
                  targets: tuple) -> None:
    """Set a widget-list relation. See the module docstring for why the value
    has to be a Gtk.AccessibleList built with new_from_list."""
    if not targets:
        return
    widget.update_relation(
        [relation], [Gtk.AccessibleList.new_from_list(list(targets))])


def labelled_by(widget: Gtk.Widget, *targets: Gtk.Widget) -> None:
    """`widget` is named by these labels (the field ← its caption)."""
    _ref_relation(widget, Gtk.AccessibleRelation.LABELLED_BY, targets)


def described_by(widget: Gtk.Widget, *targets: Gtk.Widget) -> None:
    """`widget` is further described by these (a hint or status line)."""
    _ref_relation(widget, Gtk.AccessibleRelation.DESCRIBED_BY, targets)


def controls(widget: Gtk.Widget, *targets: Gtk.Widget) -> None:
    """`widget` governs these regions (a filter chip → the list it filters)."""
    _ref_relation(widget, Gtk.AccessibleRelation.CONTROLS, targets)


def _announcements_crash_here(widget: Gtk.Widget) -> bool:
    """Whether this display is the Broadway backend, where announcing is a
    segfault rather than a message (see the module docstring)."""
    display = widget.get_display()
    return (display is not None
            and display.__gtype__.name == 'GdkBroadwayDisplay')


def announce(widget: Gtk.Widget, message: str, urgent: bool = False) -> None:
    """Speak `message` to AT without moving focus (WCAG 2.2 §4.1.3).

    `widget` only supplies the accessible root the announcement is posted
    against — it is not read out, and need not be the thing the message is
    about. An empty message is a no-op so callers can pass a cleared status
    string straight through."""
    if not message or _announcements_crash_here(widget):
        return
    widget.announce(message, _URGENT if urgent else _POLITE)


def status(label: Gtk.Label, text: str, urgent: bool = False) -> None:
    """Set a status label's text *and* announce it.

    The house pattern for every "Searching… / 12 verses found / No matches"
    line: sighted users read the label, AT users hear it, and the two can
    never drift because it is one call."""
    label.set_text(text)
    announce(label, text, urgent=urgent)


class ProgressAnnouncer:
    """Rate-limited live-region reporter for repeating progress text.

    Building a search index walks all 66 books and restates its status for
    each one. Announcing every step would bury a screen-reader user under
    sixty-six interruptions, so this lets the first message through
    immediately and then at most one per `interval` seconds. `done` always
    passes, so the end of a run is never the message that got throttled.

    Owned by the surface that reports the progress (one per search bar), so
    there is no global state to leak between windows."""

    def __init__(self, interval: float = 5.0) -> None:
        self._interval = interval
        self._last_at = 0.0
        self._last_text = ''

    def reset(self) -> None:
        """Forget the throttle so the next message is announced at once."""
        self._last_at = 0.0
        self._last_text = ''

    def progress(self, widget: Gtk.Widget, message: str) -> None:
        """Announce `message` unless one went out too recently."""
        now = time.monotonic()
        if message == self._last_text or now - self._last_at < self._interval:
            return
        self._last_at = now
        self._last_text = message
        announce(widget, message)

    def done(self, widget: Gtk.Widget, message: str) -> None:
        """Announce a terminal message, throttle notwithstanding."""
        self.reset()
        announce(widget, message)
