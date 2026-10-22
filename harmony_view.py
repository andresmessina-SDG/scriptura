"""harmony_view.py — The Harmony of the Gospels, the pane page.

Robertson's 185 sections down the left, in his 14 parts; each row ends in its
fourfold sign, four dots in canonical order, filled where the section is told.
Pick one (or walk them with Up and Down) and the page shows it: Robertson's
heading and setting, then the accounts side by side in the Bible beside the
page, Matthew, Mark, Luke, John, never reordered. A word whose Greek another
account here also uses is underlined, from the Bible's Strong's numbers.

Two lenses, one switch. Robertson's sets the accounts of one event beside
each other. Eusebius's sets out the rows of his canon tables that touch the
section: each passage beside the ones he paired it with, whether or not they
tell the same event (the Lord's Prayer in Matthew 6 beside Luke 11).

Above the accounts, the four pillars: each Gospel from first verse to last,
the section lit where it falls in each. Below them, the links to other
sections, drawn as The Creeds draws its threads: solid the same event, fine
said elsewhere, dashed a similar event, a hollow dot only here. Each names its
witness; a measured one has a dashed pill.

No commentary: the words are Robertson's headings and the Gospels'. Colour
follows the two-accent law: references are accent (they go to the Bible).
"""

from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

import content
import harmony
import settings
import sword_bridge
import tasks
from a11y import set_accessible_label
from creeds_view import _MARK, _THREAD, _label, _quotation, _swatch, _vbox
from family_card import high_contrast, lift, redraw_on_contrast
from gtk_utils import clear_children
from i18n import _, book_label, ngettext

#: Below this width the outline moves into a popover; below the second the
#: page is a phone's.
WIDE_SP = 880
NARROW_SP = 420
#: The least width a Gospel column reads at; fewer fit, they wrap.
COL_MIN = 220
#: A pillar's height, and the room between two.
STRIP_H = 7
STRIP_GAP = 5

#: The links' strokes, The Creeds' grammar: solid is "this is that", fine
#: "this echoes that", dashed "this resembles that".
_STROKE = {'same_event': _THREAD['w'], 'same_words': _THREAD['t'],
           'look_alike': _THREAD['f']}

_WITNESS = {
    'robertson': ('Robertson', 'A. T. Robertson, A Harmony of the Gospels '
                  '(1922), after John A. Broadus'),
    'eusebius': ('Eusebius', 'Eusebius of Caesarea, the canon tables '
                 '(4th century), in the INTF edition'),
}
#: Oldest first.
_WITNESS_ORDER = ('eusebius', 'robertson')

#: The section the opening offers to try: the one miracle in all four.
EXAMPLE = '72'


def _hollow(cr, ink):
    cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.8)
    cr.set_line_width(1.2)
    cr.arc(13, 5, 3.2, 0, 6.2832)
    cr.stroke()


def gospel_name(code: str) -> str:
    return book_label(harmony.BOOK[code])


