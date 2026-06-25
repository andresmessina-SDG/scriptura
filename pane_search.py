"""Per-pane Ctrl+F search subsystem.

A `PaneSearch` owns the search bar widgets (toggle button, revealer,
entry, case toggle, status label, results list) and the matched-word
highlight tag for one `BiblePane`. Composed into the pane as
`pane._search`; the pane exposes thin delegators (`step_pane_search_result`,
`_pane_search_results`, `_pending_search_highlight`, `_pane_search_rev`)
to keep window.py's external interface unchanged.

Extracted from pane.py as part of the v1.0 polish pass; previously
~250 lines inlined inside BiblePane.
"""

import re
import threading

from gi.repository import Gtk, GLib, Pango
from a11y import set_accessible_label
from gtk_utils import clear_children

import sword_bridge
import ebible_bridge


class PaneSearch:
    def __init__(self, pane):
        self._pane = pane
        # Bumped on each search; a finishing background search whose token
        # no longer matches has been superseded and its results are dropped.
        self._search_gen = 0
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
        self._hl_timer = None  # GLib source id for the 5 s auto-expire
        # Widgets — populated by build_button / build_revealer.
        self._btn = None
        self._rev = None
        self._entry = None
        self._case_btn = None
        self._spinner = None
        self._status = None
        self._list = None

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
        """Construct + return the slide-down search bar revealer."""
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        se_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        se_row.set_margin_start(8)
        se_row.set_margin_end(8)
        se_row.set_margin_top(6)
        se_row.set_margin_bottom(6)

        self._entry = Gtk.SearchEntry(hexpand=True)
        self._entry.set_placeholder_text(_('Search this module…'))
        self._entry.connect('activate', self._on_search)
        self._entry.connect('stop-search',
                            lambda _: self._btn.set_active(False))

        self._case_btn = Gtk.ToggleButton(label='Aa')
        self._case_btn.add_css_class('flat')
        self._case_btn.set_tooltip_text(_('Match case'))
        set_accessible_label(self._case_btn, _('Match case'))
        self._case_btn.connect('toggled', self._on_case_toggled)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)

        se_row.append(self._entry)
        se_row.append(self._case_btn)
        se_row.append(self._spinner)
        inner.append(se_row)
        inner.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._status = Gtk.Label(label='', xalign=0)
        self._status.add_css_class('dim-label')
        self._status.add_css_class('caption')
        self._status.set_margin_start(12)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(2)
        inner.append(self._status)

        ps_scroll = Gtk.ScrolledWindow()
        ps_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ps_scroll.set_max_content_height(200)
        ps_scroll.set_propagate_natural_height(True)
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class('boxed-list')
        self._list.set_margin_start(8)
        self._list.set_margin_end(8)
        self._list.set_margin_top(4)
        self._list.set_margin_bottom(8)
        self._list.connect('row-activated', self._on_row_activated)
        ps_scroll.set_child(self._list)
        inner.append(ps_scroll)
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

    def cancel_hl_timer(self):
        """Cancel the 5 s auto-expire timer for the search highlight.
        Called from every chapter-render reset path so the timer
        doesn't fire and remove a tag from a buffer that's already
        been re-rendered."""
        if self._hl_timer is not None:
            try:
                GLib.source_remove(self._hl_timer)
            except Exception:
                pass
            self._hl_timer = None

    def step(self, prev=False):
        """F3 / Shift+F3 step-through. Returns True if a navigation
        happened."""
        if not self._results or not self._pane._on_word_study_navigate:
            return False
        n = len(self._results)
        idx = (self._idx - 1) % n if prev else (self._idx + 1) % n
        self._idx = idx
        book, ch, v, _text = self._results[idx]
        self.stash_for_self()
        self._pane._on_word_study_navigate(book, ch, v)
        self._status.set_text(
            _('Result {i} of {n}').format(i=idx + 1, n=n))
        return True

    def apply_highlight(self):
        """Called from BiblePane._display after every chapter render.
        If a search surface stashed a pending query, find its word
        matches in the rendered buffer and amber-tag them so the user
        can spot what they were searching for. Auto-expires after 5 s."""
        buf = self._pane._buffer
        self.cancel_hl_timer()
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        tag_table = buf.get_tag_table()
        existing = tag_table.lookup('_search_hl')
        if existing:
            buf.remove_tag(existing, start, end)
            self._pane._view.queue_draw()  # bands are painted from this tag

        pending = self._pending_highlight
        self._pending_highlight = None
        if not pending:
            return
        query, case_sensitive = pending
        words = [w for w in re.split(r'\s+', query.strip()) if w]
        if not words:
            return

        tag = existing
        if tag is None:
            # Pure marker — no foreground. BibleTextView paints the translucent
            # amber band from this tag's ranges; the matched word keeps its own
            # text colour, so applying/removing the search highlight never
            # desyncs the glyph colour from the band paint.
            tag = buf.create_tag('_search_hl')

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = r'\b(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
        # get_slice, not get_text: get_text omits the placeholder char for
        # embedded child anchors (the artifact-marker buttons), but iter
        # offsets count them — so in a chapter with markers every match after
        # one would be tagged shifted. get_slice keeps the U+FFFC placeholders
        # so regex offsets and buffer offsets stay aligned.
        text = buf.get_slice(start, end, True)
        applied = False
        try:
            for m in re.finditer(pattern, text, flags):
                si = buf.get_iter_at_offset(m.start())
                ei = buf.get_iter_at_offset(m.end())
                buf.apply_tag(tag, si, ei)
                applied = True
        except re.error:
            return

        if applied:
            self._pane._view.queue_draw()

            def _expire():
                self._hl_timer = None
                t = buf.get_tag_table().lookup('_search_hl')
                if t:
                    buf.remove_tag(
                        t, buf.get_start_iter(), buf.get_end_iter())
                    self._pane._view.queue_draw()
                return GLib.SOURCE_REMOVE
            self._hl_timer = GLib.timeout_add(5000, _expire)

    # ── Internal handlers ─────────────────────────────────────────────────

    def _on_toggled(self, btn):
        if btn.get_active():
            self._rev.set_reveal_child(True)
            self._entry.grab_focus()
        else:
            self._rev.set_reveal_child(False)
            self._entry.set_text('')
            clear_children(self._list)
            self._status.set_text('')

    def _on_search(self, *_a):
        query = self._entry.get_text().strip()
        if not query:
            return
        module = self._pane._module
        clear_children(self._list)
        self._status.set_text(_('Searching…'))
        self._spinner.set_visible(True)
        self._spinner.start()

        def _idx_start():
            GLib.idle_add(self._status.set_text, _('Building index…'))

        def _idx_progress(book_idx, total, book_name):
            GLib.idle_add(
                self._status.set_text,
                _('Building index… {book} ({idx}/{total})').format(
                    book=book_label(book_name), idx=book_idx, total=total))

        case = self._case_btn.get_active()

        self._search_gen += 1
        gen = self._search_gen

        def run():
            if ebible_bridge.is_ebible_module(module):
                results = ebible_bridge.search_module(
                    module, query, case_sensitive=case)
            else:
                results = sword_bridge.search_module(
                    module, query,
                    on_indexing_start=_idx_start,
                    on_indexing_progress=_idx_progress,
                    on_indexing_done=lambda: None,
                    case_sensitive=case)
            GLib.idle_add(self._on_done, results, module, gen)

        threading.Thread(target=run, daemon=True).start()

    def _on_case_toggled(self, _btn):
        # Re-run if there's a query to reflect the new mode.
        if self._entry.get_text().strip():
            self._on_search()

    def _on_done(self, results, module, gen):
        if gen != self._search_gen:
            return GLib.SOURCE_REMOVE
        self._spinner.stop()
        self._spinner.set_visible(False)
        if module != self._pane._module:
            return GLib.SOURCE_REMOVE
        truncated = bool(results and results[-1][0] == '')
        if truncated:
            results = results[:-1]
        # Stash for F3 / Shift+F3 step-through.
        self._results = list(results)
        self._idx = -1
        if truncated:
            self._status.set_text(
                _('Showing first {n} results — try a more specific search.')
                .format(n=sword_bridge.MAX_SEARCH_RESULTS))
        else:
            n = len(results)
            self._status.set_text(ngettext(
                '{n} verse found', '{n} verses found', n).format(n=n))
        for book, ch, v, text in results[:500]:
            row = Gtk.ListBoxRow()
            row._nav = (book, ch, v)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.set_margin_start(10)
            box.set_margin_end(10)
            box.set_margin_top(5)
            box.set_margin_bottom(5)
            ref = Gtk.Label(label=f'{book_label(book)} {ch}:{v}', xalign=0)
            ref.add_css_class('caption')
            snippet = text[:120] + ('…' if len(text) > 120 else '')
            body = Gtk.Label(label=snippet, xalign=0, wrap=False)
            body.set_ellipsize(Pango.EllipsizeMode.END)
            body.add_css_class('dim-label')
            body.add_css_class('caption')
            box.append(ref)
            box.append(body)
            row.set_child(box)
            self._list.append(row)
        return GLib.SOURCE_REMOVE

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, '_nav') and self._pane._on_word_study_navigate:
            self.stash_for_self()
            self._pane._on_word_study_navigate(*row._nav)
