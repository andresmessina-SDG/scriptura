"""The Today page — a calm pre-reading landing surface ("Morning Office").

Shown once per session over the reading layout when the app opens (opt-out
via the menu panel's "Open to Today" switch). Pure typography on the reading
paper: the date, the active plan's day as a serif hero line, a whispered
progress phrase, and — when a devotional module is installed — today's
devotional quote set at the foot like a printed epigraph.

The page is deliberately standalone: it composes reading_plans, the
last-position settings, and the devotional bridge, and never touches
BiblePane internals. Any action on it navigates in and the surface slides
away; Esc skips it; nothing on it demands anything (GUIDANCE §9 — calm
technology, no gamification).
"""

import datetime
import math
import re

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gsk', '4.0')
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Adw, Pango

# Slavonic and Greek carry their accents as COMBINING marks, and a mark is
# only drawn over its letter when the font gives it zero advance. Georgia —
# a reading face the picker offers, and one people choose — does not: at 19px
# the acute takes 13px of its own, wider than the letter it belongs to, so
# «Све́тлую» draws as "Све ́тлую" with the mark stranded after the vowel. The
# reading pane already guards Greek and Hebrew this way (pane._GREEK_FONT);
# the Today epigraph takes the reader's chosen family too, and until the
# Orthodox tradition began carrying Church Slavonic there was nothing
# accented for it to render.
#
# A Pango attribute rather than a CSS class: it does not depend on winning a
# cascade against the family this label is given live, and it is measurable —
# with it the acute's advance goes from 13px to 0 in roman and italic alike.
_MARK_SAFE_SERIF = 'Noto Serif, DejaVu Serif, Source Serif 4, serif'
_COMBINING_MARK = re.compile('[\u0300-\u036f]')


def _mark_safe_attrs(text: str) -> 'Pango.AttrList | None':
    """A font attribute for text whose marks must sit on their letters, or
    None when there are none and the reader's own face should stand."""
    if not _COMBINING_MARK.search(text):
        return None
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_family_new(_MARK_SAFE_SERIF))
    return attrs


import reading_plans
import scribal_field
from a11y import set_accessible_label
from gtk_utils import DelayedPulse
from i18n import _, book_label, format_date, weekday_name

# Longest epigraph we'll set at the foot — beyond this the quote is cut at a
# word boundary. Devotional opening quotes are a verse line, almost always
# shorter; the cap only guards against unusually chatty modules.
_EPIGRAPH_MAX = 240

# The antiphon is one line, not a paragraph: a long verse is cut at a word.
_ANTIPHON_MAX = 150

# The foot's own measure. The epigraph ran 565px against a 313px hero, so the
# page's centre of gravity was a footnote — a foot block is capped narrower
# than the column it closes and can no longer out-measure the day's reading.
_EPIGRAPH_MEASURE = 560

# ── The paper ─────────────────────────────────────────────────────────────
# The surface was laid paper — the wire marks of a mould — until the page
# gained an abecedary to stand on. Laid paper is the substrate of a PRINTED
# Bible and its 5px pitch ran a second rhythm under the letters' 44px one;
# the ground is now prepared skin, with the alphabet written in the margins.
# See scribal_field, which draws it.
#
# Every stroke there is still the reader's OWN ink, so sepia, a dark paper
# and the Night Light dusk blend all carry for free and the page never gains
# a colour that did not come from it (the material rule the listening pill
# set — GUIDANCE §9).
_VIGNETTE_ALPHA = 0.032

# Ornament: the headpiece that opens the page (a lozenge between two rules)
# and the tailpiece that closes it (an asterism of three). Drawn as paths,
# never typed — a fleuron character would depend on a font the reader may
# have swapped out, and Georgia has no ornament block at all.
_ORNAMENT_ALPHA = 0.22

# The margin rail's measure: what the date line asks for whole in the widest
# language the app ships — English 207px, Russian 259, Spanish 265 (measured)
# — because the rail's first line is a date, and a date that folds reads as a
# mistake. Sized for English alone it folded in both other languages.
#
# A size request is a MINIMUM and cannot cap a wrapping label — left to it the
# rail measured 275px and shouldered the column off the page's centre. Only
# max-width-chars caps a label's natural width, so the rail's measure is set
# in characters and the pixel figure is the floor beneath it.
# Shares of the page's spare height above and below the type block. The
# block rises by slack x (below - above) / (2 x total) — a tenth here.
_RISE_ABOVE = 2
_RISE_BELOW = 3

# The margins either side of the column. The default gutter is the mark's
# own width plus its gap from the type; the wide one is what the rail asks
# for, and the marks simply move to its inner edge.
# The page's three spacings, on the house 4px grid. Its gap ladder used to
# run 20-6-30-14-8-24-16-16-28-32, where the difference between "inside a
# group" and "between groups" was about 8px and the whole column therefore
# read as one evenly-spread list.
_GAP_TIGHT = 8     # lines of one voice (date and designation)
_GAP_CLOSE = 12    # within a block (reference, its verse, its whisper)
_GAP_BLOCK = 40    # between the page's blocks

_MARK_SIZE = 58
_MARK_GAP = 16     # between the marks when they share the column at narrow
# The gutter is the mark's width plus room to sit clear of both the type and
# the window's edge — at the mark's width plus one gap the disc was tangent
# to the window and the rounded corner cut it.
_GUTTER = _MARK_SIZE + 2 * _MARK_GAP

_RAIL_WIDTH = 268
_RAIL_MARGIN = 36
_RAIL_CHARS = 34

# The wide margin is the rail's own measure; the marks move to its inner edge.
_GUTTER_WIDE = _RAIL_WIDTH + _RAIL_MARGIN

# Where the rail opens: the first width at which a page carrying one still
# gives the column everything it would have had without it.
_WIDE_AT = 720 + 2 * _GUTTER_WIDE


def _stop(offset: float, color: 'Gdk.RGBA') -> 'Gsk.ColorStop':
    stop = Gsk.ColorStop()
    stop.offset = offset
    stop.color = color
    return stop


def _draw_lozenge(cr, cx, cy, r):
    cr.move_to(cx, cy - r)
    cr.line_to(cx + r, cy)
    cr.line_to(cx, cy + r)
    cr.line_to(cx - r, cy)
    cr.close_path()
    cr.fill()


