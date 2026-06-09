import html as _html_mod
import threading
import re
from datetime import date as _date, timedelta
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gsk', '4.0')
from gi.repository import Gtk, Adw, GLib, Gdk, Gsk, Graphene, Pango
import sword_bridge
import ebible_bridge
import catena_bridge
import imagery_bridge
import archaeology_bridge
import content
import annotations
import settings
import module_positions
from genbook_reader import GenbookReader
from catena_reader import CatenaReader
from imagery_reader import ImageryReader
from archaeology_reader import ArchaeologyReader
from module_picker import ModulePicker


import devotional
import annotation_dialogs
from lexicon_panel import LexiconPanel
from pane_search import PaneSearch
from a11y import set_accessible_label

# Logical highlight IDs (persisted in annotations.json) → softer rendered tints.
# Persisted values are unchanged so existing user data still reads correctly;
# only the on-screen color is muted.
# Rendered as *translucent, mid-luminance* bands (not opaque pastels): the
# band tints visibly while the reading text shows through legibly in both
# light and dark mode — no black-text foreground tag, which used to race the
# custom band paint and leave light-on-light highlights (see the band-only
# note on BibleTextView and _apply_anno_tags).
_HIGHLIGHT_RENDER = {
    '#ffff00': 'rgba(226,196,48,0.40)',   # yellow
    '#90ee90': 'rgba(96,180,96,0.40)',    # green
    '#add8e6': 'rgba(74,150,208,0.42)',   # blue
    '#ffa500': 'rgba(234,134,40,0.42)',   # orange
}

# Dark-mode overrides. Orange-only: at full saturation it was the loudest of
# the four bands against a dark page (reads as a confident terracotta where the
# others whisper). Pulled toward amber (less red, a touch more green) with lower
# alpha so the four colors feel like one family. Light mode keeps the table
# above. Theme toggle re-renders the chapter (_on_theme_changed) → this is
# re-evaluated, so the band name stays in sync with the current theme.
_HIGHLIGHT_RENDER_DARK = {
    '#ffa500': 'rgba(214,150,54,0.34)',   # orange — muted amber for dark mode
}


def _render_highlight(color):
    if not color:
        return color
    if Adw.StyleManager.get_default().get_dark():
        dark = _HIGHLIGHT_RENDER_DARK.get(color)
        if dark is not None:
            return dark
    return _HIGHLIGHT_RENDER.get(color, color)


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

    def set_base_margin(self, px):
        """Minimum side margin once the column is wider than the window — the
        floor of the centering. Tightened in ultra-narrow mode so the text
        reflows into the available width instead of clipping."""
        self._base = max(0, int(px))
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


