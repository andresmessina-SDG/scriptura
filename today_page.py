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
import re

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango

import reading_plans
from a11y import set_accessible_label
from i18n import _, book_label

# Longest epigraph we'll set at the foot — beyond this the quote is cut at a
# word boundary. Devotional opening quotes are a verse line, almost always
# shorter; the cap only guards against unusually chatty modules.
_EPIGRAPH_MAX = 240


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
    text = re.sub(r'<[^>]+>', ' ', fragment)
    return re.sub(r'\s+', ' ', text).strip()


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


def fetch_epigraph() -> tuple[str, str] | None:
    """Today's devotional epigraph from the first installed devotional
    module: (quote, source_line). Blocking SWORD work — call from a task
    worker. None when no module or no usable quote."""
    import sword_bridge
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
            return quote, source
    return None


class TodayView(Gtk.Box):
    """The Morning Office surface. The window owns showing/dismissing it;
    this widget owns its content and look."""

    def __init__(self, on_begin, on_continue, on_choose_plans):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('today-view')
        self._on_begin = on_begin
        self._on_continue = on_continue
        self._on_choose_plans = on_choose_plans
        self._begin_target = None      # (book, chapter) for the plan day
        self._continue_target = None   # (book, chapter) for last position
        self._css = Gtk.CssProvider()
        self.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._serif_css = Gtk.CssProvider()

        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=640,
                          vexpand=True, hexpand=True)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        v.set_margin_top(56)
        v.set_margin_bottom(36)
        v.set_margin_start(24)
        v.set_margin_end(24)
        clamp.set_child(v)
        self.append(clamp)

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

        # Equal spacers above the hero group and below it centre the block
        # in the space over the epigraph — a title page, not a top-hugging
        # form with a void beneath.
        v.append(Gtk.Box(vexpand=True))

        self._eyebrow = _line(Gtk.Label())
        self._eyebrow.add_css_class('today-eyebrow')
        v.append(self._eyebrow)

        # Church-year line (opt-in via the church_calendar setting): a
        # second whisper under the date, e.g. "The Sixth Sunday after
        # Trinity". Hidden when the setting is None or nothing applies.
        self._church = _line(Gtk.Label())
        self._church.add_css_class('today-church')
        self._church.set_margin_top(6)
        self._church.set_visible(False)
        v.append(self._church)

        self._kicker = _line(Gtk.Label())
        self._kicker.add_css_class('today-kicker')
        self._kicker.set_margin_top(30)
        v.append(self._kicker)

        self._passage = _centered(Gtk.Label())
        self._passage.add_css_class('today-passage')
        self._passage.set_margin_top(14)
        self._passage.get_style_context().add_provider(
            self._serif_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        v.append(self._passage)

        self._whisper = _line(Gtk.Label())
        self._whisper.add_css_class('today-whisper')
        self._whisper.set_margin_top(8)
        v.append(self._whisper)

        self._begin_btn = Gtk.Button()
        self._begin_btn.add_css_class('flat')
        self._begin_btn.add_css_class('today-go')
        self._begin_btn.set_halign(Gtk.Align.CENTER)
        self._begin_btn.set_margin_top(24)
        self._begin_btn.connect('clicked', self._on_begin_clicked)
        v.append(self._begin_btn)

        self._continue_btn = Gtk.Button()
        self._continue_btn.add_css_class('flat')
        self._continue_btn.add_css_class('today-quiet')
        self._continue_btn.set_halign(Gtk.Align.CENTER)
        self._continue_btn.set_margin_top(16)
        self._continue_btn.connect(
            'clicked', lambda _b: self._on_continue(self._continue_target))
        v.append(self._continue_btn)

        v.append(Gtk.Box(vexpand=True))  # the twin of the spacer above

        self._epigraph_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._epigraph_box.set_margin_top(36)
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
        self._epigraph_src.set_margin_top(10)
        self._epigraph_box.append(self._epigraph_src)
        self._epigraph_box.set_visible(False)
        v.append(self._epigraph_box)

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
        # Locale day-name and date, composed with the house '·' separator.
        self._eyebrow.set_text('{day} · {date}'.format(
            day=today.strftime('%A'), date=today.strftime('%-d %B %Y')))
        self._church.set_text(church_line or '')
        self._church.set_visible(bool(church_line))

        plan_id, start_date = reading_plans.get_active()
        days = reading_plans.get_plan_days(plan_id) if plan_id else []
        total = len(days)
        has_plan = bool(plan_id and start_date and total)
        if has_plan:
            assert start_date is not None  # has_plan guarantees it
            idx = reading_plans.today_index(start_date)
            anchor = max(0, min(idx, total - 1))
            finished = idx >= total
            name = next((_(p['name']) for p in reading_plans.get_plans()
                         if p['id'] == plan_id), plan_id)
            self._kicker.set_text(
                _('{plan} — day {n}').format(plan=name, n=anchor + 1))
            self._kicker.set_visible(True)
            if finished:
                self._passage.set_text(_('Plan complete'))
                self._whisper.set_visible(False)
                self._begin_target = None
                self._begin_btn.set_visible(False)
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
            if continue_detail:
                ref = f'{ref} · {continue_detail}'
            self._continue_btn.set_label(
                _('Or continue where you left off — {ref}').format(ref=ref)
                if has_plan else
                _('Continue where you left off — {ref}').format(ref=ref))
            self._continue_btn.set_visible(True)
        else:
            self._continue_btn.set_visible(False)

    def set_epigraph(self, quote: str, source: str) -> None:
        """The devotional foot line — whole or not at all (stays hidden
        when there's nothing worth setting)."""
        self._epigraph_verse.set_text(f'“{quote}”')
        self._epigraph_src.set_text(source)
        self._epigraph_box.set_visible(True)

    # ── Look ─────────────────────────────────────────────────────────────

    def set_appearance(self, appearance: dict) -> None:
        """Mirror the reading pane's paper / ink / serif (already
        evening-blended by the caller — see pane.reading_appearance)."""
        self._css.load_from_data((
            '.today-view {{ background-color: {surface}; color: {ink}; }}'
            .format(**appearance)).encode())
        self._serif_css.load_from_data((
            'label {{ font-family: {family}; }}'
            .format(**appearance)).encode())
