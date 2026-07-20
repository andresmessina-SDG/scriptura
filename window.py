import json
import logging
import re
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')
import datetime
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, PangoCairo
from gtk_utils import clear_children
import sword_bridge
import settings
import devotional_audio
import tasks
import motion
import night_light
import module_positions
import onboarding
import backup
import bookmarks
import reading_plans
import annotations
import search_controller
from pane import (BiblePane, DROPCAP_GOLD_DARK, DROPCAP_GOLD_LIGHT,
                  auto_reading_ink, dropcap_color_hex)
from present import PresentView
from today_page import TodayView, fetch_epigraph
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


# Canonical English book names. These double as keys (SWORD VerseKey text,
# saved positions/bookmarks, BOOKS.index lookups), so the list itself stays
# English; N_() only marks them for translator extraction. The translated
# form is fetched at display time via book_label().
BOOKS = [
    N_('Genesis'), N_('Exodus'), N_('Leviticus'), N_('Numbers'), N_('Deuteronomy'),
    N_('Joshua'), N_('Judges'), N_('Ruth'), N_('1 Samuel'), N_('2 Samuel'),
    N_('1 Kings'), N_('2 Kings'), N_('1 Chronicles'), N_('2 Chronicles'),
    N_('Ezra'), N_('Nehemiah'), N_('Esther'), N_('Job'), N_('Psalms'), N_('Proverbs'),
    N_('Ecclesiastes'), N_('Song of Solomon'), N_('Isaiah'), N_('Jeremiah'),
    N_('Lamentations'), N_('Ezekiel'), N_('Daniel'), N_('Hosea'), N_('Joel'), N_('Amos'),
    N_('Obadiah'), N_('Jonah'), N_('Micah'), N_('Nahum'), N_('Habakkuk'), N_('Zephaniah'),
    N_('Haggai'), N_('Zechariah'), N_('Malachi'),
    N_('Matthew'), N_('Mark'), N_('Luke'), N_('John'), N_('Acts'), N_('Romans'),
    N_('1 Corinthians'), N_('2 Corinthians'), N_('Galatians'), N_('Ephesians'),
    N_('Philippians'), N_('Colossians'), N_('1 Thessalonians'), N_('2 Thessalonians'),
    N_('1 Timothy'), N_('2 Timothy'), N_('Titus'), N_('Philemon'), N_('Hebrews'),
    N_('James'), N_('1 Peter'), N_('2 Peter'), N_('1 John'), N_('2 John'), N_('3 John'),
    N_('Jude'), N_('Revelation'),
]


