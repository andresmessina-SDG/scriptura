"""Per-pane find-in-this-chapter bar.

A `PaneSearch` owns the find-bar widgets (toggle button, revealer,
entry, case toggle, match counter, prev/next steppers) and the
matched-word highlight tag for one `BiblePane`. Modelled on a browser
find-in-page: matches in the chapter on screen are highlighted in place
and stepped through with Enter/Shift+Enter/F3, rather than listed. The
whole-Bible search is the window's search panel; this bar never leaves
the chapter, so the two have one job each. Composed into the pane as
`pane._search`; the pane exposes thin delegators (`step_pane_search_result`,
`_pane_search_results`, `_pending_search_highlight`, `_pane_search_rev`)
to keep window.py's external interface unchanged.

Extracted from pane.py as part of the v1.0 polish pass; previously
~250 lines inlined inside BiblePane.
"""

import re

from gi.repository import Gdk, Gtk
import a11y
from a11y import set_accessible_label

import motion
import search_query
from i18n import _, ngettext



def _buffer_slice_without_markers(buf):
    """The buffer's text with footnote marker labels blanked out.

    get_slice keeps the U+FFFC anchor placeholders so regex offsets and buffer
    offsets stay aligned; the markers are ordinary letters sitting mid-sentence
    and would join words that a reader never sees joined. Blanked, not removed,
    so every offset still lands where it did. Markers are in the buffer whether
    or not they are shown, so this applies in both states.
    """
    text = buf.get_slice(buf.get_start_iter(), buf.get_end_iter(), True)
    tag = buf.get_tag_table().lookup('fn_marker')
    if tag is None:
        return text
    chars = list(text)
    it = buf.get_start_iter()
    if not it.starts_tag(tag):
        if not it.forward_to_tag_toggle(tag):
            return text
    while True:
        if it.starts_tag(tag):
            start = it.get_offset()
            if not it.forward_to_tag_toggle(tag):
                break
            for i in range(start, min(it.get_offset(), len(chars))):
                chars[i] = '\x00'
        if not it.forward_to_tag_toggle(tag):
            break
    return ''.join(chars)

