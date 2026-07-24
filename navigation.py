"""NavigationController — the passage-navigation funnel extracted from
BibleWindow (STRUCTURAL_ANALYSIS.md T2 / Step 4, part 1).

It owns the single `_go_to` funnel every navigation routes through, the
back/forward history stacks (`_nav_back` / `_nav_fwd`), the current location
(`_current_loc`), the recent-passages popover, and the combined book/chapter
reference popover with its chapter and verse grids.

It holds a back-reference to its window and reads the window's header widgets
(book/chapter dropdowns, the ref/back/forward buttons, the two popovers) and
the two panes through the small proxy properties below, so the method bodies
are the inline originals unchanged. The window keeps thin same-named delegates
(and forwarding `_current_loc` / `_nav_back` / `_nav_fwd` properties) so every
navigation, keyboard, button, bookmark, search, and present-mode call site is
untouched.
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
from gtk_utils import clear_children
import sword_bridge
import settings
import module_positions
from a11y import set_accessible_label
import window


class NavigationController:
    _NAV_MAX = 100

    def __init__(self, win):
        self._win = win
        self._nav_back = []
        self._nav_fwd = []
        self._current_loc = ('Genesis', 1)

    # ── Proxy access to window-owned widgets / panes / Today state ───────────
    @property
    def book_drop(self):
        return self._win.book_drop

    @property
    def chapter_drop(self):
        return self._win.chapter_drop

    @property
    def _ref_btn(self):
        return self._win._ref_btn

    @property
    def _back_btn(self):
        return self._win._back_btn

    @property
    def _fwd_btn(self):
        return self._win._fwd_btn

    @property
    def _ref_pop(self):
        return self._win._ref_pop

    @property
    def _recent_pop(self):
        return self._win._recent_pop

    @property
    def pane1(self):
        return self._win.pane1

    @property
    def pane2(self):
        return self._win.pane2

    @property
    def _today_suppress(self):
        return self._win._today_suppress

    @property
    def _dismiss_today(self):
        return self._win._dismiss_today

    # ── The navigation funnel ────────────────────────────────────────────────
    def _go_to(self, book, chapter, verse=None, record=True):
        if book not in window.BOOKS:
            return
        # Any navigation is "an action" — it takes the reader in, so the
        # Today page slides away (unless this is the programmatic startup
        # devotional auto-nav, which happens beneath it).
        if not self._today_suppress:
            self._dismiss_today()
        if record:
            self._push_nav_back(self._current_loc)
            self._nav_fwd.clear()
            self._update_nav_btns()

        self.book_drop.set_selected(window.BOOKS.index(book))
        count = sword_bridge.chapter_count(book)
        # Stale callers (bookmarks, search results from a different
        # versification) may pass a chapter outside this book's range.
        chapter = max(1, min(chapter, count))
        self.chapter_drop.set_model(Gtk.StringList.new([str(i) for i in range(1, count + 1)]))
        self.chapter_drop.set_selected(chapter - 1)

        self._current_loc = (book, chapter)
        self._update_ref_label(book, chapter)

        if record:
            self._push_recent(book, chapter)

        if verse:
            self.pane1.load_reference_at_verse(book, chapter, verse)
            self.pane2.load_reference_at_verse(book, chapter, verse)
        else:
            self.pane1.load_reference(book, chapter)
            self.pane2.load_reference(book, chapter)

    def _push_nav_back(self, loc):
        self._nav_back.append(loc)
        if len(self._nav_back) > self._NAV_MAX:
            del self._nav_back[0]

    def _push_recent(self, book, chapter):
        """Push a (book, chapter) onto the recent-passages list, dedup so
        the same passage never appears twice, cap at 10 entries."""
        cur = settings.get('recent_passages') or []
        if not isinstance(cur, list):
            cur = []
        entry = [book, int(chapter)]
        cur = [e for e in cur if isinstance(e, list) and e[:2] != entry]
        cur.insert(0, entry)
        settings.put('recent_passages', cur[:10])

    def _build_recent_popover_content(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_size_request(220, -1)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(10)
        header_box.set_margin_end(6)
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(6)
        title = Gtk.Label(label=_('Recent'), xalign=0, hexpand=True)
        title.add_css_class('heading')
        header_box.append(title)
        clear_btn = Gtk.Button(icon_name='user-trash-symbolic')
        clear_btn.add_css_class('flat')
        clear_btn.set_tooltip_text(_('Clear recent list'))
        set_accessible_label(clear_btn, _('Clear recent list'))
        clear_btn.connect('clicked', self._on_recent_clear)
        header_box.append(clear_btn)
        outer.append(header_box)
        # No separator rule — grouped by whitespace, matching the search panel
        # and the bookmarks popover so the side surfaces read as a set.

        entries = settings.get('recent_passages') or []
        entries = [e for e in entries if isinstance(e, list) and len(e) >= 2
                   and e[0] in window.BOOKS and isinstance(e[1], int)]

        if not entries:
            empty = Gtk.Label(
                label=_('No recent passages yet.\nNavigate around — they\'ll show here.'),
                xalign=0.5, wrap=True)
            empty.add_css_class('dim-label')
            empty.set_margin_start(12)
            empty.set_margin_end(12)
            empty.set_margin_top(10)
            empty.set_margin_bottom(12)
            outer.append(empty)
        else:
            scroll = Gtk.ScrolledWindow(vexpand=True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_max_content_height(360)
            scroll.set_propagate_natural_height(True)
            listbox = Gtk.ListBox()
            listbox.add_css_class('navigation-sidebar')
            for book, ch in entries:
                row = Gtk.ListBoxRow()
                row._passage = (book, ch)
                lbl = Gtk.Label(label=f'{book_label(book)} {ch}', xalign=0)
                lbl.set_margin_start(12)
                lbl.set_margin_end(12)
                lbl.set_margin_top(6)
                lbl.set_margin_bottom(6)
                row.set_child(lbl)
                listbox.append(row)
            listbox.connect('row-activated', self._on_recent_row_activated)
            scroll.set_child(listbox)
            outer.append(scroll)

        self._recent_pop.set_child(outer)

    def _on_back_history(self, gesture, *_args):
        # Right-click / long-press on the back arrow opens recent passages.
        # Claim the sequence so a long-press doesn't also fire back navigation.
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._recent_pop.popup()

    def _on_recent_row_activated(self, _lb, row):
        if not hasattr(row, '_passage'):
            return
        self._recent_pop.popdown()
        book, ch = row._passage
        self._go_to(book, ch)

    def _on_recent_clear(self, _btn):
        settings.put('recent_passages', [])
        self._build_recent_popover_content()

    def _load_all_panes(self):
        # Source of truth at startup is self._current_loc, which was
        # restored from settings in __init__. Sync the hidden dropdowns
        # (used by Alt+arrow nav and the chapter-count model) to match.
        book, chapter = self._current_loc
        self.book_drop.set_selected(window.BOOKS.index(book))
        # First main-thread SWORD call: join the warm-up thread started in
        # __init__ (a no-op wait by now — _build_ui takes longer than the
        # init), then clamp the restored chapter, deferred from __init__.
        sword_bridge.wait_warm()
        count = sword_bridge.chapter_count(book)
        chapter = max(1, min(chapter, count))
        self._current_loc = (book, chapter)
        self.chapter_drop.set_model(
            Gtk.StringList.new([str(i) for i in range(1, count + 1)]))
        self.chapter_drop.set_selected(chapter - 1)
        self._update_ref_label(book, chapter)
        # Restore per-module scroll positions via the shared
        # module_positions store. Setting _restore_top_verse BEFORE
        # load_reference triggers _fetch_and_render — the render path
        # consumes the attribute and routes through _scroll_to_verse_silent.
        v1 = module_positions.get_verse_position(
            self.pane1._module, book, chapter)
        v2 = module_positions.get_verse_position(
            self.pane2._module, book, chapter)
        if v1:
            self.pane1._restore_top_verse = v1
        if v2:
            self.pane2._restore_top_verse = v2
        self.pane1.load_reference(book, chapter)
        self.pane2.load_reference(book, chapter)

    def _update_ref_label(self, book, chapter):
        self._ref_btn.set_label(f'{book_label(book)} {chapter}')

    def _build_ref_popover_content(self):
        """Books on the left; right column flips between a Chapter grid and
        a Verse grid via a Stack. Left-click on a chapter navigates straight
        to that chapter; right-click slides the panel over to the verse
        picker for that chapter."""
        current_book    = window.BOOKS[self.book_drop.get_selected()]
        current_chapter = self.chapter_drop.get_selected() + 1

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        outer.set_size_request(440, 380)

        # ── Books (left) ──────────────────────────────────────────────────
        book_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        book_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        book_list = Gtk.ListBox()
        book_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        book_list.add_css_class('navigation-sidebar')

        # ── Right column (header + stack) ─────────────────────────────────
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right_col.set_size_request(190, -1)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header_box.set_margin_start(6)
        header_box.set_margin_end(8)
        header_box.set_margin_top(6)
        header_box.set_margin_bottom(4)

        back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        back_btn.add_css_class('flat')
        back_btn.set_tooltip_text(_('Back to chapters'))
        set_accessible_label(back_btn, _('Back to chapters'))
        back_btn.set_visible(False)
        header_box.append(back_btn)

        title_lbl = Gtk.Label(label=_('Chapter'), xalign=0, hexpand=True)
        title_lbl.add_css_class('heading')
        header_box.append(title_lbl)

        right_col.append(header_box)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_transition_duration(150)
        stack.set_vexpand(True)

        # Chapter grid
        chap_scroll = Gtk.ScrolledWindow(vexpand=True)
        chap_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chap_flow = Gtk.FlowBox()
        chap_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        chap_flow.set_min_children_per_line(4)
        chap_flow.set_max_children_per_line(4)
        chap_flow.set_homogeneous(True)
        chap_flow.set_valign(Gtk.Align.START)
        chap_flow.set_margin_start(8)
        chap_flow.set_margin_end(8)
        chap_flow.set_margin_top(8)
        chap_flow.set_margin_bottom(8)
        chap_flow.set_column_spacing(6)
        chap_flow.set_row_spacing(6)
        chap_scroll.set_child(chap_flow)
        stack.add_named(chap_scroll, 'chapters')

        # Verse grid
        verse_scroll = Gtk.ScrolledWindow(vexpand=True)
        verse_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        verse_flow = Gtk.FlowBox()
        verse_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        verse_flow.set_min_children_per_line(5)
        verse_flow.set_max_children_per_line(5)
        verse_flow.set_homogeneous(True)
        verse_flow.set_valign(Gtk.Align.START)
        verse_flow.set_margin_start(8)
        verse_flow.set_margin_end(8)
        verse_flow.set_margin_top(8)
        verse_flow.set_margin_bottom(8)
        verse_flow.set_column_spacing(4)
        verse_flow.set_row_spacing(4)
        verse_scroll.set_child(verse_flow)
        stack.add_named(verse_scroll, 'verses')

        right_col.append(stack)

        state = {'book': current_book, 'chapter': current_chapter}

        def show_chapters():
            title_lbl.set_label(_('Chapter'))
            back_btn.set_visible(False)
            stack.set_visible_child_name('chapters')

        def show_verses(ch):
            # Rebuild verse grid for state.book / ch
            clear_children(verse_flow)
            try:
                v_count = sword_bridge.verse_count(state['book'], ch)
            except Exception:
                v_count = 1
            for v in range(1, v_count + 1):
                vbtn = Gtk.Button(label=str(v))
                vbtn.add_css_class('nav-cell')
                vbtn.add_css_class('flat')
                vbtn.set_valign(Gtk.Align.CENTER)
                vbtn._verse = v
                vbtn.connect('clicked', self._on_ref_verse_chosen, state)
                verse_flow.append(vbtn)
            state['chapter'] = ch
            title_lbl.set_label(_('Chapter {n} Verse').format(n=ch))
            back_btn.set_visible(True)
            stack.set_visible_child_name('verses')

        def rebuild_chapters():
            clear_children(chap_flow)
            try:
                count = sword_bridge.chapter_count(state['book'])
            except Exception:
                count = 1
            for ch in range(1, count + 1):
                btn = Gtk.Button(label=str(ch))
                btn.add_css_class('nav-cell')
                btn.set_valign(Gtk.Align.CENTER)
                if state['book'] == current_book and ch == current_chapter:
                    btn.add_css_class('nav-current')   # filled-accent pill
                else:
                    btn.add_css_class('flat')
                btn.connect('clicked', self._on_ref_chapter_chosen, state)
                btn._chapter = ch
                # Right-click → slide to verse picker for this chapter
                rc = Gtk.GestureClick()
                rc.set_button(Gdk.BUTTON_SECONDARY)
                rc.connect('pressed',
                           lambda g, n, x, y, _c=ch: show_verses(_c))
                btn.add_controller(rc)
                chap_flow.append(btn)

        for name in window.BOOKS:
            row = Gtk.ListBoxRow()
            row._book = name
            lbl = Gtk.Label(label=book_label(name), xalign=0)
            lbl.set_margin_start(12)
            lbl.set_margin_end(12)
            lbl.set_margin_top(6)
            lbl.set_margin_bottom(6)
            row.set_child(lbl)
            book_list.append(row)
            if name == current_book:
                book_list.select_row(row)

        def on_book_row(_lb, row):
            if row is None:
                return
            state['book'] = row._book
            # Switching book resets back to the chapter view.
            show_chapters()
            rebuild_chapters()

        book_list.connect('row-selected', on_book_row)
        back_btn.connect('clicked', lambda _b: show_chapters())

        rebuild_chapters()

        book_scroll.set_child(book_list)
        outer.append(book_scroll)
        nav_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        nav_sep.add_css_class('nav-divider')
        outer.append(nav_sep)
        outer.append(right_col)

        self._ref_pop.set_child(outer)

        GLib.idle_add(lambda: (book_list.get_selected_row()
                               and book_list.get_selected_row().grab_focus()) or False)

    def _on_ref_chapter_chosen(self, btn, state):
        self._ref_pop.popdown()
        self._go_to(state['book'], btn._chapter)

    def _on_ref_verse_chosen(self, btn, state):
        self._ref_pop.popdown()
        self._go_to(state['book'], state['chapter'], btn._verse)

    def _on_ref_btn_scroll(self, _ctrl, _dx, dy):
        # Vertical scroll: down → next chapter, up → previous chapter.
        if dy > 0:
            self._go_next_chapter()
        elif dy < 0:
            self._go_prev_chapter()
        return True

    # ── Back / forward ──────────────────────────────────────────────────────
    def _on_nav_back(self, _btn):
        if not self._nav_back:
            return
        self._nav_fwd.append(self._current_loc)
        book, chapter = self._nav_back.pop()
        self._update_nav_btns()
        self._go_to(book, chapter, record=False)

    def _on_nav_fwd(self, _btn):
        if not self._nav_fwd:
            return
        self._push_nav_back(self._current_loc)
        book, chapter = self._nav_fwd.pop()
        self._update_nav_btns()
        self._go_to(book, chapter, record=False)

    def _update_nav_btns(self):
        self._back_btn.set_sensitive(bool(self._nav_back))
        self._fwd_btn.set_sensitive(bool(self._nav_fwd))

    # ── Keyboard chapter/book navigation ─────────────────────────────────────
    def _go_prev_chapter(self):
        book    = window.BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        if chapter > 1:
            self._go_to(book, chapter - 1)
        elif self.book_drop.get_selected() > 0:
            prev = window.BOOKS[self.book_drop.get_selected() - 1]
            self._go_to(prev, sword_bridge.chapter_count(prev))

    def _go_next_chapter(self):
        book    = window.BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        if chapter < sword_bridge.chapter_count(book):
            self._go_to(book, chapter + 1)
        elif self.book_drop.get_selected() < len(window.BOOKS) - 1:
            self._go_to(window.BOOKS[self.book_drop.get_selected() + 1], 1)

    def _go_prev_book(self):
        idx = self.book_drop.get_selected()
        if idx > 0:
            self._go_to(window.BOOKS[idx - 1], 1)

    def _go_next_book(self):
        idx = self.book_drop.get_selected()
        if idx < len(window.BOOKS) - 1:
            self._go_to(window.BOOKS[idx + 1], 1)