def progress_whisper(day_n: int, total: int) -> str:
    """One quiet, unit-free phrase for how far along the plan is. No numbers,
    no bars — shame-free to the point of near-silence (the day count already
    lives in the kicker line)."""
    if total <= 1 or day_n < 1:
        return ''
    f = day_n / total
    if f < 0.10:
        return _('just getting started')
    if f < 0.35:
        return _('about a quarter of the way through')
    if f < 0.48:
        return _('coming up on halfway')
    if f < 0.55:
        return _('right about halfway')
    if f < 0.62:
        return _('a little past halfway')
    if f < 0.85:
        return _('well into the second half')
    if f < 0.97:
        return _('nearly finished')
    return _('the final days')


def passage_display(readings: list[reading_plans.Reading]) -> str:
    """The day's readings with full localized book names — the hero line
    speaks in 'Psalms 111–115', not the menu column's 'Ps 111–115'."""
    parts = []
    for book, start, end in reading_plans.group_readings(readings):
        b = book_label(book)
        parts.append(f'{b} {start}' if start == end else f'{b} {start}–{end}')
    return ' · '.join(parts)


def _strip_tags(fragment: str) -> str:
    # sword_bridge.plain_text, not a local strip: a bare one leaves the
    # space its tag stood in sitting before the comma, and the epigraph
    # read "loved the world , that he gave".
    import sword_bridge
    return sword_bridge.plain_text(fragment)


# Hour from which the epigraph takes a two-section devotional's *evening*
# portion (SME-style modules pack morning + evening into one entry).
# Evensong hour — a starting value, tunable to taste.
EVENING_HOUR = 16

_QUOTE_RE = re.compile(
    r'<hi\b[^>]*type=["\']italic["\'][^>]*>(.*?)</hi>', re.DOTALL)
_REF_RE = re.compile(r'<reference\b[^>]*>(.*?)</reference>', re.DOTALL)


def parse_epigraph(raw_osis: str, evening: bool = False) -> tuple[str, str] | None:
    """Extract (quote, reference_display) from a devotional entry's raw OSIS.

    Devotional sections open with an italic scripture line plus a
    <reference> link (the same shape devotional.render_osis keys sections
    on). When the entry carries two such sections (Morning & Evening in one
    entry, SME-style) and `evening` is set, the second section's quote is
    taken — the foot of the page stays truthful to the hour. Returns None
    when there's no usable quote — the epigraph is whole or not at all."""
    if not raw_osis:
        return None
    # Prefer a proper section block (italic + reference in one <p>); fall
    # back to the whole entry for unstructured modules.
    sections = [p for p in re.findall(r'<p\b[^>]*>(.*?)</p>', raw_osis, re.DOTALL)
                if _QUOTE_RE.search(p) and _REF_RE.search(p)]
    if len(sections) >= 2 and evening:
        target = sections[1]
    elif sections:
        target = sections[0]
    else:
        target = raw_osis
    quote_m = _QUOTE_RE.search(target)
    if not quote_m:
        return None
    quote = _strip_tags(quote_m.group(1)).strip('"“”')
    if not quote:
        return None
    if len(quote) > _EPIGRAPH_MAX:
        cut = quote.rfind(' ', 0, _EPIGRAPH_MAX)
        quote = quote[:cut if cut > 0 else _EPIGRAPH_MAX].rstrip(' ,;:') + '…'
    ref_m = _REF_RE.search(target)
    ref = _strip_tags(ref_m.group(1)) if ref_m else ''
    return quote, ref


def fetch_antiphon(module: str, book: str, chapter: int) -> str | None:
    """The opening line of today's appointed reading, or None.

    The office books open a day with an antiphon — one sentence carrying the
    emphasis of the occasion, said before the psalm. This page had no
    Scripture on it at all: the hero is a reference, and the foot is a
    devotional module's quote, which is an optional install and which a
    chosen church calendar displaces. A reader with a calendar and no
    devotional opened a Bible to a page with no Bible on it.

    Verse 1 of the first appointed chapter, not a chosen "verse of the day":
    it needs no curation, it cannot be wrong, and it is literally where
    today's reading opens. The reader's own module answers, so it arrives in
    their translation and their language.

    Through `content`, never `sword_bridge`: an eBible key answers [] from
    the SWORD bridge without raising (GUIDANCE — one way in to a chapter).
    Blocking work — call from a task worker.
    """
    import content
    import sword_bridge
    verses = content.load_chapter(module, book, chapter)
    if not verses:
        return None
    # Verse 0 is a Psalm superscription or a book preamble where a module
    # carries one — the day opens at verse 1 wherever there is one.
    numbered = [v for v in verses if v[0] >= 1] or verses
    text = sword_bridge.plain_text(numbered[0][1]).strip()
    if not text:
        return None
    if len(text) > _ANTIPHON_MAX:
        cut = text.rfind(' ', 0, _ANTIPHON_MAX)
        text = text[:cut if cut > 0 else _ANTIPHON_MAX].rstrip(' ,;:') + '…'
    return text


def fetch_epigraph(collect_key: str | None = None
                   ) -> tuple[str, str, bool] | None:
    """Today's epigraph: (text, source_line, quoted).

    The day's prayer wins the slot. Choosing a church calendar is a reader
    asking to be shown their own tradition's day, so it would be odd for a
    devotional module to go on answering over it — and a devotional speaks
    every day, which would mean the collects were never seen at all.

    A devotional module takes the slot when no calendar is chosen, and on the
    days a chosen calendar cannot fill: coverage is partial by design, and a
    reader who has a devotional installed would rather hear it than nothing.
    `collect_key` is the church_year designation key. Blocking SWORD work —
    call from a task worker. None when neither yields.
    """
    import sword_bridge
    if collect_key:
        import collects
        import i18n
        # The collect is read in whatever language the reader has the app in
        # — a tradition that carries its own text answers, and English
        # stands in per key where it does not.
        found = collects.collect_for(collect_key, i18n.current_language())
        if found:
            return found[0], found[1], False
    evening = datetime.datetime.now().hour >= EVENING_HOUR
    for name in sword_bridge.installed_devotional_modules():
        raw = sword_bridge.get_devotional_raw(name)
        parsed = parse_epigraph(raw, evening)
        if parsed:
            quote, ref = parsed
            desc = sword_bridge.module_info(name)['description'] or name
            # Module descriptions often carry a subtitle after a colon
            # ("… Morning and Evening: Daily Readings") — too loud for a
            # foot line. The reference's own colons are never touched.
            desc = desc.split(':', 1)[0].strip()
            source = f'{ref} — {desc}' if ref else desc
            return quote, source, True
    return None