class PaneSearch:
    def __init__(self, pane):
        self._pane = pane
        # (start, end) buffer offsets of every match in the chapter on
        # screen, and which one the bar is parked on (-1: none yet).
        self._matches = []
        self._idx = -1
        # Set when the window's search panel is about to navigate the pane;
        # consumed by `apply_highlight` after the chapter re-render lands so
        # the matched words flash amber for the user.
        self._pending_highlight = None
        # Widgets — populated by build_button / build_revealer.
        self._btn = None
        self._rev = None
        self._entry = None
        self._case_btn = None
        self._status = None
        self._prev_btn = None
        self._next_btn = None

    # ── Widget construction ───────────────────────────────────────────────

    def build_button(self):
        """Construct + return the toolbar toggle button."""
        # Its own icon, not the header's magnifier: the header searches the
        # whole Bible, this finds words on the page in front of you.
        self._btn = Gtk.ToggleButton(icon_name='scriptura-find-in-text-symbolic')
        set_accessible_label(self._btn, _('Find in this chapter'))
        self._btn.add_css_class('flat')
        self._btn.add_css_class('pane-action')
        self._btn.set_tooltip_text(_('Find in this chapter'))
        self._btn.connect('toggled', self._on_toggled)
        return self._btn

    def build_revealer(self):
        """Construct + return the slide-down find bar revealer.

        A single slim row — entry, match counter, prev/next steppers,
        case toggle — modelled on a browser find bar rather than a
        results list, so the reading view keeps its full height."""
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        se_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        se_row.set_margin_start(8)
        se_row.set_margin_end(8)
        se_row.set_margin_top(6)
        se_row.set_margin_bottom(6)

        self._entry = Gtk.SearchEntry(hexpand=True)
        self._entry.set_search_delay(motion.SEARCH_DEBOUNCE_MS)
        self._entry.set_placeholder_text(_('Find in this chapter…'))
        self._entry.connect('activate', lambda _e: self.step(prev=False))
        self._entry.connect('next-match', lambda _e: self.step(prev=False))
        self._entry.connect('previous-match', lambda _e: self.step(prev=True))
        self._entry.connect('search-changed', self._on_search_changed)
        self._entry.connect('stop-search',
                            lambda _: self._btn.set_active(False))
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_entry_key)
        self._entry.add_controller(keys)

        # Match counter — "3 of 12" while stepping, "12 in this chapter"
        # as you type. Right-aligned with a reserved width so the steppers
        # don't jitter as the digits change.
        self._status = Gtk.Label(label='', xalign=1)
        self._status.add_css_class('dim-label')
        self._status.add_css_class('caption')
        self._status.set_width_chars(11)
        # The counter is a status region, and it describes the entry: an AT
        # user who lands on the field hears the current match count with it.
        a11y.set_role(self._status, Gtk.AccessibleRole.STATUS)
        a11y.described_by(self._entry, self._status)

        self._prev_btn = Gtk.Button(icon_name='scriptura-go-up-symbolic')
        self._prev_btn.add_css_class('flat')
        self._prev_btn.set_tooltip_text(_('Previous match (Shift+Enter)'))
        set_accessible_label(self._prev_btn, _('Previous match'))
        self._prev_btn.set_sensitive(False)
        self._prev_btn.connect('clicked', lambda _b: self.step(prev=True))

        self._next_btn = Gtk.Button(icon_name='scriptura-go-down-symbolic')
        self._next_btn.add_css_class('flat')
        self._next_btn.set_tooltip_text(_('Next match (Enter)'))
        set_accessible_label(self._next_btn, _('Next match'))
        self._next_btn.set_sensitive(False)
        self._next_btn.connect('clicked', lambda _b: self.step(prev=False))

        self._case_btn = Gtk.ToggleButton(label='Aa')
        self._case_btn.add_css_class('flat')
        self._case_btn.set_tooltip_text(_('Match case'))
        set_accessible_label(self._case_btn, _('Match case'))
        self._case_btn.connect('toggled', self._on_case_toggled)

        se_row.append(self._entry)
        se_row.append(self._status)
        se_row.append(self._prev_btn)
        se_row.append(self._next_btn)
        se_row.append(self._case_btn)
        inner.append(se_row)
        inner.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Without this the whole find bar is a nameless stack of boxes; as a
        # named toolbar an AT user can tell what they have landed in.
        a11y.set_role(se_row, Gtk.AccessibleRole.TOOLBAR)
        set_accessible_label(se_row, _('Find in this chapter'))

        self._rev = Gtk.Revealer()
        self._rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._rev.set_transition_duration(200)
        self._rev.set_child(inner)
        self._rev.set_reveal_child(False)
        return self._rev

    def link_view(self, view):
        """Point the steppers at the reading view they act on.

        Separate from build_revealer because the pane builds its find bar
        before the TextView exists."""
        a11y.controls(self._prev_btn, view)
        a11y.controls(self._next_btn, view)

    # ── Public API used by the pane + window ──────────────────────────────

    @property
    def button(self):
        return self._btn

    @property
    def revealer(self):
        return self._rev

    @property
    def results(self):
        return self._matches

    @property
    def pending_highlight(self):
        return self._pending_highlight

    def stash_pending_highlight(self, query, case_sensitive):
        """Stash a (query, case) tuple to be picked up by apply_highlight
        after the next chapter render. Used by the window's search panel
        before navigating."""
        self._pending_highlight = (query, case_sensitive)

    def clear_state(self):
        """Drop stale per-module state. Called from
        BiblePane._apply_module_change so a module switch doesn't leak
        matches / pending highlights across surfaces."""
        self._matches = []
        self._idx = -1
        self._pending_highlight = None

    def step(self, prev=False):
        """Enter / F3 (Shift for back): park on the next match in the
        chapter, wrapping round, and bring it into view. Returns True if
        there was a match to go to."""
        if not self._matches:
            return False
        n = len(self._matches)
        if self._idx < 0:
            self._idx = n - 1 if prev else 0
        else:
            self._idx = (self._idx + (-1 if prev else 1)) % n
        buf = self._pane._buffer
        table = buf.get_tag_table()
        soft = table.lookup('_search_hl')
        cur = table.lookup('_search_hl_cur') or buf.create_tag('_search_hl_cur')
        buf.remove_tag(cur, *buf.get_bounds())
        # The soft band goes back on every match, then comes off the current
        # one, so the two never stack into a muddier colour.
        for s, e in self._matches:
            buf.apply_tag(soft, buf.get_iter_at_offset(s),
                          buf.get_iter_at_offset(e))
        s, e = self._matches[self._idx]
        si, ei = buf.get_iter_at_offset(s), buf.get_iter_at_offset(e)
        buf.remove_tag(soft, si, ei)
        buf.apply_tag(cur, si, ei)
        self._pane.view.queue_draw()
        # A find-bar jump is not the reader scrolling: mark it, and scroll by
        # mark so the move waits for line validation (see _scroll_to_verse).
        # It is a new reading place, though: drop the old anchor and capture
        # this one, or a resize or re-render would put the reader back.
        self._pane._mark_programmatic_scroll()
        self._pane._reading_anchor = None
        self._pane._schedule_anchor_capture(400)
        mark = buf.create_mark(None, si, True)
        self._pane.view.scroll_to_mark(mark, 0.1, False, 0.0, 0.0)
        buf.delete_mark(mark)
        a11y.status(self._status,
                    _('{i} of {n}').format(i=self._idx + 1, n=n))
        return True

    def _clear_hl_tags(self, buf):
        """Strip both search bands (all matches + current match) from the
        buffer. Returns True if either was present so callers can redraw."""
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        drawn = False
        for name in ('_search_hl', '_search_hl_cur'):
            t = buf.get_tag_table().lookup(name)
            if t:
                buf.remove_tag(t, start, end)
                drawn = True
        return drawn

    def apply_highlight(self):
        """Called from BiblePane._display after every chapter render.
        A query the window's search panel stashed wins: its word matches
        are amber-tagged so the reader spots what they searched for.
        Otherwise, if this bar is open with a query, the new chapter is
        searched for it — the bar follows the reader from chapter to
        chapter, the way a browser's find bar follows a page."""
        buf = self._pane._buffer
        if self._clear_hl_tags(buf):
            self._pane.view.queue_draw()  # bands are painted from these tags

        # Offsets from the chapter before mean nothing in this one.
        self._matches = []
        self._idx = -1
        if self._prev_btn is not None:
            self._prev_btn.set_sensitive(False)
            self._next_btn.set_sensitive(False)

        pending = self._pending_highlight
        self._pending_highlight = None
        if not pending:
            q = self._entry.get_text().strip() if self._entry else ''
            if q and self._rev.get_reveal_child():
                self._live_highlight(q)
            return
        if self._status is not None:
            self._status.set_text('')
        query, case_sensitive = pending
        # Highlight exactly the query's positive terms (phrases split into
        # their words, prefix '*' stripped, excluded -terms dropped) — the
        # same grammar the backend matched on, so the highlight reflects what
        # was actually searched for.
        words = search_query.plain_terms(query)
        if not words:
            return

        # Pure marker — no foreground. BibleTextView paints the translucent
        # bands from this tag's ranges; the matched word keeps its own text
        # colour, so applying/removing the search highlight never desyncs the
        # glyph colour from the band paint.
        tag = (buf.get_tag_table().lookup('_search_hl')
               or buf.create_tag('_search_hl'))
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = r'\b(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
        # get_slice, not get_text: get_text omits the placeholder char for
        # embedded child anchors (the artifact-marker buttons), but iter
        # offsets count them — so in a chapter with markers every match after
        # one would be tagged shifted. get_slice keeps the U+FFFC placeholders
        # so regex offsets and buffer offsets stay aligned.
        text = _buffer_slice_without_markers(buf)
        applied = False
        try:
            for m in re.finditer(pattern, text, flags):
                buf.apply_tag(tag, buf.get_iter_at_offset(m.start()),
                              buf.get_iter_at_offset(m.end()))
                applied = True
        except re.error:
            return

        if applied:
            self._pane.view.queue_draw()

    # ── Internal handlers ─────────────────────────────────────────────────

    def _on_toggled(self, btn):
        if btn.get_active():
            self._rev.set_reveal_child(True)
            self._entry.grab_focus()
        else:
            self._rev.set_reveal_child(False)
            self._entry.set_text('')  # emits search-changed → _clear
            self._clear()

    def _on_entry_key(self, _ctl, keyval, _code, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) \
                and state & Gdk.ModifierType.SHIFT_MASK:
            self.step(prev=True)
            return True
        return False

    def _clear(self):
        """Drop matches, counter, and stepper state — the empty-field
        rest state."""
        self._matches = []
        self._idx = -1
        self._status.set_text('')
        self._prev_btn.set_sensitive(False)
        self._next_btn.set_sensitive(False)
        # Highlights die with the query (they otherwise persist — the
        # browser find-in-page convention).
        if self._clear_hl_tags(self._pane._buffer):
            self._pane.view.queue_draw()

    def _on_search_changed(self, entry):
        q = entry.get_text().strip()
        if not q:
            self._clear()
            return
        self._live_highlight(q)

    def _live_highlight(self, query):
        """Substring-highlight `query` across the current chapter with a
        live count. Two-character minimum so a lone letter doesn't paint
        the whole page."""
        buf = self._pane._buffer
        if self._clear_hl_tags(buf):
            self._pane.view.queue_draw()
        self._matches = []
        self._idx = -1
        if len(query) < 2:
            self._status.set_text('')
            self._prev_btn.set_sensitive(False)
            self._next_btn.set_sensitive(False)
            return
        tag_table = buf.get_tag_table()
        tag = tag_table.lookup('_search_hl') or buf.create_tag('_search_hl')
        flags = 0 if self._case_btn.get_active() else re.IGNORECASE
        text = _buffer_slice_without_markers(buf)
        for m in re.finditer(re.escape(query), text, flags):
            buf.apply_tag(tag, buf.get_iter_at_offset(m.start()),
                          buf.get_iter_at_offset(m.end()))
            self._matches.append((m.start(), m.end()))
        n = len(self._matches)
        self._prev_btn.set_sensitive(n > 0)
        self._next_btn.set_sensitive(n > 0)
        if n:
            self._pane.view.queue_draw()
            a11y.status(
                self._status,
                ngettext('{n} in this chapter', '{n} in this chapter', n)
                .format(n=n))
        else:
            a11y.status(self._status, _('No matches'))

    def _on_case_toggled(self, _btn):
        q = self._entry.get_text().strip()
        if q:
            self._live_highlight(q)
