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
import devotional
import annotation_dialogs
from lexicon_panel import LexiconPanel

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
        self._chapter_note_btn.connect(
            'clicked', lambda _b: annotation_dialogs.show_chapter_note(self))
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

        # Lexicon panel (hidden until a Strong's word is clicked).
        # Owns its own widgets, state, and navigation history; we just
        # compose it into the vertical Paned below the Bible text view.
        self._flash_timers = set()
        # _current_morph is a transient buffer: _on_left_click reads the
        # morph: tag at click time and stashes it here, so when window.py
        # later calls back via show_lexicon() we can pass it through to
        # LexiconPanel for the header decode. Cross-reference clicks
        # within the lex panel clear morph context on their own.
        self._current_morph = None
        self._lex_panel = LexiconPanel(
            on_word_study_navigate=on_word_study_navigate,
            on_first_show=self._init_outer_paned_position,
        )

        # Vertical paned: Bible text on top, lexicon panel on bottom.
        self._lex_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL,
                                    vexpand=True, hexpand=True)
        self._lex_paned.set_start_child(scrolled)
        self._lex_paned.set_end_child(self._lex_panel)
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
        self._lex_panel.def_view.add_controller(gesture_close_search_lex)

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
            devotional.render_osis(self._buffer, raw, dark)
        else:
            self._buffer.insert_markup(
                self._buffer.get_end_iter(),
                '<span foreground="gray">No entry found for this date.</span>', -1)
        self._view.get_vadjustment().set_value(0)
        return GLib.SOURCE_REMOVE

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

    # ── Lexicon panel delegators ─────────────────────────────────────────

    def show_lexicon(self, strong_num, text):
        """Called from window.py on Bible-text word click. The window has
        already fetched the definition text asynchronously; here we just
        forward it to the panel along with the morph we captured during
        the click (so the panel can decode and show it in the header)."""
        self._lex_panel.set_context(self._book, self._module)
        self._lex_panel.show(strong_num, text, morph=self._current_morph)

    def _hide_lexicon(self):
        self._lex_panel.hide()

    def _init_outer_paned_position(self):
        """Called by LexiconPanel via the on_first_show callback — sets
        the vertical Paned's divider so the lex panel gets ~200px tall
        on first reveal."""
        h = self._lex_paned.get_allocated_height()
        self._lex_paned.set_position(h - 200 if h > 200 else 300)
        return GLib.SOURCE_REMOVE

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
        annotation_dialogs.show_study_menu(self, verses, x, y)

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
        # Clear stale per-module state — morph buffer, selected verse, and
        # the lexicon panel are all keyed to the previous module's content.
        self._current_morph = None
        self._selected_verse = None
        self._lex_panel.clear_state()
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