class TodayView(Gtk.Box):
    """The Morning Office surface. The window owns showing/dismissing it;
    this widget owns its content and look."""

    def __init__(self, on_begin, on_continue, on_choose_plans,
                 on_listen=None, on_write=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('today-view')
        self._on_begin = on_begin
        self._on_continue = on_continue
        self._on_choose_plans = on_choose_plans
        self._on_listen = on_listen
        self._on_write = on_write
        self._begin_target = None      # (book, chapter) for the plan day
        self._continue_target = None   # (book, chapter) for last position
        self._mode = ''          # '' | 'narrow' | 'wide' (breakpoints)
        self._marks_move_queued = False
        self._church_line = None
        self._css = Gtk.CssProvider()
        self.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._serif_css = Gtk.CssProvider()
        self._card_css = Gtk.CssProvider()
        self._ink = '#888888'
        self._surface = '#ffffff'

        # No vexpand: the row takes the height of its type and the page's
        # spacers place it. With it the clamp swallowed the page's slack and
        # left the column standing at the top of a tall empty box.
        self._clamp = clamp = Adw.Clamp(
            maximum_size=720, tightening_threshold=640, hexpand=True)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        v.set_margin_top(40)
        v.set_margin_bottom(40)
        v.set_margin_start(24)
        v.set_margin_end(24)
        clamp.set_child(v)
        # The page is a column with a margin either side, and the margins are
        # structural: they hold their width whether or not anything is in
        # them, so the type never shifts off the page's centre when a mark
        # appears. Both marks — the spoken devotional and the journal door —
        # live there rather than in the run of type, because neither is
        # reading, and a page whose design law is "one vertical run of type"
        # cannot carry three centred links down its middle.
        #
        # Margins rather than overlay children: an overlay child is anchored
        # to the WINDOW, and at 1440px the listen disc stood 400px clear of
        # the words it belonged to. As row siblings the marks are in the
        # column's own margin at every width, with nothing to recompute on
        # resize, and the pair keeps the column centred by construction.
        #
        # The rail sits in the left margin at FILL, so its first line lands
        # on the column's first line with no arithmetic.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        # An Overlay, not a box: the rail sits at the head of the margin and
        # the mark at its middle, and stacking them would have pushed the
        # mark down by the rail's height on one side of the page only.
        self._margin_left = Gtk.Overlay()
        self._margin_left.set_size_request(_GUTTER, -1)
        self._margin_left.set_child(self._build_write_mark())
        self._margin_left.add_overlay(self._build_rail())
        self._margin_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._margin_right.set_size_request(_GUTTER, -1)
        self._margin_right.append(self._build_listen_card())
        row.append(self._margin_left)
        row.append(clamp)
        row.append(self._margin_right)
        # The row as a whole is clamped to the column plus its two margins.
        # Without it the page's spare width went to the inner clamp, which
        # then centred the column inside ITSELF — the marks hugging the
        # clamp's edge while the type stood 140px further in. Clamping the
        # row instead leaves the inner clamp exactly the column's width, so a
        # mark 16px off its edge is 16px off the words at every size.
        self._row_clamp = Adw.Clamp(maximum_size=720 + 2 * _GUTTER,
                                    tightening_threshold=720 + 2 * _GUTTER)
        self._row_clamp.set_child(row)

        # Optically centred, not geometrically: a block of type set on the
        # exact middle of a page reads as having sunk. The rise is bought by
        # splitting the page's slack 2:3 between the spacers above and below
        # — a tenth of whatever is spare, the printer's ~5% — rather than
        # with a fixed margin, which measured as part of the page's minimum
        # height and made a 700px window overflow by the rise's own amount.
        # NOT `for _ in ...`: `_` is gettext, and naming a loop variable after
        # it shadows the catalogue for the whole function (the trap this
        # file's own i18n notes already record).
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for _i in range(_RISE_ABOVE):
            page.append(Gtk.Box(vexpand=True))
        page.append(self._row_clamp)
        for _i in range(_RISE_BELOW):
            page.append(Gtk.Box(vexpand=True))

        # vexpand so the page fills the view; without it the box packs it at
        # its natural height and everything inside centres within that shrunk
        # block, sitting low on the surface.
        page.set_vexpand(True)

        # A short window must not cost the reader the foot of the page: the
        # page's blocks are 40px apart now and the day's verse is on it, so
        # the full state asks for 748px where a 700px window had been clipping
        # the tailpiece off. The viewport gives the page the whole height
        # whenever there is enough of it — the spacers still centre the type
        # and nothing scrolls — and hands back a scroll only when there is not.
        #
        # The page answers the width it is GIVEN, not the window's: on a
        # split screen this surface is a pane, and a breakpoint read off the
        # window would set a 54px hero in a 500px column. An
        # Adw.BreakpointBin measures its own allocation, which is the pane.
        bin_ = Adw.BreakpointBin(width_request=300, height_request=200)
        # The scroller goes INSIDE the bin, not around it: a BreakpointBin
        # reports its own size request as its minimum and lets its child
        # overflow, so a viewport above it believes the page fits and squeezes
        # it instead of scrolling.
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(page)
        bin_.set_child(scroller)
        self._narrow_bp = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse('max-width: 640px'))
        self._narrow_bp.add_setter(clamp, 'maximum-size', 560)
        self._narrow_bp.add_setter(clamp, 'tightening-threshold', 480)
        # No margins at all when there is no width to spare — the marks come
        # into the column instead (_place_marks).
        self._narrow_bp.add_setter(self._margin_left, 'width-request', 0)
        self._narrow_bp.add_setter(self._margin_right, 'width-request', 0)
        self._narrow_bp.add_setter(self._row_clamp, 'maximum-size', 560)
        self._narrow_bp.add_setter(self._row_clamp, 'tightening-threshold', 560)
        self._narrow_bp.connect('apply', lambda _b: self._set_mode('narrow'))
        self._narrow_bp.connect('unapply', lambda _b: self._set_mode(''))
        # 1328 is where the rail starts costing nothing: the two margins
        # take 2 x 304px, so at 1328 the column is still the 720 it gets
        # without a rail, and every pixel past that goes to the column until
        # it reaches 780. Set at 1400 — the width at which the column is at
        # its widest — the rail simply never appeared on a 1366px screen,
        # which is most laptops.
        self._wide_bp = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse(f'min-width: {_WIDE_AT}px'))
        self._wide_bp.add_setter(clamp, 'maximum-size', 780)
        self._wide_bp.add_setter(clamp, 'tightening-threshold', 700)
        self._wide_bp.add_setter(self._margin_left, 'width-request', _GUTTER_WIDE)
        self._wide_bp.add_setter(self._margin_right, 'width-request',
                                 _GUTTER_WIDE)
        _wide_row = 780 + 2 * _GUTTER_WIDE
        self._wide_bp.add_setter(self._row_clamp, 'maximum-size', _wide_row)
        self._wide_bp.add_setter(self._row_clamp, 'tightening-threshold',
                                 _wide_row)
        self._wide_bp.connect('apply', lambda _b: self._set_mode('wide'))
        self._wide_bp.connect('unapply', lambda _b: self._set_mode(''))
        bin_.add_breakpoint(self._narrow_bp)
        bin_.add_breakpoint(self._wide_bp)

        self.append(bin_)

        # The headpiece: a page of an office book opens with an ornament,
        # and this one sets the date line under something rather than under
        # nothing.
        self._headpiece = self._build_ornament(self._draw_headpiece, 140, 12)
        self._headpiece.set_margin_bottom(_GAP_BLOCK)
        v.append(self._headpiece)

        def _centered(label: Gtk.Label) -> Gtk.Label:
            """Multi-line voice (hero, epigraph verse): wraps at the clamp."""
            label.set_halign(Gtk.Align.CENTER)
            label.set_justify(Gtk.Justification.CENTER)
            label.set_wrap(True)
            label.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
            return label

        def _line(label: Gtk.Label) -> Gtk.Label:
            """One-line voice (the tracked caps lines, the whisper). NEVER
            uses wrap: a letter-spaced label folds its last word even when
            allocated exactly its natural width (measured — GTK rounds the
            tracked width short when it sets the layout width), so a line
            that must stay a line gets no layout width at all."""
            label.set_halign(Gtk.Align.CENTER)
            label.set_wrap(False)
            return label

        self._eyebrow = _line(Gtk.Label())
        self._eyebrow.add_css_class('today-eyebrow')
        v.append(self._eyebrow)

        # Church-year line (opt-in via the church_calendar setting): a
        # second whisper under the date, e.g. "The Sixth Sunday after
        # Trinity". Hidden when the setting is None or nothing applies.
        self._church = _line(Gtk.Label())
        self._church.add_css_class('today-church')
        self._church.set_margin_top(_GAP_TIGHT)
        self._church.set_visible(False)
        v.append(self._church)

        self._kicker = _line(Gtk.Label())
        self._kicker.add_css_class('today-kicker')
        self._kicker.set_margin_top(_GAP_BLOCK)
        v.append(self._kicker)

        self._passage = _centered(Gtk.Label())
        self._passage.add_css_class('today-passage')
        self._passage.set_margin_top(_GAP_CLOSE)
        self._passage.get_style_context().add_provider(
            self._serif_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        v.append(self._passage)

        # The day's own opening line, under the reference that names it.
        # Below rather than above (where an office book's antiphon stands):
        # a reference and then the words it points at reads as a title and
        # its opening, and it keeps the caps-to-hero run unbroken.
        self._antiphon = _centered(Gtk.Label())
        self._antiphon.add_css_class('today-antiphon')
        self._antiphon.set_margin_top(_GAP_CLOSE)
        self._antiphon.get_style_context().add_provider(
            self._serif_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._antiphon.set_visible(False)
        v.append(self._antiphon)

        self._whisper = _line(Gtk.Label())
        self._whisper.add_css_class('today-whisper')
        # The reading serif, not the UI sans: it was the one lowercase line
        # in the upper page set in the structural voice, and it is a phrase
        # about the reading rather than a label on it.
        self._whisper.get_style_context().add_provider(
            self._serif_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._whisper.set_margin_top(_GAP_CLOSE)
        v.append(self._whisper)

        # Where the marks stand when the pane is too narrow to have margins:
        # under the hero, side by side in the column, instead of on top of
        # the line the disc used to cover (§5 — "the disc overlaps the text").
        self._listen_slot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=_MARK_GAP)
        self._listen_slot.set_halign(Gtk.Align.CENTER)
        self._listen_slot.set_margin_top(_GAP_BLOCK)
        self._listen_slot.set_visible(False)
        v.append(self._listen_slot)

        self._begin_btn = Gtk.Button()
        self._begin_btn.add_css_class('flat')
        self._begin_btn.add_css_class('today-go')
        # Its own provider, like the serif labels below: a provider added to
        # a widget's style context styles that widget, so a descendant rule
        # on .today-view would never reach the button.
        self._go_css = Gtk.CssProvider()
        self._begin_btn.get_style_context().add_provider(
            self._go_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._begin_btn.set_halign(Gtk.Align.CENTER)
        self._begin_btn.set_margin_top(_GAP_BLOCK)
        self._begin_btn.connect('clicked', self._on_begin_clicked)
        v.append(self._begin_btn)

        self._continue_btn = Gtk.Button()
        self._continue_btn.add_css_class('flat')
        self._continue_btn.add_css_class('today-quiet')
        self._continue_btn.set_halign(Gtk.Align.CENTER)
        self._continue_btn.set_margin_top(_GAP_CLOSE)
        self._continue_btn.connect(
            'clicked', lambda _b: self._on_continue(self._continue_target))
        v.append(self._continue_btn)

        self._epigraph_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._epigraph_verse = _centered(Gtk.Label())
        self._epigraph_verse.add_css_class('today-epigraph-verse')
        self._epigraph_verse.get_style_context().add_provider(
            self._serif_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._epigraph_box.append(self._epigraph_verse)
        # One line like the other caps voices, but this one can run long
        # (module descriptions), so it ellipsizes rather than pinning the
        # window's minimum width at narrow sizes. halign FILL, not CENTER:
        # a tracked label given exactly its natural width ellipsizes anyway
        # (GTK measures tracked text one letter-space short — probed), so
        # let it have the clamp's full width and centre via xalign.
        self._epigraph_src = _line(Gtk.Label())
        self._epigraph_src.set_halign(Gtk.Align.FILL)
        self._epigraph_src.set_hexpand(True)
        self._epigraph_src.set_ellipsize(Pango.EllipsizeMode.END)
        self._epigraph_src.add_css_class('today-epigraph-src')
        self._epigraph_src.set_margin_top(_GAP_TIGHT)
        self._epigraph_box.append(self._epigraph_src)
        self._epigraph_box.set_visible(False)
        foot = Adw.Clamp(maximum_size=_EPIGRAPH_MEASURE,
                         tightening_threshold=_EPIGRAPH_MEASURE)
        foot.set_margin_top(_GAP_BLOCK)
        foot.set_child(self._epigraph_box)
        v.append(foot)

        # The tailpiece: three lozenges, the printer's asterism, closing the
        # page under whatever the last voice on it turned out to be.
        self._tailpiece = self._build_ornament(self._draw_tailpiece, 140, 12)
        self._tailpiece.set_margin_top(_GAP_BLOCK)
        v.append(self._tailpiece)

    # ── The page itself: paper, ornament, and the width it is given ──────

    def do_snapshot(self, snapshot):
        """Paint the laid paper under everything, then the page on top.

        A drawn surface rather than an image: the texture is struck from the
        reader's live ink, so it costs nothing to ship and cannot be the one
        object on the page that did not come from the reader's own choices.

        Render nodes, NOT cairo. Measured at 1366x700: the cairo version cost
        14.3ms a paint, of which the vignette's radial gradient alone was
        12.6, and `append_cairo` also rasterises and uploads a full-window
        surface every frame. The page repaints on every frame of an animation
        — the menu sliding in while this page slides away — so a whole frame
        budget spent on the background is what made opening the menu stall.
        As nodes the same paper is a gradient the GPU draws and ~150 one-pixel
        colour quads.
        """
        w, h = self.get_width(), self.get_height()
        try:
            if w > 0 and h > 0:
                self._snapshot_paper(snapshot, w, h)
        except Exception:
            # The ground is decoration and the page is not. When the sheet
            # raised here the exception left do_snapshot before the line
            # below, so the whole page painted NOTHING — a widget briefly
            # reporting a size cairo will not take cost the reader the words.
            # Nothing under here is ever worth that, so it is caught whole.
            pass
        Gtk.Box.do_snapshot(self, snapshot)

    def _ink_rgb(self):
        ink = Gdk.RGBA()
        ink.parse(self._ink)
        return ink.red, ink.green, ink.blue

    def _paper_rgb(self):
        paper = Gdk.RGBA()
        paper.parse(self._surface)
        return paper.red, paper.green, paper.blue

    def _snapshot_paper(self, snapshot, w, h):
        # The slight settling of tone toward the edges that any real sheet
        # has under a lamp, keeping the centre of the page — where the type
        # is — the calmest thing on the surface.
        #
        # Black rather than the reader's ink: the one mark here that is not
        # struck from it, because this is a shadow and not something written.
        # In ink it inverted on a dark paper, the edges LIT UP and the page
        # glowed outward, exactly backwards.
        shadow = Gdk.RGBA()
        shadow.red = shadow.green = shadow.blue = 0.0
        shadow.alpha = _VIGNETTE_ALPHA
        clear = Gdk.RGBA()
        clear.red = clear.green = clear.blue = clear.alpha = 0.0

        # The skin and the writing on it, struck once per (size, paper, ink)
        # and blitted after. Drawing it costs ~43ms at 1366x733 and the page
        # repaints on every frame of an animation — the menu sliding in
        # while this page slides away — so it can never be drawn per frame.
        sheet = scribal_field.sheet(int(w), int(h), self.get_scale_factor(),
                                    self._paper_rgb(), self._ink_rgb())
        if sheet is not None:
            snapshot.append_texture(sheet, Graphene.Rect().init(0, 0, w, h))

        radius = math.hypot(w, h) / 2
        snapshot.append_radial_gradient(
            Graphene.Rect().init(0, 0, w, h),
            Graphene.Point().init(w / 2, h / 2), radius, radius, 0.45, 1.0,
            [_stop(0.0, clear), _stop(1.0, shadow)])

    def _build_ornament(self, draw_func, width, height):
        area = Gtk.DrawingArea()
        area.set_content_width(width)
        area.set_content_height(height)
        area.set_halign(Gtk.Align.CENTER)
        area.set_can_target(False)
        area.set_draw_func(lambda _a, cr, w, h: draw_func(cr, w, h))
        return area

    def _draw_headpiece(self, cr, w, h):
        """A lozenge between two rules — the mark that opens a page."""
        r, g, b = self._ink_rgb()
        cr.set_source_rgba(r, g, b, _ORNAMENT_ALPHA)
        cx, cy = w / 2, h / 2
        _draw_lozenge(cr, cx, cy, 4.0)
        cr.set_line_width(1.0)
        for direction in (-1, 1):
            near = cx + direction * 14
            far = cx + direction * (w / 2)
            cr.move_to(near, cy + 0.5)
            cr.line_to(far, cy + 0.5)
        cr.stroke()

    def _draw_rail_rule(self, cr, w, h):
        """One hairline, the headpiece's rule at the margin's measure."""
        r, g, b = self._ink_rgb()
        cr.set_source_rgba(r, g, b, _ORNAMENT_ALPHA)
        cr.set_line_width(1.0)
        cr.move_to(0, h / 2 + 0.5)
        cr.line_to(w, h / 2 + 0.5)
        cr.stroke()

    def _draw_tailpiece(self, cr, w, h):
        """Three lozenges — the asterism that closes one."""
        r, g, b = self._ink_rgb()
        cr.set_source_rgba(r, g, b, _ORNAMENT_ALPHA)
        cy = h / 2
        for offset in (-16, 0, 16):
            _draw_lozenge(cr, w / 2 + offset, cy, 3.0)

    def _build_rail(self):
        """The wide-width margin rail: at 1240px and over, the date and the
        day's designation leave the column and stand in the left margin as a
        Kalendar heading, so the width carries something instead of nothing.

        Separate labels rather than the column's own, reparented: these wrap
        and those must not (a tracked label folds its last word — see
        `_line`), and a mode switch that only toggles visibility cannot
        strand a label in the wrong container."""
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rail.set_halign(Gtk.Align.START)
        rail.set_valign(Gtk.Align.START)  # its head sits on the column's head
        rail.set_margin_start(_RAIL_MARGIN)
        rail.set_margin_top(40)           # the column's own top margin
        rail.set_size_request(_RAIL_WIDTH, -1)
        # A short rule opening the rail, the headpiece's own line repeated at
        # the margin's measure: without it the rail stood as an island of
        # caps with nothing on the page to tie it to.
        self._rail_rule = self._build_ornament(self._draw_rail_rule, 40, 9)
        self._rail_rule.set_halign(Gtk.Align.START)
        self._rail_rule.set_margin_bottom(12)
        rail.append(self._rail_rule)
        self._rail_date = Gtk.Label(xalign=0.0, wrap=True,
                                    max_width_chars=_RAIL_CHARS)
        self._rail_date.add_css_class('today-rail-date')
        rail.append(self._rail_date)
        self._rail_church = Gtk.Label(xalign=0.0, wrap=True,
                                      max_width_chars=_RAIL_CHARS)
        self._rail_church.add_css_class('today-rail-church')
        self._rail_church.set_margin_top(8)
        rail.append(self._rail_church)
        rail.set_visible(False)
        self._rail = rail
        return rail

    def _build_write_mark(self):
        """The journal door as a mark in the left margin.

        It was the third centred line in the column, in the same voice as the
        fallback reading door, and the middle of the page read as a list of
        links. Writing is not reading: it belongs in the margin beside the
        spoken devotional, as the second of a pair of marks, and the run of
        type is left to the day and its two doors into Scripture.

        A disc with no ring — nothing about a journal entry has a progress —
        so the pair reads as one family rather than two controls."""
        # The pencil, not the journal notebook: shot at the 16px this disc
        # actually carries, the notebook's ribbon cut-out eats the cover and
        # the glyph reads as a "U". The notebook was drawn for a switcher
        # row, where a label stands beside it; a mark in the margin has only
        # a tooltip, so the glyph has to carry the meaning alone.
        self._write_btn = Gtk.Button(
            icon_name='scriptura-document-edit-symbolic')
        self._write_btn.add_css_class('today-mark')
        self._write_btn.set_halign(Gtk.Align.CENTER)
        self._write_btn.set_valign(Gtk.Align.CENTER)
        self._write_css = Gtk.CssProvider()
        self._write_btn.get_style_context().add_provider(
            self._write_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._write_btn.set_tooltip_text(_('Write about today'))
        set_accessible_label(self._write_btn, _('Write about today'))
        self._write_btn.connect(
            'clicked', lambda _b: self._on_write() if self._on_write else None)

        # The same anatomy as the listen mark — a mark-sized field with the
        # disc centred over it — minus the ring. A plain box left the disc
        # at its own start, 8px off the centre its twin sits on.
        field = Gtk.Box()
        field.set_size_request(_MARK_SIZE, _MARK_SIZE)
        self._write_mark = Gtk.Overlay()
        self._write_mark.set_child(field)
        self._write_mark.add_overlay(self._write_btn)

        holder = Gtk.Box()
        # Hugging the column's edge, not centred in the margin: at the wide
        # breakpoint the margin is 244px and a centred mark stood 122px clear
        # of the words it belongs to, which is the window-anchored fault this
        # rebuild was for. The gutter's extra width becomes outer slack.
        holder.set_halign(Gtk.Align.END)
        holder.set_valign(Gtk.Align.CENTER)
        holder.set_margin_end(_MARK_GAP)
        holder.set_vexpand(True)
        holder.append(self._write_mark)
        holder.set_visible(self._on_write is not None)
        self._write_holder = holder
        return holder

    def _set_mode(self, mode):
        """Apply a breakpoint's layout. '' is the default width."""
        self._mode = mode
        for name in ('today-narrow', 'today-wide'):
            self.remove_css_class(name)
        if mode:
            self.add_css_class(f'today-{mode}')
        wide = mode == 'wide'
        self._rail.set_visible(wide)
        self._eyebrow.set_visible(not wide)
        self._church.set_visible(bool(self._church_line) and not wide)
        self._place_marks()

    def _marks_home(self, mark, margin_home):
        return self._listen_slot if self._mode == 'narrow' else margin_home

    def _homes(self):
        # Write first, so that sharing the column they keep the order they
        # have in the margins: the journal on the left, the reading on the
        # right.
        return ((self._write_mark, self._write_holder),
                (self._listen_mark, self._listen_card))

    def _move_marks_home(self):
        """Re-hang the marks. Never called straight from a breakpoint: see
        `_place_marks`."""
        self._marks_move_queued = False
        for mark, margin_home in self._homes():
            home = self._marks_home(mark, margin_home)
            if mark.get_parent() is not home:
                mark.unparent()
                home.append(mark)
        return GLib.SOURCE_REMOVE

    def _place_marks(self):
        """Hang the two marks where this width has room for them: the
        column's margins normally, the column itself when there are none.

        The move itself goes on an idle. A breakpoint's apply/unapply runs
        inside the bin's size-allocate, and changing the widget hierarchy
        there is not allowed — and the menu sidebar sliding in over a narrow
        window is exactly a width animation that crosses this breakpoint,
        frame after frame. Visibility is safe to set here; parenthood is not.
        """
        narrow = self._mode == 'narrow'
        writing = self._on_write is not None
        if any(mark.get_parent() is not self._marks_home(mark, home)
               for mark, home in self._homes()):
            if not self._marks_move_queued:
                self._marks_move_queued = True
                GLib.idle_add(self._move_marks_home)
        self._listen_card.set_visible(not narrow and self._listen_shown)
        self._write_holder.set_visible(not narrow and writing)
        self._listen_mark.set_visible(not narrow or self._listen_shown)
        self._write_mark.set_visible(not narrow or writing)
        self._listen_slot.set_visible(
            narrow and (self._listen_shown or writing))

    def _build_listen_card(self):
        """Today's spoken devotional as a single mark in the margin.

        Not a card. This page is type on paper — the design law puts the
        reading surface at depth 0, "no boxes" — and a bounded panel was the
        only edged object on the whole surface, which is why it read as having
        landed here rather than belonging. A book's margin carries marks, not
        widgets: one disc, ink-coloured, naming itself only when reached for.

        Progress is a ring around the disc rather than a bar. A bar has to be
        aligned to something and inset from something; a ring is simply part
        of the mark.
        """
        self._listen_fraction = 0.0
        self._listen_shown = False
        # Where the fetch's travelling arc has got to, or None when there is
        # no fetch. The ring says "this reading is working" before it can say
        # how far through it is.
        self._listen_sweep = None

        self._listen_ring = Gtk.DrawingArea()
        self._listen_ring.set_content_width(58)
        self._listen_ring.set_content_height(58)
        self._listen_ring.set_draw_func(self._draw_listen_ring)
        self._listen_ring.set_can_target(False)   # the button takes the click
        self._listen_wait = DelayedPulse(
            show=lambda: setattr(self, '_listen_sweep', 0.0),
            tick=self._advance_listen_sweep,
            hide=self._clear_listen_sweep,
            interval_ms=40)   # an arc travelling, not a bar stepping

        self._listen_btn = Gtk.Button(
            icon_name='scriptura-media-playback-start-symbolic')
        self._listen_btn.add_css_class('today-mark')
        self._listen_btn.set_halign(Gtk.Align.CENTER)
        self._listen_btn.set_valign(Gtk.Align.CENTER)
        self._listen_play_css = Gtk.CssProvider()
        self._listen_btn.get_style_context().add_provider(
            self._listen_play_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._listen_btn.connect(
            'clicked', lambda _b: self._on_listen and self._on_listen())

        mark = self._listen_mark = Gtk.Overlay()
        mark.set_child(self._listen_ring)
        mark.add_overlay(self._listen_btn)

        # The title is the mark's own tooltip rather than a label: a lone disc
        # keeps the margin empty, and a play glyph has never needed explaining.
        self._listen_title = Gtk.Label()      # kept for the API below

        card = Gtk.Box()
        card.set_halign(Gtk.Align.START)
        card.set_valign(Gtk.Align.CENTER)
        card.set_margin_start(_MARK_GAP)
        card.set_vexpand(True)
        card.append(mark)
        card.set_visible(False)
        self._listen_card = card
        return card

    def _draw_listen_ring(self, _area, cr, width, height):
        """A faint track, and the arc of it that has been read."""
        import math
        r = min(width, height) / 2 - 2
        cx, cy = width / 2, height / 2
        ink = Gdk.RGBA()
        ink.parse(self._ink)
        # The full track, faint. The played arc, brighter and a touch
        # thicker, so it reads as motion at arm's length while staying
        # delicate up close — the track alone was legible only at the mark.
        cr.set_line_width(2.0)
        cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.15)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if self._listen_sweep is not None:
            # Waiting on the file: a short arc travelling the same track the
            # reading will later fill, in the same weight, so the ring reads
            # as one thing doing two jobs rather than two indicators.
            cr.set_line_width(2.5)
            cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.7)
            start = -math.pi / 2 + 2 * math.pi * self._listen_sweep
            cr.arc(cx, cy, r, start, start + math.pi / 3)
            cr.stroke()
        elif self._listen_fraction > 0.0:
            cr.set_line_width(2.5)
            cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.7)
            cr.arc(cx, cy, r, -math.pi / 2,
                   -math.pi / 2 + 2 * math.pi * self._listen_fraction)
            cr.stroke()

    def _advance_listen_sweep(self):
        self._listen_sweep = ((self._listen_sweep or 0.0) + 0.03) % 1.0
        self._listen_ring.queue_draw()

    def _clear_listen_sweep(self):
        self._listen_sweep = None
        self._listen_ring.queue_draw()

    # ── Content ──────────────────────────────────────────────────────────

    def _on_begin_clicked(self, _btn):
        if self._begin_target is not None:
            self._on_begin(*self._begin_target)
        else:
            self._on_choose_plans()

    def populate(self, last_position: tuple[str, int] | None,
                 continue_detail: str | None,
                 church_line: str | None = None) -> None:
        """Fill the page from the plan store and the given last reading
        position. `continue_detail` is the pane's module name (shown after
        the reference), or None to omit it. `church_line` is the liturgical
        designation from church_year (None hides the line)."""
        today = datetime.date.today()
        # Day name and date, composed with the house '·' separator. Both come
        # from the catalogue rather than strftime — see i18n's Dates section
        # for why LC_TIME cannot answer where the app ships.
        self._eyebrow.set_text('{day} · {date}'.format(
            day=weekday_name(today.weekday()),
            date=format_date(today)))
        self._church_line = church_line
        self._church.set_text(church_line or '')
        self._church.set_visible(bool(church_line) and self._mode != 'wide')
        self._rail_date.set_text(self._eyebrow.get_text())
        self._rail_church.set_text(church_line or '')
        self._rail_church.set_visible(bool(church_line))

        plan_id, start_date = reading_plans.get_active()
        days = reading_plans.get_plan_days(plan_id) if plan_id else []
        total = len(days)
        has_plan = bool(plan_id and start_date and total)
        if has_plan:
            assert plan_id is not None and start_date is not None  # has_plan
            # One definition of which day it is, shared with the plan panel:
            # a plan is over when its days have been read, not when the
            # calendar has run past its length (reading_plans.plan_anchor).
            anchor, finished = reading_plans.plan_anchor(
                plan_id, start_date, total)
            name = next((_(p['name']) for p in reading_plans.get_plans()
                         if p['id'] == plan_id), plan_id)
            self._kicker.set_text(
                _('{plan} — day {n}').format(plan=name, n=anchor + 1))
            self._kicker.set_visible(True)
            if finished:
                # The plan's name without a day number: "day 30" over "Plan
                # complete" counts out a plan that is over, and the count was
                # clamped to the last day anyway — it would have said day 30
                # on the hundredth day as well.
                self._kicker.set_text(name)
                self._passage.set_text(_('Plan complete'))
                self._whisper.set_visible(False)
                # A door forward. The page had none: a finished plan left the
                # reader on a hero that named an ending, under a line that
                # offered the place they left off and nothing else.
                self._begin_target = None
                self._begin_btn.set_label(_('Choose another reading plan →'))
                set_accessible_label(self._begin_btn,
                                     _('Choose another reading plan'))
                self._begin_btn.set_visible(True)
            else:
                readings = days[anchor]
                self._passage.set_text(passage_display(readings))
                whisper = progress_whisper(anchor + 1, total)
                self._whisper.set_text(whisper)
                self._whisper.set_visible(bool(whisper))
                self._begin_target = readings[0] if readings else None
                self._begin_btn.set_label(_('Begin today’s reading →'))
                set_accessible_label(self._begin_btn, _('Begin today’s reading'))
                self._begin_btn.set_visible(self._begin_target is not None)
            self._passage.set_visible(True)
        else:
            # No plan running: one quiet line offering the plans instead.
            self._kicker.set_visible(False)
            self._passage.set_visible(False)
            self._whisper.set_visible(False)
            self._begin_target = None
            self._begin_btn.set_label(_('Choose a reading plan →'))
            set_accessible_label(self._begin_btn, _('Choose a reading plan'))
            self._begin_btn.set_visible(True)

        self._continue_target = last_position
        if last_position:
            book, chapter = last_position
            ref = f'{book_label(book)} {chapter}'
            # The module name is spoken, not shown. On the page it made this
            # the widest line there was — 473px against a 313px hero, so the
            # page's loudest mark was its fallback door — and the reader
            # learns the translation the moment the door opens anyway.
            # "Or" only when there is something for this to be an
            # alternative TO. Keyed to the plan before, which left a finished
            # plan — Begin hidden, nothing above the line — reading "Or
            # continue where you left off" as the page's first offer.
            self._continue_btn.set_label(
                _('Or continue where you left off — {ref}').format(ref=ref)
                if self._begin_btn.get_visible() else
                _('Continue where you left off — {ref}').format(ref=ref))
            set_accessible_label(
                self._continue_btn,
                _('Continue where you left off — {ref}').format(
                    ref=f'{ref} · {continue_detail}' if continue_detail
                    else ref))
            self._continue_btn.set_visible(True)
        else:
            self._continue_btn.set_visible(False)

    def antiphon_target(self) -> tuple[str, int] | None:
        """The chapter whose opening line the antiphon should speak: today's
        appointed reading, or the place the reader left off when no plan is
        running. Resolved by `populate`, so call it after."""
        target = self._begin_target or self._continue_target
        return target if target is None else (target[0], int(target[1]))

    def set_antiphon(self, text: str) -> None:
        """The day's opening line, under the reference that names it."""
        self._antiphon.set_text(text)
        self._antiphon.set_attributes(_mark_safe_attrs(text))
        self._antiphon.set_visible(True)

    def clear_antiphon(self) -> None:
        """No line — the page simply opens at its reference.

        Emptied before every fetch, like the epigraph: on a rebuild the
        standing line is the previous day's or the previous module's, and it
        must not sit under the new reference while the lookup runs."""
        self._antiphon.set_text('')
        self._antiphon.set_visible(False)

    def set_epigraph(self, quote: str, source: str,
                     quoted: bool = True) -> None:
        """The devotional foot line — whole or not at all (stays hidden
        when there's nothing worth setting). `quoted` wraps the text in
        quotation marks — right for a scripture line, wrong for a prayer
        (a collect is prayed, not cited)."""
        shown = f'“{quote}”' if quoted else quote
        self._epigraph_verse.set_text(shown)
        self._epigraph_verse.set_attributes(_mark_safe_attrs(shown))
        # Italic is the mark of a quotation, and a collect is not quoted —
        # it is prayed. The flag that already decides the quotation marks
        # decides the face with them.
        if quoted:
            self._epigraph_verse.remove_css_class('today-prayer')
        else:
            self._epigraph_verse.add_css_class('today-prayer')
        self._epigraph_src.set_text(self._trim_source(source))
        self._epigraph_box.set_visible(True)

    def _trim_source(self, source: str) -> str:
        """Drop the day's designation from the foot line when the head of the
        page already carries it.

        A collect's source reads "The First Sunday in Advent — Book of Common
        Prayer", and that first half is the church-year line standing at the
        top of the same page. Printing it twice tells the reader nothing and
        makes the foot the longest tracked line on the surface."""
        head = (self._church_line or '').strip()
        if not head:
            return source
        for dash in ('—', '–', '-'):
            prefix = f'{head} {dash} '
            if source.lower().startswith(prefix.lower()):
                return source[len(prefix):]
        return source

    def set_listen(self, title: str, playing: bool = False,
                   fetching: bool = False) -> None:
        """Offer today's spoken devotional under its own title.

        Three states, and the middle one is the reason this takes a flag
        rather than a boolean: the reading has to be fetched before it can
        be heard, and a pause icon over that wait claims a playback that has
        not begun. Fetching shows a stop — press it and the fetch is dropped
        — and the ring sweeps once the wait is long enough to be worth
        showing.
        """
        if fetching:
            icon, label = ('scriptura-media-playback-stop-symbolic',
                           _('Stop fetching the reading'))
        elif playing:
            icon, label = ('scriptura-media-playback-pause-symbolic',
                           _('Pause the spoken devotional'))
        else:
            icon, label = ('scriptura-media-playback-start-symbolic',
                           _('Listen to today\'s devotional'))
        self._listen_btn.set_icon_name(icon)
        self._listen_btn.set_tooltip_text(
            label if fetching else (title or None))
        self._listen_shown = True
        self._place_marks()
        set_accessible_label(self._listen_btn, label)
        if fetching:
            self._listen_wait.start()
        else:
            self._listen_wait.stop()

    def clear_listen(self) -> None:
        """No reading for today — the invitation is simply not made."""
        self._listen_wait.stop()
        self._listen_shown = False
        self._place_marks()
        self.set_listen_progress(0.0, showing=False)

    def set_listen_progress(self, fraction: float,
                            showing: bool = True) -> None:
        self._listen_fraction = fraction if showing else 0.0
        self._listen_ring.queue_draw()

    def clear_epigraph(self) -> None:
        """Empty the foot line.

        Needed because the page can now be rebuilt in place, when the reader
        changes calendar. Without it a tradition that has nothing for today
        leaves the previous tradition's prayer standing under the new day's
        name — the right prayer on the wrong day, arrived at through the
        interface rather than through the pack."""
        self._epigraph_verse.set_text('')
        self._epigraph_src.set_text('')
        self._epigraph_box.set_visible(False)

    # ── Look ─────────────────────────────────────────────────────────────

    def set_appearance(self, appearance: dict) -> None:
        """Mirror the reading pane's paper / ink / serif (already
        evening-blended by the caller — see pane.reading_appearance)."""
        # The primary action is set in the reading gold — the same antique
        # gold the drop cap defaults to — rather than the stock blue accent,
        # and it picks its light or dark cast from the PAPER, the way the ink
        # does, so a light paper under a dark desktop still gets the deeper
        # gold. The default is used, not dropcap_color_hex(): a reader who has
        # tinted their drop caps has made a choice about Scripture's opening
        # letter, not about what colour this page's buttons are.
        from pane import (DROPCAP_GOLD_DARK, DROPCAP_GOLD_LIGHT,
                          is_dark_paper)
        gold = (DROPCAP_GOLD_DARK if is_dark_paper(appearance['surface'])
                else DROPCAP_GOLD_LIGHT)
        self._css.load_from_data((
            '.today-view {{ background-color: {surface}; color: {ink}; }}'
            .format(**appearance)).encode())
        mark_css = (
            'button.today-mark {{'
            ' background-color: alpha({ink}, 0.13); color: {ink}; }}'
            'button.today-mark:hover {{'
            ' background-color: alpha({ink}, 0.22); }}'
            .format(**appearance)).encode()
        self._listen_play_css.load_from_data(mark_css)
        self._write_css.load_from_data(mark_css)
        self._ink = appearance['ink']
        self._surface = appearance['surface']
        self._listen_ring.queue_draw()
        self._headpiece.queue_draw()
        self._tailpiece.queue_draw()
        self._rail_rule.queue_draw()
        self.queue_draw()          # the sheet is struck from this ink
        # The card's surface is the page's ink at low alpha, not a theme
        # colour: this page's paper is the pane's, and may be light while the
        # desktop is dark.
        self._card_css.load_from_data((
            '.today-listen-card {{ background-color: transparent; }}'


            .format(**appearance)).encode())
        self._go_css.load_from_data(
            f'.today-go {{ color: {gold}; }}'.encode())
        self._serif_css.load_from_data((
            'label {{ font-family: {family}; }}'
            .format(**appearance)).encode())
