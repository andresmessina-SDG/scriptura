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
import catena_bridge
import content
import annotations
import settings
import module_positions
from genbook_reader import GenbookReader
from catena_reader import CatenaReader
from module_picker import ModulePicker


import devotional
import annotation_dialogs
from lexicon_panel import LexiconPanel
from pane_search import PaneSearch

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


_DICT_SHORT_NAMES = {
    # Hand-tuned for common SWORD dict modules where the heuristic below
    # would otherwise pick a less recognisable form.
    'Easton':       "Easton's",
    'Smith':        "Smith's",
    'ISBE':         'ISBE',
    'Naves':        "Nave's",
    'Torreys':      "Torrey's",
    'WebstersDict': "Webster's 1913",
}

_DICT_FLUFF_WORDS = {
    'dictionary', 'encyclopedia', 'revised', 'unabridged',
    'concise', 'of', 'the', 'english', 'language', 'bible',
    'topical', 'textbook', 'a', 'an',
}


def _short_dict_title(mod_name, mod_desc):
    """Compact label for the dict popup tabs. SWORD descriptions can run
    to ~60 chars (e.g. "Webster's 1913 Revised Unabridged Dictionary of
    the English Language"), which wraps the StackSwitcher awkwardly and
    pushes tabs off the popup edges. Prefer a known short name; fall back
    to first 1-2 distinctive words from the description plus any
    4-digit year."""
    if mod_name in _DICT_SHORT_NAMES:
        return _DICT_SHORT_NAMES[mod_name]
    words = []
    year = None
    for raw in mod_desc.split():
        clean = raw.rstrip(',.;:').strip()
        if not clean:
            continue
        if re.fullmatch(r'\d{4}', clean):
            year = clean
            continue
        if clean.lower() in _DICT_FLUFF_WORDS:
            break
        words.append(clean)
        if len(words) >= 2:
            break
    short = ' '.join(words) if words else mod_name
    return f'{short} {year}' if year else short


def _html_to_markup(html, dark, strip=True):
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
    # OSIS-style emphasis used by commentaries like Calvin's — `<hi
    # type="italic">` wraps Bible-verse citations within the body;
    # `<hi type="bold">` wraps the verse-number prefix ("1." etc.).
    # Without these the commentary loses all visual hierarchy.
    html = re.sub(r'<hi\s[^>]*type="italic"[^>]*>(.*?)</hi>', r'[[I_S]]\1[[I_E]]', html, flags=re.DOTALL)
    html = re.sub(r'<hi\s[^>]*type="bold"[^>]*>(.*?)</hi>', r'[[INLINE_B_S]]\1[[INLINE_B_E]]', html, flags=re.DOTALL)
    # Inline verse-number superscripts used by MHC: `<hi type="super">N</hi>`
    # marks the start of verse N within a section's continuous prose.
    html = re.sub(r'<hi\s[^>]*type="super"[^>]*>(.*?)</hi>', r'[[SUP_S]]\1[[SUP_E]]', html, flags=re.DOTALL)

    # Titles and Headings
    html = re.sub(r'<title>(.*?)</title>', r'[[B_S]]\1[[B_E]]', html)
    html = re.sub(r'<h3>(.*?)</h3>', r'[[B_S]]\1[[B_E]]', html)
    html = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'[[B_S]]\1[[B_E]]', html)

    # Paragraph + section markers used by Clarke and other long-form
    # commentaries: self-closing `<div sID="…" type="x-p"/>` brackets
    # mark paragraph start/end (with matching sID/eID). Translate them
    # to blank lines so multi-paragraph commentary entries render with
    # structure instead of as a single wall of text. The final
    # newline-collapse below dedups consecutive markers down to one
    # blank line per actual break.
    html = re.sub(r'<div\s[^>]*/>', '\n\n', html)

    # Raw-HTML structure used by long-form dictionaries (Webster's 1913
    # and similar). Bibles/commentaries don't typically emit these — OSIS
    # uses <hi> / <div sID/> instead — so adding them here gives much
    # better dict formatting without disturbing other render paths.
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p\s*>', '\n\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</li\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<b>(.*?)</b>', r'[[INLINE_B_S]]\1[[INLINE_B_E]]',
                  html, flags=re.DOTALL | re.IGNORECASE)

    # 2. Strip all other tags (like <w>, <p>, etc.) but keep content
    html = re.sub(r'<[^>]+>', '', html)
    
    # 3. Escape the raw text so characters like '&' and '<' don't break Pango
    html = GLib.markup_escape_text(html)
    
    # 4. Swap markers back for real Pango Markup
    html = html.replace('[[RED_S]]', f'<span foreground="{red}">').replace('[[RED_E]]', '</span>')
    html = html.replace('[[I_S]]', '<i>').replace('[[I_E]]', '</i>')
    html = html.replace('[[B_S]]', '\n\n<b>').replace('[[B_E]]', '</b>\n')
    # Inline bold — no surrounding newlines, used for in-paragraph
    # emphasis like commentary verse-number prefixes ("1.", "2."), not
    # block-level headings.
    html = html.replace('[[INLINE_B_S]]', '<b>').replace('[[INLINE_B_E]]', '</b>')
    # Superscript verse-number markers (MHC inline). Render small +
    # raised so they read as verse pointers without looking like a
    # separate "Verse N" header.
    html = html.replace('[[SUP_S]]',
                        '<span size="smaller" rise="4000" foreground="#888">')
    html = html.replace('[[SUP_E]]', '</span>')
    
    # Annotation styling (highlight, underline, note) is NOT baked into the
    # Pango markup anymore — it's applied via named tags after the verse
    # text is inserted so that right-click changes can be reflected in-place
    # without re-rendering the chapter (which would shift the scroll).

    # Clean up excess newlines — collapse runs of (whitespace + newline)
    # to a single blank line. SWORD often emits adjacent paragraph
    # markers separated by spaces (`<div eID/> <div sID/>`); naive
    # `\n{3,}` collapse misses those because the interleaved space
    # breaks the run of newlines.
    html = re.sub(r'(?:[ \t]*\n){3,}', '\n\n', html)

    # Commentary's segmented insertion passes strip=False so the space
    # before/after a <reference> segment is preserved — otherwise the
    # rendered text reads "Elijah,Rom 11:1-5" with no breathing room.
    return html.strip() if strip else html


def _extract_segments(html):
    """Parse SWORD HTML into [(text_html, strong_nums_list, morph_or_None)] in order.

    A `<w>` tag may carry multiple Strong's numbers (e.g. KJV wraps "the
    synagogue" as one tag with strong:G3588 strong:G4864, because the
    Greek source is two words `τῇ συναγωγῇ`). We return them all; the
    word-tagging step pairs them with the English words inside the
    segment by position.

    The regex accepts both regular `<w …>text</w>` tags and self-closing
    `<w …/>` tags. KJV emits the self-closing form for Greek source
    words that have no English equivalent in the translation (e.g. the
    untranslated negation particle in 'Hath God cast away'). Without
    matching it explicitly, the engine would consume the opening `<w …/>`
    as if it were a regular tag opener and then match `</w>` from the
    NEXT tag — swallowing that tag's English text under the wrong
    Strong's number."""
    html = str(html)
    segments = []
    pos = 0
    for m in re.finditer(r'<w\s([^>]*?)(?:/>|>(.*?)</w>)', html, re.DOTALL):
        if m.start() > pos:
            segments.append((html[pos:m.start()], [], None))
        content = m.group(2)
        if content is None:
            # Self-closing — Greek word with no English mapping; nothing
            # to tag in the rendered buffer.
            pos = m.end()
            continue
        attrs = m.group(1)
        strong_nums = [s.upper() for s in re.findall(r'strong:([GHgh]\d+)', attrs)]
        mm = re.search(r'morph="([^"]+)"', attrs)
        morph = mm.group(1) if mm else None
        segments.append((content, strong_nums, morph))
        pos = m.end()
    if pos < len(html):
        segments.append((html[pos:], [], None))
    return segments




