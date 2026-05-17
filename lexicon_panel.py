"""LexiconPanel — Strong's lexicon definition view + word study list.

Composed by BiblePane. The pane places it as the bottom half of a
vertical Gtk.Paned below the Bible text view, and shows it on word
click via show(). The panel is responsible for:

* Rendering the Strong's definition (with clickable cross-numbers in
  the definition body).
* Loading and displaying word-study results (every verse in the
  current book containing this Strong's number, with the matched
  word(s) bolded).
* History navigation back through previously-viewed Strong's entries
  reached by clicking cross-numbers in the definition body.

The panel keeps no reference to BiblePane — the navigation callback
(`on_word_study_navigate`) is supplied at construction time so the
panel can route word-study row clicks back to the window without
knowing about its composer.
"""

import re
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

import sword_bridge


def _make_verse_markup(html, target_strong):
    """Return Pango markup for a verse with words matching target_strong
    in bold. Imported from pane.py's helper; kept here to avoid a
    cross-module call for the word-study rendering."""
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


def _extract_segments(html):
    """[(text_html, strong_num, morph)] from SWORD <w> markup."""
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


def _html_to_markup(html, dark):
    """Pared-down version of pane._html_to_markup for the lexicon
    definition body. Lexicon entries have <i>/<b>/<sup>-style markup
    but never the SWORD red-letter or verse-highlight markers, so we
    don't need the placeholder-token dance."""
    html = str(html)
    # Strip lone surrogates (some SWORD dict modules emit them).
    if any('\ud800' <= c <= '\udfff' for c in html):
        html = ''.join(c for c in html if not ('\ud800' <= c <= '\udfff'))
    # Map italic/bold markers before tag-stripping.
    html = re.sub(r'<i[^>]*>(.*?)</i>', r'[[I_S]]\1[[I_E]]', html, flags=re.DOTALL)
    html = re.sub(r'<b[^>]*>(.*?)</b>', r'[[B_S]]\1[[B_E]]', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', '', html)
    html = GLib.markup_escape_text(html)
    html = html.replace('[[I_S]]', '<i>').replace('[[I_E]]', '</i>')
    html = html.replace('[[B_S]]', '<b>').replace('[[B_E]]', '</b>')
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


class LexiconPanel(Gtk.Box):
    """Vertical Box containing the lexicon header, definition view, and
    word-study list. Hidden by default; the composer calls show() to
    populate and reveal it.

    `on_word_study_navigate(book, chapter, verse)` is called when the
    user clicks a row in the word-study list. The composer typically
    routes this to window-level navigation."""

    def __init__(self, on_word_study_navigate=None, on_first_show=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_visible(False)
        self.set_size_request(-1, 80)
        self.add_css_class('lex-panel')

        self._on_word_study_navigate = on_word_study_navigate
        # Called the first time the panel becomes visible after being
        # hidden — lets the composer initialize the outer vertical Paned
        # position. Fires on the idle queue, after the panel has been laid
        # out so allocation queries are meaningful.
        self._on_first_show = on_first_show

        # Navigation state — back button walks this stack.
        self._history = []
        self._current_strong = None
        self._current_morph = None

        # Context — the pane's current book/module. Word study uses this
        # to scope its scan. set_context() updates it.
        self._book = None
        self._module = None

        # ── Header row ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class('lex-header')
        header.set_margin_start(12)
        header.set_margin_end(8)
        header.set_margin_top(6)
        header.set_margin_bottom(6)

        self._back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        self._back_btn.add_css_class('flat')
        self._back_btn.set_sensitive(False)
        self._back_btn.set_tooltip_text('Back')
        self._back_btn.connect('clicked', self._on_back)
        header.append(self._back_btn)

        self._title = Gtk.Label(label="Strong's Lexicon", xalign=0)
        self._title.add_css_class('heading')
        header.append(self._title)

        self._morph_lbl = Gtk.Label(label='', xalign=0, hexpand=True)
        self._morph_lbl.add_css_class('dim-label')
        self._morph_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        header.append(self._morph_lbl)

        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.connect('clicked', lambda _: self.hide())
        header.append(close_btn)

        # ── Definition view (left side of horizontal paned) ──
        # `def_view` is exposed as a public attribute so the composer can
        # attach extra gestures (e.g. "close search panel on click").
        def_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._def_view = self.def_view = Gtk.TextView()
        self._def_view.set_editable(False)
        self._def_view.set_cursor_visible(False)
        self._def_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._def_view.set_left_margin(16)
        self._def_view.set_right_margin(16)
        self._def_view.set_top_margin(8)
        self._def_view.set_bottom_margin(8)
        self._def_buf = self._def_view.get_buffer()
        def_scroll.set_child(self._def_view)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(1)
        gesture.connect('pressed', self._on_def_click)
        self._def_view.add_controller(gesture)

        # ── Word study (right side) ──
        ws_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ws_box.add_css_class('ws-panel')

        self._ws_header = Gtk.Label(label='', xalign=0, hexpand=True)
        self._ws_header.add_css_class('ws-header')
        ws_box.append(self._ws_header)

        self._ws_list = Gtk.ListBox()
        self._ws_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._ws_list.connect('row-activated', self._on_ws_row_activated)

        ws_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        ws_scroll.set_child(self._ws_list)
        ws_box.append(ws_scroll)

        # ── Horizontal paned: definition left, word study right ──
        self._h_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                                  hexpand=True, vexpand=True)
        self._h_paned.set_start_child(def_scroll)
        self._h_paned.set_end_child(ws_box)
        self._h_paned.set_resize_start_child(True)
        self._h_paned.set_resize_end_child(True)
        self._h_paned.set_shrink_start_child(False)
        self._h_paned.set_shrink_end_child(False)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.append(header)
        self.append(self._h_paned)

    # ── Public API ───────────────────────────────────────────────────────

    def set_context(self, book, module):
        """Update the book/module used to scope word-study scans.
        Called by BiblePane whenever its location changes."""
        self._book = book
        self._module = module

    def show(self, strong_num, text, morph=''):
        """Populate the panel for a Strong's number and reveal it.
        Resets the back history (this is a fresh entry from a
        Bible-text word click, not a navigation within the panel)."""
        self._history.clear()
        self._back_btn.set_sensitive(False)
        self._current_strong = strong_num
        self._current_morph = morph
        self._show_content(strong_num, text)
        self._load_word_study(strong_num)

    def hide(self):
        self.set_visible(False)

    def init_inner_position(self):
        """Set the horizontal paned's divider — 67% to the definition,
        33% to the word study. Called by the composer once the panel
        has been laid out (allocated_width is meaningful)."""
        w = self._h_paned.get_allocated_width()
        if w > 100:
            self._h_paned.set_position(int(w * 0.67))

    def clear_state(self):
        """Reset transient state when the module changes — called by
        BiblePane._on_module_changed."""
        self._history.clear()
        self._back_btn.set_sensitive(False)
        self._current_strong = None
        self._current_morph = None
        self.hide()

    # ── Definition rendering ─────────────────────────────────────────────

    def _show_content(self, strong_num, text):
        # Ignore late callbacks from a previous navigation.
        if self._current_strong != strong_num:
            return GLib.SOURCE_REMOVE
        self._title.set_text(f"Strong's {strong_num}")
        decoded = ''
        if self._current_morph:
            m = self._current_morph
            if 'robinson:' in m:
                decoded = sword_bridge.decode_robinson(m) or ''
            else:
                decoded = sword_bridge.decode_hebrew_morph(m) or ''
        self._morph_lbl.set_text(decoded)

        if not text:
            self._def_buf.set_text('Definition not found.')
        else:
            dark = Adw.StyleManager.get_default().get_dark()
            markup = _html_to_markup(text, dark)
            self._def_buf.set_text('')
            try:
                self._def_buf.insert_markup(self._def_buf.get_start_iter(), markup, -1)
            except Exception as e:
                plain = re.sub(r'<[^>]+>', '', markup)
                self._def_buf.set_text(plain)
                print(f'[Lexicon] Markup error: {e}')
            self._tag_refs()

        if not self.get_visible():
            self.set_visible(True)
            if self._on_first_show:
                GLib.idle_add(self._on_first_show)
            GLib.idle_add(self.init_inner_position)

    def _tag_refs(self):
        """Find and tag cross-reference numbers in the definition body so
        clicks navigate within the lexicon. Handles SWORD's various
        formats: 'see HEBREW for 07554', 'from 3004', 'ref 123', plain
        'G3056' / 'H1234'."""
        start = self._def_buf.get_start_iter()
        end = self._def_buf.get_end_iter()
        text = self._def_buf.get_text(start, end, False)
        lang = self._current_strong[0].upper() if self._current_strong else 'G'

        def apply_tag(m_start, m_end, prefix, raw_num):
            num = str(int(raw_num))  # strip leading zeros
            strong = f"{prefix}{num}"
            s = self._def_buf.get_iter_at_offset(m_start)
            e = self._def_buf.get_iter_at_offset(m_end)
            tag_name = f"strg:{strong}"
            tag = self._def_buf.get_tag_table().lookup(tag_name)
            if not tag:
                tag = self._def_buf.create_tag(
                    tag_name,
                    underline=Pango.Underline.SINGLE,
                    foreground='DodgerBlue',
                )
            self._def_buf.apply_tag(tag, s, e)

        # 1. Language-switch refs: "see HEBREW for 07554"
        for m in re.finditer(r'see (?:also\s+)?(HEBREW|GREEK)\s+for\s+(\d+)', text, re.I):
            prefix = 'H' if m.group(1).upper() == 'HEBREW' else 'G'
            apply_tag(m.start(2), m.end(2), prefix, m.group(2))
        # 2. Same-language refs: "from 7554", "compare 1234", etc.
        for m in re.finditer(r'\b(?:from|compare|and|ref|see|also)\s+(\d+)\b', text, re.I):
            apply_tag(m.start(1), m.end(1), lang, m.group(1))
        # 3. Explicit G/H-prefixed refs
        for m in re.finditer(r'\b([GH])(\d+)\b', text, re.I):
            apply_tag(m.start(), m.end(), m.group(1).upper(), m.group(2))

    # ── Word study list ──────────────────────────────────────────────────

    def _load_word_study(self, strong_num):
        # Clear the list immediately so the user sees the new search start.
        child = self._ws_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._ws_list.remove(child)
            child = nxt
        self._ws_header.set_text('Searching…')

        # Capture the search context so a late callback after navigation
        # can be discarded.
        book, module = self._book, self._module
        if not book or not module:
            return

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
        # Discard stale results — the user may have navigated away.
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

    # ── In-panel navigation (clicking a cross-reference) ────────────────

    def _navigate_to(self, strong_num):
        if self._current_strong:
            self._history.append(self._current_strong)
            self._back_btn.set_sensitive(True)
        self._current_strong = strong_num
        self._current_morph = None

        def fetch():
            text = sword_bridge.lookup_strong(strong_num)
            GLib.idle_add(self._show_content, strong_num, text)
            GLib.idle_add(self._load_word_study, strong_num)
        threading.Thread(target=fetch, daemon=True).start()

    def _on_back(self, _btn):
        if not self._history:
            return
        prev = self._history.pop()
        self._current_strong = prev
        self._current_morph = None
        self._back_btn.set_sensitive(bool(self._history))

        def fetch():
            text = sword_bridge.lookup_strong(prev)
            GLib.idle_add(self._show_content, prev, text)
            GLib.idle_add(self._load_word_study, prev)
        threading.Thread(target=fetch, daemon=True).start()

    def _on_def_click(self, gesture, n_press, x, y):
        bx, by = self._def_view.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._def_view.get_iter_at_location(bx, by)
        if not found:
            return
        for tag in it.get_tags():
            name = tag.get_property('name')
            if name and name.startswith('strg:'):
                self._navigate_to(name[5:])
                return
