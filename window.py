import logging
import re
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')
import datetime
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, Pango, PangoCairo
import sword_bridge
import settings
import module_positions
import bookmarks
import reading_plans
import annotations
from pane import BiblePane
from module_manager import ModuleManagerWindow
from search_panel import SearchPanel
from study_journal import StudyJournalWindow

_log = logging.getLogger('scriptura.window')
from crossref_panel import CrossRefPanel
from a11y import set_accessible_label


def N_(message):
    """No-op gettext marker for strings in class-level data; translated at
    display time via _()."""
    return message


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
        # bible: URI ref to navigate to once panes are ready (see main.py).
        self._startup_ref = kwargs.pop('startup_ref', None)
        super().__init__(**kwargs)
        # Restore saved window size; falls back to settings defaults
        # (1100x700) on first run.
        self.set_default_size(
            settings.get('window_width'), settings.get('window_height'))
        if settings.get('window_maximized'):
            self.maximize()
        self.set_title('Scriptura')  # app name — not translated
        self._nav_back = []
        self._nav_fwd = []
        # Restore last book/chapter — validated against BOOKS list and
        # chapter count below, before the dropdowns get their initial value.
        saved_book = settings.get('last_book')
        saved_chap = settings.get('last_chapter')
        if saved_book in BOOKS and isinstance(saved_chap, int):
            try:
                max_ch = sword_bridge.chapter_count(saved_book)
                if 1 <= saved_chap <= max_ch:
                    self._current_loc = (saved_book, saved_chap)
                else:
                    self._current_loc = ('Genesis', 1)
            except Exception:
                self._current_loc = ('Genesis', 1)
        else:
            self._current_loc = ('Genesis', 1)
        self._updating_plan = False
        self._today_row = None
        self._modules_win = None
        self._journal_win = None
        # Adaptive layout state, driven by Adw.Breakpoints (see _build_ui).
        # _header_narrow: secondary controls folded into the overflow menu.
        # _panes_narrow: collapsed to a single pane; _narrow_pane (1 or 2) is
        # which one shows while collapsed in split mode.
        self._header_narrow = False
        self._panes_narrow = False
        self._ultra_narrow = False
        self._narrow_pane = 1
        self._build_ui()
        self._load_all_panes()
        self.connect('close-request', self._on_close_request)
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
        # Surface any corrupted-data fallbacks once at startup so the user
        # knows their file wasn't readable (and their default state isn't a
        # silent loss). Deferred to idle so the window has time to lay out
        # and the toast overlay is alive.
        GLib.idle_add(self._warn_on_load_failures)
        # Build the cross-reference index ahead of time on a background thread,
        # so the first verse click is instant. Parsing the 8MB OpenBible TSV is
        # ~1.3s of pure-Python (GIL-held) work the first time — paid here at
        # idle instead of stalling the user's click. Cached to a pickle after,
        # so later launches warm in <100ms. Deferred to idle so it doesn't
        # compete with the initial chapter render.
        GLib.idle_add(self._prewarm_cross_refs)
        # Surface a failed annotation write as a toast — otherwise the
        # in-memory change would quietly disappear on the next launch.
        annotations.set_save_error_handler(
            lambda: GLib.idle_add(
                self._toast,
                _("Couldn't save your annotation — check disk space or "
                  "permissions. The change may be lost when you quit.")))
        # Same treatment for the other user-authored stores: a dropped write
        # should be visible, not a silent loss on next launch.
        bookmarks.set_save_error_handler(
            lambda: GLib.idle_add(
                self._toast,
                _("Couldn't save your bookmark — check disk space or "
                  "permissions. The change may be lost when you quit.")))
        reading_plans.set_save_error_handler(
            lambda: GLib.idle_add(
                self._toast,
                _("Couldn't save reading-plan progress — check disk space or "
                  "permissions. The change may be lost when you quit.")))
        # If launched via `bible:John+3:16` URI, navigate now that the
        # panes are loaded. Bad refs silently no-op.
        if self._startup_ref:
            result = self._parse_jump(self._startup_ref)
            if result:
                book, chapter, verse = result
                GLib.idle_add(lambda: self._go_to(book, chapter, verse) or False)

    def _prewarm_cross_refs(self):
        import open_data
        if open_data.has_cross_refs():
            threading.Thread(
                target=open_data.warm_cross_refs, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _warn_on_load_failures(self):
        failed = []
        if settings.load_failed():
            failed.append(_('settings'))
        if annotations.load_failed():
            failed.append(_('annotations'))
        if bookmarks.load_failed():
            failed.append(_('bookmarks'))
        if reading_plans.load_failed():
            failed.append(_('reading plans'))
        if failed:
            names = ', '.join(failed)
            self._toast(
                _("Couldn't read {names}.json — using defaults. "
                  "Your file is preserved; rename to recover.").format(names=names))
        return GLib.SOURCE_REMOVE

    def _push_nav_back(self, loc):
        self._nav_back.append(loc)
        if len(self._nav_back) > self._NAV_MAX:
            del self._nav_back[0]

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        self._toolbar_view = toolbar_view

        header = Adw.HeaderBar()
        header.add_css_class('scriptura-header')
        # Flat header so it blends into the window background — the toolbar and
        # the two pane headers read as one calm band (Apple-Books style).
        header.add_css_class('flat')
        self._header = header
        toolbar_view.add_top_bar(header)

        # ── Left: burger + back/forward + navigation ──────────────────────────
        burger_btn = Gtk.Button(icon_name='open-menu-symbolic')
        burger_btn.set_tooltip_text(_('Menu'))
        set_accessible_label(burger_btn, _('Menu'))
        burger_btn.add_css_class('flat')
        burger_btn.add_css_class('header-action')
        burger_btn.connect('clicked', self._toggle_menu)
        header.pack_start(burger_btn)

        self._back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        self._back_btn.set_tooltip_text(_('Go back (Alt+←)'))
        set_accessible_label(self._back_btn, _('Go back'))
        self._back_btn.add_css_class('flat')
        self._back_btn.add_css_class('header-action')
        self._back_btn.set_sensitive(False)
        self._back_btn.connect('clicked', self._on_nav_back)
        header.pack_start(self._back_btn)

        self._fwd_btn = Gtk.Button(icon_name='go-next-symbolic')
        self._fwd_btn.set_tooltip_text(_('Go forward (Alt+→)'))
        set_accessible_label(self._fwd_btn, _('Go forward'))
        self._fwd_btn.add_css_class('flat')
        self._fwd_btn.add_css_class('header-action')
        self._fwd_btn.set_sensitive(False)
        self._fwd_btn.connect('clicked', self._on_nav_fwd)
        header.pack_start(self._fwd_btn)

        # Recent passages (last 10 distinct book/chapter pairs, persistent
        # across sessions) now live behind the back arrow — right-click or
        # long-press it — instead of a dedicated button, for a calmer header.
        self._recent_pop = Gtk.Popover()
        self._recent_pop.set_has_arrow(True)
        self._recent_pop.set_position(Gtk.PositionType.BOTTOM)
        self._recent_pop.set_parent(self._back_btn)
        self._recent_pop.connect(
            'show', lambda _p: self._build_recent_popover_content())
        self._back_btn.set_tooltip_text(
            _('Go back (Alt+←) · right-click or hold for recent passages'))

        recent_click = Gtk.GestureClick()
        recent_click.set_button(3)  # secondary (right) button
        recent_click.connect('pressed', self._on_back_history)
        self._back_btn.add_controller(recent_click)
        recent_hold = Gtk.GestureLongPress()
        recent_hold.connect('pressed', self._on_back_history)
        self._back_btn.add_controller(recent_hold)

        # Dropdowns remain as authoritative state holders for book/chapter
        # index — used by Alt+arrow navigation and the quick-jump bar — but
        # are not visible and have no change handlers. All navigation flows
        # through _go_to(), which writes to them.
        self.book_drop = Gtk.DropDown(model=Gtk.StringList.new(BOOKS))
        self.book_drop.set_visible(False)
        header.pack_start(self.book_drop)

        self.chapter_drop = Gtk.DropDown(
            model=Gtk.StringList.new([str(i) for i in range(1, 51)])
        )
        self.chapter_drop.set_visible(False)
        header.pack_start(self.chapter_drop)

        # Combined Book + Chapter reference button — Apple-Books style.
        self._ref_btn = Gtk.MenuButton()
        self._ref_btn.set_always_show_arrow(True)
        self._ref_btn.add_css_class('flat')
        self._ref_btn.add_css_class('reference-title-button')
        self._ref_btn.set_tooltip_text(_('Choose passage (Ctrl+L)'))
        set_accessible_label(self._ref_btn, _('Choose passage'))
        self._ref_pop = Gtk.Popover()
        self._ref_pop.set_has_arrow(True)
        self._ref_btn.set_popover(self._ref_pop)
        self._ref_pop.connect('show', lambda _p: self._build_ref_popover_content())
        # Mouse wheel over the passage button cycles chapters — matches the
        # convention from native readers and browsers (scroll-over-title).
        ref_scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL)
        ref_scroll.connect('scroll', self._on_ref_btn_scroll)
        self._ref_btn.add_controller(ref_scroll)
        header.set_title_widget(self._ref_btn)

        self.lex_toggle = Gtk.ToggleButton()
        lex_lbl = Gtk.Label()
        lex_lbl.set_markup('<span size="x-large">‎א</span><span size="large">Ω</span>')
        self.lex_toggle.set_child(lex_lbl)
        self.lex_toggle.add_css_class('flat')
        self.lex_toggle.add_css_class('scriptura-lex-toggle')
        self.lex_toggle.set_tooltip_text(
            _("Greek / Hebrew lexicon — click words for definitions"))
        # The visible child is decorative glyphs (אΩ); give AT a real name.
        set_accessible_label(self.lex_toggle, _('Greek / Hebrew lexicon'))
        self.lex_toggle.connect('toggled', self._on_lex_toggle)
        # Packed into the right-hand content cluster below — it acts on the
        # displayed text, so it belongs with the reading-view controls rather
        # than the navigation buttons on the left.

        # ── Right: search + bookmarks + view toggle ────────────────────────────
        self._bookmark_btn = Gtk.Button(icon_name='bookmark-new-symbolic')
        self._bookmark_btn.add_css_class('flat')
        self._bookmark_btn.add_css_class('header-action')
        self._bookmark_btn.set_tooltip_text(_('Bookmarks'))
        set_accessible_label(self._bookmark_btn, _('Bookmarks'))
        self._bookmark_btn.connect('clicked', self._on_bookmark_clicked)
        header.pack_end(self._bookmark_btn)

        # Overflow — folds the secondary header controls (lexicon, bookmarks,
        # swap) into one popover when the window is too narrow to show them all.
        # Hidden at full width; the Adw.Breakpoint swaps it in (see _build_ui
        # end + _set_header_narrow).
        self._overflow_btn = Gtk.MenuButton(icon_name='view-more-symbolic')
        self._overflow_btn.add_css_class('flat')
        self._overflow_btn.add_css_class('header-action')
        self._overflow_btn.set_tooltip_text(_('More'))
        set_accessible_label(self._overflow_btn, _('More actions'))
        self._overflow_pop = Gtk.Popover()
        self._overflow_btn.set_popover(self._overflow_pop)
        self._overflow_pop.connect(
            'show', lambda _p: self._overflow_pop.set_child(
                self._build_overflow_content()))
        self._overflow_btn.set_visible(False)
        header.pack_end(self._overflow_btn)

        self._search_btn = search_btn = Gtk.Button(icon_name='system-search-symbolic')
        search_btn.add_css_class('flat')
        search_btn.add_css_class('header-action')
        search_btn.set_tooltip_text(_('Search (Ctrl+F)'))
        set_accessible_label(search_btn, _('Search'))
        search_btn.connect('clicked', self._on_search_clicked)
        header.pack_end(search_btn)

        self._view_box = view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        view_box.add_css_class('linked')
        self._btn_single = Gtk.ToggleButton(icon_name='view-paged-symbolic')
        self._btn_single.add_css_class('header-action')
        self._btn_single.set_tooltip_text(_('Single pane'))
        set_accessible_label(self._btn_single, _('Single pane'))
        self._btn_split = Gtk.ToggleButton(icon_name='view-dual-symbolic')
        self._btn_split.add_css_class('header-action')
        self._btn_split.set_tooltip_text(_('Split pane'))
        set_accessible_label(self._btn_split, _('Split pane'))
        self._btn_single.set_group(self._btn_split)
        # Restore saved view mode (split by default for first run).
        if settings.get('split_pane_mode'):
            self._btn_split.set_active(True)
        else:
            self._btn_single.set_active(True)
        self._btn_single.connect('toggled', self._on_view_mode)
        self._btn_split.connect('toggled', self._on_view_mode)
        view_box.append(self._btn_single)
        view_box.append(self._btn_split)
        header.pack_end(view_box)

        # Narrow-mode pane switcher — replaces the single/split toggle when the
        # window is too narrow for two panes (shown only when the user is in
        # split mode and thus has two distinct panes to flip between).
        self._narrow_switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._narrow_switch_box.add_css_class('linked')
        self._narrow_btn1 = Gtk.ToggleButton(label='1')
        self._narrow_btn1.add_css_class('header-action')
        self._narrow_btn1.set_tooltip_text(_('Show pane 1'))
        set_accessible_label(self._narrow_btn1, _('Show pane 1'))
        self._narrow_btn2 = Gtk.ToggleButton(label='2')
        self._narrow_btn2.add_css_class('header-action')
        self._narrow_btn2.set_tooltip_text(_('Show pane 2'))
        set_accessible_label(self._narrow_btn2, _('Show pane 2'))
        self._narrow_btn2.set_group(self._narrow_btn1)
        self._narrow_btn1.set_active(True)
        self._narrow_btn1.connect('toggled', self._on_narrow_switch)
        self._narrow_btn2.connect('toggled', self._on_narrow_switch)
        self._narrow_switch_box.append(self._narrow_btn1)
        self._narrow_switch_box.append(self._narrow_btn2)
        self._narrow_switch_box.set_visible(False)
        header.pack_end(self._narrow_switch_box)

        self._swap_btn = Gtk.Button(icon_name='object-flip-horizontal-symbolic')
        self._swap_btn.add_css_class('flat')
        self._swap_btn.add_css_class('header-action')
        self._swap_btn.set_tooltip_text(_('Swap pane modules'))
        set_accessible_label(self._swap_btn, _('Swap pane modules'))
        self._swap_btn.connect('clicked', self._on_swap_clicked)
        self._swap_btn.set_sensitive(bool(settings.get('split_pane_mode')))
        header.pack_end(self._swap_btn)

        # Lexicon toggle sits at the inner edge of the right cluster (just
        # right of the centred passage title), grouped with the reading-view
        # controls. The אΩ glyph is kept deliberately — it names the two
        # languages it covers, which a generic dictionary icon would lose.
        header.pack_end(self.lex_toggle)

        # ── Panes ─────────────────────────────────────────────────────────────
        # Only modules readable in a pane (Bibles, commentaries, devotionals)
        # are valid here — support modules like Strong's lexicons and MorphGNT
        # live in the lexicon panel / dict popup, not the pane dropdown.
        import ebible_bridge as _eb
        import catena_bridge as _cat
        import content
        readable_names = content.readable_module_names()
        # SWORD-only subset for picking a default Bible/commentary pane —
        # eBible texts and the catena pack aren't default-Bible candidates.
        sword_readable = [n for n in readable_names
                          if not _eb.is_ebible_module(n)
                          and not _cat.is_catena_module(n)]

        # Pane 1 module: per-session saved → first readable module.
        # Pane 2 module: per-session saved → auto-detect any installed
        # devotional → mirror pane 1. If pane 2 ends up showing a
        # devotional on startup, we also auto-navigate pane 1 to today's
        # reading (see _startup_navigate_to_devotional_ref).
        p1_mod = settings.get('pane1_module')
        if p1_mod not in readable_names:
            p1_mod = sword_readable[0] if sword_readable else (readable_names[0] if readable_names else None)

        p2_saved = settings.get('pane2_module')
        if p2_saved in readable_names:
            p2_mod = p2_saved
            self._startup_devt_module = (
                p2_saved if p2_saved in sword_readable
                and sword_bridge.is_devotional_module(p2_saved) else None
            )
        else:
            devots = sword_bridge.installed_devotional_modules()
            self._startup_devt_module = devots[0] if devots else None
            p2_mod = self._startup_devt_module or p1_mod

        # Modules currently showing a cipher-key error toast — avoids
        # stacking duplicates across panes / re-renders.
        self._cipher_toasting = set()

        self.pane1 = BiblePane(module_name=p1_mod,
                               on_word_click=self._on_word_click,
                               on_click_outside_search=self._hide_search,
                               on_verse_select=self._on_verse_select,
                               on_word_study_navigate=self._on_word_study_nav,
                               on_toast=self._toast,
                               on_font_size_request=self._adjust_font_size,
                               on_cipher_error=self._on_cipher_error,
                               on_edit_cipher=self._show_edit_cipher_key,
                               on_modules_changed=self._on_modules_changed,
                               on_open_artifact=self._on_open_artifact,
                               pane_id=1)
        self.pane2 = BiblePane(module_name=p2_mod,
                               on_word_click=self._on_word_click,
                               on_click_outside_search=self._hide_search,
                               on_verse_select=self._on_verse_select,
                               on_word_study_navigate=self._on_word_study_nav,
                               on_toast=self._toast,
                               on_font_size_request=self._adjust_font_size,
                               on_cipher_error=self._on_cipher_error,
                               on_edit_cipher=self._show_edit_cipher_key,
                               on_modules_changed=self._on_modules_changed,
                               on_open_artifact=self._on_open_artifact,
                               pane_id=2)

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                                vexpand=True, hexpand=True)
        self._paned.add_css_class('main-split')
        self._paned.set_start_child(self.pane1)
        self._paned.set_end_child(self.pane2)
        # Apply restored split/single mode to the actual pane visibility.
        # The toggle button's set_active in _build_ui ran before pane2
        # existed and before its 'toggled' handler was connected, so
        # without this the button would say "single" while pane2 was
        # still showing.
        self.pane2.set_visible(self._btn_split.get_active())
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
        # When collapsed the revealer must not capture pointer events — in
        # ultra-narrow it's halign FILL (full-width sheet), so a collapsed-but-
        # targetable revealer would otherwise blanket the whole content area
        # and swallow scroll/clicks (incl. the pane toolbar). Track targetability
        # to the reveal state.
        self._search_revealer.set_can_target(False)
        self._search_revealer.connect(
            'notify::reveal-child',
            lambda r, _p: r.set_can_target(r.get_reveal_child()))

        # ── Quick jump overlay ────────────────────────────────────────────────
        self._jump_entry = Gtk.SearchEntry()
        self._jump_entry.set_placeholder_text(_('Go to… (e.g. John 3:16)'))
        self._jump_entry.set_size_request(320, -1)
        self._jump_entry.connect('activate', self._on_jump_activate)
        self._jump_entry.connect('stop-search', lambda _: self._hide_jump())

        jump_wrap = Gtk.Box()
        jump_wrap.set_halign(Gtk.Align.CENTER)
        jump_wrap.set_margin_top(8)
        jump_wrap.add_css_class('card')
        jump_wrap.add_css_class('jump-bar')
        jump_wrap.append(self._jump_entry)

        self._jump_revealer = Gtk.Revealer()
        self._jump_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._jump_revealer.set_transition_duration(200)
        self._jump_revealer.set_halign(Gtk.Align.CENTER)
        self._jump_revealer.set_valign(Gtk.Align.START)
        self._jump_revealer.set_child(jump_wrap)

        # ── App menu panel (right-side revealer) ─────────────────────────────
        # CSS for .menu-panel, .jump-bar, .reading-exit-btn, .bible-view,
        # .lex-panel / .ws-panel, .appearance-card, .plan-today, and
        # .resize-handle lives in data/style.css (loaded once at startup
        # by styles.load_app_css from main.py).
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

        # The paned + side overlays live inside the toast overlay so
        # toasts float above the reading area; the cross-ref bar sits
        # outside the toast overlay so toasts don't paint over it when
        # both are visible.
        overlay = Gtk.Overlay(vexpand=True, hexpand=True)
        overlay.set_child(self._paned)
        # Floating centered drag-grip for the split. The GtkPaned separator
        # stays opacity:0 forever (its built-in hairline never shows); this
        # separate overlay widget is the only visible affordance, fading in on
        # hover near the divider. can_target=False so drags pass straight
        # through to the separator beneath it.
        self._pane_grip = Gtk.Box()
        self._pane_grip.add_css_class('pane-grip')
        self._pane_grip.set_halign(Gtk.Align.START)
        self._pane_grip.set_valign(Gtk.Align.CENTER)
        self._pane_grip.set_can_target(False)
        self._pane_grip.set_visible(False)
        overlay.add_overlay(self._pane_grip)
        self._paned.connect('notify::position', self._update_pane_grip)
        grip_motion = Gtk.EventControllerMotion.new()
        grip_motion.connect('motion', self._on_grip_motion)
        grip_motion.connect('leave', lambda _c: self._pane_grip.set_visible(False))
        overlay.add_controller(grip_motion)
        overlay.add_overlay(self._search_revealer)
        overlay.add_overlay(self._jump_revealer)
        overlay.add_overlay(self._menu_revealer)

        # ── Exit-reading-mode affordance ─────────────────────────────────────
        # Floats a small circular X at top-center after the cursor hovers in
        # the top "hot zone" for 2s while reading mode is on. Gives users an
        # obvious way out without relying on remembering Esc / F11.
        self._exit_reading_btn = Gtk.Button(icon_name='window-close-symbolic')
        self._exit_reading_btn.add_css_class('circular')
        self._exit_reading_btn.add_css_class('reading-exit-btn')
        self._exit_reading_btn.set_tooltip_text(_('Exit reading mode'))
        set_accessible_label(self._exit_reading_btn, _('Exit reading mode'))
        self._exit_reading_btn.connect(
            'clicked', lambda _b: self._set_reading_mode(False))

        self._exit_reading_revealer = Gtk.Revealer()
        self._exit_reading_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._exit_reading_revealer.set_transition_duration(200)
        self._exit_reading_revealer.set_halign(Gtk.Align.CENTER)
        self._exit_reading_revealer.set_valign(Gtk.Align.START)
        self._exit_reading_revealer.set_margin_top(6)
        self._exit_reading_revealer.set_child(self._exit_reading_btn)
        self._exit_reading_revealer.set_reveal_child(False)
        overlay.add_overlay(self._exit_reading_revealer)

        self._reading_hover_timer = None
        # Attach the motion controller to the window itself so that the
        # event reaches us regardless of which child widget (TextView,
        # Paned divider, scrollbars) the cursor is currently over. We also
        # listen for `enter` so the first entry into the hot zone counts,
        # not only subsequent movement.
        self._reading_overlay_for_motion = overlay  # stash for coord remap
        motion = Gtk.EventControllerMotion.new()
        motion.connect('motion', self._on_reading_mouse_motion)
        motion.connect('enter', self._on_reading_mouse_motion)
        motion.connect('leave', lambda _c: self._reading_hide_exit_btn())
        self.add_controller(motion)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(overlay)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(self._toast_overlay)
        main_box.append(self._crossref_revealer)
        toolbar_view.set_content(main_box)

        # Adaptive layout via two breakpoints (thresholds are easy to tune):
        #  • ≤850px — the full header no longer fits, so fold the secondary
        #    controls (lexicon/bookmark/swap) into the overflow ⋯ menu.
        #  • ≤680px — two reading panes get too cramped, so also collapse to
        #    one (with a 1/2 switcher).
        # Adw applies only ONE breakpoint at a time (the last-added match), so
        # we don't drive state from each breakpoint's apply/unapply — that
        # would unapply the header breakpoint the moment the panes one kicks
        # in. Instead we watch `current-breakpoint` and set the full state for
        # whichever is active (panes added last → wins at the narrowest band).
        # Grip/gutters/cards and the user's wide-mode split choice are
        # untouched — only visibility flips.
        self._bp_header = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse('max-width: 850px'))
        self.add_breakpoint(self._bp_header)
        self._bp_panes = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse('max-width: 680px'))
        self.add_breakpoint(self._bp_panes)
        #  • ≤600px — ultra-narrow desktop: fold the *rest* of the chrome
        #    (back/forward, search, the pane switcher) into ⋯ too, leaving only
        #    the menu, passage title, one ⋯, and the system buttons, and tighten
        #    the reading margins. Chrome loses so the text never clips.
        #    This kicks in *above* the ~572px floor of the band-above so there's
        #    no dead range that clips between the two working layouts: the
        #    overflow/panes header can't shrink past ~572, so ultra must take
        #    over before the window reaches it.
        self._bp_ultra = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse('max-width: 600px'))
        self.add_breakpoint(self._bp_ultra)
        self.connect('notify::current-breakpoint', self._on_breakpoint_changed)

        # Global shortcuts are GActions with accelerators (see
        # _install_actions). Their accelerators are dispatched by GTK's
        # global-scope shortcut controller, which fires regardless of which
        # widget is focused — and even when nothing is focused. That focus
        # independence is the whole point: a window-level EventControllerKey
        # only sees keys while a focus widget exists, so on Wayland a NULL
        # focus (fresh launch, resume, a popover closing) used to leave every
        # shortcut silently dead.
        self._install_actions()

        # Only the genuinely contextual keys stay on a key controller:
        # Escape (dismiss whichever overlay is open) and Home/End (first /
        # last verse, suppressed inside text inputs). CAPTURE phase so the
        # window sees Escape before a focused search entry swallows it.
        key_controller = Gtk.EventControllerKey.new()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect('key-pressed', self._on_key_press)
        self.add_controller(key_controller)

        # Start with the reading view focused so the contextual keys above
        # work from launch (and the app opens in a sensible state) rather
        # than only after the user's first click. One-shot on first map.
        self.connect('map', self._on_first_map)

        # After the compositor suspends/resumes — or the window sits
        # backgrounded for a long time — GTK4-on-Wayland can leave allocations
        # queued while the frame clock was paused (e.g. a just-revealed
        # lexicon panel) unflushed. Manually toggling the split view "fixes"
        # it by forcing a relayout; run that same relayout automatically on
        # reactivation. (Shortcuts no longer depend on this — they're actions.)
        self.connect('notify::is-active', self._on_active_changed)

        self._update_ref_label(*self._current_loc)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def _install_actions(self):
        """Register the global shortcuts as window GActions with accelerators.

        Action accelerators dispatch focus-independently (GTK runs them via a
        global-scope shortcut controller), which is why these survive a NULL
        focus where a window-level key controller would not. The displayed
        accelerators in the Keyboard Shortcuts dialog are read back from the
        map registered here, so the two can't drift."""
        app = self.get_application()
        # (action name, accelerators, handler)
        specs = [
            ('zoom-in',  ['<Ctrl>plus', '<Ctrl>equal', '<Ctrl>KP_Add'],
             lambda: self._adjust_font_size(1.0)),
            ('zoom-out', ['<Ctrl>minus', '<Ctrl>KP_Subtract'],
             lambda: self._adjust_font_size(-1.0)),
            ('goto',     ['<Ctrl>l'], self._show_jump),
            ('search',   ['<Ctrl>f'], lambda: self._on_search_clicked(None)),
            ('search-next', ['F3'], lambda: self._step_search_result(prev=False)),
            ('search-prev', ['<Shift>F3'], lambda: self._step_search_result(prev=True)),
            ('reading-mode', ['F11'],
             lambda: self._set_reading_mode(not getattr(self, '_reading_mode', False))),
            ('focus-pane-1', ['<Ctrl>1'], lambda: self.pane1._view.grab_focus()),
            ('focus-pane-2', ['<Ctrl>2'], self._focus_pane2),
            ('focus-other-pane', ['<Ctrl>Tab'], self._focus_other_pane),
            ('prev-chapter', ['<Alt>Left'], self._go_prev_chapter),
            ('next-chapter', ['<Alt>Right'], self._go_next_chapter),
            ('prev-book', ['<Alt>Up'], self._go_prev_book),
            ('next-book', ['<Alt>Down'], self._go_next_book),
            ('show-help-overlay', ['<Ctrl>question'], self._open_shortcuts_dialog),
        ]
        self._action_accels = {}
        for name, accels, handler in specs:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, h=handler: h())
            self.add_action(action)
            app.set_accels_for_action(f'win.{name}', accels)
            self._action_accels[name] = accels

    def _focus_pane2(self):
        if self.pane2.get_visible():
            self.pane2._view.grab_focus()

    def _on_first_map(self, *_args):
        if getattr(self, '_did_initial_focus', False):
            return
        self._did_initial_focus = True
        self.pane1._view.grab_focus()

    def _on_key_press(self, controller, keyval, keycode, state):
        alt  = bool(state & Gdk.ModifierType.ALT_MASK)
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if keyval == Gdk.KEY_Escape:
            if self.pane1.dismiss_dict_peek() or self.pane2.dismiss_dict_peek():
                return True
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

        # Home / End jump to first / last verse of current chapter — but
        # only when focus isn't on a text input, so typing in the search
        # bar / jump bar / tag entry still works normally.
        if keyval in (Gdk.KEY_Home, Gdk.KEY_End) and not (ctrl or alt):
            if not self._focus_is_text_input():
                book, ch = self._current_loc
                if keyval == Gdk.KEY_Home:
                    target_v = 1
                else:
                    try:
                        target_v = sword_bridge.verse_count(book, ch)
                    except Exception:
                        target_v = 1
                self._go_to(book, ch, target_v, record=False)
                return True

        return False

    def _on_active_changed(self, *_args):
        """Flush layout deferred while the frame clock was paused (suspend /
        resume / long idle). See the connect() comment in _build_ui. This is
        what the manual split-view toggle was doing to bring the lexicon
        panel (and the pane's click gestures) back to life."""
        if not self.is_active():
            return
        self.queue_resize()

    def _focus_is_text_input(self):
        f = self.get_focus()
        if f is None:
            return False
        if isinstance(f, Gtk.Editable):
            return True
        if isinstance(f, Gtk.TextView) and f.get_editable():
            return True
        return False

    def _focus_other_pane(self):
        f = self.get_focus()
        while f is not None:
            if f is self.pane1:
                target = self.pane2 if self.pane2.get_visible() else self.pane1
                target._view.grab_focus()
                return
            if f is self.pane2:
                self.pane1._view.grab_focus()
                return
            f = f.get_parent()
        # No pane focused yet — go to pane1 by default
        self.pane1._view.grab_focus()

    def _on_ref_btn_scroll(self, _ctrl, _dx, dy):
        # Vertical scroll: down → next chapter, up → previous chapter.
        if dy > 0:
            self._go_next_chapter()
        elif dy < 0:
            self._go_prev_chapter()
        return True

    def _step_search_result(self, prev=False):
        """F3 / Shift+F3 — step through results.
        Priority:
          1. A search panel that is currently visible AND has results.
          2. Otherwise, any surface that still has cached results from a
             previous search — so F3 keeps working after the panel is
             dismissed (e.g. by clicking a row, which auto-closes the
             window panel)."""
        # Visible-panel priority pass.
        if (self._search_revealer.get_reveal_child()
                and getattr(self._search_panel, '_results', None)):
            self._search_panel.step_result(prev=prev)
            return
        for pane in (self.pane1, self.pane2):
            if (pane._pane_search_rev.get_reveal_child()
                    and pane._pane_search_results):
                pane.step_pane_search_result(prev=prev)
                return

        # Fallback: closed panel, but results still cached. Re-reveal the
        # window panel so the user can see the count label update; pane
        # results just keep stepping silently.
        if getattr(self._search_panel, '_results', None):
            self._search_revealer.set_reveal_child(True)
            self._search_panel.step_result(prev=prev)
            return
        for pane in (self.pane1, self.pane2):
            if pane._pane_search_results:
                pane.step_pane_search_result(prev=prev)
                return
        # No cached results at all — surface a hint so the user knows F3
        # fired but had nothing to step through (also useful for debugging:
        # if you see this toast, the key reached the handler).
        self._toast(_('No active search — Ctrl+F to search'))

    # ── Central navigation ────────────────────────────────────────────────────

    def _go_to(self, book, chapter, verse=None, record=True):
        if book not in BOOKS:
            return
        if record:
            self._push_nav_back(self._current_loc)
            self._nav_fwd.clear()
            self._update_nav_btns()

        self.book_drop.set_selected(BOOKS.index(book))
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
                   and e[0] in BOOKS and isinstance(e[1], int)]

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
                lbl = Gtk.Label(label=f'{book} {ch}', xalign=0)
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
        self.book_drop.set_selected(BOOKS.index(book))
        count = sword_bridge.chapter_count(book)
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
        self._ref_btn.set_label(f'{book} {chapter}')

    def _build_ref_popover_content(self):
        """Books on the left; right column flips between a Chapter grid and
        a Verse grid via a Stack. Left-click on a chapter navigates straight
        to that chapter; right-click slides the panel over to the verse
        picker for that chapter."""
        current_book    = BOOKS[self.book_drop.get_selected()]
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
            child = verse_flow.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                verse_flow.remove(child)
                child = nxt
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

        for name in BOOKS:
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

    def _toggle_appear_card(self, _w):
        open_ = not self._appear_revealer.get_reveal_child()
        self._appear_revealer.set_reveal_child(open_)
        # Chevron rotates ▸ → ▾ to signal the inline expansion.
        self._appear_arrow.set_from_icon_name(
            'pan-down-symbolic' if open_ else 'pan-end-symbolic')

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

    def _on_appear_width(self, scale):
        px = int(round(scale.get_value() / 20.0) * 20)
        settings.put('reading_width', px)
        self._width_val_lbl.set_text(f'{px}px')
        self.pane1.set_reading_width(px)
        self.pane2.set_reading_width(px)

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
        self._show_bookmarks(self._bookmark_btn)

    def _show_bookmarks(self, anchor):
        popover = Gtk.Popover()
        popover.set_parent(anchor)
        # Popovers using set_parent must be explicitly unparented in GTK4,
        # otherwise they accumulate as hidden children on each click.
        popover.connect('closed', lambda p: p.unparent())
        popover.set_child(self._build_bookmark_content(popover))
        popover.popup()

    def _build_bookmark_content(self, popover):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_size_request(260, -1)

        # Header — a quiet title so the popover rhymes with the Recent popover
        # (title + flat list, no separator rule).
        header = Gtk.Label(label=_('Bookmarks'), xalign=0)
        header.add_css_class('heading')
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_margin_top(8)
        header.set_margin_bottom(6)
        box.append(header)

        book    = BOOKS[self.book_drop.get_selected()]
        chapter = self.chapter_drop.get_selected() + 1
        add_content = Adw.ButtonContent(
            icon_name='starred-symbolic',
            label=_('Add {ref}').format(ref=f'{book} {chapter}'))
        add_content.set_halign(Gtk.Align.START)
        add_btn = Gtk.Button(child=add_content)
        add_btn.add_css_class('flat')
        add_btn.add_css_class('bookmark-add')
        add_btn.connect('clicked', self._add_bookmark, book, chapter, popover)
        box.append(add_btn)

        bmarks = bookmarks.get_all()
        if bmarks:
            scroll = Gtk.ScrolledWindow(vexpand=True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_max_content_height(300)
            scroll.set_propagate_natural_height(True)
            blist = Gtk.ListBox()
            blist.set_selection_mode(Gtk.SelectionMode.NONE)
            blist.add_css_class('navigation-sidebar')
            for i, bm in enumerate(bmarks):
                row = Gtk.ListBoxRow()
                row.add_css_class('bookmark-row')
                row._bookmark = bm
                rb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                lbl = Gtk.Label(label=bm['label'], xalign=0, hexpand=True)
                lbl.set_margin_start(12)
                lbl.set_margin_top(6)
                lbl.set_margin_bottom(6)
                rb.append(lbl)
                del_btn = Gtk.Button(icon_name='edit-delete-symbolic')
                del_btn.add_css_class('flat')
                del_btn.add_css_class('bookmark-del')
                del_btn.set_valign(Gtk.Align.CENTER)
                del_btn.set_margin_end(6)
                del_btn.set_tooltip_text(_('Remove bookmark'))
                set_accessible_label(del_btn, _('Remove bookmark'))
                del_btn.connect('clicked', self._remove_bookmark, i, popover)
                rb.append(del_btn)
                row.set_child(rb)
                blist.append(row)
            blist.connect('row-activated', self._on_bookmark_row_activated, popover)
            scroll.set_child(blist)
            box.append(scroll)
        return box

    def _add_bookmark(self, _btn, book, chapter, popover):
        bookmarks.add(book, chapter)
        popover.popdown()
        self._toast(_('Bookmarked {ref}').format(ref=f'{book} {chapter}'))

    def _on_bookmark_row_activated(self, _lb, row, popover):
        bm = getattr(row, '_bookmark', None)
        if bm is None:
            return
        popover.popdown()
        self._go_to(bm['book'], bm['chapter'], bm.get('verse'))

    def _remove_bookmark(self, _btn, index, popover):
        bookmarks.remove(index)
        popover.popdown()
        self._toast(_('Bookmark removed'))

    def _toast(self, message):
        t = Adw.Toast.new(message)
        t.set_timeout(2)
        self._toast_overlay.add_toast(t)

    def _on_cipher_error(self, module):
        """A pane detected unreadable (wrong-key) content for an encrypted
        module. Offer a one-tap path to fix the key."""
        if module in self._cipher_toasting:
            return
        self._cipher_toasting.add(module)
        t = Adw.Toast.new(
            _('{module}: content isn’t readable — the cipher key may be incorrect.').format(
                module=module))
        t.set_timeout(6)
        t.set_button_label(_('Edit Key'))
        t.connect('button-clicked', lambda _t: self._show_edit_cipher_key(module))
        t.connect('dismissed', lambda _t: self._cipher_toasting.discard(module))
        self._toast_overlay.add_toast(t)

    def _show_edit_cipher_key(self, module):
        dialog = Adw.AlertDialog(
            heading=_('Unlock Module'),
            body=_('Enter the cipher key for {module}. Keys are issued by the '
                   'module’s publisher (e.g. where you purchased it); '
                   'Scriptura does not provide them.').format(module=module))
        entry = Gtk.PasswordEntry(show_peek_icon=True)
        entry.set_property('placeholder-text', _('Paste the unlock key'))
        dialog.set_extra_child(entry)
        dialog.add_response('cancel', _('Cancel'))
        dialog.add_response('save', _('Save'))
        dialog.set_response_appearance('save', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('save')
        dialog.set_close_response('cancel')

        def on_resp(_d, resp):
            if resp == 'save':
                key = entry.get_text().strip()
                if key:
                    sword_bridge.set_cipher_key(module, key)
                    self._reload_module_panes(module)

        dialog.connect('response', on_resp)
        dialog.present(self)

    def _reload_module_panes(self, module):
        """Re-render any pane currently showing `module` (e.g. after the
        cipher key changed)."""
        for pane in (self.pane1, self.pane2):
            if pane._module == module:
                pane.force_navigate(pane._book, pane._chapter, None)

    def _set_reading_mode(self, on):
        """Distraction-free mode: hide the window header, pane toolbars, and
        any open overlay panels. Esc / F11 / mouse-to-top-edge to exit."""
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
            self._toast(_('Reading mode — Esc, F11, or hover the top edge to exit'))
        else:
            self._reading_hide_exit_btn()

    # Two thresholds (window-relative y in reading mode):
    #   TRIGGER zone (12px) — must enter this to start the 2s hover timer.
    #   KEEP-VISIBLE zone (80px) — once the button is revealed, the cursor
    #     can move down this far without dismissing it, giving the user
    #     enough room to actually reach the button to click it.
    _READING_TRIGGER_ZONE_PX = 12
    _READING_KEEP_ZONE_PX = 80
    _READING_HOVER_DELAY_MS = 2000

    # ── Split drag-grip ──────────────────────────────────────────────────────
    # The divider's centre x = 8px (paned margin-left) + position + 4px (half of
    # the 8px separator); the 6px grip is centred on it (−3).
    def _update_pane_grip(self, *_args):
        self._pane_grip.set_margin_start(int(8 + self._paned.get_position() + 4 - 3))

    def _on_grip_motion(self, _controller, x, _y):
        if not self.pane2.get_visible():        # single-pane: no divider
            self._pane_grip.set_visible(False)
            return
        center = 8 + self._paned.get_position() + 4
        near = abs(x - center) <= 10
        if near:
            self._update_pane_grip()
        self._pane_grip.set_visible(near)

    def _on_reading_mouse_motion(self, _controller, _x, y):
        if not getattr(self, '_reading_mode', False):
            return
        revealed = self._exit_reading_revealer.get_reveal_child()

        if revealed:
            # Already showing — keep visible while the cursor stays inside
            # the wide keep zone, hide once it wanders well below.
            if y > self._READING_KEEP_ZONE_PX:
                self._reading_hide_exit_btn()
            return

        # Not yet shown:
        # - Entering the narrow trigger zone arms the hover timer.
        # - Once armed, the timer survives small wobbles between the trigger
        #   zone and the keep zone. Only cancel when the cursor drifts past
        #   the keep zone entirely. Wayland compositors (Hyprland) report
        #   raw pointer motion with no smoothing — holding a cursor inside
        #   a 12 px strip for 2 s is effectively impossible, so the timer
        #   needs the wider keep zone as its cancel boundary.
        if y <= self._READING_TRIGGER_ZONE_PX:
            if self._reading_hover_timer is None:
                self._reading_hover_timer = GLib.timeout_add(
                    self._READING_HOVER_DELAY_MS, self._reading_show_exit_btn)
        elif y > self._READING_KEEP_ZONE_PX:
            self._reading_hide_exit_btn()

    def _reading_show_exit_btn(self):
        self._reading_hover_timer = None
        if getattr(self, '_reading_mode', False):
            self._exit_reading_revealer.set_reveal_child(True)
        return GLib.SOURCE_REMOVE

    def _reading_hide_exit_btn(self):
        if self._reading_hover_timer is not None:
            GLib.source_remove(self._reading_hover_timer)
            self._reading_hover_timer = None
        if hasattr(self, '_exit_reading_revealer'):
            self._exit_reading_revealer.set_reveal_child(False)

    # ── Lexicon toggle ────────────────────────────────────────────────────────

    def _on_lex_toggle(self, _btn):
        enabled = self.lex_toggle.get_active()
        self.pane1.set_lexicon_enabled(enabled)
        self.pane2.set_lexicon_enabled(enabled)

    def _on_view_mode(self, _btn):
        split = self._btn_split.get_active()
        settings.put('split_pane_mode', split)
        if self._panes_narrow:
            # View toggle is hidden while collapsed; the switcher only matters
            # in split mode (two distinct panes to flip between).
            self._narrow_switch_box.set_visible(split)
            self._apply_narrow_pane()
            return
        self.pane2.set_visible(split)
        self._swap_btn.set_sensitive(split)

    def _on_breakpoint_changed(self, *_args):
        """Map the single active breakpoint to the full adaptive state. None =
        wide; header breakpoint = condensed header; panes breakpoint = + single
        pane; ultra breakpoint (narrowest) = + fold the rest of the chrome."""
        bp = self.get_current_breakpoint()
        self._set_header_narrow(bp is not None)
        self._set_panes_narrow(bp in (self._bp_panes, self._bp_ultra))
        self._set_ultra_narrow(bp is self._bp_ultra)

    def _set_header_narrow(self, narrow):
        """Fold the secondary header controls (lexicon, bookmarks, swap) into
        the overflow ⋯ menu when the full header no longer fits, and restore
        them when it does."""
        if narrow == self._header_narrow:
            return
        self._header_narrow = narrow
        for w in (self.lex_toggle, self._bookmark_btn, self._swap_btn):
            w.set_visible(not narrow)
        self._overflow_btn.set_visible(narrow)

    def _set_panes_narrow(self, narrow):
        """Collapse to a single visible pane when two get too cramped. Reuses
        the single/split visibility plumbing; the user's wide-mode split choice
        is preserved and restored when the window widens again."""
        if narrow == self._panes_narrow:
            return
        self._panes_narrow = narrow
        split = self._btn_split.get_active()
        if narrow:
            self._view_box.set_visible(False)
            self._narrow_switch_box.set_visible(split)
            # No divider in single-pane: hide the drag grip (it would otherwise
            # linger at the far edge where the collapsed paned puts it).
            self._pane_grip.set_visible(False)
            self._apply_narrow_pane()
        else:
            self._narrow_switch_box.set_visible(False)
            self._view_box.set_visible(True)
            self.pane1.set_visible(True)
            self.pane2.set_visible(split)

    def _set_ultra_narrow(self, narrow):
        """Stricter desktop-narrow mode: fold the remaining nav/search/switcher
        into the overflow ⋯ too, leaving only menu · passage title · ⋯ · system
        buttons, and tighten the reading margins. Chrome gives way so the text
        keeps reflowing instead of clipping."""
        if narrow == self._ultra_narrow:
            return
        self._ultra_narrow = narrow
        for w in (self._back_btn, self._fwd_btn, self._search_btn):
            w.set_visible(not narrow)
        if narrow:
            self._narrow_switch_box.set_visible(False)
        else:
            # Restore the in-header switcher if we're still in collapsed-panes
            # territory and split; sync it to the active pane.
            show_switch = self._panes_narrow and self._btn_split.get_active()
            self._narrow_switch_box.set_visible(show_switch)
            if show_switch:
                btn = (self._narrow_btn2 if self._narrow_pane == 2
                       else self._narrow_btn1)
                if not btn.get_active():
                    btn.set_active(True)
        margin = 12 if narrow else 26
        self.pane1.set_reading_margin(margin)
        self.pane2.set_reading_margin(margin)
        # The 420px side search panel would overflow an ultra-narrow window, so
        # let it fill the width (full-width sheet) here; restore the docked
        # right panel otherwise. 420 mirrors SearchPanel's own request.
        if narrow:
            self._search_panel.set_size_request(-1, -1)
            self._search_revealer.set_halign(Gtk.Align.FILL)
        else:
            self._search_panel.set_size_request(420, -1)
            self._search_revealer.set_halign(Gtk.Align.END)

    def _apply_narrow_pane(self):
        """While collapsed, show exactly one pane: pane 1 in single mode, or the
        switcher-selected pane in split mode."""
        if not self._btn_split.get_active():
            self.pane1.set_visible(True)
            self.pane2.set_visible(False)
            return
        sel2 = self._narrow_pane == 2
        self.pane1.set_visible(not sel2)
        self.pane2.set_visible(sel2)

    def _on_narrow_switch(self, btn):
        if not btn.get_active():
            return
        self._select_narrow_pane(2 if btn is self._narrow_btn2 else 1)

    def _select_narrow_pane(self, n):
        """Show pane n while collapsed. Used by both the in-header switcher and
        the overflow rows (when the switcher itself is folded away in ultra)."""
        self._narrow_pane = n
        self._apply_narrow_pane()
        btn = self._narrow_btn2 if n == 2 else self._narrow_btn1
        if not btn.get_active():
            btn.set_active(True)

    def _build_overflow_content(self):
        """Popover body for the header overflow ⋯ menu: the secondary controls
        that don't fit a narrow header, as flat rows that delegate to the same
        handlers and then dismiss."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class('overflow-menu')

        def row(leading, label, handler, sensitive=True):
            btn = Gtk.Button()
            btn.add_css_class('flat')
            btn.set_sensitive(sensitive)
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            inner.append(leading)
            lbl = Gtk.Label(label=label, xalign=0, hexpand=True)
            inner.append(lbl)
            btn.set_child(inner)

            def on_click(_b, h=handler):
                self._overflow_pop.popdown()
                h()
            btn.connect('clicked', on_click)
            box.append(btn)
            return btn

        # Ultra-narrow: nav + search fold in here too (they stay in the header
        # at the wider narrow band).
        if self._ultra_narrow:
            row(Gtk.Image.new_from_icon_name('go-previous-symbolic'),
                _('Go back'), lambda: self._on_nav_back(None),
                sensitive=bool(self._nav_back))
            row(Gtk.Image.new_from_icon_name('go-next-symbolic'),
                _('Go forward'), lambda: self._on_nav_fwd(None),
                sensitive=bool(self._nav_fwd))
            row(Gtk.Image.new_from_icon_name('system-search-symbolic'),
                _('Search'), lambda: self._on_search_clicked(None))

        # Lexicon — leading glyph mirrors the header toggle (אΩ); a check marks
        # it when the lexicon is currently on.
        lex_glyph = Gtk.Label()
        lex_glyph.set_markup(
            '<span size="large">‎א</span><span size="small">Ω</span>')
        lex_row = row(lex_glyph, _('Greek / Hebrew lexicon'),
                      lambda: self.lex_toggle.set_active(
                          not self.lex_toggle.get_active()))
        if self.lex_toggle.get_active():
            lex_row.get_child().append(
                Gtk.Image.new_from_icon_name('object-select-symbolic'))

        row(Gtk.Image.new_from_icon_name('bookmark-new-symbolic'),
            _('Bookmarks'), lambda: self._show_bookmarks(self._overflow_btn))

        row(Gtk.Image.new_from_icon_name('object-flip-horizontal-symbolic'),
            _('Swap pane modules'), lambda: self._on_swap_clicked(None),
            sensitive=self._btn_split.get_active())

        # Ultra-narrow: the 1/2 pane switcher folds in here too (it's hidden
        # from the header at this width).
        if self._ultra_narrow and self._btn_split.get_active():
            row(Gtk.Label(label='1'), _('Show pane 1'),
                lambda: self._select_narrow_pane(1))
            row(Gtk.Label(label='2'), _('Show pane 2'),
                lambda: self._select_narrow_pane(2))
        return box

    def _on_swap_clicked(self, _btn):
        a = self.pane1._module
        b = self.pane2._module
        if a == b:
            return
        # No explicit position transfer needed: each _apply_module_change
        # snapshots the outgoing module's position into module_positions
        # before the change, then looks up the incoming module's saved
        # position and applies it. Cross-pane scroll memory comes from
        # the shared store, not from threading position through the swap.
        self.pane1._apply_module_change(b)
        self.pane2._apply_module_change(a)
        self._toast(_('Swapped: {a} ↔ {b}').format(a=a, b=b))

    def _on_close_request(self, _win):
        # Persist current session state so the next launch restores it.
        # close-request fires before destruction; return False to allow
        # the close to proceed.
        try:
            is_max = bool(self.is_maximized())
            settings.put('window_maximized', is_max)
            # When maximized, get_width/get_height return the maximized
            # size — saving that would lose the user's preferred restored
            # size. Only update the dimension keys when we have a real
            # unmaximized size to record.
            if not is_max:
                settings.put('window_width', int(self.get_width()))
                settings.put('window_height', int(self.get_height()))
            book, chapter = self._current_loc
            settings.put('last_book', book)
            settings.put('last_chapter', int(chapter))
            settings.put('pane1_module', self.pane1._module)
            settings.put('pane2_module', self.pane2._module)
            # Snapshot both panes' current positions into the shared
            # module_positions store so each module reopens where it
            # was last viewed regardless of which pane shows it next.
            self.pane1._save_position_to_module_state()
            self.pane2._save_position_to_module_state()
            # Force synchronous writes — the debounced timers above
            # would otherwise still be waiting when the process exits,
            # and the final session state would be lost.
            settings.flush()
            module_positions.flush()
        except Exception as e:
            _log.exception('close-save failed')
        return False

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
                         if not sword_bridge.is_internal_use(m)
                         and sword_bridge.module_type(m) == 'Biblical Texts']
                if texts:
                    mod = texts[0]
            self._search_panel.prepare_for_show(mod)
            self._search_revealer.set_reveal_child(True)

    def _hide_search(self):
        self._search_revealer.set_reveal_child(False)

    def _on_search_result(self, book, chapter, verse):
        # Stash the query on any pane whose current module matches the
        # search panel's module, so _apply_search_highlight can paint the
        # matched word(s) once the chapter re-renders.
        query = self._search_panel._entry.get_text().strip()
        case = self._search_panel._case_btn.get_active()
        if query:
            target_mod = self._search_panel._current_module()
            for pane in (self.pane1, self.pane2):
                if pane._module == target_mod:
                    pane._pending_search_highlight = (query, case)
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
        # Prefer pane2 in split view, but fall back to pane1 if pane2 is
        # hidden or showing a non-Bible resource (devotional, lexicon,
        # dictionary, generic book). If neither pane can navigate, do nothing.
        if self.pane2.get_visible() and self.pane2._is_verse_navigable():
            target = self.pane2
        elif self.pane1._is_verse_navigable():
            target = self.pane1
        else:
            return
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

        btn1 = Gtk.Button(label=_('Open in Pane 1'))
        btn1.add_css_class('flat')
        if not self.pane1._is_verse_navigable():
            btn1.set_sensitive(False)
            btn1.set_tooltip_text(_('Pane 1 is not showing a Bible or commentary'))
        else:
            btn1.connect('clicked', lambda _: (popover.popdown(),
                                               self.pane1.force_navigate(book, chapter, verse)))
        box.append(btn1)

        btn2 = Gtk.Button(label=_('Open in Pane 2'))
        btn2.add_css_class('flat')
        if not self.pane2.get_visible():
            btn2.set_sensitive(False)
            btn2.set_tooltip_text(_('Switch to split view to use Pane 2'))
        elif not self.pane2._is_verse_navigable():
            btn2.set_sensitive(False)
            btn2.set_tooltip_text(_('Pane 2 is not showing a Bible or commentary'))
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

    def _refresh_panes(self, module, book, chapter, verse):
        """Called by Study Journal when an annotation is deleted there.
        Surgical: refresh only the affected verse on whichever pane(s) are
        currently showing the same module/book/chapter. No full re-render,
        no scroll movement."""
        for pane in (self.pane1, self.pane2):
            if (pane._module == module
                and pane._book == book
                and pane._chapter == chapter):
                if verse is None:
                    pane._update_chapter_note_indicator()
                else:
                    pane._refresh_verse_annotation(verse)

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
        self._open_shortcuts_dialog()

    # ── About ─────────────────────────────────────────────────────────────────

    def _on_about_clicked(self, _btn):
        from _version import __version__
        dlg = Adw.AboutDialog(
            application_name='Scriptura',
            application_icon='page.codeberg.andresmessina.Scriptura',
            developer_name='Andres Messina',
            version=__version__,
            comments=_('GNOME-native Bible study with SWORD modules, '
                       'Strong’s lexicon, cross-references, and reading plans.'),
            website='https://codeberg.org/andresmessina/scriptura',
            issue_url='https://codeberg.org/andresmessina/scriptura/issues',
            license_type=Gtk.License.GPL_3_0,
            copyright='© 2026 Andres Messina',
        )
        dlg.add_credit_section(_('Data'), [
            'SWORD Project (CrossWire Bible Society) — modules and data layer',
            'OpenBible.info — cross-references and topical tags (CC-BY)',
            'Dodson Greek Lexicon — public-domain NT Greek definitions',
            'eBible.org — modern translation catalog and texts',
            'HistoricalChristianFaith Commentaries Database — historical commentary pack',
        ])
        dlg.add_acknowledgement_section(_('Built with'), [
            'GTK4 + libadwaita',
            'Python 3 / PyGObject',
            'Whoosh full-text search',
        ])
        dlg.present(self)

    # Display spec for the Keyboard Shortcuts dialog. Each row is
    # (description, kind, value):
    #   'action'  → value is an action name; its accelerator is read from
    #               _action_accels (single source of truth — can't drift).
    #   'accel'   → value is an accelerator string handled elsewhere
    #               (the contextual key controller).
    #   'literal' → value is plain text for input that isn't a key accel
    #               (mouse wheel gestures).
    _SHORTCUT_SECTIONS = [
        (N_('Navigation'), [
            (N_('Quick jump to any reference (e.g. John 3:16)'), 'action', 'goto'),
            (N_('Previous chapter'), 'action', 'prev-chapter'),
            (N_('Next chapter'), 'action', 'next-chapter'),
            (N_('Previous book'), 'action', 'prev-book'),
            (N_('Next book'), 'action', 'next-book'),
            (N_('First verse of current chapter'), 'accel', 'Home'),
            (N_('Last verse of current chapter'), 'accel', 'End'),
            (N_('Cycle chapters with the mouse wheel'), 'literal', N_('Scroll over title')),
        ]),
        (N_('Panes and view'), [
            (N_('Focus left pane'), 'action', 'focus-pane-1'),
            (N_('Focus right pane'), 'action', 'focus-pane-2'),
            (N_('Cycle between panes'), 'action', 'focus-other-pane'),
            (N_('Open / close search panel'), 'action', 'search'),
            (N_('Next search result'), 'action', 'search-next'),
            (N_('Previous search result'), 'action', 'search-prev'),
            (N_('Increase font size'), 'action', 'zoom-in'),
            (N_('Decrease font size'), 'action', 'zoom-out'),
            (N_('Zoom font (or pinch on touchpad)'), 'literal', N_('Ctrl + scroll')),
            (N_('Reading mode (chrome hidden)'), 'action', 'reading-mode'),
            (N_('Close search, jump bar, or menu'), 'accel', 'Escape'),
        ]),
        (N_('General'), [
            (N_('Copy selection with reference'), 'accel', '<Ctrl>c'),
            (N_('Keyboard shortcuts'), 'action', 'show-help-overlay'),
        ]),
    ]

    def _open_shortcuts_dialog(self):
        """Modern Adw.Dialog listing the shortcuts, with native key-cap
        rendering via Gtk.ShortcutLabel. (Gtk.ShortcutsWindow, the old
        standard, is deprecated since GTK 4.18 with no drop-in replacement,
        so this rolls a libadwaita-native equivalent.)"""
        dialog = Adw.Dialog()
        dialog.set_title(_('Keyboard Shortcuts'))
        dialog.set_content_width(460)
        dialog.set_content_height(620)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()

        for section, rows in self._SHORTCUT_SECTIONS:
            group = Adw.PreferencesGroup(title=_(section))
            for desc, kind, value in rows:
                row = Adw.ActionRow(title=_(desc))
                if kind == 'literal':
                    suffix = Gtk.Label(label=_(value))
                    suffix.add_css_class('dim-label')
                else:
                    accel = (self._action_accels[value][0]
                             if kind == 'action' else value)
                    suffix = Gtk.ShortcutLabel(accelerator=accel)
                suffix.set_valign(Gtk.Align.CENTER)
                row.add_suffix(suffix)
                group.add(row)
            page.add(group)

        toolbar_view.set_content(page)
        dialog.set_child(toolbar_view)
        dialog.present(self)

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
        # A verse link (a Strong's word-study jump, or a Scripture-in-Stone
        # artifact chip) needs a Bible on screen to land in. Word-study clicks
        # always come from a Bible pane, so one is already visible; but the
        # archaeology gallery isn't verse-keyed, so in single-pane mode there
        # may be no Bible showing — reveal one before navigating.
        self._ensure_bible_visible()
        self._go_to(book, chapter, verse)

    def _ensure_bible_visible(self):
        """Guarantee a visible, verse-navigable Bible pane to receive a verse
        jump. If none is on screen (e.g. the artifact gallery is the only pane),
        reveal the second pane and, if it isn't already a Bible, load one —
        keeping the gallery where it is."""
        panes = (self.pane1, self.pane2)
        if any(p.get_visible() and p._is_verse_navigable() for p in panes):
            return
        if not self._btn_split.get_active():
            self._btn_split.set_active(True)  # → _on_view_mode reveals pane2
        # Put the Bible in whichever pane isn't the gallery (defaults to pane2).
        target = self.pane2 if self.pane1._is_archaeology else self.pane1
        if not target._is_verse_navigable():
            bible = self._first_bible_module()
            if bible:
                target._apply_module_change(bible)

    def _on_open_artifact(self, source_pane, book, chapter, verse):
        """A 'related artifact' marker beside a Bible verse was clicked: show
        Scripture in Stone in the other pane and scroll it to that artifact."""
        gallery = self._ensure_artifacts_visible(source_pane)
        if gallery is not None:
            gallery._archaeology.scroll_to_verse(book, chapter, verse)

    def _ensure_artifacts_visible(self, source_pane):
        """Return a pane showing Scripture in Stone, loading it into the pane
        opposite the source (the Bible we clicked from) if it isn't open —
        mirrors _ensure_bible_visible in the other direction."""
        import archaeology_bridge
        for p in (self.pane1, self.pane2):
            if p.get_visible() and p._is_archaeology:
                return p
        other = self.pane2 if source_pane is self.pane1 else self.pane1
        if not other.get_visible():
            self._btn_split.set_active(True)  # → _on_view_mode reveals it
        if not other._is_archaeology:
            other._apply_module_change(archaeology_bridge.MODULE_KEY)
        return other

    def _first_bible_module(self):
        """A sensible Bible module key: prefer one a pane was already set to,
        else the first available Bible."""
        import content
        names = content.readable_module_names()
        for cand in (settings.get('pane2_module'), settings.get('pane1_module')):
            if cand in names and content.kind(cand) == 'bible':
                return cand
        for name in names:
            if content.kind(name) == 'bible':
                return name
        return None

    def _on_word_click(self, source_pane, strong_num):
        book    = source_pane._book
        chapter = source_pane._chapter
        verse   = source_pane._selected_verse
        has_morph = bool(source_pane._current_morph)

        # Reveal the lexicon panel with a spinner immediately so the
        # user gets feedback that their click registered. Real content
        # arrives via _show_lexicon once the SWORD fetch completes.
        source_pane.show_lexicon_loading(strong_num)

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
                _("Install StrongsGreek or StrongsHebrew from the Module Manager."))
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

        # ── Header: title + close only. Global utilities (theme, shortcuts,
        # about) now live in a bottom footer (Apple-sidebar style), which
        # declutters this strip and anchors the panel's otherwise-empty lower
        # area. No separator — the panel reads as one calm surface, grouped by
        # whitespace rather than a stack of rules.
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hbox.set_margin_start(14)
        hbox.set_margin_end(8)
        hbox.set_margin_top(10)
        hbox.set_margin_bottom(8)
        title = Gtk.Label(label=_('Menu'), hexpand=True)
        title.set_xalign(0)
        title.add_css_class('title-4')
        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.add_css_class('menu-utility-action')
        close_btn.set_tooltip_text(_('Close menu (Esc)'))
        set_accessible_label(close_btn, _('Close menu'))
        close_btn.connect('clicked', lambda _: self._menu_revealer.set_reveal_child(False))
        hbox.append(title)
        hbox.append(close_btn)
        panel.append(hbox)

        # Body — direct vertical Box so the day list at the bottom can
        # vexpand to fill remaining height. A wrapping ScrolledWindow
        # would give _body its natural height only, which would defeat
        # the vexpand. The day list is its own ScrolledWindow so long
        # plans (e.g. Bible-in-a-Year, 365 rows) still scroll inside.
        _body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        spacing=0, vexpand=True)
        panel.append(_body)

        # ── Navigation group (Study Journal / Modules) as coherent list rows
        # (icon + label + chevron), matching the app's Adw idiom rather than
        # plain grey buttons. ────────────────────────────────────────────────
        nav_group = Adw.PreferencesGroup()
        nav_group.set_margin_start(12)
        nav_group.set_margin_end(12)
        nav_group.set_margin_top(6)
        nav_group.set_margin_bottom(14)
        for icon, label, handler in [
            ('accessories-text-editor-symbolic', _('Study Journal'), self._on_journal_clicked),
            ('application-x-addon-symbolic',     _('Modules'),       self._on_modules_clicked),
        ]:
            row = Adw.ActionRow(title=label)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            chevron = Gtk.Image.new_from_icon_name('go-next-symbolic')
            chevron.add_css_class('dim-label')
            row.add_suffix(chevron)
            row.set_activatable(True)
            row.connect('activated', handler)
            nav_group.add(row)
        _body.append(nav_group)

        # ── Text Appearance: its own row whose chevron rotates (▸→▾) to expand
        # the inline appearance card just below — a real expander affordance,
        # not a → arrow that falsely implies push-navigation. ────────────────
        appear_group = Adw.PreferencesGroup()
        appear_group.set_margin_start(12)
        appear_group.set_margin_end(12)
        self._appear_row = Adw.ActionRow(title=_('Text Appearance'))
        self._appear_row.add_prefix(
            Gtk.Image.new_from_icon_name('preferences-desktop-font-symbolic'))
        self._appear_arrow = Gtk.Image.new_from_icon_name('pan-end-symbolic')
        self._appear_arrow.add_css_class('dim-label')
        self._appear_row.add_suffix(self._appear_arrow)
        self._appear_row.set_activatable(True)
        self._appear_row.connect('activated', self._toggle_appear_card)
        appear_group.add(self._appear_row)
        _body.append(appear_group)

        # ── Appearance card (inline revealer) ─────────────────────────────────
        self._appear_revealer = Gtk.Revealer()
        self._appear_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._appear_revealer.set_transition_duration(200)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class('card')
        card.add_css_class('appearance-card')
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
        font_row = _row(_('Font'))
        _prefix_labels = [_('System Serif'), _('System Sans-Serif')]
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
        size_row = _row(_('Size'))
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
        spacing_row = _row(_('Spacing'))
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

        # Reading column width — wider monitors benefit from a wider column.
        width_row = _row(_('Width'))
        self._width_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 540, 1600, 20)
        self._width_scale.set_hexpand(True)
        self._width_scale.set_draw_value(False)
        _cur_w = int(settings.get('reading_width') or 720)
        self._width_scale.set_value(_cur_w)
        self._width_val_lbl = Gtk.Label(label=f'{_cur_w}px')
        self._width_val_lbl.set_size_request(48, -1)
        self._width_scale.connect('value-changed', self._on_appear_width)
        width_row.append(self._width_scale)
        width_row.append(self._width_val_lbl)
        card.append(width_row)

        # Bold + Justify toggles
        toggle_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=8, homogeneous=True)
        self._bold_btn = Gtk.ToggleButton(label=_('Bold'))
        self._bold_btn.set_active(bool(settings.get('font_bold')))
        self._bold_btn.connect('toggled', self._on_appear_bold)
        self._justify_btn = Gtk.ToggleButton(label=_('Justified'))
        self._justify_btn.set_active(bool(settings.get('font_justify')))
        self._justify_btn.connect('toggled', self._on_appear_justify)
        toggle_row.append(self._bold_btn)
        toggle_row.append(self._justify_btn)
        card.append(toggle_row)

        # ── Text color ────────────────────────────────────────────────────────
        card.append(Gtk.Separator())
        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._color_check = Gtk.CheckButton(label=_('Custom text color'))
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

        # reading plan section label — grouped by whitespace, not a rule.
        plan_hdr = Gtk.Label(label=_('Reading Plan'), xalign=0)
        plan_hdr.add_css_class('heading')
        plan_hdr.set_margin_start(14)
        plan_hdr.set_margin_top(18)
        plan_hdr.set_margin_bottom(4)
        _body.append(plan_hdr)

        # plan selector
        plans = reading_plans.get_plans()
        plan_names = [_(p['name']) for p in plans]
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
        self._plan_start_btn = Gtk.Button(label=_('Start today'))
        self._plan_start_btn.add_css_class('suggested-action')
        self._plan_start_btn.connect('clicked', self._on_plan_start)
        self._plan_progress_lbl = Gtk.Label(hexpand=True, xalign=0)
        self._plan_reset_btn = Gtk.Button(label=_('Reset'))
        self._plan_reset_btn.add_css_class('destructive-action')
        self._plan_reset_btn.connect('clicked', self._on_plan_reset)
        self._plan_ctrl_box.append(self._plan_start_btn)
        self._plan_ctrl_box.append(self._plan_progress_lbl)
        self._plan_ctrl_box.append(self._plan_reset_btn)
        _body.append(self._plan_ctrl_box)

        # Separator + day list are only shown when a plan is active. Both
        # are stored as instance attrs so _refresh_plan_ui can toggle
        # them together — otherwise an empty boxed-list shows a stray
        # card-shaped background under "Start today".
        self._plan_sep = Gtk.Separator()
        _body.append(self._plan_sep)

        # Day list fills the remaining vertical space when shown so the
        # menu panel doesn't end abruptly. vexpand here only takes effect
        # when the day list is visible (plan active).
        self._plan_scroll = Gtk.ScrolledWindow(vexpand=True)
        self._plan_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._plan_scroll.set_min_content_height(200)
        self._day_listbox = Gtk.ListBox()
        self._day_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._day_listbox.add_css_class('boxed-list')
        self._day_listbox.connect('row-activated', self._on_day_row_activated)
        self._plan_scroll.set_child(self._day_listbox)
        _body.append(self._plan_scroll)

        # ── Footer: global utilities pinned to the bottom. _body above is
        # vexpand, so this stays anchored at the panel's foot — Apple-sidebar
        # placement that also fills the lower void when no plan is active.
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.add_css_class('menu-footer')
        footer.set_margin_start(12)
        footer.set_margin_end(8)
        footer.set_margin_top(8)
        footer.set_margin_bottom(10)

        theme_picker = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        theme_picker.add_css_class('linked')
        self._theme_light = Gtk.ToggleButton(icon_name='weather-clear-symbolic')
        self._theme_light.set_tooltip_text(_('Light theme'))
        set_accessible_label(self._theme_light, _('Light theme'))
        self._theme_dark = Gtk.ToggleButton(icon_name='weather-clear-night-symbolic')
        self._theme_dark.set_tooltip_text(_('Dark theme'))
        set_accessible_label(self._theme_dark, _('Dark theme'))
        # Bundled half-filled "auto" disc — light half + dark half = "follow
        # system". Bundled (like the globe/keyboard symbolics) because this
        # theme's platform system/monitor icons hardcode a fill and render
        # blank; ours is fill-only so GTK4 recolors it reliably.
        self._theme_system = Gtk.ToggleButton(
            icon_name='scriptura-theme-system-symbolic')
        self._theme_system.set_tooltip_text(_('Follow system theme'))
        set_accessible_label(self._theme_system, _('Follow system theme'))
        cur_scheme = settings.get('color_scheme') or 'default'
        self._theme_light.set_active(cur_scheme == 'light')
        self._theme_dark.set_active(cur_scheme == 'dark')
        self._theme_system.set_active(cur_scheme not in ('light', 'dark'))
        for _tb in (self._theme_light, self._theme_dark, self._theme_system):
            _tb.add_css_class('menu-theme-toggle')
            _tb.set_valign(Gtk.Align.CENTER)
            _tb.connect('clicked', self._on_appear_theme)
            theme_picker.append(_tb)
        footer.append(theme_picker)

        footer.append(Gtk.Box(hexpand=True))  # spacer

        hotkeys_btn = Gtk.Button(icon_name='scriptura-keyboard-symbolic')
        hotkeys_btn.add_css_class('flat')
        hotkeys_btn.add_css_class('menu-utility-action')
        hotkeys_btn.set_tooltip_text(_('Keyboard shortcuts'))
        set_accessible_label(hotkeys_btn, _('Keyboard shortcuts'))
        hotkeys_btn.connect('clicked', self._on_hotkeys_clicked)
        footer.append(hotkeys_btn)

        about_btn = Gtk.Button(icon_name='help-about-symbolic')
        about_btn.add_css_class('flat')
        about_btn.add_css_class('menu-utility-action')
        about_btn.set_tooltip_text(_('About Scriptura'))
        set_accessible_label(about_btn, _('About Scriptura'))
        about_btn.connect('clicked', self._on_about_clicked)
        footer.append(about_btn)

        panel.append(footer)

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
        self._plan_desc_lbl.set_text(_(desc) if desc else '')

        # controls
        plan_active = bool(start_date and reading_plans.get_active()[0] == sel_id)
        if plan_active:
            self._plan_start_btn.set_visible(False)
            completed = reading_plans.get_completed(sel_id)
            total = next((p['total_days'] for p in plans if p['id'] == sel_id), 0)
            self._plan_progress_lbl.set_text(ngettext(
                '{done} / {total} day', '{done} / {total} days', total).format(
                    done=len(completed), total=total))
            self._plan_progress_lbl.set_visible(True)
            self._plan_reset_btn.set_visible(True)
            self._populate_day_list(sel_id, start_date)
        else:
            self._plan_start_btn.set_visible(True)
            self._plan_progress_lbl.set_visible(False)
            self._plan_reset_btn.set_visible(False)
            self._clear_day_list()
        # The boxed-list day view and its leading separator only appear
        # for an active plan — otherwise an empty card-shaped background
        # would sit awkwardly under the "Start today" button.
        self._plan_sep.set_visible(plan_active)
        self._plan_scroll.set_visible(plan_active)

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
        day_lbl = Gtk.Label(label=_('Day {n}').format(n=idx + 1), xalign=0)
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
        self._plan_progress_lbl.set_text(ngettext(
            '{done} / {total} day', '{done} / {total} days', total).format(
                done=len(completed), total=total))

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
