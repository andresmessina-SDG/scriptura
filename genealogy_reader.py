"""genealogy_reader.py — the "Book of Generations" pane subsystem.

The standalone surface: a document of drawn genealogies you open in a pane the
way you open Scripture in Stone. Each chart is a live `Gtk.DrawingArea`
painting the primitives `genealogy_layout` computed — the *same* primitives the
static SVG plates are written from, so what is on screen and what prints
cannot drift apart.

Live where it earns it. A chart here can be expanded (a folded run of plain
generations opens in place), can switch textual tradition, and every name and
verse in it is clickable: a verse drives the partnered Bible pane, a name
opens the person, and a name on one chart can carry the reader to the chart
that draws them best. None of that is possible in a printed plate, and none of
it changes the geometry — the reader hands the layout a new parameter and
repaints.

Reading order matters here. The two-witness chart is followed by the classical
explanations, attributed and unranked, and never by a verdict.
"""

from __future__ import annotations

import logging

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Adw, GLib, Pango, PangoCairo, Gdk  # noqa: E402

import a11y                              # noqa: E402
import genealogy_bridge as gb            # noqa: E402
import genealogy_layout as gl            # noqa: E402
import motion                            # noqa: E402
from genealogy_svg import PALETTE        # noqa: E402
from i18n import _                       # noqa: E402

_log = logging.getLogger('scriptura.genealogy')

_TEXT_W = 680          # the app's comfortable reading measure
_CHART_MAX = 1040      # a chart may run wider than the prose, like a plate

#: The stack name of the title page. Every other page is named for the
#: chart it draws, and no chart may be called this.
_FRONT = 'front'

_SANS = 'Adwaita Sans, Inter, sans-serif'
#: A family LIST, and it has to start where the rest of the app starts.
#: Newsreader carries no Cyrillic, so a bare 'Newsreader' would send every
#: Russian name on these charts to whatever fontconfig picks for an unknown
#: family — a sans face — while the English rows stayed in the reading serif.
#: Same chain as verse_card, passage_print and data/style.css, guarded by
#: tests/test_verse_card.py so a fourth surface cannot drift off it.
SERIF = 'Newsreader, Source Serif 4, Charter, Georgia, serif'


def _rgba(hex_or_role: str, dark: bool) -> tuple[float, float, float]:
    pair = PALETTE.get(hex_or_role) or PALETTE['ink']
    h = (pair[1] if dark else pair[0]).lstrip('#')
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


