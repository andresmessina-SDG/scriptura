"""OverlayManager — the in-window overlay lifecycle extracted from BibleWindow
(STRUCTURAL_ANALYSIS.md T2 / Step 4, part 2).

Owns "which overlay is open and how they open, close, and exclude one another":
the mutual-exclusion rule (only one of menu / search / jump visible at a time),
the quick-jump bar (show / hide / activate / parse), the menu-sidebar toggle
(with its deferred first build), and the search-sidebar toggle.

It holds no state of its own — the overlay widgets stay window-owned. It reaches
them, and the panes / Today / plan / present hooks it coordinates, through the
small proxy properties below, so the method bodies are the inline originals
unchanged. The window keeps thin same-named delegates so every action, button,
key-controller, and idle-callback call site is untouched. OverlayManager is
imported lazily in BibleWindow.__init__ because this module imports window for
BOOKS (avoids a load-order cycle).
"""
import re
from gi.repository import GLib
import sword_bridge
import window


class OverlayManager:
    def __init__(self, win):
        self._win = win

    # ── Proxy access to window-owned widgets / panes / hooks ─────────────────
    @property
    def _menu_split(self):
        return self._win._menu_split

    @property
    def _search_split(self):
        return self._win._search_split

    @property
    def _jump_revealer(self):
        return self._win._jump_revealer

    @property
    def _jump_entry(self):
        return self._win._jump_entry

    @property
    def _search_panel(self):
        return self._win._search_panel

    @property
    def pane1(self):
        return self._win.pane1

    @property
    def _menu_panel_built(self):
        return self._win._menu_panel_built

    @_menu_panel_built.setter
    def _menu_panel_built(self, value):
        self._win._menu_panel_built = value

    @property
    def _present_mode(self):
        return getattr(self._win, '_present_mode', False)

    @property
    def _dismiss_today(self):
        return self._win._dismiss_today

    @property
    def _build_menu_panel(self):
        return self._win._build_menu_panel

    @property
    def _refresh_plan_ui(self):
        return self._win._refresh_plan_ui

    @property
    def _present_jump(self):
        return self._win._present_jump

    @property
    def _go_to(self):
        return self._win._go_to

    # ── Mutual exclusion ─────────────────────────────────────────────────────
    def _close_other_overlays(self, keep=None):
        """Dismiss any overlay panels other than the one named in `keep`.
        Only one of menu / search / jump should be visible at a time."""
        if keep != 'menu':
            self._menu_split.set_show_sidebar(False)
        if keep != 'search':
            self._search_split.set_show_sidebar(False)
        if keep != 'jump':
            self._jump_revealer.set_reveal_child(False)

    # ── Quick-jump bar ───────────────────────────────────────────────────────
    def _show_jump(self):
        self._close_other_overlays(keep='jump')
        self._jump_revealer.set_reveal_child(True)
        self._jump_entry.grab_focus()

    def _hide_jump(self):
        self._jump_revealer.set_reveal_child(False)
        self._jump_entry.set_text('')

    def _on_jump_activate(self, entry):
        result = self._parse_jump(entry.get_text().strip())
        if result:
            book, chapter, verse = result
            self._hide_jump()
            if getattr(self, '_present_mode', False):
                self._present_jump(book, chapter, verse)
            else:
                self._go_to(book, chapter, verse)
        else:
            entry.add_css_class('error')
            def clear_err():
                entry.remove_css_class('error')
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(600, clear_err)

    def _parse_jump(self, text):
        text = text.strip()
        if not text:
            return None
        # Book name with optional " chapter[:verse]" — a bare book name defaults to ch 1.
        m = re.match(r'^(.+?)(?:\s+(\d+)(?::(\d+))?)?$', text)
        if not m:
            return None
        try:
            chapter = int(m.group(2)) if m.group(2) else 1
            verse   = int(m.group(3)) if m.group(3) else None
        except ValueError:
            return None
        query = m.group(1).strip().lower().replace(' ', '')
        if not query:
            return None
        # Exact match wins over prefix — "Job" must not silently become "Joshua".
        for b in window.BOOKS:
            if b.lower().replace(' ', '') == query:
                ch_max = sword_bridge.chapter_count(b)
                return (b, max(1, min(chapter, ch_max)), verse)
        for b in window.BOOKS:
            if b.lower().replace(' ', '').startswith(query):
                ch_max = sword_bridge.chapter_count(b)
                return (b, max(1, min(chapter, ch_max)), verse)
        full = sword_bridge._CROSS_REF_ABBREVS.get(query)
        if full and full in window.BOOKS:
            ch_max = sword_bridge.chapter_count(full)
            return (full, max(1, min(chapter, ch_max)), verse)
        return None

    # ── Menu sidebar ─────────────────────────────────────────────────────────
    def _ensure_menu_panel(self):
        """Build the menu sidebar on first need. Deferred out of _build_ui
        so its ~80 ms of widget construction doesn't delay first paint;
        normally the post-init idle gets here before the user can."""
        if not self._menu_panel_built:
            self._menu_panel_built = True
            self._menu_split.set_sidebar(self._build_menu_panel())
        return GLib.SOURCE_REMOVE

    def _toggle_menu(self, _btn):
        open_ = not self._menu_split.get_show_sidebar()
        if open_:
            self._dismiss_today()
            self._ensure_menu_panel()
            self._close_other_overlays(keep='menu')
            self._refresh_plan_ui()
        self._menu_split.set_show_sidebar(open_)

    # ── Search sidebar ───────────────────────────────────────────────────────
    def _on_search_clicked(self, _btn):
        if self._search_split.get_show_sidebar():
            self._search_split.set_show_sidebar(False)
        else:
            self._dismiss_today()
            self._close_other_overlays(keep='search')
            # Default to pane1's module — but fall back to a Bible-text module
            # if pane1 is showing a devotional (search doesn't work on devotionals).
            mod = self.pane1._module
            if self.pane1._is_devotional:
                texts = [m for m in sword_bridge.module_names()
                         if not sword_bridge.is_internal_use(m)
                         and sword_bridge.module_type(m) == 'Biblical Texts']
                if texts:
                    mod = texts[0]
            self._search_panel.prepare_for_show(mod)
            self._search_split.set_show_sidebar(True)

    def _hide_search(self):
        self._search_split.set_show_sidebar(False)