class BibleTextView(Gtk.TextView):
    """TextView that paints verse highlights itself, as bands of a uniform
    height, instead of relying on tag backgrounds.

    A tag background hugs each line's run/line metrics, so the enlarged
    verse-1 drop cap (which makes its wrapped line ~2× taller) and the small
    superscript verse numbers (shorter runs) produced uneven block heights and
    notches. Drawing the band ourselves decouples its height from the line:
    every line of a highlight gets `body_height + 2·pad`. GTK lays text at the
    line-box top with the line-height leading added below, so the band is
    anchored to the line top — uniform regardless of line spacing — letting the
    drop cap rise above it and the numbers sit flush. Highlights are marked by
    zero-visual `hl_bg_<hex>` tags (applied in BiblePane._apply_anno_tags); we
    read their ranges and colors here. Drawn before the text (chained super),
    and the `.bible-view` background is transparent, so the band sits behind
    the glyphs.
    """

    __gtype_name__ = 'BibleTextView'

    _HL_PAD = 2
    _HL_RADIUS = 6   # softly-rounded band corners (band height ~ body + 4px)
    # Transient cues (search match, navigation flash) are painted as bands
    # only — they carry NO text-foreground tag. Recolouring the text via a tag
    # applied/removed after the initial layout desyncs from this custom band
    # paint (GtkTextView keeps a cached glyph rendering that a bare queue_draw
    # doesn't revalidate), which showed up as light-on-light during a flash and
    # black-on-dark after it. So instead the band is a *translucent,
    # mid-luminance* colour: it tints visibly while leaving the reading text
    # legible whatever its colour — light text in dark mode, dark text in light
    # mode, and the black text of a user highlight a flash happens to land on.
    _SEARCH_COLOR = 'rgba(214,150,40,0.40)'   # amber, search matches
    _FLASH_COLOR = 'rgba(232,120,32,0.44)'    # orange, navigation flash
    # Annotation + lexicon underlines are painted (not Pango underlines) so they
    # stay uniform under the 200% verse-1 drop cap. Thickness, and the muted
    # accent of the hover/lexicon dotted underline (per theme).
    _UL_THICK = 1.5
    _LEX_COLOR_DARK = '#7fa3c1'
    _LEX_COLOR_LIGHT = '#5a7fa3'

    def do_snapshot(self, snapshot):
        try:
            self._draw_highlights(snapshot)
        except Exception:
            pass  # never let a paint glitch blank the reading view
        Gtk.TextView.do_snapshot(self, snapshot)

    def _metrics(self):
        m = self.get_pango_context().get_metrics(None, None)
        return m.get_ascent() / Pango.SCALE, m.get_descent() / Pango.SCALE

    def _hl_tags(self):
        out = []
        table = self.get_buffer().get_tag_table()
        def collect(t, _d):
            name = t.get_property('name') or ''
            if name.startswith('hl_bg_'):
                out.append((t, name[len('hl_bg_'):]))
        table.foreach(collect, None)
        return out

    def _draw_highlights(self, snapshot):
        buf = self.get_buffer()
        table = buf.get_tag_table()
        hl_tags = self._hl_tags()
        search = table.lookup('_search_hl')
        flash = table.lookup('_flash')
        ul = table.lookup('_ul_text')        # annotation underline (solid)
        hover = table.lookup('_strg_hover')  # lexicon hover underline (dotted)
        if (not hl_tags and search is None and flash is None
                and ul is None and hover is None):
            return
        vr = self.get_visible_rect()
        _, lo = self.get_iter_at_location(0, vr.y)
        _, hi = self.get_iter_at_location(0, vr.y + vr.height)
        hi.forward_line()
        asc, desc = self._metrics()
        # Stacked, bottom to top: verse highlights, then the search-match
        # band, then the navigation flash — so each stays visible over the
        # one(s) below (e.g. a search hit on a highlighted verse, a flash on
        # either).
        for tag, hexcol in hl_tags:
            self._draw_tag_layer(snapshot, buf, tag, hexcol, lo, hi, asc, desc)
        self._draw_tag_layer(snapshot, buf, search, self._SEARCH_COLOR,
                             lo, hi, asc, desc)
        self._draw_tag_layer(snapshot, buf, flash, self._FLASH_COLOR,
                             lo, hi, asc, desc)
        # Annotation underline — a uniform painted line in the text colour.
        if ul is not None:
            ucol = self.get_color()
            for s, e in self._tag_ranges(buf, ul, lo, hi):
                self._draw_band(snapshot, s, e, ucol, asc, desc,
                                underline=True)
        # Lexicon hover — a dotted accent underline ("defined term" affordance).
        if hover is not None:
            hcol = Gdk.RGBA()
            hcol.parse(self._LEX_COLOR_DARK
                       if Adw.StyleManager.get_default().get_dark()
                       else self._LEX_COLOR_LIGHT)
            for s, e in self._tag_ranges(buf, hover, lo, hi):
                self._draw_band(snapshot, s, e, hcol, asc, desc,
                                underline=True, dotted=True)

    def _draw_tag_layer(self, snapshot, buf, tag, color, lo, hi, asc, desc):
        if tag is None:
            return
        rgba = Gdk.RGBA()
        if not rgba.parse(color):
            return
        for start, end in self._tag_ranges(buf, tag, lo, hi):
            self._draw_band(snapshot, start, end, rgba, asc, desc)

    def _tag_ranges(self, buf, tag, lo, hi):
        it = lo.copy()
        if not it.has_tag(tag) and not it.forward_to_tag_toggle(tag):
            return
        while it.compare(hi) < 0:
            if it.has_tag(tag):
                s = it.copy()
                e = it.copy()
                e.forward_to_tag_toggle(tag)
                yield s, (e if e.compare(hi) < 0 else hi.copy())
                it = e.copy()
            elif not it.forward_to_tag_toggle(tag):
                return

    _BAND_WS = (' ', '\t', ' ', '\n', '\r')

    def _skip_ws_fwd(self, start, end):
        """First non-whitespace iter in [start, end), else end."""
        it = start.copy()
        while it.compare(end) < 0 and it.get_char() in self._BAND_WS:
            if not it.forward_char():
                break
        return it

    def _trim_ws_end(self, start, end):
        """Iter just past the last non-whitespace char in [start, end)."""
        it = end.copy()
        while it.compare(start) > 0:
            probe = it.copy()
            probe.backward_char()
            if probe.get_char() in self._BAND_WS:
                it = probe
            else:
                break
        return it

    def _draw_band(self, snapshot, start, end, rgba, asc, desc,
                   underline=False, dotted=False):
        pad = self._HL_PAD
        body = asc + desc
        band_h = body + 2 * pad
        # Start on real text — skips the leading space before the verse number
        # and any blank line, so band_top and the x-extent are measured from
        # the same (text-bearing) display line.
        cur = self._skip_ws_fwd(start.copy(), end)
        while cur.compare(end) < 0:
            line_end = cur.copy()
            has_end = self.forward_display_line_end(line_end)
            seg_end = line_end if (has_end and line_end.compare(end) < 0) else end.copy()
            # A verse can cross a paragraph break (rendered as a blank line);
            # the band must pause in the gap and resume on the next paragraph,
            # never bridge it. So a segment never spans a hard newline.
            scan = cur.copy()
            while scan.compare(seg_end) < 0:
                if scan.get_char() == '\n':
                    seg_end = scan
                    break
                if not scan.forward_char():
                    break
            # Trim trailing whitespace so the band hugs the last glyph instead
            # of bleeding onto the space render appends after every verse.
            seg_last = self._trim_ws_end(cur, seg_end)
            if seg_last.compare(cur) > 0:
                r0 = self.get_iter_location(cur)
                r1 = self.get_iter_location(seg_last)
                # Anchor the band's top to the display line's *start* so a verse
                # that begins mid-line with the small raised number shares one
                # top with its neighbours. (GTK lays text at the line-box top
                # with the line-height leading below, so the line top is the
                # body-text top regardless of line spacing.)
                ls = cur.copy()
                self.backward_display_line_start(ls)
                band_top = self.get_iter_location(ls).y - pad
                wx0, wy = self.buffer_to_window_coords(
                    Gtk.TextWindowType.TEXT, int(r0.x), int(band_top))
                wx1, _ = self.buffer_to_window_coords(
                    Gtk.TextWindowType.TEXT, int(r1.x), 0)
                seg_w = max(1.0, wx1 - wx0)
                if underline:
                    # Thin line at a fixed offset below the body baseline —
                    # asc is the uniform font ascent, so the line sits at the
                    # same height on every display line, drop cap included.
                    base_uy = wy + pad + asc + 1.0
                    if dotted:
                        # Sit 2px below a solid annotation line so the two read
                        # as parallel lines (not a smear) when a word is both
                        # underlined and hovered for its definition.
                        uy = base_uy + 2.0
                        x = wx0
                        while x < wx1:
                            w = min(2.0, wx1 - x)
                            snapshot.append_color(
                                rgba, Graphene.Rect().init(
                                    x, uy, w, self._UL_THICK))
                            x += 5.0   # 2px dot + 3px gap
                    else:
                        urect = Graphene.Rect().init(
                            wx0, base_uy, seg_w, self._UL_THICK)
                        rounded = Gsk.RoundedRect()
                        # Radius must never exceed half the smallest side, or
                        # the rounded region is degenerate (pixman "invalid
                        # rectangle") — seg_w can be ~1px on a narrow column.
                        rounded.init_from_rect(
                            urect, min(self._UL_THICK / 2, seg_w / 2))
                        snapshot.push_rounded_clip(rounded)
                        snapshot.append_color(rgba, urect)
                        snapshot.pop()
                else:
                    rect = Graphene.Rect().init(wx0, wy, seg_w, band_h)
                    rounded = Gsk.RoundedRect()
                    # Clamp radius to half the smallest side so a ~1px-wide
                    # segment (narrow column) can't make a degenerate region.
                    rounded.init_from_rect(
                        rect, min(self._HL_RADIUS, seg_w / 2, band_h / 2))
                    snapshot.push_rounded_clip(rounded)
                    snapshot.append_color(rgba, rect)
                    snapshot.pop()
            # Advance past this segment, then skip whitespace / blank lines so
            # the next segment starts on real text.
            cur = seg_end.copy()
            if not cur.forward_char():
                break
            cur = self._skip_ws_fwd(cur, end)