class ChartArea(Gtk.DrawingArea):
    """One chart, painted from its plate and clickable through its hit list.

    The widget owns two pieces of state and nothing else: which folded runs
    the reader has opened, and which tradition is selected. Both are layout
    parameters, so acting on a click means rebuilding the plate and queueing a
    draw — there is no second copy of the drawing to keep in step."""

    def __init__(self, chart_id: str, on_verse=None, on_person=None,
                 on_chart=None):
        super().__init__()
        self._cid = chart_id
        self._on_verse = on_verse
        self._on_person = on_person
        self._on_chart = on_chart
        self._expanded: set[int] = set()
        self._tradition = ''
        self._plate: gl.Plate | None = None
        self._hover: gl.Hit | None = None
        self._layout_width = 0.0
        self._scale = 1.0
        self._reading_pt = 0.0
        self._cache: dict[tuple[str, float, str], float] = {}
        self._pending = 0
        #: The width the plate in hand was actually laid out for. Not the
        #: same as `_layout_width`, which is the width the widget has been
        #: GIVEN — between the two lies the frame where a resize has arrived
        #: and the new plate has not been built yet.
        self._laid_at = -1.0

        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.connect('resize', self._on_resize)

        click = Gtk.GestureClick.new()
        click.connect('pressed', self._on_click)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion.new()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        self.add_controller(motion)

        # Keyboard reach: the chart is one focusable stop whose description is
        # the text equivalent. A drawn tree is invisible to a screen reader
        # without one, and a canvas with no accessible name is worse than no
        # chart at all.
        self.set_focusable(True)
        self.update_property([Gtk.AccessibleProperty.LABEL], [''])

    # ── measurement ────────────────────────────────────────────────────────
    def _measure(self, text: str, size: float, weight: str = 'normal') -> float:
        """Pango, not an estimate.

        The layout's own fallback is deliberately generous and would leave the
        chart looking loose; more importantly, a translated string measured by
        character count is exactly how this app shipped two overflow bugs.

        Cached, because measuring is most of the cost of a rebuild and a
        rebuild happens on every resize step: `_ellipsize` binary-searches and
        `_wrap` walks word by word, so one caption can be twenty layouts. Luke
        alone was 5.6ms, and the reader holds eight charts.
        """
        key = (text, size, weight)
        got = self._cache.get(key)
        if got is None:
            lay = self.create_pango_layout(text)
            lay.set_font_description(_font(size, weight))
            got = self._cache[key] = float(lay.get_pixel_size().width)
        return got

    def _build(self, width: float) -> gl.Plate:
        # Laid out at the nominal size and painted through a Cairo scale, so
        # one number moves type, row pitch, chips and dots together. Scaling
        # the font sizes alone would grow the glyphs inside a 56px row pitch
        # that never moved.
        return gl.build(self._cid, self._measure, width / self._scale,
                        expanded=self._expanded, tradition=self._tradition)

    #: The reading size the chart geometry is drawn for: a pane set to this
    #: gets scale 1.0 and the plate at its natural size.
    BASE_PT = 12.5

    #: The narrowest a chart may be laid out in. Measured, not chosen: at
    #: 700px every caption on every chart fits within its line budget in all
    #: three languages, and below it they start being cut.
    MIN_LAYOUT_PX = 700.0

    def set_reading_size(self, pt: float) -> None:
        if pt and pt != self._reading_pt:
            self._reading_pt = pt
            self._refresh()

    def _scale_for(self, width: float) -> float:
        """The paint scale for this width — and the chart is never laid out
        narrower than `MIN_LAYOUT_PX`.

        Both directions come out of the same number. Above the minimum the
        scale grows the type with the reading size, capped so the chart never
        loses text to gain size: at 23pt an uncapped scale gave each chart
        446px and cut sixteen captions mid-word.

        Below the minimum it shrinks instead, and that is the half his narrow
        screenshots demanded. These are figures with a fixed number of columns
        — a name, its gloss, a verse chip, sometimes a mother out to the left
        and a register rail out to the right — and squeezing them does not
        reflow anything: the chip is placed from the right edge, so it lands
        on top of the name. Laying out at the minimum and painting it down
        keeps every proportion the chart was designed with. Small and right
        beats full-size and overlapping.

        This is the floor for the PROSE — 700px is where the captions stop
        being cut. What a chart's own columns need is a second floor, wider
        in Spanish and Russian than in English, and the layout measures that
        for itself; `_lay_out` picks up whichever plate comes back.
        """
        if width <= 0:
            return 1.0
        if width < self.MIN_LAYOUT_PX:
            return width / self.MIN_LAYOUT_PX
        if not self._reading_pt:
            return 1.0
        wanted = max(0.85, self._reading_pt / self.BASE_PT)
        return max(0.85, min(wanted, width / self.MIN_LAYOUT_PX))

    def _lay_out(self, w: float) -> gl.Plate:
        """The plate for a pane this wide, the scale that paints it, and the
        text a screen reader gets instead. The one place a plate is built."""
        self._layout_width = self._laid_at = w
        self._scale = self._scale_for(w)
        self._plate = plate = self._build(w)
        # A chart is allowed to refuse the width it was given. Its columns
        # are fixed — mother, thread, name, verse chip, register rail — and
        # narrowing the plate does not reflow them, it drops the chip onto
        # the name, so the layout measures what it needs and hands back a
        # wider plate. Paint that one down to the pane it has.
        if plate.width > w / self._scale + 0.5:
            self._scale = w / plate.width
        self.set_content_height(int(plate.height * self._scale))
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [plate.alt or plate.title])
        return plate

    def _refresh(self) -> None:
        """Rebuild unconditionally: the callers are the things that change a
        plate without changing its width — the reading size, an opened fold,
        another textual tradition."""
        w = self._layout_width or float(self.get_width())
        if w <= 0:
            return
        self._lay_out(w)
        self.queue_draw()

    def _on_resize(self, _area, width, _height):
        w = float(width)
        if w <= 0 or abs(w - self._layout_width) < 1:
            return
        self._layout_width = w
        # Laid out from an idle, not from inside the allocation. A chart's
        # height is a function of its width, so `_refresh` calls
        # `set_content_height` — and doing that while GTK is allocating asks
        # the parent to resize in the middle of the pass that is resizing it.
        # A ScrolledWindow absorbs that request rather than passing it on, so
        # the page kept the height it had when the chart was still empty: on
        # a page of its own, where the chart IS the page, that height was the
        # viewport's and the chart was clipped to nothing at all. One frame
        # later the same work lands as an ordinary resize and propagates.
        if not self._pending:
            self._pending = GLib.idle_add(self._refresh_idle)

    def _refresh_idle(self):
        self._pending = 0
        # `_draw` may already have laid this width out — it builds on the
        # spot rather than paint a plate cut for a width the widget no longer
        # has. Then there is nothing here to do but let it stand.
        if abs(self._laid_at - self._layout_width) >= 1:
            self._refresh()
        return GLib.SOURCE_REMOVE

    # ── painting ───────────────────────────────────────────────────────────
    def _draw(self, _area, cr, width, height):
        # Measured against the width the PLATE was cut for, not the width the
        # widget was handed: a resize sets the second one frames before the
        # first, and comparing the wrong one paints the previous step's chart
        # inside the current step's pane for every frame of a window drag.
        if self._plate is None or abs(width - self._laid_at) > 1:
            self._lay_out(float(width))
        dark = Adw.StyleManager.get_default().get_dark()
        cr.save()
        cr.scale(self._scale, self._scale)
        for prim in self._plate.prims:
            self._paint(cr, prim, dark)
        if self._hover is not None:
            r, g, b = _rgba('link', dark)
            cr.set_source_rgba(r, g, b, 0.10)
            _rounded(cr, self._hover.x - 4, self._hover.y - 2,
                     self._hover.w + 8, self._hover.h + 4, 5)
            cr.fill()
        cr.restore()

    def _paint(self, cr, p: gl.Prim, dark: bool):
        r, g, b = _rgba(p.role, dark)
        cr.set_source_rgb(r, g, b)
        if p.kind in ('line', 'hatch'):
            cr.set_line_width(2.5 if p.role == 'thread' else
                              (1.4 if p.role in ('rule', 'rule-soft', 'muted')
                               else 2.0))
            cr.set_dash(list(p.dash) if p.dash else [])
            cr.move_to(p.x, p.y)
            cr.line_to(p.x2, p.y2)
            cr.stroke()
            cr.set_dash([])
        elif p.kind == 'poly':
            if not p.points:
                return
            cr.set_line_width(1.8)
            cr.move_to(*p.points[0])
            for pt in p.points[1:]:
                cr.line_to(*pt)
            cr.stroke()
        elif p.kind == 'dot':
            cr.arc(p.x, p.y, p.r, 0, 6.2832)
            cr.fill()
        elif p.kind in ('rect', 'band'):
            if p.role == 'thread-wash':
                cr.set_source_rgba(r, g, b, 0.13)
            elif p.role == 'life':
                cr.set_source_rgba(r, g, b, 0.55)
            elif p.role == 'hatch-life':
                _hatch(cr, p, r, g, b)
                return
            _rounded(cr, p.x, p.y, p.w, p.h, p.r)
            cr.fill()
        elif p.kind == 'chip':
            _rounded(cr, p.x, p.y, p.w, p.h, p.r)
            if p.role == 'chip-on':
                cr.fill()
                cr.set_source_rgb(*_rgba('paper', dark))
            else:
                cr.set_source_rgba(r, g, b, 0.5)
                cr.set_line_width(1.0)
                cr.stroke()
                cr.set_source_rgb(r, g, b)
            self._text(cr, p.text, p.x + p.w / 2, p.y + p.h / 2 - p.size * 0.72,
                       p.size, p.weight or 'semibold', 'middle', False, False)
        elif p.kind == 'text':
            self._text(cr, p.text, p.x, p.y - p.size, p.size, p.weight,
                       p.anchor, p.style == 'italic', p.serif)

    def _text(self, cr, text, x, y, size, weight, anchor, italic, serif):
        lay = self.create_pango_layout(text)
        lay.set_font_description(_font(size, weight, italic, serif))
        w, _h = lay.get_pixel_size()
        if anchor == 'middle':
            x -= w / 2
        elif anchor == 'end':
            x -= w
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)

    # ── interaction ────────────────────────────────────────────────────────
    def _hit(self, x: float, y: float) -> gl.Hit | None:
        if self._plate is None:
            return None
        # Pointer coordinates are widget-space; hit regions are plate-space,
        # which the paint scales up. Divide, or every target moves away from
        # its own name the moment the reading size leaves the default.
        x, y = x / self._scale, y / self._scale
        # Last match wins: hits are appended in paint order, so the topmost
        # region is the one the reader can see.
        found = None
        for hit in self._plate.hits:
            if hit.x <= x <= hit.x + hit.w and hit.y <= y <= hit.y + hit.h:
                found = hit
        return found

    def _on_motion(self, _c, x, y):
        hit = self._hit(x, y)
        if hit is not self._hover:
            self._hover = hit
            self.set_cursor(Gdk.Cursor.new_from_name(
                'pointer' if hit else 'default', None))
            self.set_tooltip_text(hit.label if hit else None)
            self.queue_draw()

    def _on_leave(self, _c):
        if self._hover is not None:
            self._hover = None
            self.set_cursor(None)
            self.queue_draw()

    def _on_click(self, _g, _n, x, y):
        hit = self._hit(x, y)
        if hit is None:
            return
        if hit.kind == 'expand':
            try:
                idx = int(hit.payload.rsplit(':', 1)[1])
            except (ValueError, IndexError):
                return
            # Folds only open. A fold that closed again on the second click
            # would swallow the row the reader had just gone to read.
            self._expanded.add(idx)
            self._refresh()
        elif hit.kind == 'tradition':
            self._tradition = hit.payload
            self._refresh()
        elif hit.kind == 'verse' and self._on_verse:
            parts = hit.payload.split('|')
            if len(parts) == 3:
                self._on_verse(parts[0], int(parts[1]), int(parts[2]))
        elif hit.kind == 'person' and self._on_person:
            self._on_person(hit.payload)
        elif hit.kind == 'chart' and self._on_chart and hit.payload:
            self._on_chart(hit.payload)


