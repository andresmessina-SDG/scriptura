import html as _html_mod
import threading
import colorsys
import re
from datetime import date as _date, timedelta
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gsk', '4.0')
from gi.repository import Gtk, Adw, GLib, Gdk, Graphene, Pango
from gtk_utils import clear_children
import sword_bridge
import ebible_bridge
import archaeology_bridge
import genealogy_bridge
import content
import annotations
import motion
import settings
import tasks
import module_positions
import pane_content
from genbook_reader import GenbookReader
from catena_reader import CatenaReader
from imagery_reader import ImageryReader
from archaeology_reader import ArchaeologyReader
from genealogy_reader import GenealogyReader
from interlinear_view import InterlinearReader
import interlinear_data
from module_picker import ModulePicker


import devotional
import annotation_dialogs
from lexicon_panel import LexiconPanel
from audio_surfaces import DevotionalAudio, ReadingAudio
from pane_chrome import ChromeController
from reading_view import BibleTextView
from pane_scroll import ScrollKeeper
from pane_search import PaneSearch
from verse_cursor import VerseCursor
import a11y
from a11y import set_accessible_label
from i18n import _, ngettext, book_label


def is_dark_paper(paper_hex):
    """Whether a paper colour wants light ink on it.

    The paper decides, not the system scheme: a light paper theme under a
    dark desktop still needs dark ink, and the gold on the Today page has to
    choose the same way the ink does."""
    r = int(paper_hex[1:3], 16) / 255
    g = int(paper_hex[3:5], 16) / 255
    b = int(paper_hex[5:7], 16) / 255
    return 0.299 * r + 0.587 * g + 0.114 * b < 0.5


def auto_reading_ink(paper_hex):
    """Derive a comfortable reading ink for a paper colour. Dark papers get a
    warm off-white; light papers get a warm dark ink that *shares the paper's
    hue* — near-black on neutral/white, warm brown on sepia, deep green on a
    green paper — so 'Default' ink stays harmonious on any paper, including a
    custom one. Mirrored in the Appearance chip previews."""
    r = int(paper_hex[1:3], 16) / 255
    g = int(paper_hex[3:5], 16) / 255
    b = int(paper_hex[5:7], 16) / 255
    if is_dark_paper(paper_hex):
        return '#e8e0d4'                       # dark paper → warm light ink
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.06:
        return '#1a1a1a'                       # neutral/white paper → near-black
    nr, ng, nb = colorsys.hls_to_rgb(h, 0.16, min(s, 0.55))
    return f'#{round(nr * 255):02x}{round(ng * 255):02x}{round(nb * 255):02x}'

# The curated reading serif stack, expanded from the generic 'serif' default.
# Shared so presentation mode renders in the same face as the reading pane.
# Leads with the bundled 'Noto Serif' so the Scripture face is identical on
# every machine (the whole point of bundling) instead of resolving to whatever
# serif the host happens to have. Noto Serif is also fully polytonic, which
# tagged Greek (MorphGNT/SBLGNT) needs — and it keeps 'Georgia' from being
# reached, since Fedora binds Georgia to Gelasio, which renders polytonic varia
# as detached spacing graves (καὶ → και`). The rest are fallbacks only if the
# bundle is ever absent.
READING_SERIF_STACK = ("'Noto Serif', 'Source Serif 4', 'Charter', "
                       "'Iowan Old Style', 'Georgia', serif")

# Greek runs render in a guaranteed-polytonic serif regardless of the user's
# Latin reading face: Georgia and many text serifs lack the precomposed
# "…with varia/perispomeni" glyphs and show a detached spacing grave
# (καὶ → και`). Mirrors .interlinear-word's Greek stack. A run must BEGIN with
# a Greek letter, so a stray combining mark sitting on Latin is never captured.
_GREEK_FONT = 'Noto Serif, DejaVu Serif, Source Serif 4, serif'
# A Greek/Coptic (U+0370–03FF) or Greek Extended (U+1F00–1FFF) letter, then any
# run of the same plus combining diacritics (U+0300–036F) for decomposed text.
# (Escaped codepoints — combining marks are invisible/ambiguous as literals.)
_GREEK_RUN = re.compile(
    '[Ͱ-Ͽἀ-῿]'
    '[Ͱ-Ͽἀ-῿̀-ͯ]*')

# Hebrew has the identical exposure: a Latin reading face carries no niqqud or
# te'amim mark positioning, so a pointed WLC verse read under Georgia stacks its
# vowels beside the letter instead of beneath it. Mirrors .interlinear-word-heb.
_HEBREW_FONT = "Noto Serif Hebrew, SBL Hebrew, Ezra SIL, Taamey Frank CLM, serif"
# Written as escapes, not literals: Hebrew source characters reorder under the
# editor's bidi algorithm, which makes a literal range unreadable and easy to
# mis-edit. Start = a letter (U+05D0–05EA plus the wide/yiddish letters), so a
# stray mark on Latin is never captured; continue = letters, the full
# points/accents/punctuation block (U+0591–05C7), and Hebrew presentation forms.
_HEBREW_RUN = re.compile(
    '[\u05d0-\u05ea\u05ef-\u05f2\ufb1d-\ufb4f]'
    '[\u0591-\u05c7\u05d0-\u05ea\u05ef-\u05f4\ufb1d-\ufb4f]*')

# Logical highlight IDs (persisted in annotations.json) → softer rendered tints.
# Persisted values are unchanged so existing user data still reads correctly;
# only the on-screen color is muted.
# Rendered as *translucent, mid-luminance* bands (not opaque pastels): the
# band tints visibly while the reading text shows through legibly in both
# light and dark mode — no black-text foreground tag, which used to race the
# custom band paint and leave light-on-light highlights (see the band-only
# note on BibleTextView and _apply_anno_tags).
# Pointer wobble tolerated while a hover-preview dwell is armed. Wayland
# compositors hand raw sub-pixel deltas, so "the cursor stopped" must be
# a radius, not equality — movement inside it keeps the dwell; beyond it
# re-anchors and restarts (the two-threshold pattern from the auto-hide
# work).
_HOVER_JITTER_PX = 8


def _gloss_from_strong_entry(text):
    """Boil a raw lexicon entry down to hovercard size. Classic Strong's
    entries repeat their number (the caption already carries it) and end
    in a ':--' KJV usage list — reference-material noise at a glance; the
    definition proper sits before the delimiter. Richer lexicons
    (Abbott-Smith) lead with the lemma and have neither, so both trims
    are conditional; a word-boundary cap backstops everything."""
    plain = ' '.join(re.sub(r'<[^>]+>', ' ', str(text or '')).split())
    plain = re.sub(r'^\d+\s+', '', plain)
    head, sep, _usage = plain.partition(':--')
    if sep and len(head.strip()) >= 40:
        plain = head.strip().rstrip(';,') + '.'
    if len(plain) > 360:
        plain = plain[:360].rsplit(' ', 1)[0] + '…'
    return plain

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


# A footnote filter leaves an empty <note swordFootnote="N" …/> anchor at
# each note's attachment point (the body lives elsewhere — see
# sword_bridge.chapter_footnotes / ebible_bridge.chapter_footnotes, both
# of which key their bodies to this N). Matched pre-markup so the anchor
# becomes a marker token instead of being silently stripped.
_NOTE_ANCHOR_RE = re.compile(
    r'<note\s[^>]*?swordFootnote="(\d+)"[^>]*?(?:/>|>\s*</note>)')
_FN_TOKEN_RE = re.compile(r'\[\[FN_(\d+)\]\]')

#: Publisher section headings carry this tag, newlines and all, and are always
#: rendered — the setting only flips its `invisible`, so showing or hiding them
#: restyles the chapter instead of rebuilding it. Covers the headings that
#: arrive as entry attributes (_insert_section_heading). Headings embedded in
#: the markup as <title>/<h1..6> go in through insert_markup with their blank
#: lines OUTSIDE the span, so they cannot be hidden by one tag; a chapter with
#: those falls back to a render. Not chapter-scoped: one shared style tag.
_HEADING_TAG = 'section_heading'

#: Source markup that carries its own headings, which the tag above cannot
#: govern. Checked per verse so the toggle knows whether it may restyle.
_INLINE_TITLE_RE = re.compile(r'<title([^>]*)>|<h[1-6]>', re.IGNORECASE)


def _renders_inline_title(html):
    """True when this verse's markup carries a heading _html_to_markup would
    actually draw. The skipped types (a psalm's superscription, an acrostic
    letter, a parallel-passage note) never become headings, so a chapter full
    of them can still be restyled rather than re-rendered."""
    for m in _INLINE_TITLE_RE.finditer(str(html)):
        attr = re.search(r'type="([^"]+)"', m.group(1) or '')
        kind = attr.group(1).lower() if attr else ''
        if kind not in _SKIP_INLINE_TITLE_TYPES:
            return True
    return False

#: Every footnote marker label carries this tag as well as its own
#: `fnote:{verse}:{n}`. Markers are now always rendered, and the setting only
#: flips this tag's `invisible` — so turning footnotes on or off restyles the
#: chapter instead of rebuilding it (see BiblePane.set_show_footnotes). Not in
#: _CHAPTER_SCOPED_TAG_PREFIXES: it is one shared style tag, not per-chapter
#: state, and it must survive the rebuild that clears those.
_FN_MARKER_TAG = 'fn_marker'


def _fn_label(idx):
    """0-based marker index → bijective base-26 label: a…z, aa, ab, …
    Every note in a chapter gets a unique label, print-Bible style."""
    label = ''
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        label = chr(ord('a') + r) + label
    return label


def _substitute_footnote_markers(markup, vnotes, dark, start_idx=0):
    """Replace [[FN_n]] tokens with superscript marker labels.

    Labels run continuously through the chapter (print-Bible style), so
    `start_idx` carries the counter across verses and the next index is
    returned. Returns (markup, [(plain_offset, n, label)], next_idx) —
    plain_offset is the marker's character offset within the inserted
    text, so the fnote: tag can be applied by offset arithmetic instead
    of a buffer search. Tokens whose n has no body in vnotes are dropped.
    Done on the final markup string (not by segmented insertion) so Pango
    spans that cross an anchor — e.g. red-letter text — stay correctly
    paired.

    Ordinary letters raised with `rise`, not Unicode superscript glyphs:
    the superscript block has no q (the old glyph set wrapped at 25 with
    q missing), while rise+size renders the full a…z, aa… sequence."""
    color = theme_ink(dark)['_ink_link']
    out = []
    markers = []
    pos = 0
    plain_off = 0
    idx = start_idx
    for m in _FN_TOKEN_RE.finditer(markup):
        chunk = markup[pos:m.start()]
        out.append(chunk)
        plain_off += len(_html_mod.unescape(re.sub(r'<[^>]+>', '', chunk)))
        pos = m.end()
        n = m.group(1)
        if n not in vnotes:
            continue
        label = _fn_label(idx)
        idx += 1
        # small + rise ≈ the old size="large" superscript glyphs' visual
        # weight and elevation; small keeps the click target fair.
        out.append(f'<span size="small" rise="3000" foreground="{color}">'
                   f'{label}</span>')
        markers.append((plain_off, n, label))
        plain_off += len(label)
    out.append(markup[pos:])
    return ''.join(out), markers, idx


_DICT_SHORT_NAMES = {
    # Hand-tuned for common SWORD dict modules where the heuristic below
    # would otherwise pick a less recognisable form.
    'Easton':       "Easton's",
    'Smith':        "Smith's",
    'ISBE':         'ISBE',
    'Naves':        "Nave's",
    'Torreys':      "Torrey's",
    'WebstersDict': "Webster's 1913",
    'Wikcionario':  'Wikcionario',
}

