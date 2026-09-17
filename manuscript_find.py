"""Find and replace inside a journal entry or a sermon manuscript.

Ctrl+F in the writing pane used to do nothing at all: the Bible search is the
main window's, and the Annotations window bound no such key. A preacher
reworking an 8,000-word manuscript had no way to find the word they meant to
change but to scroll for it.

The bar sits at the head of the sheet under the formatting row, the place
GNOME Text Editor and every word processor keep it. It matches without regard
to case — the reader looking for "grace" wants "Grace" at the head of a
sentence too — and literally, never as a pattern: nobody writing a sermon
types a regular expression on purpose.

`find_all` is the whole matching rule and needs no display.
"""
from __future__ import annotations

import re

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk

from a11y import set_accessible_label
from i18n import _, ngettext

#: The reading view's own search ambers (reading_view._SEARCH_COLOR and
#: _SEARCH_CUR_COLOR), so a match looks like a match wherever the reader meets
#: one. The current match needs its own: the selection that also marks it is
#: drawn faintly while the keyboard is in the find field, which is exactly
#: when the reader is looking for it.
_MATCH_COLOUR = 'rgba(214,150,40,0.40)'
_CURRENT_COLOUR = 'rgba(224,150,36,0.85)'


def find_all(text: str, query: str) -> list[tuple[int, int]]:
    """Every place `query` occurs in `text`, as (start, end) character
    offsets, without regard to case and never overlapping.

    Offsets are Python string indices, which count code points exactly as a
    GtkTextBuffer counts characters — so they go straight to
    `get_iter_at_offset`. `str.casefold()` would be the better fold but can
    change a string's length (ß → ss), and then no offset would line up.
    """
    if not query:
        return []
    return [(m.start(), m.end())
            for m in re.finditer(re.escape(query), text, re.IGNORECASE)]


def next_index(matches: list[tuple[int, int]], offset: int,
               backwards: bool = False) -> int | None:
    """Which match to go to from `offset`, wrapping at either end."""
    if not matches:
        return None
    if backwards:
        for i in range(len(matches) - 1, -1, -1):
            if matches[i][0] < offset:
                return i
        return len(matches) - 1
    for i, (start, _end) in enumerate(matches):
        if start >= offset:
            return i
    return 0