_font_cache: dict[tuple, Pango.FontDescription] = {}


def _font(size: float, weight: str, italic: bool = False,
          serif: bool = False) -> Pango.FontDescription:
    key = (size, weight, italic, serif)
    fd = _font_cache.get(key)
    if fd is None:
        fd = Pango.FontDescription.from_string(
            '%s %.1f' % (SERIF if serif else _SANS, size))
        fd.set_weight({'bold': Pango.Weight.BOLD,
                       'semibold': Pango.Weight.SEMIBOLD}.get(
                           weight, Pango.Weight.NORMAL))
        if italic:
            fd.set_style(Pango.Style.ITALIC)
        _font_cache[key] = fd
    return fd


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    if r <= 0:
        cr.rectangle(x, y, w, h)
        return
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def _hatch(cr, p, r, g, b):
    """The 45° rule pattern that marks Enoch's bar — he does not die, and a
    bar that ended like the others would say he did."""
    cr.save()
    _rounded(cr, p.x, p.y, p.w, p.h, p.r)
    cr.clip()
    cr.set_source_rgb(r, g, b)
    cr.set_line_width(3)
    step = 6
    x = p.x - p.h
    while x < p.x + p.w + p.h:
        cr.move_to(x, p.y + p.h)
        cr.line_to(x + p.h, p.y)
        cr.stroke()
        x += step
    cr.restore()