class _ReadingScrolledWindow(Gtk.ScrolledWindow):
    """ScrolledWindow that centers a capped-width text column by pushing
    symmetric left/right margins onto its TextView child. Keeps the
    scrollbar at the widget's outer right edge (no Adw.Clamp wrapper)."""

    __gtype_name__ = 'BibleReaderReadingScrolledWindow'

    def __init__(self, view, base_margin=26, **kwargs):
        super().__init__(**kwargs)
        self._view = view
        self._base = base_margin
        self._reading_width = 720

    def set_reading_width(self, px):
        self._reading_width = max(200, int(px))
        w = self.get_width()
        if w > 0:
            self._apply_margins(w)

    def do_size_allocate(self, width, height, baseline):
        Gtk.ScrolledWindow.do_size_allocate(self, width, height, baseline)
        self._apply_margins(width)

    def _apply_margins(self, avail):
        if avail <= 0:
            return
        side = max(self._base, (avail - self._reading_width) // 2)
        if self._view.get_left_margin() != side:
            self._view.set_left_margin(side)
            self._view.set_right_margin(side)


def _printable_ratio(text):
    """Fraction of characters that are printable (Unicode-aware).

    Valid scripts — Greek, Hebrew, CJK — are all printable, so this stays
    near 1.0 for real content; a wrong SWORD cipher key decrypts to
    control/replacement bytes and drives the ratio well down.
    """
    if not text:
        return 1.0
    ok = sum(1 for c in text if c.isprintable() or c in '\n\t ')
    return ok / len(text)


def _is_bad_cipher(all_empty, chapter_in_index, ratio):
    """Decide whether a render is a wrong-cipher-key symptom.

    Compressed modules with a bad key fail to decompress and come back
    empty (so we trust the index: data present == bad key, not a coverage
    gap); uncompressed modules decrypt to gibberish (low printable ratio).
    """
    if all_empty:
        return chapter_in_index
    return ratio < 0.6


class BiblePane(Gtk.Box):
    def __init__(self, module_name=None, on_word_click=None,
                 on_click_outside_search=None, on_verse_select=None,
                 on_word_study_navigate=None, on_toast=None,
                 on_font_size_request=None, on_cipher_error=None,
                 on_modules_changed=None, pane_id=1):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_word_click = on_word_click
        self._on_click_outside_search = on_click_outside_search
        self._on_verse_select = on_verse_select
        self._on_word_study_navigate = on_word_study_navigate
        self._on_toast = on_toast
        self._on_font_size_request = on_font_size_request
        self._on_cipher_error = on_cipher_error
        self._on_modules_changed = on_modules_changed
        # Used to namespace per-pane persisted state (e.g. genbook
        # bookmarks) so pane1 and pane2 don't trample each other.
        self._pane_id = pane_id
        self._lexicon_enabled = False
        # Per-pane Ctrl+F search subsystem (widgets + state + highlight tag).
        # Constructed eagerly so the toolbar button and revealer can be
        # placed during _build_ui below.
        self._search = PaneSearch(self)

        self._names = content.readable_module_names()
        if not self._names:
            raise RuntimeError('No SWORD modules installed.')

        self._module = module_name if module_name in self._names else self._names[0]
        self._compute_module_flags()
        # Generic Books rendering, TOC, prev/next/TOC widgets, and entry-
        # path persistence live in GenbookReader. build_toolbar() below
        # attaches the three toolbar widgets; set_module() loads the
        # last-read entry path.
        self._genbook = GenbookReader(self, _html_to_markup)
        self._genbook.set_module(self._module, self._is_genbook)
        # Historical Commentaries (catena) card view — verse-synced from
        # the partnered Bible pane. Composed into the content stack below.
        self._catena = CatenaReader(self)
        self._book = 'Genesis'
        self._chapter = 1
        self._target_verse = None
        self._restore_top_verse = None
        self._selected_verse = None
        self._devotional_date = _date.today()
        # Mirrors of the window's current location, kept updated even when
        # this pane is sync-locked — used to catch up on unlock.
        self._window_book = 'Genesis'
        self._window_chapter = 1
        self._window_target_verse = None

        # Pane toolbar: module selector
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.add_css_class('pane-toolbar')
        self._toolbar = toolbar
        toolbar.set_margin_start(10)
        toolbar.set_margin_end(8)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)

        # Module picker — MenuButton + custom popover with search,
        # language-filter chips, and a per-module info view. Replaces the
        # plain Gtk.DropDown so users with many installed translations /
        # languages can narrow the list quickly.
        self._picker = ModulePicker(self)
        toolbar.append(self._picker.menu_button)

        toolbar.append(Gtk.Box(hexpand=True))

        self._sync_btn = Gtk.ToggleButton(icon_name='changes-allow-symbolic')
        self._sync_btn.add_css_class('flat')
        self._sync_btn.add_css_class('pane-action')
        self._sync_btn.set_tooltip_text('Following navigation')
        self._sync_btn.connect('notify::active', self._on_sync_toggled)
        toolbar.append(self._sync_btn)

        self._chapter_note_btn = Gtk.Button(icon_name='document-edit-symbolic')
        self._chapter_note_btn.add_css_class('flat')
        self._chapter_note_btn.add_css_class('pane-action')
        self._chapter_note_btn.set_tooltip_text('Chapter note')
        self._chapter_note_btn.connect(
            'clicked', lambda _b: annotation_dialogs.show_chapter_note(self))
        toolbar.append(self._chapter_note_btn)

        toolbar.append(self._search.build_button())

        self._copy_chapter_btn = Gtk.Button(icon_name='edit-copy-symbolic')
        self._copy_chapter_btn.add_css_class('flat')
        self._copy_chapter_btn.add_css_class('pane-action')
        self._copy_chapter_btn.set_tooltip_text('Copy chapter')
        self._copy_chapter_btn.connect('clicked', self._on_copy_chapter)
        toolbar.append(self._copy_chapter_btn)

        # Generic Books: prev / next sibling navigation + TOC popover.
        # Visible only when the pane's current module is type
        # "Generic Books". Verse-keyed chrome (lock/note/search/copy)
        # is hidden in this mode.
        self._genbook.build_toolbar(toolbar)

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
        self._toolbar_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._toolbar_separator.add_css_class('pane-toolbar-separator')
        self.append(self._toolbar_separator)

        # Per-pane inline search bar (revealed below toolbar). All
        # widgets + state live inside PaneSearch — see pane_search.py.
        self.append(self._search.build_revealer())

        # Ensure the pane itself can be shrunk by the user without UI elements pushing it
        self.set_size_request(150, -1)

        # Native TextView
        self._view = Gtk.TextView()
        self._view.set_editable(False)
        self._view.set_cursor_visible(False)
        self._view.set_wrap_mode(Gtk.WrapMode.WORD)
        # Match the surrounding pane's background — the default libadwaita
        # theme paints `textview text` with @view_bg_color (a card-like
        # surface) which doesn't match the @window_bg_color of the
        # outer pane. Without this the text column reads as a lighter
        # rectangle inside a darker frame in dark mode, and as white-on-
        # cream in light mode. The .bible-view class flips both the
        # widget and its inner text area to transparent so they pick up
        # the pane's background instead.
        self._view.add_css_class('bible-view')
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

        # Cap the reading column via dynamic left/right margins on the
        # TextView itself, not Adw.Clamp. TextView stays a direct Scrollable
        # child of ScrolledWindow (so scroll_to_iter() works for verse-flash
        # + cross-pane sync), and the vertical scrollbar sits at the pane's
        # outer edge rather than inside the column. _ReadingScrolledWindow
        # recomputes the margins on every size_allocate.
        # Pin the vertical scrollbar to always-visible so its gutter width
        # is reserved permanently. With AUTOMATIC policy the scrollbar can
        # flicker in/out when content height shifts (lexicon panel content
        # swap, cross-ref panel update, hover tag changes); under justified
        # wrapping that reflows the whole chapter, making a Strong's-word
        # click feel like it lands on a neighboring word.
        scrolled = _ReadingScrolledWindow(self._view, vexpand=True, hexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        scrolled.set_child(self._view)
        scrolled.set_reading_width(int(settings.get('reading_width') or 720))
        self._reading_scroll = scrolled

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
        # (chain, english_text) for the clicked word's source <w> tag.
        # Used by the lexicon header to display phrase context for
        # multi-Strong's / multi-word tags. Reset on every click and
        # on module change.
        self._current_phrase = (None, None)
        # Last verses passed to _display, reused for re-theming without IO.
        self._rendered_verses = None
        self._lex_panel = LexiconPanel(
            on_word_study_navigate=on_word_study_navigate,
            on_first_show=self._init_outer_paned_position,
        )

        # Content stack: the flowing reading view, or the catena card view
        # in Historical Commentaries mode. Both share the lexicon paned
        # below (the lexicon stays hidden in catena mode).
        self._content_stack = Gtk.Stack()
        self._content_stack.add_named(scrolled, 'text')
        self._content_stack.add_named(self._catena.widget, 'catena')
        self._content_stack.set_visible_child_name(
            'catena' if self._is_catena else 'text')

        # Vertical paned: Bible text on top, lexicon panel on bottom.
        self._lex_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL,
                                    vexpand=True, hexpand=True)
        self._lex_paned.set_start_child(self._content_stack)
        self._lex_paned.set_end_child(self._lex_panel)
        self._lex_paned.set_resize_start_child(True)
        self._lex_paned.set_resize_end_child(True)
        self._lex_paned.set_shrink_start_child(False)
        self._lex_paned.set_shrink_end_child(True)
        self.append(self._lex_paned)

        # Enrich Ctrl+C / native copy: prepend the verse reference so
        # selections paste with citation context. Falls through to default
        # copy when nothing's selected or selection isn't anchored to a verse.
        self._view.connect('copy-clipboard', self._on_copy_clipboard)

        # Context Menu for Study Tools
        gesture = Gtk.GestureClick.new()
        gesture.set_button(3) # Right click
        # Set phase to CAPTURE so we get it before the TextView's internal menu handler
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect('pressed', self._on_right_click)
        self._view.add_controller(gesture)

        # Strong's word lookup on left click. We defer the actual lookup
        # to the 'released' signal: if it fires on 'pressed' and the
        # lexicon entry is in cache, the panel content swap reflows the
        # chapter before the user releases the mouse, and GTK's TextView
        # interprets press-at-A + release-at-B (same screen coords, but
        # the text under those coords moved) as a drag-select.
        self._pending_strong_click = None
        gesture_left = Gtk.GestureClick.new()
        gesture_left.set_button(1)
        gesture_left.connect('pressed', self._on_left_click)
        gesture_left.connect('released', self._on_left_release)
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

        # Ctrl+scroll over the reading area adjusts font size. Universal
        # text-reader / browser convention. Pinch zoom (touchpad) goes
        # through the same code path via GestureZoom below.
        zoom_scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL)
        zoom_scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        zoom_scroll.connect('scroll', self._on_zoom_scroll)
        self._view.add_controller(zoom_scroll)

        zoom_gesture = Gtk.GestureZoom.new()
        # GestureZoom reports scale=1.0 at the start of each new pinch;
        # reset our delta accumulator so a fresh gesture doesn't trigger
        # spurious zoom-out from its first scale-changed signal.
        zoom_gesture.connect(
            'begin', lambda *_: setattr(self, '_zoom_gesture_accum', 1.0))
        zoom_gesture.connect('scale-changed', self._on_zoom_gesture)
        self._view.add_controller(zoom_gesture)
        self._zoom_gesture_accum = 1.0

        # Re-render when system theme switches dark/light
        Adw.StyleManager.get_default().connect('notify::dark', self._on_theme_changed)

        # Initial toolbar visibility based on what kind of module the
        # pane starts on. Without this, a session that ended on a
        # genbook or devotional re-opens with the verse-keyed chrome
        # (lock / chapter-note / search / copy) visible inappropriately.
        is_chapter_keyed = self._is_verse_navigable()
        # The catena pane follows the partnered Bible (book/chapter + verse),
        # so it keeps the sync button but none of the verse-text chrome.
        self._sync_btn.set_visible(is_chapter_keyed or self._is_catena)
        self._chapter_note_btn.set_visible(is_chapter_keyed)
        self._search.button.set_visible(is_chapter_keyed)
        self._copy_chapter_btn.set_visible(is_chapter_keyed)
        self._genbook.update_visibility(self._is_genbook)

        if self._is_devotional:
            self._date_nav_revealer.set_reveal_child(True)
            self._sync_btn.set_active(True)
            GLib.idle_add(self._fetch_and_render_devotional)
        elif self._is_genbook:
            GLib.idle_add(self._genbook.fetch_and_render)
        elif self._is_catena:
            GLib.idle_add(self._fetch_and_render)

    def _on_pane_click(self, gesture, n_press, x, y):
        """Called when a pane or lexicon text view is clicked."""
        if self._on_click_outside_search:
            self._on_click_outside_search()

    def _on_copy_clipboard(self, view):
        """Intercept Ctrl+C (and any other path that emits copy-clipboard)
        to prepend the verse reference, so selections paste as
        'Book Ch:V[-V2] (Module)\\n<selected text>'. Falls through to the
        default copy when nothing's selected or the selection isn't
        anchored to any verse (e.g., in commentary headers / chapter title)."""
        bounds = self._buffer.get_selection_bounds()
        if not bounds:
            return
        start, end = bounds
        verses = self._verses_in_range(start, end)
        if not verses:
            return
        text = self._buffer.get_text(start, end, False).strip()
        if not text:
            return
        first_v = min(verses)
        last_v = max(verses)
        ref = f'{self._book} {self._chapter}:{first_v}'
        if last_v > first_v:
            ref += f'-{last_v}'
        enriched = f'{ref} ({self._module})\n{text}'
        view.get_clipboard().set(enriched)
        view.stop_emission_by_name('copy-clipboard')

    def _compute_module_flags(self):
        """Derive the module-mode flags from self._module. Called from
        __init__ and on every module change, so the two paths can't drift.

        catena and devotional modules aren't verse-keyed; Generic Books are
        tree-keyed (TOC + entries). The render path and the toolbar chrome
        (sync / chapter note / search / copy / date-nav) branch on these."""
        m = self._module
        self._is_catena = catena_bridge.is_catena_module(m)
        is_ebible = ebible_bridge.is_ebible_module(m)
        if self._is_catena:
            self._module_type = 'Historical Commentaries'
        elif is_ebible:
            self._module_type = 'Biblical Texts'
        else:
            self._module_type = sword_bridge.module_type(m)
        self._is_devotional = (
            not self._is_catena and not is_ebible
            and sword_bridge.is_devotional_module(m))
        self._is_genbook = (
            not self._is_catena and not is_ebible
            and self._module_type == 'Generic Books')

    def _is_verse_navigable(self):
        """Verse-based navigation only makes sense for Bibles and commentaries.
        Lexicons, dictionaries, and generic books (e.g. Didache) don't have
        a book/chapter/verse key space — feeding them one would render
        unrelated content as though it matched the requested reference."""
        return (
            self._module_type in ('Biblical Texts', 'Commentaries')
            and not self._is_devotional
        )

    def load_reference(self, book, chapter):
        # Track the window's location even when sync is locked — so toggling
        # back to "Following" can catch up to where the rest of the app is.
        self._window_book = book
        self._window_chapter = chapter
        self._window_target_verse = None
        if self._sync_btn.get_active():
            return
        if self._is_catena:
            self._book = book
            self._chapter = chapter
            self._selected_verse = None  # no verse context yet → defaults to 1
            self._fetch_and_render()
            return
        if not self._is_verse_navigable():
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
        if self._is_catena:
            self._book = book
            self._chapter = chapter
            self._selected_verse = verse
            self._fetch_and_render()
            return
        if not self._is_verse_navigable():
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

    def set_reading_width(self, px):
        self._reading_scroll.set_reading_width(int(px))

    def _on_copy_chapter(self, _btn):
        """Copy this pane's current chapter to clipboard as plain text:
        'Book Chapter\\n\\nN verse text\\nN verse text…'."""
        if not self._is_verse_navigable():
            if self._on_toast:
                self._on_toast('Copy chapter works on Bibles and commentaries only')
            return
        book, chapter, module = self._book, self._chapter, self._module

        def fetch():
            try:
                if ebible_bridge.is_ebible_module(module):
                    verses = ebible_bridge.load_chapter(module, book, chapter)
                else:
                    verses = sword_bridge.load_chapter(module, book, chapter)
            except Exception as e:
                if self._on_toast:
                    GLib.idle_add(self._on_toast, f"Couldn't load chapter — {e}")
                return
            lines = [f'{book} {chapter}', '']
            for v_num, html in verses:
                plain = re.sub(r'<[^>]+>', '', str(html)).strip()
                if plain:
                    lines.append(f'{v_num} {plain}')
            text = '\n'.join(lines) + '\n'
            GLib.idle_add(self._finish_copy_chapter, text, book, chapter)

        threading.Thread(target=fetch, daemon=True).start()

    def _finish_copy_chapter(self, text, book, chapter):
        self._view.get_clipboard().set(text)
        if self._on_toast:
            self._on_toast(f'Copied {book} {chapter}')
        return GLib.SOURCE_REMOVE

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
        if self._lexicon_enabled == enabled:
            return
        self._lexicon_enabled = enabled
        # Toggling adds/removes Strong's word tags from the markup, which
        # requires a full re-render. Capture the verse currently at the top
        # of the viewport so we can restore the user's reading position
        # after the re-render instead of jumping back to the chapter start.
        self._restore_top_verse = self._find_topmost_visible_verse()
        self._fetch_and_render()

    def _find_topmost_visible_verse(self):
        if not self._view.get_realized():
            return None
        bx, by = self._view.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT,
            max(40, self._view.get_left_margin() + 20),
            4,
        )
        ok, it = self._view.get_iter_at_location(bx, by)
        if not ok:
            return None
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith('vnum_'):
                try:
                    return int(name.split('_', 1)[1])
                except (ValueError, IndexError):
                    continue
        return None

    def _resolve_present_verse(self, verse_num):
        """Map a requested verse to one actually rendered this chapter.
        If the exact verse is missing (e.g. an inner verse of a \\v 1-2
        bridge, or a stale cross-ref from a different versification), fall
        back to the nearest preceding verse so navigation lands on real
        text instead of nowhere."""
        present = getattr(self, '_present_verses', None)
        if not present or verse_num in present:
            return verse_num
        earlier = [v for v in present if v < verse_num]
        return max(earlier) if earlier else verse_num

    def _scroll_to_verse_silent(self, verse_num):
        verse_num = self._resolve_present_verse(verse_num)
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if not tag:
            return GLib.SOURCE_REMOVE
        it = self._buffer.get_start_iter()
        if not it.has_tag(tag):
            if not it.forward_to_tag_toggle(tag):
                return GLib.SOURCE_REMOVE
        mark = self._buffer.create_mark(None, it, True)
        self._view.scroll_to_mark(mark, 0.0, True, 0.0, 0.0)
        self._buffer.delete_mark(mark)
        return GLib.SOURCE_REMOVE

    # ── Per-pane search delegators (PaneSearch owns the real state) ──────

    @property
    def _pane_search_rev(self):
        """Window code (Ctrl+F / F3) reads this revealer's `get_reveal_child`
        to decide which surface owns the active search. Kept on the pane
        for compat; the real widget lives inside `self._search`."""
        return self._search.revealer

    @property
    def _pane_search_results(self):
        return self._search.results

    @property
    def _pending_search_highlight(self):
        return self._search.pending_highlight

    @_pending_search_highlight.setter
    def _pending_search_highlight(self, value):
        if value is None:
            self._search._pending_highlight = None
        else:
            q, case = value
            self._search.stash_pending_highlight(q, case)

    def step_pane_search_result(self, prev=False):
        return self._search.step(prev=prev)

    # Tags whose names start with these prefixes are chapter-scoped: a
    # fresh set is created on every render (vnum_N for verse anchors,
    # strg:GNNNN for Strong's words, morph:robinson:… for Greek
    # morphology, phrase:G1+G2 for multi-Strong's segments, devref:OSIS
    # for commentary references). Without explicit cleanup the tag table
    # grows unbounded across navigations — set_text('') removes content
    # but tags persist, and set_priority() then becomes O(N) in tag count.
    _CHAPTER_SCOPED_TAG_PREFIXES = ('vnum_', 'strg:', 'morph:', 'phrase:',
                                    'devref:')

    def _clear_chapter_scoped_tags(self):
        table = self._buffer.get_tag_table()
        to_remove = []

        def _collect(tag, _user_data):
            name = tag.get_property('name') or ''
            if name.startswith(self._CHAPTER_SCOPED_TAG_PREFIXES):
                to_remove.append(tag)

        table.foreach(_collect, None)
        for tag in to_remove:
            table.remove(tag)

    def _fetch_and_render(self):
        self._rendered_verses = None
        self._content_stack.set_visible_child_name(
            'catena' if self._is_catena else 'text')
        if self._is_catena:
            self._catena.render_for(
                self._book, self._chapter, self._selected_verse or 1)
            return
        if self._is_devotional:
            self._fetch_and_render_devotional()
            return
        if self._is_genbook:
            self._genbook.fetch_and_render()
            return
        if not self._is_verse_navigable():
            # Lexicons / dictionaries still fall through here — the
            # dict-popup surface owns those, the pane shows a placeholder.
            self._display_unsupported_module()
            return
        book, chapter, module = self._book, self._chapter, self._module

        def fetch():
            if ebible_bridge.is_ebible_module(module):
                verses = ebible_bridge.load_chapter(module, book, chapter)
            else:
                verses = sword_bridge.load_chapter(module, book, chapter)
            GLib.idle_add(self._display, verses, book, chapter, module)

        threading.Thread(target=fetch, daemon=True).start()

    def _display_unsupported_module(self):
        dark = Adw.StyleManager.get_default().get_dark()
        fg = '#8d8278' if dark else '#7a7066'
        self._cancel_all_flashes()
        self._search.cancel_hl_timer()
        self._buffer.set_text('')
        self._clear_chapter_scoped_tags()
        msg = (f'<span size="large" foreground="{fg}">'
               f'{GLib.markup_escape_text(self._module)}</span>\n\n'
               f'<span foreground="{fg}">'
               f'This module isn’t organized by book and chapter, '
               f'so it can’t be read in this pane yet. '
               f'Switch to a Bible or commentary in the module dropdown above.'
               f'</span>')
        self._buffer.insert_markup(self._buffer.get_end_iter(), msg, -1)
        self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)

    def _display_cipher_locked(self, dark):
        """Shown when an encrypted module's content decrypts to gibberish —
        the cipher key is wrong or missing. Pairs with the window's
        'Edit Key' toast."""
        fg = '#8d8278' if dark else '#7a7066'
        self._cancel_all_flashes()
        self._search.cancel_hl_timer()
        self._buffer.set_text('')
        self._clear_chapter_scoped_tags()
        msg = (f'<span size="large" foreground="{fg}">🔒 '
               f'{GLib.markup_escape_text(self._module)}</span>\n\n'
               f'<span foreground="{fg}">'
               f'This module’s content isn’t readable. The cipher key may '
               f'be incorrect — use “Edit Key” to enter it again.'
               f'</span>')
        self._buffer.insert_markup(self._buffer.get_end_iter(), msg, -1)
        self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)

    def _display_empty_chapter(self, book, chapter, dark):
        """Show a friendly hint when the current module has no content
        for the requested book/chapter — typically NT-only modules
        (SBLGNT, MorphGNT) navigated to an OT passage, or vice versa."""
        fg = '#8d8278' if dark else '#7a7066'
        msg = (f'<span size="large" foreground="{fg}">'
               f'{GLib.markup_escape_text(f"{book} {chapter}")}</span>\n\n'
               f'<span foreground="{fg}">'
               f'{GLib.markup_escape_text(self._module)} doesn’t include '
               f'this passage. Some modules cover only the Old or New '
               f'Testament — switch to a Bible with full coverage in the '
               f'module dropdown above.'
               f'</span>')
        self._buffer.insert_markup(self._buffer.get_end_iter(), msg, -1)
        self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)

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
        self._search.cancel_hl_timer()
        self._buffer.set_text('')
        self._clear_chapter_scoped_tags()
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

    def _save_position_to_module_state(self):
        """Snapshot the pane's current position into module_positions.
        Called before any transition that would otherwise drop the
        current scroll (module change, app close)."""
        if not self._module:
            return
        if self._is_genbook:
            self._genbook.save_position()
        elif self._is_verse_navigable():
            v = self._find_topmost_visible_verse()
            if v:
                module_positions.remember_verse_position(
                    self._module, self._book, self._chapter, v)

    def _display(self, verses, book, chapter, module):
        if book != self._book or chapter != self._chapter or module != self._module:
            return GLib.SOURCE_REMOVE
        self._rendered_verses = verses

        dark = Adw.StyleManager.get_default().get_dark()
        annos = annotations.get_annotations(module, book, chapter)
        is_commentary = self._module_type == 'Commentaries'

        self._cancel_all_flashes()
        self._search.cancel_hl_timer()
        self._buffer.set_text('')
        self._clear_chapter_scoped_tags()

        # Coverage check — every verse in `verses` may be empty if the
        # module doesn't include this book/chapter (e.g. SBLGNT is NT
        # only; navigating to Psalms returns the right verse_max but
        # all empty content). Show a friendly empty state instead of
        # rendering a chapter heading + bare verse numbers.
        all_empty = not any(
            re.sub(r'<[^>]+>', '', str(h)).strip() for _, h in verses)

        # Wrong/missing cipher key on an encrypted module. Two shapes:
        # uncompressed modules decrypt to gibberish; compressed modules
        # fail to decompress and come back empty. The index tells the
        # empty case apart from a real coverage gap. Gated to encrypted
        # modules so valid non-Latin scripts are never flagged.
        if (self._on_cipher_error
                and not ebible_bridge.is_ebible_module(module)
                and sword_bridge.is_encrypted_module(module)):
            sample = ' '.join(re.sub(r'<[^>]+>', '', str(h)) for _, h in verses)
            in_index = (sword_bridge.chapter_in_index(module, book, chapter)
                        if all_empty else False)
            if _is_bad_cipher(all_empty, in_index, _printable_ratio(sample)):
                self._display_cipher_locked(dark)
                self._on_cipher_error(module)
                return GLib.SOURCE_REMOVE

        if all_empty:
            self._display_empty_chapter(book, chapter, dark)
            return GLib.SOURCE_REMOVE

        # Verse numbers actually rendered this chapter, for nearest-preceding
        # nav fallback: a USFM verse bridge (\v 1-2) stores its text under the
        # start verse only, so a jump to an inner verse (2) should land on that
        # block rather than silently doing nothing.
        self._present_verses = sorted(v for v, _ in verses)

        # Chapter heading — muted, sits above the first verse and scrolls with text.
        # Bibles only; commentaries emit their own per-verse headers, and
        # generic books / dictionaries don't have a Book Chapter reference
        # space so a heading there would just mislabel whatever happened
        # to be loaded last.
        if self._module_type == 'Biblical Texts':
            heading_color = '#8d8278' if dark else '#7a7066'
            heading = (f'<span size="x-large" weight="bold" '
                       f'foreground="{heading_color}" letter_spacing="600">'
                       f'{GLib.markup_escape_text(f"{book} {chapter}")}</span>\n\n')
            self._buffer.insert_markup(self._buffer.get_end_iter(), heading, -1)

        # For commentaries, group consecutive verses whose source HTML
        # is identical — section-based modules (MHC, MHCC) return the
        # same multi-thousand-character block for every verse in a
        # section, so naive verse-by-verse rendering produces a wall
        # of duplicate text. We render each unique block once and tag
        # the whole verse range to it for click/navigation.
        if is_commentary:
            iterable = self._group_commentary_verses(verses)
        else:
            iterable = ((v, v, html) for v, html in verses)

        for start_v, end_v, html in iterable:
            plain = re.sub(r'<[^>]+>', '', str(html)).strip()

            # Commentary: skip verses with no meaningful content
            if is_commentary and len(plain) < 20:
                continue

            start_mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), True)

            # 1. Verse number — inline for Bibles, bold section header for commentaries
            if is_commentary:
                # Range label for grouped sections, single number otherwise
                range_label = (f'Verse {start_v}' if start_v == end_v
                               else f'Verses {start_v}-{end_v}')
                # Some modules (Clarke, MHCC) emit their own "Verse N"
                # or "Verses A-B" header inline via <hi type="bold">.
                # Skip our injected header in that case so the result
                # isn't doubled up.
                if not re.match(
                        r'^\s*<hi\s[^>]*type="bold"[^>]*>\s*Verses?\s+\d+(?:[-–]\d+)?\s*</hi>',
                        str(html)):
                    header = (f'\n<b>{range_label}</b>\n'
                              if self._buffer.get_char_count() > 0
                              else f'<b>{range_label}</b>\n')
                    self._buffer.insert_markup(self._buffer.get_end_iter(), header, -1)
                elif self._buffer.get_char_count() > 0:
                    # Source provides the header — but we still want a
                    # blank line of separation between commentary sections.
                    self._buffer.insert(self._buffer.get_end_iter(), '\n')
            else:
                v_num_markup = f'<span foreground="gray" size="small" weight="bold" rise="6000"> {start_v} </span>'
                self._buffer.insert_markup(self._buffer.get_end_iter(), v_num_markup, -1)

            text_start_mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), True)

            # 2. Verse text
            v_anno = annos.get(str(start_v), {})
            if is_commentary:
                # Commentaries use a segmented insertion so cross-refs
                # like <reference osisRef="Bible:Phil.3.4">…</reference>
                # become clickable styled links carrying a devref tag.
                # Plain segments between refs still go through
                # _html_to_markup so <hi>, <i>, etc. keep working.
                self._insert_commentary_body(html, dark)
                self._buffer.insert(self._buffer.get_end_iter(), '\n')
            else:
                v_text_markup = _html_to_markup(html, dark)
                # Drop-cap: enlarge the first letter of verse 1 for a
                # print-Bible feel. Skip the dropcap on highlighted v1 —
                # the soft tint reads better as a flat block.
                #
                # No `rise` attribute: combining `size="200%"` with a
                # negative `rise` made the verse-1 line's ink extent
                # exceed its reported logical extent, and GTK4 TextView's
                # incremental redraw on scroll left ghost fragments
                # above the cap when the user scrolled the chapter back
                # into view.
                if start_v == 1 and not v_anno.get('highlight'):
                    m = re.match(r'((?:<[^>]+>)*)([A-Za-z])', v_text_markup)
                    if m:
                        v_text_markup = (
                            f'{m.group(1)}<span size="200%" weight="bold">'
                            f'{m.group(2)}</span>{v_text_markup[m.end():]}'
                        )
                try:
                    self._buffer.insert_markup(self._buffer.get_end_iter(), v_text_markup + ' ', -1)
                except Exception:
                    self._buffer.insert(self._buffer.get_end_iter(), plain + ' ')

            # 3. Apply vnum tags. For grouped commentary sections, every
            # verse in [start_v, end_v] points at the same rendered
            # block so navigation to any of them lands on this section.
            start_iter = self._buffer.get_iter_at_mark(start_mark)
            end_iter = self._buffer.get_end_iter()
            for v in range(start_v, end_v + 1):
                tag_name = f'vnum_{v}'
                tag = self._buffer.get_tag_table().lookup(tag_name)
                if not tag:
                    tag = self._buffer.create_tag(tag_name)
                self._buffer.apply_tag(tag, start_iter, end_iter)

            # 4. Apply persistent annotation tags (highlight/underline/note
            # indicator) in-place — these can be changed later without a
            # full re-render via _refresh_verse_annotation. Bibles only;
            # commentaries don't get user annotations.
            if not is_commentary:
                self._apply_anno_tags(start_v, v_anno)

            # 5. Strong's word tagging (Bible mode only)
            if not is_commentary and self._lexicon_enabled and self._on_word_click:
                t_start = self._buffer.get_iter_at_mark(text_start_mark)
                self._tag_strong_words(t_start, self._buffer.get_end_iter(), html)

            self._buffer.delete_mark(start_mark)
            self._buffer.delete_mark(text_start_mark)

        if self._target_verse is not None:
            # Resolve to a rendered verse up front so the indicator and the
            # scroll agree when the target is an inner verse of a bridge.
            v = self._resolve_present_verse(self._target_verse)
            self._target_verse = None
            self._restore_top_verse = None
            # Navigation to a specific verse — mark it as the active
            # verse so the current-verse indicator sits on it after
            # the scroll lands.
            self._selected_verse = v
            self._set_current_verse_indicator(v)
            GLib.idle_add(self._scroll_to_verse, v)
        elif self._restore_top_verse is not None:
            v = self._restore_top_verse
            self._restore_top_verse = None
            GLib.idle_add(self._scroll_to_verse_silent, v)
        else:
            self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)
            # Fresh chapter render with no specific target — the
            # previous chapter's active verse is no longer applicable.
            self._selected_verse = None

        # If _selected_verse survived (e.g. user clicked verse 5 in this
        # chapter, then chapter re-rendered for an annotation save), the
        # indicator paint was wiped by set_text('') above — restore it.
        if self._selected_verse is not None:
            self._set_current_verse_indicator(self._selected_verse)

        self._update_chapter_note_indicator()
        self._search.apply_highlight()
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _group_commentary_verses(verses):
        """Yield (start_v, end_v, html) tuples coalescing consecutive
        verses that share identical commentary text. Section-based
        modules (MHC, MHCC) return the same multi-KB block for every
        verse in a section; deduping turns 36 repeats into 2–4 sections
        with range headers like 'Verses 1-10'."""
        groups = []
        for v, html in verses:
            s = str(html)
            if groups and s == groups[-1][2]:
                start, _, h = groups[-1]
                groups[-1] = (start, v, h)
            else:
                groups.append((v, v, s))
        return groups

    _REF_PATTERN = re.compile(
        r'<reference\s[^>]*osisRef="([^"]+)"[^>]*>(.*?)</reference>',
        re.DOTALL)

    def _insert_commentary_body(self, html, dark):
        """Render a commentary verse, breaking on <reference> tags so
        each cross-reference becomes a clickable styled link carrying
        a devref: tag. The plain segments between references go through
        _html_to_markup so existing emphasis (<hi>, <i>, <q>, etc.)
        keeps working."""
        s = str(html)
        pos = 0
        for m in self._REF_PATTERN.finditer(s):
            if m.start() > pos:
                # strip=False so a trailing space before the reference
                # ("Elijah, " + ref) isn't swallowed by .strip(), which
                # would render as "Elijah,Rom 11:1-5".
                markup = _html_to_markup(s[pos:m.start()], dark, strip=False)
                if markup:
                    try:
                        self._buffer.insert_markup(
                            self._buffer.get_end_iter(), markup, -1)
                    except Exception:
                        self._buffer.insert(
                            self._buffer.get_end_iter(),
                            re.sub(r'<[^>]+>', '', s[pos:m.start()]))
            osis = m.group(1)
            ref_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if ref_text:
                self._insert_ref_segment(ref_text, osis, dark)
            pos = m.end()
        if pos < len(s):
            markup = _html_to_markup(s[pos:], dark, strip=False)
            if markup:
                try:
                    self._buffer.insert_markup(
                        self._buffer.get_end_iter(), markup, -1)
                except Exception:
                    self._buffer.insert(
                        self._buffer.get_end_iter(),
                        re.sub(r'<[^>]+>', '', s[pos:]))

    def _insert_ref_segment(self, text, osis, dark):
        """Insert one cross-reference: styled text + devref: tag over
        the same range, so _on_left_click's existing devref handler
        routes the click to _on_word_study_navigate → _go_to."""
        color = '#7fa3c1' if dark else '#5a7fa3'
        start_mark = self._buffer.create_mark(
            None, self._buffer.get_end_iter(), True)
        markup = (f'<span foreground="{color}" underline="single">'
                  f'{GLib.markup_escape_text(text)}</span>')
        try:
            self._buffer.insert_markup(
                self._buffer.get_end_iter(), markup, -1)
        except Exception:
            self._buffer.insert(self._buffer.get_end_iter(), text)
        start = self._buffer.get_iter_at_mark(start_mark)
        end = self._buffer.get_end_iter()
        tag_name = f'devref:{osis}'
        tag = self._buffer.get_tag_table().lookup(tag_name)
        if not tag:
            tag = self._buffer.create_tag(tag_name)
        self._buffer.apply_tag(tag, start, end)
        self._buffer.delete_mark(start_mark)

    def _scroll_to_verse(self, verse_num):
        verse_num = self._resolve_present_verse(verse_num)
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

    # ── Current-verse indicator ──────────────────────────────────────────
    # A persistent subtle cue on the active verse (last clicked or
    # navigated-to). Applied to the verse-number range only — sits on
    # the left edge of the verse, visually distinct from the 1 s flash
    # (yellow text background) and the user's annotation highlight
    # (multi-color verse-text background). Bounded tag — lives across
    # chapter renders, cleared and re-applied on selection changes.

    _CURRENT_VERSE_TAG_NAME = '_current_verse'

    def _ensure_current_verse_tag(self):
        table = self._buffer.get_tag_table()
        tag = table.lookup(self._CURRENT_VERSE_TAG_NAME)
        if tag is not None:
            return tag
        dark = Adw.StyleManager.get_default().get_dark()
        # Foreground-only styling avoids the rectangle-looks-like-
        # selection problem. Purple accent — distinct from the blue
        # _note_marker and from highlight backgrounds (yellow/green/
        # blue/orange), so a current verse with a note still reads
        # clearly. No size change — keeps line height stable when
        # toggling between verses.
        fg = '#d4a8ff' if dark else '#7a4dbf'
        return self._buffer.create_tag(
            self._CURRENT_VERSE_TAG_NAME,
            foreground=fg,
            weight=Pango.Weight.BOLD)

    def _set_current_verse_indicator(self, verse_num):
        """Apply the active-verse indicator to verse_num (or clear if
        None). Idempotent: prior placements are removed first so only
        one verse ever shows the cue at a time."""
        table = self._buffer.get_tag_table()
        tag = table.lookup(self._CURRENT_VERSE_TAG_NAME)
        if tag is not None:
            self._buffer.remove_tag(
                tag,
                self._buffer.get_start_iter(),
                self._buffer.get_end_iter())
        if not verse_num:
            return
        # Bibles only. Commentary sections render their verse anchor as
        # an injected "Verse N" / "Verses A-B" header, not as " N "; the
        # indicator's offset math would paint the first few letters of
        # the word "Verse" in accent color. The header itself already
        # marks the active section visually.
        if self._module_type != 'Biblical Texts':
            return
        ranges = self._verse_ranges(verse_num)
        if not ranges:
            return
        vnum_start, vtext_start, _ = ranges
        tag = self._ensure_current_verse_tag()
        # Bump priority so anonymous insert_markup tags from subsequent
        # annotation applies don't out-rank us.
        tag.set_priority(table.get_size() - 1)
        self._buffer.apply_tag(tag, vnum_start, vtext_start)

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
        # Annotations are a Bible-only feature. Commentary panes tag whole
        # sections under vnum_*, so the verse-number offset math would paint
        # the section header (e.g. the first letters of "Verses 1-7"). The
        # render path guards its own call (is_commentary); guard here too so
        # the _refresh_verse_annotation path can't leak onto non-Bible panes.
        if self._module_type != 'Biblical Texts':
            return
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

        for word_html, strong_nums, morph in segments:
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

            if not strong_nums:
                search_pos = idx + len(word_plain)
                continue

            # Locate each English word inside the segment so we can apply
            # a separate Strong's tag per word. SWORD's KJV-style markup
            # uses one of three patterns:
            #   (a) one Strong's, one English word — simple
            #   (b) one Strong's, multiple English words — one Greek word
            #       translated as a phrase ("his own", "he went out");
            #       apply the same Strong's to every word
            #   (c) multiple Strong's, matching English words — one Greek
            #       word per English word in source order ("the synagogue"
            #       → G3588 G4864); pair by index
            # Before this split, (c) was applied as a single multi-word
            # range tagged with only the first Strong's, so clicking
            # "synagogue" returned G3588 ("the") — the user's bug report.
            word_offsets = [(wm.start(), wm.end() - wm.start())
                            for wm in re.finditer(r'\S+', word_plain)]
            if not word_offsets:
                search_pos = idx + len(word_plain)
                continue

            # When more Greek words collapse to fewer English words (e.g.
            # "τῶν χειρῶν" → "hands", tagged G3588 G5495), the Greek
            # definite article G3588 is grammatical filler — drop it so
            # the content word's Strong's reaches the English word
            # instead. Only do this when counts mismatch; matched-count
            # phrases like "the synagogue" (G3588 G4864 → "the synagogue")
            # legitimately pair article with article.
            effective_nums = strong_nums
            if len(strong_nums) > len(word_offsets):
                filtered = [s for s in strong_nums if s != 'G3588']
                if filtered:
                    effective_nums = filtered

            if len(effective_nums) == len(word_offsets):
                pairs = list(zip(effective_nums, word_offsets))
            elif len(effective_nums) == 1:
                pairs = [(effective_nums[0], wo) for wo in word_offsets]
            else:
                # Still mismatched (rare). Pair by index for as many as
                # we can; tag any remaining English words with the last
                # Strong's so clicking still triggers something sensible.
                pairs = list(zip(effective_nums, word_offsets))
                if len(word_offsets) > len(effective_nums):
                    last = effective_nums[-1]
                    pairs.extend((last, wo) for wo in word_offsets[len(effective_nums):])

            for strong_num, (local_off, local_len) in pairs:
                s = self._buffer.get_iter_at_offset(start_offset + idx + local_off)
                e = self._buffer.get_iter_at_offset(start_offset + idx + local_off + local_len)
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

            # Phrase tag — applied over the whole multi-word or multi-
            # Strong's segment so the click handler can surface phrase
            # context in the lexicon header. For idioms like "God forbid"
            # (G3361 + G1096) clicking "God" returns G3361 (per markup),
            # but the user benefits from seeing they clicked into a
            # phrase, not a literal one-to-one word lookup.
            if len(strong_nums) > 1 or len(word_offsets) > 1:
                phrase_tag_name = f'phrase:{"+".join(strong_nums)}'
                phrase_tag = self._buffer.get_tag_table().lookup(phrase_tag_name)
                if not phrase_tag:
                    phrase_tag = self._buffer.create_tag(phrase_tag_name)
                first_off, _ = word_offsets[0]
                last_off, last_len = word_offsets[-1]
                ps = self._buffer.get_iter_at_offset(start_offset + idx + first_off)
                pe = self._buffer.get_iter_at_offset(start_offset + idx + last_off + last_len)
                self._buffer.apply_tag(phrase_tag, ps, pe)

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

    def _on_zoom_scroll(self, controller, _dx, dy):
        """Ctrl+wheel = adjust font size. Without Ctrl, return False so
        the ScrolledWindow handles normal vertical scrolling unchanged."""
        if not self._on_font_size_request or dy == 0:
            return False
        event = controller.get_current_event()
        if event is None:
            return False
        if not (event.get_modifier_state() & Gdk.ModifierType.CONTROL_MASK):
            return False
        # Wheel up (dy < 0) = zoom in, wheel down (dy > 0) = zoom out —
        # matches browsers + every text reader.
        self._on_font_size_request(-0.5 if dy > 0 else 0.5)
        return True

    def _on_zoom_gesture(self, gesture, scale):
        """Touchpad pinch-to-zoom. The gesture reports cumulative scale
        from its 'begin' point — we convert deltas above a small threshold
        into discrete font-size steps so the gesture feels responsive
        without runaway zooming."""
        if not self._on_font_size_request:
            return
        ratio = scale / self._zoom_gesture_accum
        if ratio >= 1.15:
            self._on_font_size_request(0.5)
            self._zoom_gesture_accum = scale
        elif ratio <= 0.87:
            self._on_font_size_request(-0.5)
            self._zoom_gesture_accum = scale

    def _on_left_click(self, gesture, n_press, x, y):
        # Stash press position so _on_left_release can distinguish a true
        # click (collapse phantom selection) from a drag-select (preserve).
        self._click_press_pos = (x, y)
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return
        verse_num = None
        strong_num = None
        morph = None
        devref = None
        phrase_tag = None
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
            elif name and name.startswith('phrase:'):
                phrase_tag = tag
        if n_press > 1:
            return
        if devref:
            result = sword_bridge.parse_osis_ref(devref)
            if result and self._on_word_study_navigate:
                self._on_word_study_navigate(*result)
            return
        if verse_num is not None:
            self._selected_verse = verse_num
            self._set_current_verse_indicator(verse_num)
        if strong_num and self._on_word_click:
            # Resolve phrase context — the full English phrase text and
            # the full Strong's chain on the source <w> tag — so the
            # lexicon header can show that the click landed inside a
            # multi-word translation (idiomatic or otherwise).
            phrase_chain = None
            phrase_text = None
            if phrase_tag is not None:
                pname = phrase_tag.get_property('name') or ''
                if pname.startswith('phrase:'):
                    phrase_chain = pname[len('phrase:'):].split('+')
                    ps = it.copy()
                    pe = it.copy()
                    ps.backward_to_tag_toggle(phrase_tag)
                    pe.forward_to_tag_toggle(phrase_tag)
                    phrase_text = self._buffer.get_text(ps, pe, False).strip()
            # Stash for _on_left_release — see gesture setup comment.
            self._pending_strong_click = (strong_num, morph,
                                          phrase_chain, phrase_text)
        # Broadcast on every verse click, even when this pane's _selected_verse
        # already matches — it may match because the OTHER pane just broadcast
        # this same verse to us (select_verse writes _selected_verse on the
        # receiving pane). Suppressing the back-broadcast here meant pane2 → pane1
        # never re-highlighted after pane1 had previously broadcast to pane2.
        # No infinite-loop risk: select_verse() doesn't call _on_verse_select.
        if verse_num is not None and self._on_verse_select:
            self._on_verse_select(self, verse_num)

    def _on_left_release(self, gesture, n_press, x, y):
        pending = self._pending_strong_click
        self._pending_strong_click = None

        # Collapse phantom selection from a near-zero-movement click (the
        # legacy safety net for the lexicon-swap reflow case), but PRESERVE
        # selections that came from a genuine drag — otherwise drag-select
        # never sticks and Ctrl+C has nothing to copy.
        press_pos = getattr(self, '_click_press_pos', None)
        self._click_press_pos = None
        is_drag = False
        if press_pos is not None:
            is_drag = max(abs(x - press_pos[0]),
                          abs(y - press_pos[1])) > 4
        if not is_drag:
            bounds = self._buffer.get_selection_bounds()
            if bounds:
                self._buffer.place_cursor(bounds[0])

        if pending is None:
            return
        strong_num, morph, phrase_chain, phrase_text = pending
        self._current_morph = morph
        self._current_phrase = (phrase_chain, phrase_text)
        self._on_word_click(self, strong_num)

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
                sw.set_margin_start(18)
                sw.set_margin_end(18)
                for mn, md, html in sorted(results, key=lambda r: r[1].lower()):
                    page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                    _add_text(html, page_box)
                    stack.add_titled(page_box, mn, _short_dict_title(mn, md))
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

    def show_lexicon_loading(self, strong_num):
        """Reveal the lexicon panel with a spinner immediately when the
        user clicks a Strong's word. The actual content arrives later
        via show_lexicon(). Without this the panel is blank for several
        hundred ms on the first click of a session while SWORD warms up."""
        self._lex_panel.set_context(self._book, self._module)
        chain, text = getattr(self, '_current_phrase', (None, None))
        self._lex_panel.show_loading(strong_num,
                                     morph=self._current_morph,
                                     phrase_chain=chain,
                                     phrase_text=text)

    def show_lexicon(self, strong_num, text):
        """Called from window.py on Bible-text word click. The window has
        already fetched the definition text asynchronously; here we just
        forward it to the panel along with the morph we captured during
        the click (so the panel can decode and show it in the header)."""
        self._lex_panel.set_context(self._book, self._module)
        chain, ptext = getattr(self, '_current_phrase', (None, None))
        self._lex_panel.show(strong_num, text,
                             morph=self._current_morph,
                             phrase_chain=chain,
                             phrase_text=ptext)

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
        # The current-verse tag bakes its background color at creation
        # time. Drop it so the next render re-creates it against the
        # new theme.
        table = self._buffer.get_tag_table()
        cv = table.lookup(self._CURRENT_VERSE_TAG_NAME)
        if cv is not None:
            table.remove(cv)
        self._update_font_css()
        if self._is_verse_navigable() and self._rendered_verses is not None:
            self._display(self._rendered_verses,
                          self._book, self._chapter, self._module)
        else:
            self._fetch_and_render()

    def refresh_modules(self):
        # Invalidate the language cache — a module that was just installed
        # might not have been probed before; one that was uninstalled
        # shouldn't keep its entry around.
        self._picker.invalidate_lang_cache()
        new_names = content.readable_module_names()
        self._names = new_names
        if self._module not in self._names and self._names:
            # Module was uninstalled — fall back to the first available
            self._apply_module_change(self._names[0])
        else:
            # Same module is still around; just sync the label in case it
            # somehow drifted, and rebuild the picker contents on next open.
            self._picker.set_current_label(self._module)

    def _apply_module_change(self, new_module):
        """Carry out a module switch: rewire metadata, hide/show
        verse-navigation chrome, clear stale per-module state, re-render."""
        # Before changing modules, capture the OUTGOING module's
        # position into the shared module_positions store so the next
        # display of that module — even in the other pane — restores
        # to here.
        self._save_position_to_module_state()
        self._module = new_module
        self._picker.set_current_label(new_module)
        self._compute_module_flags()
        # Restore the new module's last-known position from the shared
        # module_positions store. Verse-keyed modules use _restore_top_verse
        # (consumed by _display); genbooks delegate to GenbookReader.
        self._genbook.set_module(new_module, self._is_genbook)
        if not self._is_genbook:
            v = module_positions.get_verse_position(
                new_module, self._book, self._chapter)
            if v:
                self._restore_top_verse = v
        is_devot = self._is_devotional
        is_chapter_keyed = self._is_verse_navigable()
        self._date_nav_revealer.set_reveal_child(is_devot)
        # Sync / chapter-note / per-pane search are only meaningful when
        # the pane is rendering a verse-keyed chapter. Devotionals get
        # date navigation instead; Generic Books get the TOC button.
        self._sync_btn.set_visible(is_chapter_keyed or self._is_catena)
        self._chapter_note_btn.set_visible(is_chapter_keyed)
        self._search.button.set_visible(is_chapter_keyed)
        self._copy_chapter_btn.set_visible(is_chapter_keyed)
        self._search.button.set_active(False)
        # TOC + prev/next buttons only visible for Generic Books
        self._genbook.update_visibility(self._is_genbook)
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
        self._current_phrase = (None, None)
        self._selected_verse = None
        self._lex_panel.clear_state()
        # Search results were keyed to the previous module — drop them
        # so F3 doesn't try to step through stale references.
        self._search.clear_state()
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
        if self._is_catena:
            self._selected_verse = verse_num
            self._catena.render_for(self._book, self._chapter, verse_num)
            return
        self._selected_verse = verse_num
        self._set_current_verse_indicator(verse_num)
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if tag:
            self._scroll_to_verse(verse_num)

    def force_navigate(self, book, chapter, verse):
        """Navigate to a reference regardless of the sync setting."""
        if not self._is_verse_navigable():
            return
        self._book = book
        self._chapter = chapter
        self._target_verse = verse
        self._fetch_and_render()
