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

import logging
import re
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Pango
from a11y import set_accessible_label
from gtk_utils import clear_children, fade_in, DelayedSpinner

import sword_bridge
import tasks

_log = logging.getLogger('scriptura.lexicon')

# Cap the word-study rows actually built: GTK ListBox rows aren't
# virtualized, and a common word (G3588 'the') matches nearly every verse
# of a book — thousands of rows stall the main loop for seconds. The
# header still reports the full count; a tail note names the cut.
_WS_ROW_CAP = 200


def _norm_strong(strong):
    """G0746 → G746. Module markup zero-pads to four digits while
    interlinear clicks pass the plain form; every comparison between the
    two worlds must go through this."""
    return re.sub(r'^([GH])0+(?=\d)', r'\1', strong.upper())


def _scan_pattern(strong_num):
    """Compiled regex matching strong_num in SWORD <w> markup regardless
    of zero-padding. Negative-lookahead so G65 doesn't also match G650,
    G651, G652, etc. — see lookup-side comments."""
    m = re.match(r'^([GH])0*(\d+)$', strong_num, re.IGNORECASE)
    if m:
        return re.compile(rf'strong:{m.group(1)}0*{m.group(2)}(?!\d)',
                          re.IGNORECASE)
    return re.compile(rf'strong:{re.escape(strong_num)}(?!\d)',
                      re.IGNORECASE)


def _make_verse_markup(html, target_strong):
    """Return Pango markup for a verse with words matching target_strong
    in bold. Imported from pane.py's helper; kept here to avoid a
    cross-module call for the word-study rendering."""
    segments = _extract_segments(str(html))
    if not any(s for _, s, _m in segments):
        plain = re.sub(r'<[^>]+>', '', str(html))
        return GLib.markup_escape_text(plain).strip()
    target = _norm_strong(target_strong)
    parts = []
    for seg_html, seg_strong_nums, _morph in segments:
        plain = GLib.markup_escape_text(re.sub(r'<[^>]+>', '', seg_html))
        if seg_strong_nums and target in map(_norm_strong, seg_strong_nums):
            parts.append(f'<b>{plain}</b>')
        else:
            parts.append(plain)
    return ''.join(parts).strip()


def _extract_segments(html):
    """[(text_html, strong_nums_list, morph)] from SWORD <w> markup.

    Returns a list of Strong's numbers per `<w>` tag — SWORD markup can
    fuse multiple source-language words under one tag (e.g. KJV wraps
    'the synagogue' with strong:G3588 strong:G4864). Also handles
    self-closing `<w …/>` tags emitted for untranslated source words;
    without explicit handling, the regex would consume them as openers
    and steal text from the next tag (see pane._extract_segments for
    the full explanation)."""
    html = str(html)
    segments = []
    pos = 0
    for m in re.finditer(r'<w\s([^>]*?)(?:/>|>(.*?)</w>)', html, re.DOTALL):
        if m.start() > pos:
            segments.append((html[pos:m.start()], [], None))
        content = m.group(2)
        if content is None:
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


def _preview_bible_module():
    """A text Bible to preview cited verses from: the Lexham English
    Bible when installed (a tight, scholarly rendering — the right
    register next to a lexicon entry), else one a pane is already
    reading, else the first available (mirrors the window's
    _first_bible_module — the panel keeps no window reference)."""
    import content
    import settings
    names = content.readable_module_names()
    for cand in ('LEB', settings.get('pane1_module'),
                 settings.get('pane2_module')):
        if cand in names and content.is_text_bible(cand):
            return cand
    for name in names:
        if content.is_text_bible(name):
            return name
    return None