class GenealogyReader:
    """The pane subsystem: a book of genealogies, one to a page.

    Like Scripture in Stone it is a document you open rather than a
    verse-keyed panel that follows the Bible beside it — but unlike it, this
    document is paged. Eight charts on one scroll made the reader do the
    finding: a chart is a figure to be looked AT, and the next one arriving
    under it as you read told you nothing except that there was more. A page
    holds one chart, its introduction and whatever classical readings hang on
    it, and the running foot turns to the next.

    Paging pays twice. Only the visible page is allocated, so a window drag
    rebuilds one chart instead of eight, and the reader always knows where
    they are in the book.
    """

    def __init__(self, pane=None):
        self._pane = pane
        self._built = False
        self._areas: list[ChartArea] = []
        #: Chart id per page, in reading order. The first is '' — the title
        #: page, which draws nothing and belongs to no chart.
        self._pages: list[str] = []
        self._titles: list[str] = []
        self._scrolls: list[Gtk.ScrolledWindow] = []
        self._toc_rows: list[Gtk.Widget] = []
        self._at = 0
        self._font_pt = 0
        self._build_widget()

    @property
    def widget(self):
        return self._root

    # ── construction ───────────────────────────────────────────────────────
    def _build_widget(self):
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.add_css_class('stone-topbar')
        self._contents = Gtk.MenuButton(label=_('Contents'))
        self._contents.add_css_class('flat')
        bar.append(self._contents)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)
        self._root.append(bar)

        # A CssProvider styles only the widget it is added to ([[gtk-traps]]),
        # so sharing the `.stone-page` class with the archaeology reader does
        # not share its font-size provider. Without this the reading-size
        # setting reached this pane and did nothing at all. One provider,
        # added to every page: the pages are siblings, not descendants.
        self._font_provider = Gtk.CssProvider()

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        # The page slides the way the reader turned it, which is the whole
        # reason this is a Stack and not a Notebook: Gtk.Stack takes the
        # direction from the children's own order.
        self._stack.set_transition_type(
            Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(motion.DURATION_SHORT)
        self._root.append(self._stack)
        self._root.append(self._build_foot())

    def _build_foot(self) -> Gtk.Widget:
        """The running foot: turn one way, turn the other, and where you are.

        A book's page number sits in the outer corner and its running title
        across the middle, so that is where these go. The title ellipsizes
        and the number never can — a translated title is longer than the
        English ([[i18n-width-traps]]) and "3 of 8" is the half a reader
        cannot reconstruct.
        """
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        foot.add_css_class('gen-foot')

        self._prev = self._turn_button('scriptura-go-previous-symbolic',
                                       _('Previous page'), -1)
        self._next = self._turn_button('scriptura-go-next-symbolic',
                                       _('Next page'), 1)

        self._foot_title = Gtk.Label(label='')
        self._foot_title.add_css_class('gen-foot-title')
        self._foot_title.set_ellipsize(Pango.EllipsizeMode.END)
        self._foot_title.set_hexpand(True)
        self._foot_count = Gtk.Label(label='')
        self._foot_count.add_css_class('gen-foot-count')

        # The title is centred on the FOOT, not on the space left over beside
        # the page number, so a wide number does not shove it off centre.
        gap = Gtk.Box()
        group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        group.add_widget(gap)
        group.add_widget(self._foot_count)

        foot.append(self._prev)
        foot.append(gap)
        foot.append(self._foot_title)
        foot.append(self._foot_count)
        foot.append(self._next)
        return foot

    def _turn_button(self, icon: str, label: str, step: int) -> Gtk.Button:
        btn = Gtk.Button(icon_name=icon, tooltip_text=label)
        btn.add_css_class('flat')
        # An icon-only button needs an explicit accessible name; a tooltip is
        # not a reliable AT-SPI label.
        btn.update_property([Gtk.AccessibleProperty.LABEL], [label])
        btn.connect('clicked', lambda *_a: self.turn(step))
        return btn

    def ensure_built(self):
        if self._built:
            return
        self._built = True
        try:
            self._render()
        except Exception:
            _log.exception('genealogy document failed to render')

    def _render(self):
        doc = gb.document()
        self._add_page('', _(doc['title']), self._front(doc))
        for c in doc['charts']:
            # A lifespan chart declared as another chart's companion is drawn
            # with it rather than as its own page, so Genesis 5 reads as one
            # thing: the list, then the field of lives it implies.
            if self._is_companion(c['id'], doc):
                continue
            self._add_page(c['id'], _(c['title']), self._section(c, doc))
        self._contents.set_popover(self._build_contents(doc))
        self._show(0)

    def _add_page(self, cid: str, title: str, body: Gtk.Widget) -> None:
        """One page of the book: its own scroll, its own paper, its own place
        in the stack. A chart is tall, so a page still scrolls — and because
        each page keeps its own adjustment, turning away and back returns the
        reader to the line they left."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.add_css_class('stone-page')
        page.add_css_class('gen-page')
        page.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        page.append(body)
        clamp = Adw.Clamp(maximum_size=_CHART_MAX, tightening_threshold=_TEXT_W)
        clamp.set_child(page)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, cid or _FRONT)
        self._pages.append(cid)
        self._titles.append(title)
        self._scrolls.append(scroll)

    def _build_contents(self, doc) -> Gtk.Popover:
        """The table of contents, printed the way a book prints one: what it
        is, which text it draws, and the page it is on.

        The title page does not list itself, and the numbering counts it —
        page 2 is the second page of the book, not the second chart."""
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu.set_margin_top(6)
        menu.set_margin_bottom(6)
        menu.set_margin_start(6)
        menu.set_margin_end(6)
        self._toc_rows = []
        for i, cid in enumerate(self._pages):
            if not cid:
                continue
            c = gb.chart(cid)
            row = Gtk.Button()
            row.add_css_class('flat')
            row.add_css_class('gen-toc')
            row.set_halign(Gtk.Align.FILL)
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            names.set_hexpand(True)
            t = Gtk.Label(label=self._titles[i], xalign=0)
            t.add_css_class('gen-toc-title')
            names.append(t)
            if c is not None and c['passage']:
                sub = Gtk.Label(label=_(c['passage']), xalign=0)
                sub.add_css_class('gen-toc-passage')
                names.append(sub)
            line.append(names)
            n = Gtk.Label(label='%d' % (i + 1))
            n.add_css_class('gen-toc-page')
            n.set_valign(Gtk.Align.CENTER)
            line.append(n)
            row.set_child(line)
            row.connect('clicked', lambda _b, k=i: self._pick(k))
            menu.append(row)
            self._toc_rows.append(row)
        pop = Gtk.Popover()
        pop.set_child(menu)
        return pop

    @staticmethod
    def _is_companion(cid: str, doc) -> bool:
        return any(c['companion'] == cid for c in doc['charts'])

    def _front(self, doc) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class('gen-front')
        box.set_margin_top(40)
        box.set_margin_bottom(16)
        t = Gtk.Label(label=_(doc['title']), xalign=0)
        t.add_css_class('gen-hero')
        t.set_wrap(True)
        box.append(t)
        if doc['subtitle']:
            s = Gtk.Label(label=_(doc['subtitle']), xalign=0)
            s.add_css_class('gen-deck')
            s.set_wrap(True)
            box.append(s)
        if doc['body']:
            b = Gtk.Label(label=_(doc['body']), xalign=0)
            b.add_css_class('gen-intro')
            b.set_wrap(True)
            b.set_margin_top(16)
            box.append(b)
        return box

    def _section(self, c, doc) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class('gen-section')
        box.set_margin_top(24)

        kicker = Gtk.Label(label=_(c['passage']), xalign=0)
        kicker.add_css_class('gen-kicker')
        box.append(kicker)
        t = Gtk.Label(label=_(c['title']), xalign=0)
        t.add_css_class('gen-title')
        t.set_wrap(True)
        box.append(t)
        if c['subtitle']:
            s = Gtk.Label(label=_(c['subtitle']), xalign=0)
            s.add_css_class('gen-deck')
            s.set_wrap(True)
            box.append(s)
        if c['intro']:
            i = Gtk.Label(label=_(c['intro']), xalign=0)
            i.add_css_class('gen-intro')
            i.set_wrap(True)
            i.set_margin_top(12)
            i.set_margin_bottom(20)
            box.append(i)

        box.append(self._chart_area(c['id']))
        if c['companion']:
            comp = gb.chart(c['companion'])
            if comp is not None:
                sub = Gtk.Label(label=_(comp['title']), xalign=0)
                sub.add_css_class('gen-subhead')
                sub.set_margin_top(28)
                box.append(sub)
                if comp['intro']:
                    ci = Gtk.Label(label=_(comp['intro']), xalign=0)
                    ci.add_css_class('gen-intro')
                    ci.set_wrap(True)
                    ci.set_margin_bottom(16)
                    box.append(ci)
                box.append(self._chart_area(comp['id']))

        for r in gb.readings_for(c['id']):
            box.append(self._reading(r))
        return box

    def _chart_area(self, cid: str) -> Gtk.Widget:
        area = ChartArea(cid, on_verse=self._go_to_verse,
                         on_person=self._show_person,
                         on_chart=self.open_chart)
        area.set_margin_top(8)
        self._areas.append(area)
        return area

    def _reading(self, r) -> Gtk.Widget:
        """One classical explanation, attributed and unranked.

        These sit *below* the drawing and never on it. The chart's job is to
        say where the two witnesses differ; choosing between the answers is
        not the app's to do, so each carries its author and its own weakest
        point."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class('gen-reading')
        box.set_margin_top(20)
        t = Gtk.Label(label=_(r['title']), xalign=0)
        t.add_css_class('gen-subhead')
        t.set_wrap(True)
        box.append(t)
        b = Gtk.Label(label=_(r['body']), xalign=0)
        b.add_css_class('gen-intro')
        b.set_wrap(True)
        box.append(b)
        if r['attribution']:
            a = Gtk.Label(label=_(r['attribution']), xalign=0)
            a.add_css_class('gen-attribution')
            a.set_wrap(True)
            box.append(a)
        if r['caveat']:
            cv = Gtk.Label(label=_('Against it: %s') % _(r['caveat']), xalign=0)
            cv.add_css_class('gen-caveat')
            cv.set_wrap(True)
            box.append(cv)
        return box

    # ── turning the page ───────────────────────────────────────────────────
    def turn(self, step: int) -> None:
        """One page forward or back. The book does not wrap: the last page
        has no next, and the foot says so by going insensitive."""
        self._show(self._at + step)

    def _pick(self, index: int) -> None:
        pop = self._contents.get_popover()
        if pop is not None:
            pop.popdown()
        self._show(index)

    def _show(self, index: int) -> None:
        index = max(0, min(index, len(self._pages) - 1))
        if not self._pages:
            return
        turned = index != self._at
        self._at = index
        self._stack.set_visible_child_name(self._pages[index] or _FRONT)
        # No running head on the title page: a book does not print one there,
        # and the page says the document's name in type an inch tall already.
        self._foot_title.set_label(
            self._titles[index] if self._pages[index] else '')
        self._foot_count.set_label(
            _('%(page)d of %(total)d') % {'page': index + 1,
                                          'total': len(self._pages)})
        # Focus must not die under the reader's finger. The arrow they just
        # pressed goes insensitive at the end of the book, and GTK drops the
        # focus to nothing rather than moving it — Tab then starts over at the
        # top of the window, which is where a keyboard reader gets stranded.
        # Hand it to the arrow that still works, BEFORE the other one goes.
        first, last = index == 0, index == len(self._pages) - 1
        if last and not first and self._next.has_focus():
            self._prev.grab_focus()
        elif first and not last and self._prev.has_focus():
            self._next.grab_focus()
        self._prev.set_sensitive(not first)
        self._next.set_sensitive(not last)
        if turned:
            # Turning a page moves nothing a screen reader is looking at: the
            # foot's two labels change and focus stays on the arrow. Said out
            # loud, once, the way every other status line in the app is.
            a11y.announce(self._foot_title, '%s, %s' % (
                self._titles[index], self._foot_count.get_label()))
        # The contents marks where the reader is, the way a finger in a book
        # does. `_toc_rows` skips the title page, so it is one short.
        for i, row in enumerate(self._toc_rows, start=1):
            if i == index:
                row.add_css_class('gen-toc-current')
            else:
                row.remove_css_class('gen-toc-current')

    def open_chart(self, cid: str) -> None:
        """Turn to the page that draws this chart, at its top.

        A cross-reference is an arrival at a new subject, so it does not
        resume where that page was left — unlike a page turn, which does.
        A companion chart has no page of its own; it is drawn on its host's.

        Built on demand, because this is the one entry point that can arrive
        before the document has been opened: the lineage marker beside a
        Bible verse loads this module into the other pane and asks for a
        chart in the same breath, and an unbuilt book has no pages to turn
        to — it would land on the title page and look like a dead link.
        """
        self.ensure_built()
        if cid in self._pages:
            index = self._pages.index(cid)
        else:
            host = next((c['id'] for c in gb.document()['charts']
                         if c['companion'] == cid), '')
            if host not in self._pages:
                return
            index = self._pages.index(host)
        self._show(index)
        GLib.idle_add(self._to_top, self._scrolls[index])

    @staticmethod
    def _to_top(scroll: Gtk.ScrolledWindow):
        scroll.get_vadjustment().set_value(0)
        return GLib.SOURCE_REMOVE

    def _go_to_verse(self, book: str, chapter: int, verse: int):
        """Drive the partnered Bible pane, the same channel a Strong's link
        uses (window._go_to)."""
        pane = self._pane
        if pane is None:
            return
        cb = getattr(pane, '_on_word_study_nav', None)
        if callable(cb):
            cb(book, chapter, verse)

    def _show_person(self, pid: str):
        """Open the chart that draws this person, when it is not this one."""
        cid = gb.chart_containing(pid)
        if cid:
            self.open_chart(cid)

    def render(self):
        """The PaneContent protocol's entry point. Builds on first show and
        does nothing after: this is a document, not a verse-keyed panel."""
        self.ensure_built()

    def apply_font_size(self, pt: int):
        """Match the pane's reading size — the prose through CSS, the charts
        through a paint scale.

        Both halves were missing. `.stone-page` is styled by a provider each
        reader installs on its own widget, and this one never installed it, so
        the prose ignored the setting; and `_font_pt` was stored and never
        read, so `rescale()` rebuilt eight identical plates. At his 23pt the
        document was large type around 13pt charts.

        Each chart works out its own scale from its own allocated width —
        see `ChartArea._scale_for` — because at this point none of them has
        been allocated yet.
        """
        if not pt or self._font_pt == pt:
            return
        self._font_pt = pt
        self._font_provider.load_from_data(
            f'.stone-page {{ font-size: {pt}pt; }}'.encode())
        for area in self._areas:
            area.set_reading_size(pt)

    def rescale(self, *_a):
        """Re-measure everything after a reading-size or theme change.

        The plates are measured with Pango at the size in force when they were
        built, so a font change has to rebuild them — repainting alone would
        draw new glyph sizes into geometry computed for the old ones."""
        for area in self._areas:
            area._refresh()
