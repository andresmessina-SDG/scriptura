import html as _html_mod
import threading
import re
from datetime import date as _date, timedelta
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango
import sword_bridge
import ebible_bridge
import annotations
import settings

# Logical highlight IDs (persisted in annotations.json) → softer rendered tints.
# Persisted values are unchanged so existing user data still reads correctly;
# only the on-screen color is muted.
_HIGHLIGHT_RENDER = {
    '#ffff00': '#f5e6a3',  # yellow
    '#90ee90': '#c4dfb9',  # green
    '#add8e6': '#bdd5e8',  # blue
    '#ffa500': '#f0c894',  # orange
}


def _render_highlight(color):
    return _HIGHLIGHT_RENDER.get(color, color) if color else color


def _html_to_markup(html, dark):
    # Ensure we are working with a string
    html = str(html)
    # Strip lone surrogates that SWORD produces from non-UTF-8 module data
    if any('\ud800' <= c <= '\udfff' for c in html):
        html = ''.join(c for c in html if not ('\ud800' <= c <= '\udfff'))
    
    # 1. Map SWORD/HTML tags to temporary markers to protect them from escaping
    red = '#e07070' if dark else '#bb0000'
    
    # Red letters (Jesus' words)
    html = re.sub(r'<q [^>]*who="Jesus"[^>]*>(.*?)</q>', r'[[RED_S]]\1[[RED_E]]', html)
    html = re.sub(r'<font color="red">(.*?)</font>', r'[[RED_S]]\1[[RED_E]]', html)
    
    # Italics (translator additions)
    html = re.sub(r'<transChange type="added">(.*?)</transChange>', r'[[I_S]]\1[[I_E]]', html)
    html = re.sub(r'<i>(.*?)</i>', r'[[I_S]]\1[[I_E]]', html)
    
    # Titles and Headings
    html = re.sub(r'<title>(.*?)</title>', r'[[B_S]]\1[[B_E]]', html)
    html = re.sub(r'<h3>(.*?)</h3>', r'[[B_S]]\1[[B_E]]', html)
    html = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'[[B_S]]\1[[B_E]]', html)
    
    # 2. Strip all other tags (like <w>, <p>, etc.) but keep content
    html = re.sub(r'<[^>]+>', '', html)
    
    # 3. Escape the raw text so characters like '&' and '<' don't break Pango
    html = GLib.markup_escape_text(html)
    
    # 4. Swap markers back for real Pango Markup
    html = html.replace('[[RED_S]]', f'<span foreground="{red}">').replace('[[RED_E]]', '</span>')
    html = html.replace('[[I_S]]', '<i>').replace('[[I_E]]', '</i>')
    html = html.replace('[[B_S]]', '\n\n<b>').replace('[[B_E]]', '</b>\n')
    
    # Annotation styling (highlight, underline, note) is NOT baked into the
    # Pango markup anymore — it's applied via named tags after the verse
    # text is inserted so that right-click changes can be reflected in-place
    # without re-rendering the chapter (which would shift the scroll).

    # Clean up excess newlines
    html = re.sub(r'\n{3,}', '\n\n', html)

    return html.strip()


def _extract_segments(html):
    """Parse SWORD HTML into [(text_html, strong_num_or_None, morph_or_None)] in order."""
    html = str(html)
    segments = []
    pos = 0
    for m in re.finditer(r'<w(\s[^>]*)>(.*?)</w>', html, re.DOTALL):
        if m.start() > pos:
            segments.append((html[pos:m.start()], None, None))
        attrs = m.group(1)
        sm = re.search(r'strong:([GHgh]\d+)', attrs)
        strong_num = sm.group(1).upper() if sm else None
        mm = re.search(r'morph="([^"]+)"', attrs)
        morph = mm.group(1) if mm else None
        segments.append((m.group(2), strong_num, morph))
        pos = m.end()
    if pos < len(html):
        segments.append((html[pos:], None, None))
    return segments


def _make_verse_markup(html, target_strong):
    """Return Pango markup for a verse with words matching target_strong in bold."""
    segments = _extract_segments(str(html))
    if not any(s for _, s, _m in segments):
        plain = re.sub(r'<[^>]+>', '', str(html))
        return GLib.markup_escape_text(plain).strip()
    parts = []
    for seg_html, seg_strong, _morph in segments:
        plain = GLib.markup_escape_text(re.sub(r'<[^>]+>', '', seg_html))
        if seg_strong and seg_strong.upper() == target_strong.upper():
            parts.append(f'<b>{plain}</b>')
        else:
            parts.append(plain)
    return ''.join(parts).strip()


_hl_css_loaded = False

def _ensure_hl_css():
    global _hl_css_loaded
    if _hl_css_loaded:
        return
    _hl_css_loaded = True
    p = Gtk.CssProvider()
    p.load_from_data(b"""
    button.hl-yellow { background-color: #f5e6a3; color: #000; }
    button.hl-green  { background-color: #c4dfb9; color: #000; }
    button.hl-blue   { background-color: #bdd5e8; color: #000; }
    button.hl-orange { background-color: #f0c894; color: #000; }
    """)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER)