class _FractionPaned(Gtk.Paned):
    """Paned that keeps its divider at a fraction of its own width.

    Without an explicit position, GtkPaned re-derives the split from the
    children's natural widths — so content changes inside a pane (the
    lexicon panel appearing, a definition loading) visibly wobbled both
    reading columns. Here the divider follows a fraction instead: 50%
    until the user drags it, then theirs; re-applied whenever the paned's
    width changes and immune to child size requests."""

    __gtype_name__ = 'ScripturaFractionPaned'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._fraction = 0.5
        self._applying = False
        self.connect('notify::position', self._record_drag)

    def _record_drag(self, *_args):
        w = self.get_width()
        if w > 0 and not self._applying:
            self._fraction = self.get_position() / w

    def do_size_allocate(self, width, height, baseline):
        target = round(width * self._fraction)
        if width > 0 and self.get_position() != target:
            self._applying = True
            self.set_position(target)
            self._applying = False
        Gtk.Paned.do_size_allocate(self, width, height, baseline)


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
        # Warm SWORD's one-time versification init (~150 ms, first VerseKey)
        # on a background thread so it overlaps _build_ui instead of running
        # serially before first paint. _load_all_panes joins it before the
        # first main-thread SWORD call.
        sword_bridge.start_warm()
        # Restore last book/chapter — book validated against BOOKS here;
        # the chapter is range-clamped in _load_all_panes (the clamp needs
        # chapter_count, i.e. the SWORD init warming above).
        saved_book = settings.get('last_book')
        saved_chap = settings.get('last_chapter')
        if saved_book in BOOKS and isinstance(saved_chap, int) and saved_chap >= 1:
            self._current_loc = (saved_book, saved_chap)
        else:
            self._current_loc = ('Genesis', 1)
        self._updating_plan = False
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
        # Evening paper (opt-in): follow Night Light once the panes exist.
        self._night_monitor = None
        self._evening_now = 0.0
        if settings.get('evening_paper'):
            self._start_evening_paper()
        self.connect('close-request', self._on_close_request)
        if self._startup_devt_module:
            self._startup_navigate_to_devotional_ref(self._startup_devt_module)
        # Today page content — after the panes so its paper mirrors pane 1.
        self._today_suppress = False
        self._today_dark_handler = None
        if self._today_view is not None:
            self._populate_today()
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

        # Footnotes toggle — an italic f wearing the asterisk, print's
        # oldest footnote mark (a bare dagger was tried and reads as a +
        # in this theme's font; a bare * as "required"). Two-glyph shape
        # mirrors the אΩ toggle it's linked with. Persisted (unlike the
        # lexicon): footnotes are reading content, so the preference
        # carries across sessions.
        self.fnote_toggle = Gtk.ToggleButton()
        fn_lbl = Gtk.Label()
        # 122%/102% ≈ the x-large/large pair scaled down 15% so the pair
        # sits flush beside the אΩ toggle.
        fn_lbl.set_markup('<span size="122%"><i>f</i></span>'
                          '<span size="102%">*</span>')
        self.fnote_toggle.set_child(fn_lbl)
        self.fnote_toggle.add_css_class('flat')
        self.fnote_toggle.add_css_class('scriptura-lex-toggle')
        self.fnote_toggle.set_tooltip_text(
            _("Footnotes — the translation's own notes, marked in the text"))
        set_accessible_label(self.fnote_toggle, _('Footnotes'))
        self.fnote_toggle.set_active(bool(settings.get('show_footnotes')))
        self.fnote_toggle.connect('toggled', self._on_fnote_toggle)

        # Cross-references toggle — print's reference mark (※), third of the
        # reading-tools glyphs. Persisted like footnotes: whether verse
        # clicks summon the cross-reference bar is a reading preference.
        self.xref_toggle = Gtk.ToggleButton()
        xr_lbl = Gtk.Label()
        # Single mark scaled to sit flush with the f* pair's cap height.
        xr_lbl.set_markup('<span size="122%">※</span>')
        self.xref_toggle.set_child(xr_lbl)
        self.xref_toggle.add_css_class('flat')
        self.xref_toggle.add_css_class('scriptura-lex-toggle')
        self.xref_toggle.set_tooltip_text(
            _('Cross-references — related verses appear when you tap a verse'))
        set_accessible_label(self.xref_toggle, _('Cross-references'))
        self.xref_toggle.set_active(bool(settings.get('show_crossrefs')))
        self.xref_toggle.connect('toggled', self._on_xref_toggle)

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

        # Reading-tools cluster at the inner edge of the right cluster: the
        # אΩ lexicon toggle is the anchor (the glyph is kept deliberately —
        # it names the two languages it covers, which a generic dictionary
        # icon would lose); the f* footnotes and ※ cross-references toggles
        # bloom out of a Revealer while the pointer or keyboard focus is on
        # the cluster, and fold away after a grace period — the full
        # instrument appears only when summoned. The bloom opens LEFTWARD
        # (revealer packed before the anchor): the cluster's right edge is
        # pinned against the swap button, so a rightward bloom would shove
        # the anchor out from under the hovering pointer. Clicking אΩ still
        # toggles the lexicon directly; the click's focus also blooms the
        # cluster, which is the touch/keyboard path to the siblings.
        self._tools_revealer = Gtk.Revealer()
        self._tools_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_LEFT)
        self._tools_revealer.set_transition_duration(motion.DURATION_SHORT)
        tools_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        tools_inner.append(self.xref_toggle)
        tools_inner.append(self.fnote_toggle)
        self._tools_revealer.set_child(tools_inner)
        self._study_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._study_box.append(self._tools_revealer)
        self._study_box.append(self.lex_toggle)
        set_accessible_label(self._study_box, _('Reading tools'))
        self._tools_fold_timer = 0
        self._tools_hover = Gtk.EventControllerMotion.new()
        self._tools_hover.connect('enter', self._tools_bloom)
        self._tools_hover.connect('leave', self._tools_arm_fold)
        self._study_box.add_controller(self._tools_hover)
        self._tools_focus = Gtk.EventControllerFocus.new()
        self._tools_focus.connect('enter', self._tools_bloom)
        self._tools_focus.connect('leave', self._tools_arm_fold)
        self._study_box.add_controller(self._tools_focus)
        header.pack_end(self._study_box)

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

        # First-run discoverability. The controller decides once-per-hint;
        # its present callback resolves _toast_overlay lazily (built below),
        # so it's safe to construct here, before the panes that fire hints.
        self._hints = onboarding.HintController(self._present_hint_toast)

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
                               on_module_switched=self._update_fnote_sensitivity,
                               on_hint=self._hints.maybe_fire,
                               on_open_verse=self._open_verse_in_pane2,
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
                               on_module_switched=self._update_fnote_sensitivity,
                               on_hint=self._hints.maybe_fire,
                               on_open_verse=self._open_verse_in_pane2,
                               pane_id=2)
        # Initial f* sensitivity for the startup modules — the pane
        # callbacks above only fire on later switches.
        self._update_fnote_sensitivity()

        self._paned = _FractionPaned(orientation=Gtk.Orientation.HORIZONTAL,
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
        # ── Search overlay (Adw.OverlaySplitView, end-side sidebar) ──────────
        # Same permanently-collapsed pattern as the menu split below: the
        # panel overlays the reading area from the right with a scrim and
        # click-out dismissal, no reflow. Width is governed by the split
        # view's min/max (≈ the panel's old 420px request) and shrinks to
        # the window on ultra-narrow — the old halign-FILL sheet hack and
        # the drag-resize handle are both retired.
        self._search_panel = SearchPanel(
            on_result_clicked=self._on_search_result,
            on_close=self._hide_search,
        )
        self._search_split = Adw.OverlaySplitView()
        # .search-split scopes the scrim-base + gizmo-silencing CSS (the
        # rounded-corner two-layer trick) — see style.css.
        self._search_split.add_css_class('search-split')
        self._search_split.set_collapsed(True)
        self._search_split.set_show_sidebar(False)
        self._search_split.set_sidebar_position(Gtk.PackType.END)
        self._search_split.set_min_sidebar_width(420)
        self._search_split.set_max_sidebar_width(460)
        self._search_split.set_sidebar(self._search_panel)

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

        # ── App menu panel (Adw.OverlaySplitView sidebar) ─────────────────────
        # CSS for .jump-bar, .reading-exit-btn, .bible-view, .lex-panel /
        # .ws-panel, .appearance-card, and .plan-today lives in
        # data/style.css (loaded once at startup by styles.load_app_css
        # from main.py).
        #
        # Kept permanently *collapsed*: the sidebar presents as an overlay
        # above the reading area (with a scrim and click-out dismissal), so
        # opening the menu never reflows the reading column — same surface
        # semantics as the old SLIDE_RIGHT Revealer, with native motion and
        # edge-swipe gestures for free. Trade accepted: the old drag-resize
        # handle is gone (OSV sidebars aren't user-resizable; width is pinned
        # around the previous 340px default).
        self._menu_split = Adw.OverlaySplitView()
        # .menu-split scopes the CSS that re-applies the house floating-card
        # chrome (rounded right edge + hairline) to the sidebar pane — see
        # the overlay-split-view rules in style.css.
        self._menu_split.add_css_class('menu-split')
        self._menu_split.set_collapsed(True)
        self._menu_split.set_show_sidebar(False)
        self._menu_split.set_min_sidebar_width(340)
        self._menu_split.set_max_sidebar_width(400)
        # The panel itself (~80 ms of widgets) is built lazily after first
        # paint — see _ensure_menu_panel; an idle kicks it off so it's
        # ready long before the user can reach the menu button.
        self._menu_panel_built = False
        GLib.idle_add(self._ensure_menu_panel)

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

        # Presentation surface — an opaque fullscreen page laid over the reading
        # panes. Hidden until F5 / present mode; covers the panes so exiting is
        # just a hide (the reading view underneath is never torn down).
        self._present_view = PresentView(on_cross=self._present_cross)
        self._present_view.set_visible(False)
        overlay.add_overlay(self._present_view)
        self._build_present_controls(overlay)

        # Today page (opt-out via the menu's "Open to Today" switch): a calm
        # pre-reading landing laid over the panes, shown once per session at
        # open and dismissed by Esc or any action. Built only when it will
        # show; a `bible:` URI launch skips it (the user asked for a verse).
        self._today_view = None
        self._today_revealer = None
        if settings.get('open_to_today') and not self._startup_ref:
            self._today_view = TodayView(
                on_begin=self._on_today_begin,
                on_continue=self._on_today_continue,
                on_choose_plans=self._on_today_choose_plans,
                on_listen=self._on_today_listen)
            self._today_revealer = Gtk.Revealer()
            self._today_revealer.set_transition_type(
                Gtk.RevealerTransitionType.SLIDE_DOWN)
            self._today_revealer.set_transition_duration(motion.DURATION_STANDARD)
            self._today_revealer.set_child(self._today_view)
            self._today_revealer.set_reveal_child(True)
            overlay.add_overlay(self._today_revealer)

        # The quick-jump bar sits on top of every other overlay — including the
        # opaque presentation surface — so Ctrl+L is never occluded (added here,
        # after the present view, because Gtk.Overlay z-order follows add order).
        overlay.add_overlay(self._jump_revealer)

        self._reading_hover_timer = None
        # Attach the motion controller to the window itself so that the
        # event reaches us regardless of which child widget (TextView,
        # Paned divider, scrollbars) the cursor is currently over. We also
        # listen for `enter` so the first entry into the hot zone counts,
        # not only subsequent movement.
        self._reading_overlay_for_motion = overlay  # stash for coord remap
        # (named reading_motion, not `motion` — that shadows the motion-tokens
        # module for this whole function scope)
        reading_motion = Gtk.EventControllerMotion.new()
        reading_motion.connect('motion', self._on_reading_mouse_motion)
        reading_motion.connect('enter', self._on_reading_mouse_motion)
        reading_motion.connect('leave', lambda _c: self._reading_hide_exit_btn())
        self.add_controller(reading_motion)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(overlay)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(self._toast_overlay)
        main_box.append(self._crossref_revealer)
        # Both sidebars slide over everything below the header (reading
        # area, side overlays, cross-ref bar): the search split wraps the
        # content stack, and the menu split wraps the search split — two
        # nested overlay views, one per edge.
        self._search_split.set_content(main_box)
        self._menu_split.set_content(self._search_split)
        toolbar_view.set_content(self._menu_split)

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
            ('reading-mode', ['F11'], self._toggle_reading_mode),
            ('present-mode', ['F5'], self._toggle_present_mode),
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
            if self._search_split.get_show_sidebar():
                self._hide_search()
                return True
            if self._menu_split.get_show_sidebar():
                self._menu_split.set_show_sidebar(False)
                return True
            if self._today_revealer is not None:
                self._dismiss_today()
                return True
            if getattr(self, '_present_mode', False):
                self._set_present_mode(False)
                return True
            if getattr(self, '_reading_mode', False):
                self._set_reading_mode(False)
                return True
            return False

        # Presentation stepping: while presenting, the passage is paged and
        # these keys walk it. Gate on the jump bar being closed (the only text
        # entry over the surface — Ctrl+L) rather than on focus, so stepping
        # works regardless of which widget holds focus, and only pauses while
        # you're actually typing a reference.
        if (getattr(self, '_present_mode', False) and not alt
                and not self._jump_revealer.get_reveal_child()):
            pv = self._present_view
            # Size nudge honours both plain +/- and the universal Ctrl +/- zoom
            # idiom, so it fires whether or not Ctrl is held.
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                pv.bump_size(1)
                return True
            if keyval in (Gdk.KEY_minus, Gdk.KEY_underscore,
                          Gdk.KEY_KP_Subtract):
                pv.bump_size(-1)
                return True
            # Stepping / granularity are plain (unmodified) keys, so Ctrl+F,
            # Ctrl+L, Ctrl+1/2 etc. still pass through in present mode.
            if not ctrl:
                action = None
                if keyval in (Gdk.KEY_Right, Gdk.KEY_space, Gdk.KEY_Page_Down):
                    action = pv.step_next
                elif keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
                    action = pv.step_prev
                elif keyval == Gdk.KEY_Home:
                    action = pv.step_home
                elif keyval == Gdk.KEY_End:
                    action = pv.step_end
                elif keyval in (Gdk.KEY_v, Gdk.KEY_V):
                    action = pv.toggle_granularity
                elif keyval in (Gdk.KEY_p, Gdk.KEY_P):
                    self._present_toggle_parallel(not pv.parallel)
                    return True
                if action is not None:
                    action()
                    # Keep the strip's toggles in sync (e.g. after 'v'); the
                    # strip itself is shown by pointer position, not keys.
                    self._sync_present_controls()
                    return True

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
        if (self._search_split.get_show_sidebar()
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
            self._search_split.set_show_sidebar(True)
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
        # Any navigation is "an action" — it takes the reader in, so the
        # Today page slides away (unless this is the programmatic startup
        # devotional auto-nav, which happens beneath it).
        if not self._today_suppress:
            self._dismiss_today()
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
        self.book_drop.set_selected(BOOKS.index(book))
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

        for name in BOOKS:
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

    def _startup_navigate_to_devotional_ref(self, devt_module):
        """Background thread: parse today's devotional, navigate pane1 to its passage."""
        import datetime as _dt
        date_obj = _dt.date.today()
        def go_quiet(book, chapter, verse):
            # Programmatic — must not dismiss the Today page above it.
            self._today_suppress = True
            try:
                self._go_to(book, chapter, verse, record=False)
            finally:
                self._today_suppress = False
            return GLib.SOURCE_REMOVE

        def fetch():
            raw    = sword_bridge.get_devotional_raw(devt_module, date_obj)
            result = sword_bridge.parse_devotional_refs(raw)
            if result:
                book, chapter, verse = result
                GLib.idle_add(go_quiet, book, chapter, verse)
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
            # Sync the slider without re-firing _on_appear_size, which would
            # redundantly re-apply and re-save the same value.
            self._size_scale.handler_block(self._size_scale_handler)
            self._size_scale.set_value(new_size)
            self._size_scale.handler_unblock(self._size_scale_handler)
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

    # Curated reading "papers" per resolved appearance: (label, swatch, store).
    # Default stores None (warm paper in light, @view_bg_color in dark). Light
    # papers use the leading readers' values — Apple Books off-white #fbfbfb
    # (pure #fff glares) and warm gold sepia #f8f1e3, plus a restful pale-green.
    # The reading ink is auto-derived from the paper (auto_reading_ink), so each
    # chip previews its pairing — the paper name in that paper's ink — without a
    # separate ink list. Labels N_()-marked for extraction, translated at build.
    _PAPER_LIGHT = [
        (N_('Paper'), '#f7f4ee', None),
        (N_('White'), '#fbfbfb', '#fbfbfb'),
        (N_('Sepia'), '#f8f1e3', '#f8f1e3'),
        (N_('Green'), '#dce8d0', '#dce8d0'),
    ]
    _PAPER_DARK = [
        (N_('Slate'),    '#1e1e1e', None),
        (N_('Charcoal'), '#2a2622', '#2a2622'),
        (N_('Black'),    '#000000', '#000000'),
    ]

    def _current_mode_key(self):
        return f'text_color_{settings.get("color_scheme") or "default"}'

    def _current_bg_key(self):
        return f'reading_bg_{settings.get("color_scheme") or "default"}'

    def _resolved_dark(self):
        # Explicit schemes resolve deterministically; System follows appearance.
        scheme = settings.get('color_scheme') or 'default'
        if scheme == 'light':
            return False
        if scheme == 'dark':
            return True
        return Adw.StyleManager.get_default().get_dark()

    def _papers(self):
        return self._PAPER_DARK if self._resolved_dark() else self._PAPER_LIGHT

    @staticmethod
    def _ink_for(hex_bg):
        """Pick a legible label ink (warm-dark or warm-light) for a swatch fill
        by its perceived luminance."""
        r, g, b = (int(hex_bg[i:i + 2], 16) for i in (1, 3, 5))
        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return '#2b2620' if lum > 0.55 else '#e8e0d4'

    def _make_swatch(self, label, fill_hex, ink_hex, size, tooltip, on_click,
                     extra_class=None):
        """A round colour chip: `fill_hex` background, `label` drawn in `ink_hex`
        (a paper name in that paper's ink). Fixed square + centred so it stays
        circular in its homogeneous cell."""
        btn = Gtk.Button(label=label)
        btn.add_css_class('paper-swatch')
        for cls in (extra_class or '').split():
            btn.add_css_class(cls)
        btn.set_size_request(size, size)
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(tooltip)
        set_accessible_label(btn, tooltip)
        prov = Gtk.CssProvider()
        prov.load_from_data(
            (f'button.paper-swatch {{ background-color: {fill_hex}; '
             f'color: {ink_hex}; }}').encode())
        btn.get_style_context().add_provider(
            prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        btn.connect('clicked', on_click)
        return btn

    def _rebuild_colour_row(self):
        """One row of theme chips for the active scheme. Each preset chip shows
        its paper name in that paper's auto ink, on the paper fill — so the chip
        previews the whole pairing. The active paper rings it; a custom text or
        paper instead rings the dashed Custom chip, which opens a popover to
        override either colour."""
        # The drop-cap swatch is scheme-sensitive too (gold default differs
        # per scheme); it builds after the colour row, hence the guard.
        if getattr(self, '_dropcap_swatch_css', None) is not None:
            self._update_dropcap_swatch()
        child = self._paper_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._paper_box.remove(child)
            child = nxt
        paper_stored = settings.get(self._current_bg_key())
        ink_stored = settings.get(self._current_mode_key())
        pnorm = (paper_stored or '').lower()
        papers = self._papers()
        preset_stores = {(v or '').lower() for _l, _s, v in papers}
        # "Custom" is active when the ink is overridden, or the paper is off-preset.
        custom = bool(ink_stored) or (bool(paper_stored) and pnorm not in preset_stores)
        for label, sw, val in papers:
            chip = self._make_swatch(
                _(label), sw, auto_reading_ink(sw), 56, _(label),
                lambda b, v=val: self._on_paper_preset(v))
            if not custom and (val or '').lower() == pnorm:
                chip.add_css_class('selected')
            self._paper_box.append(chip)
        # Dashed Custom chip: previews the active custom combo, or a neutral
        # opener. Click → popover to set a custom text and/or paper colour.
        if custom:
            eff_paper = paper_stored or papers[0][1]
            ccustom = self._make_swatch(
                _('Custom'), eff_paper, ink_stored or auto_reading_ink(eff_paper),
                56, _('Custom colours'), self._on_custom_clicked,
                extra_class='custom-swatch')
            ccustom.add_css_class('selected')
        else:
            neutral = '#3a3a3a' if self._resolved_dark() else '#e0ddd6'
            ccustom = self._make_swatch(
                _('Custom'), neutral, self._ink_for(neutral), 56,
                _('Custom colours'), self._on_custom_clicked,
                extra_class='custom-swatch')
        self._paper_box.append(ccustom)

    def _apply_paper(self, value):
        settings.put(self._current_bg_key(), value)
        self.pane1.set_appearance(bg_color=value)
        self.pane2.set_appearance(bg_color=value)

    def _apply_ink(self, value):
        settings.put(self._current_mode_key(), value)
        self.pane1.set_appearance(text_color=value)
        self.pane2.set_appearance(text_color=value)

    def _on_paper_preset(self, store_val):
        # A preset is a coordinated theme: set the paper and return ink to auto.
        self._apply_paper(store_val)
        self._apply_ink(None)
        self._rebuild_colour_row()

    def _on_custom_clicked(self, btn):
        # The single Custom chip fans out to either override via a mini-picker:
        # a live "Aa" preview of the current combo over a Text and a Paper row,
        # each showing the current colour and opening the colour dialog. The
        # dialog is parented to the window (not the popover), so dismissing the
        # popover can't orphan it; unparent is deferred to idle to avoid
        # destroying a row mid-click.
        paper_stored = settings.get(self._current_bg_key())
        ink_stored = settings.get(self._current_mode_key())
        eff_paper = paper_stored or self._papers()[0][1]
        eff_ink = ink_stored or auto_reading_ink(eff_paper)

        pop = Gtk.Popover()
        pop.set_parent(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(8)

        preview = Gtk.Label(label=_('Aa'))
        preview.add_css_class('custom-preview')
        pv = Gtk.CssProvider()
        pv.load_from_data(
            (f'label.custom-preview {{ background-color: {eff_paper}; '
             f'color: {eff_ink}; }}').encode())
        preview.get_style_context().add_provider(
            pv, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box.append(preview)

        box.append(self._custom_pick_row(
            eff_ink, _('Text colour'), self._on_ink_custom_clicked, pop))
        box.append(self._custom_pick_row(
            eff_paper, _('Paper colour'), self._on_paper_custom_clicked, pop))

        pop.set_child(box)
        pop.connect('closed', lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _custom_pick_row(self, colour, label, handler, pop):
        """A popover row: a swatch of the current colour + label; opens the
        colour dialog (window-parented) after dismissing the popover."""
        row = Gtk.Button()
        row.add_css_class('flat')
        row.add_css_class('custom-pick-row')
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sw = Gtk.Box()
        sw.add_css_class('mini-swatch')
        sw.set_size_request(18, 18)
        sw.set_valign(Gtk.Align.CENTER)
        prov = Gtk.CssProvider()
        prov.load_from_data(f'box.mini-swatch {{ background-color: {colour}; }}'.encode())
        sw.get_style_context().add_provider(
            prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        inner.append(sw)
        inner.append(Gtk.Label(label=label, xalign=0, hexpand=True))
        row.set_child(inner)
        row.connect('clicked', lambda _x: (pop.popdown(), handler(None)))
        return row

    def _update_dropcap_swatch(self):
        hexcol = dropcap_color_hex(Adw.StyleManager.get_default().get_dark())
        self._dropcap_swatch_css.load_from_data(
            f'box.mini-swatch {{ background-color: {hexcol}; }}'.encode())

    def _apply_dropcap_color(self, value):
        settings.put('dropcap_color', value)
        self._update_dropcap_swatch()
        self.pane1.refresh_dropcap_color()
        self.pane2.refresh_dropcap_color()

    def _on_dropcap_swatch(self, btn):
        # Same shape as the Custom-colours chip: a small popover of pick
        # rows; the colour dialog is window-parented so dismissing the
        # popover can't orphan it.
        dark = Adw.StyleManager.get_default().get_dark()
        pop = Gtk.Popover()
        pop.set_parent(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(4)
        gold = DROPCAP_GOLD_DARK if dark else DROPCAP_GOLD_LIGHT
        box.append(self._custom_pick_row(
            gold, _('Gold (default)'),
            lambda _b: self._apply_dropcap_color(None), pop))
        box.append(self._custom_pick_row(
            dropcap_color_hex(dark), _('Custom colour…'),
            self._on_dropcap_custom_clicked, pop))
        pop.set_child(box)
        pop.connect('closed', lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _on_dropcap_custom_clicked(self, btn):
        dialog = Gtk.ColorDialog()
        dialog.set_title(_('Drop cap colour'))
        initial = Gdk.RGBA()
        initial.parse(
            dropcap_color_hex(Adw.StyleManager.get_default().get_dark()))
        dialog.choose_rgba(self, initial, None, self._on_dropcap_custom_done)

    def _on_dropcap_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # dismissed
        self._apply_dropcap_color(self._rgba_hex(rgba))

    def _on_paper_custom_clicked(self, btn):
        dialog = Gtk.ColorDialog()
        dialog.set_title(_('Custom background colour'))
        initial = Gdk.RGBA()
        stored = settings.get(self._current_bg_key())
        if not (stored and initial.parse(stored)):
            initial.parse('#ffffff')
        dialog.choose_rgba(self, initial, None, self._on_paper_custom_done)

    def _on_paper_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # dismissed
        self._apply_paper(self._rgba_hex(rgba))
        self._rebuild_colour_row()

    def _on_ink_custom_clicked(self, btn):
        dialog = Gtk.ColorDialog()
        dialog.set_title(_('Custom text colour'))
        initial = Gdk.RGBA()
        stored = settings.get(self._current_mode_key())
        if not (stored and initial.parse(stored)):
            initial.parse('#000000')
        dialog.choose_rgba(self, initial, None, self._on_ink_custom_done)

    def _on_ink_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # dismissed
        self._apply_ink(self._rgba_hex(rgba))
        self._rebuild_colour_row()

    @staticmethod
    def _rgba_hex(rgba):
        return (f'#{round(rgba.red * 255):02x}'
                f'{round(rgba.green * 255):02x}'
                f'{round(rgba.blue * 255):02x}')

    def _apply_mode_theme(self):
        """Re-apply the active scheme's saved paper + ink to both panes and
        rebuild the colour row (called when the light/dark theme changes)."""
        bg = settings.get(self._current_bg_key())
        ink = settings.get(self._current_mode_key())
        for pane in (self.pane1, self.pane2):
            pane.set_appearance(bg_color=bg, text_color=ink)
        self._rebuild_colour_row()

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
        self._apply_mode_theme()

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
            self._menu_split.set_show_sidebar(False)
        if keep != 'search':
            self._search_split.set_show_sidebar(False)
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
            label=_('Add {ref}').format(ref=f'{book_label(book)} {chapter}'))
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
                # Stored fields stay English; recompute the display so the
                # book name follows the UI language rather than freezing in
                # whatever was active when the bookmark was created.
                disp = book_label(bm['book']) + f" {bm['chapter']}" + (
                    f":{bm['verse']}" if bm.get('verse') else '')
                lbl = Gtk.Label(label=disp, xalign=0, hexpand=True)
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
        self._toast(_('Bookmarked {ref}').format(ref=f'{book_label(book)} {chapter}'))

    def _on_bookmark_row_activated(self, _lb, row, popover):
        bm = getattr(row, '_bookmark', None)
        if bm is None:
            return
        popover.popdown()
        self._go_to(bm['book'], bm['chapter'], bm.get('verse'))

    def _remove_bookmark(self, _btn, index, popover):
        removed = bookmarks.remove(index)
        popover.popdown()
        if removed is None:
            return
        # Default (longer) timeout, not _toast's 2s — the user needs time
        # to reach the Undo button.
        t = Adw.Toast.new(_('Bookmark removed'))
        t.set_button_label(_('Undo'))
        t.connect('button-clicked',
                  lambda _t: bookmarks.restore(index, removed))
        self._toast_overlay.add_toast(t)

    def _toast(self, message):
        t = Adw.Toast.new(message)
        t.set_timeout(2)
        self._toast_overlay.add_toast(t)

    def _present_hint_toast(self, message):
        # Contextual hints linger a touch longer than a plain _toast (they're
        # instructional) and carry a way to the full reference, which is also
        # where hints can be turned off — dismissible now, re-findable later.
        t = Adw.Toast.new(message)
        t.set_timeout(6)
        t.set_button_label(_('Tips'))
        t.connect('button-clicked', lambda _t: self._open_tips_dialog())
        self._toast_overlay.add_toast(t)

    def _open_tips_dialog(self, *_args):
        onboarding.build_tips_dialog(
            on_shortcuts=self._open_shortcuts_dialog).present(self)

    # ── Study data backup / restore ───────────────────────────────────────────

    def _on_backup_clicked(self, _row):
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Back Up Study Data'))
        dialog.set_initial_name(
            f'scriptura-study-data-{datetime.date.today().isoformat()}.json')
        dialog.save(self, None, self._on_backup_finish)

    def _on_backup_finish(self, dialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # cancelled
        try:
            with open(gfile.get_path(), 'w', encoding='utf-8') as f:
                json.dump(backup.collect(), f, indent=2, ensure_ascii=False)
        except Exception:
            _log.exception('backup failed')
            self._toast(_('Could not write the backup file'))
            return
        self._toast(_('Study data backed up'))

    def _on_restore_clicked(self, _row):
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Restore Study Data'))
        dialog.open(self, None, self._on_restore_open)

    def _on_restore_open(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # cancelled
        try:
            with open(gfile.get_path(), encoding='utf-8') as f:
                payload = backup.validate(json.load(f))
        except Exception:
            _log.exception('restore rejected')
            self._toast(_('Not a Scriptura study-data file'))
            return
        c = backup.counts(payload)
        confirm = Adw.AlertDialog(
            heading=_('Replace study data?'),
            body=_('The file contains {a} annotation entries, {b} bookmarks '
                   'and {p} plan days marked read. Your current annotations, '
                   'bookmarks and reading-plan progress will be replaced.'
                   ).format(a=c['annotations'], b=c['bookmarks'],
                            p=c['plan_days']),
        )
        confirm.add_response('cancel', _('Cancel'))
        confirm.add_response('replace', _('Replace'))
        confirm.set_response_appearance(
            'replace', Adw.ResponseAppearance.DESTRUCTIVE)
        confirm.set_default_response('cancel')
        confirm.set_close_response('cancel')
        confirm.connect('response', self._on_restore_confirm, payload)
        confirm.present(self)

    def _on_restore_confirm(self, _dialog, response, payload):
        if response != 'replace':
            return
        backup.restore(payload)
        # Re-render both panes so restored highlights/notes/indicators
        # appear (the reading anchor keeps the text in place), and rebuild
        # the plan section against the restored progress.
        for pane in (self.pane1, self.pane2):
            pane._fetch_and_render()
        if self._menu_panel_built:
            self._refresh_plan_ui()
        # An open Study Journal still lists the replaced annotations —
        # deleting one of those stale rows would silently no-op.
        if self._journal_win is not None and self._journal_win.get_visible():
            self._journal_win._reload()
        self._toast(_('Study data restored'))

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

    def _set_reading_mode(self, on, toast=True):
        """Distraction-free mode: hide the window header, pane toolbars, and
        any open overlay panels. Esc / F11 / mouse-to-top-edge to exit.

        Presentation mode reuses this chrome-hiding primitive but supplies its
        own messaging, so it calls with ``toast=False``."""
        if on:
            self._dismiss_today()   # entering a mode is "an action" too
        self._reading_mode = bool(on)
        self._header.set_visible(not on)
        self.pane1._toolbar.set_visible(not on)
        self.pane2._toolbar.set_visible(not on)
        # Slide each page's top edge into (or back out of) the vacated
        # strip, scroll-compensated so the text itself never moves.
        # A hidden toolbar measures 0, so the same animation serves both
        # directions.
        self.pane1._animate_page_strip()
        self.pane2._animate_page_strip()
        if on:
            # Dismiss anything floating so the text stands alone
            self._menu_split.set_show_sidebar(False)
            self._search_split.set_show_sidebar(False)
            self._jump_revealer.set_reveal_child(False)
            self._crossref_revealer.set_reveal_child(False)
            if toast:
                self._toast(
                    _('Reading mode — Esc, F11, or hover the top edge to exit'))
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
        # Presentation mode reuses reading-mode chrome-hiding but has its own
        # control strip, shown by pointer position (bottom edge), not the
        # reading exit affordance.
        if getattr(self, '_present_mode', False):
            self._present_update_controls(y)
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

    # ── Presentation mode ─────────────────────────────────────────────────────
    # Built on top of reading mode: the same chrome-hiding, plus fullscreen so
    # a single passage fills a projector / mirrored display. Entering remembers
    # the prior reading + fullscreen state so exit restores exactly what the
    # user had. The large-type render (step 2), keyboard stepping (step 3) and
    # auto-hiding control strip (step 4) layer on from here.
    def _toggle_present_mode(self):
        self._set_present_mode(not getattr(self, '_present_mode', False))

    def _toggle_reading_mode(self):
        # F11 out of the immersive state: if presenting, leave presentation
        # entirely rather than half-peeling only the reading chrome.
        if getattr(self, '_present_mode', False):
            self._set_present_mode(False)
            return
        self._set_reading_mode(not getattr(self, '_reading_mode', False))

    def _set_present_mode(self, on):
        on = bool(on)
        if on == getattr(self, '_present_mode', False):
            return
        self._present_mode = on
        if on:
            self._present_was_reading = getattr(self, '_reading_mode', False)
            self._present_was_fullscreen = self.is_fullscreen()
            self._set_reading_mode(True, toast=False)
            self._show_present()
            self.fullscreen()
            self._toast(
                _('Presentation — Esc to exit, controls at the bottom edge'))
        else:
            self._present_show_controls(False)
            self._present_view.set_visible(False)
            if not getattr(self, '_present_was_fullscreen', False):
                self.unfullscreen()
            if not getattr(self, '_present_was_reading', False):
                self._set_reading_mode(False, toast=False)

    def _present_source_pane(self):
        """The pane whose passage projects. The primary pane leads; fall back to
        the secondary if only it has a navigable chapter loaded."""
        if self.pane1.current_passage() is not None:
            return self.pane1
        if self.pane2.get_visible() and self.pane2.current_passage() is not None:
            return self.pane2
        return self.pane1

    def _present_bilingual_source(self):
        """(primary, secondary) panes when a parallel projection is possible:
        split view, both showing a navigable Bible chapter, on the same
        reference, in different modules. Else None. Primary is pane1."""
        if not self.pane2.get_visible():
            return None
        p1 = self.pane1.current_passage()
        p2 = self.pane2.current_passage()
        if p1 is None or p2 is None:
            return None
        if (p1[0], p1[1]) != (p2[0], p2[1]):        # same book & chapter
            return None
        if self.pane1._module == self.pane2._module:  # two views of one text
            return None
        return (self.pane1, self.pane2)

    def _show_present(self):
        bi = self._present_bilingual_source()
        pane = bi[0] if bi else self._present_source_pane()
        self._present_module = pane._module
        self._present_module_b = bi[1]._module if bi else None
        self._present_bilingual = bool(bi)          # user intent, per session
        # Invalidate any cross/jump load still in flight from a previous present
        # session so it can't clobber the passage we're about to show.
        tasks.cancel(f'present:{id(self)}')
        # Header is already hidden (reading mode), so the window height minus the
        # surface's own padding is a good pre-allocation viewport estimate — lets
        # the very first page pre-fit instead of flashing an overflow.
        self._present_view.set_viewport_hint(self.get_height() - 80)
        self._present_view.set_appearance(pane.reading_appearance())
        passage = pane.current_passage()
        if passage is None:
            # Nothing navigable to project (e.g. a lexicon/imagery module) —
            # show the surface with a gentle placeholder rather than a blank.
            self._present_book = None
            self._present_view.show_placeholder(
                _('Open a Bible passage to present it.'))
        else:
            book, chapter, translation, verses = passage
            self._present_book, self._present_chapter = book, chapter
            secondary = None
            if bi:
                _b, _c, trans_b, verses_b = bi[1].current_passage()
                secondary = (trans_b, verses_b)
            # Both panes' verses are already fetched — load synchronously (no
            # worker thread needed) so the first slide is ready instantly.
            self._present_view.load_chapter(
                book, chapter, translation, verses,
                focus_verse=pane.current_verse(), secondary=secondary)
            self._present_view.set_parallel(bool(bi))
        self._present_view.set_visible(True)
        self._sync_present_controls()

    # ── Cross-chapter navigation (presentation) ───────────────────────────────
    # Stepping off either end of a chapter rolls into the adjacent one, so the
    # arrows are always live. Present mode navigates its own location; the
    # source pane is left where it was (exit returns you to your study spot).
    def _adjacent_chapter(self, book, chapter, delta):
        """(book, chapter) one chapter forward/back from here, crossing book
        boundaries; None at the very start / end of the canon."""
        try:
            idx = BOOKS.index(book)
        except ValueError:
            return None
        module = self._present_module
        if delta > 0:
            if chapter < sword_bridge.chapter_count(book, module):
                return (book, chapter + 1)
            if idx < len(BOOKS) - 1:
                return (BOOKS[idx + 1], 1)
            return None
        if chapter > 1:
            return (book, chapter - 1)
        if idx > 0:
            prev = BOOKS[idx - 1]
            return (prev, sword_bridge.chapter_count(prev, module))
        return None

    def _load_chapter_verses(self, module, book, chapter):
        import ebible_bridge
        if ebible_bridge.is_ebible_module(module):
            return ebible_bridge.load_chapter(module, book, chapter)
        return sword_bridge.load_chapter(module, book, chapter)

    def _present_cross(self, delta):
        """Load the chapter `delta` away into the presentation surface, landing
        on its first page (forward) or last page (backward). A canon edge or an
        empty (out-of-coverage) chapter leaves the current slide unchanged."""
        if not getattr(self, '_present_book', None):
            return
        nxt = self._adjacent_chapter(
            self._present_book, self._present_chapter, delta)
        if nxt is None:
            return
        book, chapter = nxt
        self._present_load_async(
            book, chapter, land='first' if delta > 0 else 'last')

    def _present_jump(self, book, chapter, verse):
        """Jump the presentation to an arbitrary reference (from the Ctrl+L bar)
        without moving the source pane. Opens on the page holding `verse` when
        one is given. A book the presenting module doesn't carry leaves the
        slide unchanged and says so, rather than projecting a blank."""
        if book not in BOOKS:
            return
        chapter = max(1, min(chapter,
                             sword_bridge.chapter_count(book,
                                                        self._present_module)))
        self._present_load_async(
            book, chapter, focus_verse=verse, empty_toast=True)

    def _present_load_async(self, book, chapter, *, land='first',
                            focus_verse=None, empty_toast=False):
        """Load a chapter for the presentation surface off the UI thread, then
        show it on the main loop — so a slow module never stalls the projected
        display mid-roll. The tasks runner drops any load a newer navigation
        has superseded (and _show_present cancels the key on entry), so rapid
        arrow-rolls can't paint a stale chapter."""
        module = self._present_module
        module_b = (self._present_module_b
                    if getattr(self, '_present_bilingual', False) else None)

        def work(_task):
            try:
                verses = self._load_chapter_verses(module, book, chapter)
            except Exception:
                verses = []
            translation = sword_bridge.display_name(module)
            secondary = None
            if module_b:
                try:
                    verses_b = self._load_chapter_verses(module_b, book, chapter)
                except Exception:
                    verses_b = []
                # Only offer the second column where it actually has this
                # chapter — otherwise this chapter degrades cleanly to single.
                if any(re.sub(r'<[^>]+>', '', str(h)).strip()
                       for _v, h in verses_b):
                    secondary = (sword_bridge.display_name(module_b), verses_b)
            return verses, translation, secondary

        tasks.submit(
            f'present:{id(self)}', work,
            lambda res: self._present_load_finish(
                book, chapter, *res, land, focus_verse, empty_toast),
            on_error=lambda _exc: self._present_load_finish(
                book, chapter, [], '', None, land, focus_verse, empty_toast))

    def _present_load_finish(self, book, chapter, verses, translation,
                             secondary, land, focus_verse, empty_toast):
        if not getattr(self, '_present_mode', False):
            return GLib.SOURCE_REMOVE           # present exited meanwhile
        if not any(re.sub(r'<[^>]+>', '', str(h)).strip() for _v, h in verses):
            if empty_toast:
                self._toast(_('%s isn’t in this translation.') % book_label(book))
            return GLib.SOURCE_REMOVE           # canon edge / out of coverage
        self._present_book, self._present_chapter = book, chapter
        self._present_view.load_chapter(
            book, chapter, translation, verses,
            land=land, focus_verse=focus_verse, secondary=secondary)
        # Honour the session's parallel intent, but only where the second column
        # actually loaded (an out-of-coverage chapter shows single).
        self._present_view.set_parallel(
            bool(secondary) and getattr(self, '_present_bilingual', False))
        self._sync_present_controls()
        return GLib.SOURCE_REMOVE

    # ── Presentation control strip ────────────────────────────────────────────
    # A floating OSD bar (media-overlay style, theme-neutral over any paper)
    # with the step + toggle controls. Shown by pointer position (near the
    # bottom edge) rather than an idle timer, so it never hops on its own;
    # keyboard-only presenting leaves it hidden for a clean slide.
    def _build_present_controls(self, overlay):
        def icon_button(icon, tooltip, handler, toggle=False):
            btn = (Gtk.ToggleButton() if toggle else Gtk.Button())
            btn.set_icon_name(icon)
            btn.add_css_class('flat')
            btn.set_tooltip_text(tooltip)
            set_accessible_label(btn, tooltip)
            btn.connect('toggled' if toggle else 'clicked', handler)
            return btn

        self._present_prev_btn = icon_button(
            'go-previous-symbolic', _('Previous'),
            lambda _b: self._present_step(self._present_view.step_prev))
        self._present_next_btn = icon_button(
            'go-next-symbolic', _('Next'),
            lambda _b: self._present_step(self._present_view.step_next))
        self._present_numbers_btn = icon_button(
            'view-list-ordered-symbolic', _('Verse numbers'),
            lambda b: self._present_view.set_show_numbers(b.get_active()),
            toggle=True)
        # A stylized "V" (Verse) reads better here than any stock icon — the
        # paged/fullscreen glyphs looked like copy/fullscreen.
        self._present_gran_btn = Gtk.ToggleButton()
        self._present_gran_btn.add_css_class('flat')
        _vglyph = Gtk.Label(label='V')
        _vglyph.add_css_class('present-verse-glyph')
        self._present_gran_btn.set_child(_vglyph)
        self._present_gran_btn.set_tooltip_text(_('One verse per page'))
        set_accessible_label(self._present_gran_btn, _('One verse per page'))
        self._present_gran_btn.connect(
            'toggled',
            lambda b: self._present_view.set_verse_at_a_time(b.get_active()))
        # Parallel (bilingual) toggle — only meaningful, and only shown, when a
        # second translation is loaded (see _sync_present_controls).
        self._present_parallel_btn = icon_button(
            'view-dual-symbolic', _('Parallel — both translations'),
            lambda b: self._present_toggle_parallel(b.get_active()),
            toggle=True)
        self._present_zoom_out_btn = icon_button(
            'zoom-out-symbolic', _('Smaller text'),
            lambda _b: self._present_view.bump_size(-1))
        self._present_zoom_in_btn = icon_button(
            'zoom-in-symbolic', _('Larger text'),
            lambda _b: self._present_view.bump_size(1))
        self._present_exit_btn = icon_button(
            'window-close-symbolic', _('Exit presentation'),
            lambda _b: self._set_present_mode(False))

        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        strip.add_css_class('osd')
        strip.add_css_class('toolbar')
        strip.add_css_class('present-controls')
        strip.append(self._present_prev_btn)
        strip.append(self._present_next_btn)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(self._present_numbers_btn)
        strip.append(self._present_gran_btn)
        strip.append(self._present_parallel_btn)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(self._present_zoom_out_btn)
        strip.append(self._present_zoom_in_btn)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(self._present_exit_btn)

        self._present_controls_revealer = Gtk.Revealer()
        self._present_controls_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_UP)
        self._present_controls_revealer.set_transition_duration(200)
        self._present_controls_revealer.set_halign(Gtk.Align.CENTER)
        self._present_controls_revealer.set_valign(Gtk.Align.END)
        self._present_controls_revealer.set_margin_bottom(28)
        self._present_controls_revealer.set_child(strip)
        self._present_controls_revealer.set_reveal_child(False)
        overlay.add_overlay(self._present_controls_revealer)

        self._present_controls_shown = False

    def _sync_present_controls(self):
        """Reflect the view's current toggle state on the strip. The setters the
        buttons drive are idempotent, so mirroring back here can't loop."""
        if not hasattr(self, '_present_numbers_btn'):
            return
        self._present_numbers_btn.set_active(self._present_view.show_numbers)
        self._present_gran_btn.set_active(self._present_view.verse_at_a_time)
        # The parallel toggle only appears when a second translation is loaded.
        self._present_parallel_btn.set_visible(self._present_view.has_secondary)
        self._present_parallel_btn.set_active(self._present_view.parallel)

    def _present_toggle_parallel(self, on):
        """Show both translations (on) or collapse to the primary. Records the
        session intent so cross-chapter rolls keep the presenter's choice."""
        self._present_bilingual = bool(on)
        self._present_view.set_parallel(bool(on))
        self._sync_present_controls()

    def _present_step(self, op):
        op()
        self._sync_present_controls()

    # Show the strip while the pointer is within this many px of the bottom
    # (near the controls), hide it once the pointer moves up to read. Purely
    # position-driven — no idle timer — so it never hops on its own.
    _PRESENT_CONTROL_ZONE_PX = 150

    def _present_update_controls(self, y):
        if not getattr(self, '_present_mode', False):
            return
        height = self.get_height()
        if not height:
            return
        self._present_show_controls(y > height - self._PRESENT_CONTROL_ZONE_PX)

    def _present_show_controls(self, show):
        show = bool(show)
        if show == self._present_controls_shown:
            return                              # only act on an actual edge
        self._present_controls_shown = show
        if show:
            self._sync_present_controls()
        self._present_controls_revealer.set_reveal_child(show)

    def _on_present_menu_clicked(self, _row):
        # Menu entry point (F5 is the shortcut). Close the menu first so it
        # isn't left open behind the fullscreen surface.
        self._menu_split.set_show_sidebar(False)
        self._set_present_mode(True)

    # ── Lexicon toggle ────────────────────────────────────────────────────────

    def _on_lex_toggle(self, _btn):
        enabled = self.lex_toggle.get_active()
        self.pane1.set_lexicon_enabled(enabled)
        self.pane2.set_lexicon_enabled(enabled)
        # Strong's words carry no visible mark at rest; on first enabling the
        # mode, name the gesture that now pays off.
        if enabled:
            self._hints.maybe_fire('first_lexicon')

    def _on_fnote_toggle(self, _btn):
        enabled = self.fnote_toggle.get_active()
        settings.put('show_footnotes', enabled)
        self.pane1.set_show_footnotes(enabled)
        self.pane2.set_show_footnotes(enabled)

    def _on_xref_toggle(self, _btn):
        enabled = self.xref_toggle.get_active()
        settings.put('show_crossrefs', enabled)
        # Off hides an open bar immediately; on doesn't retro-summon it —
        # the next verse tap reveals as usual.
        if not enabled:
            self._hide_crossref()

    # ── Evening paper (follows Night Light) ──────────────────────────────

    def _start_evening_paper(self):
        if self._night_monitor is None:
            self._night_monitor = night_light.NightLightMonitor(
                self._on_evening_strength)

    def _stop_evening_paper(self):
        if self._night_monitor is not None:
            self._night_monitor.stop()
            self._night_monitor = None
        self._on_evening_strength(0.0)

    def _on_evening_strength(self, strength):
        self._evening_now = strength
        for pane in (self.pane1, self.pane2):
            pane.set_evening_strength(strength)
        self._refresh_today_appearance()

    # ── Today page (the Morning Office landing) ──────────────────────────

    def _populate_today(self):
        saved_book = settings.get('last_book')
        saved_chap = settings.get('last_chapter')
        last = ((saved_book, saved_chap)
                if saved_book in BOOKS and isinstance(saved_chap, int)
                and saved_chap >= 1 else None)
        church_line = None
        collect_key = None
        tradition = settings.get('church_calendar')
        if tradition:
            import church_year
            desig = church_year.day_designation(
                datetime.date.today(), tradition)
            if desig:
                collect_key, church_line = desig
        # Human-friendly module label — the raw key can be an internal
        # eBible id ("eBible: spabes"); display_name resolves every kind.
        module = settings.get('pane1_module')
        detail = sword_bridge.display_name(module) if module else None
        self._today_view.populate(last, detail, church_line=church_line)
        self._refresh_today_appearance()
        # A System-scheme flip (or Night Light toggling dark) re-papers the
        # page while it's up; disconnected again on dismissal. Dropped first
        # so that repopulating — which is what changing the church calendar
        # does — leaves one handler behind rather than another one.
        if self._today_dark_handler is not None:
            Adw.StyleManager.get_default().disconnect(self._today_dark_handler)
        self._today_dark_handler = Adw.StyleManager.get_default().connect(
            'notify::dark', lambda *_a: self._refresh_today_appearance())
        # Emptied before the fetch, not after it: on a rebuild the old foot
        # line is the previous calendar's, and it must not stand under the new
        # day's name for however long the lookup takes.
        self._today_view.clear_epigraph()
        self._sync_today_listen()
        tasks.submit(
            key=f'today-epigraph:{id(self)}',
            work=lambda _t: fetch_epigraph(collect_key),
            apply=self._on_today_epigraph,
            on_error=lambda _e: None)

    def _refresh_today_appearance(self):
        if self._today_view is not None:
            self._today_view.set_appearance(
                self.pane1.reading_appearance(self._evening_now))

    def _on_today_epigraph(self, result):
        if self._today_view is None:
            return
        if result:
            self._today_view.set_epigraph(*result)
        else:
            self._today_view.clear_epigraph()

    # ── Today's spoken devotional ────────────────────────────────────────
    # Offered only for the current day. Its feed is a rolling thirty-day
    # window rather than a back catalogue, so any other date is simply absent
    # — and a control that worked in July and failed in October, for reasons
    # no reader could see, would be worse than no control at all.

    def _sync_today_listen(self):
        if self._today_view is None:
            return
        today = datetime.date.today()
        got = devotional_audio.todays_strength(today)
        if got is not None:
            self._today_listen = got
            self._today_view.set_listen(got[1])
            return
        self._today_view.clear_listen()
        tasks.submit(
            key=f'today-listen:{id(self)}',
            work=lambda _t: devotional_audio.refresh_index(
                feed=devotional_audio.DAILY_STRENGTH_FEED_URL),
            apply=lambda _i: self._on_today_listen_index(today),
            on_error=lambda _e: None)

    def _on_today_listen_index(self, day):
        if self._today_view is None or datetime.date.today() != day:
            return
        got = devotional_audio.todays_strength(day)
        if got is not None:
            self._today_listen = got
            self._today_view.set_listen(got[1])

    def _on_today_listen(self):
        player = getattr(self, '_today_player', None)
        if player is not None and player.playing:
            player.pause()
            self._today_view.set_listen(self._today_listen[1])
            return
        if not getattr(self, '_today_listen', None):
            return
        url, title = self._today_listen
        self._today_view.set_listen(title, playing=True)
        cached = devotional_audio.cached_episode(url)
        if cached:
            self._start_today_listen(cached)
            return
        tasks.submit(
            key=f'today-audio:{id(self)}',
            work=lambda _t: devotional_audio.fetch_episode(url),
            apply=self._start_today_listen,
            on_error=lambda _e: self._stop_today_listen())

    def _start_today_listen(self, path):
        if not path or self._today_view is None:
            self._stop_today_listen()
            return
        if getattr(self, '_today_player', None) is None:
            self._today_player = devotional_audio.Player()
        if not self._today_player.play(path):
            self._stop_today_listen()
            return
        self._today_view.set_listen(self._today_listen[1], playing=True)
        if getattr(self, '_today_listen_tick', None) is None:
            self._today_listen_tick = GLib.timeout_add(
                500, self._on_today_listen_tick)

    def _on_today_listen_tick(self):
        player = getattr(self, '_today_player', None)
        if player is None or self._today_view is None:
            self._today_listen_tick = None
            return GLib.SOURCE_REMOVE
        if player.ended():
            self._stop_today_listen()
            return GLib.SOURCE_REMOVE
        self._today_view.set_listen_progress(player.progress())
        return GLib.SOURCE_CONTINUE

    def _stop_today_listen(self):
        if getattr(self, '_today_listen_tick', None) is not None:
            GLib.source_remove(self._today_listen_tick)
        self._today_listen_tick = None
        if getattr(self, '_today_player', None) is not None:
            self._today_player.stop()
            self._today_player = None
        if self._today_view is not None:
            if getattr(self, '_today_listen', None):
                self._today_view.set_listen(self._today_listen[1])
            self._today_view.set_listen_progress(0.0, showing=False)

    def _set_church_calendar(self, tradition):
        """Change the calendar, and let the Today page say so at once.

        The page is built once at startup, so writing the setting alone left
        the line — and the day's collect under it — showing the calendar the
        reader had just changed away from until the next launch.
        """
        settings.put('church_calendar', tradition)
        if self._today_view is not None:
            self._populate_today()

    def _dismiss_today(self):
        """Slide the Today page away. Once per session — there is no way
        back to it until the next launch."""
        if self._today_revealer is None:
            return
        revealer, self._today_revealer = self._today_revealer, None
        self._today_view = None
        if self._today_dark_handler is not None:
            Adw.StyleManager.get_default().disconnect(self._today_dark_handler)
            self._today_dark_handler = None
        tasks.cancel(f'today-epigraph:{id(self)}')
        self._stop_today_listen()
        # can_target off immediately so the sliding page never eats a click;
        # fully hidden (and out of the picking/AT tree) after the slide.
        revealer.set_can_target(False)
        revealer.set_reveal_child(False)
        GLib.timeout_add(
            motion.DURATION_STANDARD + 50,
            lambda: revealer.set_visible(False) or GLib.SOURCE_REMOVE)

    def _on_today_begin(self, book, chapter):
        self._go_to(book, chapter)      # navigation dismisses the page

    def _on_today_continue(self, target):
        # The panes already restored the saved position at startup; navigate
        # anyway so the page's promise holds even if a startup devotional
        # auto-nav moved pane 1 meanwhile.
        if target:
            self._go_to(target[0], target[1], record=False)
        self._dismiss_today()

    def _on_today_choose_plans(self):
        self._toggle_menu(None)         # opening the menu dismisses the page

    # ── Reading-tools bloom (the אΩ cluster) ─────────────────────────────

    def _tools_bloom(self, *_args):
        """Pointer or keyboard focus arrived on the cluster: open it and
        cancel any pending fold."""
        if self._tools_fold_timer:
            GLib.source_remove(self._tools_fold_timer)
            self._tools_fold_timer = 0
        self._tools_revealer.set_reveal_child(True)

    def _tools_arm_fold(self, *_args):
        """Pointer or focus left: fold after a grace period. The grace
        absorbs brush-outs and raw-pointer jitter (wlroots compositors
        deliver unsmoothed motion — GUIDANCE §3); re-entry cancels it."""
        if self._tools_fold_timer:
            GLib.source_remove(self._tools_fold_timer)
        self._tools_fold_timer = GLib.timeout_add(
            motion.HOVER_GRACE_MS, self._tools_fold)

    def _tools_fold(self):
        self._tools_fold_timer = 0
        # A leave from one controller can race an enter on the other
        # (Tab away while the pointer still rests on the cluster) — hold
        # open while either kind of presence remains.
        if (self._tools_hover.contains_pointer()
                or self._tools_focus.contains_focus()):
            return False
        self._tools_revealer.set_reveal_child(False)
        return False

    def _update_fnote_sensitivity(self):
        """Enable the f* toggle only when a loaded module can actually show
        footnotes, so flipping it never silently does nothing. Disabled (not
        hidden) with an explanatory tooltip — the header layout stays put.
        Runs on every pane module switch and after module installs."""
        import content
        capable = any(content.has_footnotes(p._module)
                      for p in (self.pane1, self.pane2))
        self.fnote_toggle.set_sensitive(capable)
        self.fnote_toggle.set_tooltip_text(
            _("Footnotes — the translation's own notes, marked in the text")
            if capable else
            _("Footnotes — the open translations don't include any"))

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
        for w in (self._study_box, self._bookmark_btn, self._swap_btn):
            w.set_visible(not narrow)
        self._overflow_btn.set_visible(narrow)

    def _set_panes_narrow(self, narrow):
        """Collapse to a single visible pane when two get too cramped. Reuses
        the single/split visibility plumbing; the user's wide-mode split choice
        is preserved and restored when the window widens again."""
        if narrow == self._panes_narrow:
            return
        self._panes_narrow = narrow
        # Single-column width: let the cross-ref bar drop its title eyebrow so
        # the chips aren't squeezed down to one clipped reference.
        self._crossref_panel.set_compact(narrow)
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
        # The search split's min-sidebar-width is a hard minimum that
        # propagates up to the window even while the sidebar is hidden —
        # below 420px the window under-allocates (Adwaita warns) and the
        # open panel overflows the right edge. Drop the floor here so the
        # sidebar fills the window instead (measured: a collapsed OSV
        # sizes its sidebar to min(max-sidebar-width, window width));
        # restore the 420px floor when leaving the ultra band.
        self._search_split.set_min_sidebar_width(0 if narrow else 420)

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

        fn_glyph = Gtk.Label()
        # Same italic-f + asterisk as the header toggle, a step smaller to
        # sit in the overflow row (mirrors the lex row's smaller אΩ).
        fn_glyph.set_markup('<span size="large"><i>f</i></span>'
                            '<span size="small">*</span>')
        fn_row = row(fn_glyph, _('Footnotes'),
                     lambda: self.fnote_toggle.set_active(
                         not self.fnote_toggle.get_active()),
                     sensitive=self.fnote_toggle.get_sensitive())
        if self.fnote_toggle.get_active():
            fn_row.get_child().append(
                Gtk.Image.new_from_icon_name('object-select-symbolic'))

        xr_glyph = Gtk.Label()
        xr_glyph.set_markup('<span size="large">※</span>')
        xr_row = row(xr_glyph, _('Cross-references'),
                     lambda: self.xref_toggle.set_active(
                         not self.xref_toggle.get_active()))
        if self.xref_toggle.get_active():
            xr_row.get_child().append(
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
        except Exception:
            _log.exception('close-save failed')
        return False

    # ── Search ────────────────────────────────────────────────────────────────

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

    def _on_search_result(self, book, chapter, verse):
        # Stash the query on any pane whose current module matches the
        # search panel's module, so _apply_search_highlight can paint the
        # matched word(s) once the chapter re-renders.
        query = self._search_panel._entry.get_text().strip()
        case = self._search_panel._case_btn.get_active()
        if query:
            target_mod = self._search_panel._current_module()
            # 'All Bibles' has no single source module — highlight on whatever
            # each pane is showing; otherwise only the matching module's pane.
            all_bibles = target_mod == search_controller.ALL_BIBLES
            for pane in (self.pane1, self.pane2):
                if all_bibles or pane._module == target_mod:
                    pane._pending_search_highlight = (query, case)
        self._go_to(book, chapter, verse)

    # ── Verse select / cross-references ──────────────────────────────────────

    def _on_verse_select(self, source_pane, verse_num):
        # The source pane reports its own displayed verse number, which on
        # a versification-mapped module (Vulgate/Synodal psalter) is that
        # module's numbering. Normalize to app-space here so the partner
        # pane and the (KJV-keyed) cross-reference panel both receive the
        # one shared reference space; select_verse maps back per receiver.
        verse_num = sword_bridge.map_verse_to_app(
            source_pane._module, source_pane._book, source_pane._chapter,
            verse_num)
        for pane in [self.pane1, self.pane2]:
            if pane is not source_pane:
                pane.select_verse(verse_num)
        if (source_pane._book and source_pane._chapter
                and self.xref_toggle.get_active()):
            self._crossref_panel.load(source_pane._book, source_pane._chapter, verse_num)
            self._crossref_revealer.set_reveal_child(True)
        # They've engaged a verse — the moment to reveal the deeper gesture.
        self._hints.maybe_fire('first_verse_click')

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

        ref_lbl = Gtk.Label(label=f'{book_label(book)} {chapter}:{verse}', xalign=0)
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
            _('SWORD Project (CrossWire Bible Society) — modules and data layer'),
            _('OpenBible.info — cross-references and topical tags (CC-BY)'),
            _('Dodson Greek Lexicon — public-domain NT Greek definitions'),
            _('eBible.org — modern translation catalog and texts'),
            _('HistoricalChristianFaith Commentaries Database — historical commentary pack'),
        ])
        dlg.add_acknowledgement_section(_('Built with'), [
            'GTK4 + libadwaita',
            'Python 3 / PyGObject',
            'SQLite FTS5 full-text search',
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
        (N_('Presentation'), [
            (N_('Present the passage full-screen'), 'action', 'present-mode'),
            (N_('Next page'), 'accel', 'Right'),
            (N_('Previous page'), 'accel', 'Left'),
            (N_('First page'), 'accel', 'Home'),
            (N_('Last page'), 'accel', 'End'),
            (N_('One verse per page'), 'accel', 'v'),
            (N_('Larger / smaller text'), 'accel', 'plus minus'),
            (N_('Jump to a passage'), 'action', 'goto'),
            (N_('Exit presentation'), 'accel', 'Escape'),
        ]),
        (N_('General'), [
            (N_('Copy selection with reference'), 'accel', '<Ctrl>c'),
            (N_('Keyboard shortcuts'), 'action', 'show-help-overlay'),
        ]),
    ]

    def _open_shortcuts_dialog(self):
        """Native shortcuts dialog (Adw.ShortcutsDialog, libadwaita 1.8+ —
        the official successor to the deprecated Gtk.ShortcutsWindow, which
        is why a hand-rolled Adw.Dialog used to live here). Built from
        _SHORTCUT_SECTIONS; _action_accels stays the single source of truth
        for action accelerators, so the dialog and the dispatch can't
        drift. 'literal' rows (mouse / scroll gestures that aren't key
        accelerators) render as title + subtitle with no key caps."""
        dialog = Adw.ShortcutsDialog()
        for section, rows in self._SHORTCUT_SECTIONS:
            sec = Adw.ShortcutsSection.new(_(section))
            for desc, kind, value in rows:
                if kind == 'literal':
                    item = Adw.ShortcutsItem.new(_(desc), '')
                    item.set_subtitle(_(value))
                else:
                    accel = (self._action_accels[value][0]
                             if kind == 'action' else value)
                    item = Adw.ShortcutsItem.new(_(desc), accel)
                sec.add(item)
            dialog.add(sec)
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
        # A same-module refresh doesn't fire on_module_switched, but an
        # install can still change capability (e.g. an eBible re-download
        # that now carries notes).
        self._update_fnote_sensitivity()

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

    def _open_verse_in_pane2(self, book, chapter, verse, module=None):
        """A verse peek's 'open in Bible pane' button: put the cited verse
        in pane 2 and leave pane 1 exactly where it is — the peek exists
        so a citation never tears the user away from what they're
        studying, and this button extends that to the full-pane view.
        Reveals pane 2 if the window is single-pane; if it isn't showing
        a text Bible, loads `module` (the Bible the peek previewed)."""
        import content
        if not self._btn_split.get_active():
            self._btn_split.set_active(True)  # → _on_view_mode reveals pane2
        if not content.is_text_bible(self.pane2._module):
            fallback = module or self._first_bible_module()
            if not fallback:
                return
            self.pane2._apply_module_change(fallback)
        # A locked pane ignores navigation but still stashes the target;
        # navigate first, then unlock — the unlock's catch-up render then
        # lands on the verse (one render either way).
        self.pane2.load_reference_at_verse(book, chapter, verse)
        if self.pane2._sync_btn.get_active():
            self.pane2._sync_btn.set_active(False)

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
        else the first available Bible. Text Bibles only — callers want a
        verse-navigable reading pane, which the interlinear isn't."""
        import content
        names = content.readable_module_names()
        for cand in (settings.get('pane2_module'), settings.get('pane1_module')):
            if cand in names and content.is_text_bible(cand):
                return cand
        for name in names:
            if content.is_text_bible(name):
                return name
        return None

    def _on_word_click(self, source_pane, strong_num):
        book    = source_pane._book
        chapter = source_pane._chapter
        verse   = source_pane._selected_verse
        # Snapshot the click's display context on the main thread and thread it
        # through to the async display. Reading the pane's live _current_morph /
        # _current_phrase at display time races a rapid second click — an older
        # worker would show the newer word's text with the wrong morphology.
        click_morph = source_pane._current_morph
        phrase = getattr(source_pane, '_current_phrase', (None, None))

        # Reveal the lexicon panel with a spinner immediately so the
        # user gets feedback that their click registered. Real content
        # arrives via _show_lexicon once the SWORD fetch completes.
        source_pane.show_lexicon_loading(strong_num)

        def fetch(_task):
            text = sword_bridge.lookup_strong(strong_num)
            morph = click_morph
            if not morph and verse:
                if strong_num.startswith('G'):
                    morph = sword_bridge.lookup_morph_for_strong(book, chapter, verse, strong_num)
                else:
                    morph = sword_bridge.lookup_morph_for_strong_heb(book, chapter, verse, strong_num)
            return text, morph

        # Keyed per source pane: rapid word clicks supersede each other's
        # lookups (latest wins), the two panes' lexicons stay independent,
        # and a raised lookup lands on the install hint instead of
        # stranding the panel's loading spinner.
        tasks.submit(
            f'lexicon-open:{id(source_pane)}', fetch,
            lambda res: self._show_lexicon(source_pane, strong_num,
                                           res[0], res[1], phrase),
            on_error=lambda _exc: self._show_lexicon(
                source_pane, strong_num, '', click_morph, phrase))

    def _show_lexicon(self, source_pane, strong_num, text, morph, phrase):
        if text:
            source_pane.show_lexicon(strong_num, text, morph, phrase)
        else:
            source_pane.show_lexicon(
                strong_num,
                _("Install StrongsGreek or StrongsHebrew from the Module Manager."),
                morph, phrase)
        return GLib.SOURCE_REMOVE

    # ── App menu panel ────────────────────────────────────────────────────────

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

    def _build_menu_panel(self):
        # .menu-panel carries the floating-card chrome (opaque background,
        # hairline edge, rounded right corners); the OverlaySplitView pane
        # behind it paints a scrim-shade base so the rounded cut-outs read
        # as continuous scrim — see the .menu-split rules in style.css.
        # No size request: width is governed by the split view's min/max
        # sidebar width.
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.add_css_class('menu-panel')

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
        close_btn.connect('clicked', lambda _: self._menu_split.set_show_sidebar(False))
        hbox.append(title)
        hbox.append(close_btn)
        panel.append(hbox)

        # Body — a vertical Box inside a ScrolledWindow so the panel can
        # scroll when its content (the expanded appearance card, or a long
        # reading plan) exceeds the available height. The footer below is a
        # sibling of the scroller, so it stays pinned to the panel's foot
        # instead of being pushed off-screen when the body overflows.
        self._menu_scroll = Gtk.ScrolledWindow(vexpand=True)
        self._menu_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # Reserve a gutter for the scrollbar instead of overlaying it on the
        # content, so it can't steal clicks from edge controls like the plan
        # ⋯ menu button.
        self._menu_scroll.set_overlay_scrolling(False)
        _body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._menu_scroll.set_child(_body)
        panel.append(self._menu_scroll)

        def _section_header(text):
            # One quiet ALL-CAPS label leading a section, so the panel's
            # settings groups share a rhythm (Appearance / Reading Plan).
            h = Gtk.Label(label=text, xalign=0)
            h.add_css_class('menu-section-header')
            h.set_margin_start(14)
            h.set_margin_end(12)
            h.set_margin_top(16)
            h.set_margin_bottom(4)
            return h

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
            ('view-fullscreen-symbolic',         _('Presentation'),  self._on_present_menu_clicked),
        ]:
            row = Adw.ActionRow(title=label)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            chevron = Gtk.Image.new_from_icon_name('go-next-symbolic')
            chevron.add_css_class('dim-label')
            row.add_suffix(chevron)
            row.set_activatable(True)
            row.connect('activated', handler)
            nav_group.add(row)
        # Open-to-Today switch (label is a draft — Andres's taxonomy). Off
        # restores direct-to-reading at launch; the change applies from the
        # next launch (the current session's page, if any, is already up).
        today_row = Adw.ActionRow(title=_('Open to Today'))
        today_row.add_prefix(
            Gtk.Image.new_from_icon_name('x-office-calendar-symbolic'))
        today_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        today_sw.set_active(bool(settings.get('open_to_today')))
        set_accessible_label(today_sw, _('Open to Today'))
        today_sw.connect(
            'notify::active',
            lambda s, _p: settings.put('open_to_today', s.get_active()))
        today_row.add_suffix(today_sw)
        today_row.set_activatable_widget(today_sw)
        nav_group.add(today_row)
        # Church calendar for the Today page's church-year line. Default
        # None — the ecumenical silence; each option is a tradition's
        # historic calendar (labels are drafts — Andres's taxonomy).
        church_row = Adw.ActionRow(title=_('Church calendar'))
        church_row.add_prefix(
            Gtk.Image.new_from_icon_name('scriptura-church-symbolic'))
        _church_values = [None, 'anglican', 'roman', 'orthodox']
        # Two labels per tradition. The pill carries the bare name, because it
        # sits on the row's own line and grows with whatever it says —
        # "Orthodox (New Calendar)" pushed the row's title onto two lines. The
        # popover has the width to name the edition, which is where the
        # distinction is actually being made.
        _church_names = [_('None'), _('Anglican'), _('Roman'), _('Orthodox')]
        _church_editions = [_('None'), _('Anglican (BCP)'),
                            _('Roman (traditional)'),
                            _('Orthodox (New Calendar)')]
        church_drop = Gtk.DropDown(model=Gtk.StringList.new(_church_names))
        _church_list = Gtk.SignalListItemFactory()
        _church_list.connect(
            'setup', lambda _f, i: i.set_child(Gtk.Label(xalign=0)))
        _church_list.connect(
            'bind',
            lambda _f, i: i.get_child().set_label(
                _church_editions[i.get_position()]))
        # Set only for the popover: with a list-factory in place the plain
        # factory keeps the button, which is what splits the two labels.
        church_drop.set_list_factory(_church_list)
        church_drop.set_valign(Gtk.Align.CENTER)
        set_accessible_label(church_drop, _('Church calendar'))
        cur_trad = settings.get('church_calendar')
        church_drop.set_selected(
            _church_values.index(cur_trad) if cur_trad in _church_values else 0)
        church_drop.connect(
            'notify::selected',
            lambda d, _p: self._set_church_calendar(
                _church_values[d.get_selected()]))
        church_row.add_suffix(church_drop)
        nav_group.add(church_row)
        _body.append(nav_group)

        # ── Appearance: a section header + its own row whose chevron rotates
        # (▸→▾) to expand the inline appearance card just below — a real expander
        # affordance, not a → arrow that falsely implies push-navigation. ──────
        _body.append(_section_header(_('Appearance')))
        appear_group = Adw.PreferencesGroup()
        appear_group.set_margin_start(12)
        appear_group.set_margin_end(12)
        self._appear_row = Adw.ActionRow(title=_('Appearance'))
        self._appear_row.add_prefix(
            Gtk.Image.new_from_icon_name('applications-graphics-symbolic'))
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
        # Bold + Justify ride the Font row as compact icon toggles (linked pair),
        # so they cost no extra vertical row; the dropdown narrows to make room.
        style_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        style_box.add_css_class('linked')
        style_box.add_css_class('appear-style-toggles')
        self._bold_btn = Gtk.ToggleButton(icon_name='format-text-bold-symbolic')
        self._bold_btn.set_tooltip_text(_('Bold'))
        set_accessible_label(self._bold_btn, _('Bold'))
        self._bold_btn.set_active(bool(settings.get('font_bold')))
        self._bold_btn.connect('toggled', self._on_appear_bold)
        self._justify_btn = Gtk.ToggleButton(icon_name='scriptura-justify-symbolic')
        self._justify_btn.set_tooltip_text(_('Justified'))
        set_accessible_label(self._justify_btn, _('Justified'))
        self._justify_btn.set_active(bool(settings.get('font_justify')))
        self._justify_btn.connect('toggled', self._on_appear_justify)
        style_box.append(self._bold_btn)
        style_box.append(self._justify_btn)
        font_row.append(style_box)
        card.append(font_row)

        # Font size
        size_row = _row(_('Size'))
        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 8, 26, 0.5)
        self._size_scale.set_hexpand(True)
        self._size_scale.set_draw_value(False)
        set_accessible_label(self._size_scale, _('Font size'))
        self._size_scale.set_value(settings.get('font_size'))
        self._size_val_lbl = Gtk.Label(
            label=f'{settings.get("font_size"):.0f}pt')
        self._size_val_lbl.set_size_request(36, -1)
        self._size_scale_handler = self._size_scale.connect(
            'value-changed', self._on_appear_size)
        size_row.append(self._size_scale)
        size_row.append(self._size_val_lbl)
        card.append(size_row)

        # Line spacing
        spacing_row = _row(_('Spacing'))
        self._spacing_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1.0, 2.5, 0.1)
        self._spacing_scale.set_hexpand(True)
        self._spacing_scale.set_draw_value(False)
        set_accessible_label(self._spacing_scale, _('Line spacing'))
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
        set_accessible_label(self._width_scale, _('Reading column width'))
        _cur_w = int(settings.get('reading_width') or 540)
        self._width_scale.set_value(_cur_w)
        self._width_val_lbl = Gtk.Label(label=f'{_cur_w}px')
        self._width_val_lbl.set_size_request(48, -1)
        self._width_scale.connect('value-changed', self._on_appear_width)
        width_row.append(self._width_scale)
        width_row.append(self._width_val_lbl)
        card.append(width_row)

        # ── Colour: one row of theme chips ────────────────────────────────────
        # Each chip previews its pairing — the paper name drawn in that paper's
        # auto ink, on the paper fill. Selecting one sets the paper and returns
        # the ink to auto; the dashed Custom chip opens a popover to override
        # text and/or paper. Built per active scheme by _rebuild_colour_row;
        # rebuilt on theme change via _apply_mode_theme.
        card.append(Gtk.Separator())
        colour_cap = Gtk.Label(label=_('Colour'), xalign=0)
        colour_cap.add_css_class('paper-caption')
        card.append(colour_cap)
        self._paper_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=8, homogeneous=True, hexpand=True)
        self._paper_box.add_css_class('paper-flow')
        card.append(self._paper_box)
        self._rebuild_colour_row()

        # ── Advanced reading toggles ──────────────────────────────────────
        # Reading conventions (small caps, old-style figures) default on;
        # opt-in taste (flush poetry, tinted drop cap) and opt-in behavior
        # (hover preview) default off. New toggles slot in as rows without
        # a redesign.
        card.append(Gtk.Separator())
        adv = Gtk.Expander(label=_('Advanced'))
        adv.add_css_class('appearance-advanced')
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        adv_box.set_margin_top(6)

        def _adv_apply(key, active, setter_name):
            settings.put(key, active)
            for pane in (self.pane1, self.pane2):
                getattr(pane, setter_name)(active)

        def _adv_switch(label_text, key, setter_name, extra=None):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.append(Gtk.Label(label=label_text, xalign=0, hexpand=True))
            if extra is not None:
                r.append(extra)
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            sw.set_active(bool(settings.get(key)))
            set_accessible_label(sw, label_text)
            sw.connect('notify::active',
                       lambda s, _p: _adv_apply(key, s.get_active(),
                                                setter_name))
            r.append(sw)
            adv_box.append(r)
            return sw

        _adv_switch(_('Small caps for the divine name'),
                    'smallcaps_divine', 'set_divine_smallcaps')
        _adv_switch(_('Old-style numerals'),
                    'oldstyle_numerals', 'set_oldstyle_numerals')
        _adv_switch(_('Flush poetry indents'),
                    'poetry_flush', 'set_poetry_flush')
        # Drop-cap row carries a swatch of the effective cap colour (gold
        # default; popover offers gold / custom), shown only while active.
        self._dropcap_swatch = Gtk.Button()
        self._dropcap_swatch.add_css_class('flat')
        self._dropcap_swatch.set_valign(Gtk.Align.CENTER)
        self._dropcap_swatch.set_tooltip_text(_('Drop cap colour'))
        set_accessible_label(self._dropcap_swatch, _('Drop cap colour'))
        _sw_box = Gtk.Box()
        _sw_box.add_css_class('mini-swatch')
        _sw_box.set_size_request(18, 18)
        self._dropcap_swatch_css = Gtk.CssProvider()
        _sw_box.get_style_context().add_provider(
            self._dropcap_swatch_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._dropcap_swatch.set_child(_sw_box)
        self._dropcap_swatch.set_visible(bool(settings.get('colored_dropcap')))
        self._dropcap_swatch.connect('clicked', self._on_dropcap_swatch)
        self._update_dropcap_swatch()
        cap_sw = _adv_switch(_('Coloured drop cap'),
                             'colored_dropcap', 'set_colored_dropcap',
                             extra=self._dropcap_swatch)
        cap_sw.connect(
            'notify::active',
            lambda s, _p: self._dropcap_swatch.set_visible(s.get_active()))
        # Behavior, not typography: dwell on a Strong's word peeks its
        # gloss without a click. Off by default — the reading surface
        # stays inert unless the reader opts in.
        _adv_switch(_('Preview words on hover'),
                    'hover_preview', 'set_hover_preview')
        # Evening paper is window-scoped (a Night Light D-Bus monitor), so
        # it can't use the per-pane setter helper above. Same row idiom.
        ev_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ev_row.append(Gtk.Label(label=_('Evening paper (follows Night Light)'),
                                xalign=0, hexpand=True))
        ev_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        ev_sw.set_active(bool(settings.get('evening_paper')))
        set_accessible_label(ev_sw, _('Evening paper (follows Night Light)'))

        def _on_evening_switch(s, _p):
            on = s.get_active()
            settings.put('evening_paper', on)
            if on:
                self._start_evening_paper()
            else:
                self._stop_evening_paper()
        ev_sw.connect('notify::active', _on_evening_switch)
        ev_row.append(ev_sw)
        adv_box.append(ev_row)
        adv.set_child(adv_box)
        card.append(adv)

        self._appear_revealer.set_child(card)
        _body.append(self._appear_revealer)

        # ── Reading Plan ──────────────────────────────────────────────────────
        # Header: title + a quiet ⋯ menu. Reset lives in that menu rather than
        # as a loud red button, keeping the destructive action off the calm
        # surface.
        plan_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        plan_hdr_box.set_margin_start(8)
        plan_hdr_box.set_margin_end(8)
        plan_hdr_box.set_margin_top(18)
        plan_hdr_box.set_margin_bottom(2)
        # The title row doubles as a collapse toggle: click it to fold the
        # whole section down to just this header (state persists).
        self._plan_collapsed = bool(settings.get('plan_collapsed'))
        self._plan_collapse_btn = Gtk.Button()
        self._plan_collapse_btn.add_css_class('flat')
        self._plan_collapse_btn.add_css_class('plan-section-toggle')
        self._plan_collapse_btn.set_halign(Gtk.Align.START)
        self._plan_collapse_btn.set_tooltip_text(_('Show or hide the reading plan'))
        _hdr_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        plan_hdr = Gtk.Label(label=_('Reading Plan'), xalign=0)
        plan_hdr.add_css_class('menu-section-header')
        _hdr_inner.append(plan_hdr)
        self._plan_chevron = Gtk.Image.new_from_icon_name('pan-down-symbolic')
        self._plan_chevron.add_css_class('dim-label')
        _hdr_inner.append(self._plan_chevron)
        self._plan_collapse_btn.set_child(_hdr_inner)
        self._plan_collapse_btn.connect('clicked', self._on_plan_toggle_collapse)
        plan_hdr_box.append(self._plan_collapse_btn)
        self._plan_menu_btn = Gtk.MenuButton(icon_name='view-more-symbolic')
        self._plan_menu_btn.add_css_class('flat')
        self._plan_menu_btn.add_css_class('menu-utility-action')
        self._plan_menu_btn.set_valign(Gtk.Align.CENTER)
        self._plan_menu_btn.set_hexpand(True)        # float the ⋯ to the right
        self._plan_menu_btn.set_halign(Gtk.Align.END)
        self._plan_menu_btn.set_tooltip_text(_('Reading plan options'))
        set_accessible_label(self._plan_menu_btn, _('Reading plan options'))
        self._plan_menu_pop = Gtk.Popover()
        _reset_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        _reset_box.set_margin_start(4)
        _reset_box.set_margin_end(4)
        _reset_box.set_margin_top(4)
        _reset_box.set_margin_bottom(4)
        self._plan_catchup_btn = Gtk.Button(label=_('Catch up to today'))
        self._plan_catchup_btn.add_css_class('flat')
        self._plan_catchup_btn.get_child().set_xalign(0)
        self._plan_catchup_btn.connect('clicked', self._on_plan_catch_up)
        _reset_box.append(self._plan_catchup_btn)
        _reset_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self._plan_reset_btn = Gtk.Button(label=_('Reset progress'))
        self._plan_reset_btn.add_css_class('flat')
        self._plan_reset_btn.get_child().set_xalign(0)
        self._plan_reset_btn.connect('clicked', self._on_plan_reset)
        _reset_box.append(self._plan_reset_btn)
        self._plan_menu_pop.set_child(_reset_box)
        self._plan_menu_btn.set_popover(self._plan_menu_pop)
        plan_hdr_box.append(self._plan_menu_btn)
        _body.append(plan_hdr_box)

        # Quiet plan switcher.
        plans = reading_plans.get_plans()
        plan_names = [_(p['name']) for p in plans]
        self._plan_ids = [p['id'] for p in plans]
        self._plan_drop = Gtk.DropDown(model=Gtk.StringList.new(plan_names))
        self._plan_drop.set_margin_start(12)
        self._plan_drop.set_margin_end(12)
        self._plan_drop.set_margin_top(6)
        self._plan_drop.set_margin_bottom(8)
        self._plan_drop_handler = self._plan_drop.connect(
            'notify::selected', self._on_plan_dropdown_changed)
        _body.append(self._plan_drop)

        # Not-started state: a one-line description + a single Start button.
        self._plan_desc_lbl = Gtk.Label(wrap=True, xalign=0)
        self._plan_desc_lbl.set_margin_start(12)
        self._plan_desc_lbl.set_margin_end(12)
        self._plan_desc_lbl.set_margin_bottom(10)
        self._plan_desc_lbl.add_css_class('dim-label')
        self._plan_desc_lbl.add_css_class('caption')
        _body.append(self._plan_desc_lbl)

        self._plan_start_btn = Gtk.Button(label=_('Start today'))
        self._plan_start_btn.add_css_class('suggested-action')
        self._plan_start_btn.set_halign(Gtk.Align.START)
        self._plan_start_btn.set_margin_start(12)
        self._plan_start_btn.set_margin_end(12)
        self._plan_start_btn.set_margin_bottom(8)
        self._plan_start_btn.connect('clicked', self._on_plan_start)
        _body.append(self._plan_start_btn)

        # Active-plan view: a "Today" hero, a slim progress meter, and a
        # tappable month dot-grid (done = accent fill, today = ring,
        # missed = hollow). Built/refreshed by _refresh_plan_ui.
        self._plan_active_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._plan_active_box.set_margin_start(14)
        self._plan_active_box.set_margin_end(14)

        self._plan_today_eyebrow = Gtk.Label(xalign=0)
        self._plan_today_eyebrow.add_css_class('caption')
        self._plan_today_eyebrow.add_css_class('plan-eyebrow')
        self._plan_active_box.append(self._plan_today_eyebrow)

        self._plan_today_passage = Gtk.Label(xalign=0, wrap=True)
        self._plan_today_passage.add_css_class('plan-today-passage')
        self._plan_today_passage.set_margin_top(1)
        self._plan_active_box.append(self._plan_today_passage)

        _today_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        _today_actions.set_margin_top(10)
        self._plan_open_btn = Gtk.Button(label=_('Open'))
        self._plan_open_btn.add_css_class('suggested-action')
        self._plan_open_btn.connect('clicked', self._on_plan_open_today)
        _today_actions.append(self._plan_open_btn)
        self._plan_today_check = Gtk.CheckButton(label=_('Mark done'))
        self._plan_today_check.set_valign(Gtk.Align.CENTER)
        self._plan_today_check_handler = self._plan_today_check.connect(
            'toggled', self._on_plan_today_check)
        _today_actions.append(self._plan_today_check)
        self._plan_active_box.append(_today_actions)

        self._plan_progress_bar = Gtk.ProgressBar()
        self._plan_progress_bar.add_css_class('plan-progress')
        self._plan_progress_bar.set_margin_top(16)
        self._plan_active_box.append(self._plan_progress_bar)
        self._plan_progress_lbl = Gtk.Label(xalign=0)
        self._plan_progress_lbl.add_css_class('caption')
        self._plan_progress_lbl.add_css_class('dim-label')
        self._plan_progress_lbl.set_margin_top(5)
        self._plan_active_box.append(self._plan_progress_lbl)

        self._plan_grid = Gtk.Grid()
        self._plan_grid.add_css_class('plan-grid')
        self._plan_grid.set_row_spacing(5)
        self._plan_grid.set_column_spacing(5)
        self._plan_grid.set_margin_top(14)
        # Spread the 7 columns across the full panel width rather than
        # crowding into a left-hand column.
        self._plan_grid.set_hexpand(True)
        self._plan_grid.set_halign(Gtk.Align.FILL)
        self._plan_grid.set_column_homogeneous(True)
        self._plan_active_box.append(self._plan_grid)

        _body.append(self._plan_active_box)

        # ── Study data: one-file backup / restore of everything the reader
        # accumulates by hand (annotations, bookmarks, plan progress) — the
        # data is otherwise trapped inside the Flatpak datadir. ──────────────
        _body.append(_section_header(_('Study Data')))
        data_group = Adw.PreferencesGroup()
        data_group.set_margin_start(12)
        data_group.set_margin_end(12)
        data_group.set_margin_bottom(8)
        for icon, label, handler in [
            ('document-save-symbolic', _('Back Up…'), self._on_backup_clicked),
            ('document-open-symbolic', _('Restore…'), self._on_restore_clicked),
        ]:
            row = Adw.ActionRow(title=label)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.set_activatable(True)
            row.connect('activated', handler)
            data_group.add(row)
        _body.append(data_group)

        # ── Footer: global utilities pinned to the bottom. The scroller above
        # is vexpand, so this stays anchored at the panel's foot — Apple-sidebar
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

        tips_btn = Gtk.Button(icon_name='scriptura-tips-symbolic')
        tips_btn.add_css_class('flat')
        tips_btn.add_css_class('menu-utility-action')
        tips_btn.set_tooltip_text(_('Tips & gestures'))
        set_accessible_label(tips_btn, _('Tips & gestures'))
        tips_btn.connect('clicked', self._open_tips_dialog)
        footer.append(tips_btn)

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
        return panel

    def _refresh_plan_ui(self):
        self._updating_plan = True
        plan_id, start_date = reading_plans.get_active()
        plans = reading_plans.get_plans()

        if plan_id and plan_id in self._plan_ids:
            self._plan_drop.set_selected(self._plan_ids.index(plan_id))
        sel_id = self._plan_ids[self._plan_drop.get_selected()]

        self._plan_chevron.set_from_icon_name(
            'pan-end-symbolic' if self._plan_collapsed else 'pan-down-symbolic')
        if self._plan_collapsed:
            # Folded: only the header row shows.
            for w in (self._plan_drop, self._plan_desc_lbl,
                      self._plan_start_btn, self._plan_menu_btn,
                      self._plan_active_box):
                w.set_visible(False)
            self._updating_plan = False
            return
        self._plan_drop.set_visible(True)

        plan_active = bool(start_date and reading_plans.get_active()[0] == sel_id)
        if plan_active:
            self._plan_desc_lbl.set_visible(False)
            self._plan_start_btn.set_visible(False)
            self._plan_menu_btn.set_visible(True)
            self._plan_active_box.set_visible(True)
            self._build_plan_view(sel_id, start_date)
        else:
            desc = next((p['description'] for p in plans if p['id'] == sel_id), '')
            self._plan_desc_lbl.set_text(_(desc) if desc else '')
            self._plan_desc_lbl.set_visible(bool(desc))
            self._plan_start_btn.set_visible(True)
            self._plan_menu_btn.set_visible(False)
            self._plan_active_box.set_visible(False)

        self._updating_plan = False

    def _build_plan_view(self, plan_id, start_date):
        """Populate the Today hero, progress meter, and dot grid for an
        active plan."""
        days = reading_plans.get_plan_days(plan_id)
        total = len(days)
        self._plan_id = plan_id
        try:
            self._plan_start_date = datetime.date.fromisoformat(start_date)
        except (TypeError, ValueError):
            self._plan_start_date = datetime.date.today()
        self._plan_days = days
        self._plan_total = total
        self._plan_completed = set(reading_plans.get_completed(plan_id))
        self._plan_today_idx = reading_plans.today_index(start_date)
        # Clamp the hero day into range so a finished or not-yet-due plan
        # still shows a real day.
        self._plan_anchor = (max(0, min(self._plan_today_idx, total - 1))
                             if total else 0)

        finished = bool(total) and self._plan_today_idx >= total
        self._plan_today_eyebrow.set_text(
            _('Plan complete') if finished
            else _('Day {n} · Today').format(n=self._plan_anchor + 1))
        self._plan_today_passage.set_text(
            reading_plans.format_passages(days[self._plan_anchor]) if total else '')

        self._plan_today_check.handler_block(self._plan_today_check_handler)
        self._plan_today_check.set_active(self._plan_anchor in self._plan_completed)
        self._plan_today_check.handler_unblock(self._plan_today_check_handler)

        self._update_plan_progress()
        self._build_plan_grid()

    def _update_plan_progress(self):
        total = self._plan_total
        done_n = len(self._plan_completed)
        self._plan_progress_bar.set_fraction(done_n / total if total else 0.0)
        self._plan_progress_lbl.set_text(ngettext(
            '{done} of {total} day read · tap a day to read',
            '{done} of {total} days read · tap a day to read',
            total).format(done=done_n, total=total))

    def _build_plan_grid(self):
        clear_children(self._plan_grid)
        self._plan_cells = {}
        cols = 7
        row = col = 0
        prev_month = None
        for idx in range(self._plan_total):
            date = self._plan_start_date + datetime.timedelta(days=idx)
            month = (date.year, date.month)
            if month != prev_month:
                # Start each calendar month on a fresh row under its header.
                if col != 0:
                    row += 1
                    col = 0
                header = Gtk.Label(label=self._format_plan_month(date), xalign=0)
                header.add_css_class('plan-month')
                self._plan_grid.attach(header, 0, row, cols, 1)
                row += 1
                prev_month = month
            cell = Gtk.Button(label=str(date.day))
            cell.add_css_class('plan-tile')
            cell.set_valign(Gtk.Align.CENTER)
            cell.set_halign(Gtk.Align.FILL)
            cell.set_hexpand(True)   # share the row width evenly
            summary = self._plan_day_summary(idx)
            cell.set_tooltip_text(summary)
            set_accessible_label(cell, summary)
            cell.connect('clicked', self._on_plan_dot_clicked, idx)
            self._style_plan_cell(cell, idx)
            self._plan_grid.attach(cell, col, row, 1, 1)
            self._plan_cells[idx] = cell
            col += 1
            if col == cols:
                col = 0
                row += 1

    def _format_plan_month(self, date):
        """Localized month header, e.g. 'Jun' — with the year once the plan
        crosses into a different calendar year than its start."""
        label = date.strftime('%b')
        if date.year != self._plan_start_date.year:
            label = f'{label} {date.year}'
        return label

    def _style_plan_cell(self, cell, idx):
        for c in ('plan-tile-done', 'plan-tile-today',
                  'plan-tile-overdue', 'plan-tile-ahead'):
            cell.remove_css_class(c)
        if idx in self._plan_completed:
            cell.add_css_class('plan-tile-done')
        elif idx < self._plan_today_idx:
            cell.add_css_class('plan-tile-overdue')  # a scheduled day went unread
        else:
            cell.add_css_class('plan-tile-ahead')
        if idx == self._plan_today_idx:
            cell.add_css_class('plan-tile-today')    # ring; composes with the fill

    def _plan_day_summary(self, idx):
        return _('Day {n} · {passages}').format(
            n=idx + 1,
            passages=reading_plans.format_passages(self._plan_days[idx]))

    def _on_plan_dot_clicked(self, cell, idx):
        pop = Gtk.Popover()
        pop.set_parent(cell)
        pop.set_has_arrow(True)
        pop.connect('closed', lambda p: p.unparent())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        eyebrow = Gtk.Label(label=_('Day {n}').format(n=idx + 1), xalign=0)
        eyebrow.add_css_class('caption')
        eyebrow.add_css_class('dim-label')
        box.append(eyebrow)
        # One tappable row per passage group — opens it and closes the menu.
        for book, start, end in reading_plans.group_readings(self._plan_days[idx]):
            label = (f'{book_label(book)} {start}' if start == end
                     else f'{book_label(book)} {start}–{end}')
            btn = Gtk.Button(label=label)
            btn.add_css_class('flat')
            btn.set_halign(Gtk.Align.FILL)
            btn.get_child().set_xalign(0)
            btn.connect('clicked', self._on_plan_passage_clicked, pop, book, start)
            box.append(btn)
        done_chk = Gtk.CheckButton(label=_('Mark done'))
        done_chk.set_margin_top(4)
        done_chk.set_active(idx in self._plan_completed)
        done_chk.connect(
            'toggled', lambda b, i=idx: self._set_plan_day_done(i, b.get_active()))
        box.append(done_chk)
        pop.set_child(box)
        pop.popup()

    def _set_plan_day_done(self, idx, done):
        reading_plans.set_day_done(self._plan_id, idx, done)
        if done:
            self._plan_completed.add(idx)
        else:
            self._plan_completed.discard(idx)
        cell = self._plan_cells.get(idx)
        if cell is not None:
            self._style_plan_cell(cell, idx)
        if idx == self._plan_anchor:
            self._plan_today_check.handler_block(self._plan_today_check_handler)
            self._plan_today_check.set_active(done)
            self._plan_today_check.handler_unblock(self._plan_today_check_handler)
        self._update_plan_progress()

    def _on_plan_today_check(self, btn):
        if self._updating_plan:
            return
        self._set_plan_day_done(self._plan_anchor, btn.get_active())

    def _on_plan_open_today(self, _btn):
        self._open_plan_day(self._plan_anchor, self._plan_open_btn)

    def _open_plan_day(self, idx, anchor):
        readings = self._plan_days[idx]
        if not readings:
            return
        groups = reading_plans.group_readings(readings)
        if len(groups) <= 1:
            book, chapter = readings[0]
            self._menu_split.set_show_sidebar(False)
            self._go_to(book, chapter)
            return
        # Multi-passage day: let the user pick which to open.
        pop = Gtk.Popover()
        pop.set_parent(anchor)
        pop.set_has_arrow(True)
        pop.connect('closed', lambda p: p.unparent())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        for book, start, end in groups:
            label = (f'{book_label(book)} {start}' if start == end
                     else f'{book_label(book)} {start}–{end}')
            btn = Gtk.Button(label=label)
            btn.add_css_class('flat')
            btn.set_halign(Gtk.Align.FILL)
            btn.get_child().set_xalign(0)
            btn.connect('clicked', self._on_plan_passage_clicked, pop, book, start)
            box.append(btn)
        pop.set_child(box)
        pop.popup()

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

    def _on_plan_toggle_collapse(self, _btn):
        self._plan_collapsed = not self._plan_collapsed
        settings.put('plan_collapsed', self._plan_collapsed)
        self._refresh_plan_ui()

    def _on_plan_catch_up(self, _btn):
        """Mark every day up to and including today read, in one action."""
        self._plan_menu_pop.popdown()
        last = min(self._plan_today_idx, self._plan_total - 1)
        if last < 0:
            return
        self._plan_completed = reading_plans.mark_done_through(self._plan_id, last)
        for idx, cell in self._plan_cells.items():
            self._style_plan_cell(cell, idx)
        self._plan_today_check.handler_block(self._plan_today_check_handler)
        self._plan_today_check.set_active(self._plan_anchor in self._plan_completed)
        self._plan_today_check.handler_unblock(self._plan_today_check_handler)
        self._update_plan_progress()

    def _on_plan_reset(self, _btn):
        self._plan_menu_pop.popdown()
        sel_id = self._plan_ids[self._plan_drop.get_selected()]
        reading_plans.reset_progress(sel_id)
        self._refresh_plan_ui()

    def _on_plan_passage_clicked(self, _btn, pop, book, chapter):
        pop.popdown()
        self._menu_split.set_show_sidebar(False)
        self._go_to(book, chapter)