class BiblePane(Gtk.Box):
    # Auto-hide-on-scroll tuning for the pane toolbar (pixels of the reading
    # scroll). A top dead-zone always shows the bar near the chapter start;
    # the bar only hides after this much accumulated downward scroll, and
    # reveals after a smaller upward scroll (reveal is deliberately cheaper —
    # hidden chrome must always be trivially easy to bring back).
    _CHROME_TOP_DEADZONE = 64.0
    _CHROME_HIDE_THRESHOLD = 48.0
    _CHROME_SHOW_THRESHOLD = 24.0

    def __init__(self, module_name=None, on_word_click=None,
                 on_click_outside_search=None, on_verse_select=None,
                 on_word_study_navigate=None, on_toast=None,
                 on_font_size_request=None, on_cipher_error=None,
                 on_edit_cipher=None, on_modules_changed=None,
                 on_open_artifact=None, pane_id=1):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_word_click = on_word_click
        self._on_click_outside_search = on_click_outside_search
        self._on_verse_select = on_verse_select
        self._on_word_study_navigate = on_word_study_navigate
        self._on_open_artifact = on_open_artifact
        self._on_toast = on_toast
        self._on_font_size_request = on_font_size_request
        self._on_cipher_error = on_cipher_error
        self._on_edit_cipher = on_edit_cipher
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
        # Bible Imagery card view — also verse-synced from the partnered
        # Bible pane; composed into the content stack below.
        self._imagery = ImageryReader(self)
        # Scripture in Stone — a standalone, bundled archaeology document.
        # NOT verse-synced; it renders once and its verse chips drive the
        # partnered Bible pane.
        self._archaeology = ArchaeologyReader(self)
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
        toolbar.set_margin_top(1)
        toolbar.set_margin_bottom(1)

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
        self._sync_btn.set_tooltip_text(_('Following navigation'))
        set_accessible_label(self._sync_btn, _('Follow navigation'))
        self._sync_btn.connect('notify::active', self._on_sync_toggled)
        toolbar.append(self._sync_btn)

        self._chapter_note_btn = Gtk.Button(icon_name='document-edit-symbolic')
        self._chapter_note_btn.add_css_class('flat')
        self._chapter_note_btn.add_css_class('pane-action')
        self._chapter_note_btn.set_tooltip_text(_('Chapter note'))
        set_accessible_label(self._chapter_note_btn, _('Chapter note'))
        self._chapter_note_btn.connect(
            'clicked', lambda _b: annotation_dialogs.show_chapter_note(self))
        toolbar.append(self._chapter_note_btn)

        toolbar.append(self._search.build_button())

        self._copy_chapter_btn = Gtk.Button(icon_name='edit-copy-symbolic')
        self._copy_chapter_btn.add_css_class('flat')
        self._copy_chapter_btn.add_css_class('pane-action')
        self._copy_chapter_btn.set_tooltip_text(_('Copy chapter'))
        set_accessible_label(self._copy_chapter_btn, _('Copy chapter'))
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
        prev_day_btn.set_tooltip_text(_('Previous day'))
        set_accessible_label(prev_day_btn, _('Previous day'))
        prev_day_btn.connect('clicked', lambda _: self._go_devotional_day(-1))
        self._date_label = Gtk.Label(label='', xalign=0.5, hexpand=True)
        self._date_label.add_css_class('heading')
        next_day_btn = Gtk.Button(icon_name='go-next-symbolic')
        next_day_btn.add_css_class('flat')
        next_day_btn.set_tooltip_text(_('Next day'))
        set_accessible_label(next_day_btn, _('Next day'))
        next_day_btn.connect('clicked', lambda _: self._go_devotional_day(1))
        today_btn = Gtk.Button(label=_('Today'))
        today_btn.add_css_class('flat')
        today_btn.connect('clicked', lambda _: self._go_devotional_day(0, reset=True))
        date_nav.append(prev_day_btn)
        date_nav.append(self._date_label)
        date_nav.append(today_btn)
        date_nav.append(next_day_btn)

        self._date_nav_revealer = Gtk.Revealer()
        self._date_nav_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._date_nav_revealer.set_transition_duration(200)
        self._date_nav_revealer.set_child(date_nav)
        self._date_nav_revealer.set_reveal_child(False)

        # The pane toolbar auto-hides while reading (scroll down to reclaim
        # its height, scroll up / tap the text / focus a control to bring it
        # back) — see _on_reading_scroll below. SLIDE_UP retracts it upward so
        # the reading page rises to fill the space.
        self._toolbar_revealer = Gtk.Revealer()
        self._toolbar_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._toolbar_revealer.set_transition_duration(280)
        self._toolbar_revealer.set_child(toolbar)
        self._toolbar_revealer.set_reveal_child(True)
        # Keyboard focus must never strand the user on a hidden control: any
        # focus entering the toolbar (Tab, Ctrl+L → picker, etc.) reveals it.
        toolbar_focus = Gtk.EventControllerFocus.new()
        toolbar_focus.connect('enter', lambda _c: self._reveal_chrome())
        toolbar.add_controller(toolbar_focus)

        self.append(self._toolbar_revealer)
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
        self._view = BibleTextView()
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
        # Embedded 'related artifact' marker icons in the current chapter, kept
        # so they can be resized live when the reading font changes.
        self._artifact_markers = []
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

        # Auto-hide-on-scroll state for the pane toolbar. Direction-driven with
        # a top dead-zone and a hysteresis accumulator so small or ambiguous
        # motion never toggles it (the jitter that separates premium from
        # janky). Reveal is biased easier than hide. _chrome_lock swallows the
        # value-changes the content reflow emits while the bar animates, so the
        # resize can't bounce the state back near the bottom of a chapter.
        self._chrome_revealed = True
        self._scroll_accum = 0.0
        self._last_scroll_value = 0.0
        self._chrome_lock = False
        self._chrome_lock_id = 0
        scrolled.get_vadjustment().connect('value-changed', self._on_reading_scroll)

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
        # Each child sizes to its own content, not to the widest sibling. A
        # homogeneous stack would pin the min-width-0 reading view to the
        # imagery/archaeology card widths (~280px), so the start child of the
        # non-shrinking lexicon paned could never narrow past that floor —
        # clipping genbook/devotional/archaeology text where Bibles reflow.
        self._content_stack.set_hhomogeneous(False)
        self._content_stack.add_named(scrolled, 'text')
        self._content_stack.add_named(self._catena.widget, 'catena')
        self._content_stack.add_named(self._imagery.widget, 'imagery')
        self._content_stack.add_named(self._archaeology.widget, 'archaeology')
        # Full-pane placeholder for "can't show content here" states
        # (unsupported module, wrong cipher key, passage not in this module).
        self._status_page = Adw.StatusPage()
        self._content_stack.add_named(self._status_page, 'status')
        self._content_stack.set_visible_child_name(self._content_child())

        # Vertical paned: Bible text on top, lexicon panel on bottom.
        # Styled as a soft "page" (rounded top, gentle surface, gutter margins)
        # so the two panes read as pages floating under the header band.
        self._lex_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL,
                                    vexpand=True, hexpand=True)
        self._lex_paned.add_css_class('reading-page')
        # Clip the scroll/lexicon to the page's rounded corners (square child
        # corners would otherwise poke past the 16px card edge).
        self._lex_paned.set_overflow(Gtk.Overflow.HIDDEN)
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
        self._sync_btn.set_visible(
            is_chapter_keyed or self._is_catena or self._is_imagery)
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
        elif self._is_catena or self._is_imagery or self._is_archaeology:
            GLib.idle_add(self._fetch_and_render)

    def _on_pane_click(self, gesture, n_press, x, y):
        """Called when a pane or lexicon text view is clicked."""
        # A tap in the reading area brings the toolbar back (reading-app
        # convention). Reveal-only, not toggle: a tap should never hide chrome
        # mid-read (e.g. a Strong's-word click) — scrolling down does that.
        self._reveal_chrome()
        if self._on_click_outside_search:
            self._on_click_outside_search()

    def _on_reading_scroll(self, adj):
        """Hide/show the pane toolbar based on reading-scroll direction.

        Direction-driven with a top dead-zone and a hysteresis accumulator:
        motion in one direction accumulates and only flips the bar past a
        threshold; a direction change resets the accumulator. Only engages for
        the flowing Bible text — the card views (catena/imagery/archaeology)
        scroll through their own containers and keep the toolbar pinned."""
        v = adj.get_value()
        delta = v - self._last_scroll_value
        self._last_scroll_value = v
        if self._chrome_lock or self._content_child() != 'text':
            self._scroll_accum = 0.0
            return
        # Always reveal near the top of the chapter.
        if v <= self._CHROME_TOP_DEADZONE:
            self._scroll_accum = 0.0
            self._set_chrome_revealed(True)
            return
        # Accumulate motion in the current direction; a reversal resets it.
        if (delta > 0) != (self._scroll_accum > 0):
            self._scroll_accum = 0.0
        self._scroll_accum += delta
        if self._chrome_revealed and self._scroll_accum > self._CHROME_HIDE_THRESHOLD:
            self._set_chrome_revealed(False)
        elif (not self._chrome_revealed
              and self._scroll_accum < -self._CHROME_SHOW_THRESHOLD):
            self._set_chrome_revealed(True)

    def _set_chrome_revealed(self, reveal):
        """Toggle the toolbar revealer, with asymmetric motion timing: exits
        are brisk (get out of the way), entrances gentler (arrive softly)."""
        if reveal == self._chrome_revealed:
            return
        self._chrome_revealed = reveal
        self._scroll_accum = 0.0
        self._toolbar_revealer.set_transition_duration(280 if reveal else 200)
        self._toolbar_revealer.set_reveal_child(reveal)
        # Swallow the value-changes the content reflow emits while the bar
        # animates, so the resize can't bounce the state back.
        self._chrome_lock = True
        if self._chrome_lock_id:
            GLib.source_remove(self._chrome_lock_id)
        self._chrome_lock_id = GLib.timeout_add(360, self._release_chrome_lock)

    def _release_chrome_lock(self):
        self._chrome_lock = False
        self._chrome_lock_id = 0
        self._last_scroll_value = self._reading_scroll.get_vadjustment().get_value()
        return GLib.SOURCE_REMOVE

    def _reveal_chrome(self):
        """Force the pane toolbar back into view (tap, focus, module change)."""
        self._scroll_accum = 0.0
        self._set_chrome_revealed(True)

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
        ref = f'{book_label(self._book)} {self._chapter}:{first_v}'
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
        self._is_imagery = imagery_bridge.is_imagery_module(m)
        self._is_archaeology = archaeology_bridge.is_archaeology_module(m)
        is_ebible = ebible_bridge.is_ebible_module(m)
        if self._is_catena:
            self._module_type = 'Historical Commentaries'
        elif self._is_imagery:
            self._module_type = 'Bible Imagery'
        elif self._is_archaeology:
            self._module_type = 'Scripture in Stone'
        elif is_ebible:
            self._module_type = 'Biblical Texts'
        else:
            self._module_type = sword_bridge.module_type(m)
        self._is_devotional = (
            not self._is_catena and not self._is_imagery
            and not self._is_archaeology and not is_ebible
            and sword_bridge.is_devotional_module(m))
        self._is_genbook = (
            not self._is_catena and not self._is_imagery
            and not self._is_archaeology and not is_ebible
            and self._module_type == 'Generic Books')

    def _content_child(self):
        """Which content-stack child the current module renders into."""
        if self._is_catena:
            return 'catena'
        if self._is_imagery:
            return 'imagery'
        if self._is_archaeology:
            return 'archaeology'
        return 'text'

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
        if self._is_catena or self._is_imagery:
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
        if self._is_catena or self._is_imagery:
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
        # Resize the embedded artifact markers live with the reading font — no
        # re-render needed (the text reflows via the CSS above on its own).
        px = self._artifact_icon_px()
        for img in getattr(self, '_artifact_markers', ()):
            img.set_pixel_size(px)
        just = Gtk.Justification.FILL if self._font_justify else Gtk.Justification.LEFT
        self._view.set_justification(just)
        # Font size / line spacing changed the layout the highlight bands are
        # measured against — repaint them.
        self._view.queue_draw()

    def set_appearance(self, **kwargs):
        if 'font_size'    in kwargs: self._font_size    = kwargs['font_size']
        if 'font_family'  in kwargs: self._font_family  = kwargs['font_family']
        if 'line_spacing' in kwargs: self._line_spacing = kwargs['line_spacing']
        if 'font_bold'    in kwargs: self._font_bold    = kwargs['font_bold']
        if 'font_justify' in kwargs: self._font_justify = kwargs['font_justify']
        if 'text_color'   in kwargs: self._text_color   = kwargs['text_color']
        self._update_font_css()
        # The archaeology document scales with the same reading font size.
        self._archaeology.apply_font_size(self._font_size)

    def set_font_size(self, size):
        self.set_appearance(font_size=size)

    def set_reading_width(self, px):
        self._reading_scroll.set_reading_width(int(px))

    def set_reading_margin(self, px):
        self._reading_scroll.set_base_margin(px)

    def _on_copy_chapter(self, _btn):
        """Copy this pane's current chapter to clipboard as plain text:
        'Book Chapter\\n\\nN verse text\\nN verse text…'."""
        if not self._is_verse_navigable():
            if self._on_toast:
                self._on_toast(_('Copy chapter works on Bibles and commentaries only'))
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
                    GLib.idle_add(self._on_toast,
                                  _("Couldn't load chapter — {error}").format(error=e))
                return
            lines = [f'{book_label(book)} {chapter}', '']
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
            self._on_toast(_('Copied {ref}').format(ref=f'{book_label(book)} {chapter}'))
        return GLib.SOURCE_REMOVE

    def _on_sync_toggled(self, btn, _param):
        locked = btn.get_active()
        btn.set_icon_name('changes-prevent-symbolic' if locked else 'changes-allow-symbolic')
        btn.set_tooltip_text(_('Locked — not following navigation') if locked
                             else _('Following navigation'))
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
        self._content_stack.set_visible_child_name(self._content_child())
        if self._is_catena:
            # Follows the global book/chapter picker (and any verse the
            # partnered Bible broadcasts); defaults to verse 1 on its own.
            self._catena.render_for(
                self._book, self._chapter, self._selected_verse or 1)
            return
        if self._is_imagery:
            self._imagery.render_for(
                self._book, self._chapter, self._selected_verse or 1)
            return
        if self._is_archaeology:
            self._archaeology.render()
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

    def _show_status_page(self, icon, title, description, action=None):
        self._cancel_all_flashes()
        self._search.cancel_hl_timer()
        self._buffer.set_text('')
        self._clear_chapter_scoped_tags()
        self._status_page.set_icon_name(icon)
        self._status_page.set_title(title)
        self._status_page.set_description(description)
        self._status_page.set_child(self._status_action_button(action))
        self._content_stack.set_visible_child_name('status')

    def _status_action_button(self, action):
        """Optional centred pill button for a status page (or None) — turns a
        dead-end placeholder into something the user can act on."""
        if action is None:
            return None
        label, callback = action
        btn = Gtk.Button(label=label)
        btn.add_css_class('pill')
        btn.add_css_class('suggested-action')
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect('clicked', lambda _b: callback())
        return btn

    def _display_unsupported_module(self):
        self._show_status_page(
            'dialog-information-symbolic', self._module,
            _('This module isn’t organized by book and chapter, so it can’t be '
              'read in this pane. Pick a Bible or commentary to read here.'),
            action=(_('Choose another module'),
                    lambda: self._picker.menu_button.popup()))

    def _display_cipher_locked(self):
        """Shown when an encrypted module's content decrypts to gibberish —
        the cipher key is wrong or missing. Pairs with the window's
        'Edit Key' toast."""
        action = ((_('Edit Key'), lambda: self._on_edit_cipher(self._module))
                  if self._on_edit_cipher is not None else None)
        self._show_status_page(
            'dialog-password-symbolic', self._module,
            _('This module’s content isn’t readable — the cipher key may be '
              'incorrect.'),
            action=action)

    def _display_empty_chapter(self, book, chapter):
        """Show a friendly hint when the current module has no content
        for the requested book/chapter — typically NT-only modules
        (SBLGNT, MorphGNT) navigated to an OT passage, or vice versa."""
        self._show_status_page(
            'dialog-information-symbolic', f'{book_label(book)} {chapter}',
            _('{module} doesn’t include this passage. Some modules cover '
              'only the Old or New Testament — pick a Bible with full coverage.').format(
                  module=self._module),
            action=(_('Choose another module'),
                    lambda: self._picker.menu_button.popup()))
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
                '<span foreground="gray">'
                + GLib.markup_escape_text(_('No entry found for this date.'))
                + '</span>', -1)
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

    def _artifact_icon_px(self):
        # Match the reading font (pt) at text height; ×1.4 ≈ the glyph em-box.
        return max(14, int(self._font_size * 1.4))

    def _insert_artifact_marker(self, verse):
        """Embed a tiny clay amphora icon at the end of `verse`, linking to the
        Scripture-in-Stone gallery. A real widget (anchored in the text) rather
        than a font glyph, so it always renders and clicks directly."""
        self._buffer.insert(self._buffer.get_end_iter(), ' ')
        anchor = self._buffer.create_child_anchor(self._buffer.get_end_iter())
        img = Gtk.Image.new_from_icon_name('scriptura-artifact-symbolic')
        # Scale the icon to the current reading font so it sits at text height
        # (font_size is in pt; ×1.4 ≈ the glyph em-box in px).
        img.set_pixel_size(self._artifact_icon_px())
        self._artifact_markers.append(img)
        btn = Gtk.Button(child=img)
        btn.add_css_class('flat')
        btn.add_css_class('artifact-marker')
        # Keyboard/AT users need to reach the marker; an inline icon-only
        # control also needs an explicit accessible name (the tooltip isn't one).
        btn.set_can_focus(True)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(_('Related artifact — open in Scripture in Stone'))
        set_accessible_label(btn, _('Related artifact'))
        if self._on_open_artifact:
            btn.connect(
                'clicked',
                lambda *_a, v=verse: self._on_open_artifact(
                    self, self._book, self._chapter, v))
        self._view.add_child_at_anchor(btn, anchor)

    def _display(self, verses, book, chapter, module):
        if book != self._book or chapter != self._chapter or module != self._module:
            return GLib.SOURCE_REMOVE
        self._rendered_verses = verses

        dark = Adw.StyleManager.get_default().get_dark()
        annos = annotations.get_annotations(module, book, chapter)
        is_commentary = self._module_type == 'Commentaries'
        # Verses in this chapter that a Scripture-in-Stone artifact references,
        # so we can drop a subtle clickable marker beside them (Bibles only).
        art_verses = (set() if is_commentary
                      else archaeology_bridge.verses_with_artifacts(book, chapter))
        self._artifact_markers = []  # rebuilt below; old ones died with set_text('')

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
                self._display_cipher_locked()
                self._on_cipher_error(module)
                return GLib.SOURCE_REMOVE

        if all_empty:
            self._display_empty_chapter(book, chapter)
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
            # Single trailing newline (not two): line_spacing 1.6 already gives
            # ample separation, and a blank line here left an oversized top gap.
            heading = (f'<span size="x-large" weight="bold" '
                       f'foreground="{heading_color}" letter_spacing="600">'
                       f'{GLib.markup_escape_text(f"{book_label(book)} {chapter}")}</span>\n')
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
                v_num_markup = f'<span foreground="gray" size="small" weight="bold" rise="2500"> {start_v} </span>'
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
                # print-Bible feel. Kept even under a highlight — the band is
                # painted at a uniform height by BibleTextView, so the cap
                # rises within it cleanly instead of inflating the block.
                #
                # No `rise` attribute: combining `size="200%"` with a
                # negative `rise` made the verse-1 line's ink extent
                # exceed its reported logical extent, and GTK4 TextView's
                # incremental redraw on scroll left ghost fragments
                # above the cap when the user scrolled the chapter back
                # into view.
                if start_v == 1:
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
                # Subtle 'related artifact' marker — a small clickable
                # amphora icon beside any verse a gallery artifact
                # references. Rare (~34 verses Bible-wide), so it reads as
                # a quiet cue. An embedded icon (not a font glyph) so it
                # always renders — the U+26B1 codepoint falls back to tofu
                # in many reading fonts.
                if start_v in art_verses:
                    self._insert_artifact_marker(start_v)

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
        # Every verse's body-text spans (created by insert_markup during the
        # render loop) carry an ever-increasing tag priority, which can
        # out-rank the readable-text foreground applied earlier — leaving
        # highlighted text in its light body colour on the tint until a later
        # re-apply flips it dark. Re-assert the overlay foregrounds above all
        # body spans now that the whole chapter (and its tags) exists.
        self._bump_overlay_priorities()
        return GLib.SOURCE_REMOVE

    def _bump_overlay_priorities(self):
        """Pin the foreground-bearing overlay tags above the chapter's body-text
        spans so their colour wins from the first frame — the underline and the
        current-verse indicator. Highlights and the transient cues (search /
        flash) are band-only with no foreground, so they need no priority."""
        table = self._buffer.get_tag_table()
        for name in ('_ul_text', '_current_verse'):
            tag = table.lookup(name)
            if tag is not None:
                tag.set_priority(table.get_size() - 1)

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

        # Clear any previous annotation tags from the verse's ranges. The
        # highlight background can reach back over the verse number, so clear
        # from vnum_start (removing where a tag isn't applied is a no-op).
        old_tags = []
        def _collect(t, _data):
            name = t.get_property('name') or ''
            if name.startswith('hl_') or name == '_ul_text':
                old_tags.append(t)
        table.foreach(_collect, None)
        for t in old_tags:
            self._buffer.remove_tag(t, vnum_start, vtext_end)
        note_tag = table.lookup('_note_marker')
        if note_tag:
            self._buffer.remove_tag(note_tag, vnum_start, vtext_start)

        if isinstance(anno, str):
            anno = {'highlight': anno, 'underline': False, 'note': None}
        anno = anno or {}
        highlight = anno.get('highlight')

        # The highlight band is painted by BibleTextView (uniform height); a
        # change here means it must repaint.
        self._view.queue_draw()

        if not (highlight or anno.get('underline') or anno.get('note')):
            return

        def _bump(t):
            # Annotation tags created during chapter render get out-prioritized
            # by anonymous insert_markup tags created on later chapter renders
            # (same priority-decay we hit with flash). Bump to top each apply.
            t.set_priority(table.get_size() - 1)

        if highlight:
            rendered = _render_highlight(highlight)
            # Zero-visual marker tag: BibleTextView reads its range + color
            # (from the `hl_bg_<rgba>` name) and paints the translucent band
            # itself, spanning the verse number too so it's continuous. No text
            # foreground — the band's translucency keeps the reading text (and
            # the gray verse number) legible in both light and dark mode.
            bg_name = f'hl_bg_{rendered}'
            bg = table.lookup(bg_name)
            if not bg:
                bg = self._buffer.create_tag(bg_name)
            self._buffer.apply_tag(bg, vnum_start, vtext_end)

        if anno.get('underline'):
            ul = table.lookup('_ul_text')
            if not ul:
                # Zero-visual marker: BibleTextView paints a uniform line for
                # this range (a Pango underline dips/thickens under the drop cap).
                ul = self._buffer.create_tag('_ul_text')
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
            # Pure marker — no foreground. BibleTextView paints the translucent
            # band from this tag's range; the reading text keeps its own colour
            # so applying/removing the flash never desyncs the glyph colour from
            # the band (the bug that left text low-contrast during the flash and
            # dark after it).
            flash_tag = self._buffer.create_tag('_flash')

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
                self._view.queue_draw()  # band is painted from this tag
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
            self._view.queue_draw()  # band is painted from this tag


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
            # Foreground only — the dotted underline is painted by
            # BibleTextView (Pango has no dotted underline), so the lexicon mark
            # reads distinctly from the solid annotation underline.
            hover_tag = self._buffer.create_tag(
                '_strg_hover',
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
        # Any click in the view dismisses an open dict peek (it's non-autohide,
        # so we close it ourselves).
        existing = getattr(self, '_dict_pop', None)
        if existing is not None and existing.get_visible():
            self._dict_user_closed = True
            existing.popdown()
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
            # Small defer off the click dispatch; the popover shows invisibly
            # and is revealed only once stable, so we don't need to wait out
            # the relayout cascade here.
            GLib.timeout_add(100, self._show_dict_popup, word, offset)

    def _dict_reshow(self, pop):
        """Re-show the dict peek after the relayout cascade unmapped it (see
        the self-heal note in _show_dict_popup). Still invisible (opacity 0)
        until it survives long enough to be revealed."""
        if self._dict_pop is pop and not self._dict_user_closed:
            pop.set_opacity(0.0)
            pop.popup()
            self._dict_arm_reveal(pop)
        return GLib.SOURCE_REMOVE

    def _dict_arm_reveal(self, pop):
        """Reveal the peek once it has stayed mapped briefly — i.e. the
        relayout cascade is over. Re-armed on every (re)show and cancelled
        whenever a close interrupts, so opacity only reaches 1 on a stable
        show and the user never sees the intervening churn."""
        if getattr(self, '_dict_reveal_timer', 0):
            GLib.source_remove(self._dict_reveal_timer)
        self._dict_reveal_timer = GLib.timeout_add(130, self._dict_reveal, pop)

    def _dict_reveal(self, pop):
        self._dict_reveal_timer = 0
        if self._dict_pop is pop and not self._dict_user_closed:
            pop.set_opacity(1.0)
        return GLib.SOURCE_REMOVE

    def dismiss_dict_peek(self):
        """Close an open dictionary peek. Returns True if one was open — the
        window's Escape handler uses this (the peek is non-focusable, so it
        never sees the key itself)."""
        pop = getattr(self, '_dict_pop', None)
        if pop is not None and pop.get_visible():
            self._dict_user_closed = True
            pop.popdown()
            return True
        return False

    def _show_dict_popup(self, word, word_offset):
        # A lightweight "Look Up" peek anchored at the double-clicked word,
        # not a detached window centred on the screen. Deep study still goes
        # through the Strong's lexicon panel.
        #
        # The popover is *non-autohide* and reused per pane: an autohide
        # popover grabs the pointer the instant it's shown, so the very
        # double-click that opened it would read as a click-outside and dismiss
        # it. We dismiss it ourselves instead — on any click in the view
        # (_on_dict_click), a new lookup, or a module change.

        # Guard the self-heal (below) against our own teardown/rebuild: True
        # while we intentionally close or replace the popover.
        self._dict_user_closed = True
        pop = getattr(self, '_dict_pop', None)
        if pop is None:
            pop = Gtk.Popover()
            pop.set_has_arrow(True)
            pop.set_autohide(False)
            pop.set_can_focus(False)
            # Parent to the text view so the arrow anchors on the word in the
            # view's own coordinate space (parenting elsewhere mis-anchors it).
            pop.set_parent(self._view)
            # Clicking a word re-renders the other pane (cross-pane verse
            # sync); that relayout cascade unmaps a freshly-shown popover no
            # matter where it's parented — a Gtk.Popover can't survive a
            # concurrent relayout. So self-heal: if it's torn down within the
            # settle window and the user didn't dismiss it, re-show until the
            # layout goes quiet (the stable state the popover lives in).
            def _on_closed(p):
                # Cancel a pending reveal — the show was interrupted, so it
                # wasn't stable; the next reshow re-arms it.
                if getattr(self, '_dict_reveal_timer', 0):
                    GLib.source_remove(self._dict_reveal_timer)
                    self._dict_reveal_timer = 0
                if (not self._dict_user_closed
                        and self._dict_pop is p
                        and self._dict_retries < 12
                        and GLib.get_monotonic_time() - self._dict_open_at
                        < 1_200_000):
                    self._dict_retries += 1
                    GLib.timeout_add(60, self._dict_reshow, p)
            pop.connect('closed', _on_closed)
            self._dict_pop = pop
        else:
            pop.popdown()

        # Stale-result guard: a newer lookup bumps the generation so an
        # earlier fetch returning late can't overwrite the current content.
        self._dict_gen = getattr(self, '_dict_gen', 0) + 1
        gen = self._dict_gen

        # Point the arrow at the word: union the start/end iter rectangles,
        # converted from buffer coords to widget coords.
        start = self._buffer.get_iter_at_offset(word_offset)
        end = start.copy()
        if not end.ends_word():
            end.forward_word_end()
        r1 = self._view.get_iter_location(start)
        r2 = self._view.get_iter_location(end)
        wx1, wy1 = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r1.x, r1.y)
        wx2, _wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r2.x, r2.y)
        rect = Gdk.Rectangle()
        rect.x = wx1
        rect.y = wy1
        rect.width = max(1, wx2 - wx1) if r2.y == r1.y else max(1, r1.width)
        rect.height = r1.height

        # Open the peek on whichever side of the word has more room, and cap
        # the definition height so the whole popover *fits* on that side. If it
        # doesn't fit, GTK flips it to the other side but strands the arrow on
        # the original edge (pointing away from the word) — capping avoids the
        # flip entirely. Room is measured in the window, where the popover
        # actually lives (it can extend up over the toolbar).
        root = self._view.get_root()
        ok, pt = self._view.compute_point(
            root, Graphene.Point().init(float(rect.x), float(rect.y)))
        word_y = pt.y if ok else rect.y
        win_h = root.get_height() if root is not None else self._view.get_height()
        room_above = word_y
        room_below = win_h - (word_y + rect.height)
        if room_above > room_below:
            pop.set_position(Gtk.PositionType.TOP)
            avail = room_above
        else:
            pop.set_position(Gtk.PositionType.BOTTOM)
            avail = room_below
        # ~130px is the title + tabs + popover chrome above the scrolled body.
        self._dict_max_body = int(max(140, min(320, avail - 130)))
        pop.set_pointing_to(rect)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # Cap to the window width so the popover doesn't overflow a narrow
        # window; 360 is the comfortable width when there's room.
        _root = self.get_root()
        _win_w = _root.get_width() if _root is not None else 0
        content.set_size_request(
            360 if _win_w <= 0 else max(260, min(360, _win_w - 24)), -1)
        pop.set_child(content)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_margin_top(28)
        spinner.set_margin_bottom(28)
        spinner.set_halign(Gtk.Align.CENTER)
        content.append(spinner)
        # Arm the self-heal, then show *invisibly*: the relayout cascade may
        # unmap the popover a few times before the layout settles. Opacity 0
        # until it has stayed up briefly (see _dict_arm_reveal) hides that
        # churn — the user only ever sees the final, stable peek. (Shown with a
        # spinner first so the wrapped TextView can measure its natural height
        # once mapped; building before showing collapses it to a sliver.)
        self._dict_retries = 0
        self._dict_open_at = GLib.get_monotonic_time()
        self._dict_user_closed = False
        pop.set_opacity(0.0)
        pop.popup()
        self._dict_arm_reveal(pop)

        def _clear():
            child = content.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                content.remove(child)
                child = nxt

        def _status(icon, title, desc):
            # Hand-built (not Adw.StatusPage): StatusPage is vexpand and
            # collapses in a small popover, leaving the disclaimer invisible.
            # A plain box reports a real natural height the popover sizes to.
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_margin_top(22)
            box.set_margin_bottom(22)
            box.set_margin_start(24)
            box.set_margin_end(24)
            box.set_valign(Gtk.Align.CENTER)
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(36)
            img.add_css_class('dim-label')
            box.append(img)
            t = Gtk.Label(label=title)
            t.add_css_class('title-4')
            t.set_wrap(True)
            t.set_justify(Gtk.Justification.CENTER)
            box.append(t)
            d = Gtk.Label(label=desc)
            d.add_css_class('dim-label')
            d.set_wrap(True)
            d.set_justify(Gtk.Justification.CENTER)
            d.set_max_width_chars(34)
            box.append(d)
            content.append(box)

        def _headword_title(text):
            # Serif title echoing the app's chapter headings, so the peek
            # reads as a Scriptura entry rather than a system tooltip.
            lbl = Gtk.Label(label=text[:1].upper() + text[1:], xalign=0)
            lbl.add_css_class('dict-headword')
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_margin_start(18)
            lbl.set_margin_end(18)
            lbl.set_margin_top(10)
            lbl.set_margin_bottom(2)
            return lbl

        def _strip_headword(html):
            # Drop a leading headword that duplicates the serif title (plus any
            # indent the SWORD HTML carries). Best-effort: if nothing matches,
            # the body is returned unchanged.
            stripped = re.sub(
                r'^\s*(?:<[^>]+>\s*)*' + re.escape(word)
                + r'(?:\s*</[^>]+>)*\s*(?:<br\s*/?>|[—:.\-,])?\s*',
                '', html, count=1, flags=re.IGNORECASE)
            return re.sub(r'^(?:\s| |&nbsp;)+', '', stripped)

        def _add_text(html, box=None, source=None):
            if box is None:
                box = content
            dark = Adw.StyleManager.get_default().get_dark()
            # Source attribution for the single-dictionary case (the tabs carry
            # it when there are several).
            if source:
                cap = Gtk.Label(label=source, xalign=0)
                cap.add_css_class('caption')
                cap.add_css_class('dim-label')
                cap.set_margin_start(18)
                cap.set_margin_bottom(6)
                box.append(cap)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_propagate_natural_height(True)
            scroll.set_max_content_height(self._dict_max_body)
            # Floor the body so a long entry can't collapse to a sliver when
            # the natural-height measurement under-reports (it does for some
            # popover positions). A short entry sits in this min with a little
            # slack rather than scrolling.
            scroll.set_min_content_height(min(self._dict_max_body, 200))
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_cursor_visible(False)
            tv.set_wrap_mode(Gtk.WrapMode.WORD)
            tv.set_left_margin(18)
            tv.set_right_margin(18)
            tv.set_top_margin(4)
            tv.set_bottom_margin(14)
            # Breathe — the app reads generously everywhere else.
            tv.set_pixels_below_lines(3)
            tv.set_pixels_inside_wrap(3)
            buf = tv.get_buffer()
            html = _strip_headword(html)
            markup = _html_to_markup(html, dark)
            try:
                buf.insert_markup(buf.get_end_iter(), markup, -1)
            except Exception:
                buf.set_text(re.sub(r'<[^>]+>', '', html))
            scroll.set_child(tv)
            box.append(scroll)

        def _build_source_tabs(results):
            # Underline tabs matching the module picker, not a chunky
            # StackSwitcher.
            tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            tabs.add_css_class('module-tabs')
            tabs.set_halign(Gtk.Align.START)
            tabs.set_margin_start(10)
            tabs.set_margin_top(2)
            tabs.set_margin_bottom(7)
            stack = Gtk.Stack()
            stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            stack.set_transition_duration(120)
            stack.set_vhomogeneous(False)
            btns: dict = {}

            def _on_tab(btn, mn):
                if not btn.get_active():
                    if stack.get_visible_child_name() == mn:
                        btn.set_active(True)   # enforce exactly-one
                    return
                # Switch first, then clear the others — deactivating a sibling
                # re-enters this handler, and it must see the new selection so
                # it doesn't snap itself back on.
                stack.set_visible_child_name(mn)
                for k, b in btns.items():
                    if k != mn and b.get_active():
                        b.set_active(False)

            ordered = sorted(results, key=lambda r: r[1].lower())
            for mn, md, html in ordered:
                page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                _add_text(html, page)
                stack.add_named(page, mn)
                btn = Gtk.ToggleButton(label=_short_dict_title(mn, md))
                btns[mn] = btn
                btn.connect('toggled', _on_tab, mn)
                tabs.append(btn)
            first = ordered[0][0]
            btns[first].set_active(True)
            stack.set_visible_child_name(first)
            content.append(tabs)
            content.append(stack)

        def populate(results):
            # Guard against a later double-click having replaced this popover.
            if gen != self._dict_gen:
                return GLib.SOURCE_REMOVE
            _clear()
            if not results:
                _status('system-search-symbolic', f'No entry for “{word}”',
                        'Bible dictionaries index proper nouns and key terms '
                        '— try a word like “covenant,” “Abraham,” or '
                        '“atonement.”')
            else:
                content.append(_headword_title(word))
                if len(results) == 1:
                    mn, md, html = results[0]
                    _add_text(html, source=_short_dict_title(mn, md))
                else:
                    _build_source_tabs(results)
            return GLib.SOURCE_REMOVE

        def show_no_dicts():
            if gen != self._dict_gen:
                return GLib.SOURCE_REMOVE
            _clear()
            _status('dialog-information-symbolic', 'No dictionaries installed',
                    'Add Easton’s or Smith’s Bible Dictionary from the '
                    'Module Manager.')
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
        self._sync_btn.set_visible(
            is_chapter_keyed or self._is_catena or self._is_imagery)
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
        # Dismiss any dict peek since it's tied to a word in the previous
        # module's text. Reused popover — hide it, don't unparent.
        prev_dict = getattr(self, '_dict_pop', None)
        if prev_dict is not None and prev_dict.get_visible():
            self._dict_user_closed = True
            prev_dict.popdown()
        # A fresh module starts with its chrome shown (the new content may not
        # even drive the reading scroll — card views don't).
        self._reveal_chrome()
        self._fetch_and_render()

    def select_verse(self, verse_num):
        """Called by other panes broadcasting a verse selection."""
        if self._is_archaeology:
            return  # standalone document — not verse-keyed
        if self._is_catena:
            self._selected_verse = verse_num
            self._catena.render_for(self._book, self._chapter, verse_num)
            return
        if self._is_imagery:
            self._selected_verse = verse_num
            self._imagery.render_for(self._book, self._chapter, verse_num)
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