class HarmonyPage:
    """The pane subsystem: the outline, the lens, the section."""

    def __init__(self, pane=None):
        self._pane = pane
        sel = settings.get('harmony_section') or None
        self._sel: str | None = sel if harmony.section(sel or '') else None
        self._lens = ('eusebius' if settings.get('harmony_lens') == 'eusebius'
                      else 'robertson')
        self._wide = True
        self._narrow = False
        self._built = False
        self._font_pt = 0
        self._width = 0
        self._module: str | None = None
        self._rows: dict[str, Gtk.Button] = {}
        self._cells: list[dict] = []
        self._account_rows: list[dict] | None = None
        self._grid: Gtk.Grid | None = None
        self._texts: dict[tuple, list] = {}
        self._font_provider = Gtk.CssProvider()
        self.widget = Adw.BreakpointBin()
        self.widget.set_size_request(300, 200)
        # One breakpoint is in force at a time, the last added that matches.
        self._bp_medium = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(
            f'max-width: {WIDE_SP}sp'))
        self._bp_narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(
            f'max-width: {NARROW_SP}sp'))
        self.widget.add_breakpoint(self._bp_medium)
        self.widget.add_breakpoint(self._bp_narrow)
        self.widget.connect('notify::current-breakpoint', self._on_breakpoint)

    # ── building ─────────────────────────────────────────────────────────

    def _build(self):
        self._built = True
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # The lens in the app's page switcher; the outline's door and the
        # steps beside it when the outline is not on screen.
        self._lenses = Adw.ToggleGroup()
        self._lenses.add_css_class('round')
        self._lenses.add_css_class('page-switcher')
        self._lenses.add(Adw.Toggle(name='robertson', label='Robertson'))
        self._lenses.add(Adw.Toggle(name='eusebius', label='Eusebius'))
        self._lenses.set_active_name(self._lens)
        self._lenses.connect('notify::active-name', self._on_lens)
        self._outline_btn = Gtk.MenuButton(label=_('Sections'))
        self._outline_btn.add_css_class('flat')
        self._outline_pop = Gtk.Popover()
        self._outline_btn.set_popover(self._outline_pop)
        self._outline_pop.connect('show', self._on_outline_open)
        steps = Gtk.Box(spacing=2)
        self._prev = Gtk.Button(icon_name='scriptura-go-previous-symbolic')
        self._next = Gtk.Button(icon_name='scriptura-go-next-symbolic')
        for b, label, d in ((self._prev, _('Previous section'), -1),
                            (self._next, _('Next section'), 1)):
            b.add_css_class('flat')
            b.set_tooltip_text(label)
            b.connect('clicked', lambda _b, d=d: self._step(d))
            steps.append(b)
        self._steps = steps
        bar = Gtk.CenterBox()
        bar.set_margin_start(14)
        bar.set_margin_end(14)
        bar.set_margin_top(8)
        bar.set_margin_bottom(4)
        bar.set_start_widget(self._outline_btn)
        bar.set_center_widget(self._lenses)
        bar.set_end_widget(steps)
        root.append(bar)

        self._body = Gtk.Box()
        self._body.set_vexpand(True)
        root.append(self._body)

        self._outline = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._outline.add_css_class('harmony-outline')
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._on_key)
        self._outline.add_controller(keys)
        self._outline_scroll = Gtk.ScrolledWindow()
        self._outline_scroll.set_policy(Gtk.PolicyType.NEVER,
                                        Gtk.PolicyType.AUTOMATIC)
        self._outline_scroll.set_child(self._outline)
        self._outline_scroll.add_css_class('harmony-outline-scroll')
        # Set, so the titles' expand cannot widen the outline past its width.
        self._outline_scroll.set_hexpand(False)
        self._fill_outline()

        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._page.set_margin_start(20)
        self._page.set_margin_end(20)
        self._page.set_margin_top(12)
        self._page.set_margin_bottom(40)
        # Measures the page's width, for how many columns fit on a line.
        self._probe = Gtk.DrawingArea(hexpand=True, content_height=1)
        self._probe.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self._probe.connect('resize', self._on_width)
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._page.append(self._probe)
        self._page.append(self._content)
        clamp = Adw.Clamp(maximum_size=1100, tightening_threshold=900)
        clamp.set_child(self._page)
        self._main = Gtk.ScrolledWindow()
        self._main.set_hexpand(True)
        self._main.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._main.set_child(clamp)
        self._body.append(self._main)

        esc = Gtk.EventControllerKey()
        esc.connect('key-pressed', self._on_escape)
        root.add_controller(esc)
        self.widget.set_child(root)
        self._apply_width()
        self._show()

    def _fill_outline(self):
        for part in harmony.data().get('parts', []):
            head = _label(f"{part['n']}  {part['heading']}", 'harmony-part')
            self._outline.append(head)
            for sid in part['sections']:
                s = harmony.section(sid) or {}
                num = Gtk.Label(label=sid, xalign=0, yalign=0)
                num.add_css_class('harmony-num')
                num.set_size_request(30, -1)
                sign = _sign(s.get('gospels', []))
                sign.set_valign(Gtk.Align.START)
                sign.set_margin_top(6)
                title = Gtk.Label(label=s.get('heading', ''), xalign=0,
                                  wrap=True)
                title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                title.set_max_width_chars(34)
                title.set_hexpand(True)
                title.add_css_class('harmony-row-title')
                box = Gtk.Box(spacing=8)
                box.append(num)
                box.append(title)
                box.append(sign)
                btn = Gtk.Button(child=box)
                btn.add_css_class('flat')
                btn.add_css_class('harmony-row')
                set_accessible_label(btn, _('Section {n}, {gospels}: '
                                            '{title}').format(
                    n=sid, gospels=', '.join(gospel_name(g)
                                             for g in s.get('gospels', [])),
                    title=s.get('heading', '')))
                btn.connect('clicked', self._on_row, sid)
                self._outline.append(btn)
                self._rows[sid] = btn

    # ── choosing ─────────────────────────────────────────────────────────

    def render(self):
        """Show the page (called when a pane turns to the harmony)."""
        if not self._built:
            self._build()
        elif self._reading_module() != self._module:
            self._show()

    def apply_font_size(self, pt: int):
        """The Gospel text follows the pane's reading size; the rest is
        chrome and follows the desktop."""
        if not pt or pt == self._font_pt:
            return
        self._font_pt = pt
        self._font_provider.load_from_data(
            f'.harmony-text {{ font-size: {pt}pt; }}'.encode())

    def select(self, sid: str | None):
        if sid is not None and harmony.section(sid) is None:
            return
        self._sel = sid
        settings.put('harmony_section', sid or '')
        self._show()
        self._main.get_vadjustment().set_value(0)
        btn = self._rows.get(sid or '')
        if btn is not None and self._wide:
            GLib.idle_add(self._keep_in_view, btn)

    def _on_row(self, _btn, sid: str):
        # Up and Down walk the rows with the popover open; a click closes it.
        if self._outline_pop.get_visible():
            self._outline_pop.popdown()
        self.select(sid)

    def _on_outline_open(self, _pop):
        btn = self._rows.get(self._sel or '')
        if btn is not None:
            GLib.idle_add(self._keep_in_view, btn)

    def show_section(self, sid: str):
        """Open the page at a section (for a door from elsewhere)."""
        if not self._built:
            self._build()
        self.select(sid)
        btn = self._rows.get(sid)
        if btn is not None and self._wide:
            GLib.idle_add(self._reveal, btn)

    def current_section(self) -> str | None:
        return self._sel

    def _keep_in_view(self, btn):
        """Scroll the outline so the chosen row shows, unless it already
        does; focus stays where it is."""
        ok, b = btn.compute_bounds(self._outline)
        if ok:
            adj = self._outline_scroll.get_vadjustment()
            top, page = adj.get_value(), adj.get_page_size()
            if not top <= b.get_y() <= top + page - b.get_height():
                adj.set_value(min(max(0, b.get_y() - page / 3),
                                  adj.get_upper() - page))
        return GLib.SOURCE_REMOVE

    def _reveal(self, btn):
        btn.grab_focus()
        return GLib.SOURCE_REMOVE

    def _step(self, d: int):
        ids = harmony.section_ids()
        i = ids.index(self._sel) + d if self._sel in ids else 0
        if 0 <= i < len(ids):
            self.select(ids[i])

    def _on_lens(self, group, _pspec):
        lens = group.get_active_name()
        if not lens or lens == self._lens:
            return
        self._lens = lens
        settings.put('harmony_lens', lens)
        self._show()

    def _on_key(self, _ctl, keyval, _code, _state):
        if keyval not in (Gdk.KEY_Up, Gdk.KEY_Down):
            return False
        root = self.widget.get_root()
        focus = root.get_focus() if root else None
        cur = self._sel
        for sid, btn in self._rows.items():
            if focus is not None and (focus is btn or focus.is_ancestor(btn)):
                cur = sid
        ids = harmony.section_ids()
        if cur not in ids:
            return False
        i = ids.index(cur) + (1 if keyval == Gdk.KEY_Down else -1)
        if 0 <= i < len(ids):
            self.select(ids[i])
            self._rows[ids[i]].grab_focus()
        return True

    def _on_escape(self, _ctl, keyval, _code, _state):
        if keyval != Gdk.KEY_Escape or self._sel is None:
            return False
        sid = self._sel
        self.select(None)
        if sid in self._rows and self._wide:
            self._rows[sid].grab_focus()
        return True

    def _on_breakpoint(self, bin_, _pspec):
        bp = bin_.get_current_breakpoint()
        self._wide = bp is None
        self._narrow = bp is self._bp_narrow
        if self._built:
            self._apply_width()

    def _apply_width(self):
        """The outline beside the page when wide, in a popover when not."""
        parent = self._outline_scroll.get_parent()
        if self._wide and parent is not self._body:
            self._outline_pop.set_child(None)
            self._outline_scroll.set_size_request(320, -1)
            self._outline_scroll.set_propagate_natural_height(False)
            self._body.prepend(self._outline_scroll)
        elif not self._wide and parent is not self._outline_pop:
            if parent is not None:
                self._body.remove(self._outline_scroll)
            self._outline_scroll.set_size_request(340, 480)
            self._outline_pop.set_child(self._outline_scroll)
        self._outline_btn.set_visible(not self._wide)
        self._steps.set_visible(not self._wide)

    def _on_width(self, _area, width, _height):
        if self._per_line(width) != self._per_line(self._width):
            self._width = width
            self._place_cells()
        self._width = width

    def _per_line(self, width: int) -> int:
        """How many columns go on a line at this width: as many as fit,
        evened out, so four that fit three to a line go two and two."""
        n = len(self._slots()) or 1
        lines = -(-n // max(1, min(n, width // COL_MIN)))
        return -(-n // lines)

    # ── the page ─────────────────────────────────────────────────────────

    def _reading_module(self) -> str | None:
        """The Bible the accounts are read in: the one beside the page, else
        the one this pane showed before, else the first Bible there is."""
        pane = self._pane
        root = pane.get_root() if pane is not None else None
        for other in (getattr(root, 'pane1', None), getattr(root, 'pane2', None)):
            if (other is not None and other is not pane and other.get_visible()
                    and content.is_text_bible(other.module)):
                return str(other.module)
        came = getattr(pane, '_came_from', None)
        if came and content.is_text_bible(came):
            return str(came)
        first = getattr(root, '_first_bible_module', None)
        return first() if first is not None else 'KJV'

    def _show(self):
        for sid, btn in self._rows.items():
            if sid == self._sel:
                btn.add_css_class('chosen')
            else:
                btn.remove_css_class('chosen')
        self._prev.set_sensitive(self._sel not in (None, harmony.section_ids()[0]))
        self._next.set_sensitive(self._sel != harmony.section_ids()[-1])
        clear_children(self._content)
        self._cells = []
        self._grid = None
        self._account_rows = None
        self._module = self._reading_module()
        if self._sel is None:
            self._content.append(self._opening())
            return
        self._content.append(self._header(self._sel))
        self._content.append(self._band(self._sel))
        self._content.append(self._accounts(self._sel))
        links = harmony.other_links(self._sel)
        if links:
            self._content.append(self._links(links))
        # Facts about the text come after it, not before (his call).
        for fact, verse in harmony.facts(self._sel):
            self._content.append(self._fact(fact, verse))

    def _header(self, sid: str) -> Gtk.Widget:
        s = harmony.section(sid) or {}
        part = harmony.part_of(sid) or {}
        box = _vbox(4, 'harmony-head')
        box.append(_label(f"{part.get('n', '')} · {part.get('heading', '')}",
                          'creeds-kicker'))
        box.append(_label(s.get('heading', ''), 'creeds-title'))
        cite = [_('Robertson § {n}').format(n=sid)]
        tables = harmony.canons(sid)
        if tables:
            cite.append(_('Eusebius {canons}').format(canons=', '.join(tables)))
        spans = [r for rs in harmony.gospel_spans(sid).values() for r in rs]
        spans += harmony.other_spans(sid)
        cite.append('; '.join(harmony.ref_text(r) for r in spans))
        box.append(_label('  ·  '.join(cite), 'harmony-cite'))
        for line in s.get('setting', []):
            box.append(_label(line, 'harmony-setting'))
        for line in s.get('summary') or []:
            box.append(_label(line, 'harmony-setting'))
        if s.get('compare'):
            box.append(_label(s['compare'], 'harmony-setting'))
        return box

    def _kind_line(self, sid: str) -> Gtk.Widget:
        """What joins the accounts: the stroke, its name, its witnesses."""
        row = Adw.WrapBox(child_spacing=8, line_spacing=6)
        gospels = (harmony.section(sid) or {}).get('gospels', [])
        if self._lens == 'eusebius':
            row.append(_label(_('The rows of Eusebius’s tables that touch '
                                'this section, each passage beside those he '
                                'paired with it'), 'creeds-ui'))
            return row
        if len(gospels) < 2:
            row.append(_swatch(_hollow))
            row.append(_label(_('Only in {gospel}').format(
                gospel=gospel_name(gospels[0])) if gospels else
                _(harmony.KIND_NAMES['only_here']), 'creeds-ui'))
            row.append(self._witness('robertson'))
            return row
        link = harmony.same_event(sid) or {}
        row.append(_swatch(_STROKE['same_event']))
        row.append(_label(_(harmony.KIND_NAMES['same_event']), 'creeds-ui'))
        for w in _WITNESS_ORDER:
            if w in link.get('witnesses', ['robertson']):
                row.append(self._witness(w))
        if link.get('shares_words'):
            row.append(self._measured(True))
        return row

    def _witness(self, w: str) -> Gtk.Widget:
        name, full = _WITNESS[w]
        t = _label(name, 'creeds-witness')
        t.set_tooltip_text(full)
        return t

    def _measured(self, words: bool) -> Gtk.Widget:
        t = _label(_('Same words in the Greek') if words
                   else _('Same teaching'), 'creeds-witness')
        t.add_css_class('creeds-witness-measured')
        t.set_tooltip_text(
            _('Measured from the Greek words: these passages share more of '
              'them than chance gives') if words else
            _('Measured from the Greek words: these passages share few of '
              'them; they agree in what they teach'))
        return t

    def _fact(self, fact: str, verse) -> Gtk.Widget:
        import interlinear_data
        row = Gtk.Box(spacing=8)
        row.add_css_class('harmony-fact')
        row.append(_label(fact, 'creeds-ui'))
        if verse is not None and interlinear_data.is_installed(
                interlinear_data.GREEK):
            btn = Gtk.Button(label=_('Readings'))
            btn.add_css_class('flat')
            btn.add_css_class('creeds-ref')
            btn.set_valign(Gtk.Align.CENTER)
            btn.set_tooltip_text(_('Show what the Greek editions read, in the '
                                   'interlinear'))
            btn.connect('clicked', lambda _b, v=verse: self._open_readings(*v))
            row.append(btn)
        return row

    # ── the pillars ──────────────────────────────────────────────────────

    def _band(self, sid: str) -> Gtk.Widget:
        """Each Gospel from first verse to last, the section lit where it
        falls; the passages it links to marked in their strokes."""
        lit: dict[str, list] = {b: [] for b in harmony.GOSPELS}
        if self._lens == 'eusebius':
            mine = harmony.gospel_spans(sid)
            for row in harmony.eusebius_rows(sid):
                for b, entries in row['cells'].items():
                    for e in entries:
                        inside = any(harmony.overlaps(e['span'], r)
                                     for r in mine.get(b, []))
                        lit[b].append((harmony.place(e['span']),
                                       'section' if inside else 'same_words'))
        else:
            for b, spans in harmony.gospel_spans(sid).items():
                lit[b] += [(harmony.place(r), 'section') for r in spans]
            for m in harmony.other_links(sid):
                for r in m['spans']:
                    lit[r['book']].append((harmony.place(r), m['kind']))
        grid = Gtk.Grid(column_spacing=10, row_spacing=STRIP_GAP)
        grid.add_css_class('harmony-band')
        for i, b in enumerate(harmony.GOSPELS):
            name = _label(gospel_name(b), 'harmony-band-label')
            name.set_wrap(False)
            grid.attach(name, 0, i, 1, 1)
            strip = Gtk.DrawingArea(hexpand=True, content_height=STRIP_H)
            strip.set_valign(Gtk.Align.CENTER)
            strip.set_draw_func(self._draw_strip, lit[b])
            strip.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            redraw_on_contrast(strip)
            grid.attach(strip, 1, i, 1, 1)
        set_accessible_label(grid, _('Where the section falls in each Gospel'))
        return grid

    def _draw_strip(self, area, cr, w, h, marks):
        ink = area.get_color()
        hc = high_contrast()

        def src(alpha):
            cr.set_source_rgba(ink.red, ink.green, ink.blue, lift(alpha, hc))

        src(0.10)
        cr.rectangle(0, 1, w, h - 2)
        cr.fill()
        # The links first, so the section draws over them.
        for (a, z), kind in sorted(marks, key=lambda m: m[1] == 'section'):
            x = a * w
            if kind == 'section':
                src(0.85)
                cr.rectangle(x, 0, max(2.5, (z - a) * w), h)
                cr.fill()
                continue
            cr.set_line_width(1.2 if kind == 'look_alike' else 1)
            src(0.8 if kind == 'look_alike' else 0.5)
            if kind == 'look_alike':
                cr.set_dash([2, 1.5])
            cr.move_to(x + 0.5, 0)
            cr.line_to(x + 0.5, h)
            cr.stroke()
            cr.set_dash([])

    # ── the accounts ─────────────────────────────────────────────────────

    def _slots(self) -> list[str]:
        """The Gospels that get a column: those told here (Robertson), or any
        in a row (Eusebius), in canonical order."""
        if self._sel is None:
            return []
        if self._lens == 'eusebius':
            found = {b for r in harmony.eusebius_rows(self._sel)
                     for b in r['cells']}
            return [b for b in harmony.GOSPELS if b in found]
        return list(harmony.gospel_spans(self._sel))

    def _accounts(self, sid: str) -> Gtk.Widget:
        box = _vbox(10, 'harmony-accounts')
        box.append(self._kind_line(sid))
        self._note = _label('', 'creeds-hint')
        self._note.set_visible(False)
        box.append(self._note)
        rows: list[dict]
        if self._lens == 'eusebius':
            rows = [{'head': _canon_head(r), 'cells': [
                {'book': b, 'spans': [e['span'] for e in r['cells'][b]],
                 'eus': [e['id'] for e in r['cells'][b]]}
                for b in self._slots() if b in r['cells']]}
                for r in harmony.eusebius_rows(sid)]
        else:
            rows = [{'head': None, 'cells': [
                {'book': b, 'spans': spans, 'eus': []}
                for b, spans in harmony.gospel_spans(sid).items()]}]
        self._account_rows = rows
        self._grid = Gtk.Grid(column_spacing=22, row_spacing=10)
        self._grid.set_column_homogeneous(True)
        box.append(self._grid)
        self._read(rows)
        return box

    def _read(self, rows: list[dict]):
        """Fetch the accounts' words off the main loop, then lay them out."""
        module = self._module or 'KJV'
        want = [(module, _span_key(sp)) for r in rows for c in r['cells']
                for sp in c['spans']]
        spans = {_span_key(sp): sp for r in rows for c in r['cells']
                 for sp in c['spans']}
        missing = [k for k in want if k not in self._texts]

        def work(_task):
            return {k: harmony.passage(module, spans[k[1]]) for k in missing}

        def done(found):
            self._texts.update(found)
            if self._account_rows is rows:
                self._fill(rows, module)

        if missing:
            tasks.submit(f'harmony:{id(self)}', work, done,
                         lambda _exc: done({}))
        else:
            self._fill(rows, module)

    def _fill(self, rows: list[dict], module: str):
        self._cells = []
        tagged = False
        for r in rows:
            words = [[v for sp in c['spans'] for v in self._texts.get(
                (module, _span_key(sp)), [])] for c in r['cells']]
            shared = harmony.shared_numbers(words)
            tagged |= any(nums for col in words for _c, _v, ws in col
                          for _t, nums in ws)
            cells = [self._cell(c, w, s) for c, w, s in
                     zip(r['cells'], words, shared)]
            self._cells.append({'head': r['head'], 'cells': cells,
                                'books': [c['book'] for c in r['cells']]})
        self._note.set_label(
            _('Underlined: a word whose Greek another passage here also uses.')
            if tagged else
            _('{bible} carries no Strong’s numbers, so the words the passages '
              'share are not underlined.').format(
                bible=sword_bridge.display_name(module)))
        self._note.set_visible(any(len(c['cells']) > 1 for c in self._cells))
        self._place_cells()

    def _cell(self, cell: dict, verses: list, shared: set) -> Gtk.Widget:
        box = _vbox(6, 'harmony-cell')
        head = Gtk.Box(spacing=6)
        head.add_css_class('harmony-col-head')
        name = _label(gospel_name(cell['book']), 'creeds-kicker')
        name.set_wrap(False)
        head.append(name)
        refs = Adw.WrapBox(child_spacing=4, line_spacing=2)
        refs.set_hexpand(True)
        refs.set_halign(Gtk.Align.END)
        for sp, eid in zip(cell['spans'], cell['eus'] or [None] * len(
                cell['spans'])):
            chip = Gtk.Button(label=harmony.ref_text(sp, with_book=False))
            chip.add_css_class('flat')
            chip.add_css_class('creeds-ref')
            chip.set_tooltip_text(_('Open in the Bible'))
            chip.connect('clicked', lambda _b, s=sp: self._open(s))
            set_accessible_label(chip, harmony.ref_text(sp))
            refs.append(chip)
            if eid:
                n = _label(_('§ {n}').format(n=eid.split('.')[1]), 'harmony-num')
                n.set_tooltip_text(_('Eusebius’s section number in this Gospel'))
                refs.append(n)
        head.append(refs)
        box.append(head)
        text = Gtk.Label(xalign=0, yalign=0, wrap=True, use_markup=True)
        text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text.set_markup(_markup(verses, shared))
        text.add_css_class('harmony-text')
        text.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        text.set_selectable(True)
        box.append(text)
        return box

    def _place_cells(self):
        """Lay the cells out, as many to a line as fit; in Eusebius's lens
        each row under its canon, each Gospel keeping its column."""
        grid = self._grid
        if grid is None:
            return
        for child in list(grid):
            grid.remove(child)
        slots = self._slots()
        per = self._per_line(self._width)
        aligned = per >= len(slots)
        y = 0
        for r in self._cells:
            if r['head'] is not None:
                head = _label(r['head'], 'harmony-canon')
                grid.attach(head, 0, y, max(1, per), 1)
                y += 1
            for i, (book, cell) in enumerate(zip(r['books'], r['cells'])):
                k = slots.index(book) if aligned else i
                grid.attach(cell, k % per, y + k // per, 1, 1)
            used = len(slots) if aligned else len(r['cells'])
            y += (used + per - 1) // per

    # ── the links ────────────────────────────────────────────────────────

    def _links(self, links: list[dict]) -> Gtk.Widget:
        box = _vbox(0, 'harmony-links')
        for kind in ('look_alike', 'same_words'):
            mine = [m for m in links if m['kind'] == kind]
            if not mine:
                continue
            head = _label(f"{_(harmony.KIND_NAMES[kind])} · {len(mine)}",
                          'creeds-section-head')
            head.set_margin_top(18)
            head.set_margin_bottom(4)
            box.append(head)
            for m in mine:
                box.append(self._link_row(m))
        return box

    def _link_row(self, m: dict) -> Gtk.Widget:
        row = Gtk.Box(spacing=12)
        row.add_css_class('harmony-link')
        sw = _swatch(_STROKE[m['kind']])
        sw.set_valign(Gtk.Align.START)
        sw.set_margin_top(6)
        row.append(sw)
        col = _vbox(4, 'harmony-link-body')
        col.set_hexpand(True)
        target = harmony.section(m['section']) if m['section'] else None
        if target is not None:
            go = Gtk.Button()
            go.set_child(_label(_('§ {n}  {title}').format(
                n=target['id'], title=target['heading']), 'harmony-target'))
            go.add_css_class('flat')
            go.add_css_class('harmony-target-btn')
            go.set_tooltip_text(_('Show this section'))
            go.connect('clicked', lambda _b, i=target['id']: self.select(i))
            col.append(go)
        refs = Adw.WrapBox(child_spacing=6, line_spacing=6)
        for sp in m['spans']:
            chip = Gtk.Button(label=harmony.ref_text(sp))
            chip.add_css_class('flat')
            chip.add_css_class('creeds-ref')
            chip.set_tooltip_text(_('Open in the Bible'))
            chip.connect('clicked', lambda _b, s=sp: self._open(s))
            refs.append(chip)
        for w in _WITNESS_ORDER:
            if w in m['witnesses']:
                refs.append(self._witness(w))
        if m['kind'] == 'same_words':
            refs.append(self._measured(m['shares_words']))
        col.append(refs)
        if m.get('quote'):
            q = _label(f"“{m['quote']}”", 'harmony-quote')
            col.append(q)
            col.append(_label('Robertson', 'creeds-cite'))
        row.append(col)
        return row

    # ── the opening ──────────────────────────────────────────────────────

    def _opening(self) -> Gtk.Widget:
        """Before a section is picked: why four, how to read the links (with
        a section to try), the witnesses."""
        box = _vbox(10, 'harmony-opening')
        box.append(_label(_(harmony.DISPLAY_NAME), 'creeds-title'))
        d = harmony.data()
        n = len(d.get('sections', []))
        shared = sum(1 for s in d.get('sections', []) if len(s['gospels']) > 1)
        box.append(_label('   '.join((
            ngettext('{n} section', '{n} sections', n).format(n=n),
            ngettext('{n} told in more than one Gospel',
                     '{n} told in more than one Gospel', shared).format(n=shared),
            ngettext('{n} Eusebian section', '{n} Eusebian sections',
                     len(d.get('eusebius', []))).format(
                n=len(d.get('eusebius', []))))), 'creeds-facts'))
        for q in d.get('opening', []):
            box.append(_quotation(q))

        head = _label(_('Reading the links'), 'creeds-kicker')
        head.set_margin_top(12)
        box.append(head)
        for kind, draw in (('same_event', _STROKE['same_event']),
                           ('same_words', _STROKE['same_words']),
                           ('look_alike', _STROKE['look_alike']),
                           ('only_here', _hollow)):
            row = Gtk.Box(spacing=10)
            sw = _swatch(draw)
            sw.set_valign(Gtk.Align.START)
            sw.set_margin_top(5)
            row.append(sw)
            col = _vbox(2, 'creeds-reading')
            col.append(_label(_(harmony.KIND_NAMES[kind]), 'creeds-ui'))
            quote = d.get('kinds', {}).get(kind, {}).get('quote')
            if quote:
                col.append(_label(f'“{quote}” Robertson', 'harmony-quote'))
            row.append(col)
            box.append(row)
        ex = harmony.section(EXAMPLE)
        if ex is not None:
            text = Gtk.Label(xalign=0, wrap=True)
            text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            text.set_label(_('Try § {n}: {title}').format(
                n=EXAMPLE, title=ex['heading']))
            btn = Gtk.Button(child=text)
            btn.add_css_class('flat')
            btn.add_css_class('creeds-example')
            btn.connect('clicked', lambda _b: self.select(EXAMPLE))
            box.append(btn)

        head = _label(_('The witnesses'), 'creeds-kicker')
        head.set_margin_top(12)
        box.append(head)
        for w in _WITNESS_ORDER:
            box.append(_label(_WITNESS[w][1], 'creeds-witness-line'))
        box.append(_label(_('Pick a section to begin. Up and Down move between '
                            'sections; Esc comes back here.'), 'creeds-hint'))
        return box

    # ── doors ────────────────────────────────────────────────────────────

    def _open(self, span: dict):
        """Open a passage in the Bible beside the page, the channel The
        Creeds' chips use."""
        cb = getattr(self._pane, '_on_word_study_navigate', None)
        if cb is not None:
            c, v = span['start']
            cb(harmony.BOOK[span['book']], c, v)

    def _open_readings(self, book: str, chapter: int, verse: int):
        """The Greek interlinear in the other pane, at the verse, with its
        Variants line on."""
        import interlinear_data
        pane = self._pane
        root = pane.get_root() if pane is not None else None
        panes = (getattr(root, 'pane1', None), getattr(root, 'pane2', None))
        other = next((p for p in panes if p is not None and p is not pane), None)
        if other is None:
            return
        split = getattr(root, '_btn_split', None)
        if split is not None and not split.get_active():
            split.set_active(True)
        if other.module != interlinear_data.GREEK:
            other._apply_module_change(interlinear_data.GREEK)
        # Its own chip, so the line shows now and the choice is saved; the
        # reader loads its saved lines only when the app starts.
        other._interlinear._chip_btns['variants'].set_active(True)
        other.load_reference_at_verse(book, chapter, verse)


# ── helpers ──────────────────────────────────────────────────────────────

def _span_key(span: dict) -> tuple:
    return (span['book'], *span['start'], *span['end'])


def _canon_head(row: dict) -> str:
    gospels = harmony.CANON_GOSPELS[row['table']]
    if not gospels:
        return _('Canon X · only in {gospel}').format(
            gospel=gospel_name(next(iter(row['cells']))))
    return _('Canon {n} · {gospels}').format(
        n=row['table'], gospels=', '.join(gospel_name(b) for b in gospels))


def _markup(verses: list, shared: set) -> str:
    """The passage as markup: small verse numbers (the chapter where it
    changes), the shared words underlined in the marks' grey."""
    out, chapter = [], None
    for c, v, words in verses:
        n = f'{c}:{v}' if c != chapter else str(v)
        chapter = c
        out.append(f'<span size="70%" rise="3pt" fgalpha="55%">{n}</span> ')
        for text, nums in words:
            t = GLib.markup_escape_text(text)
            if nums & shared:
                t = (f'<span underline="single" '
                     f'underline_color="{_MARK}">{t}</span>')
            out.append(t)
        out.append(' ')
    return ''.join(out).strip()


def _sign(gospels: list[str]) -> Gtk.DrawingArea:
    """The fourfold sign: four dots, Matthew to John, filled where told."""
    area = Gtk.DrawingArea(content_width=26, content_height=8)
    area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    told = [b in gospels for b in harmony.GOSPELS]

    def draw(ar, cr, w, h):
        ink = ar.get_color()
        cr.set_source_rgba(ink.red, ink.green, ink.blue,
                           lift(0.55, high_contrast()))
        cr.set_line_width(1.1)
        for i, on in enumerate(told):
            cr.arc(4 + i * 6, h / 2, 2.1, 0, 6.2832)
            cr.fill() if on else cr.stroke()

    area.set_draw_func(draw)
    redraw_on_contrast(area)
    return area
