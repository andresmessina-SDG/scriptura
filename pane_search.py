"""Per-pane Ctrl+F find bar.

A `PaneSearch` owns the find-bar widgets (toggle button, revealer,
entry, case toggle, match counter, prev/next steppers) and the
matched-word highlight tag for one `BiblePane`. Modelled on a browser
Ctrl+F: matches are highlighted in place and stepped through with
↑/↓/F3, rather than listed. Composed into the pane as
`pane._search`; the pane exposes thin delegators (`step_pane_search_result`,
`_pane_search_results`, `_pending_search_highlight`, `_pane_search_rev`)
to keep window.py's external interface unchanged.

Extracted from pane.py as part of the v1.0 polish pass; previously
~250 lines inlined inside BiblePane.
"""

import re

from gi.repository import Gtk, GLib
from a11y import set_accessible_label
from gtk_utils import DelayedSpinner

import sword_bridge
import search_query
import search_controller


class PaneSearch:
    def __init__(self, pane):
        self._pane = pane
        # Shared search execution (dispatch + threading + stale-result
        # guarding) lives in search_controller; this owns only the widgets.
        self._runner = search_controller.SearchRunner()
        # F3 / Shift+F3 step-through state. `results` is the full list
        # produced by the most recent search; `idx` is the current
        # step position into it.
        self._results = []
        self._idx = -1
        # Set when a search surface (window panel or this per-pane bar)
        # is about to navigate the pane; consumed by `apply_highlight`
        # after the chapter re-render lands so the matched words flash
        # amber for the user.
        self._pending_highlight = None
        # (book, ch, v) of the match the find bar is currently parked on, so
        # apply_highlight can paint that verse's words with the stronger
        # "current match" band. None when navigation isn't a per-pane step.
        self._cur_ref = None
        # Widgets — populated by build_button / build_revealer.
        self._btn = None
        self._rev = None
        self._entry = None
        self._case_btn = None
        self._spinner = None
        self._delayed_spinner = None
        self._status = None
        self._prev_btn = None
        self._next_btn = None

    # ── Widget construction ───────────────────────────────────────────────

    def build_button(self):
        """Construct + return the toolbar toggle button."""
        self._btn = Gtk.ToggleButton(icon_name='system-search-symbolic')
        set_accessible_label(self._btn, _('Search this module'))
        self._btn.add_css_class('flat')
        self._btn.add_css_class('pane-action')
        self._btn.set_tooltip_text(_('Search this module'))
        self._btn.connect('toggled', self._on_toggled)
        return self._btn

    def build_revealer(self):
        """Construct + return the slide-down find bar revealer.

        A single slim row — entry, match counter, prev/next steppers,
        case toggle — modelled on a browser Ctrl+F find bar rather than a
        results list: matches are highlighted in place and stepped through
        with ↑/↓/F3, so the reading view keeps its full height."""
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        se_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        se_row.set_margin_start(8)
        se_row.set_margin_end(8)
        se_row.set_margin_top(6)
        se_row.set_margin_bottom(6)

        self._entry = Gtk.SearchEntry(hexpand=True)
        self._entry.set_placeholder_text(_('Search this module…'))
        self._entry.set_tooltip_text(_(
            'Phrase: "living water" · either: bread OR wine · '
            'exclude: faith -works · prefix: baptiz*'))
        self._entry.connect('activate', self._on_search)
        self._entry.connect('search-changed', self._on_search_changed)
        self._entry.connect('stop-search',
                            lambda _: self._btn.set_active(False))

        # Match counter — "3 of 3892" while stepping, a result summary
        # right after a search. Right-aligned with a reserved width so the
        # steppers don't jitter as the digits change.
        self._status = Gtk.Label(label='', xalign=1)
        self._status.add_css_class('dim-label')
        self._status.add_css_class('caption')
        self._status.set_width_chars(11)

        self._prev_btn = Gtk.Button(icon_name='go-up-symbolic')
        self._prev_btn.add_css_class('flat')
        self._prev_btn.set_tooltip_text(_('Previous match'))
        set_accessible_label(self._prev_btn, _('Previous match'))
        self._prev_btn.set_sensitive(False)
        self._prev_btn.connect('clicked', lambda _b: self.step(prev=True))

        self._next_btn = Gtk.Button(icon_name='go-down-symbolic')
        self._next_btn.add_css_class('flat')
        self._next_btn.set_tooltip_text(_('Next match'))
        set_accessible_label(self._next_btn, _('Next match'))
        self._next_btn.set_sensitive(False)
        self._next_btn.connect('clicked', lambda _b: self.step(prev=False))

        self._case_btn = Gtk.ToggleButton(label='Aa')
        self._case_btn.add_css_class('flat')
        self._case_btn.set_tooltip_text(_('Match case'))
        set_accessible_label(self._case_btn, _('Match case'))
        self._case_btn.connect('toggled', self._on_case_toggled)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self._delayed_spinner = DelayedSpinner(self._spinner)

        se_row.append(self._entry)
        se_row.append(self._spinner)
        se_row.append(self._status)
        se_row.append(self._prev_btn)
        se_row.append(self._next_btn)
        se_row.append(self._case_btn)
        inner.append(se_row)
        inner.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._rev = Gtk.Revealer()
        self._rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._rev.set_transition_duration(200)
        self._rev.set_child(inner)
        self._rev.set_reveal_child(False)
        return self._rev

    # ── Public API used by the pane + window ──────────────────────────────

    @property
    def button(self):
        return self._btn

    @property
    def revealer(self):
        return self._rev

    @property
    def results(self):
        return self._results

    @property
    def pending_highlight(self):
        return self._pending_highlight

    def stash_pending_highlight(self, query, case_sensitive):
        """Stash a (query, case) tuple to be picked up by apply_highlight
        after the next chapter render. Used by the window's external
        search panel before navigating."""
        self._pending_highlight = (query, case_sensitive)
        # A window-panel navigation isn't a per-pane step, so there's no
        # "current match" verse to single out — clear any stale one.
        self._cur_ref = None

    def stash_for_self(self):
        """Stash the current entry text before a self-initiated nav so
        apply_highlight paints the same matches on the destination
        chapter."""
        if not self._entry:
            return
        q = self._entry.get_text().strip()
        if not q:
            return
        self._pending_highlight = (q, self._case_btn.get_active())

    def clear_state(self):
        """Drop stale per-module state. Called from
        BiblePane._apply_module_change so a module switch doesn't leak
        results / pending highlights across surfaces."""
        self._results = []
        self._idx = -1
        self._pending_highlight = None
        self._cur_ref = None

    def step(self, prev=False):
        """F3 / Shift+F3 step-through. Returns True if a navigation
        happened."""
        if not self._results or not self._pane._on_word_study_navigate:
            return False
        n = len(self._results)
        idx = (self._idx - 1) % n if prev else (self._idx + 1) % n
        self._idx = idx
        book, ch, v, _text = self._results[idx]
        self._cur_ref = (book, ch, v)
        self.stash_for_self()
        self._pane._on_word_study_navigate(book, ch, v)
        self._status.set_text(
            _('{i} of {n}').format(i=idx + 1, n=n))
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

    def _cur_verse_span(self, buf):
        """Buffer [start, end) offsets of the verse the find bar is parked
        on, or None. Used to paint that verse's matches with the stronger
        current-match band."""
        if not self._cur_ref:
            return None
        book, ch, v = self._cur_ref
        # Guard against a stale ref: only single out the verse if the render
        # we're highlighting is actually its chapter (vnum tags are recreated
        # per chapter, so a same-numbered verse elsewhere could collide).
        if (book, ch) != (self._pane._book, self._pane._chapter):
            return None
        # Index refs are app-space (FTS v3); the buffer's vnum tags carry
        # the module's own numbering — translate (no-op for app-keyed).
        v = sword_bridge.map_target_verse(self._pane._module, book, ch, v)
        tag = buf.get_tag_table().lookup(f'vnum_{v}')
        if not tag:
            return None
        it = buf.get_start_iter()
        if not it.has_tag(tag) and not it.forward_to_tag_toggle(tag):
            return None
        e = it.copy()
        e.forward_to_tag_toggle(tag)
        return it.get_offset(), e.get_offset()

    def apply_highlight(self):
        """Called from BiblePane._display after every chapter render.
        If a search surface stashed a pending query, find its word
        matches in the rendered buffer and amber-tag them so the user
        can spot what they were searching for. The verse the find bar is
        parked on gets a stronger band so it reads as the current match.
        Highlights persist until the query changes or the bar closes
        (the browser find-in-page convention)."""
        buf = self._pane._buffer
        if self._clear_hl_tags(buf):
            self._pane._view.queue_draw()  # bands are painted from these tags

        pending = self._pending_highlight
        self._pending_highlight = None
        if not pending:
            return
        query, case_sensitive = pending
        # Highlight exactly the query's positive terms (phrases split into
        # their words, prefix '*' stripped, excluded -terms dropped) — the
        # same grammar the backend matched on, so the highlight reflects what
        # was actually searched for.
        words = search_query.plain_terms(query)
        if not words:
            return

        tag_table = buf.get_tag_table()
        # Pure markers — no foreground. BibleTextView paints the translucent
        # bands from these tags' ranges; the matched word keeps its own text
        # colour, so applying/removing the search highlight never desyncs the
        # glyph colour from the band paint.
        tag = tag_table.lookup('_search_hl') or buf.create_tag('_search_hl')
        cur_tag = (tag_table.lookup('_search_hl_cur')
                   or buf.create_tag('_search_hl_cur'))
        cur_span = self._cur_verse_span(buf)

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = r'\b(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
        # get_slice, not get_text: get_text omits the placeholder char for
        # embedded child anchors (the artifact-marker buttons), but iter
        # offsets count them — so in a chapter with markers every match after
        # one would be tagged shifted. get_slice keeps the U+FFFC placeholders
        # so regex offsets and buffer offsets stay aligned.
        text = buf.get_slice(buf.get_start_iter(), buf.get_end_iter(), True)
        applied = False
        try:
            for m in re.finditer(pattern, text, flags):
                si = buf.get_iter_at_offset(m.start())
                ei = buf.get_iter_at_offset(m.end())
                # A match inside the parked verse is the current one — give it
                # the stronger band and skip the soft one so the two don't
                # stack into a muddier colour.
                in_cur = (cur_span is not None
                          and cur_span[0] <= m.start() < cur_span[1])
                buf.apply_tag(cur_tag if in_cur else tag, si, ei)
                applied = True
        except re.error:
            return

        if applied:
            self._pane._view.queue_draw()

    # ── Internal handlers ─────────────────────────────────────────────────

    def _on_toggled(self, btn):
        if btn.get_active():
            self._rev.set_reveal_child(True)
            self._entry.grab_focus()
        else:
            self._rev.set_reveal_child(False)
            self._entry.set_text('')  # emits search-changed → _clear
            self._clear()

    def _clear(self):
        """Drop matches, counter, and stepper state — the empty-field
        rest state. Fixes the stale 'N verses found' that used to linger
        after the query was cleared."""
        self._results = []
        self._idx = -1
        self._cur_ref = None
        self._status.set_text('')
        self._prev_btn.set_sensitive(False)
        self._next_btn.set_sensitive(False)
        self._delayed_spinner.stop()
        # Highlights die with the query (they otherwise persist — the
        # browser find-in-page convention).
        if self._clear_hl_tags(self._pane._buffer):
            self._pane._view.queue_draw()

    def _on_search_changed(self, entry):
        # Only react to an emptied field; a live query is searched on
        # Enter (see _on_search), not on every keystroke.
        if not entry.get_text().strip():
            self._clear()

    def _on_search(self, *_a):
        query = self._entry.get_text().strip()
        if not query:
            return
        module = self._pane._module
        self._status.set_text(_('Searching…'))
        self._prev_btn.set_sensitive(False)
        self._next_btn.set_sensitive(False)
        # Threshold-gated: an already-indexed FTS query returns fast and
        # never flashes a spinner; the status text is immediate either way.
        self._delayed_spinner.start()

        def _idx_start():
            GLib.idle_add(self._status.set_text, _('Indexing…'))

        def _idx_progress(book_idx, total, book_name):
            GLib.idle_add(
                self._status.set_text,
                _('Indexing {idx}/{total}').format(idx=book_idx, total=total))

        case = self._case_btn.get_active()

        def _search():
            return search_controller.search_backend(
                module, query, case,
                on_indexing_start=_idx_start,
                on_indexing_progress=_idx_progress,
                on_indexing_done=lambda: None)

        self._runner.run(_search, lambda rows, truncated:
                         self._on_done(rows, truncated, module))

    def _on_case_toggled(self, _btn):
        # Re-run if there's a query to reflect the new mode.
        if self._entry.get_text().strip():
            self._on_search()

    def _on_done(self, results, truncated, module):
        # Stale results were already dropped by the runner's generation guard.
        self._delayed_spinner.stop()
        if module != self._pane._module:
            return
        self._results = list(results)
        self._idx = -1
        n = len(self._results)
        has = n > 0
        self._prev_btn.set_sensitive(has)
        self._next_btn.set_sensitive(has)
        if not has:
            self._status.set_text(_('No matches'))
            return
        if truncated and self._pane._on_toast:
            self._pane._on_toast(
                _('Showing first {n} matches — try a more specific search.')
                .format(n=sword_bridge.MAX_SEARCH_RESULTS))
        # Jump to the first match; step() sets the "1 of N" counter.
        self.step(prev=False)
