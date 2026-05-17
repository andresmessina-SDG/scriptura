import re
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')
import datetime
from gi.repository import Gtk, Adw, GLib, Gdk, Pango, PangoCairo
import sword_bridge
import settings
import bookmarks
import reading_plans
from pane import BiblePane
from module_manager import ModuleManagerWindow
from search_panel import SearchPanel
from study_journal import StudyJournalWindow
from crossref_panel import CrossRefPanel


BOOKS = [
    'Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy',
    'Joshua', 'Judges', 'Ruth', '1 Samuel', '2 Samuel',
    '1 Kings', '2 Kings', '1 Chronicles', '2 Chronicles',
    'Ezra', 'Nehemiah', 'Esther', 'Job', 'Psalms', 'Proverbs',
    'Ecclesiastes', 'Song of Solomon', 'Isaiah', 'Jeremiah',
    'Lamentations', 'Ezekiel', 'Daniel', 'Hosea', 'Joel', 'Amos',
    'Obadiah', 'Jonah', 'Micah', 'Nahum', 'Habakkuk', 'Zephaniah',
    'Haggai', 'Zechariah', 'Malachi',
    'Matthew', 'Mark', 'Luke', 'John', 'Acts', 'Romans',
    '1 Corinthians', '2 Corinthians', 'Galatians', 'Ephesians',
    'Philippians', 'Colossians', '1 Thessalonians', '2 Thessalonians',
    '1 Timothy', '2 Timothy', 'Titus', 'Philemon', 'Hebrews',
    'James', '1 Peter', '2 Peter', '1 John', '2 John', '3 John',
    'Jude', 'Revelation',
]