def _rgba(spec: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(spec)
    return rgba


class FindBar(Gtk.Revealer):
    """The find row, and the replace row under it when asked for."""

    def __init__(self, view: Gtk.TextView):
        super().__init__()
        self._view = view
        self._buf = view.get_buffer()
        self._matches: list[tuple[int, int]] = []
        self._current: int | None = None
        self._refresh_source = 0
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)

        self._tag = self._buf.create_tag(
            'find-match', background_rgba=_rgba(_MATCH_COLOUR))
        self._current_tag = self._buf.create_tag(
            'find-current', background_rgba=_rgba(_CURRENT_COLOUR))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class('journal-find')

        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._replace_toggle = Gtk.ToggleButton(
            icon_name='scriptura-pan-end-symbolic')
        self._replace_toggle.add_css_class('flat')
        self._replace_toggle.set_tooltip_text(_('Replace (Ctrl+H)'))
        set_accessible_label(self._replace_toggle, _('Replace'))
        self._replace_toggle.connect('toggled', self._on_replace_toggled)
        find_row.append(self._replace_toggle)

        self.entry = Gtk.SearchEntry(hexpand=True)
        self.entry.set_placeholder_text(_('Find in this page'))
        self.entry.connect('search-changed', lambda _e: self._search(True))
        self.entry.connect('activate', lambda _e: self.step(False))
        self.entry.connect('next-match', lambda _e: self.step(False))
        self.entry.connect('previous-match', lambda _e: self.step(True))
        self.entry.connect('stop-search', lambda _e: self.close())
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_entry_key)
        self.entry.add_controller(keys)
        find_row.append(self.entry)

        self._count = Gtk.Label()
        self._count.add_css_class('dim-label')
        self._count.add_css_class('caption')
        self._count.add_css_class('numeric')
        self._count.set_margin_start(6)
        self._count.set_margin_end(4)
        find_row.append(self._count)

        for icon, tip, name, backwards in (
                ('scriptura-go-up-symbolic', _('Previous match (Shift+Enter)'),
                 _('Previous match'), True),
                ('scriptura-go-down-symbolic', _('Next match (Enter)'),
                 _('Next match'), False)):
            btn = Gtk.Button(icon_name=icon)
            btn.add_css_class('flat')
            btn.set_tooltip_text(tip)
            set_accessible_label(btn, name)
            btn.connect('clicked', lambda _b, back=backwards: self.step(back))
            find_row.append(btn)

        close = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        close.add_css_class('flat')
        close.set_tooltip_text(_('Close (Esc)'))
        set_accessible_label(close, _('Close'))
        close.connect('clicked', lambda _b: self.close())
        find_row.append(close)
        box.append(find_row)

        self._replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=4)
        # Lined up under the find field, past the chevron.
        self._replace_row.set_margin_start(34)
        self.replace_entry = Gtk.Entry(hexpand=True)
        self.replace_entry.set_placeholder_text(_('Replace with'))
        self.replace_entry.connect('activate', lambda _e: self.replace())
        self._replace_row.append(self.replace_entry)
        self._replace_btn = Gtk.Button(label=_('Replace'))
        self._replace_btn.connect('clicked', lambda _b: self.replace())
        self._replace_row.append(self._replace_btn)
        self._replace_all_btn = Gtk.Button(label=_('Replace All'))
        self._replace_all_btn.connect('clicked', lambda _b: self.replace_all())
        self._replace_row.append(self._replace_all_btn)
        self._replace_row.set_visible(False)
        box.append(self._replace_row)

        self.set_child(box)
        self._buf.connect('changed', self._on_buffer_changed)
        self._show_count()

    # ── Opening and closing ─────────────────────────────────────────────

    def open(self, replace: bool = False):
        """Show the bar with the find field focused. A selection on one line
        becomes the search, the way every editor treats it."""
        bounds = self._buf.get_selection_bounds()
        if bounds:
            picked = self._buf.get_text(bounds[0], bounds[1], False)
            if picked and '\n' not in picked:
                self.entry.set_text(picked)
        if replace:
            self._replace_toggle.set_active(True)
        self.set_reveal_child(True)
        self.entry.grab_focus()
        self.entry.select_region(0, -1)
        self._search(True)

    def close(self):
        """Hide the bar and hand the keyboard back to the page, on the match
        that was current."""
        if not self.get_reveal_child():
            return False
        self.set_reveal_child(False)
        self._clear_tags()
        self._view.grab_focus()
        return True

    def _on_replace_toggled(self, toggle):
        on = toggle.get_active()
        self._replace_row.set_visible(on)
        toggle.set_icon_name('scriptura-pan-down-symbolic' if on
                             else 'scriptura-pan-end-symbolic')
        if on and self.get_reveal_child():
            self.replace_entry.grab_focus()

    def _on_entry_key(self, _ctl, keyval, _code, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) \
                and state & Gdk.ModifierType.SHIFT_MASK:
            self.step(True)
            return True
        return False

    # ── Finding ─────────────────────────────────────────────────────────

    def _text(self) -> str:
        return str(self._buf.get_text(*self._buf.get_bounds(), True))

    def _insert_offset(self) -> int:
        return int(self._buf.get_iter_at_mark(
            self._buf.get_insert()).get_offset())

    def _search(self, from_cursor: bool):
        """Find every match, mark them, and choose the current one: the first
        at or after the cursor, so typing a word finds the next use of it
        from where the reader is, not from the top."""
        self._matches = find_all(self._text(), self.entry.get_text())
        self._clear_tags()
        for start, end in self._matches:
            self._buf.apply_tag(self._tag, self._buf.get_iter_at_offset(start),
                                self._buf.get_iter_at_offset(end))
        if not self._matches:
            self._current = None
        elif from_cursor:
            bounds = self._buf.get_selection_bounds()
            at = bounds[0].get_offset() if bounds else self._insert_offset()
            self._current = next_index(self._matches, at)
            self._select_current()
        self._show_count()

    def step(self, backwards: bool = False):
        """Go to the next match, or the previous one, wrapping round."""
        if not self._matches:
            return
        if self._current is None:
            at = self._insert_offset()
        elif backwards:
            at = self._matches[self._current][0]
        else:
            at = self._matches[self._current][0] + 1
        self._current = next_index(self._matches, at, backwards)
        self._select_current()
        self._show_count()

    def _mark_current(self):
        self._buf.remove_tag(self._current_tag, *self._buf.get_bounds())
        if self._current is None:
            return
        start, end = self._matches[self._current]
        self._buf.apply_tag(self._current_tag,
                            self._buf.get_iter_at_offset(start),
                            self._buf.get_iter_at_offset(end))

    def _select_current(self):
        self._mark_current()
        if self._current is None:
            return
        start, end = self._matches[self._current]
        a = self._buf.get_iter_at_offset(start)
        self._buf.select_range(a, self._buf.get_iter_at_offset(end))
        self._view.scroll_to_iter(a, 0.1, False, 0, 0)

    def _clear_tags(self):
        self._buf.remove_tag(self._tag, *self._buf.get_bounds())
        self._buf.remove_tag(self._current_tag, *self._buf.get_bounds())

    def _show_count(self):
        n = len(self._matches)
        has_query = bool(self.entry.get_text())
        if not has_query:
            self._count.set_text('')
        elif not n:
            self._count.set_text(_('No matches'))
        else:
            self._count.set_text(_('{current} of {total}').format(
                current=(self._current or 0) + 1, total=n))
        for widget in (self._replace_btn, self._replace_all_btn):
            widget.set_sensitive(bool(n))

    def _on_buffer_changed(self, _buf):
        """Keep the marks true while the reader edits the page with the bar
        open. Once per idle, not per keystroke's worth of signals."""
        if not self.get_reveal_child() or self._refresh_source:
            return
        self._refresh_source = GLib.idle_add(self._refresh_after_edit)

    def _refresh_after_edit(self):
        self._refresh_source = 0
        current = self._current
        self._search(False)
        if self._matches and current is not None:
            self._current = min(current, len(self._matches) - 1)
            # Marked, not selected: selecting would pull the cursor out of
            # the words the reader is typing.
            self._mark_current()
            self._show_count()
        return GLib.SOURCE_REMOVE

    # ── Replacing ───────────────────────────────────────────────────────

    def replace(self):
        """Replace the current match, then go on to the next one.

        Only when the selection still IS that match: if the reader has since
        clicked somewhere else, the first press selects the match again and
        the second replaces it, so nothing is changed that is not on show.
        """
        if self._current is None:
            return
        start, end = self._matches[self._current]
        bounds = self._buf.get_selection_bounds()
        if not bounds or (bounds[0].get_offset(), bounds[1].get_offset()) \
                != (start, end):
            self._select_current()
            return
        new = self.replace_entry.get_text()
        self._buf.begin_user_action()
        self._buf.delete(self._buf.get_iter_at_offset(start),
                         self._buf.get_iter_at_offset(end))
        self._buf.insert(self._buf.get_iter_at_offset(start), new)
        self._buf.end_user_action()
        self._buf.place_cursor(self._buf.get_iter_at_offset(start + len(new)))
        self._search(True)

    def replace_all(self) -> int:
        """Replace every match as one undoable step. Returns how many."""
        new = self.replace_entry.get_text()
        text = self._text()
        matches = find_all(text, self.entry.get_text())
        if not matches:
            return 0
        # The whole page in one delete and one insert. An edit per match
        # costs the buffer's undo a step each: replacing the 4,320 uses of
        # "the" in an 8,500-word manuscript took 2.4 s, and undoing it 4.9 s,
        # with the window frozen for both. As one edit each takes a
        # millisecond. The cursor is put back where it was, moved by the
        # replacements before it, as the edits would have moved it.
        pieces, last = [], 0
        for start, end in matches:
            pieces.append(text[last:start])
            pieces.append(new)
            last = end
        pieces.append(text[last:])
        cursor = self._insert_offset()
        cursor += sum(len(new) - (end - start)
                      for start, end in matches if end <= cursor)
        self._buf.begin_user_action()
        self._buf.delete(*self._buf.get_bounds())
        self._buf.insert(self._buf.get_start_iter(), ''.join(pieces))
        self._buf.end_user_action()
        self._buf.place_cursor(self._buf.get_iter_at_offset(
            max(0, min(cursor, self._buf.get_char_count()))))
        # Searched here rather than on idle, so the count can say what was
        # done instead of a bare "No matches" a moment later.
        if self._refresh_source:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = 0
        self._search(False)
        n = len(matches)
        self._count.set_text(ngettext(
            'Replaced {n} match', 'Replaced {n} matches', n).format(n=n))
        return n