_DICT_FLUFF_WORDS = {
    'dictionary', 'encyclopedia', 'revised', 'unabridged',
    'concise', 'of', 'the', 'english', 'language', 'bible',
    'topical', 'textbook', 'a', 'an',
    # Spanish — the app ships a Spanish interface and now a Spanish
    # dictionary, whose Description is generic in exactly the same way.
    'diccionario', 'enciclopedia', 'general', 'español', 'española',
    'lengua',
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
        # A dash or bullet separating the name from its blurb is not a word:
        # counting it as one spent half the two-word budget and left the
        # label trailing a dangling em dash ("Wikcionario —").
        if not re.search(r'\w', clean):
            continue
        if clean.lower() in _DICT_FLUFF_WORDS:
            break
        words.append(clean)
        if len(words) >= 2:
            break
    short = ' '.join(words) if words else mod_name
    return f'{short} {year}' if year else short


def _strip_leading_headword(html, word):
    """Drop a leading headword that duplicates the peek's serif title (plus
    any indent the SWORD HTML carries). Best-effort: if nothing matches, the
    body is returned unchanged.
    """
    stripped = re.sub(
        r'^\s*(?:<[^>]+>\s*)*' + re.escape(word)
        # A middle dot means the word heads a compound label
        # ("dios · Sustantivo masculino"), where dropping the word
        # alone would strand the separator. Leave those whole.
        + r'(?!\s*·)'
        + r'(?:\s*</[^>]+>)*\s*(?:<br\s*/?>|[—:.\-,])?\s*',
        '', html, count=1, flags=re.IGNORECASE)
    return re.sub(r'^(?:\s| |&nbsp;)+', '', stripped)


# Inline <title> kinds that are not section headings, mirroring the rule
# sword_bridge applies to the attribute-sourced ones: parallel-passage
# cross references and canonical Psalm superscriptions would both read as
# headings if rendered as one.
_SKIP_INLINE_TITLE_TYPES = frozenset({'parallel', 'psalm', 'acrostic', 'sub'})


def _html_to_markup(html, dark, strip=True, divine_smallcaps=False,
                    show_headings=True):
    # Ensure we are working with a string
    html = str(html)
    # Strip lone surrogates that SWORD produces from non-UTF-8 module data
    if any('\ud800' <= c <= '\udfff' for c in html):
        html = ''.join(c for c in html if not ('\ud800' <= c <= '\udfff'))

    # 1. Map SWORD/HTML tags to temporary markers to protect them from escaping
    red = theme_ink(dark)['_ink_redletter']

    # Red letters (Jesus' words)
    html = re.sub(r'<q [^>]*who="Jesus"[^>]*>(.*?)</q>', r'[[RED_S]]\1[[RED_E]]', html)
    html = re.sub(r'<font color="red">(.*?)</font>', r'[[RED_S]]\1[[RED_E]]', html)

    # Italics (translator additions)
    html = re.sub(r'<transChange type="added">(.*?)</transChange>', r'[[I_S]]\1[[I_E]]', html)
    html = re.sub(r'<i>(.*?)</i>', r'[[I_S]]\1[[I_E]]', html)
    # The quoted word a footnote comments on ("<catchWord>firmament</catchWord>:
    # Heb. expansion") — italicised so note bodies keep their word/gloss shape.
    html = re.sub(r'<catchWord>(.*?)</catchWord>', r'[[I_S]]\1[[I_E]]', html, flags=re.DOTALL)
    # OSIS-style emphasis used by commentaries like Calvin's — `<hi
    # type="italic">` wraps Bible-verse citations within the body;
    # `<hi type="bold">` wraps the verse-number prefix ("1." etc.).
    # Without these the commentary loses all visual hierarchy.
    html = re.sub(r'<hi\s[^>]*type="italic"[^>]*>(.*?)</hi>', r'[[I_S]]\1[[I_E]]', html, flags=re.DOTALL)
    html = re.sub(r'<hi\s[^>]*type="bold"[^>]*>(.*?)</hi>', r'[[INLINE_B_S]]\1[[INLINE_B_E]]', html, flags=re.DOTALL)
    # Straubinger's notes open with their own locator, which is the same verse
    # prefix in a different tag: `<reference type="annotateRef">3 ss. </reference>`.
    # It is not redundant with the marker beside it — "3 ss." says the note
    # runs from verse 3 on, which a marker on one verse cannot say — so it is
    # kept and given the prefix's weight rather than dropped to bare digits.
    # Bounded to annotateRef: a commentary's `<reference osisRef=…>` is a
    # cross-reference the segmented insertion turns into a link, not a prefix.
    html = re.sub(r'<reference\s[^>]*type="annotateRef"[^>]*>(.*?)</reference>',
                  r'[[INLINE_B_S]]\1[[INLINE_B_E]]', html, flags=re.DOTALL)
    # Inline verse-number superscripts used by MHC: `<hi type="super">N</hi>`
    # marks the start of verse N within a section's continuous prose.
    html = re.sub(r'<hi\s[^>]*type="super"[^>]*>(.*?)</hi>', r'[[SUP_S]]\1[[SUP_E]]', html, flags=re.DOTALL)

    # Divine name (OSIS <divineName>, the LORD/GOD convention) → small
    # caps. Content is usually mixed-case ("Lord"), which the small-caps
    # variant renders as L + small ORD; the few all-caps bodies ("LORD",
    # 6 in KJV) are case-normalized so they don't stay full-size caps.
    if divine_smallcaps:
        html = re.sub(r'<divineName[^>]*>(.*?)</divineName>',
                      lambda m: '[[DN_S]]' + _normalize_divine(m.group(1)) + '[[DN_E]]',
                      html, flags=re.DOTALL)

    # Titles and Headings. The pattern has to allow attributes: enabling
    # SWORD's Headings option (needed for the Bible section headings, which
    # arrive as entry attributes) also lets commentaries emit their own
    # titles INLINE, and those carry a type — Clarke's are `type="x-s"`,
    # MHC's `type="x-s3"`. A bare `<title>` pattern missed them, the generic
    # tag-strip below then removed the tags but not the text, and a heading
    # like "The Creation. (b. c. 4004.)" landed in the middle of the
    # commentary's prose as ordinary body text.
    #
    # `show_headings=False` drops them entirely rather than rendering them:
    # they only became visible when that option was turned on, so the
    # Appearance toggle has to govern them too or turning it off would leave
    # commentary headings the reader never used to see.
    def _title_sub(m):
        attr = re.search(r'type="([^"]+)"', m.group(1) or '')
        kind = attr.group(1).lower() if attr else ''
        if not show_headings or kind in _SKIP_INLINE_TITLE_TYPES:
            return ''
        return f'[[B_S]]{m.group(2)}[[B_E]]'

    html = re.sub(r'<title([^>]*)>(.*?)</title>', _title_sub, html,
                  flags=re.DOTALL)
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

    # Flattened footnote anchors: CCEL-sourced Generic Books (Calvin's
    # Institutes) carry footnote markers as bare digit runs in the "A B AB"
    # form ("5 3 53", "20 05 205") immediately before a <scripRef> citation —
    # conversion debris, not prose. Strip only that 3+-group signature sitting
    # against a scripRef; a lone number there is real ("Greg. Lib. 4
    # <scripRef>Ep. 76</scripRef>" — a patristic book number) and must survive.
    html = re.sub(r'(?<=\D)\d+(?: \d+){2,}\s+(?=<scripRef)', ' ', html)

    # 2. Strip all other tags (like <w>, <p>, etc.) but keep content
    html = re.sub(r'<[^>]+>', '', html)

    # Decode HTML entities the source already escaped ("&amp;c." → "&c.")
    # before we Pango-escape below — otherwise the '&' is escaped a second
    # time and the literal "&amp;c." shows on screen. Mirrors the unescape
    # the plain-offset path already does.
    html = _html_mod.unescape(html)

    # 3. Escape the raw text so characters like '&' and '<' don't break Pango
    html = GLib.markup_escape_text(html)

    # Collapse runs of horizontal whitespace to a single space — some modules
    # (Didache) pad ~10 literal spaces between every word, which Pango renders
    # as gaping holes. Newlines/paragraph breaks are preserved (handled in the
    # cleanup below); only spaces and tabs collapse.
    html = re.sub(r'[^\S\n]{2,}', ' ', html)

    # 4. Swap markers back for real Pango Markup
    html = html.replace('[[RED_S]]', f'<span foreground="{red}">').replace('[[RED_E]]', '</span>')
    html = html.replace('[[I_S]]', '<i>').replace('[[I_E]]', '</i>')
    html = html.replace('[[DN_S]]', '<span variant="small-caps">')
    html = html.replace('[[DN_E]]', '</span>')
    # Section titles: a quiet kicker rather than undifferentiated body
    # bold — slightly smaller than the body, tracked, muted ink; the
    # blank line above / single newline below keeps more space above
    # than below (heading hierarchy: chapter > section > body).
    html = html.replace(
        '[[B_S]]',
        '\n\n<span size="90%" weight="bold" letter_spacing="800" '
        'foreground="gray">')
    html = html.replace('[[B_E]]', '</span>\n')
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

    # Force Greek and Hebrew into faces that cover their diacritics (see
    # _GREEK_RUN / _HEBREW_RUN). Applied last, on the finished markup: runs are
    # plain non-ASCII text and Pango tags are ASCII, so a match can never land
    # inside a tag name or attribute value.
    html = _GREEK_RUN.sub(
        lambda m: f'<span font_family="{_GREEK_FONT}">{m.group(0)}</span>',
        html)
    html = _HEBREW_RUN.sub(
        lambda m: f'<span font_family="{_HEBREW_FONT}">{m.group(0)}</span>',
        html)

    # Commentary's segmented insertion passes strip=False so the space
    # before/after a <reference> segment is preserved — otherwise the
    # rendered text reads "Elijah,Rom 11:1-5" with no breathing room.
    return html.strip() if strip else html


def _normalize_divine(inner):
    """Case-normalize a <divineName> body for the small-caps span: an
    all-caps body ("LORD") would render full-size (small caps only maps
    lowercase), so lower everything after the first letter. Mixed-case
    bodies — the overwhelming majority — pass through untouched, as do
    the rare bodies carrying nested tags."""
    if '<' not in inner and len(inner) > 1 and inner.isupper():
        return inner[0] + inner[1:].lower()
    return inner


# The literal fallback for modules that print the divine name as literal
# capitals with no OSIS markup (BSB, Webster, the eBible KJV). Possessive
# forms ride inside the span (KJV prints "LORD'S" as part of the name).
_DIVINE_LITERAL_RE = re.compile(r"\b(LORD|GOD|JEHOVAH)(['’][Ss])?\b")
_DIVINE_TOKENS = frozenset({'LORD', 'GOD', 'JEHOVAH'})
_WORD_BEFORE_RE = re.compile(r"([A-Za-z][A-Za-z'’]*)[\s\"“”]*$")
_WORD_AFTER_RE = re.compile(r"^[\s,;:.!?'’\"“”]*([A-Za-z]+)")


def _is_caps_word(word):
    word = word.replace("'", '').replace('’', '')
    return len(word) >= 2 and word.isupper()


def _smallcap_divine_literals(markup):
    """Wrap literal all-caps divine names (LORD / GOD / JEHOVAH) in a
    small-caps span, skipping all-caps inscriptions ("HOLINESS TO THE
    LORD", "TO THE UNKNOWN GOD") — corpus-swept: a neighboring all-caps
    word marks an inscription, unless that neighbor is itself a divine
    name ("LORD GOD", "LORD JEHOVAH" are compound names, not context).
    Operates on the text runs of final Pango markup; tags pass through."""
    parts = re.split(r'(<[^>]+>)', markup)
    for i, part in enumerate(parts):
        if not part or part.startswith('<'):
            continue

        def repl(m):
            name, poss = m.group(1), m.group(2) or ''
            wb = _WORD_BEFORE_RE.search(m.string[:m.start()])
            wa = _WORD_AFTER_RE.match(m.string[m.end():])
            for w in ((wb.group(1) if wb else None),
                      (wa.group(1) if wa else None)):
                if w and w.upper() not in _DIVINE_TOKENS and _is_caps_word(w):
                    return m.group(0)
            return (f'{name[0]}<span variant="small-caps">'
                    f'{name[1:].lower()}{poss.lower()}</span>')

        parts[i] = _DIVINE_LITERAL_RE.sub(repl, part)
    return ''.join(parts)


# Drop-cap ink: the illuminated-initial tradition is gold. A user custom
# colour (stored hex) wins; otherwise a scheme-aware antique gold —
# deeper on light paper, soft gold leaf on dark.
DROPCAP_GOLD_LIGHT = '#a5822b'
DROPCAP_GOLD_DARK = '#d0ac5c'


def _dropcap_split(markup):
    """Split a verse's markup around the first real letter, for the drop cap.

    Returns (before, letter, after) or None when there is no letter to
    enlarge. Three things have to be stepped over to find it:

    * markup tags — the red-letter span opens before the text;
    * opening punctuation — LEB and BSB both begin Matthew 6:1 with a
      quotation mark, and the old ASCII-letter regex simply gave up there,
      so those translations silently lost their drop cap;
    * character entities — `&quot;` contains letters, and capping its "q"
      would enlarge a piece of the escape rather than the verse.

    The letter test is `str.isalpha`, not `[A-Za-z]`: the old class matched
    Latin only. RusSynodalLIO appeared to work solely because its text
    happens to start with a Latin "C" homoglyph rather than a Cyrillic one —
    genuine Cyrillic, Greek or Hebrew got no cap.

    The fourth thing to step over is a footnote token. Modules that anchor a
    note at the very start of verse 1 — Straubinger does it in every chapter —
    put `[[FN_1]]` ahead of the first word, and capping the "F" inside it both
    loses the cap and splits the token so it can never become a marker: the
    reader sees a literal `[[FN_1]]` and the note behind it is unreachable.
    """
    i, n = 0, len(markup)
    while i < n:
        ch = markup[i]
        if markup.startswith('[[FN_', i):  # footnote token, not text
            j = markup.find(']]', i)
            if j < 0:
                return None
            i = j + 2
        elif ch == '<':                    # markup tag
            j = markup.find('>', i)
            if j < 0:
                return None
            i = j + 1
        elif ch == '&':                    # character entity
            j = markup.find(';', i)
            if j < 0 or j - i > 12:
                return None
            i = j + 1
        elif ch.isalpha():
            return markup[:i], ch, markup[i + 1:]
        else:
            i += 1                         # quote, bracket, space…
    return None


# The cap's size and weight, and nothing else. Its colour is applied as a tag
# over the same character (`BiblePane._apply_dropcap_tag`) rather than written
# in here: a colour baked into markup cannot be found again, and both the
# toggle and the custom-colour picker have to change it without a re-render.
_DROPCAP_SPAN = '<span size="200%" weight="bold">'


def _plain_len(markup):
    """How many characters `markup` contributes to the buffer.

    Tags contribute none, an entity exactly one, everything else itself. Used
    to turn the cap span's position in the markup into its offset in the text
    — the same markup-to-plain-offset move `_substitute_footnote_markers`
    makes for marker letters.
    """
    n = i = 0
    end = len(markup)
    while i < end:
        ch = markup[i]
        if ch == '<':
            j = markup.find('>', i)
            if j < 0:
                break
            i = j + 1
        elif ch == '&':
            j = markup.find(';', i)
            n += 1
            i = i + 1 if (j < 0 or j - i > 12) else j + 1
        else:
            n += 1
            i += 1
    return n


def _dropcap_index(markup, since):
    """Where the cap sits in the text `markup` will produce, or None.

    `since` is where the span was before the footnote markers went in. Markers
    can only push it further right, so searching from there both skips work and
    rules out an earlier accidental match. None when the span is not there at
    all — a lost cap is a cosmetic miss, not worth raising over.
    """
    at = markup.find(_DROPCAP_SPAN, since)
    return _plain_len(markup[:at]) if at >= 0 else None


def dropcap_color_hex(dark):
    """Effective drop-cap colour (shared with the Appearance swatch)."""
    custom = settings.get('dropcap_color')
    if custom:
        return str(custom)
    return DROPCAP_GOLD_DARK if dark else DROPCAP_GOLD_LIGHT


def _numeral_features(oldstyle):
    """The OpenType feature verse and chapter numerals are set with.

    Both states are explicit — some faces (Georgia) default to old-style
    figures, so OFF must request lining (lnum) rather than request nothing, or
    the toggle is invisible there. Faces lacking a feature ignore it.
    """
    return 'onum=1' if oldstyle else 'lnum=1'


def theme_ink(dark):
    """Every foreground a rendered chapter bakes that depends on the theme.

    One table, keyed by the tag name the render adopts each colour into
    (`BiblePane._adopt_theme_ink`). A colour that is written straight into the
    markup and nowhere else cannot be found again after the fact, and the
    recolouring path would go quietly stale the day someone changed one of
    them — so the markup and the recolouring read the same entry.

    `_ink_link` is the blue shared by footnote markers, commentary
    cross-references and the lexicon hover; they are one colour by intent.
    """
    return {
        '_ink_heading':   '#8d8278' if dark else '#7a7066',
        '_ink_link':      '#7fa3c1' if dark else '#5a7fa3',
        '_ink_redletter': '#e07070' if dark else '#bb0000',
        '_ink_dropcap':   dropcap_color_hex(dark),
    }


# ── Per-verse decorations ────────────────────────────────────────────────────

class _VerseRender:
    """What one verse of the render loop produced, for the marks that follow it.

    The loop fills this in as it writes the verse; `_decorate_verse` then walks
    `_VERSE_DECORATIONS` over it. Everything a per-verse mark has ever needed
    is here, so a new mark is an entry in that tuple rather than another branch
    inside the loop — which is what the loop had become.

    `start_mark` spans the whole block (heading excluded, deliberately);
    `text_mark` starts at the verse text, after the number. Both are left
    gravity, so text inserted by an earlier decoration does not drag them.
    """

    __slots__ = ('start_v', 'end_v', 'html', 'is_commentary', 'anno',
                 'start_mark', 'text_mark', 'has_artifact', 'has_lineage',
                 'cap_index', 'fn_markers', 'vnotes', 'poetry_lines')

    def __init__(self, start_v, end_v, html, is_commentary):
        self.start_v = start_v
        self.end_v = end_v
        self.html = html
        self.is_commentary = is_commentary
        self.anno = {}
        self.start_mark = None
        self.text_mark = None
        self.has_artifact = False
        self.has_lineage = False
        # Filled in by the Bible branch only; a commentary produces none of
        # them, and the plain-text fallback resets them to exactly this.
        self.cap_index = None
        self.fn_markers = []
        self.vnotes = {}
        self.poetry_lines = {}


class _VerseDecoration:
    """One mark applied to a verse as it is rendered.

    Mirrors `reading_view._Decoration`, which does the same job for the marks
    the view PAINTS; this one is for the marks the render APPLIES. Both answer
    the same question — what is on this verse and what switches it on — and
    keeping one shape for both means a reader who has seen one has seen both.
    """

    __slots__ = ('name', 'apply', 'enabled')

    def __init__(self, name, apply, enabled=None):
        self.name = name
        self.apply = apply
        self.enabled = enabled

    def on(self, pane, r):
        return self.enabled is None or bool(self.enabled(pane, r))


#: Commentaries carry none of the verse-level marks but `vnum`: they render one
#: block per section, their own `Verse N` header stands in for the number, and
#: they take no user annotations — hence the `not r.is_commentary` on all but
#: one entry below.
#:
#: In application order, and the order is load-bearing twice over. The artifact
#: marker INSERTS a character, so it has to land before `vnum` measures the
#: block's end. And `strong_words` reads the text between `text_mark` and the
#: end, so it has to come after everything that adds to it.
_VERSE_DECORATIONS = (
    _VerseDecoration(
        'dropcap',
        lambda p, r: p._apply_dropcap_tag(r.text_mark, r.cap_index),
        lambda p, r: not r.is_commentary and r.cap_index is not None),
    _VerseDecoration(
        'footnotes',
        lambda p, r: p._apply_footnote_tags(
            r.start_v, r.fn_markers, r.vnotes, r.text_mark),
        lambda p, r: not r.is_commentary and bool(r.fn_markers)),
    _VerseDecoration(
        'poetry_lines',
        lambda p, r: p._apply_poetry_line_tags(r.text_mark, r.poetry_lines),
        lambda p, r: not r.is_commentary and bool(r.poetry_lines)),
    # Subtle 'related artifact' marker — a small clickable amphora icon beside
    # any verse a gallery artifact references. Rare (~34 verses Bible-wide), so
    # it reads as a quiet cue. An embedded icon (not a font glyph) so it always
    # renders — U+26B1 falls back to tofu in many reading fonts.
    _VerseDecoration(
        'artifact_marker',
        lambda p, r: p._insert_artifact_marker(r.start_v),
        lambda p, r: not r.is_commentary and r.has_artifact),
    # The same quiet cue for a verse the genealogy table draws a line from.
    # `marker_verses` has already thinned a genealogy chapter down to one
    # marker — without that, Matthew 1 carries fifteen of these.
    _VerseDecoration(
        'lineage_marker',
        lambda p, r: p._insert_lineage_marker(r.start_v),
        lambda p, r: not r.is_commentary and r.has_lineage),
    # The verse anchor navigation resolves against. For a grouped commentary
    # section every verse in [start_v, end_v] points at the same block, so
    # navigating to any of them lands on this section. No enable condition:
    # this one is the reason a block is addressable at all.
    _VerseDecoration('vnum', lambda p, r: p._apply_vnum_tags(r)),
    # Highlight / underline / note indicator, applied in place so they can be
    # changed later without rebuilding the chapter (`_refresh_verse_annotation`).
    # Skipped for un-annotated verses: on a fresh buffer there is nothing to
    # clear, and the per-verse call was the chapter render's main scaling cost.
    _VerseDecoration(
        'annotations',
        lambda p, r: p._apply_anno_tags(r.start_v, r.anno, fresh=True),
        lambda p, r: not r.is_commentary and bool(r.anno)),
    _VerseDecoration(
        'strong_words',
        lambda p, r: p._tag_strong_words(
            p._buffer.get_iter_at_mark(r.text_mark),
            p._buffer.get_end_iter(), r.html),
        lambda p, r: (not r.is_commentary and p._lexicon_enabled
                      and p._on_word_click)),
)


# OSIS poetry-line milestones (<l sID/> … <l eID/>, ASV/BSB/LEB carry
# level="1..3", ESV marks the indented b-line type="x-indent") become
# [[PL*]] tokens before the generic tag strip — the same protection
# pattern as footnote anchors. <lg> stanza-group starts become a gap
# token; everything else about a group is implicit in its lines.
_POETRY_TOKEN_RE = re.compile(r'\[\[PL(?:S[123]|E|GS)\]\]')


def _poetry_tokens(html):
    def l_token(m):
        tag = m.group(0)
        if 'eID' in tag:
            return '[[PLE]]'
        lm = re.search(r'level="(\d+)"', tag)
        if lm:
            level = min(max(int(lm.group(1)), 1), 3)
        elif 'x-indent' in tag:
            level = 2
        else:
            level = 1
        return f'[[PLS{level}]]'
    html = re.sub(r'<l(?=[\s/>])[^>]*/>', l_token, html)
    # Container form (<l>…</l>) for completeness; installed modules all
    # use milestones, but the OSIS schema allows both.
    html = re.sub(r'<l(?=[\s>])[^>]*(?<!/)>', l_token, html)
    html = re.sub(r'</l\s*>', '[[PLE]]', html)
    html = re.sub(r'<lg(?=[\s/>])[^>]*sID[^>]*/>', '[[PLGS]]', html)
    html = re.sub(r'<lg(?=[\s/>])[^>]*>|</lg\s*>', '', html)
    return html


def _resolve_poetry_markup(markup, state):
    """Resolve [[PL*]] tokens to newlines; return (markup, line_levels).

    line_levels maps a line index *within this verse's inserted text*
    (0 = the line the verse starts on) to its indent level. `state` is
    the chapter-render carry — poetry lines cross verse boundaries
    (ASV closes a line and opens the next across the verse break), so
    `open` (the level of a line left unclosed by the previous verse)
    and `at_ls` (whether the buffer sits at a fresh line, verse-number
    prefixes not counting as content) persist across the verse loop.
    """
    levels = {}
    if state['open'] is not None:
        levels[0] = state['open']
    if '[[PL' not in markup:
        # Prose verse: just keep the line-start carry honest.
        if markup:
            state['at_ls'] = markup.endswith('\n')
        return markup, levels
    out = []
    nl = 0
    pos = 0
    skip_ws = False

    def emit(seg):
        nonlocal nl, skip_ws
        if skip_ws:
            seg = seg.lstrip(' \t')
            if seg:
                skip_ws = False
        if not seg:
            return
        out.append(seg)
        nl += seg.count('\n')
        tail = re.sub(r'<[^>]+>', '', seg.rsplit('\n', 1)[-1])
        if tail.strip():
            state['at_ls'] = False
        elif '\n' in seg:
            state['at_ls'] = True

    for m in _POETRY_TOKEN_RE.finditer(markup):
        emit(markup[pos:m.start()])
        pos = m.end()
        tok = m.group(0)
        if tok == '[[PLE]]':
            out.append('\n')
            nl += 1
            state['open'] = None
            state['at_ls'] = True
            skip_ws = True
        elif tok == '[[PLGS]]':
            # Stanza gap: one blank line between groups.
            if not state['at_ls']:
                out.append('\n\n')
                nl += 2
                state['at_ls'] = True
            elif out:
                out.append('\n')
                nl += 1
            skip_ws = True
        else:  # [[PLS<n>]]
            level = int(tok[5])
            if not state['at_ls']:
                out.append('\n')
                nl += 1
                state['at_ls'] = True
            levels[nl] = level
            state['open'] = level
            skip_ws = True
    emit(markup[pos:])
    return ''.join(out), levels


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
    Strong's number.

    The prefix match is case-insensitive because the modules disagree:
    SpaRV1909 writes `savlm="Strong:H7225"` on nearly every word and the
    lowercase `strong:` only inside its rare multi-number tags, so a
    case-sensitive match found 15 of 36 verses in John 3 and none at all
    in Genesis 1 — a fully tagged Bible whose word study was dead."""
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
        strong_nums = [s.upper() for s in
                       re.findall(r'strong:([GH]\d+)', attrs, re.IGNORECASE)]
        mm = re.search(r'morph="([^"]+)"', attrs)
        morph = mm.group(1) if mm else None
        segments.append((content, strong_nums, morph))
        pos = m.end()
    if pos < len(html):
        segments.append((html[pos:], [], None))
    return segments




#: Longest a rebuild's scroll hold may last (see _ReadingScrolledWindow.
#: hold_scroll). Generous against a slow render, short enough that a hold
#: which somehow never released cannot pin the scrollbar for a reader.
HOLD_SAFETY_MS = 2000


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
        # Set by BiblePane: called (during layout — receiver must defer
        # real work to idle) when the viewport height changes, e.g. the
        # lexicon paned opening or a window resize.
        self.on_height_change = None
        # Same contract, fired when the computed side margins change —
        # the poetry indent tags mirror the margin (a tag left-margin
        # REPLACES the view's, so it must track it).
        self.on_margins_change = None
        self._last_alloc_height = -1
        # Set by hold_scroll() for the length of a rebuild; see there.
        self._hold_value = None
        self._hold_handler = None
        self._faked_upper = None
        self._in_hold = False
        # Bumped by every hold and every release, so a safety timer can tell
        # whether the hold it was armed for is still the one running.
        self._hold_gen = 0

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
        # Margins first, then chain up. Setting them afterwards re-queued a
        # resize on the TextView with the parent's allocation already done,
        # and the overlay scrollbar's trough was then snapshotted with no
        # allocation of its own ("Trying to snapshot GtkGizmo ..." on every
        # resize). Applying them first lets one allocation pass do the work.
        self._apply_margins(width)
        Gtk.ScrolledWindow.do_size_allocate(self, width, height, baseline)
        self._reassert_held_scroll()
        if height != self._last_alloc_height:
            was_first = self._last_alloc_height < 0
            self._last_alloc_height = height
            if not was_first and self.on_height_change is not None:
                self.on_height_change()

    def hold_scroll(self):
        """Keep the reading position through a buffer rebuild.

        Emptying the buffer collapses the vadjustment's `upper` to GTK's
        estimate for the lines it has not validated yet (measured: 16245 ->
        688 on Psalms 119), and the chain-up above clamps `value` against it.
        The restore runs on an idle at DEFAULT_IDLE, which loses to
        GDK_PRIORITY_REDRAW — so the clamped value is what gets PAINTED, and
        the reader sees the chapter top for two or three frames before the
        position walks back.

        Held here rather than fixed at the source because GtkTextView offers
        no way to validate the lines early: get_iter_location, get_line_yrange,
        queue_draw and scroll_to_iter all read the btree's estimates and leave
        `upper` where it was (measured for the scroll matrix).
        """
        adj = self.get_vadjustment()
        if self._hold_value is None:
            # Rebuilds can arrive faster than they finish. Only the first of a
            # run captures: by the second, `value` is whatever the unfinished
            # first one left behind — a clamp, or the restore's overshoot — and
            # capturing that locks the run onto the wrong position.
            self._hold_value = adj.get_value() or None
        self._faked_upper = None
        if self._hold_value is None:
            return
        # The collapse does not wait for an allocation: GtkTextView revises
        # `upper` from its validation idle too, and those frames are painted
        # as well. Ride the adjustment's own signal instead of only the
        # layout pass.
        if self._hold_handler is None:
            self._hold_handler = adj.connect('changed', self._on_adj_changed)
        # A hold must never outlive its rebuild, whatever happens to the
        # restore. Nothing downstream is trusted to end it. The timer is
        # stamped with the hold it belongs to: an unstamped one expiring 2s
        # later tore down whichever hold happened to be running by then, which
        # is how a toggle could still paint the chapter top (measured: holds at
        # 5.882 and 6.082 killed the rebuilds that began at 7.827 and 8.050).
        self._hold_gen += 1
        GLib.timeout_add(HOLD_SAFETY_MS, self._expire_hold, self._hold_gen)

    def _expire_hold(self, gen):
        if gen == self._hold_gen:
            self._release_hold()
        return GLib.SOURCE_REMOVE

    def _on_adj_changed(self, _adj):
        if self._in_hold:
            return                      # our own set_upper coming back round
        self._in_hold = True
        try:
            self._reassert_held_scroll()
        finally:
            self._in_hold = False

    def release_scroll_hold(self):
        """End a hold because the rebuild's restore has run. That is the only
        honest end signal available — see _reassert_held_scroll for why the
        adjustment's height cannot serve as one."""
        self._release_hold()

    def _release_hold(self):
        self._hold_value = None
        self._faked_upper = None
        # Retire this hold's number so its safety timer, still pending, cannot
        # come back and release a hold taken after it.
        self._hold_gen += 1

        if self._hold_handler is not None:
            self.get_vadjustment().disconnect(self._hold_handler)
            self._hold_handler = None
        return GLib.SOURCE_REMOVE

    def _reassert_held_scroll(self):
        """Put the held position back, whatever moved it. Ends only when the
        rebuild's restore says so — never on the strength of a height, because
        `upper` reads tall both when GTK has finished revalidating and when it
        has not yet collapsed at all, and the two are indistinguishable from
        here (measured: released at upper=27462, painted the chapter top at
        upper=836 four frames later)."""
        if self._hold_value is None:
            return
        adj = self.get_vadjustment()
        page = adj.get_page_size()
        upper = adj.get_upper()
        # `_faked_upper` is our own height talking back — GTK has revised
        # nothing, so it is not evidence the document has grown.
        if upper != self._faked_upper and upper - page < self._hold_value:
            # Lie about the height for exactly as long as the estimate is
            # short, and by the smallest amount that clears the clamp. The
            # alternative is a value of nearly zero: the flicker.
            #
            # It is tempting to report the height the document came in with
            # instead, so the scrollbar thumb (sized page/upper) does not
            # twitch. Do not: holding `upper` above what GtkTextView has
            # actually laid out starves its incremental validation, and the
            # view paints a BLANK page for the length of the hold. Tried,
            # seen, reverted. The thumb is GTK's to move; the position is
            # ours to keep.
            self._faked_upper = self._hold_value + page
            adj.set_upper(self._faked_upper)
        # Pin unconditionally, including while `upper` is tall enough to carry
        # the position on its own. Nothing is clamping then, but GtkTextView
        # SCROLLS as it revalidates — holding a visible line steady against
        # corrected heights above it — and that walked the value 683px
        # (11464 -> 12147 at upper=12964) into a painted frame.
        if adj.get_value() != self._hold_value:
            adj.set_value(self._hold_value)

    def _apply_margins(self, avail):
        if avail <= 0:
            return
        side = max(self._base, (avail - self._reading_width) // 2)
        if self._view.get_left_margin() != side:
            self._view.set_left_margin(side)
            self._view.set_right_margin(side)
            if self.on_margins_change is not None:
                self.on_margins_change()


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


#: How far the focus veil quiets the page outside the sense-unit being read
#: — the paper's own colour laid back over the text at this alpha. Chosen by
#: eye from rendered candidates; low enough that the quieted text stays
#: readable if the reader looks at it, which is the difference between a
#: focus aid and a blindfold.
FOCUS_DIM = 0.55


class BiblePane(Gtk.Box):
    # The auto-hide-on-scroll chrome band lives in ChromeController
    # (pane_chrome.py) — its reveal state, hysteresis thresholds, and the
    # strip animation that keeps the reading glyphs screen-fixed. This pane
    # owns the reading scroll/anchor machinery it collaborates with.

    def __init__(self, module_name=None, on_word_click=None,
                 on_click_outside_search=None, on_verse_select=None,
                 on_word_study_navigate=None, on_toast=None,
                 on_font_size_request=None, on_cipher_error=None,
                 on_edit_cipher=None, on_modules_changed=None,
                 on_open_artifact=None, on_open_lineage=None, on_module_switched=None,
                 on_hint=None, on_open_verse=None, pane_id=1):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        # GROUP, not REGION — measured, not assumed. GTK4's AT-SPI backend
        # emits no landmark roles at all: REGION, MAIN, NAVIGATION and BANNER
        # every one of them arrives at AT-SPI as `filler`, a semantically
        # empty spacer. `gtk_test_accessible_has_role` passes for REGION
        # (GTK stores it faithfully), which is exactly why this needed
        # checking against a live AT-SPI tree rather than the GTK test API.
        # GROUP maps to `grouping`, a real container role, and the pane's
        # accessible name survives either way — so Orca says "Reading pane 1"
        # and now has an honest role to attach it to. Don't "upgrade" this
        # back to REGION; landmark navigation is not available here.
        a11y.set_role(self, Gtk.AccessibleRole.GROUP)
        set_accessible_label(
            self, _('Reading pane {n}').format(n=pane_id))
        self._on_word_click = on_word_click
        self._on_click_outside_search = on_click_outside_search
        self._on_verse_select = on_verse_select
        self._on_word_study_navigate = on_word_study_navigate
        self._on_open_artifact = on_open_artifact
        self._on_open_lineage = on_open_lineage
        self._on_toast = on_toast
        self._on_font_size_request = on_font_size_request
        self._on_cipher_error = on_cipher_error
        self._on_edit_cipher = on_edit_cipher
        self._on_modules_changed = on_modules_changed
        # Fires after this pane switches to a different module — the window
        # re-evaluates cross-pane state that depends on what's loaded
        # (currently the f* footnote toggle's sensitivity).
        self._on_module_switched = on_module_switched
        # Fired with a hint key the first time a discoverability context
        # occurs (see onboarding.HintController); the controller collapses
        # repeats, so the pane may call it freely.
        self._on_hint = on_hint
        # Used to namespace per-pane persisted state (e.g. genbook
        # bookmarks) so pane1 and pane2 don't trample each other.
        self._pane_id = pane_id
        self._lexicon_enabled = False
        # Translator-footnote markers (the † header toggle). Persisted,
        # unlike the lexicon: footnotes are reading content, not a lookup
        # mode, so a reader who wants them wants them every session.
        self._show_footnotes = bool(settings.get('show_footnotes'))
        # Section headings (Appearance ▸ Advanced). A reading convention —
        # publisher-supplied structure that SWORD hands over separately from
        # the verse text — so it defaults on, like small caps.
        self._show_headings = bool(settings.get('show_headings'))
        self._mark_current_unit = bool(settings.get('mark_current_unit'))
        # Quiet the rest of the page while reading a unit. Shares the
        # `_cur_unit` tag with the margin rule above, so either, both or
        # neither can run.
        self._focus_unit = bool(settings.get('focus_current_unit'))
        # Verse the currently-marked sense-unit starts at, so a scroll that
        # stays inside one unit costs a comparison and no retagging.
        self._current_unit = None
        # Advanced typography (Appearance ▸ Advanced): small-caps divine
        # name and old-style figures are reading conventions (on by
        # default); flush poetry and the tinted drop cap are opt-ins.
        self._smallcaps_divine = bool(settings.get('smallcaps_divine'))
        self._oldstyle_nums = bool(settings.get('oldstyle_numerals'))
        self._poetry_flush = bool(settings.get('poetry_flush'))
        self._colored_dropcap = bool(settings.get('colored_dropcap'))
        # Hover-to-preview (Appearance ▸ Advanced, off by default): dwell
        # state for the Strong's gloss hovercard — the candidate word, the
        # pointer anchor the jitter radius is measured from, the pending
        # dwell/grace timers, and the word range an open gloss belongs to.
        self._hover_preview = bool(settings.get('hover_preview'))
        self._hover_word = None          # (start_off, end_off, strong_num)
        self._hover_anchor = (0.0, 0.0)
        self._hover_timer = 0
        self._hover_grace_timer = 0
        self._hover_gloss_range = None
        # Poetry-line paragraph tags, created on first poetry render;
        # their margin geometry follows the reading column (see
        # _sync_poetry_tags).
        self._poetry_tags = None
        # (verse, marker_index) → (type, body) for the rendered chapter;
        # the fnote: click handler reads the peek content from here.
        self._chapter_footnotes = {}
        self._rendered_inline_titles = False
        # {verse: [section heading, …]} for the rendered chapter. Declared
        # here, not only in _display: the re-theme path calls _display with
        # no headings argument, so the attribute has to exist before the
        # first fetch ever assigns one.
        self._rendered_headings = {}
        # Per-pane Ctrl+F search subsystem (widgets + state + highlight tag).
        # Constructed eagerly so the toolbar button and revealer can be
        # placed during _build_ui below.
        self._search = PaneSearch(self)
        # Keyboard access to the verse/word gestures (verse_cursor.py).
        self._cursor = VerseCursor(self)

        self._names = content.readable_module_names()
        if not self._names:
            raise RuntimeError('No SWORD modules installed.')

        self._module = module_name if module_name in self._names else self._names[0]
        # Generic Books rendering, TOC, prev/next/TOC widgets, and entry-
        # path persistence live in GenbookReader. build_toolbar() below
        # attaches the three toolbar widgets; set_module() loads the
        # last-read entry path.
        self._genbook = GenbookReader(self, _html_to_markup)
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
        # The Book of Generations — a standalone, bundled genealogy document.
        # Like Scripture in Stone it is NOT verse-synced: it renders once and
        # its verse chips drive the partnered Bible pane.
        self._genealogy = GenealogyReader(self)
        # Interlinear Greek NT — word-stack cells, verse-synced like a Bible.
        self._interlinear = InterlinearReader(self)
        # Each content mode is a PaneContent strategy; _compute_module_flags
        # resolves the active one into self._content, so the render path calls
        # one object instead of branching on _is_<mode> at every dispatch site.
        # Card modes (own stack child) are registry-keyed; the text-view modes
        # depend on the finer flags and are picked during resolution.
        self._contents = pane_content.build(self)
        self._text_content = pane_content.build_text(self)
        self._compute_module_flags()
        self._genbook.set_module(self._module, self._is_genbook)
        self._book = 'Genesis'
        self._chapter = 1
        self._target_verse = None
        self._restore_top_verse = None
        # Pixel-exact reading locus captured before a content-mutating
        # re-render (footnote toggle, theme flip) — consumed by _display.
        # Coarser than _restore_top_verse's use (module switches), finer
        # restore: same verse, same character, same pixel.
        self._restore_anchor = None
        # The reading-anchor / generation / pin machinery (the "text never
        # moves" north star) and the scroll-intent tracking live on
        # ScrollKeeper; the auto-hiding toolbar band + its strip compensation
        # live on ChromeController. Both hold a back-reference to this pane and
        # touch its widgets at call time, so they can be built now (before the
        # widgets) — and created before _update_font_css, which marks a
        # programmatic scroll during construction. The pane keeps thin
        # delegates + forwarding _reading_anchor / _anchor_seq properties so
        # every render/navigation/signal call site is unchanged.
        self._scroll = ScrollKeeper(self)
        self._chrome = ChromeController(self)
        # Monotonic id of the newest chapter fetch; _display drops results
        # from superseded fetches (see _fetch_and_render).
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
        # A Box of icon buttons reports as `generic`; naming it a toolbar
        # lets AT users move to it as one thing instead of stumbling into
        # a run of unattached buttons.
        a11y.set_role(toolbar, Gtk.AccessibleRole.TOOLBAR)
        set_accessible_label(toolbar, _('Pane controls'))
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

        self._sync_btn = Gtk.ToggleButton(icon_name='scriptura-changes-allow-symbolic')
        self._sync_btn.add_css_class('flat')
        self._sync_btn.add_css_class('pane-action')
        self._sync_btn.set_tooltip_text(_('Following navigation'))
        set_accessible_label(self._sync_btn, _('Follow navigation'))
        self._sync_btn.connect('notify::active', self._on_sync_toggled)
        toolbar.append(self._sync_btn)

        self._chapter_note_btn = Gtk.Button(icon_name='scriptura-document-edit-symbolic')
        self._chapter_note_btn.add_css_class('flat')
        self._chapter_note_btn.add_css_class('pane-action')
        self._chapter_note_btn.set_tooltip_text(_('Chapter note'))
        set_accessible_label(self._chapter_note_btn, _('Chapter note'))
        self._chapter_note_btn.connect(
            'clicked', lambda _b: annotation_dialogs.show_chapter_note(self))
        toolbar.append(self._chapter_note_btn)

        toolbar.append(self._search.build_button())

        self._copy_chapter_btn = Gtk.Button(icon_name='scriptura-edit-copy-symbolic')
        self._copy_chapter_btn.add_css_class('flat')
        self._copy_chapter_btn.add_css_class('pane-action')
        self._copy_chapter_btn.set_tooltip_text(_('Copy chapter'))
        set_accessible_label(self._copy_chapter_btn, _('Copy chapter'))
        self._copy_chapter_btn.connect('clicked', self._on_copy_chapter)
        toolbar.append(self._copy_chapter_btn)

        # The chapter on screen, read aloud. Two sources feed this one
        # control: the Berean Standard Bible's own public-domain reading,
        # which covers every chapter of the canon, and Crossway's psalm
        # episodes, which cover the Psalms in any translation. One button,
        # because they answer the same request and a toolbar carrying two
        # play icons would ask the reader to tell them apart at a glance.
        # It lives with the other pane actions and appears only when there is
        # something behind it — a Bible pane has no strip of its own to
        # reveal, and adding one would be chrome every book had to carry.
        # The chapter read aloud, and the listening pill that governs it —
        # widgets, players and all — live on ReadingAudio (audio_surfaces.py).
        # It builds its headphones into this toolbar; the pane keeps only the
        # pill's placement, in the chrome overlay below.
        self._audio = ReadingAudio(self, toolbar)

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
        prev_day_btn = Gtk.Button(icon_name='scriptura-go-previous-symbolic')
        prev_day_btn.add_css_class('flat')
        prev_day_btn.set_tooltip_text(_('Previous day'))
        set_accessible_label(prev_day_btn, _('Previous day'))
        prev_day_btn.connect('clicked', lambda _: self._go_devotional_day(-1))
        self._date_label = Gtk.Label(label='', xalign=0.5, hexpand=True)
        self._date_label.add_css_class('heading')
        next_day_btn = Gtk.Button(icon_name='scriptura-go-next-symbolic')
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
        date_nav.add_css_class('devotional-date-nav')
        self._date_nav = date_nav
        # The day's reading on the date row lives on DevotionalAudio
        # (audio_surfaces.py); it builds its own controls into this row.
        self._devot_audio = DevotionalAudio(self, date_nav)

        self._date_nav_revealer = Gtk.Revealer()
        self._date_nav_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._date_nav_revealer.set_transition_duration(200)
        date_nav_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        date_nav_stack.append(date_nav)
        date_nav_stack.append(self._devot_audio.progress)
        self._date_nav = date_nav_stack     # measured for the page strip
        self._date_nav_revealer.set_child(date_nav_stack)
        self._date_nav_revealer.set_reveal_child(False)

        # The pane toolbar auto-hides while reading (scroll down to get it
        # out of the way, scroll up / tap the text / focus a control to
        # bring it back) — see _on_reading_scroll below. SLIDE_UP retracts
        # it upward, sliding OVER the reading page: all pane chrome lives
        # in an overlay band above the text surface, so revealing or hiding
        # it never reallocates the viewport — the reading text is the fixed
        # point everything else moves around.
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

        # The floating chrome band: toolbar + devotional date nav +
        # per-pane search bar, stacked over the top of the reading page
        # (composed into a Gtk.Overlay with the paned below). Opaque via
        # .pane-chrome-band so text scrolling beneath it is masked.
        self._chrome_band = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._chrome_band.add_css_class('pane-chrome-band')
        self._chrome_band.set_valign(Gtk.Align.START)
        self._chrome_band.append(self._toolbar_revealer)
        self._chrome_band.append(self._date_nav_revealer)
        self._toolbar_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._toolbar_separator.add_css_class('pane-toolbar-separator')
        self._chrome_band.append(self._toolbar_separator)

        # How far through the reading used to be a hairline under the toolbar,
        # inset to the reading card's corner radius. It has retired into the
        # pill: a progress line and a player are two answers to one question,
        # and the line only ever lived up here because there was nowhere else
        # to put it. The pill floats at the foot of the reading area — see
        # audio_pill.py, and the overlay assembly below.

        # Per-pane inline search bar (revealed below toolbar). All
        # widgets + state live inside PaneSearch — see pane_search.py.
        self._chrome_band.append(self._search.build_revealer())

        # Ensure the pane itself can be shrunk by the user without UI elements pushing it
        self.set_size_request(150, -1)

        # Native TextView
        self._view = BibleTextView()
        self._view.set_unit_rule(self._mark_current_unit)
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
        self._letter_spacing = settings.get('letter_spacing') or 0.0
        self._font_bold    = settings.get('font_bold')
        self._font_justify = settings.get('font_justify')
        self._text_color   = settings.get(f'text_color_{settings.get("color_scheme") or "default"}')
        self._bg_color     = settings.get(f'reading_bg_{settings.get("color_scheme") or "default"}')
        self._evening_strength = 0.0   # night-light paper shift (window-fed)
        self._css_provider = Gtk.CssProvider()
        self._view.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._update_font_css()

        self._buffer = self._view.get_buffer()

        # The reading column is the app's main content, not a plain text box:
        # naming it DOCUMENT tells AT this is prose to be read, and gives the
        # per-verse state (_announce_verse_state) somewhere to hang. The find
        # bar's steppers are declared to act on it.
        a11y.set_role(self._view, Gtk.AccessibleRole.DOCUMENT)
        set_accessible_label(self._view, _('Reading view'))
        self._search.link_view(self._view)

        # Verse cursor keys. CAPTURE phase, and that is the whole point:
        # GtkTextView claims the arrow keys for its own cursor movement and
        # scrolling, so on the default BUBBLE phase ↑↓←→ never reached this
        # handler at all — the verse cursor and the word tier were dead in
        # the real app while [ and ], which the view does NOT claim, worked
        # fine. Real Orca found it; the unit tests could not, because they
        # call VerseCursor.on_key directly and never exercise the controller.
        #
        # Capturing is safe because the handler is strict about what it
        # owns: it returns False for every key it does not handle, and False
        # again at a chapter edge, so scrolling and every window shortcut
        # still fall through untouched.
        cursor_keys = Gtk.EventControllerKey.new()
        cursor_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        cursor_keys.connect('key-pressed', self._cursor.on_key)
        self._view.add_controller(cursor_keys)

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
        scrolled.set_reading_width(int(settings.get('reading_width') or 540))
        scrolled.on_height_change = self._on_viewport_resized
        scrolled.on_margins_change = self._on_reading_margins_changed
        self._reading_scroll = scrolled

        # The reading-scroll handler and its intent tracking live on
        # ScrollKeeper (self._scroll); the value-changed signal is routed
        # there through the pane delegate.
        scrolled.get_vadjustment().connect('value-changed', self._on_reading_scroll)

        # User-intent scroll detection. value-changed alone can't tell the
        # reader's hand from layout churn: lazy validation keeps correcting
        # line-height estimates (and with them the adjustment) long after a
        # render, past any fixed ignore window. Only input says "the reader
        # moved": wheel/touchpad, scroll keys, or a scrollbar drag. Scroll
        # handling (in ScrollKeeper) treats value changes without recent input
        # as churn.
        wheel = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES)
        wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        wheel.connect('scroll', self._on_wheel_input)
        scrolled.add_controller(wheel)
        scroll_keys = Gtk.EventControllerKey.new()
        scroll_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll_keys.connect('key-pressed', self._on_scroll_key_input)
        scrolled.add_controller(scroll_keys)
        sb_drag = Gtk.GestureClick.new()
        sb_drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        sb_drag.connect('pressed', lambda *_a: self._scroll._on_scrollbar_pressed())
        sb_drag.connect('released', self._on_scrollbar_released)
        sb_drag.connect('cancel', self._on_scrollbar_released)
        scrolled.get_vscrollbar().add_controller(sb_drag)

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
        # Last verses/footnotes passed to _display, reused for re-theming
        # without IO.
        self._rendered_verses = None
        self._rendered_notes = {}
        self._lex_panel = LexiconPanel(
            on_word_study_navigate=on_word_study_navigate,
            on_first_show=self._init_outer_paned_position,
            on_show_peek=self.show_anchored_peek,
            on_dismiss_peek=self._dismiss_lexicon_peek,
            on_open_verse=on_open_verse,
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
        self._content_stack.add_named(self._genealogy.widget, 'genealogy')
        self._content_stack.add_named(self._interlinear.widget, 'interlinear')
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
        # The chrome band floats in a Gtk.Overlay, so its reveal/hide can
        # never move the text. Its steady height is reserved as a constant
        # top margin on the page card (_sync_view_top_margin), so the band
        # occupies its own strip above the card — visually identical to
        # the old in-flow layout when revealed.
        chrome_overlay = Gtk.Overlay(vexpand=True)
        chrome_overlay.set_child(self._lex_paned)
        chrome_overlay.add_overlay(self._chrome_band)
        # The listening pill floats in the same overlay, at the foot: it is
        # summoned, it persists while there is something to control, and it
        # never moves the text.
        chrome_overlay.add_overlay(self._audio.pill)
        self.append(chrome_overlay)
        self._sync_view_top_margin()
        self._apply_reading_page_edge()

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
        motion.connect('leave', lambda _c: self._on_view_leave())
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
            is_chapter_keyed or self._is_catena or self._is_imagery
            or self._is_interlinear)
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
        elif (self._is_catena or self._is_imagery or self._is_archaeology
                or self._is_genealogy or self._is_interlinear):
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
        self._scroll._on_reading_scroll(adj)
        # Scroll-driven, so it follows the eye rather than the last click.
        # Cheap: a comparison unless the unit actually changed.
        self._update_current_unit()

    def _set_chrome_revealed(self, reveal):
        self._chrome.set_revealed(reveal)

    def _animate_page_strip(self):
        self._chrome.animate_strip()

    def _on_viewport_resized(self):
        self._scroll._on_viewport_resized()

    def _schedule_anchor_capture(self, ms=250):
        self._scroll._schedule_anchor_capture(ms)

    def _on_wheel_input(self, controller, dx, dy):
        return self._scroll._on_wheel_input(controller, dx, dy)

    def _on_scroll_key_input(self, controller, keyval, keycode, state):
        return self._scroll._on_scroll_key_input(controller, keyval, keycode, state)

    def _on_scrollbar_released(self, *args):
        self._scroll._on_scrollbar_released(*args)

    def _mark_programmatic_scroll(self, ms=400):
        self._scroll._mark_programmatic_scroll(ms)

    def _sync_view_top_margin(self):
        self._chrome.sync_view_top_margin()

    def _reveal_chrome(self):
        self._chrome.reveal()

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
        # One source of truth for "which content source is this": the content
        # registry (content.py), instead of re-walking each bridge predicate
        # here. The registry's membership predicates are disjoint, so exactly
        # one key matches.
        tk = content.type_key(m)
        self._is_catena = tk == 'catena'
        self._is_imagery = tk == 'imagery'
        self._is_archaeology = tk == 'archaeology'
        self._is_genealogy = tk == 'genealogy'
        self._is_interlinear = tk == 'interlinear'
        is_ebible = tk == 'ebible'
        if self._is_catena:
            self._module_type = 'Historical Commentaries'
        elif self._is_imagery:
            self._module_type = 'Bible Imagery'
        elif self._is_archaeology:
            self._module_type = 'Scripture in Stone'
        elif self._is_genealogy:
            self._module_type = 'The Book of Generations'
        elif self._is_interlinear:
            self._module_type = 'Interlinear'
        elif is_ebible:
            self._module_type = 'Biblical Texts'
        else:
            self._module_type = sword_bridge.module_type(m)
        self._is_devotional = (
            not self._is_catena and not self._is_imagery
            and not self._is_archaeology and not self._is_genealogy
            and not self._is_interlinear
            and not is_ebible
            and sword_bridge.is_devotional_module(m))
        self._is_genbook = (
            not self._is_catena and not self._is_imagery
            and not self._is_archaeology and not self._is_genealogy
            and not self._is_interlinear
            and not is_ebible
            and self._module_type == 'Generic Books')
        # The active content strategy. Card modes are registry-keyed; the
        # text-view modes are picked by the finer flags, in the same order
        # the render dispatch used to test them.
        card = self._contents.get(tk)
        if card is not None:
            self._content = card
        elif self._is_devotional:
            self._content = self._text_content['devotional']
        elif self._is_genbook:
            self._content = self._text_content['genbook']
        elif self._is_verse_navigable():
            self._content = self._text_content['bible']
        else:
            self._content = self._text_content['unsupported']

    def _content_child(self):
        """Which content-stack child the current module renders into."""
        return self._content.stack_child

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
        if self._is_catena or self._is_imagery or self._is_interlinear:
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
        if self._is_catena or self._is_imagery or self._is_interlinear:
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
            family_decl = READING_SERIF_STACK
        else:
            family_decl = f"'{self._font_family}', serif"
        dark = Adw.StyleManager.get_default().get_dark()
        # Reading "paper" surface. Must stay OPAQUE so scrolling repaints a fill
        # (the scroll-trail fix). A user-chosen paper (preset or custom) wins;
        # otherwise a soft warm paper in light mode, and in dark mode the static
        # .bible-view @view_bg_color rule (surface=None, no override needed).
        if self._bg_color:
            surface = self._bg_color
        elif not dark:
            surface = '#f7f4ee'
        else:
            surface = None
        # Evening paper (opt-in, follows Night Light): warm/dim the resolved
        # surface. Display-time only — stored paper preferences are never
        # touched. The dark default (surface=None → @view_bg_color) blends
        # from its concrete Adwaita value so dark mode shifts too.
        if self._evening_strength > 0.0:
            import night_light
            surface = night_light.dusk_blend(
                surface or ('#1e1e1e' if dark else '#f7f4ee'),
                self._evening_strength)
        # Ink: an explicit user choice wins; otherwise auto-derive from the paper
        # (warm-light on dark papers, warm dark sharing the paper's hue on light).
        if self._text_color:
            ink = self._text_color
        else:
            ink = auto_reading_ink(surface or ('#1e1e1e' if dark else '#f7f4ee'))
        # The whole buffer reflows when this loads — adjustment churn from
        # it must not flip the auto-hiding toolbar.
        self._mark_programmatic_scroll()
        # Tracking in em, not px, so it holds its proportion when the reader
        # changes size — 0.06em is 0.06em at 10pt and at 20pt, where a px
        # value would be tight type at one end and loose at the other.
        # Omitted entirely at 0, so a reader who has not asked for tracking
        # gets the face exactly as its designer set it.
        tracking = (f"letter-spacing: {self._letter_spacing:.2f}em; "
                    if self._letter_spacing else '')
        css = (f"textview {{ font-family: {family_decl}; "
               f"font-size: {self._font_size}pt; "
               f"font-weight: {weight}; "
               f"line-height: {self._line_spacing}; "
               f"{tracking}"
               f"color: {ink}; }}")
        # Higher specificity than the static .bible-view rule, so when emitted
        # the chosen/derived surface wins.
        if surface:
            css += (" textview.bible-view, textview.bible-view text "
                    f"{{ background-color: {surface}; }}")
        self._css_provider.load_from_data(css.encode())
        # The pill is cast from the same paper and ink. Its own provider,
        # because this one is on the text view and would never reach a
        # sibling in the overlay.
        self._audio.pill.set_appearance(
            surface or ('#1e1e1e' if dark else '#f7f4ee'), ink)
        # The focus veil is the same paper, laid back over the text it quiets,
        # so it reads as unlit page rather than as a grey wash.
        self._view.set_focus_paper(
            surface or ('#1e1e1e' if dark else '#f7f4ee'),
            FOCUS_DIM if self._focus_unit else 0.0)
        # Resize the embedded artifact markers live with the reading font — no
        # re-render needed (the text reflows via the CSS above on its own).
        px = self._artifact_icon_px()
        for img in getattr(self, '_artifact_markers', ()):
            img.set_pixel_size(px)
        just = Gtk.Justification.FILL if self._font_justify else Gtk.Justification.LEFT
        self._view.set_justification(just)
        # Poetry hang/step distances are em-derived — track the font size.
        self._sync_poetry_tags()
        # Font size / line spacing changed the layout the highlight bands are
        # measured against — repaint them.
        self._view.queue_draw()

    def set_evening_strength(self, strength):
        """Evening-paper shift strength (0 = neutral). Tone-only: reloads
        the font CSS with a blended surface; no re-render, no scroll."""
        if strength == self._evening_strength:
            return
        self._evening_strength = strength
        self._update_font_css()

    def set_appearance(self, **kwargs):
        if 'font_size'    in kwargs: self._font_size    = kwargs['font_size']
        if 'font_family'  in kwargs: self._font_family  = kwargs['font_family']
        if 'line_spacing' in kwargs: self._line_spacing = kwargs['line_spacing']
        if 'letter_spacing' in kwargs: self._letter_spacing = kwargs['letter_spacing']
        if 'font_bold'    in kwargs: self._font_bold    = kwargs['font_bold']
        if 'font_justify' in kwargs: self._font_justify = kwargs['font_justify']
        if 'text_color'   in kwargs: self._text_color   = kwargs['text_color']
        if 'bg_color'     in kwargs: self._bg_color     = kwargs['bg_color']
        self._update_font_css()
        # The card-mode documents scale with the same reading font size
        # (only archaeology and catena actually re-scale; the rest no-op).
        for content_mode in self._contents.values():
            content_mode.apply_font_size(self._font_size)

    def set_font_size(self, size):
        self.set_appearance(font_size=size)

    def set_reading_width(self, px):
        self._reading_scroll.set_reading_width(int(px))

    def set_reading_margin(self, px):
        self._reading_scroll.set_base_margin(px)

    # ── Presentation-mode accessors ───────────────────────────────────────────
    def current_passage(self):
        """(book, chapter, translation, verses) for this pane's current chapter,
        or None when it isn't showing a navigable Bible/commentary chapter.
        `book` stays canonical English (the cross-chapter navigator and SWORD
        keys need it); `verses` is the same [(verse, source_html), …] the
        reading view drew, so presentation reuses the fetched text without
        re-hitting SWORD."""
        if not self._is_verse_navigable() or not self._rendered_verses:
            return None
        # Bibles only — a commentary returns the same multi-verse block for
        # every verse in a section, which would project as a wall of repeats.
        if self._module_type != 'Biblical Texts':
            return None
        # An out-of-coverage chapter (e.g. an NT-only module on an OT book) is
        # kept in _rendered_verses as empty entries; don't present a blank.
        if not any(re.sub(r'<[^>]+>', '', str(h)).strip()
                   for _v, h in self._rendered_verses):
            return None
        translation = sword_bridge.display_name(self._module)
        return self._book, self._chapter, translation, self._rendered_verses

    def current_verse(self):
        """The verse the reader is focused on (or None), so presentation can
        open on the page holding it rather than always at the chapter top."""
        return self._selected_verse

    def reading_appearance(self, evening_strength=0.0):
        """The effective paper / ink / serif this pane reads with, so the
        presentation surface can mirror it (opaque bg — a fullscreen slide
        can't fall through to @view_bg_color the way the docked view does).
        `evening_strength` optionally applies the Night Light dusk blend
        (the Today page follows it; presentation deliberately doesn't) —
        auto ink then re-derives from the blended paper, matching
        _update_font_css."""
        dark = Adw.StyleManager.get_default().get_dark()
        if self._bg_color:
            surface = self._bg_color
        elif not dark:
            surface = '#f7f4ee'
        else:
            surface = '#1e1e1e'
        if evening_strength > 0.0:
            import night_light
            surface = night_light.dusk_blend(surface, evening_strength)
        ink = self._text_color or auto_reading_ink(surface)
        family = (READING_SERIF_STACK if self._font_family == 'serif'
                  else f"'{self._font_family}', serif")
        return {
            'surface': surface, 'ink': ink, 'family': family,
            'bold': self._font_bold, 'font_size': self._font_size,
        }

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
        btn.set_icon_name('scriptura-changes-prevent-symbolic' if locked else 'scriptura-changes-allow-symbolic')
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
        # No re-render: the toggle changes only which TextTags exist, never
        # the text itself — Strong's tags are applied over the finished
        # buffer (step 5 of _display). Tag/untag in place so the reading
        # position physically cannot move. Non-Bible content never carries
        # Strong's tags, so there is nothing to do for it at all.
        if (self._rendered_verses is None
                or self._module_type != 'Biblical Texts'):
            return
        if enabled:
            self._tag_strong_words_in_place()
        else:
            self._remove_strong_tags()

    def _tag_strong_words_in_place(self):
        """Apply Strong's/morph/phrase tags to the already-rendered chapter,
        verse by verse, using the source HTML kept in _rendered_verses."""
        if not self._on_word_click:
            return
        table = self._buffer.get_tag_table()
        for verse, html in self._rendered_verses:
            tag = table.lookup(f'vnum_{verse}')
            if tag is None:
                continue
            start = self._buffer.get_start_iter()
            if not start.has_tag(tag) and not start.forward_to_tag_toggle(tag):
                continue
            end = start.copy()
            end.forward_to_tag_toggle(tag)
            self._tag_strong_words(start, end, html)

    def _remove_strong_tags(self):
        """Drop all Strong's-related tags (and the hover underline) from the
        buffer — removing them from the tag table detaches them from the
        text and keeps the table from accumulating stale entries."""
        self._clear_strg_hover()
        table = self._buffer.get_tag_table()
        to_remove = []

        def _collect(tag, _user_data):
            name = tag.get_property('name') or ''
            if name.startswith(('strg:', 'morph:', 'phrase:')):
                to_remove.append(tag)

        table.foreach(_collect, None)
        for tag in to_remove:
            table.remove(tag)

    def _capture_scroll_anchor(self):
        return self._scroll._capture_scroll_anchor()

    def _apply_scroll_anchor(self, anchor):
        return self._scroll._apply_scroll_anchor(anchor)

    def _find_topmost_visible_verse(self):
        return self._scroll._find_topmost_visible_verse()

    def _resolve_present_verse(self, verse_num):
        return self._scroll._resolve_present_verse(verse_num)

    def _scroll_to_verse_silent(self, verse_num):
        return self._scroll._scroll_to_verse_silent(verse_num)

    # Forwarding to ScrollKeeper so the many render / navigation call sites
    # that read or clear the reading locus (and bump the render generation on
    # every buffer rebuild) are untouched by the extraction.
    @property
    def _reading_anchor(self):
        return self._scroll._reading_anchor

    @_reading_anchor.setter
    def _reading_anchor(self, value):
        self._scroll._reading_anchor = value

    @property
    def _anchor_seq(self):
        return self._scroll._anchor_seq

    @_anchor_seq.setter
    def _anchor_seq(self, value):
        self._scroll._anchor_seq = value

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
                                    'devref:', 'fnote:')

    def _clear_chapter_scoped_tags(self):
        # Every buffer rebuild passes through here — invalidate any
        # in-flight scroll-anchor corrections aimed at the old layout.
        self._anchor_seq += 1
        # The keyboard cursor holds buffer offsets and a cache of the vnum_
        # tags being removed just below, both of which describe the outgoing
        # buffer. Same seam, same reason.
        self._cursor.on_render()
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
        self._audio.sync()
        # Chapter audio stops above on every render. The devotional player must
        # too when the pane is no longer a devotional — otherwise Spurgeon's
        # reading plays on after a switch to a Bible, its controls gone with
        # the date bar. A devotional render stops/re-offers it below, via
        # _fetch_and_render_devotional → the devotional surface's sync.
        if not self._is_devotional:
            self._devot_audio.stop()
        self._content_stack.set_visible_child_name(self._content_child())
        # One dispatch: the active PaneContent renders itself. Card modes
        # render into their own stack child (verse-synced from the partnered
        # Bible); the text-view modes (Bible/commentary core, devotional,
        # generic book, unsupported placeholder) render into 'text'.
        self._content.render()

    def _render_bible_chapter(self):
        """Async-load the current verse-keyed chapter (Bible or commentary)
        and hand the verses + footnotes to _display."""
        book, chapter, module = self._book, self._chapter, self._module
        # Last-write-wins across overlapping fetches. The location guard in
        # _display can't catch two renders of the SAME chapter (e.g. rapid
        # footnote toggling faster than the fetch): the first consumed the
        # scroll restore, the late one found none and jumped to the chapter
        # start. Only the most recently requested render may display — the
        # runner's per-pane key carries that; a failed load keeps the
        # current text (details in the log).
        def fetch(_task):
            if ebible_bridge.is_ebible_module(module):
                verses = ebible_bridge.load_chapter(module, book, chapter)
                notes = ebible_bridge.chapter_footnotes(module, book, chapter)
                heads = {}
            else:
                verses = sword_bridge.load_chapter(module, book, chapter)
                notes = sword_bridge.chapter_footnotes(module, book, chapter)
                heads = sword_bridge.chapter_headings(module, book, chapter)
            return verses, notes, heads

        task = tasks.submit(
            f'chapter:{id(self)}', fetch,
            lambda res: self._display(res[0], book, chapter, module,
                                      res[1], task, headings=res[2]),
            on_error=lambda _exc: None)

    def _show_status_page(self, icon, title, description, action=None):
        self._cancel_all_flashes()
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
            'scriptura-dialog-information-symbolic', self._module,
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
            'scriptura-dialog-password-symbolic', self._module,
            _('This module’s content isn’t readable — the cipher key may be '
              'incorrect.'),
            action=action)

    def _display_empty_chapter(self, book, chapter):
        """Show a friendly hint when the current module has no content
        for the requested book/chapter — typically NT-only modules
        (SBLGNT, MorphGNT) navigated to an OT passage, or vice versa."""
        if book in sword_bridge.DEUTEROCANON:
            if sword_bridge.module_has_book(self._module, book):
                # The module carries the book but prints nothing here.
                # KJVA's Additions to Esther 1-9 are the case: single-verse
                # '…' placeholders, because that material is set inside
                # Esther itself.
                body = _('{module} has no text under this chapter.').format(
                    module=self._module)
            else:
                # Not a coverage gap. Saying the module "follows a canon of
                # 66 books" was worse than vague — it is false of Wycliffe,
                # which carries nine of these books and simply lacks this
                # one. Name the book, not the canon.
                body = _('%s isn’t in this translation.') % book_label(book)
        else:
            body = _('{module} doesn’t include this passage. Some modules cover '
                     'only the Old or New Testament — pick a Bible with full '
                     'coverage.').format(module=self._module)
        self._show_status_page(
            'scriptura-dialog-information-symbolic', f'{book_label(book)} {chapter}',
            body,
            action=(_('Choose another module'),
                    lambda: self._picker.menu_button.popup()))
        self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)

    def _fetch_and_render_devotional(self):
        module = self._module
        date_obj = self._devotional_date
        self._date_label.set_text(date_obj.strftime('%B %-d, %Y'))
        self._devot_audio.sync()

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

    def stop_audio(self):
        """Silence both spoken-reading players. Called when the pane is hidden
        (split collapsed, narrow-mode pane switch) so audio never plays on from
        a surface the reader can no longer see or reach the controls on."""
        self._audio.stop()
        self._devot_audio.stop()

    def set_show_audio(self, _active):
        """Re-evaluate both spoken-reading controls after the Advanced toggle.
        Each sync consults the setting and either offers or withdraws its
        control for the pane's current content, so re-running them is enough
        in both directions."""
        self._audio.sync()
        self._devot_audio.sync()

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

    def _insert_lineage_marker(self, verse):
        """A small clickable mark beside a verse whose people the genealogy
        charts draw, opening The Book of Generations at that line. Same shape
        and same machinery as the artifact marker — an embedded icon rather
        than a font glyph, so it renders in every reading font."""
        self._buffer.insert(self._buffer.get_end_iter(), ' ')
        anchor = self._buffer.create_child_anchor(self._buffer.get_end_iter())
        img = Gtk.Image.new_from_icon_name('scriptura-genealogy-symbolic')
        img.set_pixel_size(self._artifact_icon_px())
        self._artifact_markers.append(img)
        btn = Gtk.Button(child=img)
        btn.add_css_class('flat')
        btn.add_css_class('artifact-marker')
        btn.set_can_focus(True)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(_('This line is drawn — open The Book of '
                               'Generations'))
        set_accessible_label(btn, _('Line of descent'))
        if self._on_open_lineage:
            btn.connect(
                'clicked',
                lambda *_a, v=verse: self._on_open_lineage(
                    self, self._book, self._chapter, v))
        self._view.add_child_at_anchor(btn, anchor)

    def _display(self, verses, book, chapter, module, notes=None, task=None,
                 headings=None):
        if book != self._book or chapter != self._chapter or module != self._module:
            return GLib.SOURCE_REMOVE
        if task is not None and not task.is_current():
            return GLib.SOURCE_REMOVE  # superseded by a newer fetch
        # The rebuild collapses and re-grows the adjustment; none of that
        # is the reader scrolling.
        self._mark_programmatic_scroll()
        self._rendered_verses = verses
        # A new render is a new buffer: the remembered unit refers to the old
        # one. Without this, moving to a chapter whose first unit starts at
        # the same verse hits the "unchanged" early-return and the mark is
        # never applied — and nearly every ESV/LEB chapter opens a unit at
        # verse 1.
        self._current_unit = None
        if headings is not None:
            # Kept so a re-theme render (which re-runs _display with no fetch)
            # doesn't drop the headings the way it would a bare parameter.
            self._rendered_headings = headings
        # The re-theming path re-calls _display without notes; reuse the
        # set from the original fetch.
        if notes is None:
            notes = self._rendered_notes or {}
        else:
            self._rendered_notes = notes

        dark = Adw.StyleManager.get_default().get_dark()
        annos = annotations.get_annotations(module, book, chapter)
        is_commentary = self._module_type == 'Commentaries'
        # Verses in this chapter that a Scripture-in-Stone artifact references,
        # so we can drop a subtle clickable marker beside them (Bibles only).
        art_verses = (set() if is_commentary
                      else archaeology_bridge.verses_with_artifacts(book, chapter))
        # Verses whose people the genealogy table draws a line from. The mark
        # goes on the VERSE, never on each name: in Genesis 5 or Matthew 1 a
        # mark per name marks every line on the page, which is noise.
        gen_verses = (set() if is_commentary
                      else genealogy_bridge.marker_verses(book, chapter))
        self._artifact_markers = []  # rebuilt below; old ones died with set_text('')

        self._cancel_all_flashes()
        # Before the buffer empties: hold the position the allocation's clamp
        # is about to take. Only where a restore is coming — a navigation
        # means to land somewhere else, and a hold would fight it.
        if (self._restore_anchor is not None
                or self._restore_top_verse is not None):
            self._reading_scroll.hold_scroll()
        self._buffer.set_text('')
        self._clear_chapter_scoped_tags()
        self._chapter_footnotes = {}
        # Whether this chapter carries headings _HEADING_TAG cannot govern.
        # Set below, per verse, from the source markup.
        self._rendered_inline_titles = False

        # Coverage check — every verse in `verses` may be empty if the
        # module doesn't include this book/chapter (e.g. SBLGNT is NT
        # only; navigating to Psalms returns the right verse_max but
        # all empty content). Show a friendly empty state instead of
        # rendering a chapter heading + bare verse numbers.
        # KJVA marks material printed elsewhere with a bare '…' — every
        # verse of Additions to Esther 1-9 is one, because those additions
        # are set inside Esther. Stripping it here is what keeps the reader
        # from meeting a chapter heading over a single ellipsis. Individual
        # '…' verses inside a real chapter (Additions to Esther 10) are
        # untouched; only a chapter that is nothing else counts as empty.
        all_empty = not any(
            re.sub(r'<[^>]+>', '', str(h)).strip(' \t\r\n…') for _, h in verses)

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
                # No restore will run on this path to end the hold for us.
                self._reading_scroll.release_scroll_hold()
                return GLib.SOURCE_REMOVE

        if all_empty:
            self._display_empty_chapter(book, chapter)
            self._reading_scroll.release_scroll_hold()
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
            heading_color = theme_ink(dark)['_ink_heading']
            # Single trailing newline (not two): line_spacing 1.6 already gives
            # ample separation, and a blank line here left an oversized top gap.
            heading = (f'<span size="x-large" weight="bold" '
                       f'foreground="{heading_color}" letter_spacing="600"'
                       f'{self._numeral_ff()}>'
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

        # Footnote marker letters run a, b, c… through the whole chapter
        # (print-Bible style), not restarting per verse.
        fn_letter_idx = 0

        # Poetry-line carry across the verse loop: OSIS lines cross verse
        # boundaries (a verse can leave its last line open; the next
        # verse's text continues it). See _resolve_poetry_markup.
        poetry_state = {'open': None, 'at_ls': True}

        # False until a verse block has actually been written, so the first
        # section heading of a chapter doesn't stack a blank line on top of
        # the chapter heading's own trailing newline.
        wrote_a_block = False

        for start_v, end_v, html in iterable:
            plain = re.sub(r'<[^>]+>', '', str(html)).strip()

            # Commentary: skip verses with no meaningful content
            if is_commentary and len(plain) < 20:
                continue

            # Section heading, where the module supplies one for this verse.
            # It opens the block it titles, so it is inserted before the verse
            # number — but ALSO before start_mark, deliberately: the vnum_ tag
            # spans start_mark→end, and a heading inside that range makes the
            # heading part of the verse. That put the current-verse indicator
            # on the heading's first characters, would paint a highlight band
            # across it, and threw _verse_ranges' offsets (vtext_start lands
            # len(str(v))+2 chars in, i.e. inside the heading text).
            # Commentaries are excluded: their own "Verse N" headers already
            # divide the text.
            # Always inserted, whatever the setting says: the headings-off
            # state is _HEADING_TAG's `invisible`, not their absence, so the
            # toggle need not re-render. Keeping them in the buffer also keeps
            # _verse_ranges' offsets identical between the two states.
            if not is_commentary:
                for head in self._rendered_headings.get(start_v, ()):
                    self._insert_section_heading(head, wrote_a_block)

            if _renders_inline_title(html):
                self._rendered_inline_titles = True

            start_mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), True)
            r = _VerseRender(start_v, end_v, html, is_commentary)
            r.start_mark = start_mark
            r.anno = annos.get(str(start_v), {})
            r.has_artifact = start_v in art_verses
            r.has_lineage = start_v in gen_verses

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
                v_num_markup = (f'<span foreground="gray" size="small" '
                                f'weight="bold" rise="2500"{self._numeral_ff()}>'
                                f' {start_v} </span>')
                self._buffer.insert_markup(self._buffer.get_end_iter(), v_num_markup, -1)

            text_start_mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), True)
            r.text_mark = text_start_mark

            # 2. Verse text
            if is_commentary:
                # Commentaries use a segmented insertion so cross-refs
                # like <reference osisRef="Bible:Phil.3.4">…</reference>
                # become clickable styled links carrying a devref tag.
                # Plain segments between refs still go through
                # _html_to_markup so <hi>, <i>, etc. keep working.
                src_html = str(html)
                vnotes = {}
                if notes.get(start_v):
                    # A grouped section renders one identical block for its
                    # whole verse range, so its anchors — and note bodies —
                    # are the same for every verse; the start verse's set
                    # serves the group.
                    vnotes = {n: (t, b) for n, t, b in notes[start_v]}
                    src_html = _NOTE_ANCHOR_RE.sub(
                        lambda m: f'[[FN_{m.group(1)}]]', src_html)
                fn_letter_idx = self._insert_commentary_body(
                    src_html, dark, start_v, vnotes, fn_letter_idx)
                self._buffer.insert(self._buffer.get_end_iter(), '\n')
            else:
                # Footnote anchors → [[FN_n]] tokens before the generic tag
                # strip in _html_to_markup (which otherwise removes them).
                # Always substituted, whatever the setting says: the markers-off
                # state is the shared fn_marker tag's `invisible`, not their
                # absence, so the toggle need not re-render. Poetry line
                # milestones get the same token protection.
                src_html = _poetry_tokens(str(html))
                vnotes = {}
                if notes.get(start_v):
                    vnotes = {n: (t, b) for n, t, b in notes[start_v]}
                    src_html = _NOTE_ANCHOR_RE.sub(
                        lambda m: f'[[FN_{m.group(1)}]]', src_html)
                v_text_markup = _html_to_markup(
                    src_html, dark,
                    divine_smallcaps=self._smallcaps_divine,
                    show_headings=self._show_headings)
                if self._smallcaps_divine:
                    v_text_markup = _smallcap_divine_literals(v_text_markup)
                # Poetry tokens → line breaks + per-line indent levels.
                # Before the footnote substitution, so the plain-text
                # offsets it records are final.
                v_text_markup, poetry_lines = _resolve_poetry_markup(
                    v_text_markup, poetry_state)
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
                cap_index = None
                if start_v == 1:
                    split = _dropcap_split(v_text_markup)
                    if split:
                        before, letter, after = split
                        v_text_markup = (
                            f'{before}{_DROPCAP_SPAN}{letter}</span>{after}')
                        cap_index = len(before)   # markup offset for now
                # Tokens → superscript marker letters, after the drop-cap
                # transform so the recorded plain-text offsets are final.
                fn_markers = []
                if vnotes:
                    v_text_markup, fn_markers, fn_letter_idx = (
                        _substitute_footnote_markers(
                            v_text_markup, vnotes, dark, fn_letter_idx))
                # Where the cap landed in the finished text. Re-found on the
                # final markup, after the footnote markers went in, so a marker
                # ahead of it can't shift the offset out from under us.
                if cap_index is not None:
                    cap_index = _dropcap_index(v_text_markup, cap_index)
                # A verse ending on a closed poetry line already breaks —
                # the inter-verse space would dangle at the next line start.
                sep = '' if v_text_markup.endswith('\n') else ' '
                try:
                    self._buffer.insert_markup(self._buffer.get_end_iter(), v_text_markup + sep, -1)
                except Exception:
                    self._buffer.insert(self._buffer.get_end_iter(), plain + ' ')
                    fn_markers = []  # fallback text has no marker letters
                    poetry_lines = {}
                    cap_index = None  # the plain fallback carries no cap
                r.cap_index = cap_index
                r.fn_markers = fn_markers
                r.vnotes = vnotes
                r.poetry_lines = poetry_lines

            # 3. Every mark this verse wears, in one declarative pass.
            self._decorate_verse(r)

            self._buffer.delete_mark(start_mark)
            self._buffer.delete_mark(text_start_mark)
            wrote_a_block = True

        if self._target_verse is not None:
            # The target arrives in app-space (KJV) numbering; the rendered
            # verse numbers are the module's own. Translate where the module
            # is versification-mapped (no-op otherwise), then resolve to a
            # rendered verse up front so the indicator and the scroll agree
            # when the target is an inner verse of a bridge.
            v = sword_bridge.map_target_verse(
                self._module, self._book, self._chapter, self._target_verse)
            v = self._resolve_present_verse(v)
            self._target_verse = None
            self._restore_top_verse = None
            self._restore_anchor = None
            self._reading_anchor = None
            # A navigation that arrived mid-rebuild outranks the restore the
            # hold was taken for. Let it go now rather than fight the landing
            # until the safety timer expires.
            self._reading_scroll.release_scroll_hold()
            # Navigation to a specific verse — mark it as the active
            # verse so the current-verse indicator sits on it after
            # the scroll lands.
            self._selected_verse = v
            self._set_current_verse_indicator(v)
            GLib.idle_add(self._scroll_to_verse, v)
        elif self._restore_anchor is not None:
            anchor = self._restore_anchor
            self._restore_anchor = None
            GLib.idle_add(self._restore_then_release,
                          self._apply_scroll_anchor, anchor)
        elif self._restore_top_verse is not None:
            v = self._restore_top_verse
            self._restore_top_verse = None
            GLib.idle_add(self._restore_then_release,
                          self._scroll_to_verse_silent, v)
        else:
            # Belt and braces: scroll_to_iter's pending scroll can be
            # dropped during a buffer swap (observed: navigation from a
            # deep scroll landed at the clamp, not the top — pre-existing
            # even before the anchor work). Position 0 needs no layout
            # validation, so set it directly as well.
            self._reading_scroll.get_vadjustment().set_value(0)
            self._view.scroll_to_iter(self._buffer.get_start_iter(), 0.0, False, 0, 0)
            # Fresh chapter render with no specific target — the
            # previous chapter's active verse is no longer applicable.
            self._selected_verse = None
            self._reading_anchor = None
            self._schedule_anchor_capture(400)
            # New chapter, top of page: starting context, chrome present.
            # (The scroll gate keys off real input, so the deadzone
            # can't reveal it for programmatic scrolls like this one.)
            # Snap the strip open WITHOUT scroll compensation — there is
            # no reading locus to preserve, and a compensated reveal
            # would land the fresh chapter 32px below its top.
            self._reveal_chrome()
            self._sync_view_top_margin()

        # If _selected_verse survived (e.g. user clicked verse 5 in this
        # chapter, then chapter re-rendered for an annotation save), the
        # indicator paint was wiped by set_text('') above — restore it.
        if self._selected_verse is not None:
            self._set_current_verse_indicator(self._selected_verse)

        self._update_chapter_note_indicator()
        # Give the theme-dependent spans and the numerals one owner apiece
        # before the overlay bumps below, which must stay at the top of the
        # table.
        self._adopt_theme_ink(dark)
        self._adopt_numerals(self._oldstyle_nums)
        self._raise_dropcap()
        self._search.apply_highlight()
        # Every verse's body-text spans (created by insert_markup during the
        # render loop) carry an ever-increasing tag priority, which can
        # out-rank the readable-text foreground applied earlier — leaving
        # highlighted text in its light body colour on the tint until a later
        # re-apply flips it dark. Re-assert the overlay foregrounds above all
        # body spans now that the whole chapter (and its tags) exists.
        self._bump_overlay_priorities()
        # A real chapter of Scripture is now on screen (not a commentary,
        # empty, or cipher-locked state — each of those returned earlier):
        # the right context to teach that verses are tappable.
        if self._on_hint and self._module_type == 'Biblical Texts':
            self._on_hint('first_render')
        # Mark the unit the fresh chapter opens on. The render cleared both
        # the tag and `_current_unit`, and until this the mark waited for a
        # scroll — so a reader who opened a chapter and read down it saw
        # nothing marked and nothing quieted. On an idle because the lines
        # have to be validated before a position can be read back. Applying
        # the tag cannot move the text: it carries no visual properties, and
        # the rule and the veil are both painted from it.
        if self._mark_current_unit or self._focus_unit:
            GLib.idle_add(self._update_current_unit)
        return GLib.SOURCE_REMOVE

    def _decorate_verse(self, r):
        """Apply every mark `r`'s verse wears, in `_VERSE_DECORATIONS` order.

        The render loop used to inline these as seven consecutive `if`s, so a
        new per-verse feature meant another branch in the middle of the loop —
        the one place in the file where an ordering mistake is hardest to see
        and most expensive to make.
        """
        for dec in _VERSE_DECORATIONS:
            if dec.on(self, r):
                dec.apply(self, r)

    def _apply_vnum_tags(self, r):
        """Tag the whole block with `vnum_N` for every verse it answers to."""
        buf = self._buffer
        table = buf.get_tag_table()
        start = buf.get_iter_at_mark(r.start_mark)
        end = buf.get_end_iter()
        for v in range(r.start_v, r.end_v + 1):
            name = f'vnum_{v}'
            tag = table.lookup(name) or buf.create_tag(name)
            buf.apply_tag(tag, start, end)

    #: Ascending precedence, and it mirrors how the markup nests: a footnote
    #: marker sits inside red-letter text. Later application wins, so the
    #: innermost span is adopted last. The drop cap is absent on purpose: its
    #: colour is never written into the markup (see `_DROPCAP_SPAN`), so it has
    #: nothing to adopt and `_raise_dropcap` handles its precedence instead.
    _INK_ORDER = ('_ink_heading', '_ink_redletter', '_ink_link')

    #: What `insert_markup` calls the tags it mints for a `foreground=` span.
    #: Adoption considers these and nothing else — see `_adopt_theme_ink`.
    _MARKUP_FG_PREFIX = 'foreground_rgba='

    def _adopt_theme_ink(self, dark):
        """Move the chapter's theme-coloured spans onto tags of our own.

        `insert_markup` names every span it creates after its own attributes
        (`foreground_rgba=rgb(141,130,120)`), so recolouring one in place would
        leave a lying name behind and the next render would mint a second tag
        for the new colour. Each theme-dependent colour is instead re-applied
        as a stable `_ink_*` tag over the same ranges and the parser's tag is
        dropped — which also stops the tag table growing a dead colour tag
        every time the theme flips.

        Matching is by colour, not by name: the same blue arrives from two
        render paths (footnote markers and commentary cross-references) and
        both want one owner. Only tags the markup parser minted are candidates,
        though — a colour is not proof of ownership. The lexicon hover carries
        that same blue by intent, and the drop-cap colour is whatever the
        reader picked in Appearance, so it can collide with any tag we style
        ourselves; matching on colour alone deleted `_strg_hover` on every
        render and would take `_note_marker` or the current-verse indicator
        with it the day someone chose their gold.
        """
        buf = self._buffer
        table = buf.get_tag_table()
        wanted = []
        for name, hexcol in theme_ink(dark).items():
            if name not in self._INK_ORDER:
                continue
            rgba = Gdk.RGBA()
            if rgba.parse(hexcol):
                wanted.append((name, rgba))

        found = {}

        def _collect(tag, _user_data=None):
            name = tag.get_property('name') or ''
            if not name.startswith(self._MARKUP_FG_PREFIX):
                return
            colour = tag.get_property('foreground-rgba')
            for ink_name, rgba in wanted:
                if colour.equal(rgba):
                    found.setdefault(ink_name, []).append(tag)
                    return

        table.foreach(_collect, None)

        for ink_name in self._INK_ORDER:
            tags = found.get(ink_name)
            if not tags:
                continue
            ours = table.lookup(ink_name)
            if ours is None:
                ours = buf.create_tag(ink_name)
            ours.set_property('foreground-rgba',
                              tags[0].get_property('foreground-rgba'))
            for tag in tags:
                # Offsets, not iters: the table is mutated below and a
                # collected range has to survive that.
                for lo, hi in self._tag_ranges(tag):
                    buf.apply_tag(ours, buf.get_iter_at_offset(lo),
                                  buf.get_iter_at_offset(hi))
                table.remove(tag)
            # Above the body spans, for the same priority decay
            # _bump_overlay_priorities exists for.
            ours.set_priority(table.get_size() - 1)

    #: The figure style is one OpenType feature on the chapter heading and on
    #: every verse number. Same adoption as the colours, and for the same
    #: reason: insert_markup names the tag `font_features=onum=1`, after the
    #: value it holds.
    _NUMERAL_TAG = '_numerals'

    def _adopt_numerals(self, oldstyle):
        """Re-tag the numeral spans with `_NUMERAL_TAG` over the same ranges."""
        buf = self._buffer
        table = buf.get_tag_table()
        want = _numeral_features(oldstyle)
        victims = []

        def _collect(tag, _user_data=None):
            if tag.get_property('name') == self._NUMERAL_TAG:
                return
            if (tag.get_property('font-features-set')
                    and tag.get_property('font-features') == want):
                victims.append(tag)

        table.foreach(_collect, None)
        if not victims:
            return
        ours = table.lookup(self._NUMERAL_TAG)
        if ours is None:
            ours = buf.create_tag(self._NUMERAL_TAG)
        ours.set_property('font-features', want)
        for tag in victims:
            for lo, hi in self._tag_ranges(tag):
                buf.apply_tag(ours, buf.get_iter_at_offset(lo),
                              buf.get_iter_at_offset(hi))
            table.remove(tag)

    def _restyle_numerals(self):
        """Switch the figure style on the rendered chapter without rebuilding
        it. False when the tag has never been minted, so the caller can fall
        back to a render — note that is a weaker test than "this buffer has
        numerals": the tag is not chapter-scoped and outlives the chapter that
        adopted it. See `set_oldstyle_numerals` for why that is safe.

        No anchor work, and that was measured rather than assumed: swapping
        the figures moves the reading position 0px on the shipped serif, on
        Noto Serif and on Georgia — the face `_numeral_features` exists for,
        whose own default figures are old-style. The numerals sit in a
        space-padded span of their own, so the new metrics do not reflow the
        line. Re-asserting the anchor here made it worse, not safer: it
        applied a locus captured before the toggle and threw the reader
        2504px up Psalm 119.
        """
        tag = self._buffer.get_tag_table().lookup(self._NUMERAL_TAG)
        if tag is None:
            return False
        tag.set_property('font-features', _numeral_features(self._oldstyle_nums))
        return True

    #: The cap's ink. Same name the `theme_ink` table keys it under, so the
    #: theme flip already knows how to find it — but unlike the other three
    #: this tag is applied by the render rather than adopted from the markup,
    #: because the cap has to keep its size and weight while losing its colour.
    _DROPCAP_TAG = '_ink_dropcap'

    def _apply_dropcap_tag(self, text_start_mark, index):
        """Tag the drop-cap character, `index` characters into the verse text."""
        buf = self._buffer
        base = buf.get_iter_at_mark(text_start_mark).get_offset()
        table = buf.get_tag_table()
        tag = table.lookup(self._DROPCAP_TAG)
        if tag is None:
            tag = buf.create_tag(self._DROPCAP_TAG)
        self._sync_dropcap_ink(tag)
        buf.apply_tag(tag, buf.get_iter_at_offset(base + index),
                      buf.get_iter_at_offset(base + index + 1))

    def _sync_dropcap_ink(self, tag=None):
        """Put the current drop-cap colour on the tag, or take it off.

        `foreground-set` is what carries the toggle: clearing it leaves the
        cap enlarged and bold, wearing the reading colour like any other
        letter, which is exactly the uncoloured state. False when there is no
        cap tag to change, so the caller can fall back to a render — the tag
        outlives its chapter, so that means "no cap has ever been rendered
        here", not "this chapter has none".
        """
        if tag is None:
            tag = self._buffer.get_tag_table().lookup(self._DROPCAP_TAG)
        if tag is None:
            return False
        if self._colored_dropcap:
            dark = Adw.StyleManager.get_default().get_dark()
            tag.set_property('foreground', dropcap_color_hex(dark))
        else:
            tag.set_property('foreground-set', False)
        return True

    def _raise_dropcap(self):
        """Put the cap back on top of the body spans.

        The adoptions above re-prioritise `_ink_redletter`, and in a
        red-letter Bible the cap sits inside the Lord's words — so without
        this the gold would lose to the red on exactly the chapters where
        the illuminated initial matters most.
        """
        table = self._buffer.get_tag_table()
        tag = table.lookup(self._DROPCAP_TAG)
        if tag is not None:
            tag.set_priority(table.get_size() - 1)

    def _tag_ranges(self, tag):
        """(start, end) character offsets of every range `tag` covers."""
        buf = self._buffer
        out = []
        it = buf.get_start_iter()
        if not it.starts_tag(tag) and not it.forward_to_tag_toggle(tag):
            return out
        while True:
            start = it.get_offset()
            if not it.forward_to_tag_toggle(tag):
                out.append((start, buf.get_end_iter().get_offset()))
                return out
            out.append((start, it.get_offset()))
            if not it.forward_to_tag_toggle(tag):
                return out

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

    def _insert_commentary_body(self, html, dark, verse, vnotes, fn_idx):
        """Render a commentary verse, breaking on <reference> tags so
        each cross-reference becomes a clickable styled link carrying
        a devref: tag. The plain segments between references go through
        _html_to_markup so existing emphasis (<hi>, <i>, <q>, etc.)
        keeps working.

        Footnote [[FN_n]] tokens (pre-substituted by _display) become
        superscript markers here. Insertion is segmented, so marker
        offsets are taken against each segment's own start mark — a
        whole-verse base would drift across the styled reference
        insertions. Returns the chapter's next marker-letter index."""
        s = str(html)
        pos = 0

        def insert_plain(seg):
            nonlocal fn_idx
            # strip=False so a trailing space before the reference
            # ("Elijah, " + ref) isn't swallowed by .strip(), which
            # would render as "Elijah,Rom 11:1-5".
            markup = _html_to_markup(seg, dark, strip=False,
                                     show_headings=self._show_headings)
            if not markup:
                return
            fn_markers = []
            if vnotes:
                markup, fn_markers, fn_idx = _substitute_footnote_markers(
                    markup, vnotes, dark, fn_idx)
            seg_mark = self._buffer.create_mark(
                None, self._buffer.get_end_iter(), True)
            try:
                self._buffer.insert_markup(
                    self._buffer.get_end_iter(), markup, -1)
            except Exception:
                self._buffer.insert(
                    self._buffer.get_end_iter(),
                    _FN_TOKEN_RE.sub('', re.sub(r'<[^>]+>', '', seg)))
                fn_markers = []  # fallback text has no marker letters
            if fn_markers:
                self._apply_footnote_tags(verse, fn_markers, vnotes, seg_mark)
            self._buffer.delete_mark(seg_mark)

        for m in self._REF_PATTERN.finditer(s):
            if m.start() > pos:
                insert_plain(s[pos:m.start()])
            osis = m.group(1)
            # Tokens never belong inside a reference's link text; drop any
            # that land there so they can't render literally.
            ref_text = _FN_TOKEN_RE.sub(
                '', re.sub(r'<[^>]+>', '', m.group(2))).strip()
            if ref_text:
                self._insert_ref_segment(ref_text, osis, dark)
            pos = m.end()
        if pos < len(s):
            insert_plain(s[pos:])
        return fn_idx

    def _insert_ref_segment(self, text, osis, dark):
        """Insert one cross-reference: styled text + devref: tag over
        the same range, so _on_left_click's existing devref handler
        routes the click to _on_word_study_navigate → _go_to."""
        color = theme_ink(dark)['_ink_link']
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

    def _heading_tag(self):
        """The shared section-heading tag, carrying the current visibility.
        Headings are rendered whatever the setting says; this decides whether
        they are drawn."""
        table = self._buffer.get_tag_table()
        tag = table.lookup(_HEADING_TAG)
        if tag is None:
            tag = self._buffer.create_tag(_HEADING_TAG)
        tag.set_property('invisible', not self._show_headings)
        return tag

    def _fn_marker_tag(self):
        """The shared marker tag, carrying the current visibility. Markers are
        rendered whatever the setting says; this is what decides whether they
        are drawn."""
        table = self._buffer.get_tag_table()
        tag = table.lookup(_FN_MARKER_TAG)
        if tag is None:
            tag = self._buffer.create_tag(_FN_MARKER_TAG)
        tag.set_property('invisible', not self._show_footnotes)
        return tag

    def _apply_footnote_tags(self, verse, markers, vnotes, text_start_mark):
        """Tag each marker label with fnote:{verse}:{n} (click → peek) and
        stash (type, body, label) for the handler. Offsets from
        _substitute_footnote_markers are relative to text_start_mark."""
        base = self._buffer.get_iter_at_mark(text_start_mark).get_offset()
        table = self._buffer.get_tag_table()
        shared = self._fn_marker_tag()
        for off, n, label in markers:
            name = f'fnote:{verse}:{n}'
            tag = table.lookup(name) or self._buffer.create_tag(name)
            s = self._buffer.get_iter_at_offset(base + off)
            e = self._buffer.get_iter_at_offset(base + off + len(label))
            self._buffer.apply_tag(tag, s, e)
            self._buffer.apply_tag(shared, s, e)
            ftype, body = vnotes[n]
            self._chapter_footnotes[(verse, n)] = (ftype, body, label)

    def _restore_then_release(self, restore, arg):
        """Place the reading position, then end the rebuild's scroll hold.

        Order matters: the hold has to outlive every frame up to and including
        this one, because GTK's collapse of `upper` can arrive after the
        painted frames the restore was scheduled behind."""
        restore(arg)
        self._reading_scroll.release_scroll_hold()
        return GLib.SOURCE_REMOVE

    def _rerender_keeping_place(self):
        """Re-render the current chapter, restoring the exact reading locus
        (pixel anchor; coarse verse fallback) — for toggles whose effect
        is baked into the rendered markup."""
        if not self._is_verse_navigable():
            return  # flag applies whenever a Bible next renders here
        self._restore_anchor = self._capture_scroll_anchor()
        if self._restore_anchor is None:
            self._restore_top_verse = self._find_topmost_visible_verse()
        self._fetch_and_render()

    def _insert_section_heading(self, text, lead_blank):
        """Insert a publisher section heading above the verse it titles.

        Same voice as the section titles _html_to_markup already styles —
        a quiet tracked kicker, smaller than the body — so a heading that
        arrives via the entry attributes and one embedded in the markup
        look identical.

        `lead_blank` is False for the first block of a chapter. The chapter
        heading above it already ends in a newline and deliberately carries
        no blank line of its own (see its comment: a blank line there "left
        an oversized top gap"); adding one here reopens exactly that gap."""
        lead = '\n\n' if lead_blank else ''
        markup = (f'{lead}<span size="90%" weight="bold" letter_spacing="800" '
                  f'foreground="gray">'
                  f'{GLib.markup_escape_text(text)}</span>\n')
        start = self._buffer.get_end_iter().get_offset()
        self._buffer.insert_markup(self._buffer.get_end_iter(), markup, -1)
        # The surrounding newlines are inside the tagged range on purpose:
        # hiding the words but leaving their blank line behind would open a
        # gap where the heading used to be.
        self._buffer.apply_tag(self._heading_tag(),
                               self._buffer.get_iter_at_offset(start),
                               self._buffer.get_end_iter())

    def _unit_bounds(self, verse):
        """(first_verse, last_verse) of the sense-unit containing `verse`,
        or None. Units start where the module put a section heading, so
        they exist only where headings do."""
        heads = self._rendered_headings
        if not heads or not self._show_headings:
            return None
        rendered = sorted(v for v, _h in (self._rendered_verses or []))
        if not rendered:
            return None
        starts = sorted(v for v in heads if v in set(rendered))
        if not starts:
            return None
        opening = [v for v in starts if v <= verse]
        if not opening:
            # Before the first heading. That opening passage is a sense-unit
            # too — the epistolary greeting, the psalm's superscription — it
            # simply has no title of its own, and returning None here left
            # BOTH controls silent at the top of every chapter whose first
            # heading is not verse 1 (2 Peter 1 carries its first at verse 3
            # in the Synodal and the BSB). That is exactly where a reader
            # opens a chapter and looks, so the feature read as broken.
            preface = [v for v in rendered if v < starts[0]]
            return (rendered[0], preface[-1]) if preface else None
        first = opening[-1]
        later = [v for v in starts if v > first]
        last = (max(v for v in rendered if v < later[0]) if later
                else rendered[-1])
        return first, last

    def _update_current_unit(self):
        """Follow the reader with the viewport, not with the cursor.

        Driven by scroll position because that is the only source that
        answers "where am I?" while simply reading — a cursor- or
        click-driven mark shows where you last acted and then sits there.
        Retags only when the unit actually changes, so scrolling inside one
        unit does no buffer work."""
        if ((not self._mark_current_unit and not self._focus_unit)
                or self._module_type != 'Biblical Texts'):
            return
        top = (self._rendered_verses[-1][0] if self._at_chapter_foot()
               else self._find_topmost_visible_verse())
        if top is None:
            # The viewport top is on a heading or blank line, which carries
            # no vnum_ tag, and that answer covers several situations: the
            # top of a chapter, a heading sitting on the viewport's first
            # row, the gap between two units.
            #
            # This used to KEEP the unit it had, on the reasoning that a
            # heading between units is a moment in passing and re-marking
            # would flicker. That is defensible for a hairline in the margin
            # and wrong for anything that dims text: the kept unit scrolls
            # away, and then either nothing is quieted at all (the veil
            # cannot find its unit and fails open) or everything is (only a
            # sliver of the unit is left on screen, so the veil below it
            # covers the page). Both were measured off real screenshots.
            #
            # So look further down the page instead. The first verse the
            # viewport actually shows is the one the reader is entering —
            # under a heading at the top, that is the new unit, which is
            # exactly what should be marked.
            top = self._first_visible_verse()
        if top is None:
            rendered = sorted(v for v, _h in (self._rendered_verses or []))
            if not rendered or self._current_unit is not None:
                return
            top = rendered[0]
        bounds = self._unit_bounds(top)
        if bounds is None or bounds[0] == self._current_unit:
            return
        self._current_unit = bounds[0]
        self._apply_unit_tag(*bounds)

    def _first_visible_verse(self):
        """The first verse the viewport shows anywhere, not only on its top
        row.

        Walks down the visible height a line at a time until a `vnum_` tag
        answers. Only reached when the top row carries none — a heading, a
        paragraph gap, the chapter title — so the common path still costs one
        lookup. Deliberately NOT folded into ScrollKeeper's
        `_find_topmost_visible_verse`: that one feeds the reading anchor and
        the scroll invariant, and it means the verse at the top edge exactly.
        """
        view = self._view
        if not view.get_realized():
            return None
        x = max(40, view.get_left_margin() + 20)
        height = view.get_visible_rect().height
        step = max(12, int(self._line_height_hint()))
        y = 4
        while y < height:
            bx, by = view.window_to_buffer_coords(
                Gtk.TextWindowType.TEXT, x, y)
            ok, it = view.get_iter_at_location(bx, by)
            if ok:
                for tag in it.get_tags():
                    name = tag.get_property('name') or ''
                    if name.startswith('vnum_'):
                        try:
                            return int(name.split('_', 1)[1])
                        except (ValueError, IndexError):
                            pass
            y += step
        return None

    def _line_height_hint(self):
        """Roughly one line, for stepping down the viewport."""
        metrics = self._view.get_pango_context().get_metrics(None, None)
        return ((metrics.get_ascent() + metrics.get_descent())
                / Pango.SCALE) or 20

    def _at_chapter_foot(self):
        """Whether the reader has scrolled as far as the chapter goes.

        The topmost visible verse is the right reading of "where am I?"
        everywhere except here: at the foot of a chapter the scroll has run
        out, so a last unit shorter than the viewport can never reach the top
        and never becomes current — it just sits there quieted while the
        reader reads it, which is precisely backwards.

        Requires the chapter to actually scroll. A chapter that fits the
        viewport whole is at its foot from the moment it opens, and there the
        topmost verse is the honest answer.
        """
        if not self._rendered_verses:
            return False
        adj = self._reading_scroll.get_vadjustment()
        page = adj.get_page_size()
        if adj.get_upper() <= page:
            return False
        return adj.get_value() >= adj.get_upper() - page - 2.0

    def _apply_unit_tag(self, first, last):
        """Mark the unit's whole span with the tag BibleTextView draws the
        margin rule from."""
        buf = self._buffer
        table = buf.get_tag_table()
        tag = table.lookup('_cur_unit') or buf.create_tag('_cur_unit')
        buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
        first_range = self._verse_ranges(first)
        last_range = self._verse_ranges(last)
        if not first_range or not last_range:
            return
        buf.apply_tag(tag, first_range[0], last_range[2])
        self._view.queue_draw()

    def _clear_unit_tag(self):
        buf = self._buffer
        tag = buf.get_tag_table().lookup('_cur_unit')
        if tag is not None:
            buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
            self._view.queue_draw()
        self._current_unit = None

    def marks_sections(self):
        """Whether the module this pane is showing supplies section headings
        at all — the data both sense-unit controls are built on.

        Asked of the module rather than of the chapter on screen: a chapter
        with no headings of its own is common in a module full of them, and a
        control that came and went as the reader paged would be worse than
        one that is honestly absent. eBible modules carry none by
        construction (the fetch hands back an empty map).
        """
        if self._module_type != 'Biblical Texts' or not self._module:
            return False
        if ebible_bridge.is_ebible_module(self._module):
            return False
        return sword_bridge.module_marks_sections(self._module)

    def set_mark_current_unit(self, enabled):
        if self._mark_current_unit == bool(enabled):
            return
        self._mark_current_unit = bool(enabled)
        self._view.set_unit_rule(self._mark_current_unit)
        if self._mark_current_unit:
            self._update_current_unit()
        elif not self._focus_unit:
            # The veil reads the same tag; only the last one out clears it.
            self._clear_unit_tag()
        else:
            self._view.queue_draw()

    def set_focus_current_unit(self, enabled):
        if self._focus_unit == bool(enabled):
            return
        self._focus_unit = bool(enabled)
        self._update_font_css()          # the veil's paper and strength
        if self._focus_unit:
            self._update_current_unit()
        elif not self._mark_current_unit:
            self._clear_unit_tag()

    def set_show_headings(self, enabled):
        if self._show_headings == bool(enabled):
            return
        self._show_headings = bool(enabled)
        # Attribute-only where it can be — see set_show_footnotes for why that
        # matters: a rebuild is what the reading position has to be held
        # through, and holding it is where the jumping comes from.
        if self._restyle_section_headings():
            return
        self._rerender_keeping_place()

    def _restyle_section_headings(self):
        """Show or hide the rendered chapter's section headings without
        rebuilding it. False when this chapter has headings the tag cannot
        govern — ones embedded in the source markup, whose blank lines sit
        outside the span insert_markup tagged — so the caller re-renders."""
        if self._rendered_inline_titles:
            return False
        if self._buffer.get_tag_table().lookup(_HEADING_TAG) is None:
            return False
        # Unlike the numerals and the footnote markers, this really does move
        # the text: every heading above the reading position is two blank lines
        # and a line of type, and hiding them pulls the page up by that much.
        # No rebuild means no restore comes for free, so re-apply the locus by
        # hand — captured BEFORE the flip, applied after the relayout.
        # Both probes, exactly as _rerender_keeping_place takes them: the pixel
        # anchor is not always available (the viewport top can fall in the
        # space between paragraphs, where get_iter_at_location finds nothing),
        # and without the coarse fallback the page simply keeps the jump.
        anchor = self._capture_scroll_anchor()
        top_verse = (self._find_topmost_visible_verse()
                     if anchor is None else None)
        self._heading_tag()              # carries the new visibility
        if anchor is not None:
            GLib.idle_add(self._apply_scroll_anchor, anchor)
        elif top_verse is not None:
            GLib.idle_add(self._scroll_to_verse_silent, top_verse)
        return True

    def set_show_footnotes(self, enabled):
        if self._show_footnotes == bool(enabled):
            return
        self._show_footnotes = bool(enabled)
        # Attribute-only: the markers are already in the buffer, so this is one
        # tag property, not a rebuild. That matters beyond speed — a rebuild
        # empties and refills the buffer, and the reading position has to be
        # held through GTK's re-estimation of the document height (see
        # _ReadingScrolledWindow.hold_scroll and the flicker it exists to
        # fight). Nothing is rebuilt here, so there is nothing to hold.
        if self._restyle_footnote_markers():
            return
        # Nothing adopted to restyle — a chapter rendered before the markers
        # existed, or a surface that never rendered one. Fall through to the
        # render, which is also what picks the flag up when a Bible next
        # appears here.
        self._rerender_keeping_place()

    def _restyle_footnote_markers(self):
        """Show or hide the rendered chapter's markers without rebuilding it.
        False when there is nothing tagged to flip, so the caller can fall back
        to a render."""
        if self._buffer.get_tag_table().lookup(_FN_MARKER_TAG) is None:
            return False
        self._fn_marker_tag()            # carries the new visibility
        return True

    def set_divine_smallcaps(self, enabled):
        if self._smallcaps_divine == bool(enabled):
            return
        self._smallcaps_divine = bool(enabled)
        self._rerender_keeping_place()

    def set_oldstyle_numerals(self, enabled):
        if self._oldstyle_nums == bool(enabled):
            return
        self._oldstyle_nums = bool(enabled)
        # Same text, one font feature. The fall-through covers a pane that has
        # never rendered a Bible — the tag is not chapter-scoped, so once one
        # has, it survives every later render and this path is taken from then
        # on. Which is right either way: `_numeral_ff` is written by the Bible
        # render and nothing else, so a devotional or genbook standing in the
        # pane has no numerals for the mutation to miss, and the render that
        # brings a Bible back reads the flag afresh.
        if not self._restyle_numerals():
            self._rerender_keeping_place()

    def set_colored_dropcap(self, enabled):
        if self._colored_dropcap == bool(enabled):
            return
        self._colored_dropcap = bool(enabled)
        # Same text, same cap, one foreground on or off. Same shape as the
        # numerals above, and the same caveat: the cap tag outlives the chapter
        # that made it, so the fall-through only ever fires on a pane no cap
        # has been rendered into. Harmless — the enlarged letter is written by
        # the Bible render alone, and a chapter whose verse 1 offered no letter
        # to enlarge would not gain one from a re-render either.
        if not self._sync_dropcap_ink():
            self._rerender_keeping_place()

    def set_poetry_flush(self, flush):
        if self._poetry_flush == bool(flush):
            return
        self._poetry_flush = bool(flush)
        # Pure paragraph-geometry change on the existing tags — the
        # already-rendered lines reflow in place, no re-render.
        self._sync_poetry_tags()

    def refresh_dropcap_color(self):
        """The stored drop-cap colour changed. Nothing to do while the cap is
        uncoloured — the toggle reads the colour fresh when it turns on."""
        if self._colored_dropcap and not self._sync_dropcap_ink():
            self._rerender_keeping_place()

    def _numeral_ff(self):
        """The markup attribute carrying `_numeral_features`."""
        return f' font_features="{_numeral_features(self._oldstyle_nums)}"'

    def _ensure_poetry_tags(self):
        if self._poetry_tags is None:
            self._poetry_tags = {
                lvl: self._buffer.create_tag(f'poetry_l{lvl}')
                for lvl in (1, 2, 3)}
            self._sync_poetry_tags()

    def _sync_poetry_tags(self):
        """Poetry-line paragraph geometry. Level 1 is indent-only (a
        negative indent hangs wrapped continuations one stop past the
        column edge, and the paragraph keeps the view's own margin).
        Levels 2/3 step in — which needs left-margin, and a tag
        left-margin REPLACES the view's dynamic centering margin
        (measured), so they track the current margin and re-sync when
        it, the font size, or the flush toggle changes."""
        if self._poetry_tags is None:
            return
        em = self._font_size * 96.0 / 72.0
        hang = round(1.5 * em)
        step = 0 if self._poetry_flush else round(1.5 * em)
        side = self._view.get_left_margin()
        self._poetry_tags[1].props.indent = -hang
        for lvl in (2, 3):
            self._poetry_tags[lvl].props.left_margin = side + (lvl - 1) * step
            self._poetry_tags[lvl].props.indent = -hang

    def _on_reading_margins_changed(self):
        # Synchronous, and it has to be. _apply_margins runs BEFORE the
        # ScrolledWindow chains up, so mirroring the tags here puts them in
        # place before the TextView is laid out: the frame paints the indent
        # and the margin it mirrors together. Deferring cost exactly that —
        # measured over a split-drag storm, counting PAINTED frames where
        # the tag margin disagreed with the view's: 26 on an idle, 9 on a
        # tick callback (which, scheduled from inside the layout phase, has
        # already missed that frame's update phase), 0 here.
        if self._poetry_tags is None:
            return
        self._sync_poetry_tags()

    def _apply_poetry_line_tags(self, text_start_mark, levels):
        """Tag whole buffer lines (paragraphs) with the poetry indent
        tags. Keys are line indices relative to the verse's first line;
        a line continuing across a verse boundary is simply re-tagged
        from its own line start, so the paragraph attribute covers the
        verse-number prefix too."""
        self._ensure_poetry_tags()
        base = self._buffer.get_iter_at_mark(text_start_mark).get_line()
        for k, lvl in levels.items():
            ok, start = self._buffer.get_iter_at_line(base + k)
            if not ok:
                continue
            end = start.copy()
            end.forward_line()  # start of next line, or buffer end
            self._buffer.apply_tag(self._poetry_tags[lvl], start, end)

    def _scroll_to_verse(self, verse_num):
        self._mark_programmatic_scroll()
        self._reading_anchor = None  # a jump IS a new reading locus
        self._schedule_anchor_capture(400)  # …and worth holding, too
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

    def _verse_state_text(self, verse_num):
        """"Jonah 2:3, highlighted yellow, has note" — the reference plus
        whatever a sighted reader can see painted on the verse.

        The highlight band, the underline, and the note indicator are drawn
        by BibleTextView (pixels, no semantics), so this is the only way an
        AT user learns they are there."""
        parts = [f'{book_label(self._book)} {self._chapter}:{verse_num}']
        if self._module_type == 'Biblical Texts':
            annos = annotations.get_annotations(
                self._module, self._book, self._chapter)
            anno = (annos or {}).get(str(verse_num), {})
            if isinstance(anno, str):
                anno = {'highlight': anno}
            anno = anno or {}
            color = annotation_dialogs.highlight_name(anno.get('highlight'))
            if color:
                parts.append(_('highlighted {color}').format(
                    color=color.lower()))
            elif anno.get('highlight'):
                parts.append(_('highlighted'))
            if anno.get('underline'):
                parts.append(_('underlined'))
            if anno.get('note'):
                parts.append(_('has note'))
            # Only when they are shown: the map is populated whether or not
            # the markers are drawn, and announcing a footnote a reader can
            # neither see nor reach is worse than silence.
            if self._show_footnotes:
                notes = self._chapter_footnotes
                if any(v == verse_num for v, _n in notes):
                    parts.append(_('has footnotes'))
        return ', '.join(parts)

    def _announce_verse_state(self, verse_num):
        """Speak the verse the reader just moved to, and its annotation
        state, without moving focus.

        The navigation flash and the current-verse indicator are painted
        cues; this is their AT equivalent. Also parked on the view as its
        accessible description, so the state is still discoverable after
        the announcement has passed."""
        if not verse_num or not self._is_verse_navigable():
            return
        text = self._verse_state_text(verse_num)
        a11y.set_accessible_description(self._view, text)
        a11y.announce(self._view, text)

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

    def _apply_anno_tags(self, verse_num, anno, fresh=False):
        """Idempotently apply highlight / underline / note-indicator tags
        for verse_num based on the given annotation dict. Clears any prior
        annotation tags first. Does not modify the buffer text — pure tag
        manipulation, so the scroll position is preserved.

        `fresh=True` (the full-render path) skips the clear pass: the
        buffer was just rebuilt, so no annotation tags are applied yet —
        and the clearing scan is the expensive part (a tag-table foreach
        per verse made big chapters quadratic; Psalm 119 spent ~125 ms
        of its render freeze there)."""
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

        if not fresh:
            # Clear any previous annotation tags from the verse's ranges. The
            # highlight background can reach back over the verse number, so
            # clear from vnum_start (removing where a tag isn't applied is a
            # no-op).
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
        # Annotating is a user action whose whole result is a painted band —
        # say what it did, or an AT user gets no confirmation at all.
        self._announce_verse_state(verse_num)

    def _flash_verse(self, verse_num):
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if not tag:
            return

        # The flash is the "you arrived here" cue; announce its AT equivalent.
        self._announce_verse_state(verse_num)

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
                    # Case-insensitive last resort: the small-caps divine
                    # name downcases the buffer text ("LORD" → "Lord" —
                    # the span only *draws* capitals), so the raw segment
                    # no longer matches exactly and the word would lose
                    # its Strong's tag. Case transforms preserve length,
                    # so the offsets stay exact.
                    idx = verse_text.lower().find(
                        stripped.lower(), search_pos)
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
        word under the cursor; clear when the cursor leaves any tagged
        word. Also feeds the hover-preview dwell tracker (Advanced,
        default off) — every exit path reports 'not on a word' so a
        pending dwell can't fire for a word the cursor already left."""
        if not self._lexicon_enabled:
            self._clear_strg_hover()
            self._hover_track(None, None, x, y)
            return
        bx, by = self._view.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            self._clear_strg_hover()
            self._hover_track(None, None, x, y)
            return
        # Last strg: tag wins, mirroring the click path — a fused tag
        # (e.g. 'the synagogue', G3588+G4864) must gloss the same entry
        # a click would open.
        strong = None
        for t in it.get_tags():
            name = t.get_property('name') or ''
            if name.startswith('strg:'):
                strong = name[5:]
        if strong is None:
            self._clear_strg_hover()
            self._hover_track(None, None, x, y)
            return
        # Find the word boundaries around `it` and apply the hover tag there.
        word_start = it.copy()
        word_end = it.copy()
        if not word_start.starts_word():
            word_start.backward_word_start()
        if not word_end.ends_word():
            word_end.forward_word_end()
        new_range = (word_start.get_offset(), word_end.get_offset())
        # Before the unchanged-range early-out: the dwell detector needs
        # every motion event to measure whether the cursor has stopped.
        self._hover_track(new_range, strong, x, y)
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
                foreground=theme_ink(dark)['_ink_link'],
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

    def _on_view_leave(self):
        """Cursor left the reading view — possibly into the hover gloss,
        whose own motion controller cancels the grace on entry."""
        self._clear_strg_hover()
        if self._hover_preview:
            self._hover_cancel_dwell()
            self._hover_arm_grace()

    # ── Hover-to-preview (Appearance ▸ Advanced, default off) ────────────

    def set_hover_preview(self, enabled):
        if self._hover_preview == bool(enabled):
            return
        self._hover_preview = bool(enabled)
        if not self._hover_preview:
            self._hover_cancel_dwell()
            self._hover_cancel_grace()
            if self._hover_gloss_range is not None:
                self.dismiss_dict_peek()

    def _hover_track(self, word_range, strong, x, y):
        """Dwell detector: intent is the cursor *stopping* on a Strong's
        word. Wobble inside the jitter radius keeps the dwell armed; real
        movement re-anchors and restarts it; leaving the word arms the
        dismissal grace instead of killing an open gloss outright, so the
        diagonal move onto the card survives."""
        if not self._hover_preview:
            return
        if word_range is None:
            self._hover_cancel_dwell()
            self._hover_arm_grace()
            return
        if self._hover_gloss_range == word_range:
            # Back over the word the open gloss belongs to — keep it.
            self._hover_cancel_grace()
            self._hover_cancel_dwell()
            return
        cur = self._hover_word
        if cur is None or (cur[0], cur[1]) != word_range:
            # New candidate word: anchor here and arm the dwell.
            self._hover_word = (word_range[0], word_range[1], strong)
            self._hover_anchor = (x, y)
            self._hover_restart_dwell()
        else:
            dx = x - self._hover_anchor[0]
            dy = y - self._hover_anchor[1]
            if dx * dx + dy * dy > _HOVER_JITTER_PX ** 2:
                # The cursor hasn't stopped — re-anchor, restart.
                self._hover_anchor = (x, y)
                self._hover_restart_dwell()
        if (self._hover_gloss_range is not None
                and word_range != self._hover_gloss_range):
            # Crossed straight onto another word: the old gloss still
            # dismisses on grace (a new one needs its own full dwell).
            self._hover_arm_grace()

    def _hover_restart_dwell(self):
        if self._hover_timer:
            GLib.source_remove(self._hover_timer)
        self._hover_timer = GLib.timeout_add(
            motion.HOVER_DWELL_MS, self._hover_dwell_fire)

    def _hover_cancel_dwell(self):
        if self._hover_timer:
            GLib.source_remove(self._hover_timer)
            self._hover_timer = 0
        self._hover_word = None

    def _hover_arm_grace(self):
        if self._hover_gloss_range is None or self._hover_grace_timer:
            return
        self._hover_grace_timer = GLib.timeout_add(
            motion.HOVER_GRACE_MS, self._hover_grace_fire)

    def _hover_cancel_grace(self):
        if self._hover_grace_timer:
            GLib.source_remove(self._hover_grace_timer)
            self._hover_grace_timer = 0

    def _hover_grace_fire(self):
        self._hover_grace_timer = 0
        if self._hover_gloss_range is not None:
            self.dismiss_dict_peek()
        return GLib.SOURCE_REMOVE

    def _hover_dwell_fire(self):
        self._hover_timer = 0
        word = self._hover_word
        if word is None or not self._hover_preview:
            return GLib.SOURCE_REMOVE
        if self._hover_gloss_range == (word[0], word[1]):
            # This word's gloss is already up. Reachable when movement
            # inside the word re-armed the dwell while the first fetch
            # was in flight — without this, the fire would re-show the
            # same card (popdown/popup blink) and re-fetch for nothing.
            return GLib.SOURCE_REMOVE
        pop = getattr(self, '_dict_pop', None)
        if (pop is not None and pop.get_visible()
                and self._hover_gloss_range is None):
            # A click-opened peek (dictionary/footnote) is up — a hover
            # must never replace something the reader asked for.
            return GLib.SOURCE_REMOVE
        start_off, end_off, strong = word

        def apply(text):
            gloss = _gloss_from_strong_entry(text)
            cur = self._hover_word
            if (not gloss or cur is None
                    or (cur[0], cur[1]) != (start_off, end_off)):
                return  # nothing to glance at, or the cursor moved on
            self._show_hover_gloss(start_off, end_off, strong, gloss)

        # Same key as the click peeks: a click or newer lookup supersedes
        # the gloss fetch. A raised lookup shows nothing — a hovercard
        # either appears whole or not at all.
        tasks.submit(f'peek:{id(self)}',
                     lambda _t: sword_bridge.lookup_strong(strong),
                     apply, on_error=lambda _exc: None)
        return GLib.SOURCE_REMOVE

    def _show_hover_gloss(self, start_off, end_off, strong, text):
        """The hovercard: a compact plain-text gloss of the Strong's entry
        in the shared self-healing peek, anchored at the dwelled word — a
        glance, not a study; the full lexicon stays one click away."""
        start = self._buffer.get_iter_at_offset(start_off)
        end = self._buffer.get_iter_at_offset(end_off)
        r1 = self._view.get_iter_location(start)
        r2 = self._view.get_iter_location(end)
        wx1, wy1 = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r1.x, r1.y)
        wx2, _wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r2.x, r2.y)
        rect = Gdk.Rectangle()
        rect.x, rect.y = wx1, wy1
        rect.width = max(1, wx2 - wx1) if r2.y == r1.y else max(1, r1.width)
        rect.height = r1.height

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cap = Gtk.Label(label=_('Strong’s {num}').format(num=strong),
                        xalign=0)
        cap.add_css_class('caption')
        cap.add_css_class('dim-label')
        body = Gtk.Label(label=text, xalign=0, wrap=True)
        body.set_max_width_chars(44)
        # A CAP is not a FLOOR. With only the cap set, a wrapping label's
        # minimum width is its longest word, so anchored near a window edge
        # the card collapsed to a column two words wide — "Christos {khris-
        # tos} from 5548;" down the screen. The dictionary peek has always
        # asked for a width; this asks for the same one, capped the same way
        # so a narrow window still fits it.
        _root = self.get_root()
        _win_w = _root.get_width() if _root is not None else 0
        box.set_size_request(
            320 if _win_w <= 0 else max(240, min(320, _win_w - 24)), -1)
        box.append(cap)
        box.append(body)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(12)
        # The corridor: pointer onto the card cancels the dismissal grace;
        # leaving the card re-arms it.
        mc = Gtk.EventControllerMotion()
        mc.connect('enter', lambda *_a: self._hover_cancel_grace())
        mc.connect('leave', lambda *_a: self._hover_arm_grace())
        box.add_controller(mc)

        self.show_anchored_peek(self._view, rect, box)
        self._hover_gloss_range = (start_off, end_off)

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

    def _targets_at_iter(self, it):
        """What the reading text offers at `it`: the verse it belongs to and
        any lookup the position carries.

        Returns `(targets, it)` — the iter comes back because a footnote
        marker re-anchors it (see below). Shared by the click handler and the
        keyboard verse cursor, so the two can never disagree about what a
        position means."""
        targets = {'verse': None, 'strong': None, 'morph': None,
                   'devref': None, 'fnote': None, 'phrase_tag': None}
        for tag in it.get_tags():
            name = tag.get_property('name')
            if name and name.startswith('strg:'):
                targets['strong'] = name[5:]
            elif name and name.startswith('vnum_'):
                try:
                    targets['verse'] = int(name.split('_')[1])
                except (ValueError, IndexError):
                    pass
            elif name and name.startswith('morph:'):
                targets['morph'] = name[6:]
            elif name and name.startswith('devref:'):
                targets['devref'] = name[7:]
            elif name and name.startswith('fnote:'):
                targets['fnote'] = name[6:]
            elif name and name.startswith('phrase:'):
                targets['phrase_tag'] = tag
        if not self._show_footnotes:
            # The markers are still in the buffer when they are switched off,
            # merely not drawn — and the probe below deliberately looks one
            # character to each side, so a click on the letter beside a hidden
            # marker resolved to it and opened a note the reader had turned
            # off. Nothing invisible is a click target.
            targets['fnote'] = None
        elif targets['fnote'] is None:
            # A marker is a single narrow superscript glyph, and
            # get_iter_at_location resolves a click on its right half to
            # the NEXT character — so exact-iter tagging misses half the
            # glyph. Probe one char to each side and accept a marker there.
            for step in (-1, 1):
                p = it.copy()
                moved = p.backward_char() if step < 0 else p.forward_char()
                if not moved:
                    continue
                for tag in p.get_tags():
                    name = tag.get_property('name') or ''
                    if name.startswith('fnote:'):
                        targets['fnote'] = name[6:]
                        it = p  # anchor the peek on the marker itself
                        break
                if targets['fnote']:
                    break
        return targets, it

    def _on_left_click(self, gesture, n_press, x, y):
        # Stash press position so _on_left_release can distinguish a true
        # click (collapse phantom selection) from a drag-select (preserve).
        self._click_press_pos = (x, y)
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return
        targets, it = self._targets_at_iter(it)
        verse_num = targets['verse']
        strong_num = targets['strong']
        morph = targets['morph']
        devref = targets['devref']
        fnote = targets['fnote']
        phrase_tag = targets['phrase_tag']
        if n_press > 1:
            return
        if devref:
            result = sword_bridge.parse_osis_ref(devref)
            if result and self._on_word_study_navigate:
                self._on_word_study_navigate(*result)
            return
        if fnote:
            # Peek only — no verse broadcast, so the other pane doesn't
            # re-render (and reflow) underneath the open popover.
            self._show_footnote_peek(fnote, it)
            return
        if verse_num is not None:
            self._selected_verse = verse_num
            self._set_current_verse_indicator(verse_num)
            self._announce_verse_state(verse_num)
            # Resume keyboard stepping from wherever the pointer just landed.
            self._cursor.sync_to(verse_num)
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
        # Suppress on navigation links (devref) and footnote markers (the
        # first click already opened the note peek); Strong's-tagged words
        # should still open the dict popup on double-click — the lexicon
        # opens on the first click, the dict on the second.
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith(('devref:', 'fnote:')):
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

    def _attach_dict_to_label(self, label):
        """Wire the double-click dictionary peek onto a card label (commentary
        quote, caption, archaeology body). Makes the text selectable so GTK's
        native double-click selects the word; a CAPTURE-phase click then reads
        that selection and shows the same peek used in the reading view."""
        if label is None:
            return
        label.set_selectable(True)
        g = Gtk.GestureClick.new()
        g.set_button(1)
        g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        g.connect('pressed', self._on_label_dict_click, label)
        label.add_controller(g)

    def _on_label_dict_click(self, gesture, n_press, x, y, label):
        # Any click dismisses an open peek (it's non-autohide). Defer the
        # lookup so the label has settled its native double-click selection.
        existing = getattr(self, '_dict_pop', None)
        if existing is not None and existing.get_visible():
            self._dict_user_closed = True
            existing.popdown()
        if n_press == 2:
            GLib.timeout_add(50, self._label_dict_lookup, label, int(x), int(y))

    def _label_dict_lookup(self, label, x, y):
        non_empty, s, e = label.get_selection_bounds()
        if non_empty:
            word = label.get_text()[s:e].strip()
            if word and word.replace("'", '').replace('’', '').isalpha():
                rect = Gdk.Rectangle()
                rect.x, rect.y, rect.width, rect.height = x, y, 1, 1
                self._show_dict_popup_at(word, label, rect)
        return GLib.SOURCE_REMOVE

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
            self._peek_fade_in(pop)
        return GLib.SOURCE_REMOVE

    def _peek_fade_in(self, pop):
        """Fade the stable peek up to full opacity (EASE_FADE) instead of a
        hard flip — the reveal step only; the show-when-stable/self-heal
        choreography around it is untouched. Adw.TimedAnimation follows
        gtk-enable-animations, so reduced motion collapses this back to
        the instant flip."""
        prev = getattr(self, '_peek_fade', None)
        if prev is not None:
            prev.pause()
        target = Adw.PropertyAnimationTarget.new(pop, 'opacity')
        anim = Adw.TimedAnimation.new(
            pop, pop.get_opacity(), 1.0, motion.DURATION_MICRO, target)
        anim.set_easing(motion.EASE_FADE)
        self._peek_fade = anim
        anim.play()

    def grab_content_focus(self) -> bool:
        """Put the keyboard on whatever this pane is SHOWING.

        `_view` is the Bible text view and it stays in the content stack when
        another reader is on top of it — visible, but not mapped. GTK grants
        `grab_focus` to such a widget, so "Focus left pane" landed the caret
        on something the reader cannot see: arrow keys moved through hidden
        text, and the genealogy chart — which is focusable and carries the
        chart's text equivalent for a screen reader — never got the focus at
        all. The same held for every reader that is not a Bible.
        """
        if self._view.get_mapped():
            return self._view.grab_focus()
        shown = self._content_stack.get_visible_child()
        if shown is None:
            return self._view.grab_focus()

        def first_focusable(w):
            if w.get_focusable() and w.get_mapped():
                return w
            child = w.get_first_child()
            while child is not None:
                got = first_focusable(child)
                if got is not None:
                    return got
                child = child.get_next_sibling()
            return None

        target = first_focusable(shown)
        return target.grab_focus() if target is not None else False

    def dismiss_dict_peek(self):
        """Close an open dictionary peek. Returns True if one was open — the
        window's Escape handler uses this (the peek is non-focusable, so it
        never sees the key itself)."""
        self._hover_gloss_range = None  # a dismissed gloss can re-dwell
        pop = getattr(self, '_dict_pop', None)
        if pop is not None and pop.get_visible():
            self._dict_user_closed = True
            pop.popdown()
            return True
        return False

    def _peek_room(self, anchor_widget, rect, pop):
        """Point `pop` at whichever side of `rect` has more room, and return
        the pixels available on that side.

        A popover taller than the window is never placed: GTK closes it the
        moment it is shown, the self-heal reshows it, and after twelve rounds
        the peek is simply unopenable. So every peek whose body can run long
        measures the room first and caps itself to it (_peek_scroller). Room
        is measured in the window, where the popover actually lives — it can
        extend up over the toolbar."""
        root = anchor_widget.get_root()
        y, win_h = rect.y, anchor_widget.get_height()
        if root is not None:
            ok, pt = anchor_widget.compute_point(
                root, Graphene.Point().init(float(rect.x), float(rect.y)))
            if ok:
                y = pt.y
            win_h = root.get_height()
        above, below = y, win_h - (y + rect.height)
        if above > below:
            pop.set_position(Gtk.PositionType.TOP)
            return above
        pop.set_position(Gtk.PositionType.BOTTOM)
        return below

    @staticmethod
    def _peek_scroller(child, avail, chrome=86):
        """Wrap a peek's body so a long one scrolls inside the popover instead
        of demanding a height that cannot be placed. `chrome` is what the
        popover spends around the body — caption, margins, arrow. A short body
        keeps its natural height and never shows a bar."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(int(max(140, min(420, avail - chrome))))
        scroll.set_child(child)
        return scroll

    def show_anchored_peek(self, anchor_widget, rect, content):
        """Show `content` in the shared self-healing peek popover, anchored
        at `rect` in `anchor_widget`. The lexicon panel's verse peek rides
        the same instance as the dictionary/footnote peeks, so the reshow-
        until-stable machinery and the dismissal paths (Escape, module
        change, new lookup) cover it too.

        `content` arrives whole (header and body together), so the cap wraps
        all of it: a long verse or gloss scrolls with its own caption rather
        than being unopenable."""
        pop = self._ensure_peek_popover(anchor_widget)
        # A dictionary fetch already in flight can't replace this peek's
        # content when it returns.
        tasks.cancel(f'peek:{id(self)}')
        avail = self._peek_room(anchor_widget, rect, pop)
        pop.set_pointing_to(rect)
        pop.set_child(self._peek_scroller(content, avail, chrome=40))
        # Invisible until it has survived the post-click relayout churn —
        # the same show-when-stable dance as the dictionary peek.
        self._dict_retries = 0
        self._dict_open_at = GLib.get_monotonic_time()
        self._dict_user_closed = False
        pop.set_opacity(0.0)
        pop.popup()
        self._dict_arm_reveal(pop)

    def _dismiss_lexicon_peek(self):
        """Dismiss the shared peek only when it's the lexicon panel's verse
        peek (anchored on the def view) — clicks inside the lexicon must
        not reach across and close a reading-view dict/footnote peek."""
        pop = getattr(self, '_dict_pop', None)
        if (pop is not None and pop.get_visible()
                and pop.get_parent() is self._lex_panel.def_view):
            self._dict_user_closed = True
            pop.popdown()

    def _verse_at_offset(self, offset):
        """The verse number a buffer offset falls in, or 0.

        The genealogy table disambiguates on the verse — one name covers many
        people, and "this Jacob" means the one this verse is about. The
        `vnum_` tags are already on the text; the right-click menu reads them
        the same way."""
        it = self._buffer.get_iter_at_offset(offset)
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith('vnum_'):
                try:
                    return int(name.split('_')[1])
                except (ValueError, IndexError):
                    return 0
        return 0

    def _show_dict_popup(self, word, word_offset):
        # TextView entry point: compute the word's rectangle in the view's
        # widget coords, then hand off to the shared peek anchored on the view.
        self._peek_verse = self._verse_at_offset(word_offset)
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
        self._show_dict_popup_at(word, self._view, rect)

    def _ensure_peek_popover(self, anchor_widget):
        """The shared non-autohide peek popover — dictionary look-ups and
        footnote markers use the same reused instance, so the dismissal
        paths (click in view, Esc, module change) cover both. Created once
        per pane with the self-heal closed-handler; re-parented to whichever
        widget anchors the current peek."""
        # Guard the self-heal (below) against our own teardown/rebuild: True
        # while we intentionally close or replace the popover.
        self._dict_user_closed = True
        # Whatever shows next isn't the hover gloss (the gloss path re-sets
        # this after the show) — so the grace machinery can't dismiss a
        # click-opened peek.
        self._hover_gloss_range = None
        pop = getattr(self, '_dict_pop', None)
        if pop is None:
            pop = Gtk.Popover()
            pop.set_has_arrow(True)
            pop.set_autohide(False)
            pop.set_can_focus(False)
            # Clicking a word re-renders the other pane (cross-pane verse
            # sync); that relayout cascade unmaps a freshly-shown popover no
            # matter where it's parented — a Gtk.Popover can't survive a
            # concurrent relayout. So self-heal: if it's torn down within the
            # settle window and the user didn't dismiss it, re-show until the
            # layout goes quiet (the stable state the popover lives in).
            def _on_closed(p):
                # Cancel a pending reveal — the show was interrupted, so it
                # wasn't stable; the next reshow re-arms it. An in-flight
                # fade is stopped too, or its remaining frames would fight
                # the reshow's opacity-0.
                if getattr(self, '_dict_reveal_timer', 0):
                    GLib.source_remove(self._dict_reveal_timer)
                    self._dict_reveal_timer = 0
                fade = getattr(self, '_peek_fade', None)
                if fade is not None:
                    fade.pause()
                    self._peek_fade = None
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
        # Parent to the anchor widget so the arrow anchors on the word in that
        # widget's own coordinate space (parenting elsewhere mis-anchors it).
        # Re-parent when the lookup comes from a different widget (e.g. the
        # reading view vs. a commentary card label).
        if pop.get_parent() is not anchor_widget:
            if pop.get_parent() is not None:
                pop.unparent()
            pop.set_parent(anchor_widget)
        return pop

    def _show_footnote_peek(self, key, it):
        """Show a footnote's body in the shared peek popover, anchored at
        the clicked marker letter. `key` is '{verse}:{n}' from the fnote:
        tag. Content is already in memory (no fetch), and the click doesn't
        trigger a cross-pane re-render, so unlike the dictionary peek this
        shows immediately — no stability wait, just the shared fade-in —
        and the self-heal machinery stays armed anyway in case some other
        relayout lands on it."""
        try:
            verse_s, n = key.split(':', 1)
            verse = int(verse_s)
        except ValueError:
            return
        entry = self._chapter_footnotes.get((verse, n))
        if not entry:
            return
        ftype, body, letter = entry
        r = self._view.get_iter_location(it)
        wx, wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r.x, r.y)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = (
            wx, wy, max(1, r.width), r.height)

        pop = self._ensure_peek_popover(self._view)
        # A dictionary fetch already in flight can't replace this note's
        # content when it returns.
        tasks.cancel(f'peek:{id(self)}')
        # Open on whichever side of the marker has more room, and cap the body
        # to what fits there. A translator's note is one line; a commentator's
        # is an essay (Straubinger writes 2,377 characters on Psalm 51:13), and
        # an uncapped peek that tall is unopenable — see _peek_room. That is
        # why the failure looked arbitrary: a short note two lines below the
        # unopenable one opened first time.
        avail = self._peek_room(self._view, rect, pop)
        pop.set_pointing_to(rect)

        dark = Adw.StyleManager.get_default().get_dark()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_size_request(280, -1)
        cap_text = (_('Cross-references ({letter}) · verse {v}')
                    if ftype == 'crossReference'
                    else _('Footnote ({letter}) · verse {v}')).format(
                        letter=letter, v=verse)
        cap = Gtk.Label(label=cap_text, xalign=0)
        cap.add_css_class('caption')
        cap.add_css_class('dim-label')
        content.append(cap)
        lbl = Gtk.Label(xalign=0, wrap=True)
        lbl.add_css_class('fnote-body')
        lbl.set_max_width_chars(40)
        try:
            lbl.set_markup(_html_to_markup(body, dark))
        except Exception:
            lbl.set_text(re.sub(r'<[^>]+>', '', body))
        # The caption stays put and only the note scrolls, so a long note
        # keeps the letter and verse it belongs to in view.
        content.append(self._peek_scroller(lbl, avail))
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(content, f'set_margin_{m}')(14)
        pop.set_child(content)
        # The peek is a transient panel the reader opened deliberately, and
        # its body never takes focus — announce it, or the note is silent.
        a11y.set_role(content, Gtk.AccessibleRole.NOTE)
        set_accessible_label(content, cap_text)
        a11y.labelled_by(lbl, cap)
        a11y.announce(self._view, f'{cap_text}. {lbl.get_text()}')

        self._dict_retries = 0
        self._dict_open_at = GLib.get_monotonic_time()
        self._dict_user_closed = False
        pop.set_opacity(0.0)
        pop.popup()
        self._peek_fade_in(pop)

    def _show_dict_popup_at(self, word, anchor_widget, rect):
        # A lightweight "Look Up" peek anchored at the double-clicked word,
        # not a detached window centred on the screen. Deep study still goes
        # through the Strong's lexicon panel. `anchor_widget`/`rect` say where
        # to point the arrow (the reading view, or a card label).
        #
        # The popover is *non-autohide* and reused per pane: an autohide
        # popover grabs the pointer the instant it's shown, so the very
        # double-click that opened it would read as a click-outside and dismiss
        # it. We dismiss it ourselves instead — on any click in the view
        # (_on_dict_click), a new lookup, or a module change.

        pop = self._ensure_peek_popover(anchor_widget)

        # Open the peek on whichever side of the word has more room, and cap
        # the definition height so the whole popover *fits* on that side. If it
        # doesn't fit, GTK flips it to the other side but strands the arrow on
        # the original edge (pointing away from the word) — capping avoids the
        # flip entirely. Room is measured in the window, where the popover
        # actually lives (it can extend up over the toolbar).
        root = anchor_widget.get_root()
        ok, pt = anchor_widget.compute_point(
            root, Graphene.Point().init(float(rect.x), float(rect.y)))
        word_y = pt.y if ok else rect.y
        win_h = root.get_height() if root is not None else anchor_widget.get_height()
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
            clear_children(content)

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
            return _strip_leading_headword(html, word)

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

            # Already ranked by `fetch` — re-sorting here by description
            # is what put Webster's 1913 in front of Wikcionario.
            ordered = results
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

        def _lineage_fragment():
            """The compact 'who were their parents and children' answer, for a
            word the curated genealogy table knows.

            Text, not a drawing. The peek is a 260-360px popover with its body
            capped between 140 and 320px; a chart does not fit there, and
            anything that changes the popover's natural height can bring back
            the arrow-flip the cap exists to prevent. So the fragment's own
            measured height is taken OFF the dictionary body's cap below,
            leaving the whole peek exactly as tall as it was."""
            frag = genealogy_bridge.fragment_for(
                word, self._book, self._chapter,
                getattr(self, '_peek_verse', 0) or 0)
            if frag is None:
                return None
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.add_css_class('peek-lineage')
            box.set_margin_start(18)
            box.set_margin_end(18)
            box.set_margin_top(2)
            box.set_margin_bottom(8)

            def _row(label, people, muted):
                if not people:
                    return
                r = Gtk.Label(xalign=0)
                r.add_css_class('peek-lineage-row')
                if muted:
                    r.add_css_class('dim-label')
                names = ', '.join(GLib.markup_escape_text(n)
                                  for _pid, n, _ref in people)
                r.set_markup('<b>%s</b>  %s'
                             % (GLib.markup_escape_text(label), names))
                r.set_wrap(True)
                box.append(r)

            _row(_('Parents'), frag['parents'], True)
            if frag['mother']:
                _row(_('Mother'), [(frag['mother'][0], frag['mother'][1], '')],
                     True)
            _row(_('Children'), frag['children'], True)
            if frag['note']:
                nl = Gtk.Label(label=frag['note'], xalign=0)
                nl.add_css_class('peek-lineage-note')
                nl.set_wrap(True)
                box.append(nl)
            if frag['ambiguous']:
                # Never silently pick a Zechariah: say that the name covers
                # more than one person and let the reader open the chart.
                amb = Gtk.Label(xalign=0)
                amb.add_css_class('peek-lineage-note')
                amb.set_wrap(True)
                amb.set_markup(GLib.markup_escape_text(
                    ngettext('%d other person carries this name',
                             '%d other people carry this name',
                             len(frag['ambiguous'])) % len(frag['ambiguous'])))
                box.append(amb)
            if frag['chart'] and self._on_open_lineage:
                link = Gtk.Button(label=_('See the whole line'))
                link.add_css_class('flat')
                link.add_css_class('peek-lineage-link')
                link.set_halign(Gtk.Align.START)
                link.connect('clicked', lambda *_a: self._on_open_lineage(
                    self, self._book, self._chapter,
                    getattr(self, '_peek_verse', 0) or 1))
                box.append(link)
            return box

        def populate(results):
            _clear()
            frag = _lineage_fragment()
            if frag is not None:
                content.append(frag)
                # Re-measure, do not assume: the ~130px chrome constant was
                # measured for title + tabs and knows nothing about this box.
                _min, nat = frag.measure(Gtk.Orientation.VERTICAL, -1)[:2]
                self._dict_max_body = max(
                    100, self._dict_max_body - max(nat, _min))
            if not results:
                # Names what was actually searched rather than describing what
                # dictionaries hold. The old line taught that they "index
                # proper nouns and key terms" and offered “covenant,”
                # “Abraham,” “atonement” — true of Easton's, false of the
                # general dictionary the Spanish reader has (Wikcionario
                # answers ordinary vocabulary), and the English examples were
                # the wrong words to try in any case.
                _status('scriptura-system-search-symbolic',
                        _('No entry for “%s”') % word,
                        (_('Searched %s. Another dictionary may carry it — '
                           'the Module Manager lists more.')
                         % ', '.join(searched)) if searched else
                        _('Another dictionary may carry it — the Module '
                          'Manager lists more.'))
            else:
                content.append(_headword_title(word))
                if len(results) == 1:
                    mn, md, html = results[0]
                    _add_text(html, source=_short_dict_title(mn, md))
                else:
                    _build_source_tabs(results)

        def show_no_dicts():
            _clear()
            frag = _lineage_fragment()
            if frag is not None:
                # The table answers even with no dictionary installed, which is
                # the common case in a language whose only dictionary is a
                # general one.
                content.append(_headword_title(word))
                content.append(frag)
                return
            _status('scriptura-dialog-information-symbolic',
                    _('No dictionaries installed'),
                    # Named two English dictionaries by name, which is the
                    # wrong advice for a reader who reads in Spanish.
                    _('Add one from the Module Manager, then double-click '
                      'the word again.'))

        # Filled by `fetch` so the empty state can name what it looked in.
        searched: list = []

        def fetch(_task):
            dicts = sword_bridge.installed_dict_modules()
            if not dicts:
                return None
            searched[:] = [_short_dict_title(mn, md) for mn, md in dicts]
            # Which tab opens matters more than which tabs exist. Two things
            # decide it, in this order:
            #
            #   * an exact hit beats a de-inflected one. The de-inflection is
            #     English, so it strips the `s` from Spanish `pues` and finds
            #     Webster's `Pue` — "to make a low whistling sound; to chirp,
            #     as birds" — a confident answer to a question nobody asked.
            #   * then the reading module's own language. A reader in a
            #     Spanish Bible should not have to click past French to
            #     reach Spanish.
            #
            # Everything still gets a tab; this only chooses which one is
            # already open.
            lang = sword_bridge.module_language(self._module)
            results = []
            for mod_name, mod_desc in dicts:
                html, exact = sword_bridge.lookup_dict_entry(mod_name, word)
                if html:
                    same = bool(lang) and \
                        sword_bridge.module_language(mod_name) == lang
                    results.append((mod_name, mod_desc, html, exact, same))
            results.sort(key=lambda r: (not r[3], not r[4], r[1].lower()))
            return [(mn, md, html) for mn, md, html, _e, _s in results]

        # Latest-wins on the shared peek key: a newer lookup, footnote, or
        # anchored peek supersedes this fetch, so a late return can't
        # overwrite the popover's current content. A raised lookup lands as
        # "no entry" instead of stranding the spinner (details in the log).
        tasks.submit(f'peek:{id(self)}', fetch,
                     lambda results: (show_no_dicts() if results is None
                                      else populate(results)),
                     on_error=lambda _exc: populate([]))
        return GLib.SOURCE_REMOVE

    # ── Lexicon panel delegators ─────────────────────────────────────────

    def _lex_scan_module(self):
        """Module the lexicon panel's word-study scan reads. The interlinear
        pseudo-modules have no SWORD text (the scan would find 0 matches for
        every word), so they scan the tagged original-language source the
        morph lookups already rely on — MorphGNT for the Greek NT, OSHB for
        the Hebrew OT. Absent those, fall through to the pane's own module
        (scan degrades to empty, as any untagged module's would)."""
        if self._is_interlinear:
            tagged = ('OSHB' if interlinear_data.is_hebrew(self._module)
                      else 'MorphGNT')
            if tagged in sword_bridge.module_names():
                return tagged
        return self._module

    def show_lexicon_loading(self, strong_num):
        """Reveal the lexicon panel with a spinner immediately when the
        user clicks a Strong's word. The actual content arrives later
        via show_lexicon(). Without this the panel is blank for several
        hundred ms on the first click of a session while SWORD warms up."""
        self._lex_panel.set_context(self._book, self._lex_scan_module())
        chain, text = getattr(self, '_current_phrase', (None, None))
        self._lex_panel.show_loading(strong_num,
                                     morph=self._current_morph,
                                     phrase_chain=chain,
                                     phrase_text=text)

    def show_lexicon(self, strong_num, text, morph=None, phrase=(None, None)):
        """Called from window.py on Bible-text word click. The window has
        already fetched the definition text asynchronously and passes the
        morph + phrase snapshot taken at click time — threaded through rather
        than re-read here, so a rapid second click can't swap them under us."""
        self._lex_panel.set_context(self._book, self._lex_scan_module())
        chain, ptext = phrase
        self._lex_panel.show(strong_num, text,
                             morph=morph,
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
        self._update_font_css()
        self._apply_reading_page_edge()
        # The indicator bakes its background at creation, and _ensure_current_
        # verse_tag hands back an existing tag without looking at its colour.
        # Drop it here rather than on the recolour path alone: a pane showing a
        # devotional still holds the tag from the Bible it showed before, and
        # would go back to that Bible wearing the other theme's purple.
        table = self._buffer.get_tag_table()
        cv = table.lookup(self._CURRENT_VERSE_TAG_NAME)
        if cv is not None:
            table.remove(cv)
        if self._is_verse_navigable() and self._rendered_verses is not None:
            # Same text, new colours: recolour it where it stands. Rebuilding
            # the chapter to change four values threw the reading position
            # away and then spent the whole anchor apparatus recovering it.
            self._recolour_for_theme()
        else:
            self._fetch_and_render()

    def _recolour_for_theme(self):
        """Repaint the chapter's theme-dependent colours without a re-render.

        Three kinds of colour live in the buffer, and only these three: the
        `_ink_*` spans the render adopted, which can simply be set; the tags
        whose NAME carries the colour (`hl_bg_<rgba>` and the current-verse
        indicator), which cannot be mutated and are re-applied instead; and
        the colours BibleTextView resolves at paint time, which need nothing
        but a redraw.
        """
        dark = Adw.StyleManager.get_default().get_dark()
        ink = theme_ink(dark)
        table = self._buffer.get_tag_table()
        for name, hexcol in ink.items():
            tag = table.lookup(name)
            if tag is not None:
                tag.set_property('foreground', hexcol)
        # The cap is the one entry in that table whose colour is conditional:
        # the loop above just set a foreground on it, which would light up a
        # cap the reader has turned off. This has the last word.
        self._sync_dropcap_ink()
        # Created lazily on first hover and outlives the render, so it is the
        # one span the adoption pass never sees.
        hover = table.lookup('_strg_hover')
        if hover is not None:
            hover.set_property('foreground', ink['_ink_link'])

        # The highlight band's colour is read back out of its tag name by the
        # view, and orange is muted in dark mode — so the band a reader put on
        # a verse has to be re-applied under the other theme's name.
        annos = annotations.get_annotations(
            self._module, self._book, self._chapter) or {}
        for verse, anno in annos.items():
            try:
                self._apply_anno_tags(int(verse), anno)
            except (TypeError, ValueError):
                continue

        # `_on_theme_changed` dropped the indicator tag; re-applying mints it
        # against the new theme.
        if self._selected_verse is not None:
            self._set_current_verse_indicator(self._selected_verse)
        self._view.queue_draw()

    def _apply_reading_page_edge(self):
        """Hairline card border in light mode only — in dark the pale border
        reads as a boxy outline on the already-recessed surface."""
        dark = Adw.StyleManager.get_default().get_dark()
        if dark:
            self._lex_paned.add_css_class('reading-page-flush')
        else:
            self._lex_paned.remove_css_class('reading-page-flush')

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
        # Devotionals keep the date bar in the chrome band — reserve its
        # height too (the switch re-renders anyway, so no mid-read reflow).
        self._sync_view_top_margin()
        # Sync / chapter-note / per-pane search are only meaningful when
        # the pane is rendering a verse-keyed chapter. Devotionals get
        # date navigation instead; Generic Books get the TOC button.
        self._sync_btn.set_visible(
            is_chapter_keyed or self._is_catena or self._is_imagery
            or self._is_interlinear)
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
        # Same for the keyboard cursor: its verse and word offsets belong to
        # the outgoing module's buffer.
        self._cursor.clear()
        self._current_unit = None
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
        if self._on_module_switched:
            self._on_module_switched()

    def select_verse(self, verse_num):
        """Called by other panes broadcasting a verse selection."""
        self._content.on_verse(verse_num)

    def _broadcast_verse_to_text(self, verse_num):
        """Move the text view's selected-verse indicator to a broadcast verse,
        scrolling to it when it's on screen. Modes rendering into the text view
        without matching verse tags (devotionals, generic books) harmlessly
        find none."""
        # The broadcast speaks app-space; this pane's rendered verse
        # numbers are its module's own — translate before touching tags
        # (no-op for app-keyed modules).
        verse_num = sword_bridge.map_target_verse(
            self._module, self._book, self._chapter, verse_num)
        self._selected_verse = verse_num
        self._set_current_verse_indicator(verse_num)
        self._cursor.sync_to(verse_num)
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
