"""Generic Books (TreeKey) reader extracted from BiblePane.

SWORD's Generic Books are tree-keyed modules (Augsburg Confession,
Spurgeon's sermons-as-book, Westminster Standards). Unlike Bibles they
have no book/chapter/verse — entries are addressed by TreeKey paths
like '/Article_1' or '/Sermon_42/Section_A'.

This module owns:
  - The three toolbar widgets (prev / next / TOC menubutton + popover).
  - The current entry-path state.
  - The full render pipeline: async fetch on a background thread,
    fallback-to-first-non-empty when the saved entry is stale or empty,
    breadcrumb title, GTK idle_add display, TOC popover lazy-build,
    sibling step navigation, position persistence.

The pane still owns `_is_genbook` because it gates pane-level chrome
(sync / chapter-note / search visibility) and dispatches between
verse-keyed / genbook / devotional render paths. Calls into the reader
are the four entry points: build_toolbar, set_module, update_visibility,
fetch_and_render — plus step / save_position / entry property.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any, Callable

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

import module_positions
import sword_bridge
from a11y import set_accessible_label
from i18n import _

if TYPE_CHECKING:
    from pane import BiblePane

# (path, label, depth) — TreeKey listing tuple from sword_bridge.
Entry = tuple[str, str, int]
HtmlToMarkup = Callable[..., str]


class GenbookReader:
    def __init__(self, pane: BiblePane, html_to_markup: HtmlToMarkup) -> None:
        self._pane = pane
        self._html_to_markup = html_to_markup
        self._entry_path: str | None = None
        # Widgets are created by build_toolbar() so the caller controls
        # where they sit in the toolbar Box.
        self._prev_btn: Gtk.Button | None = None
        self._next_btn: Gtk.Button | None = None
        self._toc_btn: Gtk.MenuButton | None = None
        self._toc_pop: Gtk.Popover | None = None

    @property
    def entry(self) -> str | None:
        return self._entry_path

    # ── Lifecycle hooks driven by BiblePane ──────────────────────────────

    def build_toolbar(self, toolbar: Gtk.Box) -> None:
        """Create and append prev / next / TOC widgets to the pane toolbar.
        All three start hidden — `update_visibility(True)` reveals them
        when the active module is a Generic Book."""
        self._prev_btn = Gtk.Button(icon_name='go-previous-symbolic')
        self._prev_btn.add_css_class('flat')
        self._prev_btn.add_css_class('pane-action')
        self._prev_btn.set_tooltip_text(_('Previous entry'))
        set_accessible_label(self._prev_btn, _('Previous entry'))
        self._prev_btn.set_visible(False)
        self._prev_btn.connect('clicked', lambda _b: self.step(-1))
        toolbar.append(self._prev_btn)

        self._next_btn = Gtk.Button(icon_name='go-next-symbolic')
        self._next_btn.add_css_class('flat')
        self._next_btn.add_css_class('pane-action')
        self._next_btn.set_tooltip_text(_('Next entry'))
        set_accessible_label(self._next_btn, _('Next entry'))
        self._next_btn.set_visible(False)
        self._next_btn.connect('clicked', lambda _b: self.step(1))
        toolbar.append(self._next_btn)

        self._toc_btn = Gtk.MenuButton(
            icon_name='view-list-bullet-symbolic')
        self._toc_btn.add_css_class('flat')
        self._toc_btn.add_css_class('pane-action')
        self._toc_btn.set_tooltip_text(_('Table of contents'))
        set_accessible_label(self._toc_btn, _('Table of contents'))
        self._toc_btn.set_visible(False)
        self._toc_pop = Gtk.Popover()
        self._toc_pop.set_has_arrow(True)
        self._toc_btn.set_popover(self._toc_pop)
        self._toc_pop.connect('show', lambda _p: self._build_toc())
        toolbar.append(self._toc_btn)

    def set_module(self, module: str | None, is_genbook: bool) -> None:
        """Called on initial pane creation and on every module switch.
        Loads the saved entry path from module_positions for genbooks;
        clears it otherwise."""
        if is_genbook and module:
            self._entry_path = module_positions.get_genbook_path(module)
        else:
            self._entry_path = None

    def update_visibility(self, is_genbook: bool) -> None:
        if self._prev_btn is None:
            return  # build_toolbar() not yet called
        assert self._next_btn is not None and self._toc_btn is not None
        self._prev_btn.set_visible(is_genbook)
        self._next_btn.set_visible(is_genbook)
        self._toc_btn.set_visible(is_genbook)

    def save_position(self) -> None:
        """Persist the current entry path into module_positions."""
        if not self._entry_path:
            return
        module = self._pane._module
        if not module:
            return
        module_positions.remember_genbook_path(module, self._entry_path)

    # ── Render pipeline ──────────────────────────────────────────────────

    def fetch_and_render(self) -> None:
        """Render the current Generic Book entry. If no entry is selected
        (cold open) or the saved entry path no longer renders (module
        restructured between sessions), fall back to the first
        non-empty entry."""
        module = self._pane._module

        def fetch() -> None:
            entries: list[Entry] = sword_bridge.list_genbook_entries(module)
            entry_path = self._entry_path
            html = ''

            if entry_path:
                html = sword_bridge.load_genbook_entry(module, entry_path)
                # Saved path may be stale (module reinstalled with
                # different TreeKey shape). Detect by checking if it
                # strips to empty; if so, fall through to first-non-empty.
                if not (html and re.sub(r'<[^>]+>', '', html).strip()):
                    # Only auto-skip if the entry has no children either —
                    # genuine section-heading entries (with kids) we
                    # WANT to land on so the empty-entry hint can fire.
                    if not self._entry_has_children(entries, entry_path):
                        entry_path = None
                        html = ''

            if entry_path is None and entries:
                # Walk the first few entries until one has real content.
                for path, _label, _depth in entries[:8]:
                    candidate = sword_bridge.load_genbook_entry(module, path)
                    if candidate and re.sub(r'<[^>]+>', '', candidate).strip():
                        entry_path = path
                        html = candidate
                        break
                else:
                    # All scanned entries were empty — land on the first
                    # one anyway so the section-heading hint can render.
                    entry_path = entries[0][0]
                    html = sword_bridge.load_genbook_entry(module, entry_path)

            GLib.idle_add(self._display, entries, entry_path, html, module)

        threading.Thread(target=fetch, daemon=True).start()

    @staticmethod
    def _entry_has_children(entries: list[Entry], path: str | None) -> bool:
        """True if any other entry in `entries` is a descendant of `path`
        (i.e., `path` is a section heading with sub-entries)."""
        if not path:
            return False
        prefix = path + '/'
        return any(p.startswith(prefix) for p, _l, _d in entries)

    def _display(self, entries: list[Entry], entry_path: str | None,
                 html: str, module: str) -> Any:
        # Returns GLib.SOURCE_REMOVE — typed as Any since gi stubs don't
        # narrow the constant; this is the GLib.idle_add callback contract.
        pane = self._pane
        if module != pane._module or not pane._is_genbook:
            return GLib.SOURCE_REMOVE
        dark = Adw.StyleManager.get_default().get_dark()
        pane._cancel_all_flashes()
        pane._buffer.set_text('')
        pane._clear_chapter_scoped_tags()

        self._entry_path = entry_path
        self.save_position()
        self._update_nav_sensitivity(entries)

        if not entries:
            fg = '#8d8278' if dark else '#7a7066'
            pane._buffer.insert_markup(
                pane._buffer.get_end_iter(),
                f'<span foreground="{fg}">'
                f'{GLib.markup_escape_text(module)}\n\n'
                f'This generic book has no readable entries.</span>', -1)
            return GLib.SOURCE_REMOVE

        # Breadcrumb title: split the TreeKey path on '/' and join the
        # segments with ' › '. Long hierarchies get full context
        # ("Augsburg Confession › Of God › Article 1") rather than
        # just the leaf name. Underscores in any segment → spaces.
        if entry_path:
            segs = [s.replace('_', ' ') for s in entry_path.split('/') if s]
            breadcrumb = ' › '.join(segs) if segs else module
        else:
            breadcrumb = module
        title_fg = '#7a7066' if not dark else '#8d8278'
        title_start = pane._buffer.get_end_iter().get_offset()
        pane._buffer.insert_markup(
            pane._buffer.get_end_iter(),
            f'<span size="x-large" weight="bold" foreground="{title_fg}" '
            f'letter_spacing="400">'
            f'{GLib.markup_escape_text(breadcrumb)}</span>\n\n',
            -1)
        # The view-wide justification (FILL when the user enables "Justified")
        # would stretch a wrapped title into ragged word gaps — headings must
        # never justify. Pin the title paragraph to left-aligned via a tag,
        # which overrides the view default. Reused across renders.
        table = pane._buffer.get_tag_table()
        left_tag = table.lookup('gb-title-left')
        if left_tag is None:
            left_tag = pane._buffer.create_tag(
                'gb-title-left', justification=Gtk.Justification.LEFT)
        pane._buffer.apply_tag(
            left_tag,
            pane._buffer.get_iter_at_offset(title_start),
            pane._buffer.get_end_iter())

        if html and re.sub(r'<[^>]+>', '', html).strip():
            try:
                markup = self._html_to_markup(html, dark)
                pane._buffer.insert_markup(
                    pane._buffer.get_end_iter(), markup, -1)
            except Exception:
                pane._buffer.insert(
                    pane._buffer.get_end_iter(),
                    re.sub(r'<[^>]+>', '', html))
        else:
            # Distinguish "section heading with sub-entries" from a
            # genuinely-empty leaf so the user knows whether to open
            # the TOC or whether the module just has nothing here.
            fg = '#8d8278' if dark else '#7a7066'
            if self._entry_has_children(entries, entry_path):
                msg = ('This is a section heading. Open the table of '
                       'contents and pick a sub-entry to read.')
            else:
                msg = '(Empty entry.)'
            pane._buffer.insert_markup(
                pane._buffer.get_end_iter(),
                f'<span foreground="{fg}">'
                f'{GLib.markup_escape_text(msg)}</span>', -1)

        pane._view.get_vadjustment().set_value(0)
        return GLib.SOURCE_REMOVE

    # ── Sibling navigation (prev/next entry buttons) ─────────────────────

    def step(self, delta: int) -> None:
        """Move to the previous (delta=-1) or next (delta=+1) entry in
        document order."""
        if not self._pane._is_genbook:
            return
        entries: list[Entry] = sword_bridge.list_genbook_entries(self._pane._module)
        if not entries:
            return
        paths = [p for p, _l, _d in entries]
        try:
            idx = paths.index(self._entry_path) if self._entry_path else 0
        except ValueError:
            idx = 0
        new_idx = max(0, min(len(paths) - 1, idx + delta))
        if new_idx == idx:
            return
        self._entry_path = paths[new_idx]
        self.save_position()
        self.fetch_and_render()

    def _update_nav_sensitivity(self, entries: list[Entry]) -> None:
        """Grey out prev/next when at the first/last entry."""
        if self._prev_btn is None or self._next_btn is None:
            return
        if not entries:
            self._prev_btn.set_sensitive(False)
            self._next_btn.set_sensitive(False)
            return
        paths = [p for p, _l, _d in entries]
        try:
            idx = paths.index(self._entry_path) if self._entry_path else 0
        except ValueError:
            idx = 0
        self._prev_btn.set_sensitive(idx > 0)
        self._next_btn.set_sensitive(idx < len(paths) - 1)

    # ── TOC popover (lazy-built on each open) ────────────────────────────

    def _build_toc(self) -> None:
        """Populate the TOC popover with this module's TreeKey entries.
        Built lazily on each show because the active module can change."""
        assert self._toc_pop is not None
        pop = self._toc_pop
        entries: list[Entry] = sword_bridge.list_genbook_entries(self._pane._module)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(480)
        scroll.set_propagate_natural_height(True)
        # Force the popover content to be wide. Setting min_content_width
        # on the ScrolledWindow alone wasn't enough on narrow windows —
        # the popover anchors to the TOC button (top-right of the pane
        # toolbar) and constrained itself to the gap to the window edge.
        # set_size_request on the listbox forces the popover to take at
        # least this width; GTK will reposition the popover (flip arrow
        # direction or shift offset) to honor it.
        # …but never wider than the window — cap to the available width so the
        # popover doesn't overflow a narrow window (360 when there's room).
        root = self._pane.get_root()
        win_w = root.get_width() if root is not None else 0
        toc_w = 360 if win_w <= 0 else max(260, min(360, win_w - 24))
        scroll.set_size_request(toc_w, -1)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class('navigation-sidebar')
        listbox.set_size_request(toc_w, -1)

        if not entries:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            lbl = Gtk.Label(label=_('No entries in this book.'), xalign=0)
            lbl.add_css_class('dim-label')
            lbl.set_margin_start(12)
            lbl.set_margin_end(12)
            lbl.set_margin_top(10)
            lbl.set_margin_bottom(10)
            row.set_child(lbl)
            listbox.append(row)
        else:
            current_row: Gtk.ListBoxRow | None = None
            for path, label, depth in entries:
                row = Gtk.ListBoxRow()
                row._path = path
                # Convert TreeKey segment underscores to spaces for
                # display. The raw `path` is preserved for setKeyText.
                display_label = label.replace('_', ' ')
                lbl = Gtk.Label(label=display_label, xalign=0)
                # Wrap rather than ellipsize so long section names
                # ("Preface to the Electronic Edition") are fully
                # readable. Cap at a reasonable width so the popover
                # doesn't stretch arbitrarily.
                lbl.set_wrap(True)
                lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                lbl.set_max_width_chars(38)
                # Indent according to TreeKey depth so the hierarchy
                # reads visually.
                lbl.set_margin_start(12 + depth * 14)
                lbl.set_margin_end(12)
                lbl.set_margin_top(4)
                lbl.set_margin_bottom(4)
                if path == self._entry_path:
                    lbl.add_css_class('accent')
                    current_row = row
                row.set_child(lbl)
                listbox.append(row)
            listbox.connect('row-activated', self._on_entry_chosen)

            # Auto-scroll the TOC to the current entry once the popover
            # has had a chance to allocate. Without the idle defer, the
            # row's vadjustment math runs against stale sizes.
            if current_row is not None:
                current_row_capture = current_row

                def _scroll_to_current() -> Any:
                    try:
                        adj = scroll.get_vadjustment()
                        success, rect = current_row_capture.compute_bounds(listbox)
                        if not success or adj is None:
                            return GLib.SOURCE_REMOVE
                        page = adj.get_page_size()
                        target = max(0.0,
                                     rect.get_y() - page / 2 + rect.get_height() / 2)
                        adj.set_value(min(target,
                                          max(0.0, adj.get_upper() - page)))
                    except Exception:
                        pass
                    return GLib.SOURCE_REMOVE
                GLib.idle_add(_scroll_to_current)

        scroll.set_child(listbox)
        pop.set_child(scroll)

    def _on_entry_chosen(self, _lb: Gtk.ListBox, row: Any) -> None:
        if not hasattr(row, '_path'):
            return
        assert self._toc_pop is not None
        self._toc_pop.popdown()
        self._entry_path = row._path
        self.save_position()
        self.fetch_and_render()
