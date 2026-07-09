"""Presentation mode surface — a passage in large, centered type for a
projector or mirrored display.

A chapter is shown a screenful at a time (auto-fit pages); toggling to
verse-at-a-time makes each verse its own slide. Stepping past either end of a
chapter rolls into the adjacent one via the host's cross-chapter callback, so
the arrows are always meaningful. The pure grouping + index math lives in
present_paging (unit-tested headlessly); this view supplies the pixel estimate
of how much fits and the on-screen rendering.
"""
import re
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib

from pane import _html_to_markup
import present_paging
import present_align


class PresentView(Gtk.Box):
    """Fullscreen presentation surface. Fed a chapter via `load_chapter`, then
    stepped with step_next / step_prev / step_home / step_end. `on_cross(delta)`
    is called (delta ±1) when a step runs off the end of the current chapter."""

    __gtype_name__ = 'PresentView'

    # Capacity (characters) used before the surface has a real allocation to
    # measure; the first size-allocate replaces it with the true screenful.
    _DEFAULT_CAPACITY = 700

    def __init__(self, on_cross=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('present-view')
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._on_cross = on_cross

        # The stylesheet must reach the descendant label, so it goes on the
        # display (a provider added to this widget's own context would style
        # the box but not its children — that was why the big font never
        # applied). The classes are used only here, so display scope is safe.
        self._css = Gtk.CssProvider()
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._eyebrow = Gtk.Label()
        self._eyebrow.add_css_class('present-eyebrow')
        self._eyebrow.set_wrap(True)
        self._eyebrow.set_justify(Gtk.Justification.CENTER)

        self._text = Gtk.Label()
        self._text.add_css_class('present-text')
        self._text.set_wrap(True)
        self._text.set_justify(Gtk.Justification.CENTER)
        self._text.set_use_markup(True)
        self._text.set_selectable(False)

        # Parallel (bilingual) surface: two verse-locked columns flanking a
        # dimmed verse-number spine. Kept in the same column and toggled by
        # visibility with _text, so the fit/measure engine measures whichever is
        # showing (a hidden widget contributes 0 to the size request).
        self._grid = Gtk.Grid()
        self._grid.add_css_class('present-grid')
        self._grid.set_column_spacing(22)
        self._grid.set_row_spacing(14)
        self._grid.set_hexpand(True)
        self._grid.set_visible(False)

        self._column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._column.set_valign(Gtk.Align.CENTER)
        self._column.append(self._eyebrow)
        self._column.append(self._text)
        self._column.append(self._grid)
        column = self._column

        # Clamp gives a centered, readable measure; the scroller is a safety net
        # for a lone verse taller than the screen at a large font. Parallel mode
        # widens the clamp (two columns need more room than one reading measure).
        self._clamp = Adw.Clamp(maximum_size=1100, tightening_threshold=920)
        self._clamp.set_child(column)
        self._clamp.set_valign(Gtk.Align.CENTER)
        clamp = self._clamp

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_child(clamp)
        self._scroller.set_vexpand(True)
        self._scroller.set_hexpand(True)
        self.append(self._scroller)

        self._book = None          # canonical English book, or None (placeholder)
        self._chapter = 0
        self._translation = ''
        self._verses = []          # [(verse_num, source_html), …]
        self._verses_b = []        # secondary pane's verses (parallel mode)
        self._translation_b = ''
        self._rows = []            # aligned [(verse, html_a|None, html_b|None)]
        self._has_secondary = False  # a second translation is loaded
        self._bilingual = False    # user toggle; effective = has_secondary & this
        self._weights = []         # per-item text length, for pagination
        self._pages = []           # [(start, end), …] half-open slices
        self._stepper = present_paging.Stepper()
        self._show_numbers = True
        self._verse_at_a_time = False
        self._capacity = self._DEFAULT_CAPACITY
        self._reading_pt = 16      # base reading size; present size derives from it
        self._present_pt = 40      # rendered size, set by the fit pass (grow/shrink)
        self._size_step = 0        # live +/- nudges (shift the fill target)
        self._bold = False
        self._surface = ''
        self._ink = ''
        self._family = ''
        self._reflow_pending = None
        self._alloc_key = (0, 0)
        self._viewport_hint = 0

    def set_cross_handler(self, on_cross):
        self._on_cross = on_cross

    def set_viewport_hint(self, height):
        """Expected content height, so the very first page (rendered before the
        surface is ever allocated) can still be measured and pre-fit — measure()
        needs no allocation, only a target height to fit within."""
        self._viewport_hint = max(0, int(height))

    # ── Appearance ────────────────────────────────────────────────────────────
    def set_appearance(self, appearance):
        """Mirror the reading pane's paper / ink / serif, scaled up for a
        projector. `appearance` is BiblePane.reading_appearance()."""
        self._surface = appearance['surface']
        self._ink = appearance['ink']
        self._family = appearance['family']
        self._bold = appearance['bold']
        self._reading_pt = appearance['font_size']
        self._apply_font()
        self._reflow()

    _SIZE_MIN_PT = 20     # readable floor
    _SIZE_CAP_PT = 140    # sane projector ceiling
    # Fill to this fraction of the viewport by default. The headroom absorbs
    # GTK's under-measurement of large wrapped labels in a grid (worse the more
    # the font is grown), so a grown slide never tips into a scrollbar.
    _FILL_FRAC = 0.88
    # Each nudge step shifts the fill target by this fraction: + fills fuller
    # (up to the no-scroll ceiling), − leaves more margin. Auto-fit then sizes
    # the font to that target, so nudge and auto-fit cooperate.
    _NUDGE_FRAC = 0.08

    def _mode_base_pt(self):
        """The natural per-mode size before auto-fit — the seed the fit pass
        grows or shrinks from. Verse-at-a-time starts bigger and more dramatic;
        chapter mode moderate so a screenful holds several verses."""
        if self._verse_at_a_time:
            base = max(40, round(self._reading_pt * 2.4))
        else:
            base = max(26, round(self._reading_pt * 1.5))
        return max(self._SIZE_MIN_PT, min(base, self._SIZE_CAP_PT))

    def bump_size(self, direction):
        """Nudge the fill target one step bigger (direction > 0) or smaller and
        re-fit. A press that doesn't move the rendered size (the pt range ended)
        is reverted, so neither end accumulates a dead zone."""
        delta = 1 if direction > 0 else -1
        old_pt = self._present_pt
        self._size_step += delta
        self._reflow()
        if self._present_pt == old_pt:
            self._size_step -= delta      # no visible effect → don't bank it
            self._reflow()

    def _scale_font(self, target, natural):
        """Scale the rendered font toward making the page measure `target` px,
        given it currently measures `natural`. Proportional (height ≈ linear in
        pt) so it grows or shrinks to fill in one step; bounded to the readable
        range. Returns False when it's already at the bound it needs — the
        caller then stops (accepting a little margin, or letting the scroller
        catch a forced overflow)."""
        want = max(self._SIZE_MIN_PT,
                   min(round(self._present_pt * target / natural),
                       self._SIZE_CAP_PT))
        if want == self._present_pt:
            return False
        self._present_pt = want
        # Size is markup-driven now; the next _paint_slice applies it (and the
        # fit loop repaints before it re-measures), so no CSS reload here.
        return True

    def _apply_font(self):
        # Family / colour / weight only — the SIZE is applied per-paint via Pango
        # markup (see _sized). CSS provider changes are not reflected in measure()
        # within the same call chain, so sizing through CSS made the fit loop
        # measure a stale height and grow the font away without converging;
        # markup updates the label's layout synchronously. Family/weight are
        # constant per appearance, so their async CSS application is harmless.
        weight = 'bold' if self._bold else 'normal'
        self._css.load_from_data((
            '.present-view { '
            f'background-color: {self._surface}; color: {self._ink}; '
            f'font-family: {self._family}; }} '
            '.present-text { '
            f'font-weight: {weight}; }}'
        ).encode())

    def _sized(self, markup):
        """Wrap painted markup in an absolute Pango size span. Driving the font
        size through markup (not CSS) is what makes a size change show up in the
        next measure() synchronously, so the fit loop converges instead of
        running away. Pango size is in 1024ths of a point."""
        if not markup:
            return ''
        return f'<span size="{int(round(self._present_pt * 1024))}">{markup}</span>'

    # ── Chapter loading ─────────────────────────────────────────────────────
    def load_chapter(self, book, chapter, translation, verses,
                     land='first', show_numbers=None, focus_verse=None,
                     secondary=None):
        """Show `verses` (a [(verse, source_html), …] list) for one chapter.
        `land` decides which page to open on — 'first' (default) or 'last',
        used when rolling backward into the previous chapter. `focus_verse`,
        when given, wins over `land`: open on the page holding that verse, so
        F5 presents from where the reader is rather than the chapter top.

        `secondary`, when given, is `(translation_b, verses_b)` — a second
        pane's chapter. It's verse-aligned with the primary so parallel mode can
        project both; `None` (or an empty secondary) leaves the surface single."""
        if show_numbers is not None:
            self._show_numbers = bool(show_numbers)
        self._book = book
        self._chapter = chapter
        self._translation = translation
        # Drop verses with no visible text (critical-text modules omit some,
        # e.g. Mark 9:44) so verse-at-a-time never lands on a blank slide.
        self._verses = [(v, h) for v, h in verses
                        if re.sub(r'<[^>]+>', '', str(h)).strip()]
        if secondary is not None:
            self._translation_b, verses_b = secondary
            self._verses_b = [(v, h) for v, h in verses_b
                              if re.sub(r'<[^>]+>', '', str(h)).strip()]
            self._rows = present_align.align(self._verses, self._verses_b)
            self._has_secondary = bool(self._verses_b)
        else:
            self._translation_b = ''
            self._verses_b = []
            self._rows = []
            self._has_secondary = False
        self._recompute_weights()
        self._pages = []
        self._stepper = present_paging.Stepper()
        # Fresh auto-fit each chapter — reseed the mode base, then the fit pass
        # grows or shrinks each slide to fill.
        self._present_pt = self._mode_base_pt()
        self._apply_font()
        # Start each chapter from a fresh estimate (a budget tightened for a
        # tall earlier chapter shouldn't permanently over-page later ones); the
        # measured fit-check then refines it.
        self._recompute_capacity()
        self._paginate()
        if focus_verse is not None and self._go_to_verse(focus_verse):
            pass
        elif land == 'last':
            self._stepper.end()
        self._render()

    def _effective_parallel(self):
        """Whether both columns actually show — a second translation is loaded
        AND the presenter hasn't collapsed to one language."""
        return self._has_secondary and self._bilingual

    def _page_items(self):
        """The list the pages slice into: aligned rows in parallel, else the
        primary verses. Both are indexable with `item[0]` == verse number."""
        return self._rows if self._effective_parallel() else self._verses

    def _clamp_max(self):
        # Two columns need more room than a single reading measure.
        return 1700 if self._effective_parallel() else 1100

    def _recompute_weights(self):
        """Per-item pagination weight. In parallel the row is as tall as its
        taller cell, so the pair weight is the max of the two sides (a missing
        side counts 0)."""
        if self._effective_parallel() and self._rows:
            self._weights = [
                max(self._verse_weight(a) if a else 0,
                    self._verse_weight(b) if b else 0)
                for _v, a, b in self._rows]
        else:
            self._weights = [self._verse_weight(h) for _v, h in self._verses]

    def _current_verse_number(self):
        """First verse number of the current page, in the current item space —
        so a granularity/parallel flip can re-anchor by verse across the two
        differently-indexed lists."""
        items = self._page_items()
        if not self._pages or not items:
            return None
        start, _end = self._pages[min(self._stepper.index,
                                      len(self._pages) - 1)]
        return items[start][0]

    def _go_to_verse(self, verse):
        """Move the stepper to the page holding `verse`; True if found. The
        pages index the current item list, so map the verse number to its index
        first."""
        items = self._page_items()
        vi = next((i for i, item in enumerate(items) if item[0] == verse), None)
        if vi is None:
            return False
        for pi, (s, e) in enumerate(self._pages):
            if s <= vi < e:
                self._stepper.go_to(pi)
                return True
        return False

    def show_placeholder(self, message):
        """No navigable passage to project (e.g. a lexicon module is showing)."""
        self._book = None
        self._chapter = 0
        self._translation = ''
        self._verses = [(0, message)]
        self._verses_b = []
        self._translation_b = ''
        self._rows = []
        self._has_secondary = False
        self._weights = [1]
        self._pages = [(0, 1)]
        self._stepper = present_paging.Stepper()
        self._stepper.set_count(1)
        self._render()

    @staticmethod
    def _verse_weight(html):
        # Visible text length drives the screenful estimate — strip tags, and
        # count at least 1 so an empty verse still advances the accumulator.
        return max(1, len(re.sub(r'<[^>]+>', '', str(html))))

    # ── Verse numbers ─────────────────────────────────────────────────────────
    def set_show_numbers(self, on):
        on = bool(on)
        if on == self._show_numbers:
            return
        self._show_numbers = on
        self._render()

    def toggle_numbers(self):
        self.set_show_numbers(not self._show_numbers)

    @property
    def show_numbers(self):
        return self._show_numbers

    # ── Granularity: screenful chapter (default) vs verse-at-a-time ────────────
    def set_verse_at_a_time(self, on):
        on = bool(on)
        if on == self._verse_at_a_time:
            return
        self._verse_at_a_time = on
        self._apply_font()      # the two modes use different sizes
        self._reflow()

    def toggle_granularity(self):
        self.set_verse_at_a_time(not self._verse_at_a_time)

    @property
    def verse_at_a_time(self):
        return self._verse_at_a_time

    # ── Parallel (bilingual) ───────────────────────────────────────────────────
    def set_parallel(self, on):
        """Show both translations (on) or collapse to the primary (off). No-op
        when no second translation is loaded. Re-anchors by verse so the flip
        between the single- and parallel-indexed page lists stays put."""
        on = bool(on)
        if on == self._bilingual:
            return
        verse = self._current_verse_number()
        self._bilingual = on
        self._reflow()
        if verse is not None and self._go_to_verse(verse):
            self._render()

    def toggle_parallel(self):
        self.set_parallel(not self._bilingual)

    @property
    def parallel(self):
        return self._bilingual

    @property
    def has_secondary(self):
        return self._has_secondary

    # ── Stepping ────────────────────────────────────────────────────────────
    def step_next(self):
        if self._stepper.next():
            self._render()
        elif self._on_cross is not None:
            self._on_cross(1)      # roll into the next chapter's first page

    def step_prev(self):
        if self._stepper.prev():
            self._render()
        elif self._on_cross is not None:
            self._on_cross(-1)     # roll into the previous chapter's last page

    def step_home(self):
        if self._stepper.home():
            self._render()

    def step_end(self):
        if self._stepper.end():
            self._render()

    @property
    def page_index(self):
        return self._stepper.index

    @property
    def page_count(self):
        return self._stepper.count

    # ── Pagination ────────────────────────────────────────────────────────────
    def _capacity_for(self, width, height):
        """Rough characters-that-fit estimate for one screenful. Biased to
        under-fill (0.85) so a page never overflows the display; overflow would
        clip a projected verse, whereas an extra page is harmless."""
        if self._verse_at_a_time:
            return 0
        if width <= 0 or height <= 0:
            return self._DEFAULT_CAPACITY
        ppp = 96.0 / 72.0                       # CSS px per pt
        line_px = self._present_pt * ppp * 1.4  # matches .present-text line-height
        usable_h = height - 200                 # eyebrow + generous top/bottom pad
        lines = max(1, int(usable_h / line_px))
        col_w = min(width, self._clamp_max()) - 24   # clamp max-width, minus inset
        if self._effective_parallel():
            col_w = max(1, (col_w - 100) / 2)   # two columns flanking the spine
        glyph_px = self._present_pt * ppp * 0.5  # ~0.5em average advance
        chars_per_line = max(8, int(col_w / glyph_px))
        return max(1, int(lines * chars_per_line * 0.85))

    def _recompute_capacity(self):
        """Reset the chapter-mode budget to the char-count estimate (a starting
        point the measured fit-check then refines down)."""
        self._capacity = self._capacity_for(self.get_width(), self.get_height())

    def _reflow(self):
        """Re-estimate the budget and re-page in place (font-size, granularity,
        parallel, or allocation changed). Auto-fit starts fresh from the mode
        base so a change that frees up room grows back, not just shrinks."""
        self._present_pt = self._mode_base_pt()
        self._apply_font()
        self._clamp.set_maximum_size(self._clamp_max())
        self._recompute_weights()
        self._recompute_capacity()
        if self._verses:
            self._paginate()

    def _build_pages(self):
        """Group verses into pages at the current budget (no painting).
        Verse-at-a-time is one verse per page (capacity 0) regardless of the
        chapter-mode budget."""
        cap = 0 if self._verse_at_a_time else self._capacity
        # Preserve the verse the presenter is on across a re-page so a resize or
        # granularity flip doesn't jump them elsewhere in the chapter.
        anchor = None
        if self._pages and self._verses:
            start, _end = self._pages[min(self._stepper.index,
                                          len(self._pages) - 1)]
            anchor = start
        self._pages = present_paging.paginate(self._weights, cap)
        self._stepper.set_count(len(self._pages))
        if anchor is not None:
            for pi, (s, e) in enumerate(self._pages):
                if s <= anchor < e:
                    self._stepper.go_to(pi)
                    break

    def _paginate(self):
        self._build_pages()
        self._fit_chapter()     # one font + pagination for the whole chapter
        self._render()

    def do_size_allocate(self, width, height, baseline):
        Gtk.Box.do_size_allocate(self, width, height, baseline)
        # Re-page only when the allocation actually changes — NOT when the
        # budget drifts from a fit correction, or the two would fight.
        key = (width, height)
        if key != self._alloc_key:
            self._alloc_key = key
            if self._reflow_pending is None:
                self._reflow_pending = GLib.idle_add(self._reflow_idle)

    def _reflow_idle(self):
        self._reflow_pending = None
        self._reflow()
        return GLib.SOURCE_REMOVE

    def _tallest_natural(self, width):
        """Paint and measure every page at the current font; return
        ``(page_index, natural_px)`` of the tallest actually-rendered page.

        Char weight only approximates rendered height — Latin and Cyrillic wrap
        differently, the two parallel columns break independently, and grid rows
        add spacing — so fitting the *weight*-heaviest page alone let a lighter-
        but-taller page scroll. Measuring every page is what makes one font
        provably fit the whole chapter. Cheap enough because the fit runs once
        per load/reflow, never per step."""
        worst_i, worst_px = 0, 0
        for i, (start, end) in enumerate(self._pages):
            self._paint_slice(start, end)
            px = self._column.measure(Gtk.Orientation.VERTICAL, width)[1]
            if px > worst_px:
                worst_i, worst_px = i, px
        return worst_i, worst_px

    def _fit_chapter(self):
        """Choose ONE font (and, chapter-mode, one pagination) for the whole
        chapter by fitting its tallest page, so the size is identical on every
        slide (no per-slide resizing while flipping) and nothing scrolls.

        Two MONOTONE phases, so the fit can never terminate on an overflowing
        (scrolling) page: first shrink/repaginate until the tallest measured page
        fits under the no-scroll ceiling, then grow toward the fill target while
        reverting any step that would breach the ceiling. All pages share the
        resulting font; sparser pages simply carry more margin. Run once per
        load/reflow — stepping never re-fits — so page count and size stay put."""
        if not self._pages:
            return
        # Real allocation once shown; the window's hint before the first one.
        viewport = self._scroller.get_height() or self._viewport_hint
        if viewport <= 0:
            return                             # nothing to fit against (headless)
        have_real = self._scroller.get_height() > 0
        # Measure at the width the content will actually render at: the clamp caps
        # the column at clamp_max, so on a projector (screen wider than the clamp)
        # the render width IS clamp_max. Deriving it from the live scroller width
        # and the freshly-set clamp_max — NOT the column's own allocation — is what
        # keeps a parallel↔single toggle (which changes clamp_max without a new
        # size-allocate, so get_width() is stale-wide) from measuring too wide,
        # under-counting the wrap, and over-growing the font into a scrollbar.
        avail = self._scroller.get_width() or self._column.get_width() or 1000
        width = min(avail, self._clamp_max())
        safe = max(1, viewport - 12)           # hard no-scroll ceiling
        base = self._mode_base_pt()
        # Fill to a fraction of the viewport; the headroom absorbs GTK's under-
        # measurement of large wrapped grid labels. Nudge shifts the target.
        fill = min(safe, int(viewport * self._FILL_FRAC
                             * (1 + self._size_step * self._NUDGE_FRAC)))
        # Phase 1 — shrink until the tallest page fits under the ceiling. Drop a
        # verse (chapter mode, at/below base) else shrink the font; a proportional-
        # rounding stall that leaves a sliver of overflow is nudged down a whole
        # point so it can't exit still overflowing. Ends with tallest ≤ safe, or
        # the font at its floor (a lone verse taller than the screen — the scroller
        # is the intended backstop).
        for _ in range(64):
            idx, natural = self._tallest_natural(width)   # measure every page
            if natural <= safe:
                break
            start, end = self._pages[idx]      # the genuinely tallest one
            if (not self._verse_at_a_time and (end - start) > 1
                    and self._present_pt <= base):
                tighter = present_paging.tighten_capacity(
                    self._capacity, safe, natural)
                if tighter is not None and tighter < self._capacity:
                    self._capacity = tighter
                    self._build_pages()
                    continue
            if self._scale_font(safe, natural):
                continue
            if self._present_pt > self._SIZE_MIN_PT:
                self._present_pt -= 1          # break the rounding stall
                continue
            break                              # at min font — scroller backstop
        # Phase 2 — grow toward the fill target, but never past the ceiling. A
        # single pt step can jump the whole [fill, safe] band (bigger font wraps
        # more, so height is super-linear in pt), so any grow that breaches safe is
        # reverted. Monotone up and capped ⇒ the exit height is always ≤ safe.
        if have_real:
            natural = self._tallest_natural(width)[1]
            for _ in range(64):
                if natural >= fill:
                    break
                prev = self._present_pt
                if not self._scale_font(fill, natural):
                    break                      # at max font — accept the margin
                natural = self._tallest_natural(width)[1]
                if natural > safe:
                    self._present_pt = prev    # overshoot — keep the safe size
                    break

    # ── Render ────────────────────────────────────────────────────────────────
    def _render(self):
        # Font and pagination are fixed per chapter by _fit_chapter, so a step is
        # a plain repaint — same size on every slide.
        self._paint_page()
        GLib.idle_add(self._scroll_to_top)

    def _current_page(self):
        if not self._pages:
            return None
        return self._pages[min(self._stepper.index, len(self._pages) - 1)]

    def _paint_page(self):
        self._eyebrow.set_text(self._eyebrow_text())
        page = self._current_page()
        if page is None:
            self._text.set_visible(True)
            self._grid.set_visible(False)
            self._text.set_markup('')
            return
        self._paint_slice(*page)

    def _paint_slice(self, start, end):
        """Render items [start:end) into the text label (single) or the grid
        (parallel). Split from _paint_page so the fit pass can paint — and
        measure — any page, not just the current one."""
        dark = Adw.StyleManager.get_default().get_dark()
        if self._effective_parallel():
            self._text.set_visible(False)
            self._grid.set_visible(True)
            self._clear_grid()
            row = 0
            for verse, html_a, html_b in self._rows[start:end]:
                self._grid.attach(
                    self._cell(html_a, dark, Gtk.Justification.RIGHT, 1.0),
                    0, row, 1, 1)
                if self._show_numbers and verse:
                    spine = Gtk.Label(label=str(verse))
                    spine.add_css_class('present-spine')
                    spine.set_valign(Gtk.Align.START)
                    self._grid.attach(spine, 1, row, 1, 1)
                self._grid.attach(
                    self._cell(html_b, dark, Gtk.Justification.LEFT, 0.0),
                    2, row, 1, 1)
                row += 1
            return
        self._text.set_visible(True)
        self._grid.set_visible(False)
        parts = []
        for verse, html in self._verses[start:end]:
            text = _html_to_markup(html, dark).strip()
            if not text:
                continue
            if self._show_numbers and verse:
                # Small, dimmed, raised verse number — enough to locate a verse
                # on the slide without competing with the words.
                parts.append(
                    f'<span size="55%" rise="7000" fgalpha="42000">'
                    f'{verse} </span>{text}')
            else:
                parts.append(text)
        self._text.set_markup(self._sized('  '.join(parts)))

    def _cell(self, html, dark, justify, xalign):
        lbl = Gtk.Label()
        lbl.add_css_class('present-text')
        lbl.set_wrap(True)
        lbl.set_use_markup(True)
        lbl.set_selectable(False)
        lbl.set_justify(justify)
        lbl.set_hexpand(True)
        lbl.set_halign(Gtk.Align.FILL)
        lbl.set_valign(Gtk.Align.START)
        lbl.set_xalign(xalign)          # block hugs the spine (right) or margin (left)
        lbl.set_markup(self._sized(_html_to_markup(html, dark).strip()) if html
                       else '')
        return lbl

    def _clear_grid(self):
        child = self._grid.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._grid.remove(child)
            child = nxt

    def _eyebrow_text(self):
        if not self._book:
            return self._translation or ''
        ref = f'{book_label(self._book)} {self._chapter}'
        items = self._page_items()
        if self._verse_at_a_time and self._pages and items:
            start, _end = self._pages[min(self._stepper.index,
                                          len(self._pages) - 1)]
            ref = f'{book_label(self._book)} {self._chapter}:{items[start][0]}'
        parts = [ref]
        if self._translation:
            parts.append(self._translation)
        if self._effective_parallel() and self._translation_b:
            parts.append(self._translation_b)
        if not self._verse_at_a_time and self._stepper.count > 1:
            parts.append(f'{self._stepper.index + 1}/{self._stepper.count}')
        return '   ·   '.join(parts)

    def _scroll_to_top(self):
        self._scroller.get_vadjustment().set_value(0)
        return GLib.SOURCE_REMOVE