class BiblePane(Gtk.Box):
    def __init__(self, module_name=None, on_word_click=None,
                 on_click_outside_search=None, on_verse_select=None,
                 on_word_study_navigate=None, on_toast=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_word_click = on_word_click
        self._on_click_outside_search = on_click_outside_search
        self._on_verse_select = on_verse_select
        self._on_word_study_navigate = on_word_study_navigate
        self._on_toast = on_toast
        self._lexicon_enabled = False

        self._names = sword_bridge.module_names() + ebible_bridge.module_names()
        if not self._names:
            raise RuntimeError('No SWORD modules installed.')

        self._module = module_name if module_name in self._names else self._names[0]
        self._module_type = (
            'Biblical Texts' if ebible_bridge.is_ebible_module(self._module)
            else sword_bridge.module_type(self._module)
        )
        self._is_devotional = (
            not ebible_bridge.is_ebible_module(self._module)
            and sword_bridge.is_devotional_module(self._module)
        )
        self._book = 'Genesis'
        self._chapter = 1
        self._target_verse = None
        self._selected_verse = None
        self._devotional_date = _date.today()
        # Mirrors of the window's current location, kept updated even when
        # this pane is sync-locked — used to catch up on unlock.
        self._window_book = 'Genesis'
        self._window_chapter = 1
        self._window_target_verse = None

        # Pane toolbar: module selector
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._toolbar = toolbar
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        self.module_drop = Gtk.DropDown(model=Gtk.StringList.new(self._names))
        self.module_drop.set_hexpand(True)
        self.module_drop.set_size_request(120, -1)
        self.module_drop.set_enable_search(True)
        self.module_drop.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, 'string'))
        self.module_drop.set_selected(self._names.index(self._module))
        self._module_handler = self.module_drop.connect('notify::selected', self._on_module_changed)
        toolbar.append(self.module_drop)

        self._sync_btn = Gtk.ToggleButton(icon_name='changes-allow-symbolic')
        self._sync_btn.add_css_class('flat')
        self._sync_btn.set_tooltip_text('Following navigation')
        self._sync_btn.connect('notify::active', self._on_sync_toggled)
        toolbar.append(self._sync_btn)

        self._chapter_note_btn = Gtk.Button(icon_name='document-edit-symbolic')
        self._chapter_note_btn.add_css_class('flat')
        self._chapter_note_btn.set_tooltip_text('Chapter note')
        self._chapter_note_btn.connect('clicked', self._on_chapter_note_clicked)
        toolbar.append(self._chapter_note_btn)

        self._pane_search_btn = Gtk.ToggleButton(icon_name='system-search-symbolic')
        self._pane_search_btn.add_css_class('flat')
        self._pane_search_btn.set_tooltip_text('Search this module')
        self._pane_search_btn.connect('toggled', self._on_pane_search_toggled)
        toolbar.append(self._pane_search_btn)

        # Date navigation row — shown only for Daily Devotional modules
        date_nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        date_nav.set_margin_start(8)
        date_nav.set_margin_end(8)
        date_nav.set_margin_bottom(4)
        prev_day_btn = Gtk.Button(icon_name='go-previous-symbolic')
        prev_day_btn.add_css_class('flat')
        prev_day_btn.set_tooltip_text('Previous day')
        prev_day_btn.connect('clicked', lambda _: self._go_devotional_day(-1))
        self._date_label = Gtk.Label(label='', xalign=0.5, hexpand=True)
        self._date_label.add_css_class('heading')
        next_day_btn = Gtk.Button(icon_name='go-next-symbolic')
        next_day_btn.add_css_class('flat')
        next_day_btn.set_tooltip_text('Next day')
        next_day_btn.connect('clicked', lambda _: self._go_devotional_day(1))
        today_btn = Gtk.Button(label='Today')
        today_btn.add_css_class('flat')
        today_btn.connect('clicked', lambda _: self._go_devotional_day(0, reset=True))
        date_nav.append(prev_day_btn)
        date_nav.append(self._date_label)
        date_nav.append(today_btn)
        date_nav.append(next_day_btn)

        self._date_nav_revealer = Gtk.Revealer()
        self._date_nav_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._date_nav_revealer.set_child(date_nav)
        self._date_nav_revealer.set_reveal_child(False)

        self.append(toolbar)
        self.append(self._date_nav_revealer)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Per-pane inline search bar (revealed below toolbar)
        _sr_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        _se_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        _se_row.set_margin_start(8)
        _se_row.set_margin_end(8)
        _se_row.set_margin_top(6)
        _se_row.set_margin_bottom(6)
        self._pane_search_entry = Gtk.SearchEntry(hexpand=True)
        self._pane_search_entry.set_placeholder_text('Search this module…')
        self._pane_search_entry.connect('activate', self._on_pane_search)
        self._pane_search_entry.connect('stop-search',
                                        lambda _: self._pane_search_btn.set_active(False))
        self._pane_search_spinner = Gtk.Spinner()
        self._pane_search_spinner.set_visible(False)
        _se_row.append(self._pane_search_entry)
        _se_row.append(self._pane_search_spinner)
        _sr_inner.append(_se_row)
        _sr_inner.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._pane_search_status = Gtk.Label(label='', xalign=0)
        self._pane_search_status.add_css_class('dim-label')
        self._pane_search_status.add_css_class('caption')
        self._pane_search_status.set_margin_start(12)
        self._pane_search_status.set_margin_top(4)
        self._pane_search_status.set_margin_bottom(2)
        _sr_inner.append(self._pane_search_status)

        _ps_scroll = Gtk.ScrolledWindow()
        _ps_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        _ps_scroll.set_max_content_height(200)
        _ps_scroll.set_propagate_natural_height(True)
        self._pane_search_list = Gtk.ListBox()
        self._pane_search_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._pane_search_list.add_css_class('boxed-list')
        self._pane_search_list.set_margin_start(8)
        self._pane_search_list.set_margin_end(8)
        self._pane_search_list.set_margin_top(4)
        self._pane_search_list.set_margin_bottom(8)
        self._pane_search_list.connect('row-activated', self._on_pane_search_row)
        _ps_scroll.set_child(self._pane_search_list)
        _sr_inner.append(_ps_scroll)
        _sr_inner.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._pane_search_rev = Gtk.Revealer()
        self._pane_search_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._pane_search_rev.set_transition_duration(150)
        self._pane_search_rev.set_child(_sr_inner)
        self._pane_search_rev.set_reveal_child(False)
        self.append(self._pane_search_rev)

        # Ensure the pane itself can be shrunk by the user without UI elements pushing it
        self.set_size_request(150, -1)

        # Native TextView
        self._view = Gtk.TextView()
        self._view.set_editable(False)
        self._view.set_cursor_visible(False)
        self._view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._view.set_left_margin(26)
        self._view.set_right_margin(26)
        self._view.set_top_margin(18)
        self._view.set_bottom_margin(18)
        self._view.set_pixels_below_lines(8)
        
        self._font_size    = settings.get('font_size')
        self._font_family  = settings.get('font_family')
        self._line_spacing = settings.get('line_spacing')
        self._font_bold    = settings.get('font_bold')
        self._font_justify = settings.get('font_justify')
        self._text_color   = settings.get(f'text_color_{settings.get("color_scheme") or "default"}')
        self._css_provider = Gtk.CssProvider()
        self._view.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._update_font_css()

        self._buffer = self._view.get_buffer()

        # Cap the reading column width so long lines stay comfortable on wide
        # windows. The scrolled window is itself clamped — TextView stays a
        # direct Scrollable child of ScrolledWindow so scroll_to_iter() works
        # for verse-flash + cross-pane sync. (Wrapping the TextView in a
        # Clamp forces an implicit Viewport that breaks scroll propagation.)
        inner_scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        inner_scrolled.set_child(self._view)
        scrolled = Adw.Clamp()
        scrolled.set_maximum_size(720)
        scrolled.set_tightening_threshold(600)
        scrolled.set_child(inner_scrolled)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # Lexicon panel (hidden until a Strong's word is clicked)
        self._lex_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._lex_box.set_visible(False)
        self._lex_box.set_size_request(-1, 80)
        self._lex_box.add_css_class('lex-panel')
        self._lex_history = []
        self._current_strong = None
        self._current_morph = None
        self._flash_timers = set()

        lex_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lex_header.add_css_class('lex-header')
        lex_header.set_margin_start(12)
        lex_header.set_margin_end(8)
        lex_header.set_margin_top(6)
        lex_header.set_margin_bottom(6)

        self._lex_back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        self._lex_back_btn.add_css_class('flat')
        self._lex_back_btn.set_sensitive(False)
        self._lex_back_btn.set_tooltip_text('Back')
        self._lex_back_btn.connect('clicked', self._on_lex_back)
        lex_header.append(self._lex_back_btn)

        self._lex_title = Gtk.Label(label="Strong's Lexicon", xalign=0)
        self._lex_title.add_css_class('heading')
        lex_header.append(self._lex_title)

        self._morph_lbl = Gtk.Label(label='', xalign=0, hexpand=True)
        self._morph_lbl.add_css_class('dim-label')
        self._morph_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lex_header.append(self._morph_lbl)

        lex_close = Gtk.Button(icon_name='window-close-symbolic')
        lex_close.add_css_class('flat')
        lex_close.connect('clicked', lambda _: self._hide_lexicon())
        lex_header.append(lex_close)

        lex_scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._lex_inner = Gtk.TextView()
        self._lex_inner.set_editable(False)
        self._lex_inner.set_cursor_visible(False)
        self._lex_inner.set_wrap_mode(Gtk.WrapMode.WORD)
        self._lex_inner.set_left_margin(16)
        self._lex_inner.set_right_margin(16)
        self._lex_inner.set_top_margin(8)
        self._lex_inner.set_bottom_margin(8)
        self._lex_buf = self._lex_inner.get_buffer()
        lex_scrolled.set_child(self._lex_inner)

        gesture_lex = Gtk.GestureClick.new()
        gesture_lex.set_button(1)
        gesture_lex.connect('pressed', self._on_lex_click)
        self._lex_inner.add_controller(gesture_lex)

        # Word study panel (right third of lexicon area)
        ws_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ws_box.add_css_class('ws-panel')

        # Badge-style header — distinct from the main lexicon title so the
        # two stop competing as equal-weight headings.
        self._ws_header = Gtk.Label(label='', xalign=0, hexpand=True)
        self._ws_header.add_css_class('ws-header')
        ws_box.append(self._ws_header)

        self._ws_list = Gtk.ListBox()
        self._ws_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._ws_list.connect('row-activated', self._on_ws_row_activated)

        ws_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        ws_scroll.set_child(self._ws_list)
        ws_box.append(ws_scroll)

        # Horizontal paned: definition left, word study right
        self._lex_h_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                                      hexpand=True, vexpand=True)
        self._lex_h_paned.set_start_child(lex_scrolled)
        self._lex_h_paned.set_end_child(ws_box)
        self._lex_h_paned.set_resize_start_child(True)
        self._lex_h_paned.set_resize_end_child(True)
        self._lex_h_paned.set_shrink_start_child(False)
        self._lex_h_paned.set_shrink_end_child(False)

        self._lex_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self._lex_box.append(lex_header)
        self._lex_box.append(self._lex_h_paned)

        # Vertical paned: Bible text on top, lexicon on bottom (resizable)
        self._lex_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL,
                                    vexpand=True, hexpand=True)
        self._lex_paned.set_start_child(scrolled)
        self._lex_paned.set_end_child(self._lex_box)
        self._lex_paned.set_resize_start_child(True)
        self._lex_paned.set_resize_end_child(True)
        self._lex_paned.set_shrink_start_child(False)
        self._lex_paned.set_shrink_end_child(True)
        self.append(self._lex_paned)

        # Context Menu for Study Tools
        gesture = Gtk.GestureClick.new()
        gesture.set_button(3) # Right click
        # Set phase to CAPTURE so we get it before the TextView's internal menu handler
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect('pressed', self._on_right_click)
        self._view.add_controller(gesture)

        # Strong's word lookup on left click
        gesture_left = Gtk.GestureClick.new()
        gesture_left.set_button(1)
        gesture_left.connect('pressed', self._on_left_click)
        self._view.add_controller(gesture_left)

        # Dictionary lookup on double-click — CAPTURE phase so n_press counts correctly
        # before the TextView's own selection gesture claims the event sequence
        gesture_dict = Gtk.GestureClick.new()
        gesture_dict.set_button(1)
        gesture_dict.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture_dict.connect('pressed', self._on_dict_click)
        self._view.add_controller(gesture_dict)

        # Gesture to close search panel on click outside
        gesture_close_search_view = Gtk.GestureClick.new()
        gesture_close_search_view.set_button(1)
        gesture_close_search_view.connect('pressed', self._on_pane_click)
        self._view.add_controller(gesture_close_search_view)
        
        # Gesture to close search panel on click outside for lexicon
        gesture_close_search_lex = Gtk.GestureClick.new()
        gesture_close_search_lex.set_button(1)
        gesture_close_search_lex.connect('pressed', self._on_pane_click)
        self._lex_inner.add_controller(gesture_close_search_lex)

        # Hover-only Strong's underline — apply a transient underline tag
        # to the word under the cursor, instead of a permanent underline
        # on every Strong's-tagged word in the chapter.
        self._strg_hover_range = None
        motion = Gtk.EventControllerMotion.new()
        motion.connect('motion', self._on_view_motion)
        motion.connect('leave', lambda _c: self._clear_strg_hover())
        self._view.add_controller(motion)

        # Re-render when system theme switches dark/light
        Adw.StyleManager.get_default().connect('notify::dark', self._on_theme_changed)

        # Apply initial devotional mode if starting with a devotional module
        if self._is_devotional:
            self._date_nav_revealer.set_reveal_child(True)
            self._sync_btn.set_visible(False)
            self._chapter_note_btn.set_visible(False)
            self._pane_search_btn.set_visible(False)
            self._sync_btn.set_active(True)
            GLib.idle_add(self._fetch_and_render_devotional)

    def _on_pane_click(self, gesture, n_press, x, y):
        """Called when a pane or lexicon text view is clicked."""
        if self._on_click_outside_search:
            self._on_click_outside_search()

    def load_reference(self, book, chapter):
        # Track the window's location even when sync is locked — so toggling
        # back to "Following" can catch up to where the rest of the app is.
        self._window_book = book
        self._window_chapter = chapter
        self._window_target_verse = None
        if self._sync_btn.get_active():
            return
        self._book = book
        self._chapter = chapter
        self._fetch_and_render()

    def load_reference_at_verse(self, book, chapter, verse):
        self._window_book = book
        self._window_chapter = chapter
        self._window_target_verse = verse
        if self._sync_btn.get_active():
            return
        self._book = book
        self._chapter = chapter
        self._target_verse = verse
        self._fetch_and_render()

    def _update_font_css(self):
        weight = 'bold' if self._font_bold else 'normal'
        # Expand the generic 'serif' default into a curated reading stack;
        # respect any explicit family the user has chosen.
        if self._font_family == 'serif':
            family_decl = "'Source Serif 4', 'Source Serif Pro', 'Charter', " \
                          "'Iowan Old Style', 'Georgia', serif"
        else:
            family_decl = f"'{self._font_family}', serif"
        # In dark mode, default to a warm off-white instead of pure white —
        # easier on the eyes for long reading sessions. Honors any user override.
        if self._text_color:
            color_rule = f"color: {self._text_color}; "
        elif Adw.StyleManager.get_default().get_dark():
            color_rule = "color: #e8e0d4; "
        else:
            color_rule = ""
        css = (f"textview {{ font-family: {family_decl}; "
               f"font-size: {self._font_size}pt; "
               f"font-weight: {weight}; "
               f"line-height: {self._line_spacing}; "
               f"{color_rule}}}")
        self._css_provider.load_from_data(css.encode())
        just = Gtk.Justification.FILL if self._font_justify else Gtk.Justification.LEFT
        self._view.set_justification(just)

    def set_appearance(self, **kwargs):
        if 'font_size'    in kwargs: self._font_size    = kwargs['font_size']
        if 'font_family'  in kwargs: self._font_family  = kwargs['font_family']
        if 'line_spacing' in kwargs: self._line_spacing = kwargs['line_spacing']
        if 'font_bold'    in kwargs: self._font_bold    = kwargs['font_bold']
        if 'font_justify' in kwargs: self._font_justify = kwargs['font_justify']
        if 'text_color'   in kwargs: self._text_color   = kwargs['text_color']
        self._update_font_css()

    def set_font_size(self, size):
        self.set_appearance(font_size=size)

    def _on_sync_toggled(self, btn, _param):
        locked = btn.get_active()
        btn.set_icon_name('changes-prevent-symbolic' if locked else 'changes-allow-symbolic')
        btn.set_tooltip_text('Locked – not following navigation' if locked else 'Following navigation')
        # When re-enabling "Following navigation", catch up to wherever the rest
        # of the app has navigated to since the lock was applied.
        if not locked and getattr(self, '_window_book', None):
            wb, wc = self._window_book, self._window_chapter
            if (self._book, self._chapter) != (wb, wc):
                self._book = wb
                self._chapter = wc
                self._target_verse = getattr(self, '_window_target_verse', None)
                self._fetch_and_render()

    def set_lexicon_enabled(self, enabled):
        self._lexicon_enabled = enabled
        self._fetch_and_render()

    def _fetch_and_render(self):
        if self._is_devotional:
            self._fetch_and_render_devotional()
            return
        book, chapter, module = self._book, self._chapter, self._module

        def fetch():
            if ebible_bridge.is_ebible_module(module):
                verses = ebible_bridge.load_chapter(module, book, chapter)
            else:
                verses = sword_bridge.load_chapter(module, book, chapter)
            GLib.idle_add(self._display, verses, book, chapter, module)

        threading.Thread(target=fetch, daemon=True).start()

    def _fetch_and_render_devotional(self):
        module = self._module
        date_obj = self._devotional_date
        self._date_label.set_text(date_obj.strftime('%B %-d, %Y'))

        def fetch():
            raw = sword_bridge.get_devotional_raw(module, date_obj)
            GLib.idle_add(self._display_devotional, raw, module, date_obj)

        threading.Thread(target=fetch, daemon=True).start()

    def _display_devotional(self, raw, module, date_obj):
        if module != self._module or date_obj != self._devotional_date:
            return GLib.SOURCE_REMOVE
        dark = Adw.StyleManager.get_default().get_dark()
        self._cancel_all_flashes()
        self._buffer.set_text('')
        if raw:
            self._render_devotional_osis(raw, dark)
        else:
            self._buffer.insert_markup(
                self._buffer.get_end_iter(),
                '<span foreground="gray">No entry found for this date.</span>', -1)
        self._view.get_vadjustment().set_value(0)
        return GLib.SOURCE_REMOVE

    def _render_devotional_osis(self, raw, dark):
        link_color = '#4a9dff' if dark else '#1a6ac4'

        title_m = re.search(r'<title[^>]*>(.*?)</title>', raw, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ''

        p_blocks = re.findall(r'<p\b[^>]*>(.*?)</p>', raw, re.DOTALL)

        if not p_blocks:
            # Fallback: strip all tags
            if title:
                self._buffer.insert_markup(
                    self._buffer.get_end_iter(),
                    f'<b><big>{GLib.markup_escape_text(title)}</big></b>\n\n', -1)
            plain = re.sub(r'<[^>]+>', ' ', raw).strip()
            self._buffer.insert(self._buffer.get_end_iter(), re.sub(r'\s+', ' ', plain))
            return

        if title:
            self._buffer.insert_markup(
                self._buffer.get_end_iter(),
                f'<b><big>{GLib.markup_escape_text(title)}</big></b>\n\n', -1)

        # Detect section headers — a <p> with both an italic quote AND a
        # <reference> marks the start of a devotional section. SME packs the
        # morning + evening readings into one entry, so we label the second
        # (and any subsequent) sections to make the boundary obvious.
        def _is_section_header(p):
            return bool(
                re.search(r'<hi\b[^>]*type=["\']italic["\'][^>]*>', p) and
                re.search(r'<reference\b', p)
            )

        section_starts = [i for i, p in enumerate(p_blocks) if _is_section_header(p)]
        multi_section  = len(section_starts) > 1
        # Default labels for two-section SME-style entries; generic numbering otherwise.
        labels = (['Morning', 'Evening']
                  if len(section_starts) == 2
                  else [f'Part {i + 1}' for i in range(len(section_starts))])

        section_idx = -1
        for i, p in enumerate(p_blocks):
            if i in section_starts:
                section_idx += 1
                if multi_section:
                    if section_idx > 0:
                        # Spacer + label between sections
                        self._buffer.insert_markup(
                            self._buffer.get_end_iter(), '\n', -1)
                    label = labels[section_idx] if section_idx < len(labels) else f'Part {section_idx + 1}'
                    self._buffer.insert_markup(
                        self._buffer.get_end_iter(),
                        f'<b><big>{GLib.markup_escape_text(label)}</big></b>\n', -1)
                # Italic quote
                quote_m = re.search(r'<hi\b[^>]*type=["\']italic["\'][^>]*>(.*?)</hi>',
                                     p, re.DOTALL)
                if quote_m:
                    quote = re.sub(r'<[^>]+>', '', quote_m.group(1)).strip()
                    if quote:
                        self._buffer.insert_markup(
                            self._buffer.get_end_iter(),
                            f'<i>{GLib.markup_escape_text(quote)}</i>\n', -1)
                # Clickable reference
                ref_m = re.search(r'<reference[^>]+osisRef="([^"]+)"[^>]*>(.*?)</reference>',
                                  p, re.DOTALL)
                if ref_m:
                    osis_ref = ref_m.group(1)
                    display  = re.sub(r'<[^>]+>', '', ref_m.group(2)).strip() or osis_ref
                    clean    = osis_ref[6:] if osis_ref.startswith('Bible:') else osis_ref
                    self._insert_devotional_ref(display, clean, link_color)
                    self._buffer.insert(self._buffer.get_end_iter(), '\n')
                self._buffer.insert(self._buffer.get_end_iter(), '\n')
            else:
                text = re.sub(r'<lb\s*/?>', '\n', p)
                text = re.sub(r'<[^>]+>', '', text).strip()
                text = re.sub(r'\s+', ' ', text)
                if text:
                    self._buffer.insert(self._buffer.get_end_iter(), text + '\n\n')

    def _insert_devotional_ref(self, display_text, osis_ref, link_color):
        start_offset = self._buffer.get_char_count()
        self._buffer.insert(self._buffer.get_end_iter(), display_text)
        end_offset = self._buffer.get_char_count()
        tag_name = f'devref:{osis_ref}'
        tag = self._buffer.get_tag_table().lookup(tag_name)
        if not tag:
            tag = self._buffer.create_tag(
                tag_name,
                foreground=link_color,
                underline=Pango.Underline.SINGLE,
            )
        s = self._buffer.get_iter_at_offset(start_offset)
        e = self._buffer.get_iter_at_offset(end_offset)
        self._buffer.apply_tag(tag, s, e)

    def _go_devotional_day(self, delta, reset=False):
        if reset:
            self._devotional_date = _date.today()
        else:
            self._devotional_date += timedelta(days=delta)
        self._fetch_and_render_devotional()

    def _display(self, verses, book, chapter, module):
        if book != self._book or chapter != self._chapter or module != self._module:
            return GLib.SOURCE_REMOVE

        dark = Adw.StyleManager.get_default().get_dark()
        annos = annotations.get_annotations(module, book, chapter)
        is_commentary = self._module_type == 'Commentaries'

        self._cancel_all_flashes()
        self._buffer.set_text('')

        # Chapter heading — muted, sits above the first verse and scrolls with text.
        # Bibles only; commentary modules already emit their own per-verse headers.
        if not is_commentary:
            heading_color = '#8d8278' if dark else '#7a7066'
            heading = (f'<span size="x-large" weight="bold" '
                       f'foreground="{heading_color}" letter_spacing="600">'
                       f'{GLib.markup_escape_text(f"{book} {chapter}")}</span>\n\n')
            self._buffer.insert_markup(self._buffer.get_end_iter(), heading, -1)

        for v, html in verses:
            plain = re.sub(r'<[^>]+>', '', str(html)).strip()

            # Commentary: skip verses with no meaningful content
            if is_commentary and len(plain) < 20:
                continue

            start_mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), True)

            # 1. Verse number — inline for Bibles, bold section header for commentaries
            if is_commentary:
                header = f'\n<b>Verse {v}</b>\n' if self._buffer.get_char_count() > 0 else f'<b>Verse {v}</b>\n'
                self._buffer.insert_markup(self._buffer.get_end_iter(), header, -1)
            else:
                v_num_markup = f'<span foreground="gray" size="small" weight="bold" rise="6000"> {v} </span>'
                self._buffer.insert_markup(self._buffer.get_end_iter(), v_num_markup, -1)

            text_start_mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), True)

            # 2. Verse text
            v_anno = annos.get(str(v), {})
            v_text_markup = _html_to_markup(html, dark)
            # Drop-cap: enlarge the first letter of verse 1 for a print-Bible feel.
            # Skip the dropcap on highlighted v1 — the soft tint reads better as a flat block.
            if not is_commentary and v == 1 and not v_anno.get('highlight'):
                m = re.match(r'((?:<[^>]+>)*)([A-Za-z])', v_text_markup)
                if m:
                    v_text_markup = (
                        f'{m.group(1)}<span size="200%" weight="bold" rise="-2000">'
                        f'{m.group(2)}</span>{v_text_markup[m.end():]}'
                    )
            try:
                suffix = '\n' if is_commentary else ' '
                self._buffer.insert_markup(self._buffer.get_end_iter(), v_text_markup + suffix, -1)
            except Exception:
                self._buffer.insert(self._buffer.get_end_iter(), plain + ('\n' if is_commentary else ' '))

            # 3. Apply vnum tag for click targeting and navigation
            start_iter = self._buffer.get_iter_at_mark(start_mark)
            tag_name = f'vnum_{v}'
            tag = self._buffer.get_tag_table().lookup(tag_name)
            if not tag:
                tag = self._buffer.create_tag(tag_name)
            self._buffer.apply_tag(tag, start_iter, self._buffer.get_end_iter())

            # 4. Apply persistent annotation tags (highlight/underline/note
            # indicator) in-place — these can be changed later without a
            # full re-render via _refresh_verse_annotation. Bibles only;
            # commentaries don't get user annotations.
            if not is_commentary:
                self._apply_anno_tags(v, v_anno)

            # 5. Strong's word tagging (Bible mode only)
            if not is_commentary and self._lexicon_enabled and self._on_word_click:
                t_start = self._buffer.get_iter_at_mark(text_start_mark)
                self._tag_strong_words(t_start, self._buffer.get_end_iter(), html)

            self._buffer.delete_mark(start_mark)
            self._buffer.delete_mark(text_start_mark)

        if self._target_verse is not None:
            v = self._target_verse
            self._target_verse = None
            GLib.idle_add(self._scroll_to_verse, v)
        else:
            self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)

        self._update_chapter_note_indicator()
        return GLib.SOURCE_REMOVE

    def _scroll_to_verse(self, verse_num):
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if tag:
            it = self._buffer.get_start_iter()
            if not it.has_tag(tag):
                # The tag may exist in the table from an earlier chapter that
                # had more verses, even if it's unused in the current buffer.
                # forward_to_tag_toggle returns False AND moves the iter to
                # end_iter on miss — without this guard we'd scroll to the
                # buffer end and _flash_verse would bail, looking like a
                # successful scroll with no highlight.
                if not it.forward_to_tag_toggle(tag):
                    return GLib.SOURCE_REMOVE
            # Use scroll_to_mark, not scroll_to_iter — scroll_to_iter uses
            # currently-computed line heights, which are stale right after a
            # fresh chapter render. scroll_to_mark defers the scroll until
            # line validation completes.
            mark = self._buffer.create_mark(None, it, True)
            self._view.scroll_to_mark(mark, 0.1, True, 0.0, 0.2)
            self._buffer.delete_mark(mark)
            # Defer the flash by ~150ms so scroll has fully settled and the
            # verse is actually in the viewport. Applying the flash in the
            # same idle iteration as the scroll request leaves the tag at
            # the right buffer offset but on a region that's still off-screen
            # for verses deeper in long chapters (e.g. LEB Deut 6:16,
            # 1 Cor 10:9). A short delay is more reliable than chaining
            # idle_add because GTK4's line validation isn't synchronous.
            GLib.timeout_add(150, self._flash_verse_deferred, verse_num)
        return GLib.SOURCE_REMOVE

    def _flash_verse_deferred(self, verse_num):
        self._flash_verse(verse_num)
        return GLib.SOURCE_REMOVE

    def _verse_ranges(self, verse_num):
        """Return (vnum_start, vtext_start, vtext_end) iters for verse_num
        in the current buffer, or None if the verse isn't applied here.

        The verse number span is rendered as " {N} " (leading space, digits,
        trailing space) — so vtext_start is len(str(N))+2 chars past
        vnum_start. This lets highlight/underline tags target the verse
        text only, leaving the gray verse number untouched."""
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if not tag:
            return None
        vnum_start = self._buffer.get_start_iter()
        if not vnum_start.has_tag(tag):
            if not vnum_start.forward_to_tag_toggle(tag):
                return None
        vtext_end = vnum_start.copy()
        vtext_end.forward_to_tag_toggle(tag)
        vtext_start = vnum_start.copy()
        vtext_start.forward_chars(len(str(verse_num)) + 2)
        return vnum_start, vtext_start, vtext_end

    def _apply_anno_tags(self, verse_num, anno):
        """Idempotently apply highlight / underline / note-indicator tags
        for verse_num based on the given annotation dict. Clears any prior
        annotation tags first. Does not modify the buffer text — pure tag
        manipulation, so the scroll position is preserved."""
        ranges = self._verse_ranges(verse_num)
        if not ranges:
            return
        vnum_start, vtext_start, vtext_end = ranges
        table = self._buffer.get_tag_table()

        # Clear any previous annotation tags from the verse's ranges.
        old_tags = []
        def _collect(t, _data):
            name = t.get_property('name') or ''
            if name.startswith('hl_') or name == '_ul_text':
                old_tags.append(t)
        table.foreach(_collect, None)
        for t in old_tags:
            self._buffer.remove_tag(t, vtext_start, vtext_end)
        note_tag = table.lookup('_note_marker')
        if note_tag:
            self._buffer.remove_tag(note_tag, vnum_start, vtext_start)

        if not anno:
            return
        if isinstance(anno, str):
            anno = {'highlight': anno, 'underline': False, 'note': None}

        def _bump(t):
            # Annotation tags created during chapter render get out-prioritized
            # by anonymous insert_markup tags created on later chapter renders
            # (same priority-decay we hit with flash). Bump to top each apply.
            t.set_priority(table.get_size() - 1)

        highlight = anno.get('highlight')
        if highlight:
            rendered = _render_highlight(highlight)
            name = f'hl_{rendered}'
            tag = table.lookup(name)
            if not tag:
                tag = self._buffer.create_tag(
                    name, background=rendered, foreground='black')
            _bump(tag)
            self._buffer.apply_tag(tag, vtext_start, vtext_end)

        if anno.get('underline'):
            ul = table.lookup('_ul_text')
            if not ul:
                ul = self._buffer.create_tag(
                    '_ul_text', underline=Pango.Underline.DOUBLE)
            _bump(ul)
            self._buffer.apply_tag(ul, vtext_start, vtext_end)

        if anno.get('note'):
            nt = table.lookup('_note_marker')
            if not nt:
                nt = self._buffer.create_tag(
                    '_note_marker',
                    foreground='#5b8def',
                    weight=Pango.Weight.BOLD,
                )
            _bump(nt)
            self._buffer.apply_tag(nt, vnum_start, vtext_start)

    def _refresh_verse_annotation(self, verse_num):
        """Re-read this verse's stored annotation and re-apply the visual
        tags. Called by the in-place right-click handlers so the buffer
        text doesn't have to be rebuilt."""
        annos = annotations.get_annotations(
            self._module, self._book, self._chapter)
        v_anno = (annos or {}).get(str(verse_num), {})
        self._apply_anno_tags(verse_num, v_anno)

    def _flash_verse(self, verse_num):
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if not tag:
            return

        # Find the exact start of this verse's tag range
        start = self._buffer.get_start_iter()
        if not start.has_tag(tag):
            if not start.forward_to_tag_toggle(tag):
                return

        # Find the end: forward_to_tag_toggle from inside the tag skips
        # the toggle AT the current position and lands on the closing toggle
        end = start.copy()
        end.forward_to_tag_toggle(tag)

        flash_tag = self._buffer.get_tag_table().lookup('_flash')
        if not flash_tag:
            # Pale yellow on black text in both light and dark modes — keeps
            # the flash unambiguous against any theme background (including
            # blue-tinted dark themes where a blue flash camouflages).
            flash_tag = self._buffer.create_tag(
                '_flash',
                background='#fff176',
                foreground='black',
            )
        # Always pin flash to the highest priority — every chapter render
        # creates fresh anonymous tags via insert_markup (highlights, drop-cap,
        # red letters), and any of those added after the flash tag's creation
        # would otherwise out-prioritize its background.
        table = self._buffer.get_tag_table()
        flash_tag.set_priority(table.get_size() - 1)

        self._buffer.apply_tag(flash_tag, start, end)
        # Force the textview to repaint — apply_tag alone sometimes fails to
        # invalidate the right screen region after a scroll, leaving the
        # tag applied at the correct buffer offset but the visible verse
        # rendered as if the tag isn't there.
        self._view.queue_draw()
        start_offset = start.get_offset()
        end_offset = end.get_offset()
        # Each flash runs its own timer. Rapid clicks on multiple verses
        # would otherwise cancel earlier timers and leave their highlights stuck.
        # Buffer-reset paths (chapter/module change) clear all pending flashes
        # via _cancel_all_flashes() so stale offsets can't leak into new content.
        holder = [0]

        def _expire():
            self._flash_timers.discard(holder[0])
            ft = self._buffer.get_tag_table().lookup('_flash')
            if ft:
                s = self._buffer.get_iter_at_offset(start_offset)
                e = self._buffer.get_iter_at_offset(end_offset)
                self._buffer.remove_tag(ft, s, e)
            return GLib.SOURCE_REMOVE

        holder[0] = GLib.timeout_add(1000, _expire)
        self._flash_timers.add(holder[0])

    def _cancel_all_flashes(self):
        for sid in list(self._flash_timers):
            try:
                GLib.source_remove(sid)
            except Exception:
                pass
        self._flash_timers.clear()
        flash_tag = self._buffer.get_tag_table().lookup('_flash')
        if flash_tag:
            self._buffer.remove_tag(
                flash_tag,
                self._buffer.get_start_iter(),
                self._buffer.get_end_iter(),
            )


    def _tag_strong_words(self, start_iter, end_iter, raw_html):
        segments = _extract_segments(raw_html)
        if not any(s for _, s, _m in segments):
            return

        verse_text = self._buffer.get_text(start_iter, end_iter, False)
        start_offset = start_iter.get_offset()
        search_pos = 0

        for word_html, strong_num, morph in segments:
            word_plain = _html_mod.unescape(re.sub(r'<[^>]+>', '', word_html))
            if not word_plain.strip():
                continue

            idx = verse_text.find(word_plain, search_pos)
            if idx == -1:
                stripped = word_plain.strip()
                idx = verse_text.find(stripped, search_pos)
                if idx == -1:
                    continue
                word_plain = stripped

            if strong_num:
                s = self._buffer.get_iter_at_offset(start_offset + idx)
                e = self._buffer.get_iter_at_offset(start_offset + idx + len(word_plain))
                tag_name = f"strg:{strong_num}"
                tag = self._buffer.get_tag_table().lookup(tag_name)
                if not tag:
                    # No static underline — every Bible verse otherwise turns
                    # into a wall of underlines. Discoverability is provided
                    # by the on-hover underline applied dynamically by
                    # _on_view_motion.
                    tag = self._buffer.create_tag(tag_name)
                self._buffer.apply_tag(tag, s, e)
                if morph:
                    morph_tag_name = f"morph:{morph}"
                    mtag = self._buffer.get_tag_table().lookup(morph_tag_name)
                    if not mtag:
                        mtag = self._buffer.create_tag(morph_tag_name)
                    self._buffer.apply_tag(mtag, s, e)

            search_pos = idx + len(word_plain)

    def _on_view_motion(self, controller, x, y):
        """Apply a transient hover-underline tag to the Strong's-tagged
        word under the cursor; clear when the cursor leaves any tagged word."""
        if not self._lexicon_enabled:
            self._clear_strg_hover()
            return
        bx, by = self._view.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            self._clear_strg_hover()
            return
        has_strg = any(
            (t.get_property('name') or '').startswith('strg:')
            for t in it.get_tags()
        )
        if not has_strg:
            self._clear_strg_hover()
            return
        # Find the word boundaries around `it` and apply the hover tag there.
        word_start = it.copy()
        word_end = it.copy()
        if not word_start.starts_word():
            word_start.backward_word_start()
        if not word_end.ends_word():
            word_end.forward_word_end()
        new_range = (word_start.get_offset(), word_end.get_offset())
        if new_range == self._strg_hover_range:
            return
        self._clear_strg_hover()
        hover_tag = self._buffer.get_tag_table().lookup('_strg_hover')
        if not hover_tag:
            # Subtle: thin underline, slightly muted accent color. The
            # tag is created lazily so its priority lands above the
            # anonymous span tags created during chapter render.
            dark = Adw.StyleManager.get_default().get_dark()
            hover_tag = self._buffer.create_tag(
                '_strg_hover',
                underline=Pango.Underline.SINGLE,
                foreground='#7fa3c1' if dark else '#5a7fa3',
            )
        table = self._buffer.get_tag_table()
        hover_tag.set_priority(table.get_size() - 1)
        self._buffer.apply_tag(hover_tag, word_start, word_end)
        self._strg_hover_range = new_range

    def _clear_strg_hover(self):
        if self._strg_hover_range is None:
            return
        hover_tag = self._buffer.get_tag_table().lookup('_strg_hover')
        if hover_tag:
            s = self._buffer.get_iter_at_offset(self._strg_hover_range[0])
            e = self._buffer.get_iter_at_offset(self._strg_hover_range[1])
            self._buffer.remove_tag(hover_tag, s, e)
        self._strg_hover_range = None

    def _on_left_click(self, gesture, n_press, x, y):
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return
        verse_num = None
        strong_num = None
        morph = None
        devref = None
        for tag in it.get_tags():
            name = tag.get_property('name')
            if name and name.startswith('strg:'):
                strong_num = name[5:]
            elif name and name.startswith('vnum_'):
                try:
                    verse_num = int(name.split('_')[1])
                except (ValueError, IndexError):
                    pass
            elif name and name.startswith('morph:'):
                morph = name[6:]
            elif name and name.startswith('devref:'):
                devref = name[7:]
        if n_press > 1:
            return
        if devref:
            result = sword_bridge.parse_osis_ref(devref)
            if result and self._on_word_study_navigate:
                self._on_word_study_navigate(*result)
            return
        if verse_num is not None:
            self._selected_verse = verse_num
        if strong_num and self._on_word_click:
            self._current_morph = morph
            self._on_word_click(self, strong_num)
        # Broadcast on every verse click, even when this pane's _selected_verse
        # already matches — it may match because the OTHER pane just broadcast
        # this same verse to us (select_verse writes _selected_verse on the
        # receiving pane). Suppressing the back-broadcast here meant pane2 → pane1
        # never re-highlighted after pane1 had previously broadcast to pane2.
        # No infinite-loop risk: select_verse() doesn't call _on_verse_select.
        if verse_num is not None and self._on_verse_select:
            self._on_verse_select(self, verse_num)

    def _on_dict_click(self, gesture, n_press, x, y):
        if n_press != 2:
            return
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return
        # Suppress only on navigation links (devref); Strong's-tagged words
        # should still open the dict popup on double-click — the lexicon
        # opens on the first click, the dict on the second.
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith('devref:'):
                return
        word_start = it.copy()
        word_end = it.copy()
        if not word_start.starts_word():
            word_start.backward_word_start()
        if not word_end.ends_word():
            word_end.forward_word_end()
        word = self._buffer.get_text(word_start, word_end, False).strip()
        if word and word.replace("'", '').replace('’', '').isalpha():
            offset = word_start.get_offset()
            GLib.idle_add(self._show_dict_popup, word, offset)

    def _show_dict_popup(self, word, word_offset):
        # Close any prior dict window cleanly
        prev = getattr(self, '_dict_win', None)
        if prev is not None:
            try:
                prev.close()
            except Exception:
                pass
            self._dict_win = None

        root = self._view.get_root()
        win = Adw.Window(transient_for=root, modal=False)
        win.set_default_size(380, 300)
        self._dict_win = win

        # Clear the slot when the user closes via ESC / X, so a later double-click
        # doesn't call .close() on an already-destroyed window.
        def _on_close(_w):
            if self._dict_win is win:
                self._dict_win = None
            return False
        win.connect('close-request', _on_close)

        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect('key-pressed',
                         lambda _c, kv, _kc, _s: win.close() or True
                         if kv == Gdk.KEY_Escape else False)
        win.add_controller(key_ctrl)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)
        win.set_content(toolbar_view)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        title_widget = Adw.WindowTitle(title=word.capitalize(), subtitle='Dictionary')
        header.set_title_widget(title_widget)

        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_margin_top(24)
        spinner.set_margin_bottom(24)
        spinner.set_halign(Gtk.Align.CENTER)
        content.append(spinner)
        toolbar_view.set_content(content)

        win.present()

        def _clear():
            child = content.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                content.remove(child)
                child = nxt

        def _hint(text):
            lbl = Gtk.Label(label=text, wrap=True, xalign=0)
            lbl.add_css_class('dim-label')
            lbl.set_margin_start(18)
            lbl.set_margin_end(18)
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
            content.append(lbl)

        def _add_text(html, box=None):
            if box is None:
                box = content
            dark = Adw.StyleManager.get_default().get_dark()
            scroll = Gtk.ScrolledWindow(vexpand=True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_cursor_visible(False)
            tv.set_wrap_mode(Gtk.WrapMode.WORD)
            tv.set_left_margin(18)
            tv.set_right_margin(18)
            tv.set_top_margin(12)
            tv.set_bottom_margin(12)
            buf = tv.get_buffer()
            markup = _html_to_markup(html, dark)
            try:
                buf.insert_markup(buf.get_end_iter(), markup, -1)
            except Exception:
                buf.set_text(re.sub(r'<[^>]+>', '', html))
            scroll.set_child(tv)
            box.append(scroll)

        def populate(results):
            # Guard against a later double-click having replaced this window.
            if self._dict_win is not win:
                return GLib.SOURCE_REMOVE
            _clear()
            if not results:
                _hint(f'No dictionary entry found for "{word}".\n\n'
                      'Bible dictionaries index proper nouns and theological terms — '
                      'try a word like "covenant," "Abraham," or "atonement."')
                return GLib.SOURCE_REMOVE
            if len(results) == 1:
                _mod_name, mod_desc, html = results[0]
                title_widget.set_subtitle(mod_desc)
                _add_text(html)
            else:
                stack = Gtk.Stack()
                stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
                sw = Gtk.StackSwitcher()
                sw.set_stack(stack)
                sw.set_halign(Gtk.Align.CENTER)
                sw.set_margin_top(8)
                sw.set_margin_bottom(4)
                for mn, md, html in sorted(results, key=lambda r: r[1].lower()):
                    page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                    _add_text(html, page_box)
                    stack.add_titled(page_box, mn, md)
                content.append(sw)
                content.append(stack)
            return GLib.SOURCE_REMOVE

        def show_no_dicts():
            if self._dict_win is not win:
                return GLib.SOURCE_REMOVE
            _clear()
            _hint('No dictionary modules installed.\n\n'
                  'Install Easton\'s Bible Dictionary or Smith\'s Bible Dictionary '
                  'from the Module Manager.')
            return GLib.SOURCE_REMOVE

        def fetch():
            dicts = sword_bridge.installed_dict_modules()
            if not dicts:
                GLib.idle_add(show_no_dicts)
                return
            results = []
            for mod_name, mod_desc in dicts:
                html = sword_bridge.lookup_dict_word(mod_name, word)
                if html:
                    results.append((mod_name, mod_desc, html))
            GLib.idle_add(populate, results)

        threading.Thread(target=fetch, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def show_lexicon(self, strong_num, text):
        """Called from window.py on Bible-text word click. Resets nav history."""
        self._lex_history.clear()
        self._lex_back_btn.set_sensitive(False)
        self._current_strong = strong_num
        self._show_lex_content(strong_num, text)
        self._load_word_study(strong_num)

    def _load_word_study(self, strong_num):
        child = self._ws_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._ws_list.remove(child)
            child = nxt
        self._ws_header.set_text('Searching…')
        module, book = self._module, self._book

        def fetch():
            results = []
            for ch in range(1, sword_bridge.chapter_count(book) + 1):
                for v_num, html in sword_bridge.load_chapter(module, book, ch):
                    if re.search(rf'strong:{re.escape(strong_num)}',
                                 str(html), re.IGNORECASE):
                        markup = _make_verse_markup(html, strong_num)
                        results.append((book, ch, v_num, markup))
            GLib.idle_add(self._populate_word_study, strong_num, results, book, module)

        threading.Thread(target=fetch, daemon=True).start()

    def _populate_word_study(self, strong_num, results, book, module):
        # Discard if the user has navigated away (module / book / strong's all must match)
        if (self._current_strong != strong_num
                or self._book != book
                or self._module != module):
            return GLib.SOURCE_REMOVE
        child = self._ws_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._ws_list.remove(child)
            child = nxt
        n = len(results)
        self._ws_header.set_text(
            f'{n} occurrence{"s" if n != 1 else ""} in {book}')
        for ref_book, ch, v_num, markup in results:
            row = Gtk.ListBoxRow()
            row._nav = (ref_book, ch, v_num)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            card.set_margin_start(8)
            card.set_margin_end(8)
            card.set_margin_top(6)
            card.set_margin_bottom(6)
            ref_lbl = Gtk.Label(label=f'{ch}:{v_num}', xalign=0)
            ref_lbl.add_css_class('dim-label')
            text_lbl = Gtk.Label(xalign=0, wrap=True)
            try:
                text_lbl.set_markup(markup)
            except Exception:
                text_lbl.set_text(re.sub(r'<[^>]+>', '', markup))
            card.append(ref_lbl)
            card.append(text_lbl)
            row.set_child(card)
            self._ws_list.append(row)
        return GLib.SOURCE_REMOVE

    def _on_ws_row_activated(self, _listbox, row):
        if hasattr(row, '_nav') and self._on_word_study_navigate:
            self._on_word_study_navigate(*row._nav)

    def _show_lex_content(self, strong_num, text):
        # Quick lexicon navigations (G3056 → G2316 → G3056) spawn fetches whose
        # callbacks land out of order; ignore any result that's not for the
        # currently-active Strong's number.
        if self._current_strong != strong_num:
            return GLib.SOURCE_REMOVE
        self._lex_title.set_text(f"Strong's {strong_num}")
        decoded = ''
        if self._current_morph:
            m = self._current_morph
            if 'robinson:' in m:
                decoded = sword_bridge.decode_robinson(m) or ''
            else:
                decoded = sword_bridge.decode_hebrew_morph(m) or ''
        self._morph_lbl.set_text(decoded)

        if not text:
            self._lex_buf.set_text("Definition not found.")
        else:
            dark = Adw.StyleManager.get_default().get_dark()
            markup = _html_to_markup(text, dark)
            self._lex_buf.set_text('')
            try:
                self._lex_buf.insert_markup(self._lex_buf.get_start_iter(), markup, -1)
            except Exception as e:
                plain = re.sub(r'<[^>]+>', '', markup)
                self._lex_buf.set_text(plain)
                print(f"[Lexicon] Markup error: {e}")
            self._tag_lex_refs()

        if not self._lex_box.get_visible():
            self._lex_box.set_visible(True)
            GLib.idle_add(self._init_lex_position)

    def _tag_lex_refs(self):
        """Tag cross-reference numbers in the lexicon text as clickable.

        SWORD Strong's entries don't use G/H prefixes in the rendered text.
        Handles variations like 'see HEBREW for 07554', 'from 3004', 'ref 123', etc.
        """
        start = self._lex_buf.get_start_iter()
        end = self._lex_buf.get_end_iter()
        text = self._lex_buf.get_text(start, end, False)
        lang = self._current_strong[0].upper() if self._current_strong else 'G'

        def apply_tag(m_start, m_end, prefix, raw_num):
            num = str(int(raw_num))  # strip leading zeros
            strong_num = f"{prefix}{num}"
            s = self._lex_buf.get_iter_at_offset(m_start)
            e = self._lex_buf.get_iter_at_offset(m_end)
            tag_name = f"strg:{strong_num}"
            tag = self._lex_buf.get_tag_table().lookup(tag_name)
            if not tag:
                tag = self._lex_buf.create_tag(tag_name, 
                    underline=Pango.Underline.SINGLE,
                    foreground='DodgerBlue'
                )
            self._lex_buf.apply_tag(tag, s, e)

        # 1. Targeted search for language-switching refs:
        # "see HEBREW for 07554" / "see GREEK for 3004"
        for m in re.finditer(r'see (?:also\s+)?(HEBREW|GREEK)\s+for\s+(\d+)', text, re.I):
            prefix = 'H' if m.group(1).upper() == 'HEBREW' else 'G'
            apply_tag(m.start(2), m.end(2), prefix, m.group(2))

        # 2. Sequential/Same-language refs:
        # "from 7554" / "compare 1234" / "and 5346" / "ref 111"
        for m in re.finditer(r'\b(?:from|compare|and|ref|see|also)\s+(\d+)\b', text, re.I):
            apply_tag(m.start(1), m.end(1), lang, m.group(1))

        # 3. Explicit G/H-prefixed refs (e.g. G3056, H1234)
        for m in re.finditer(r'\b([GH])(\d+)\b', text, re.I):
            apply_tag(m.start(), m.end(), m.group(1).upper(), m.group(2))

    def _navigate_to_strong(self, strong_num):
        """Navigate to a new Strong's entry from within the lexicon panel."""
        if self._current_strong:
            self._lex_history.append(self._current_strong)
            self._lex_back_btn.set_sensitive(True)
        self._current_strong = strong_num
        self._current_morph = None

        def fetch():
            text = sword_bridge.lookup_strong(strong_num)
            GLib.idle_add(self._show_lex_content, strong_num, text)
            GLib.idle_add(self._load_word_study, strong_num)
        threading.Thread(target=fetch, daemon=True).start()

    def _on_lex_back(self, _btn):
        if not self._lex_history:
            return
        prev = self._lex_history.pop()
        self._current_strong = prev
        self._current_morph = None
        self._lex_back_btn.set_sensitive(bool(self._lex_history))

        def fetch():
            text = sword_bridge.lookup_strong(prev)
            GLib.idle_add(self._show_lex_content, prev, text)
            GLib.idle_add(self._load_word_study, prev)
        threading.Thread(target=fetch, daemon=True).start()

    def _on_lex_click(self, gesture, n_press, x, y):
        bx, by = self._lex_inner.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._lex_inner.get_iter_at_location(bx, by)
        if not found:
            return
        for tag in it.get_tags():
            name = tag.get_property('name')
            if name and name.startswith('strg:'):
                self._navigate_to_strong(name[5:])
                return

    def _init_lex_position(self):
        h = self._lex_paned.get_allocated_height()
        self._lex_paned.set_position(h - 200 if h > 200 else 300)
        w = self._lex_h_paned.get_allocated_width()
        if w > 100:
            self._lex_h_paned.set_position(int(w * 0.67))
        return GLib.SOURCE_REMOVE

    def _hide_lexicon(self):
        self._lex_box.set_visible(False)

    def _verses_in_range(self, start, end):
        seen = set()
        verses = []
        it = start.copy()
        while it.compare(end) <= 0:
            for tag in it.get_tags():
                name = tag.get_property('name') or ''
                if name.startswith('vnum_'):
                    try:
                        v = int(name.split('_')[1])
                    except (ValueError, IndexError):
                        continue
                    if v not in seen:
                        seen.add(v)
                        verses.append(v)
            if not it.forward_to_tag_toggle(None):
                break
        return sorted(verses)

    def _on_right_click(self, gesture, n_press, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return

        if self._buffer.get_has_selection():
            start, end = self._buffer.get_selection_bounds()
            verses = self._verses_in_range(start, end)
        else:
            verses = []
            for tag in it.get_tags():
                name = tag.get_property('name') or ''
                if name.startswith('vnum_'):
                    try:
                        verses = [int(name.split('_')[1])]
                    except (ValueError, IndexError):
                        continue
                    break

        if not verses:
            return
        self._show_study_menu(verses, x, y)

    def _show_study_menu(self, verses, x, y):
        popover = Gtk.Popover()
        popover.set_parent(self._view)
        # GTK4 requires explicit unparent for set_parent popovers.
        popover.connect('closed', lambda p: p.unparent())
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        if len(verses) == 1:
            title = f'Verse {verses[0]}'
        else:
            title = f'Verses {verses[0]}–{verses[-1]}'
        lbl = Gtk.Label(label=title)
        lbl.add_css_class('dim-label')
        box.append(lbl)

        # 1. Highlighting
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        color_box.set_halign(Gtk.Align.CENTER)
        _ensure_hl_css()
        for color, css_cls in [('#ffff00', 'hl-yellow'), ('#90ee90', 'hl-green'),
                                ('#add8e6', 'hl-blue'),  ('#ffa500', 'hl-orange')]:
            btn = Gtk.Button()
            btn.set_size_request(28, 28)
            btn.add_css_class(css_cls)
            btn.connect('clicked', self._apply_highlight, verses, color, popover)
            color_box.append(btn)

        clear_btn = Gtk.Button(label='Clear Highlight')
        clear_btn.connect('clicked', self._apply_highlight, verses, None, popover)
        box.append(color_box)
        box.append(clear_btn)
        box.append(Gtk.Separator())

        # 2. Underline
        annos = annotations.get_annotations(self._module, self._book, self._chapter)
        all_underlined = all(
            (lambda a: a if isinstance(a, dict) else {'underline': False})(
                annos.get(str(v), {})).get('underline', False)
            for v in verses
        )
        und_lbl = 'Remove Underline' if all_underlined else 'Underline'
        und_btn = Gtk.Button(label=und_lbl)
        und_btn.connect('clicked', self._toggle_underline, verses, not all_underlined, popover)
        box.append(und_btn)

        # 3. Note & Tags (single verse only)
        if len(verses) == 1:
            anno = annos.get(str(verses[0]), {})
            if isinstance(anno, str):
                anno = {'highlight': anno, 'underline': False, 'note': None}
            note_text = anno.get('note', '')
            current_tags = anno.get('tags', [])
            has_study = bool(note_text or current_tags)
            note_btn = Gtk.Button(label='Edit Note & Tags' if has_study else 'Note & Tags')
            note_btn.connect('clicked', self._on_edit_note, verses[0], note_text, current_tags, popover)
            box.append(note_btn)

        box.append(Gtk.Separator())

        # 4. Copy verse(s)
        copy_lbl = 'Copy verses' if len(verses) > 1 else 'Copy verse'
        copy_btn = Gtk.Button(label=copy_lbl)
        copy_btn.add_css_class('flat')
        copy_btn.connect('clicked', self._copy_verse, verses, popover)
        box.append(copy_btn)

        # 5. Compare translations (single verse only)
        if len(verses) == 1:
            comp_btn = Gtk.Button(label='Compare translations')
            comp_btn.add_css_class('flat')
            comp_btn.connect('clicked', self._compare_translations, verses[0], popover)
            box.append(comp_btn)

        popover.set_child(box)
        popover.popup()

    def _copy_verse(self, _btn, verses, popover):
        popover.popdown()
        chapter_verses = sword_bridge.load_chapter(self._module, self._book, self._chapter)
        verse_map = {v: html for v, html in chapter_verses}
        lines = []
        for v in verses:
            plain = re.sub(r'<[^>]+>', '', str(verse_map.get(v, ''))).strip()
            lines.append(f'{self._book} {self._chapter}:{v}  {plain}')
        ref = (f'{self._book} {self._chapter}:{verses[0]}–{verses[-1]}'
               if len(verses) > 1 else f'{self._book} {self._chapter}:{verses[0]}')
        text = f'{ref} ({self._module})\n' + '\n'.join(lines)
        self._view.get_clipboard().set(text)
        if self._on_toast:
            self._on_toast(f'Copied {ref}')

    def _compare_translations(self, _btn, verse, popover):
        popover.popdown()

        comp = Gtk.Popover()
        comp.set_parent(self._view)
        comp.connect('closed', lambda p: p.unparent())
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = 160, 80, 1, 1
        comp.set_pointing_to(rect)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        title = Gtk.Label(
            label=f'{self._book} {self._chapter}:{verse} — Translations',
            xalign=0)
        title.add_css_class('heading')
        title.set_margin_start(12)
        title.set_margin_end(12)
        title.set_margin_top(8)
        title.set_margin_bottom(6)
        outer.append(title)
        outer.append(Gtk.Separator())

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_width(420)
        scroll.set_min_content_height(200)
        scroll.set_max_content_height(420)
        scroll.set_propagate_natural_height(True)

        # Local — not on self — so two compare popovers in flight don't clobber each other.
        comp_list = Gtk.ListBox()
        comp_list.set_selection_mode(Gtk.SelectionMode.NONE)
        comp_list.add_css_class('boxed-list')
        comp_list.set_margin_start(8)
        comp_list.set_margin_end(8)
        comp_list.set_margin_top(8)
        comp_list.set_margin_bottom(8)

        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_margin_top(12)
        spinner.set_margin_bottom(12)
        comp_list.append(spinner)

        scroll.set_child(comp_list)
        outer.append(scroll)
        comp.set_child(outer)
        comp.popup()

        book, chapter = self._book, self._chapter

        def fetch():
            names = [m for m in sword_bridge.module_names()
                     if sword_bridge.module_type(m) == 'Biblical Texts']
            names += ebible_bridge.module_names()
            results = []
            for mod in names:
                if ebible_bridge.is_ebible_module(mod):
                    vs = ebible_bridge.load_chapter(mod, book, chapter)
                else:
                    vs = sword_bridge.load_chapter(mod, book, chapter)
                v_html = next((h for vn, h in vs if vn == verse), '')
                plain = re.sub(r'<[^>]+>', '', str(v_html)).strip()
                if plain:
                    results.append((mod, plain))
            GLib.idle_add(populate, results)

        def populate(results):
            # Skip if the popover was dismissed before the fetch returned.
            if comp.get_parent() is None:
                return GLib.SOURCE_REMOVE
            child = comp_list.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                comp_list.remove(child)
                child = nxt
            for mod, text in results:
                row = Gtk.ListBoxRow()
                rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                rb.set_margin_start(12)
                rb.set_margin_end(12)
                rb.set_margin_top(8)
                rb.set_margin_bottom(8)
                ml = Gtk.Label(label=mod, xalign=0)
                ml.add_css_class('dim-label')
                tl = Gtk.Label(label=text, xalign=0, wrap=True)
                tl.set_max_width_chars(52)
                rb.append(ml)
                rb.append(tl)
                row.set_child(rb)
                comp_list.append(row)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=fetch, daemon=True).start()

    def _apply_highlight(self, btn, verses, color, popover):
        for v in verses:
            annotations.save_highlight(self._module, self._book, self._chapter, v, color)
        popover.popdown()
        for v in verses:
            self._refresh_verse_annotation(v)

    def _toggle_underline(self, btn, verses, enabled, popover):
        for v in verses:
            annotations.save_underline(self._module, self._book, self._chapter, v, enabled)
        popover.popdown()
        for v in verses:
            self._refresh_verse_annotation(v)

    def _on_edit_note(self, btn, verse, current_note, current_tags, parent_popover):
        parent_popover.popdown()
        # Defer to next idle so the parent popover's surface teardown finishes
        # before we open a new window. Note editor is an Adw.Window (not a
        # popover) to avoid popover-inside-popover lifecycle/Wayland issues
        # — same pattern as the dictionary lookup popup.
        GLib.idle_add(self._show_note_window, verse, current_note, current_tags)

    def _show_note_window(self, verse, current_note, current_tags):
        root = self._view.get_root()
        win = Adw.Window(transient_for=root, modal=True)
        win.set_title(f'{self._book} {self._chapter}:{verse}')
        win.set_default_size(420, 360)

        toolbar_view = Adw.ToolbarView()
        win.set_content(toolbar_view)
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        save_btn = Gtk.Button(label='Save')
        save_btn.add_css_class('suggested-action')
        header.pack_end(save_btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_margin_top(12)
        box.set_margin_bottom(14)
        toolbar_view.set_content(box)

        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scrolled.set_min_content_height(160)
        entry = Gtk.TextView()
        entry.set_editable(True)
        entry.set_cursor_visible(True)
        entry.set_wrap_mode(Gtk.WrapMode.WORD)
        entry.set_left_margin(8)
        entry.set_right_margin(8)
        entry.set_top_margin(6)
        entry.set_bottom_margin(6)
        note_buf = entry.get_buffer()
        note_buf.set_text(current_note or '')
        scrolled.set_child(entry)
        # Wrapping in a Gtk.Frame gives the input area the standard GNOME
        # "view" background (lighter than the surrounding window) plus a
        # subtle border, so the text box is visually distinct.
        frame = Gtk.Frame()
        frame.set_child(scrolled)
        box.append(frame)

        tags_lbl = Gtk.Label(label='Topics (comma-separated)', xalign=0)
        tags_lbl.add_css_class('dim-label')
        box.append(tags_lbl)

        tags_entry = Gtk.Entry()
        safe_tags = [str(t) for t in (current_tags or []) if t]
        tags_entry.set_text(', '.join(safe_tags))
        tags_entry.set_placeholder_text('e.g. Salvation, Prayer, Prophecy')
        box.append(tags_entry)

        try:
            suggested = self._build_suggested_topics(
                self._book, self._chapter, verse, tags_entry)
            box.append(suggested)
        except Exception as e:
            print(f'[note window] suggested topics failed: {e}')

        save_btn.connect('clicked', self._save_note_window,
                         verse, note_buf, tags_entry, win)

        # Esc closes the window
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect(
            'key-pressed',
            lambda _c, kv, _kc, _s: (win.close() or True) if kv == Gdk.KEY_Escape else False,
        )
        win.add_controller(key_ctrl)

        win.present()
        GLib.idle_add(entry.grab_focus)
        return GLib.SOURCE_REMOVE

    def _save_note_window(self, _btn, verse, note_buf, tags_entry, win):
        start, end = note_buf.get_bounds()
        annotations.save_note(self._module, self._book, self._chapter, verse,
                               note_buf.get_text(start, end, True))
        raw = tags_entry.get_text().strip()
        tags = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
        annotations.save_tags(self._module, self._book, self._chapter, verse, tags)
        win.close()
        self._refresh_verse_annotation(verse)

    def _build_suggested_topics(self, book, chapter, verse, tags_entry):
        """Chip row that fetches OpenBible topics for the verse and appends
        each one to tags_entry on click. Hidden if no topics for this verse
        or the topics file isn't downloaded."""
        import open_data
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wrapper.set_visible(False)

        hint = Gtk.Label(label='Suggested', xalign=0)
        hint.add_css_class('dim-label')
        hint.add_css_class('caption')
        wrapper.append(hint)

        chip_scroll = Gtk.ScrolledWindow()
        chip_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        chip_scroll.set_propagate_natural_height(True)
        chip_scroll.set_min_content_height(36)
        chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chip_scroll.set_child(chip_box)
        wrapper.append(chip_scroll)

        def append_topic(_btn, text):
            existing = [t.strip() for t in tags_entry.get_text().split(',') if t.strip()]
            if text not in existing:
                existing.append(text)
            tags_entry.set_text(', '.join(existing))

        def fetch():
            topics = open_data.get_topics(book, chapter, verse) if verse else []
            def apply():
                if not topics:
                    return False
                for topic in topics:
                    btn = Gtk.Button(label=topic)
                    btn.add_css_class('pill')
                    btn.connect('clicked', append_topic, topic)
                    chip_box.append(btn)
                wrapper.set_visible(True)
                return False
            GLib.idle_add(apply)

        threading.Thread(target=fetch, daemon=True).start()
        return wrapper

    def _on_chapter_note_clicked(self, _btn):
        data = annotations.get_chapter_note_data(self._module, self._book, self._chapter)
        note = data['note'] if data else ''
        tags = data['tags'] if data else []

        popover = Gtk.Popover()
        popover.set_parent(self._chapter_note_btn)
        popover.connect('closed', lambda p: p.unparent())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        title = Gtk.Label(
            label=f'{self._book} {self._chapter} — Chapter Note', xalign=0)
        title.add_css_class('heading')
        box.append(title)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(160)
        scrolled.set_min_content_width(320)
        tv = Gtk.TextView()
        tv.set_editable(True)
        tv.set_cursor_visible(True)
        tv.set_wrap_mode(Gtk.WrapMode.WORD)
        tv.set_left_margin(8)
        tv.set_right_margin(8)
        tv.set_top_margin(6)
        tv.set_bottom_margin(6)
        buf = tv.get_buffer()
        buf.set_text(note)
        scrolled.set_child(tv)
        box.append(scrolled)

        tags_lbl = Gtk.Label(label='Topics (comma-separated)', xalign=0)
        tags_lbl.add_css_class('dim-label')
        box.append(tags_lbl)

        tags_entry = Gtk.Entry()
        safe_tags = [str(t) for t in (tags or []) if t]
        tags_entry.set_text(', '.join(safe_tags))
        tags_entry.set_placeholder_text('e.g. Creation, Covenant')
        box.append(tags_entry)

        save_btn = Gtk.Button(label='Save')
        save_btn.add_css_class('suggested-action')
        save_btn.connect('clicked', self._save_chapter_note, buf, tags_entry, popover)
        box.append(save_btn)

        popover.set_child(box)
        popover.popup()
        GLib.idle_add(tv.grab_focus)

    def _save_chapter_note(self, _btn, buf, tags_entry, popover):
        start, end = buf.get_bounds()
        annotations.save_chapter_note(
            self._module, self._book, self._chapter,
            buf.get_text(start, end, True))
        raw = tags_entry.get_text().strip()
        tags = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
        annotations.save_chapter_note_tags(
            self._module, self._book, self._chapter, tags)
        popover.popdown()
        self._update_chapter_note_indicator()

    def _update_chapter_note_indicator(self):
        if annotations.get_chapter_note(self._module, self._book, self._chapter):
            self._chapter_note_btn.add_css_class('accent')
        else:
            self._chapter_note_btn.remove_css_class('accent')

    def _on_theme_changed(self, *_):
        # StyleManager is a global singleton; the notify::dark connection from
        # __init__ has no natural disconnect point. Bail if this pane has been
        # detached from its window — avoids touching a destroyed buffer.
        if self.get_root() is None:
            return
        self._update_font_css()
        self._fetch_and_render()

    def _on_pane_search_toggled(self, btn):
        if btn.get_active():
            self._pane_search_rev.set_reveal_child(True)
            self._pane_search_entry.grab_focus()
        else:
            self._pane_search_rev.set_reveal_child(False)
            self._pane_search_entry.set_text('')
            child = self._pane_search_list.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self._pane_search_list.remove(child)
                child = nxt
            self._pane_search_status.set_text('')

    def _on_pane_search(self, *_):
        query = self._pane_search_entry.get_text().strip()
        if not query:
            return
        module = self._module
        child = self._pane_search_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._pane_search_list.remove(child)
            child = nxt
        self._pane_search_status.set_text('Searching…')
        self._pane_search_spinner.set_visible(True)
        self._pane_search_spinner.start()

        def _idx_start():
            GLib.idle_add(self._pane_search_status.set_text, 'Building index…')

        def run():
            if ebible_bridge.is_ebible_module(module):
                results = ebible_bridge.search_module(module, query)
            else:
                results = sword_bridge.search_module(
                    module, query,
                    on_indexing_start=_idx_start,
                    on_indexing_done=lambda: None)
            GLib.idle_add(self._pane_search_done, results, module)

        threading.Thread(target=run, daemon=True).start()

    def _pane_search_done(self, results, module):
        self._pane_search_spinner.stop()
        self._pane_search_spinner.set_visible(False)
        if module != self._module:
            return GLib.SOURCE_REMOVE
        if results and results[-1][0] == '':
            self._pane_search_status.set_text(results[-1][3])
            results = results[:-1]
        else:
            n = len(results)
            self._pane_search_status.set_text(
                f'{n} verse{"s" if n != 1 else ""} found')
        for book, ch, v, text in results[:500]:
            row = Gtk.ListBoxRow()
            row._nav = (book, ch, v)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.set_margin_start(10)
            box.set_margin_end(10)
            box.set_margin_top(5)
            box.set_margin_bottom(5)
            ref = Gtk.Label(label=f'{book} {ch}:{v}', xalign=0)
            ref.add_css_class('caption')
            snippet = text[:120] + ('…' if len(text) > 120 else '')
            body = Gtk.Label(label=snippet, xalign=0, wrap=False)
            body.set_ellipsize(Pango.EllipsizeMode.END)
            body.add_css_class('dim-label')
            body.add_css_class('caption')
            box.append(ref)
            box.append(body)
            row.set_child(box)
            self._pane_search_list.append(row)
        return GLib.SOURCE_REMOVE

    def _on_pane_search_row(self, _listbox, row):
        if hasattr(row, '_nav') and self._on_word_study_navigate:
            self._on_word_study_navigate(*row._nav)

    def refresh_modules(self):
        new_names = sword_bridge.module_names() + ebible_bridge.module_names()
        self.module_drop.disconnect(self._module_handler)
        self._names = new_names
        self.module_drop.set_model(Gtk.StringList.new(self._names))
        if self._module in self._names:
            self.module_drop.set_selected(self._names.index(self._module))
        elif self._names:
            self._module = self._names[0]
            self.module_drop.set_selected(0)
            self._fetch_and_render()
        self._module_handler = self.module_drop.connect('notify::selected', self._on_module_changed)

    def _on_module_changed(self, drop, _param):
        self._module = self._names[drop.get_selected()]
        self._module_type = (
            'Biblical Texts' if ebible_bridge.is_ebible_module(self._module)
            else sword_bridge.module_type(self._module)
        )
        self._is_devotional = (
            not ebible_bridge.is_ebible_module(self._module)
            and sword_bridge.is_devotional_module(self._module)
        )
        is_devot = self._is_devotional
        self._date_nav_revealer.set_reveal_child(is_devot)
        self._sync_btn.set_visible(not is_devot)
        self._chapter_note_btn.set_visible(not is_devot)
        self._pane_search_btn.set_visible(not is_devot)
        self._pane_search_btn.set_active(False)
        if is_devot:
            self._devotional_date = _date.today()
            self._sync_btn.set_active(True)  # lock navigation silently
        elif self._sync_btn.get_active():
            # Switching FROM a devotional (or otherwise-locked) module TO a
            # Bible: auto-unlock so the pane follows window navigation again.
            # _on_sync_toggled's catch-up logic loads the window's current
            # book/chapter into this pane.
            self._sync_btn.set_active(False)
        # Clear stale per-module state — Strong's words, morph, selected verse, and
        # the lexicon panel are all keyed to the previous module's content.
        self._current_strong = None
        self._current_morph = None
        self._selected_verse = None
        self._lex_history.clear()
        self._lex_back_btn.set_sensitive(False)
        self._hide_lexicon()
        # Dismiss any dict popup since it's tied to a word in the previous module's text.
        prev_dict = getattr(self, '_dict_win', None)
        if prev_dict is not None:
            try:
                prev_dict.close()
            except Exception:
                pass
            self._dict_win = None
        self._fetch_and_render()

    def select_verse(self, verse_num):
        """Called by other panes broadcasting a verse selection."""
        self._selected_verse = verse_num
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if tag:
            self._scroll_to_verse(verse_num)

    def force_navigate(self, book, chapter, verse):
        """Navigate to a reference regardless of the sync setting."""
        self._book = book
        self._chapter = chapter
        self._target_verse = verse
        self._fetch_and_render()