class BibleWindow(Adw.ApplicationWindow):
    _NAV_MAX = 100

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(1100, 700)
        self.set_title('Bible Reader')
        self._nav_back = []
        self._nav_fwd = []
        self._current_loc = ('Genesis', 1)
        self._updating_plan = False
        self._today_row = None
        self._modules_win = None
        self._journal_win = None
        self._hotkeys_win = None
        self._build_ui()
        self._load_all_panes()
        if self._startup_devt_module:
            self._startup_navigate_to_devotional_ref(self._startup_devt_module)
        _scheme_map = {
            'light':   Adw.ColorScheme.FORCE_LIGHT,
            'dark':    Adw.ColorScheme.FORCE_DARK,
            'default': Adw.ColorScheme.DEFAULT,
        }
        Adw.StyleManager.get_default().set_color_scheme(
            _scheme_map.get(settings.get('color_scheme') or 'default',
                            Adw.ColorScheme.DEFAULT))

    def _push_nav_back(self, loc):
        self._nav_back.append(loc)
        if len(self._nav_back) > self._NAV_MAX:
            del self._nav_back[0]

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        self._toolbar_view = toolbar_view

        header = Adw.HeaderBar()
        self._header = header
        toolbar_view.add_top_bar(header)

        # ── Left: burger + back/forward + navigation ──────────────────────────
        burger_btn = Gtk.Button(icon_name='open-menu-symbolic')
        burger_btn.set_tooltip_text('Menu')
        burger_btn.add_css_class('flat')
        burger_btn.connect('clicked', self._toggle_menu)
        header.pack_start(burger_btn)

        self._back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        self._back_btn.set_tooltip_text('Go back (Alt+←)')
        self._back_btn.set_sensitive(False)
        self._back_btn.connect('clicked', self._on_nav_back)
        header.pack_start(self._back_btn)

        self._fwd_btn = Gtk.Button(icon_name='go-next-symbolic')
        self._fwd_btn.set_tooltip_text('Go forward (Alt+→)')
        self._fwd_btn.set_sensitive(False)
        self._fwd_btn.connect('clicked', self._on_nav_fwd)
        header.pack_start(self._fwd_btn)

        # Dropdowns remain as authoritative state holders. Kept in the widget
        # tree but invisible — the combined Book+Chapter popover below drives
        # navigation through the existing _on_book_changed / _on_chapter_changed
        # handlers via _go_to(), so all the existing nav paths still work.
        self.book_drop = Gtk.DropDown(model=Gtk.StringList.new(BOOKS))
        self._book_handler = self.book_drop.connect('notify::selected', self._on_book_changed)
        self.book_drop.set_visible(False)
        header.pack_start(self.book_drop)

        self.chapter_drop = Gtk.DropDown(
            model=Gtk.StringList.new([str(i) for i in range(1, 51)])
        )
        self._chapter_handler = self.chapter_drop.connect('notify::selected', self._on_chapter_changed)
        self.chapter_drop.set_visible(False)
        header.pack_start(self.chapter_drop)

        # Combined Book + Chapter reference button — Apple-Books style.
        self._ref_btn = Gtk.MenuButton()
        self._ref_btn.set_always_show_arrow(True)
        self._ref_btn.add_css_class('flat')
        self._ref_btn.set_tooltip_text('Choose passage')
        self._ref_pop = Gtk.Popover()
        self._ref_pop.set_has_arrow(True)
        self._ref_btn.set_popover(self._ref_pop)
        self._ref_pop.connect('show', lambda _p: self._build_ref_popover_content())
        header.pack_start(self._ref_btn)

        self.lex_toggle = Gtk.ToggleButton()
        lex_lbl = Gtk.Label()
        lex_lbl.set_markup('<span size="x-large">‎א</span><span size="large">Ω</span>')
        self.lex_toggle.set_child(lex_lbl)
        self.lex_toggle.set_tooltip_text("Show/Hide Strong's word links")
        self.lex_toggle.connect('toggled', self._on_lex_toggle)
        header.pack_start(self.lex_toggle)

        # ── Right: search + bookmarks + view toggle ────────────────────────────
        self._bookmark_btn = Gtk.Button(icon_name='bookmark-new-symbolic')
        self._bookmark_btn.set_tooltip_text('Bookmarks')
        self._bookmark_btn.connect('clicked', self._on_bookmark_clicked)
        header.pack_end(self._bookmark_btn)

        search_btn = Gtk.Button(icon_name='system-search-symbolic')
        search_btn.set_tooltip_text('Search')
        search_btn.connect('clicked', self._on_search_clicked)
        header.pack_end(search_btn)

        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        view_box.add_css_class('linked')
        self._btn_single = Gtk.ToggleButton(icon_name='view-paged-symbolic')
        self._btn_single.set_tooltip_text('Single pane')
        self._btn_split = Gtk.ToggleButton(icon_name='view-dual-symbolic')
        self._btn_split.set_tooltip_text('Split pane')
        self._btn_split.set_active(True)
        self._btn_single.set_group(self._btn_split)
        self._btn_single.connect('toggled', self._on_view_mode)
        self._btn_split.connect('toggled', self._on_view_mode)
        view_box.append(self._btn_single)
        view_box.append(self._btn_split)
        header.pack_end(view_box)

        # ── Panes ─────────────────────────────────────────────────────────────
        sword_names = sword_bridge.module_names()
        import ebible_bridge as _eb
        all_names = sword_names + _eb.module_names()

        default_mod  = settings.get('default_module')
        startup_devt = settings.get('startup_devotional')

        # Pick pane1 module: saved default → first available
        p1_mod = default_mod if default_mod and default_mod in all_names \
                 else (sword_names[0] if sword_names else None)

        # Pick pane2 module: saved devotional → auto-detect installed devotional
        if not startup_devt or startup_devt not in sword_names:
            devots = sword_bridge.installed_devotional_modules()
            startup_devt = devots[0] if devots else None
        p2_mod = startup_devt if startup_devt else p1_mod
        self._startup_devt_module = startup_devt

        self.pane1 = BiblePane(module_name=p1_mod,
                               on_word_click=self._on_word_click,
                               on_click_outside_search=self._hide_search,
                               on_verse_select=self._on_verse_select,
                               on_word_study_navigate=self._on_word_study_nav,
                               on_toast=self._toast)
        self.pane2 = BiblePane(module_name=p2_mod,
                               on_word_click=self._on_word_click,
                               on_click_outside_search=self._hide_search,
                               on_verse_select=self._on_verse_select,
                               on_word_study_navigate=self._on_word_study_nav,
                               on_toast=self._toast)

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                                vexpand=True, hexpand=True)
        self._paned.set_start_child(self.pane1)
        self._paned.set_end_child(self.pane2)
        self._paned.set_resize_start_child(True)
        self._paned.set_resize_end_child(True)
        self._paned.set_shrink_start_child(False)
        self._paned.set_shrink_end_child(False)

        # ── Search overlay ────────────────────────────────────────────────────
        self._search_panel = SearchPanel(
            on_result_clicked=self._on_search_result,
            on_close=self._hide_search,
        )
        search_handle = Gtk.Box()
        search_handle.add_css_class('resize-handle')
        search_wrapper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        search_wrapper.append(search_handle)
        search_wrapper.append(self._search_panel)

        self._search_revealer = Gtk.Revealer()
        self._search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self._search_revealer.set_transition_duration(200)
        self._search_revealer.set_halign(Gtk.Align.END)
        self._search_revealer.set_vexpand(True)
        self._search_revealer.set_child(search_wrapper)

        # ── Quick jump overlay ────────────────────────────────────────────────
        self._jump_entry = Gtk.SearchEntry()
        self._jump_entry.set_placeholder_text('Go to… (e.g. John 3:16)')
        self._jump_entry.set_size_request(320, -1)
        self._jump_entry.connect('activate', self._on_jump_activate)
        self._jump_entry.connect('stop-search', lambda _: self._hide_jump())

        jump_wrap = Gtk.Box()
        jump_wrap.set_halign(Gtk.Align.CENTER)
        jump_wrap.set_margin_top(8)
        jump_wrap.add_css_class('card')
        jump_wrap.append(self._jump_entry)

        self._jump_revealer = Gtk.Revealer()
        self._jump_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._jump_revealer.set_transition_duration(150)
        self._jump_revealer.set_halign(Gtk.Align.CENTER)
        self._jump_revealer.set_valign(Gtk.Align.START)
        self._jump_revealer.set_child(jump_wrap)

        # ── App menu panel (right-side revealer) ─────────────────────────────
        menu_css = b"""
.menu-panel { background-color: @card_bg_color;
              border: 2px solid @accent_color;
              border-radius: 0 12px 0 0;
              box-shadow: 4px 0 16px alpha(black, 0.35); }
row.plan-today { background-color: alpha(@accent_bg_color, 0.18); }
.resize-handle { background-color: transparent; min-width: 6px; }
.resize-handle:hover { background-color: alpha(@borders, 0.25); }
.key-chip { background-color: alpha(@borders, 0.5); border-radius: 5px;
            padding: 2px 8px; font-family: monospace; font-weight: bold; }

/* Lexicon + Word-study panel styling */
.lex-panel {
    border-top: 2px solid alpha(@accent_color, 0.45);
}
.lex-header {
    background-color: alpha(@card_bg_color, 0.6);
    border-bottom: 1px solid alpha(@borders, 0.4);
}
.ws-panel {
    border-left: 1px solid alpha(@borders, 0.4);
}
.ws-header {
    background-color: alpha(@accent_color, 0.12);
    color: @accent_color;
    font-weight: 600;
    padding: 8px 14px;
    border-bottom: 1px solid alpha(@borders, 0.4);
}
"""
        _mp = Gtk.CssProvider()
        _mp.load_from_data(menu_css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _mp, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._menu_revealer = Gtk.Revealer()
        self._menu_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self._menu_revealer.set_transition_duration(200)
        self._menu_revealer.set_halign(Gtk.Align.START)
        self._menu_revealer.set_vexpand(True)
        menu_panel_body, menu_handle = self._build_menu_panel()
        self._menu_revealer.set_child(menu_panel_body)
        self._setup_resize_handle(menu_handle, self._menu_panel_box, left_panel=True)
        self._setup_resize_handle(search_handle, self._search_panel, left_panel=False)

        # ── Cross-reference panel ─────────────────────────────────────────────
        self._crossref_panel = CrossRefPanel(
            on_ref_clicked=self._on_crossref_clicked,
            on_close=self._hide_crossref,
            on_ref_right_clicked=self._on_crossref_right_clicked,
        )
        self._crossref_revealer = Gtk.Revealer()
        self._crossref_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._crossref_revealer.set_transition_duration(200)
        self._crossref_revealer.set_child(self._crossref_panel)

        # Paned + crossref form the base content; overlay panels float above both
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(self._paned)
        main_box.append(self._crossref_revealer)

        overlay = Gtk.Overlay(vexpand=True, hexpand=True)
        overlay.set_child(main_box)
        overlay.add_overlay(self._search_revealer)
        overlay.add_overlay(self._jump_revealer)
        overlay.add_overlay(self._menu_revealer)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(overlay)
        toolbar_view.set_content(self._toast_overlay)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self._on_key_press)
        self.add_controller(key_controller)

        self._update_ref_label(*self._current_loc)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def _on_key_press(self, controller, keyval, keycode, state):
        alt  = bool(state & Gdk.ModifierType.ALT_MASK)
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if keyval == Gdk.KEY_Escape:
            if self._jump_revealer.get_reveal_child():
                self._hide_jump()
                return True
            if self._search_revealer.get_reveal_child():
                self._hide_search()
                return True
            if self._menu_revealer.get_reveal_child():
                self._menu_revealer.set_reveal_child(False)
                return True
            if getattr(self, '_reading_mode', False):
                self._set_reading_mode(False)
                return True
            return False

        if keyval == Gdk.KEY_F11:
            self._set_reading_mode(not getattr(self, '_reading_mode', False))
            return True

        if ctrl:
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
                self._adjust_font_size(1.0)
                return True
            if keyval == Gdk.KEY_minus:
                self._adjust_font_size(-1.0)
                return True
            if keyval == Gdk.KEY_l:
                self._show_jump()
                return True
            if keyval == Gdk.KEY_f:
                self._on_search_clicked(None)
                return True

        if alt:
            if keyval == Gdk.KEY_Left:
                self._go_prev_chapter()
                return True
            if keyval == Gdk.KEY_Right:
                self._go_next_chapter()
                return True
            if keyval == Gdk.KEY_Up:
                self._go_prev_book()
                return True
            if keyval == Gdk.KEY_Down:
                self._go_next_book()
                return True

        return False

    # ── Central navigation ────────────────────────────────────────────────────

    def _go_to(self, book, chapter, verse=None, record=True):
        if book not in BOOKS:
            return
        if record:
            self._push_nav_back(self._current_loc)
            self._nav_fwd.clear()
            self._update_nav_btns()

        self.book_drop.disconnect(self._book_handler)
        self.chapter_drop.disconnect(self._chapter_handler)
        try:
            self.book_drop.set_selected(BOOKS.index(book))
            count = sword_bridge.chapter_count(book)
            self.chapter_drop.set_model(Gtk.StringList.new([str(i) for i in range(1, count + 1)]))
            self.chapter_drop.set_selected(chapter - 1)
        finally:
            # Reconnect even on failure — otherwise dropdowns become permanently inert.
            self._book_handler  = self.book_drop.connect('notify::selected', self._on_book_changed)
            self._chapter_handler = self.chapter_drop.connect('notify::selected', self._on_chapter_changed)

        self._current_loc = (book, chapter)
        self._update_ref_label(book, chapter)

        if verse:
            self.pane1.load_reference_at_verse(book, chapter, verse)
            self.pane2.load_reference_at_verse(book, chapter, verse)
        else:
            self.pane1.load_reference(book, chapter)
            self.pane2.load_reference(book, chapter)

    def _load_all_panes(self):
        book    = BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        self._update_ref_label(book, chapter)
        self.pane1.load_reference(book, chapter)
        self.pane2.load_reference(book, chapter)

    def _update_ref_label(self, book, chapter):
        self._ref_btn.set_label(f'{book} {chapter}')

    def _build_ref_popover_content(self):
        """Build the side-by-side Book/Chapter selector each time the popover opens."""
        current_book    = BOOKS[self.book_drop.get_selected()]
        current_chapter = self.chapter_drop.get_selected() + 1

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        outer.set_size_request(420, 360)

        # Book list (left)
        book_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        book_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        book_list = Gtk.ListBox()
        book_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        book_list.add_css_class('navigation-sidebar')

        # Chapter grid (right)
        chap_scroll = Gtk.ScrolledWindow(vexpand=True)
        chap_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chap_scroll.set_size_request(150, -1)
        chap_flow = Gtk.FlowBox()
        chap_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        chap_flow.set_min_children_per_line(4)
        chap_flow.set_max_children_per_line(4)
        chap_flow.set_homogeneous(True)
        chap_flow.set_margin_start(8)
        chap_flow.set_margin_end(8)
        chap_flow.set_margin_top(8)
        chap_flow.set_margin_bottom(8)
        chap_flow.set_column_spacing(6)
        chap_flow.set_row_spacing(6)

        # State for the popover
        state = {'book': current_book}

        def rebuild_chapters():
            child = chap_flow.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                chap_flow.remove(child)
                child = nxt
            try:
                count = sword_bridge.chapter_count(state['book'])
            except Exception:
                count = 1
            for ch in range(1, count + 1):
                btn = Gtk.Button(label=str(ch))
                btn.add_css_class('flat')
                if state['book'] == current_book and ch == current_chapter:
                    btn.add_css_class('suggested-action')
                btn.connect('clicked', self._on_ref_chapter_chosen, state)
                btn._chapter = ch
                chap_flow.append(btn)

        for i, name in enumerate(BOOKS):
            row = Gtk.ListBoxRow()
            row._book = name
            lbl = Gtk.Label(label=name, xalign=0)
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
            rebuild_chapters()

        book_list.connect('row-selected', on_book_row)

        rebuild_chapters()

        book_scroll.set_child(book_list)
        chap_scroll.set_child(chap_flow)
        outer.append(book_scroll)
        outer.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        outer.append(chap_scroll)

        self._ref_pop.set_child(outer)

        # Scroll the selected book into view after the popover lays out
        GLib.idle_add(lambda: (book_list.get_selected_row()
                               and book_list.get_selected_row().grab_focus()) or False)

    def _on_ref_chapter_chosen(self, btn, state):
        self._ref_pop.popdown()
        self._go_to(state['book'], btn._chapter)

    def _startup_navigate_to_devotional_ref(self, devt_module):
        """Background thread: parse today's devotional, navigate pane1 to its passage."""
        import datetime as _dt
        date_obj = _dt.date.today()
        def fetch():
            raw    = sword_bridge.get_devotional_raw(devt_module, date_obj)
            result = sword_bridge.parse_devotional_refs(raw)
            if result:
                book, chapter, verse = result
                GLib.idle_add(self._go_to, book, chapter, verse, False)
        threading.Thread(target=fetch, daemon=True).start()

    def _on_book_changed(self, drop, _param):
        book = BOOKS[drop.get_selected()]
        self._push_nav_back(self._current_loc)
        self._nav_fwd.clear()
        self._update_nav_btns()

        count = sword_bridge.chapter_count(book)
        self.chapter_drop.disconnect(self._chapter_handler)
        self.chapter_drop.set_model(Gtk.StringList.new([str(i) for i in range(1, count + 1)]))
        self.chapter_drop.set_selected(0)
        self._chapter_handler = self.chapter_drop.connect('notify::selected', self._on_chapter_changed)

        self._current_loc = (book, 1)
        self._load_all_panes()

    def _on_chapter_changed(self, _drop, _param):
        book    = BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        self._push_nav_back(self._current_loc)
        self._nav_fwd.clear()
        self._update_nav_btns()
        self._current_loc = (book, chapter)
        self._load_all_panes()

    # ── Back / forward ────────────────────────────────────────────────────────

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
        book    = BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        if chapter > 1:
            self._go_to(book, chapter - 1)
        elif self.book_drop.get_selected() > 0:
            prev = BOOKS[self.book_drop.get_selected() - 1]
            self._go_to(prev, sword_bridge.chapter_count(prev))

    def _go_next_chapter(self):
        book    = BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        if chapter < sword_bridge.chapter_count(book):
            self._go_to(book, chapter + 1)
        elif self.book_drop.get_selected() < len(BOOKS) - 1:
            self._go_to(BOOKS[self.book_drop.get_selected() + 1], 1)

    def _go_prev_book(self):
        idx = self.book_drop.get_selected()
        if idx > 0:
            self._go_to(BOOKS[idx - 1], 1)

    def _go_next_book(self):
        idx = self.book_drop.get_selected()
        if idx < len(BOOKS) - 1:
            self._go_to(BOOKS[idx + 1], 1)

    # ── Font size ─────────────────────────────────────────────────────────────

    def _adjust_font_size(self, delta):
        new_size = max(8.0, min(26.0, settings.get('font_size') + delta))
        settings.put('font_size', new_size)
        self.pane1.set_appearance(font_size=new_size)
        self.pane2.set_appearance(font_size=new_size)
        if hasattr(self, '_size_scale'):
            self._size_scale.set_value(new_size)
            self._size_val_lbl.set_text(f'{new_size:.0f}pt')

    def _toggle_appear_card(self, _btn):
        open_ = not self._appear_revealer.get_reveal_child()
        self._appear_revealer.set_reveal_child(open_)
        self._appear_arrow.set_from_icon_name(
            'pan-down-symbolic' if open_ else 'pan-end-symbolic')
        if open_:
            self._appear_btn.remove_css_class('flat')
            self._appear_btn.add_css_class('suggested-action')
        else:
            self._appear_btn.remove_css_class('suggested-action')
            self._appear_btn.add_css_class('flat')

    def _on_appear_font(self, drop, _):
        idx = drop.get_selected()
        family = self._font_css_names[idx] if idx < len(self._font_css_names) else 'serif'
        settings.put('font_family', family)
        self.pane1.set_appearance(font_family=family)
        self.pane2.set_appearance(font_family=family)

    def _current_mode_key(self):
        return f'text_color_{settings.get("color_scheme") or "default"}'

    def _apply_mode_color(self):
        color = settings.get(self._current_mode_key())
        self._color_check.set_active(bool(color))
        self._color_btn.set_sensitive(bool(color))
        if color:
            rgba = Gdk.RGBA()
            if rgba.parse(color):
                self._color_btn.set_rgba(rgba)
        self.pane1.set_appearance(text_color=color)
        self.pane2.set_appearance(text_color=color)

    def _on_appear_theme(self, btn):
        self._theme_light.set_active(btn is self._theme_light)
        self._theme_dark.set_active(btn is self._theme_dark)
        self._theme_system.set_active(btn is self._theme_system)
        if btn is self._theme_light:
            scheme, adw = 'light', Adw.ColorScheme.FORCE_LIGHT
        elif btn is self._theme_dark:
            scheme, adw = 'dark', Adw.ColorScheme.FORCE_DARK
        else:
            scheme, adw = 'default', Adw.ColorScheme.DEFAULT
        settings.put('color_scheme', scheme)
        Adw.StyleManager.get_default().set_color_scheme(adw)
        self._apply_mode_color()

    def _on_color_check(self, btn):
        enabled = btn.get_active()
        self._color_btn.set_sensitive(enabled)
        if not enabled:
            settings.put(self._current_mode_key(), None)
            self.pane1.set_appearance(text_color=None)
            self.pane2.set_appearance(text_color=None)
        else:
            self._on_color_changed(self._color_btn)

    def _on_color_changed(self, btn):
        if not self._color_check.get_active():
            return
        rgba = btn.get_rgba()
        color = (f'#{round(rgba.red*255):02x}'
                 f'{round(rgba.green*255):02x}'
                 f'{round(rgba.blue*255):02x}')
        settings.put(self._current_mode_key(), color)
        self.pane1.set_appearance(text_color=color)
        self.pane2.set_appearance(text_color=color)

    def _on_appear_size(self, scale):
        size = round(scale.get_value(), 1)
        settings.put('font_size', size)
        self._size_val_lbl.set_text(f'{size:.0f}pt')
        self.pane1.set_appearance(font_size=size)
        self.pane2.set_appearance(font_size=size)

    def _on_appear_spacing(self, scale):
        val = round(scale.get_value(), 1)
        settings.put('line_spacing', val)
        self._spacing_val_lbl.set_text(f'{val:.1f}×')
        self.pane1.set_appearance(line_spacing=val)
        self.pane2.set_appearance(line_spacing=val)

    def _on_appear_bold(self, btn):
        bold = btn.get_active()
        settings.put('font_bold', bold)
        self.pane1.set_appearance(font_bold=bold)
        self.pane2.set_appearance(font_bold=bold)

    def _on_appear_justify(self, btn):
        justify = btn.get_active()
        settings.put('font_justify', justify)
        self.pane1.set_appearance(font_justify=justify)
        self.pane2.set_appearance(font_justify=justify)

    def _on_default_mod_changed(self, drop, _param):
        opts = drop.get_model()
        idx  = drop.get_selected()
        val  = opts.get_string(idx) if idx > 0 else None
        settings.put('default_module', val)

    def _on_devot_changed(self, drop, _param):
        opts = drop.get_model()
        idx  = drop.get_selected()
        val  = opts.get_string(idx) if idx > 0 else None
        settings.put('startup_devotional', val)

    # ── Quick jump ────────────────────────────────────────────────────────────

    def _close_other_overlays(self, keep=None):
        """Dismiss any overlay panels other than the one named in `keep`.
        Only one of menu / search / jump should be visible at a time."""
        if keep != 'menu':
            self._menu_revealer.set_reveal_child(False)
        if keep != 'search':
            self._search_revealer.set_reveal_child(False)
        if keep != 'jump':
            self._jump_revealer.set_reveal_child(False)

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
        for b in BOOKS:
            if b.lower().replace(' ', '') == query:
                ch_max = sword_bridge.chapter_count(b)
                return (b, max(1, min(chapter, ch_max)), verse)
        for b in BOOKS:
            if b.lower().replace(' ', '').startswith(query):
                ch_max = sword_bridge.chapter_count(b)
                return (b, max(1, min(chapter, ch_max)), verse)
        full = sword_bridge._CROSS_REF_ABBREVS.get(query)
        if full and full in BOOKS:
            ch_max = sword_bridge.chapter_count(full)
            return (full, max(1, min(chapter, ch_max)), verse)
        return None

    # ── Bookmarks ─────────────────────────────────────────────────────────────

    def _on_bookmark_clicked(self, _btn):
        popover = Gtk.Popover()
        popover.set_parent(self._bookmark_btn)
        # Popovers using set_parent must be explicitly unparented in GTK4,
        # otherwise they accumulate as hidden children on each click.
        popover.connect('closed', lambda p: p.unparent())
        popover.set_child(self._build_bookmark_content(popover))
        popover.popup()

    def _build_bookmark_content(self, popover):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_size_request(260, -1)

        book    = BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        add_btn = Gtk.Button()
        add_btn.set_child(Adw.ButtonContent(
            icon_name='starred-symbolic', label=f'Add {book} {chapter}'))
        add_btn.add_css_class('suggested-action')
        add_btn.connect('clicked', self._add_bookmark, book, chapter, popover)
        box.append(add_btn)

        bmarks = bookmarks.get_all()
        if bmarks:
            box.append(Gtk.Separator())
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_max_content_height(280)
            scroll.set_propagate_natural_height(True)
            blist = Gtk.ListBox()
            blist.set_selection_mode(Gtk.SelectionMode.NONE)
            blist.add_css_class('boxed-list')
            for i, bm in enumerate(bmarks):
                row = Gtk.ListBoxRow()
                rb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                rb.set_margin_start(6)
                rb.set_margin_top(4)
                rb.set_margin_bottom(4)
                lbl = Gtk.Button(label=bm['label'], hexpand=True)
                lbl.add_css_class('flat')
                lbl.connect('clicked', self._go_to_bookmark, bm, popover)
                del_btn = Gtk.Button(icon_name='edit-delete-symbolic')
                del_btn.add_css_class('flat')
                del_btn.connect('clicked', self._remove_bookmark, i, popover)
                rb.append(lbl)
                rb.append(del_btn)
                row.set_child(rb)
                blist.append(row)
            scroll.set_child(blist)
            box.append(scroll)
        return box

    def _add_bookmark(self, _btn, book, chapter, popover):
        bookmarks.add(book, chapter)
        popover.popdown()
        self._toast(f'Bookmarked {book} {chapter}')

    def _go_to_bookmark(self, _btn, bm, popover):
        popover.popdown()
        self._go_to(bm['book'], bm['chapter'], bm.get('verse'))

    def _remove_bookmark(self, _btn, index, popover):
        bookmarks.remove(index)
        popover.popdown()
        self._toast('Bookmark removed')

    def _toast(self, message):
        t = Adw.Toast.new(message)
        t.set_timeout(2)
        self._toast_overlay.add_toast(t)

    def _set_reading_mode(self, on):
        """Distraction-free mode: hide the window header, pane toolbars, and
        any open overlay panels. Esc or F11 toggles back."""
        self._reading_mode = bool(on)
        self._header.set_visible(not on)
        self.pane1._toolbar.set_visible(not on)
        self.pane2._toolbar.set_visible(not on)
        if on:
            # Dismiss anything floating so the text stands alone
            self._menu_revealer.set_reveal_child(False)
            self._search_revealer.set_reveal_child(False)
            self._jump_revealer.set_reveal_child(False)
            self._crossref_revealer.set_reveal_child(False)
            self._toast('Reading mode — Esc or F11 to exit')

    # ── Lexicon toggle ────────────────────────────────────────────────────────

    def _on_lex_toggle(self, _btn):
        enabled = self.lex_toggle.get_active()
        self.pane1.set_lexicon_enabled(enabled)
        self.pane2.set_lexicon_enabled(enabled)

    def _on_view_mode(self, _btn):
        self.pane2.set_visible(self._btn_split.get_active())

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search_clicked(self, _btn):
        if self._search_revealer.get_reveal_child():
            self._search_revealer.set_reveal_child(False)
        else:
            self._close_other_overlays(keep='search')
            # Default to pane1's module — but fall back to a Bible-text module
            # if pane1 is showing a devotional (search doesn't work on devotionals).
            mod = self.pane1._module
            if self.pane1._is_devotional:
                texts = [m for m in sword_bridge.module_names()
                         if sword_bridge.module_type(m) == 'Biblical Texts']
                if texts:
                    mod = texts[0]
            self._search_panel.prepare_for_show(mod)
            self._search_revealer.set_reveal_child(True)

    def _hide_search(self):
        self._search_revealer.set_reveal_child(False)

    def _on_search_result(self, book, chapter, verse):
        self._go_to(book, chapter, verse)

    # ── Verse select / cross-references ──────────────────────────────────────

    def _on_verse_select(self, source_pane, verse_num):
        for pane in [self.pane1, self.pane2]:
            if pane is not source_pane:
                pane.select_verse(verse_num)
        if source_pane._book and source_pane._chapter:
            self._crossref_panel.load(source_pane._book, source_pane._chapter, verse_num)
            self._crossref_revealer.set_reveal_child(True)

    def _on_crossref_clicked(self, book, chapter, verse):
        if book not in BOOKS:
            return
        # Prefer pane2 in split view, but fall back to pane1 if pane2 is hidden
        # or showing a devotional (which ignores book/chapter navigation).
        if self.pane2.get_visible() and not self.pane2._is_devotional:
            target = self.pane2
        else:
            target = self.pane1
        target.force_navigate(book, chapter, verse)

    def _on_crossref_right_clicked(self, book, chapter, verse, widget):
        if book not in BOOKS:
            return
        popover = Gtk.Popover()
        popover.set_parent(widget)
        popover.connect('closed', lambda p: p.unparent())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        ref_lbl = Gtk.Label(label=f'{book} {chapter}:{verse}', xalign=0)
        ref_lbl.add_css_class('dim-label')
        ref_lbl.add_css_class('caption')
        ref_lbl.set_margin_bottom(4)
        box.append(ref_lbl)
        box.append(Gtk.Separator())

        btn1 = Gtk.Button(label='Open in Pane 1')
        btn1.add_css_class('flat')
        btn1.connect('clicked', lambda _: (popover.popdown(),
                                           self.pane1.force_navigate(book, chapter, verse)))
        box.append(btn1)

        btn2 = Gtk.Button(label='Open in Pane 2')
        btn2.add_css_class('flat')
        if not self.pane2.get_visible():
            btn2.set_sensitive(False)
            btn2.set_tooltip_text('Switch to split view to use Pane 2')
        elif self.pane2._is_devotional:
            btn2.set_sensitive(False)
            btn2.set_tooltip_text('Pane 2 is showing a devotional')
        else:
            btn2.connect('clicked', lambda _: (popover.popdown(),
                                               self.pane2.force_navigate(book, chapter, verse)))
        box.append(btn2)

        popover.set_child(box)
        popover.popup()

    def _hide_crossref(self):
        self._crossref_revealer.set_reveal_child(False)

    # ── Journal ───────────────────────────────────────────────────────────────

    def _on_journal_clicked(self, _btn):
        if self._journal_win is not None and self._journal_win.get_visible():
            self._journal_win.present()
            return
        self._journal_win = StudyJournalWindow(
            on_navigate=self._on_journal_navigate,
            on_annotation_changed=self._refresh_panes,
            transient_for=self,
            modal=False,
        )
        self._attach_esc_close(self._journal_win, '_journal_win')
        self._journal_win.present()

    def _refresh_panes(self):
        self.pane1._fetch_and_render(keep_scroll=True)
        if self._paned.get_end_child().get_visible():
            self.pane2._fetch_and_render(keep_scroll=True)

    def _on_journal_navigate(self, module, book, chapter, verse):
        self._go_to(book, chapter, verse)

    # ── Modules ───────────────────────────────────────────────────────────────

    def _attach_esc_close(self, win, slot_name=None):
        ctrl = Gtk.EventControllerKey.new()
        ctrl.connect('key-pressed',
            lambda c, kv, kc, s: win.close() or True if kv == Gdk.KEY_Escape else False)
        win.add_controller(ctrl)
        # Clear the slot on `self` when the window closes, so the next open
        # creates a fresh window instead of presenting a destroyed one.
        if slot_name:
            def _clear(_w):
                if getattr(self, slot_name, None) is win:
                    setattr(self, slot_name, None)
                return False
            win.connect('close-request', _clear)

    def _on_hotkeys_clicked(self, _btn):
        if self._hotkeys_win is not None and self._hotkeys_win.get_visible():
            self._hotkeys_win.present()
            return
        self._hotkeys_win = self._build_hotkeys_window()
        self._attach_esc_close(self._hotkeys_win, '_hotkeys_win')
        self._hotkeys_win.present()

    _HOTKEYS = [
        ('Navigation', [
            ('Ctrl+L',      'Quick jump to any reference (e.g. John 3:16)'),
            ('Alt+Left',    'Previous chapter'),
            ('Alt+Right',   'Next chapter'),
            ('Alt+Up',      'Previous book'),
            ('Alt+Down',    'Next book'),
        ]),
        ('Search & View', [
            ('Ctrl+F',      'Open / close search panel'),
            ('Ctrl+ +',     'Increase font size'),
            ('Ctrl+ -',     'Decrease font size'),
            ('Escape',      'Close search, jump bar, or menu'),
        ]),
    ]

    def _build_hotkeys_window(self):
        win = Adw.Window(transient_for=self, modal=False)
        win.set_title('Keyboard Shortcuts')
        win.set_default_size(560, 320)

        toolbar_view = Adw.ToolbarView()
        win.set_content(toolbar_view)
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=32)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        outer.set_margin_top(20)
        outer.set_margin_bottom(24)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)

        for section, bindings in self._HOTKEYS:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            col.set_hexpand(True)

            heading = Gtk.Label(label=section, xalign=0)
            heading.add_css_class('heading')
            col.append(heading)
            col.append(Gtk.Separator())

            for keys, desc in bindings:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                key_lbl = Gtk.Label(label=keys, xalign=0)
                key_lbl.add_css_class('key-chip')
                key_lbl.set_size_request(110, -1)
                desc_lbl = Gtk.Label(label=desc, xalign=0, hexpand=True, wrap=True)
                desc_lbl.add_css_class('dim-label')
                row.append(key_lbl)
                row.append(desc_lbl)
                col.append(row)

            outer.append(col)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(outer)
        toolbar_view.set_content(scroll)
        return win

    def _on_modules_clicked(self, _btn):
        if self._modules_win is not None and self._modules_win.get_visible():
            self._modules_win.present()
            return
        self._modules_win = ModuleManagerWindow(
            on_modules_changed=self._on_modules_changed,
            transient_for=self,
            modal=False,
        )
        self._attach_esc_close(self._modules_win, '_modules_win')
        self._modules_win.present()

    def _on_modules_changed(self):
        self.pane1.refresh_modules()
        self.pane2.refresh_modules()

    # ── Lexicon word click ────────────────────────────────────────────────────

    def _on_word_study_nav(self, book, chapter, verse):
        self._go_to(book, chapter, verse)

    def _on_word_click(self, source_pane, strong_num):
        book    = source_pane._book
        chapter = source_pane._chapter
        verse   = source_pane._selected_verse
        has_morph = bool(source_pane._current_morph)

        def fetch():
            text = sword_bridge.lookup_strong(strong_num)
            if not has_morph and verse:
                if strong_num.startswith('G'):
                    morph = sword_bridge.lookup_morph_for_strong(book, chapter, verse, strong_num)
                else:
                    morph = sword_bridge.lookup_morph_for_strong_heb(book, chapter, verse, strong_num)
                source_pane._current_morph = morph
            GLib.idle_add(self._show_lexicon, source_pane, strong_num, text)
        threading.Thread(target=fetch, daemon=True).start()

    def _show_lexicon(self, source_pane, strong_num, text):
        if text:
            source_pane.show_lexicon(strong_num, text)
        else:
            source_pane.show_lexicon(strong_num,
                "Install StrongsGreek or StrongsHebrew from the Module Manager.")
        return GLib.SOURCE_REMOVE

    # ── App menu panel ────────────────────────────────────────────────────────

    def _setup_resize_handle(self, handle, target, left_panel):
        handle.set_cursor(Gdk.Cursor.new_from_name('ew-resize'))

        start_w = [0]
        latest_w = [340]
        pending = [False]

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        # BUBBLE phase (default): fires after children, so AdwHeaderBar handles
        # title-bar drags first — GNOME Shell can snap the window normally.
        # Window-level coords are stable even as the panel/handle moves during resize.

        def on_begin(g, start_x, start_y):
            pos = handle.translate_coordinates(self, 0, 0)
            if pos is None:
                g.set_state(Gtk.EventSequenceState.DENIED)
                return
            hx, hy = pos
            if not (hx <= start_x <= hx + handle.get_width()
                    and hy <= start_y <= hy + handle.get_height()):
                g.set_state(Gtk.EventSequenceState.DENIED)
                return
            w = target.get_width()
            start_w[0] = w if w > 0 else (target.get_size_request()[0] or 340)
            latest_w[0] = start_w[0]
            g.set_state(Gtk.EventSequenceState.CLAIMED)

        def on_update(g, offset_x, offset_y):
            delta = offset_x if left_panel else -offset_x
            latest_w[0] = max(240, min(700, int(start_w[0] + delta)))
            if not pending[0]:
                pending[0] = True
                def apply():
                    target.set_size_request(latest_w[0], -1)
                    pending[0] = False
                    return GLib.SOURCE_REMOVE
                GLib.idle_add(apply)

        drag.connect('drag-begin', on_begin)
        drag.connect('drag-update', on_update)
        self.add_controller(drag)

    def _toggle_menu(self, _btn):
        open_ = not self._menu_revealer.get_reveal_child()
        if open_:
            self._close_other_overlays(keep='menu')
            self._refresh_plan_ui()
        self._menu_revealer.set_reveal_child(open_)

    def _build_menu_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.set_size_request(340, -1)
        panel.add_css_class('menu-panel')
        self._menu_panel_box = panel

        # header row
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hbox.set_margin_start(12)
        hbox.set_margin_end(8)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        title = Gtk.Label(label='Menu', hexpand=True)
        title.set_xalign(0)
        title.add_css_class('title-4')
        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.connect('clicked', lambda _: self._menu_revealer.set_reveal_child(False))
        hbox.append(title)
        hbox.append(close_btn)
        panel.append(hbox)
        panel.append(Gtk.Separator())

        # Scrollable body — everything below the header lives here
        _body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _body_scroll = Gtk.ScrolledWindow(vexpand=True)
        _body_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        _body_scroll.set_child(_body)
        panel.append(_body_scroll)

        # top nav buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          homogeneous=True)
        btn_box.set_margin_start(12)
        btn_box.set_margin_end(12)
        btn_box.set_margin_top(12)
        btn_box.set_margin_bottom(12)
        for icon, label, handler in [
            ('accessories-text-editor-symbolic', 'Study Journal', self._on_journal_clicked),
            ('application-x-addon-symbolic',     'Modules',       self._on_modules_clicked),
        ]:
            btn = Gtk.Button()
            bx = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            bx.set_halign(Gtk.Align.CENTER)
            bx.append(Gtk.Image.new_from_icon_name(icon))
            bx.append(Gtk.Label(label=label))
            btn.set_child(bx)
            btn.connect('clicked', handler)
            btn_box.append(btn)
        _body.append(btn_box)
        _body.append(Gtk.Separator())

        # ── Appearance + Hotkeys button row ──────────────────────────────────
        tool_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tool_row.set_margin_start(12)
        tool_row.set_margin_end(12)
        tool_row.set_margin_top(8)
        tool_row.set_margin_bottom(8)

        self._appear_btn = Gtk.Button()
        self._appear_btn.add_css_class('flat')
        self._appear_btn.set_hexpand(True)
        abx = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        abx.set_margin_start(4)
        abx.append(Gtk.Image.new_from_icon_name('preferences-desktop-font-symbolic'))
        abx.append(Gtk.Label(label='Text Appearance', hexpand=True, xalign=0))
        self._appear_arrow = Gtk.Image.new_from_icon_name('pan-end-symbolic')
        abx.append(self._appear_arrow)
        self._appear_btn.set_child(abx)
        self._appear_btn.connect('clicked', self._toggle_appear_card)
        tool_row.append(self._appear_btn)

        hotkeys_btn = Gtk.Button(icon_name='help-browser-symbolic')
        hotkeys_btn.add_css_class('circular')
        hotkeys_btn.set_tooltip_text('Keyboard shortcuts')
        hotkeys_btn.connect('clicked', self._on_hotkeys_clicked)
        tool_row.append(hotkeys_btn)

        _body.append(tool_row)

        # ── Appearance card (inline revealer) ─────────────────────────────────
        self._appear_revealer = Gtk.Revealer()
        self._appear_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._appear_revealer.set_transition_duration(150)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class('card')
        card.set_margin_start(12)
        card.set_margin_end(12)
        card.set_margin_top(6)
        card.set_margin_bottom(8)

        def _row(label_text):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=label_text, xalign=0)
            lbl.set_size_request(64, -1)
            r.append(lbl)
            return r

        # Font family — all installed system fonts
        font_row = _row('Font')
        _prefix_labels = ['System Serif', 'System Sans-Serif']
        _prefix_css    = ['serif', 'sans-serif']
        _installed = sorted(
            f.get_name()
            for f in PangoCairo.FontMap.get_default().list_families()
        )
        self._font_css_names = _prefix_css + _installed
        cur_family = settings.get('font_family') or 'serif'
        try:
            font_idx = self._font_css_names.index(cur_family)
        except ValueError:
            font_idx = 0
        self._font_drop = Gtk.DropDown(
            model=Gtk.StringList.new(_prefix_labels + _installed))
        self._font_drop.set_hexpand(True)
        self._font_drop.set_enable_search(True)
        self._font_drop.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, 'string'))
        self._font_drop.set_selected(font_idx)
        self._font_drop.connect('notify::selected', self._on_appear_font)
        font_row.append(self._font_drop)
        card.append(font_row)

        # Font size
        size_row = _row('Size')
        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 8, 26, 0.5)
        self._size_scale.set_hexpand(True)
        self._size_scale.set_draw_value(False)
        self._size_scale.set_value(settings.get('font_size'))
        self._size_val_lbl = Gtk.Label(
            label=f'{settings.get("font_size"):.0f}pt')
        self._size_val_lbl.set_size_request(36, -1)
        self._size_scale.connect('value-changed', self._on_appear_size)
        size_row.append(self._size_scale)
        size_row.append(self._size_val_lbl)
        card.append(size_row)

        # Line spacing
        spacing_row = _row('Spacing')
        self._spacing_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1.0, 2.5, 0.1)
        self._spacing_scale.set_hexpand(True)
        self._spacing_scale.set_draw_value(False)
        self._spacing_scale.set_value(settings.get('line_spacing'))
        self._spacing_val_lbl = Gtk.Label(
            label=f'{settings.get("line_spacing"):.1f}×')
        self._spacing_val_lbl.set_size_request(36, -1)
        self._spacing_scale.connect('value-changed', self._on_appear_spacing)
        spacing_row.append(self._spacing_scale)
        spacing_row.append(self._spacing_val_lbl)
        card.append(spacing_row)

        # Bold + Justify toggles
        toggle_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=8, homogeneous=True)
        self._bold_btn = Gtk.ToggleButton(label='Bold')
        self._bold_btn.set_active(bool(settings.get('font_bold')))
        self._bold_btn.connect('toggled', self._on_appear_bold)
        self._justify_btn = Gtk.ToggleButton(label='Justified')
        self._justify_btn.set_active(bool(settings.get('font_justify')))
        self._justify_btn.connect('toggled', self._on_appear_justify)
        toggle_row.append(self._bold_btn)
        toggle_row.append(self._justify_btn)
        card.append(toggle_row)

        # ── Theme ─────────────────────────────────────────────────────────────
        card.append(Gtk.Separator())
        theme_lbl = Gtk.Label(label='Theme', xalign=0)
        theme_lbl.add_css_class('heading')
        card.append(theme_lbl)

        theme_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                            spacing=0, homogeneous=True)
        theme_row.add_css_class('linked')
        self._theme_light  = Gtk.ToggleButton(label='Light')
        self._theme_dark   = Gtk.ToggleButton(label='Dark')
        self._theme_system = Gtk.ToggleButton(label='System')
        cur_scheme = settings.get('color_scheme') or 'default'
        self._theme_light.set_active(cur_scheme == 'light')
        self._theme_dark.set_active(cur_scheme == 'dark')
        self._theme_system.set_active(cur_scheme not in ('light', 'dark'))
        for _tb in [self._theme_light, self._theme_dark, self._theme_system]:
            _tb.connect('clicked', self._on_appear_theme)
            theme_row.append(_tb)
        card.append(theme_row)

        # ── Text color ────────────────────────────────────────────────────────
        card.append(Gtk.Separator())
        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._color_check = Gtk.CheckButton(label='Custom text color')
        self._color_check.set_hexpand(True)
        saved_color = settings.get(f'text_color_{settings.get("color_scheme") or "default"}')
        self._color_check.set_active(bool(saved_color))
        self._color_check.connect('toggled', self._on_color_check)

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self._color_btn = Gtk.ColorButton()
        self._color_btn.set_use_alpha(False)
        self._color_btn.set_sensitive(bool(saved_color))
        _init_rgba = Gdk.RGBA()
        if not (saved_color and _init_rgba.parse(saved_color)):
            _init_rgba.red = _init_rgba.green = _init_rgba.blue = _init_rgba.alpha = 1.0
        self._color_btn.set_rgba(_init_rgba)
        self._color_btn.connect('color-set', self._on_color_changed)

        color_row.append(self._color_check)
        color_row.append(self._color_btn)
        card.append(color_row)

        self._appear_revealer.set_child(card)
        _body.append(self._appear_revealer)
        _body.append(Gtk.Separator())

        # ── Startup defaults (always visible, outside the appearance card) ─────
        import ebible_bridge as _eb2
        _all_bible_names = [n for n in sword_bridge.module_names()
                            if sword_bridge.module_type(n) == 'Biblical Texts'] \
                         + _eb2.module_names()
        _devot_names = sword_bridge.installed_devotional_modules()

        startup_lbl = Gtk.Label(label='Startup', xalign=0)
        startup_lbl.add_css_class('heading')
        startup_lbl.set_margin_start(12)
        startup_lbl.set_margin_top(8)
        startup_lbl.set_margin_bottom(2)
        _body.append(startup_lbl)

        def _srow(label_text):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.set_margin_start(12)
            r.set_margin_end(12)
            r.set_margin_top(4)
            r.set_margin_bottom(4)
            lbl = Gtk.Label(label=label_text, xalign=0)
            lbl.set_size_request(80, -1)
            r.append(lbl)
            return r

        default_mod_row = _srow('Bible')
        _bible_opts = ['(last used)'] + _all_bible_names
        _saved_def  = settings.get('default_module') or ''
        _def_idx    = _bible_opts.index(_saved_def) if _saved_def in _bible_opts else 0
        self._default_mod_drop = Gtk.DropDown(model=Gtk.StringList.new(_bible_opts))
        self._default_mod_drop.set_hexpand(True)
        self._default_mod_drop.set_enable_search(True)
        self._default_mod_drop.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, 'string'))
        self._default_mod_drop.set_selected(_def_idx)
        self._default_mod_drop.connect('notify::selected', self._on_default_mod_changed)
        default_mod_row.append(self._default_mod_drop)
        _body.append(default_mod_row)

        devot_row = _srow('Devotional')
        _devot_opts = ['(none)'] + _devot_names
        _saved_devt = settings.get('startup_devotional') or ''
        _devt_idx   = _devot_opts.index(_saved_devt) if _saved_devt in _devot_opts else 0
        self._devot_drop = Gtk.DropDown(model=Gtk.StringList.new(_devot_opts))
        self._devot_drop.set_hexpand(True)
        self._devot_drop.set_selected(_devt_idx)
        self._devot_drop.connect('notify::selected', self._on_devot_changed)
        devot_row.append(self._devot_drop)
        _body.append(devot_row)
        _body.append(Gtk.Separator())

        # reading plan section label
        plan_hdr = Gtk.Label(label='Reading Plan', xalign=0)
        plan_hdr.add_css_class('heading')
        plan_hdr.set_margin_start(12)
        plan_hdr.set_margin_top(10)
        plan_hdr.set_margin_bottom(4)
        _body.append(plan_hdr)

        # plan selector
        plans = reading_plans.get_plans()
        plan_names = [p['name'] for p in plans]
        self._plan_ids = [p['id'] for p in plans]
        self._plan_drop = Gtk.DropDown(model=Gtk.StringList.new(plan_names))
        self._plan_drop.set_margin_start(12)
        self._plan_drop.set_margin_end(12)
        self._plan_drop.set_margin_top(10)
        self._plan_drop.set_margin_bottom(6)
        self._plan_drop_handler = self._plan_drop.connect(
            'notify::selected', self._on_plan_dropdown_changed)
        _body.append(self._plan_drop)

        # plan description label
        self._plan_desc_lbl = Gtk.Label(wrap=True, xalign=0)
        self._plan_desc_lbl.set_margin_start(12)
        self._plan_desc_lbl.set_margin_end(12)
        self._plan_desc_lbl.set_margin_bottom(8)
        self._plan_desc_lbl.add_css_class('dim-label')
        self._plan_desc_lbl.add_css_class('caption')
        _body.append(self._plan_desc_lbl)

        # controls row (start / progress + reset)
        self._plan_ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._plan_ctrl_box.set_margin_start(12)
        self._plan_ctrl_box.set_margin_end(12)
        self._plan_ctrl_box.set_margin_bottom(8)
        self._plan_start_btn = Gtk.Button(label='Start today')
        self._plan_start_btn.add_css_class('suggested-action')
        self._plan_start_btn.connect('clicked', self._on_plan_start)
        self._plan_progress_lbl = Gtk.Label(hexpand=True, xalign=0)
        self._plan_reset_btn = Gtk.Button(label='Reset')
        self._plan_reset_btn.add_css_class('destructive-action')
        self._plan_reset_btn.connect('clicked', self._on_plan_reset)
        self._plan_ctrl_box.append(self._plan_start_btn)
        self._plan_ctrl_box.append(self._plan_progress_lbl)
        self._plan_ctrl_box.append(self._plan_reset_btn)
        _body.append(self._plan_ctrl_box)

        _body.append(Gtk.Separator())

        # day list (fixed height — outer body scroll handles overall panel scrolling)
        self._plan_scroll = Gtk.ScrolledWindow()
        self._plan_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._plan_scroll.set_min_content_height(200)
        self._day_listbox = Gtk.ListBox()
        self._day_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._day_listbox.add_css_class('boxed-list')
        self._day_listbox.connect('row-activated', self._on_day_row_activated)
        self._plan_scroll.set_child(self._day_listbox)
        _body.append(self._plan_scroll)

        handle = Gtk.Box()
        handle.add_css_class('resize-handle')
        handle.set_vexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        outer.append(panel)
        outer.append(handle)
        return outer, handle

    def _refresh_plan_ui(self):
        self._updating_plan = True
        plan_id, start_date = reading_plans.get_active()
        plans = reading_plans.get_plans()

        # sync dropdown to active plan
        if plan_id and plan_id in self._plan_ids:
            self._plan_drop.set_selected(self._plan_ids.index(plan_id))
        sel_idx = self._plan_drop.get_selected()
        sel_id = self._plan_ids[sel_idx]
        plan_id = plan_id or sel_id

        # description
        desc = next((p['description'] for p in plans if p['id'] == sel_id), '')
        self._plan_desc_lbl.set_text(desc)

        # controls
        if start_date and reading_plans.get_active()[0] == sel_id:
            self._plan_start_btn.set_visible(False)
            completed = reading_plans.get_completed(sel_id)
            total = next((p['total_days'] for p in plans if p['id'] == sel_id), 0)
            self._plan_progress_lbl.set_text(f'{len(completed)} / {total} days')
            self._plan_progress_lbl.set_visible(True)
            self._plan_reset_btn.set_visible(True)
            self._populate_day_list(sel_id, start_date)
        else:
            self._plan_start_btn.set_visible(True)
            self._plan_progress_lbl.set_visible(False)
            self._plan_reset_btn.set_visible(False)
            self._clear_day_list()

        self._updating_plan = False

    def _clear_day_list(self):
        self._today_row = None
        while True:
            row = self._day_listbox.get_row_at_index(0)
            if row is None:
                break
            self._day_listbox.remove(row)

    def _populate_day_list(self, plan_id, start_date):
        self._clear_day_list()
        days = reading_plans.get_plan_days(plan_id)
        completed = reading_plans.get_completed(plan_id)
        today_idx = reading_plans.today_index(start_date)
        for idx, readings in enumerate(days):
            try:
                date = (datetime.date.fromisoformat(start_date)
                        + datetime.timedelta(days=idx)).isoformat()
            except Exception:
                date = ''
            is_today = (idx == today_idx)
            row = self._make_day_row(plan_id, idx, readings, date,
                                     done=(idx in completed), is_today=is_today)
            self._day_listbox.append(row)
            if is_today:
                self._today_row = row
        GLib.idle_add(self._scroll_to_today)

    def _make_day_row(self, plan_id, idx, readings, date, done, is_today):
        row = Gtk.ListBoxRow()
        row._plan_id = plan_id
        row._day_idx = idx
        row._readings = readings
        if is_today:
            row.add_css_class('plan-today')

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        check = Gtk.CheckButton()
        check.set_active(done)
        check.connect('toggled', self._on_day_check_toggled, plan_id, idx)
        box.append(check)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        day_lbl = Gtk.Label(label=f'Day {idx + 1}', xalign=0)
        day_lbl.add_css_class('caption')
        day_lbl.add_css_class('dim-label')
        passage_lbl = Gtk.Label(
            label=reading_plans.format_passages(readings), xalign=0, hexpand=True)
        passage_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        if done:
            passage_lbl.add_css_class('dim-label')
        vbox.append(day_lbl)
        vbox.append(passage_lbl)
        box.append(vbox)

        if date:
            date_lbl = Gtk.Label(label=date, xalign=1)
            date_lbl.add_css_class('caption')
            date_lbl.add_css_class('dim-label')
            box.append(date_lbl)

        row.set_child(box)
        return row

    def _scroll_to_today(self):
        if self._today_row:
            self._today_row.grab_focus()
            adj = self._plan_scroll.get_vadjustment()
            alloc = self._today_row.get_allocation()
            if alloc.height > 0:
                target = alloc.y - (self._plan_scroll.get_allocated_height() // 2)
                adj.set_value(max(0, target))
        return GLib.SOURCE_REMOVE

    def _on_plan_dropdown_changed(self, _drop, _param):
        if self._updating_plan:
            return
        sel_id = self._plan_ids[self._plan_drop.get_selected()]
        reading_plans.set_plan(sel_id)
        self._refresh_plan_ui()

    def _on_plan_start(self, _btn):
        sel_id = self._plan_ids[self._plan_drop.get_selected()]
        today = datetime.date.today().isoformat()
        reading_plans.set_start_date(sel_id, today)
        self._refresh_plan_ui()

    def _on_plan_reset(self, _btn):
        sel_id = self._plan_ids[self._plan_drop.get_selected()]
        reading_plans.clear_start_date(sel_id)
        self._refresh_plan_ui()

    def _on_day_check_toggled(self, check, plan_id, idx):
        reading_plans.set_day_done(plan_id, idx, check.get_active())
        # update progress label without rebuilding the whole list
        plans = reading_plans.get_plans()
        completed = reading_plans.get_completed(plan_id)
        total = next((p['total_days'] for p in plans if p['id'] == plan_id), 0)
        self._plan_progress_lbl.set_text(f'{len(completed)} / {total} days')

    def _on_day_row_activated(self, _listbox, row):
        if not row._readings:
            return
        groups = reading_plans.group_readings(row._readings)
        if len(groups) <= 1:
            book, chapter = row._readings[0]
            self._menu_revealer.set_reveal_child(False)
            self._go_to(book, chapter)
            return

        pop = Gtk.Popover()
        pop.set_parent(row)
        pop.set_has_arrow(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        for book, start, end in groups:
            label = f'{book} {start}' if start == end else f'{book} {start}–{end}'
            btn = Gtk.Button(label=label)
            btn.add_css_class('flat')
            btn.set_halign(Gtk.Align.FILL)
            btn.get_child().set_xalign(0)
            btn.connect('clicked', self._on_plan_passage_clicked, pop, book, start)
            box.append(btn)
        pop.set_child(box)
        pop.connect('closed', lambda p: p.unparent())
        pop.popup()

    def _on_plan_passage_clicked(self, _btn, pop, book, chapter):
        pop.popdown()
        self._menu_revealer.set_reveal_child(False)
        self._go_to(book, chapter)