class LexiconPanel(Gtk.Box):
    """Vertical Box containing the lexicon header, definition view, and
    word-study list. Hidden by default; the composer calls show() to
    populate and reveal it.

    `on_word_study_navigate(book, chapter, verse)` is called when the
    user clicks a row in the word-study list. The composer typically
    routes this to window-level navigation."""

    def __init__(self, on_word_study_navigate=None, on_first_show=None,
                 on_show_peek=None, on_dismiss_peek=None,
                 on_open_verse=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_visible(False)
        self.set_size_request(-1, 80)
        self.add_css_class('lex-panel')

        self._on_word_study_navigate = on_word_study_navigate
        # Verse-peek plumbing: the composing pane lends us its shared
        # self-healing peek popover (show_anchored_peek) and a dismisser
        # scoped to peeks anchored on our def view. A popover of our own
        # dies to the post-click relayout churn the pane's machinery was
        # built to survive.
        self._on_show_peek = on_show_peek
        self._on_dismiss_peek = on_dismiss_peek
        # Verse-peek 'open in Bible pane' button: routed to the window
        # (which owns pane visibility), signature (book, ch, v, module).
        self._on_open_verse = on_open_verse
        # Cancelled by every def-view click and re-render; an in-flight
        # verse fetch only shows its peek while it is still the current
        # submission on this key.
        self._verse_peek_key = f'versepeek:{id(self)}'
        # Hiding the panel (close button, content-kind switch) takes the
        # def view — the peek's anchor — off screen: dismiss an open peek
        # (deliberately, so the pane's self-heal doesn't fight it) and
        # supersede an in-flight fetch so it can't pop up over nothing.
        self.connect('unmap', self._on_panel_unmap)
        # Called the first time the panel becomes visible after being
        # hidden — lets the composer initialize the outer vertical Paned
        # position. Fires on the idle queue, after the panel has been laid
        # out so allocation queries are meaningful.
        self._on_first_show = on_first_show

        # Navigation state — back button walks this stack.
        self._history = []
        self._current_strong = None
        self._current_morph = None
        # Phrase context for the currently-shown Strong's: a tuple of
        # (chain_list, english_text). Set on show()/show_loading() from
        # a Bible-text word click; cleared on within-lexicon navigation
        # since those clicks aren't anchored to a specific phrase.
        self._current_phrase = (None, None)

        # Context — the pane's current book/module. Word study uses this
        # to scope its scan. set_context() updates it.
        self._book = None
        self._module = None
        self._ws_rows = 0        # rows built so far (capped at _WS_ROW_CAP)

        # ── Header row ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        # Tint + inset live in CSS (.lex-header) as padding, not widget margins,
        # so the header surface is full-bleed and joins the occurrences header.
        header.add_css_class('lex-header')

        self._back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        self._back_btn.add_css_class('flat')
        self._back_btn.set_sensitive(False)
        self._back_btn.set_tooltip_text(_('Back to previous definition'))
        set_accessible_label(self._back_btn, _('Back to previous definition'))
        self._back_btn.connect('clicked', self._on_back)
        header.append(self._back_btn)

        # Title + morphology share a horizontal scroller: in a narrow pane
        # the full Strong's heading and morphology stay reachable by
        # scrolling instead of vanishing into an ellipsis. The scroller
        # also serves the purpose the old max-width-chars + ellipsize caps
        # had — a ScrolledWindow doesn't propagate its child's natural
        # width, so a long title (e.g. `Strong's H3068 · in "the LORD"`)
        # can't combine with _ws_header below through the inner h_paned
        # (shrink=False on both children) to push the lexicon — and
        # therefore pane 1 — wider than its allocation when content loads.
        self._title = Gtk.Label(label=_("Strong's Lexicon"), xalign=0)
        self._title.add_css_class('heading')

        self._morph_lbl = Gtk.Label(label='', xalign=0, hexpand=True)
        self._morph_lbl.add_css_class('dim-label')

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_box.append(self._title)
        title_box.append(self._morph_lbl)
        title_scroll = Gtk.ScrolledWindow(hexpand=True)
        title_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        # .lex-title-scroll pins the overlay scrollbar to a hairline at the
        # bottom edge (see style.css) — at this scroller's one-line height
        # the stock hover-fattened bar blankets the text it scrolls.
        title_scroll.add_css_class('lex-title-scroll')
        title_scroll.set_child(title_box)
        header.append(title_scroll)

        # Loading indicator — shown while the SWORD lexicon fetch is in
        # flight on a click. The first-ever click on a Strong's word can
        # take several hundred ms (SWORD initializes its module cache),
        # which previously left the panel blank with no feedback. Lives
        # outside the title scroller so it can't scroll out of view.
        # Delayed: a warm-cache lookup resolving under the perception
        # threshold never flashes it.
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        header.append(self._spinner)
        self._delayed_spinner = DelayedSpinner(self._spinner)

        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.set_tooltip_text(_('Close lexicon'))
        set_accessible_label(close_btn, _('Close lexicon'))
        close_btn.connect('clicked', lambda _: self.hide())
        header.append(close_btn)

        # ── Definition view (left side of horizontal paned) ──
        # `def_view` is exposed as a public attribute so the composer can
        # attach extra gestures (e.g. "close search panel on click").
        def_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        # NEVER on the horizontal policy bounds the scrolled window's
        # natural width to its allocation — otherwise the TextView's
        # natural width briefly balloons to "longest unwrapped line"
        # the moment a new definition is inserted, pushing the lexicon
        # (and therefore the parent pane) wider for a frame.
        def_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._def_view = self.def_view = Gtk.TextView()
        self._def_view.set_editable(False)
        self._def_view.set_cursor_visible(False)
        self._def_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._def_view.set_left_margin(16)
        self._def_view.set_right_margin(16)
        self._def_view.set_top_margin(8)
        self._def_view.set_bottom_margin(8)
        self._def_buf = self._def_view.get_buffer()
        # Headword (first line of an entry) rendered a tad more prominent.
        self._headword_tag = self._def_buf.create_tag(
            'headword', weight=Pango.Weight.BOLD, scale=1.1)
        def_scroll.set_child(self._def_view)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(1)
        gesture.connect('pressed', self._on_def_click)
        self._def_view.add_controller(gesture)

        # Depth bar: when the scholar's lexicon pack is installed and the
        # entry has a full LSJ article, one quiet link swaps the brief
        # Abbott-Smith entry for it (and back). Hidden otherwise.
        self._lsj_btn = Gtk.Button(label=_('Full LSJ entry'))
        self._lsj_btn.add_css_class('flat')
        self._lsj_btn.add_css_class('lex-depth-link')
        self._lsj_btn.set_halign(Gtk.Align.START)
        self._lsj_btn.set_visible(False)
        set_accessible_label(self._lsj_btn, _('Full LSJ entry'))
        self._lsj_btn.connect('clicked', self._on_lsj_toggle)
        self._showing_lsj = False
        self._brief_text = None      # panel-dialect html of the brief entry
        self._brief_heuristic_refs = True

        def_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        def_box.append(def_scroll)
        def_box.append(self._lsj_btn)

        # ── Word study (right side) ──
        ws_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ws_box.add_css_class('ws-panel')

        self._ws_header = Gtk.Label(label='', xalign=0, hexpand=True)
        self._ws_header.add_css_class('ws-header')
        # Same reason as _title above: bound the natural width so a
        # long progress string ("Searching Proverbs… 87 matches so far
        # (31/31)") doesn't widen the lexicon panel's allocation
        # request when it updates during the word-study scan.
        self._ws_header.set_max_width_chars(32)
        self._ws_header.set_ellipsize(Pango.EllipsizeMode.END)
        ws_box.append(self._ws_header)

        self._ws_list = Gtk.ListBox()
        self._ws_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._ws_list.connect('row-activated', self._on_ws_row_activated)

        ws_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        ws_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ws_scroll.set_child(self._ws_list)
        ws_box.append(ws_scroll)

        # ── Horizontal paned: definition left, word study right ──
        self._h_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                                  hexpand=True, vexpand=True)
        self._h_paned.set_start_child(def_box)
        self._h_paned.set_end_child(ws_box)
        self._h_paned.set_resize_start_child(True)
        self._h_paned.set_resize_end_child(True)
        self._h_paned.set_shrink_start_child(False)
        self._h_paned.set_shrink_end_child(False)

        # No separator rule — the soft .lex-panel top border is the only divider
        # from the reading area; the header below is flat, grouped by whitespace.
        self.append(header)
        self.append(self._h_paned)

    # ── Public API ───────────────────────────────────────────────────────

    def set_context(self, book, module):
        """Update the book/module used to scope word-study scans.
        Called by BiblePane whenever its location changes."""
        self._book = book
        self._module = module

    def show_loading(self, strong_num, morph='', phrase_chain=None, phrase_text=None):
        """Reveal the panel immediately with a spinner while the lexicon
        fetch is running. Called by the composer on click; the real
        content arrives later via show(). Resets back history.

        Setting `_current_strong` here also lets late callbacks for a
        previous Strong's number short-circuit in `_show_content`."""
        self._history.clear()
        self._back_btn.set_sensitive(False)
        self._current_strong = strong_num
        self._current_morph = morph
        self._current_phrase = (phrase_chain, phrase_text)
        self._set_title_with_phrase(strong_num, phrase_chain, phrase_text)
        self._morph_lbl.set_text('')
        self._def_buf.set_text('')
        # Clear any prior word-study list and header so the user doesn't
        # see stale content from the previous word during the fetch.
        self._clear_ws()
        self._ws_header.set_text('')
        self._delayed_spinner.start()
        # The previous entry's depth link would be stale for the word now
        # loading — hide until _show_content decides for the new one.
        self._lsj_btn.set_visible(False)
        self._reveal_if_hidden()

    def show(self, strong_num, text, morph='', phrase_chain=None, phrase_text=None):
        """Populate the panel for a Strong's number and reveal it.
        Resets the back history (this is a fresh entry from a
        Bible-text word click, not a navigation within the panel)."""
        self._delayed_spinner.stop()
        self._history.clear()
        self._back_btn.set_sensitive(False)
        self._current_strong = strong_num
        self._current_morph = morph
        self._current_phrase = (phrase_chain, phrase_text)
        self._show_content(strong_num, text)
        self._load_word_study(strong_num)

    def _set_title_with_phrase(self, strong_num, chain, text):
        """Render the title label with an optional muted phrase-context
        suffix. For idiomatic multi-word translations like KJV's
        'God forbid' = μή (G3361) + γένοιτο (G1096), the user sees they
        clicked into a phrase, not a one-to-one word lookup."""
        base = _("Strong's {num}").format(num=strong_num)
        if not chain or len(chain) <= 1:
            self._title.set_text(base)
            return
        others = [s for s in chain if s != strong_num]
        bits = []
        if text and ' ' in text.strip():
            bits.append(_('in “{text}”').format(
                text=GLib.markup_escape_text(text.strip())))
        if others:
            bits.append(_('with {strongs}').format(strongs=' + '.join(others)))
        if not bits:
            self._title.set_text(base)
            return
        suffix = ' · '.join(bits)
        self._title.set_markup(
            f"{GLib.markup_escape_text(base)}  "
            f"<span size='small' alpha='65%'>· {suffix}</span>"
        )

    def hide(self):
        # Teardown path (Esc, module change via clear_state): a pending
        # spinner timer must not fire into a hidden panel.
        self._delayed_spinner.stop()
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
        self._current_phrase = (None, None)
        self.hide()

    # ── Definition rendering ─────────────────────────────────────────────

    def _show_content(self, strong_num, text):
        # Ignore late callbacks from a previous navigation.
        if self._current_strong != strong_num:
            return GLib.SOURCE_REMOVE
        chain, ptext = self._current_phrase
        self._set_title_with_phrase(strong_num, chain, ptext)
        decoded = ''
        if self._current_morph:
            m = self._current_morph
            if 'robinson:' in m:
                decoded = sword_bridge.decode_robinson(m) or ''
            else:
                decoded = sword_bridge.decode_hebrew_morph(m) or ''
        self._morph_lbl.set_text(decoded)

        # Scholar's-pack entries (Abbott-Smith / LSJ) are scholarly prose
        # where "compare 143" cites a section of Herodotus, not Strong's
        # G143 — the heuristic ref rules only fit Strong's-1890 dictionary
        # text. Cheap indexed point queries.
        import lexicon_data
        from_pack = (bool(text) and strong_num.startswith('G')
                     and lexicon_data.has_brief(strong_num))
        self._brief_heuristic_refs = not from_pack

        if not text:
            self._def_buf.set_text(_('Definition not found.'))
        else:
            self._render_def(text, heuristic_refs=not from_pack)

        # Depth link: offer the full LSJ article where the scholar's pack
        # carries one for this word.
        self._brief_text = text
        self._showing_lsj = False
        self._lsj_btn.set_label(_('Full LSJ entry'))
        self._lsj_btn.set_visible(
            bool(text) and strong_num.startswith('G')
            and lexicon_data.has_lsj(strong_num))

        self._reveal_if_hidden()

    def _render_def(self, text, heuristic_refs=True):
        """Render a definition (panel-dialect HTML) into the buffer with
        ref tagging and the headword bump — shared by the brief entry and
        the LSJ depth view."""
        # Any re-render leaves an open verse peek pointing at stale text —
        # close it, and supersede one whose fetch is still in flight.
        tasks.cancel(self._verse_peek_key)
        if self._on_dismiss_peek:
            self._on_dismiss_peek()
        dark = Adw.StyleManager.get_default().get_dark()
        markup = _html_to_markup(text, dark)
        self._def_buf.set_text('')
        try:
            self._def_buf.insert_markup(self._def_buf.get_start_iter(), markup, -1)
        except Exception:
            plain = re.sub(r'<[^>]+>', '', markup)
            self._def_buf.set_text(plain)
            _log.exception('Markup error')
        self._tag_refs(heuristic=heuristic_refs)
        # Bump the headword (first line) so the lemma stands out from the gloss.
        head_start = self._def_buf.get_start_iter()
        head_end = head_start.copy()
        if not head_end.ends_line():
            head_end.forward_to_line_end()
        self._def_buf.apply_tag(self._headword_tag, head_start, head_end)
        # Entry swaps (new word, back-nav, LSJ depth toggle) arrive with a
        # soft fade instead of a pop; the word-study list streams in rows
        # and needs none. Never the reading text.
        fade_in(self._def_view)

    def _on_lsj_toggle(self, _btn):
        """Swap the definition area between the brief (Abbott-Smith) entry
        and the full LSJ article for the same word."""
        import lexicon_data
        if self._showing_lsj:
            self._render_def(self._brief_text or '',
                             heuristic_refs=self._brief_heuristic_refs)
            self._showing_lsj = False
            self._lsj_btn.set_label(_('Full LSJ entry'))
            return
        lsj = lexicon_data.lookup_lsj(self._current_strong or '')
        if not lsj:
            return
        self._render_def(lsj, heuristic_refs=False)
        self._showing_lsj = True
        self._lsj_btn.set_label(_('Brief entry (Abbott-Smith)'))

    def _reveal_if_hidden(self):
        """Reveal the panel, first nudging the outer vertical paned to the
        lexicon's compact height. Setting that position BEFORE the panel
        becomes visible matters: the outer paned has been allocated since
        BiblePane was constructed (only this end-child was hidden), so its
        height is already known and the position-set sticks for the next
        allocation. Without it, GtkPaned's first layout with both children
        visible uses a roughly 50/50 default and the lexicon flashes as a
        huge empty half-pane for a frame before the idle callback shrinks it
        to ~200px."""
        if self.get_visible():
            return
        if self._on_first_show:
            self._on_first_show()
        self.set_visible(True)
        GLib.idle_add(self.init_inner_position)

    def _tag_refs(self, heuristic=True):
        """Find and tag cross-reference numbers in the definition body so
        clicks navigate within the lexicon. Handles SWORD's various
        formats: 'see HEBREW for 07554', 'from 3004', 'ref 123', plain
        'G3056' / 'H1234'. The bare-number rules (1–2) fit Strong's-1890
        dictionary prose only; pass heuristic=False for scholarly entries
        where 'compare 143' cites a classical text."""
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
                # Colour-only: at Abbott-Smith's citation density an
                # underline per ref makes the entry read like a link
                # index — the link colour alone carries the affordance.
                tag = self._def_buf.create_tag(
                    tag_name,
                    foreground='DodgerBlue',
                )
            self._def_buf.apply_tag(tag, s, e)

        if heuristic:
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
        # 4. Scripture refs (Abbott-Smith's 'Mat.8:8' style) — clicking
        # navigates the Bible pane, like a word-study row.
        import lexicon_data
        for start_off, end_off, book, ch, v in \
                lexicon_data.scripture_refs(text):
            tag_name = f'sref:{book}:{ch}:{v}'
            tag = self._def_buf.get_tag_table().lookup(tag_name)
            if not tag:
                tag = self._def_buf.create_tag(
                    tag_name,
                    foreground='DodgerBlue',
                )
            self._def_buf.apply_tag(
                tag, self._def_buf.get_iter_at_offset(start_off),
                self._def_buf.get_iter_at_offset(end_off))

    # ── Word study list ──────────────────────────────────────────────────

    def _load_word_study(self, strong_num):
        # Clear the list immediately so the user sees the new search start.
        self._clear_ws()
        self._ws_rows = 0

        # Capture the search context so a late callback after navigation
        # can be discarded.
        book, module = self._book, self._module
        if not book or not module:
            self._ws_header.set_text('')   # no context — nothing to scan
            return
        self._ws_header.set_text(_('Searching…'))

        # Padding-agnostic: interlinear clicks pass G746 while module
        # markup carries strong:G0746. Compiled once outside the loop.
        pattern = _scan_pattern(strong_num)

        def fetch(task):
            # A mid-scan failure still reaches _ws_finalize with the partial
            # count — a dead scan would leave the header on 'Searching…'
            # forever. (The runner's on_error backstops the same way.)
            running = 0
            try:
                total = sword_bridge.chapter_count(book)
                for ch in range(1, total + 1):
                    if not task.is_current():
                        return running  # superseded — stop scanning
                    batch = []
                    for v_num, html in sword_bridge.load_chapter(module, book, ch):
                        if pattern.search(str(html)):
                            markup = _make_verse_markup(html, strong_num)
                            batch.append((book, ch, v_num, markup))
                    running += len(batch)
                    task.post(self._ws_chapter_done,
                              strong_num, book, module, batch, ch, total, running)
            except Exception:
                _log.exception('word study scan failed')
            return running

        tasks.submit(
            f'wordstudy:{id(self)}', fetch,
            lambda running: self._ws_finalize(strong_num, book, module, running),
            on_error=lambda _exc: self._ws_finalize(strong_num, book, module, 0))

    def _clear_ws(self):
        clear_children(self._ws_list)

    def _ws_chapter_done(self, strong_num, book, module, batch, ch, total, running):
        # Discard stale callbacks — the user may have navigated to a
        # different word, book, or module while the scan was in flight.
        if (self._current_strong != strong_num
                or self._book != book
                or self._module != module):
            return GLib.SOURCE_REMOVE
        # Progress header — running count + chapter position. The chapter
        # number gives the user a sense of how much scanning is left
        # without a full progress bar.
        self._ws_header.set_text(ngettext(
            'Searching {book}… {n} match so far ({ch}/{total})',
            'Searching {book}… {n} matches so far ({ch}/{total})',
            running).format(book=book_label(book), n=running, ch=ch, total=total))
        for ref_book, c, v_num, markup in batch:
            if self._ws_rows >= _WS_ROW_CAP:
                break
            self._ws_list.append(self._build_ws_row(ref_book, c, v_num, markup))
            self._ws_rows += 1
        return GLib.SOURCE_REMOVE

    def _ws_finalize(self, strong_num, book, module, running):
        if (self._current_strong != strong_num
                or self._book != book
                or self._module != module):
            return GLib.SOURCE_REMOVE
        self._ws_header.set_text(ngettext(
            '{n} occurrence in {book}',
            '{n} occurrences in {book}',
            running).format(n=running, book=book_label(book)))
        if running > self._ws_rows:
            # The list stops at the cap; say so rather than look truncated.
            note = Gtk.Label(
                label=_('Showing the first {n} verses').format(n=self._ws_rows),
                xalign=0)
            note.add_css_class('dim-label')
            note.set_margin_start(8)
            note.set_margin_top(6)
            note.set_margin_bottom(8)
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.set_child(note)
            self._ws_list.append(row)
        return GLib.SOURCE_REMOVE

    def _build_ws_row(self, ref_book, ch, v_num, markup):
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
        # Cap the label's *natural* width so the ListBox doesn't request
        # "widest verse" worth of horizontal space when a batch of rows
        # arrives — that's what made the panel pop wider for a frame.
        text_lbl.set_max_width_chars(40)
        try:
            text_lbl.set_markup(markup)
        except Exception:
            text_lbl.set_text(re.sub(r'<[^>]+>', '', markup))
        card.append(ref_lbl)
        card.append(text_lbl)
        row.set_child(card)
        return row

    def _on_ws_row_activated(self, _listbox, row):
        if hasattr(row, '_nav') and self._on_word_study_navigate:
            self._on_word_study_navigate(*row._nav)

    # ── Verse peek (clicking a scripture citation) ───────────────────────

    def _on_panel_unmap(self, _widget):
        tasks.cancel(self._verse_peek_key)
        if self._on_dismiss_peek:
            self._on_dismiss_peek()

    def _show_verse_peek(self, book, chapter, verse, it):
        """Preview a cited verse in a small anchored popover — the
        footnote-peek idiom. A citation click must not tear the user away
        from the pane they're studying, so nothing navigates. The popover
        is the pane's shared self-healing peek (on_show_peek): a popover
        of our own — autohide or not — gets unmapped by the post-click
        relayout churn and vanishes within a second; the pane's instance
        reshows until the layout is stable and only then becomes visible."""
        if self._on_show_peek is None:
            return
        r = self._def_view.get_iter_location(it)
        wx, wy = self._def_view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r.x, r.y)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = (
            wx, wy, max(1, r.width), r.height)

        module = _preview_bible_module()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(280, -1)
        cap_text = f'{book_label(book)} {chapter}:{verse}'
        if module:
            cap_text += f' · {sword_bridge.display_name(module)}'
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cap = Gtk.Label(label=cap_text, xalign=0, hexpand=True)
        cap.add_css_class('caption')
        cap.add_css_class('dim-label')
        head.append(cap)
        if self._on_open_verse and module:
            open_btn = Gtk.Button(icon_name='go-next-symbolic')
            open_btn.add_css_class('flat')
            open_btn.set_valign(Gtk.Align.CENTER)
            open_btn.set_tooltip_text(_('Open in Bible pane'))
            set_accessible_label(open_btn, _('Open in Bible pane'))

            def _open(_btn):
                # The peek's job is done — close it before the pane
                # opens (the relayout would strand it mid-air anyway).
                if self._on_dismiss_peek:
                    self._on_dismiss_peek()
                self._on_open_verse(book, chapter, verse, module)

            open_btn.connect('clicked', _open)
            head.append(open_btn)
        box.append(head)
        body = Gtk.Label(xalign=0, wrap=True)
        body.set_max_width_chars(44)
        body.add_css_class('fnote-body')
        box.append(body)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(14)

        if module is None:
            body.set_text(_('No Bible installed.'))
            self._on_show_peek(self._def_view, rect, box)
            return

        # Fetch off the main thread (first hit may touch disk), and only
        # show the peek once the verse text is in the box — popping up
        # with an empty body and resizing when the text lands reads as
        # flicker. A newer peek (or any dismissing click) supersedes this
        # one on the task key.
        def fetch(_task):
            import ebible_bridge
            if ebible_bridge.is_ebible_module(module):
                verses = ebible_bridge.load_chapter(module, book, chapter)
            else:
                verses = sword_bridge.load_chapter(module, book, chapter)
            for v_num, html in verses:
                if v_num == verse:
                    return re.sub(r'<[^>]+>', '', str(html)).strip()
            return ''

        def show(text):
            body.set_text(text or _('Verse not found in this Bible.'))
            self._on_show_peek(self._def_view, rect, box)

        tasks.submit(self._verse_peek_key, fetch, show,
                     on_error=lambda _exc: show(''))

    # ── In-panel navigation (clicking a cross-reference) ────────────────

    def _navigate_to(self, strong_num):
        if self._current_strong:
            self._history.append(self._current_strong)
            self._back_btn.set_sensitive(True)
        self._current_strong = strong_num
        self._current_morph = None
        # Within-lexicon navigation isn't anchored to a specific Bible
        # phrase, so clear the phrase suffix from the title.
        self._current_phrase = (None, None)
        self._fetch_entry(strong_num)

    def _on_back(self, _btn):
        if not self._history:
            return
        prev = self._history.pop()
        self._current_strong = prev
        self._current_morph = None
        self._current_phrase = (None, None)
        self._back_btn.set_sensitive(bool(self._history))
        self._fetch_entry(prev)

    def _fetch_entry(self, strong_num):
        """Look up a Strong's entry off-thread, then render it and kick the
        word-study scan. Latest-wins per panel: fast back-to-back
        navigations render only the newest entry (the older lookup used
        to race it to the buffer)."""
        def apply(text):
            self._show_content(strong_num, text)
            self._load_word_study(strong_num)

        tasks.submit(f'lexicon:{id(self)}',
                     lambda _task: sword_bridge.lookup_strong(strong_num),
                     apply, on_error=lambda _exc: None)

    def _on_def_click(self, gesture, n_press, x, y):
        # Any click in the view dismisses an open verse peek (the shared
        # peek is non-autohide, so we close it ourselves) and supersedes
        # a peek whose fetch is still in flight, so it can't pop up after
        # this click moved on. A click on another citation re-peeks below.
        tasks.cancel(self._verse_peek_key)
        if self._on_dismiss_peek:
            self._on_dismiss_peek()
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
            if name and name.startswith('sref:'):
                book, ch, v = name[5:].rsplit(':', 2)
                self._show_verse_peek(book, int(ch), int(v), it)
                return
