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

import genealogy_bridge as gb            # noqa: E402
import genealogy_layout as gl            # noqa: E402
from genealogy_svg import PALETTE        # noqa: E402
from i18n import _                       # noqa: E402

_log = logging.getLogger('scriptura.genealogy')

_TEXT_W = 680          # the app's comfortable reading measure
_CHART_MAX = 1040      # a chart may run wider than the prose, like a plate

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
        """How much bigger the chart may be drawn at this width.

        Capped by width, not by taste. Growing the type lays the chart out
        narrower — the pane does not get wider — and past a point that costs
        whole sentences: at 23pt an uncapped scale gave each chart 446px and
        cut sixteen captions mid-word. A chart must never lose text to gain
        size, so the ceiling is whatever still leaves `MIN_LAYOUT_PX`, and in
        a wider window it rises on its own.
        """
        if not self._reading_pt or width <= 0:
            return 1.0
        wanted = max(0.85, self._reading_pt / self.BASE_PT)
        return max(0.85, min(wanted, width / self.MIN_LAYOUT_PX))

    def _refresh(self) -> None:
        w = self._layout_width or float(self.get_width())
        if w <= 0:
            return
        self._scale = self._scale_for(w)
        self._plate = self._build(w)
        self.set_content_height(int(self._plate.height * self._scale))
        alt = self._plate.alt or self._plate.title
        self.update_property([Gtk.AccessibleProperty.LABEL], [alt])
        self.queue_draw()

    def _on_resize(self, _area, width, _height):
        w = float(width)
        if w <= 0 or abs(w - self._layout_width) < 1:
            return
        self._layout_width = w
        self._refresh()

    # ── painting ───────────────────────────────────────────────────────────
    def _draw(self, _area, cr, width, height):
        if self._plate is None or abs(width - self._layout_width) > 1:
            self._layout_width = float(width)
            self._scale = self._scale_for(float(width))
            self._plate = self._build(float(width))
            self.set_content_height(int(self._plate.height * self._scale))
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
    """The pane subsystem. Built once, rendered once — like Scripture in Stone
    it is a document you open, not a verse-keyed panel that follows the Bible
    beside it."""

    def __init__(self, pane=None):
        self._pane = pane
        self._built = False
        self._anchors: dict[str, Gtk.Widget] = {}
        self._areas: list[ChartArea] = []
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
        self._contents = Gtk.MenuButton(label=_('Charts'))
        self._contents.add_css_class('flat')
        bar.append(self._contents)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)
        self._root.append(bar)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        self._root.append(self._scroll)

        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._page.add_css_class('stone-page')
        self._page.add_css_class('gen-page')
        # A CssProvider styles only the widget it is added to ([[gtk-traps]]),
        # so sharing the `.stone-page` class with the archaeology reader does
        # not share its font-size provider. Without this the reading-size
        # setting reached this pane and did nothing at all.
        self._font_provider = Gtk.CssProvider()
        self._page.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        clamp = Adw.Clamp(maximum_size=_CHART_MAX, tightening_threshold=_TEXT_W)
        clamp.set_child(self._page)
        self._scroll.set_child(clamp)

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
        self._front(doc)
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu.set_margin_top(6)
        menu.set_margin_bottom(6)
        menu.set_margin_start(6)
        menu.set_margin_end(6)

        for c in doc['charts']:
            # A lifespan chart declared as another chart's companion is drawn
            # with it rather than as its own section, so Genesis 5 reads as
            # one thing: the list, then the field of lives it implies.
            if self._is_companion(c['id'], doc):
                continue
            self._section(c, doc)
            btn = Gtk.Button(label=_(c['title']))
            btn.add_css_class('flat')
            btn.set_halign(Gtk.Align.FILL)
            btn.get_child().set_xalign(0)
            btn.connect('clicked', lambda _b, cid=c['id']: self.scroll_to(cid))
            menu.append(btn)

        pop = Gtk.Popover()
        pop.set_child(menu)
        self._contents.set_popover(pop)

    @staticmethod
    def _is_companion(cid: str, doc) -> bool:
        return any(c['companion'] == cid for c in doc['charts'])

    def _front(self, doc):
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
        self._page.append(box)

    def _section(self, c, doc):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class('gen-section')
        box.set_margin_top(40)

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

        self._anchors[c['id']] = box
        self._page.append(box)

    def _chart_area(self, cid: str) -> Gtk.Widget:
        area = ChartArea(cid, on_verse=self._go_to_verse,
                         on_person=self._show_person,
                         on_chart=self.scroll_to)
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

    # ── navigation ─────────────────────────────────────────────────────────
    def scroll_to(self, cid: str):
        w = self._anchors.get(cid)
        if w is None:
            return
        GLib.idle_add(self._do_scroll, w)

    def _do_scroll(self, w):
        ok, y = w.translate_coordinates(self._page, 0, 0)
        if ok:
            adj = self._scroll.get_vadjustment()
            adj.set_value(max(0, y - 24))
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
            self.scroll_to(cid)

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
