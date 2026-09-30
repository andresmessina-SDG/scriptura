"""creeds_view.py — The Creeds, the pane page.

Each creed is set in sense-lines, one phrase to a line, and every line ends in
a tick. Pick a line (or walk them with Up and Down) and threads run from its
tick to the verses it is drawn from, on a strip that is the whole Bible:
Genesis at the top, Revelation at the foot, each Testament filling half. Pick
a book on the strip and the lines that draw on it light instead.

Three kinds of link, drawn three ways: the same words (a solid thread), the
same teaching (a fine one), foretold (dashed). A thread grows heavier with
each older witness that cites the verse for the same article. Verses sitting
close together get their own labels, fanned out, each tied back to its true
place on the strip by a small knot, so four verses of John 1 read as four.

Every verse reference goes to the Bible beside the page, the way Scripture in
Stone's chips do. Colour follows the two-accent law: references are accent
(they go to the Bible); nothing on the page is clay.

The detail sits beside the lines when the pane is wide, and opens under the
chosen line when it is not. On a narrow pane the strip turns sideways above
the lines and the threads are not drawn.
"""

from __future__ import annotations

import math

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk, Pango

import creeds
import motion
import settings
from a11y import set_accessible_label
from family_card import high_contrast, lift, redraw_on_contrast
from gtk_utils import clear_children
from i18n import _, book_label, ngettext

#: Width of the Bible strip, and of the label column beside it.
STRIP_W = 12
#: The run the threads cross between the lines' ticks and the strip.
FIELD_W = 120
LABELS_W = 176
#: Least room between two labels, and between a label and the next.
LABEL_GAP = 24
BOOK_GAP = 21
#: Below this width the detail opens under the line; below the second the
#: strip turns sideways and the threads go.
WIDE_SP = 880
NARROW_SP = 560
THREAD_MS = 550


def ref_label(link: dict) -> str:
    """A reference in the reader's language, from its canonical book."""
    tail = link['ref'][len(link['book']):].strip()
    return f"{book_label(link['book'])} {tail}"


def spread(items: list[dict], gap: float, lo: float, hi: float) -> None:
    """Give each item a `py` near its `y`, in order, at least `gap` apart,
    each crowded run centred on its true places, all within lo..hi."""
    items.sort(key=lambda it: it['y'])
    groups: list[dict] = []
    for it in items:
        groups.append({'start': it['y'], 'items': [it]})
        while len(groups) > 1:
            a, b = groups[-2], groups[-1]
            if a['start'] + len(a['items']) * gap <= b['start']:
                break
            a['items'] += b['items']
            groups.pop()
            mean = sum(x['y'] for x in a['items']) / len(a['items'])
            a['start'] = mean - (len(a['items']) - 1) * gap / 2
    floor = lo
    for g in groups:
        g['start'] = max(g['start'], floor)
        floor = g['start'] + len(g['items']) * gap
    ceil = hi
    for g in reversed(groups):
        g['start'] = min(g['start'], ceil - (len(g['items']) - 1) * gap)
        ceil = g['start'] - gap
    for g in groups:
        for k, it in enumerate(g['items']):
            it['py'] = g['start'] + k * gap


def _bezier_length(p0, p1, p2, p3, n=16) -> float:
    total, prev = 0.0, p0
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        x = (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0]
             + t ** 3 * p3[0])
        y = (u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1]
             + t ** 3 * p3[1])
        total += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
    return total


class CreedsPage:
    """The pane subsystem: the creed tabs, the lines, the drawing, the detail."""

    def __init__(self, pane=None):
        self._pane = pane
        self._creed_id = settings.get('creeds_tab') or 'apostles'
        if self._creed_id not in creeds.CREED_IDS:
            self._creed_id = 'apostles'
        self._orig = settings.get('creeds_text') == 'orig'
        self._sel: str | None = None
        self._book: str | None = None
        self._hot: str | None = None
        self._focus_ref: str | None = None
        self._wide = True
        self._narrow = False
        self._progress = 1.0
        self._anim = None
        self._rows: dict[str, Gtk.Button] = {}
        self._texts: dict[str, Gtk.Label] = {}
        self._geo: dict | None = None
        self._layout_pending = False
        self._built = False
        self._font_pt = 0
        self._chips: dict[str, Gtk.Button] = {}

        self._font_provider = Gtk.CssProvider()
        self.widget = Adw.BreakpointBin()
        self.widget.set_size_request(300, 200)
        # One breakpoint is in force at a time, the last added that matches;
        # so the page's width is read from which one that is.
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

        # The three creeds in the app's page switcher, and the text switch.
        self._tabs = Adw.ToggleGroup()
        self._tabs.add_css_class('round')
        self._tabs.add_css_class('page-switcher')
        for cid, label in (('apostles', _("Apostles'")),
                           ('nicene', _('Nicene')),
                           ('athanasian', _('Athanasian'))):
            self._tabs.add(Adw.Toggle(name=cid, label=label))
        self._tabs.set_active_name(self._creed_id)
        self._tabs.connect('notify::active-name', self._on_tab)
        self._text_en = Gtk.ToggleButton(label=_('English'))
        self._text_orig = Gtk.ToggleButton(label=_('Latin'))
        self._text_orig.set_group(self._text_en)
        for b in (self._text_en, self._text_orig):
            b.add_css_class('flat')
            b.add_css_class('family-pill')
        (self._text_orig if self._orig else self._text_en).set_active(True)
        self._text_orig.connect('toggled', self._on_text)
        text_box = Gtk.Box(spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)
        text_box.append(self._text_en)
        text_box.append(self._text_orig)
        bar = Gtk.CenterBox()
        bar.set_margin_start(14)
        bar.set_margin_end(14)
        bar.set_margin_top(8)
        bar.set_margin_bottom(4)
        bar.set_center_widget(self._tabs)
        root.append(bar)

        body = Gtk.Box()
        body.set_vexpand(True)
        root.append(body)

        # The page: header, the key, the lines with their drawing.
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_margin_start(20)
        page.set_margin_end(20)
        page.set_margin_top(12)
        page.set_margin_bottom(40)
        self._title = Gtk.Label(xalign=0, wrap=True)
        self._title.add_css_class('creeds-title')
        self._origin = Gtk.Label(xalign=0, wrap=True)
        self._origin.add_css_class('creeds-origin')
        self._facts = Gtk.Label(xalign=0, wrap=True)
        self._facts.add_css_class('creeds-facts')
        head = Gtk.Box(spacing=12)
        self._title.set_hexpand(True)
        head.append(self._title)
        head.append(text_box)
        page.append(head)
        page.append(self._origin)
        page.append(self._facts)
        page.append(self._key())
        hint = Gtk.Label(
            label=_('Pick a line, or walk with Up and Down, to follow its '
                    'threads to the verses it comes from. Pick a book on the '
                    'strip to light the lines that rest on it.'),
            xalign=0, wrap=True)
        hint.add_css_class('creeds-hint')
        page.append(hint)

        # Sideways strip, for a narrow pane.
        self._hstrip = Gtk.DrawingArea()
        self._hstrip.set_content_height(40)
        self._hstrip.set_draw_func(self._draw_hstrip)
        self._hstrip.set_visible(False)
        self._hstrip.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        page.append(self._hstrip)

        self._lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._lines.add_css_class('creeds-lines')
        self._lines.set_valign(Gtk.Align.START)
        # The lines take the width; the threads get a fixed run to the strip.
        self._lines.set_hexpand(True)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._on_key)
        self._lines.add_controller(keys)
        self._field = Gtk.Box()
        self._field.set_size_request(FIELD_W, -1)
        self._strip = Gtk.Box()
        self._strip.set_size_request(STRIP_W, -1)
        self._labels = Gtk.Fixed()
        self._labels.set_size_request(LABELS_W, -1)
        row = Gtk.Box()
        row.append(self._lines)
        row.append(self._field)
        row.append(self._strip)
        row.append(self._labels)
        self._overlay = Gtk.Overlay()
        self._overlay.set_child(row)
        self._area = Gtk.DrawingArea()
        self._area.set_can_target(False)
        self._area.set_draw_func(self._draw)
        self._area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self._area.connect('resize', lambda *_a: self._queue_layout())
        redraw_on_contrast(self._area)
        self._overlay.add_overlay(self._area)
        page.append(self._overlay)

        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Adw.Clamp(maximum_size=980, tightening_threshold=720)
        clamp.set_child(page)
        scroll.set_child(clamp)
        self._scroll = scroll
        body.append(scroll)

        # The detail, beside the lines on a wide pane.
        self._side = Gtk.ScrolledWindow()
        self._side.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._side.set_size_request(360, -1)
        # Set, so no child's expand (the author label's) can widen the panel.
        self._side.set_hexpand(False)
        self._side.add_css_class('creeds-side')
        body.append(self._side)

        esc = Gtk.EventControllerKey()
        esc.connect('key-pressed', self._on_escape)
        root.add_controller(esc)
        self.widget.set_child(root)
        self._apply_width()
        self._load()

    def _key(self) -> Gtk.Widget:
        """The key: the three threads, a heavier one, the two marks."""
        box = Adw.WrapBox(child_spacing=16, line_spacing=6)
        box.add_css_class('creeds-key')
        box.set_margin_top(10)
        box.set_margin_bottom(4)

        def swatch(draw):
            a = Gtk.DrawingArea()
            a.set_content_width(26)
            a.set_content_height(10)
            a.set_valign(Gtk.Align.CENTER)
            a.set_draw_func(lambda ar, cr, w, h: draw(cr, ar.get_color()))
            return a

        def line(width, alpha, dash=None):
            def draw(cr, ink):
                cr.set_source_rgba(ink.red, ink.green, ink.blue, alpha)
                cr.set_line_width(width)
                if dash:
                    cr.set_dash(dash)
                cr.move_to(1, 5)
                cr.line_to(25, 5)
                cr.stroke()
            return draw

        def heavier(cr, ink):
            cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.9)
            for x0, x1, w in ((1, 11, 1.0), (15, 25, 3.0)):
                cr.set_line_width(w)
                cr.move_to(x0, 5)
                cr.line_to(x1, 5)
                cr.stroke()

        items = ((line(2.0, 0.95), _('Same words')),
                 (line(1.2, 0.55), _('Same teaching')),
                 (line(1.4, 0.8, [4, 3]), _('Foretold')),
                 (heavier, _('Heavier: more witnesses')))
        for draw, text in items:
            item = Gtk.Box(spacing=6)
            item.append(swatch(draw))
            item.append(Gtk.Label(label=text))
            box.append(item)
        for wrap, sample, text in ((_coined, _('word'), _('Not a Bible word')),
                                   (_disputed, _('line'), _('Disputed'))):
            item = Gtk.Box(spacing=6)
            s = Gtk.Label(use_markup=True)
            s.set_markup(wrap(GLib.markup_escape_text(sample)))
            s.add_css_class('creeds-key-sample')
            item.append(s)
            item.append(Gtk.Label(label=text))
            box.append(item)
        return box

    # ── the creed shown ──────────────────────────────────────────────────

    def _load(self):
        c = creeds.creed(self._creed_id) or {}
        self._creed = c
        self._phrases = creeds.phrases(self._creed_id)
        self._byid = {p['id']: p for p in self._phrases}
        self._all = [(p, link) for p in self._phrases for link in p['links']]
        self._books: dict[str, list] = {}
        for p, link in self._all:
            self._books.setdefault(link['book'], []).append((p, link))
        self._verses: dict[str, dict] = {}
        for p, link in self._all:
            v = self._verses.setdefault(link['ref'], {'link': link, 'lines': set()})
            v['lines'].add(p['id'])
        self._sel = self._book = self._hot = None
        self._geo = None
        self._title.set_label(_(creeds.TITLES.get(self._creed_id, '')))
        self._origin.set_label(creeds.ORIGINS.get(self._creed_id, ''))
        self._text_orig.set_label(_('Greek') if c.get('orig') == 'grc'
                                  else _('Latin'))
        self._set_facts()
        self._render_lines()
        self._show_detail()

    def _set_facts(self):
        links = len(self._all)
        older = sum(1 for _p, link in self._all
                    if any(w != 'Word match' for w in link['witness']))
        books = len(self._books)
        disputed = sum(1 for p in self._phrases if p.get('disputed'))
        parts = [
            ngettext('{n} link to Scripture', '{n} links to Scripture',
                     links).format(n=links),
            ngettext('{n} book', '{n} books', books).format(n=books),
            ngettext('{n} cited by an older witness',
                     '{n} cited by an older witness', older).format(n=older),
        ]
        if disputed:
            parts.append(ngettext('{n} disputed line', '{n} disputed lines',
                                  disputed).format(n=disputed))
        self._facts.set_label('   '.join(parts))

    def _line_markup(self, p: dict) -> tuple[str, bool]:
        """The line's text as markup, with the words the Church chose and the
        disputed words marked; and whether the line is missing here."""
        if self._orig:
            text = p.get('orig', '')
            if not text:
                return (GLib.markup_escape_text(
                    _('[not in the Greek]') if self._creed.get('orig') == 'grc'
                    else _('[not in the Latin]')), True)
            coined = [w for w, _g in p.get('coined', [])]
            disp = p.get('disp_orig')
            stems = [_fold(w)[:6] for w in coined]
            words = []
            for w in text.split(' '):
                esc = GLib.markup_escape_text(w)
                core = w.strip(':;,.()')
                if core and any(_fold(core).startswith(s) for s in stems):
                    esc = esc.replace(GLib.markup_escape_text(core),
                                      _coined(GLib.markup_escape_text(core)), 1)
                words.append(esc)
            s = ' '.join(words)
        else:
            text = p['en'].strip()
            coined = (self._creed.get('coined_en') or {}).get(p['id'], [])
            disp = p.get('disp_en')
            s = GLib.markup_escape_text(text)
            for w in coined:
                s = _replace_words(s, GLib.markup_escape_text(w), _coined)
        if p.get('disputed'):
            if disp:
                s = s.replace(GLib.markup_escape_text(disp),
                              _disputed(GLib.markup_escape_text(disp)), 1)
            else:
                s = _disputed(s)
        return s, False

    def _render_lines(self):
        clear_children(self._lines)
        self._rows.clear()
        self._texts.clear()
        sections = dict((n, name) for n, name in (self._creed.get('sections') or []))
        greek = self._orig and self._creed.get('orig') == 'grc'
        self._lines.remove_css_class('creeds-greek')
        if greek:
            self._lines.add_css_class('creeds-greek')
        every = self._creed.get('id') == 'athanasian'
        for p in self._phrases:
            if p['first'] and p['art'] in sections:
                head = Gtk.Label(label=sections[p['art']], xalign=0)
                head.add_css_class('creeds-section')
                self._lines.append(head)
            markup, absent = self._line_markup(p)
            num = Gtk.Label(label=str(p['art']) if p['first'] else '',
                            xalign=0, yalign=0)
            num.add_css_class('creeds-num')
            num.set_size_request(26, -1)
            text = Gtk.Label(xalign=0, wrap=True, use_markup=True)
            text.set_markup(markup)
            text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            # Bounds the column's natural width; no hexpand here, which
            # would climb to the column and push the strip off the page.
            text.set_max_width_chars(44)
            text.add_css_class('creeds-text')
            # A widget's own provider styles that widget only, not its
            # children, so each line carries the reading size itself.
            text.get_style_context().add_provider(
                self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            if absent:
                text.add_css_class('creeds-absent')
            box = Gtk.Box(spacing=4)
            box.append(num)
            box.append(text)
            btn = Gtk.Button(child=box)
            btn.add_css_class('flat')
            btn.add_css_class('creeds-line')
            if p['first'] and not every:
                btn.add_css_class('creeds-article-start')
            label = (_('Verse {n}: {text}') if every
                     else _('Article {n}: {text}')).format(
                n=p['art'], text=p['en'].strip())
            if p.get('disputed'):
                label += ' ' + _('(disputed)')
            set_accessible_label(btn, label)
            btn.connect('clicked', lambda _b, pid=p['id']: self.select_line(pid))
            motion_ctl = Gtk.EventControllerMotion()
            motion_ctl.connect('enter', self._on_enter, p['id'])
            motion_ctl.connect('leave', self._on_leave, p['id'])
            btn.add_controller(motion_ctl)
            self._lines.append(btn)
            self._rows[p['id']] = btn
            self._texts[p['id']] = text
        self._queue_layout()


    # ── choosing ─────────────────────────────────────────────────────────

    def render(self):
        """Show the page (called when a pane turns to The Creeds)."""
        if not self._built:
            self._build()
        else:
            self._queue_layout()

    def apply_font_size(self, pt: int):
        """The creed's lines follow the pane's reading size; the rest is
        chrome and follows the desktop."""
        if not pt or pt == self._font_pt:
            return
        self._font_pt = pt
        self._font_provider.load_from_data(
            f'.creeds-text {{ font-size: {pt}pt; }}'.encode())
        self._queue_layout()

    def select_line(self, pid: str | None, ref: str | None = None):
        """Pick a line (or put it down, picked twice); `ref` picks one of its
        verses in the detail."""
        if pid is not None and pid == self._sel and ref is None:
            pid = None
        self._book = None
        self._hot = None
        self._sel = pid
        self._focus_ref = ref
        self._animate()
        self._show_detail()
        self._queue_layout()

    def select_book(self, name: str | None):
        self._sel = None
        self._hot = None
        self._book = None if name == self._book else name
        self._animate()
        self._show_detail()
        self._queue_layout()

    def show_line(self, creed_id: str, pid: str):
        """Open the page at a line (the reading view's mark asks for this)."""
        if not self._built:
            self._build()
        if creed_id != self._creed_id and creed_id in creeds.CREED_IDS:
            self._tabs.set_active_name(creed_id)   # → _on_tab loads it
        self.select_line(pid)
        btn = self._rows.get(pid)
        if btn is not None:
            GLib.idle_add(self._reveal, btn)

    def current_creed(self) -> str:
        return str(self._creed_id)

    def _reveal(self, btn):
        btn.grab_focus()
        return GLib.SOURCE_REMOVE

    def _on_tab(self, group, _pspec):
        cid = group.get_active_name()
        if not cid or cid == self._creed_id:
            return
        self._creed_id = cid
        settings.put('creeds_tab', cid)
        self._load()

    def _on_text(self, btn):
        self._orig = btn.get_active()
        settings.put('creeds_text', 'orig' if self._orig else 'en')
        self._render_lines()

    def _on_enter(self, _ctl, _x, _y, pid):
        if self._sel or self._book or self._narrow:
            return
        self._hot = pid
        self._queue_layout()

    def _on_leave(self, _ctl, pid):
        if self._hot == pid:
            self._hot = None
            self._queue_layout()

    def _on_key(self, _ctl, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval not in (Gdk.KEY_Up, Gdk.KEY_Down):
            return False
        focus = self.widget.get_root().get_focus() if self.widget.get_root() else None
        cur = self._sel
        for pid, btn in self._rows.items():
            if focus is not None and (focus is btn or focus.is_ancestor(btn)):
                cur = pid
        if cur is None:
            return False
        ids = [p['id'] for p in self._phrases]
        i = ids.index(cur) + (1 if keyval == Gdk.KEY_Down else -1)
        if not 0 <= i < len(ids):
            return True
        self.select_line(ids[i])
        self._rows[ids[i]].grab_focus()
        return True

    def _on_escape(self, _ctl, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval != Gdk.KEY_Escape or not (self._sel or self._book):
            return False
        pid = self._sel
        self.select_line(None) if self._sel else self.select_book(None)
        if pid in self._rows:
            self._rows[pid].grab_focus()
        return True

    def _on_breakpoint(self, bin_, _pspec):
        bp = bin_.get_current_breakpoint()
        self._wide = bp is None
        self._narrow = bp is self._bp_narrow
        if not self._built:
            return
        self._apply_width()
        self._show_detail()
        self._queue_layout()

    def _apply_width(self):
        self._hstrip.set_visible(self._narrow)
        for w in (self._field, self._strip, self._labels, self._area):
            w.set_visible(not self._narrow)
        self._side.set_visible(self._wide)

    # ── the detail ───────────────────────────────────────────────────────

    def _show_detail(self):
        """Put the detail where it belongs: beside the lines on a wide pane,
        under the chosen line on a narrow one."""
        old = getattr(self, '_inline', None)
        if old is not None and old.get_parent() is not None:
            self._lines.remove(old)
        self._inline = None
        body = self._detail()
        if self._wide:
            self._side.set_child(body)
            self._side.get_vadjustment().set_value(0)
            self._side.set_visible(True)
        else:
            self._side.set_child(None)
            self._side.set_visible(False)
            anchor = None
            if self._sel:
                anchor = self._rows.get(self._sel)
            elif self._book:
                first = self._books[self._book][0][0]['id']
                anchor = self._rows.get(first)
            if anchor is not None and body is not None:
                body.add_css_class('creeds-inline')
                self._lines.insert_child_after(body, anchor)
                self._inline = body
        if body is not None and self._focus_ref:
            ref, self._focus_ref = self._focus_ref, None
            chip = self._chips.get(ref)
            if chip is not None:
                GLib.idle_add(self._reveal, chip)

    def _detail(self) -> Gtk.Widget | None:
        if self._book:
            return self._book_detail(self._book)
        if not self._sel:
            if not self._wide:
                return None
            box = _vbox(10, 'creeds-detail')
            box.append(_label(_('Scripture for a line'), 'creeds-kicker'))
            box.append(_label(
                _('Pick a line of the creed. Its verses appear here: the ones '
                  'whose words the creed uses, the ones that teach what it '
                  'says, and the promises it sees fulfilled.'), 'creeds-ui'))
            box.append(_label(
                _('Keys: Up and Down walk the lines; Esc puts a line down.'),
                'creeds-hint'))
            return box
        p = self._byid[self._sel]
        box = _vbox(14, 'creeds-detail')
        self._chips = {}
        total = len(self._creed.get('articles', []))
        kicker = (_('Verse {n} of {total}')
                  if self._creed.get('id') == 'athanasian'
                  else _('Article {n} of {total}'))
        box.append(_label(kicker.format(n=p['art'], total=total),
                          'creeds-kicker'))
        box.append(_label(p['en'].strip(), 'creeds-phrase'))
        if p.get('orig'):
            o = _label(p['orig'], 'creeds-orig')
            if self._creed.get('orig') == 'grc':
                o.add_css_class('creeds-greek-text')
            box.append(o)
        if p.get('disputed'):
            flag = Gtk.Label(label=_('Disputed'))
            flag.add_css_class('creeds-flag')
            flag.set_halign(Gtk.Align.START)
            box.append(flag)
        if p.get('note'):
            box.append(_label(p['note'], 'creeds-body'))
        for word, gloss in p.get('coined', []):
            where = (_('The Church chose this word; the New Testament does not '
                       'use it.') if self._creed.get('orig') == 'grc' else
                     _('The Church chose this word; the Latin Bible does not '
                       'use it.'))
            c = Gtk.Label(xalign=0, wrap=True, use_markup=True)
            c.set_markup(f'<b>{GLib.markup_escape_text(word)}</b> '
                         f'“{GLib.markup_escape_text(gloss)}”. '
                         f'{GLib.markup_escape_text(where)}')
            c.add_css_class('creeds-coined-note')
            box.append(c)
        for kind in ('w', 't', 'f'):
            links = [link for link in p['links'] if link['kind'] == kind]
            if not links:
                continue
            box.append(_label(f"{_(creeds.KIND_NAMES[kind])} · {len(links)}",
                              'creeds-section-head'))
            for link in links:
                box.append(self._link_card(link, self._chips))
        art: dict = next((a for a in self._creed.get('articles', [])
                    if a['n'] == p['art']), {})
        for lo in art.get('left_out', []):
            left = _vbox(6, 'creeds-left-out')
            left.append(_label(_('Left out: {ref}').format(
                ref=ref_label({'ref': lo['ref'],
                               'book': lo['ref'].rsplit(' ', 1)[0]})),
                'creeds-section-head'))
            left.append(_label(lo['note'], 'creeds-body'))
            left.append(_label(lo['text'], 'creeds-verse'))
            box.append(left)
        return box

    def _link_card(self, link: dict, chips: dict) -> Gtk.Widget:
        card = _vbox(6, 'creeds-link')
        top = Gtk.Box(spacing=8)
        chip = Gtk.Button(label=ref_label(link))
        chip.add_css_class('flat')
        chip.add_css_class('creeds-ref')
        chip.set_tooltip_text(_('Open in the Bible'))
        chip.connect('clicked', lambda _b, lk=link: self._open(lk))
        chips[link['ref']] = chip
        top.append(chip)
        who = _label(link['author'], 'creeds-who')
        who.set_hexpand(True)
        who.set_xalign(1)
        top.append(who)
        card.append(top)
        card.append(_label(link['text'], 'creeds-verse'))
        if link.get('orig_words'):
            parts = []
            for word, hit, gloss in link['orig_words']:
                w = GLib.markup_escape_text(word)
                parts.append(f'<b><u>{w}</u></b>' if hit else w)
            o = Gtk.Label(xalign=0, wrap=True, use_markup=True)
            o.set_markup(' '.join(parts))
            o.add_css_class('creeds-orig-verse')
            if self._creed.get('orig') == 'grc':
                o.add_css_class('creeds-greek-text')
            card.append(o)
        if link.get('note'):
            card.append(_label(link['note'], 'creeds-link-note'))
        wits = Adw.WrapBox(child_spacing=6, line_spacing=6)
        for w in link['witness'] or [None]:
            if w is None:
                t = _label(_('No witness yet'), 'creeds-witness')
            elif w == 'Word match':
                t = _label(_('Word match · {n}').format(n=link.get('shared', 0)),
                           'creeds-witness')
                t.add_css_class('creeds-witness-measured')
                t.set_tooltip_text(_('Shares words with the creed in its '
                                     'original language'))
            else:
                t = _label(w, 'creeds-witness')
                t.set_tooltip_text(_WITNESS_FULL.get(w, w))
            wits.append(t)
        card.append(wits)
        return card

    def _book_detail(self, book: str) -> Gtk.Widget:
        items = self._books[book]
        by_line: dict[str, list] = {}
        for p, link in items:
            by_line.setdefault(p['id'], []).append(link)
        box = _vbox(12, 'creeds-detail')
        box.append(_label(_('Book'), 'creeds-kicker'))
        box.append(_label(book_label(book), 'creeds-phrase'))
        box.append(_label('  ·  '.join((
            ngettext('{n} link', '{n} links', len(items)).format(n=len(items)),
            ngettext('{n} line of the creed', '{n} lines of the creed',
                     len(by_line)).format(n=len(by_line)))), 'creeds-ui'))
        for pid, links in by_line.items():
            entry = _vbox(6, 'creeds-book-line')
            line = Gtk.Button()
            lab = _label(self._byid[pid]['en'].strip(), 'creeds-body')
            line.set_child(lab)
            line.add_css_class('flat')
            line.add_css_class('creeds-book-line-btn')
            line.connect('clicked', lambda _b, i=pid: self.select_line(i))
            entry.append(line)
            refs = Adw.WrapBox(child_spacing=6, line_spacing=6)
            for link in links:
                chip = Gtk.Button(label=ref_label(link))
                chip.add_css_class('flat')
                chip.add_css_class('creeds-ref')
                chip.set_tooltip_text(_(creeds.KIND_NAMES[link['kind']]))
                chip.connect('clicked', lambda _b, lk=link: self._open(lk))
                refs.append(chip)
            entry.append(refs)
            box.append(entry)
        return box

    def _open(self, link: dict):
        """Open the verse in the Bible beside the page, the channel Scripture
        in Stone's chips use."""
        pane = self._pane
        cb = getattr(pane, '_on_word_study_navigate', None)
        if cb is not None:
            cb(link['book'], link['ch'], link['v'])

    # ── drawing ──────────────────────────────────────────────────────────

    def _animate(self):
        if self._anim is not None:
            self._anim.skip()
            self._anim = None
        if not (self._sel or self._book) or not motion.should_animate():
            self._progress = 1.0
            return
        self._progress = 0.0
        target = Adw.CallbackAnimationTarget.new(self._on_progress)
        self._anim = Adw.TimedAnimation.new(self._area, 0.0, 1.0, THREAD_MS,
                                            target)
        self._anim.set_easing(motion.EASE_ENTER)
        self._anim.play()

    def _on_progress(self, value):
        self._progress = value
        self._area.queue_draw()

    def _queue_layout(self):
        if self._layout_pending or not self._built:
            return
        self._layout_pending = True
        GLib.idle_add(self._layout)

    def _layout(self):
        """Measure where everything is, then place the labels and repaint.
        Run idle: positions read inside an allocation are mid-settle."""
        self._layout_pending = False
        for pid, btn in self._rows.items():
            btn.remove_css_class('chosen')
            btn.remove_css_class('hot')
            btn.remove_css_class('lit')
        active = self._active()
        lit = {p['id'] for p, _l in active}
        for pid, btn in self._rows.items():
            if pid == self._sel:
                btn.add_css_class('chosen')
            elif pid == self._hot:
                btn.add_css_class('hot')
            elif self._book and pid in lit:
                btn.add_css_class('lit')
        self._lines.remove_css_class('creeds-active')
        if active:
            self._lines.add_css_class('creeds-active')
        if self._narrow:
            self._geo = None
            self._hstrip.queue_draw()
            return GLib.SOURCE_REMOVE
        g = self._measure()
        self._geo = g
        clear_children(self._labels)
        if g is None:
            return GLib.SOURCE_REMOVE
        if active:
            ports: dict[str, dict] = {}
            for p, link in active:
                e = ports.setdefault(link['ref'], {'y': g['y'](link), 'link': link,
                                                   'pid': p['id'], 'n': 0})
                e['n'] += 1
                if link['kind'] == 'w':
                    e['link'] = link
            items = list(ports.values())
            spread(items, LABEL_GAP, g['top'], g['bottom'])
            g['ports'] = {e['link']['ref']: e for e in items}
            for e in items:
                text = ref_label(e['link'])
                if e['n'] > 1:
                    text += f"  ×{e['n']}"
                btn = Gtk.Button(label=text)
                btn.add_css_class('flat')
                btn.add_css_class('creeds-ref')
                btn.add_css_class('creeds-port')
                set_accessible_label(btn, '{ref}, {kind}'.format(
                    ref=ref_label(e['link']),
                    kind=_(creeds.KIND_NAMES[e['link']['kind']])))
                btn.connect('clicked', self._on_port, e['pid'], e['link']['ref'])
                self._place(btn, e['py'])
        else:
            counts = [(name, items) for name, items in self._books.items()]
            most = max((len(i) for _n, i in counts), default=1)
            entries = [{'y': sum(g['y'](link) for _p, link in items) / len(items),
                        'name': name, 'n': len(items)} for name, items in counts]
            spread(entries, BOOK_GAP, g['top'], g['bottom'])
            g['books'] = entries
            for e in entries:
                btn = Gtk.Button()
                row = Gtk.Box(spacing=6)
                row.append(Gtk.Label(label=book_label(e['name'])))
                bar = Gtk.Box()
                bar.add_css_class('creeds-count-bar')
                bar.set_size_request(round(4 + 44 * e['n'] / most), 4)
                bar.set_valign(Gtk.Align.CENTER)
                row.append(bar)
                n = Gtk.Label(label=str(e['n']))
                n.add_css_class('creeds-count')
                row.append(n)
                btn.set_child(row)
                btn.add_css_class('flat')
                btn.add_css_class('creeds-book')
                set_accessible_label(btn, ngettext(
                    '{book}: {n} link', '{book}: {n} links', e['n']).format(
                    book=book_label(e['name']), n=e['n']))
                btn.connect('clicked', lambda _b, nm=e['name']: self.select_book(nm))
                self._place(btn, e['py'])
        self._area.queue_draw()
        return GLib.SOURCE_REMOVE

    def _place(self, btn: Gtk.Widget, y: float):
        self._labels.put(btn, 0, 0)
        _m, nat, _b1, _b2 = btn.measure(Gtk.Orientation.VERTICAL, -1)
        self._labels.move(btn, 0, max(0, y - nat / 2))

    def _on_port(self, _btn, pid, ref):
        self.select_line(pid, ref)

    def _active(self) -> list:
        if self._book:
            return self._books.get(self._book, [])
        pid = self._sel or self._hot
        if pid and pid in self._byid:
            p = self._byid[pid]
            return [(p, link) for link in p['links']]
        return []

    def _measure(self) -> dict | None:
        ov = self._overlay
        first = next(iter(self._rows.values()), None)
        if first is None or ov.get_width() <= 0:
            return None
        ok_l, lines = self._lines.compute_bounds(ov)
        ok_s, strip = self._strip.compute_bounds(ov)
        ok_f, lab = self._labels.compute_bounds(ov)
        ok_r, row0 = first.compute_bounds(ov)
        if not (ok_l and ok_s and ok_f and ok_r):
            return None
        top = row0.get_y() + 6
        bottom = lines.get_y() + lines.get_height() - 6
        half = (bottom - top) / 2

        def y(link):
            return (top + half + 5 + link['tp'] * (half - 5) if link['nt']
                    else top + link['tp'] * (half - 5))

        ys = {}
        for pid, text in self._texts.items():
            ok, b = text.compute_bounds(ov)
            if not ok:
                continue
            layout = text.get_layout()
            line = layout.get_line_readonly(0)
            h = line.get_pixel_extents()[1].height if line else b.get_height()
            ys[pid] = b.get_y() + min(h, b.get_height()) / 2
        return {'gx': lines.get_x() + lines.get_width() + 10,
                'sx': strip.get_x(), 'lx': lab.get_x(),
                'top': top, 'bottom': bottom, 'mid': top + half,
                'y': y, 'ys': ys}

    def _draw(self, area, cr, w, h):
        g = self._geo
        if g is None:
            return
        ink = area.get_color()
        hc = high_contrast()

        def src(alpha):
            cr.set_source_rgba(ink.red, ink.green, ink.blue, lift(alpha, hc))

        active = self._active()
        lines_on = {p['id'] for p, _l in active}
        refs_on = {link['ref'] for _p, link in active}
        sx = g['sx']
        # The strip: every book a band, the Testaments parted by a rule.
        for i, (b, _off, _n) in enumerate(creeds.data().get('books', [])):
            a, z, nt = creeds.data()['bookspan'][b]
            y1 = g['y']({'tp': a, 'nt': nt})
            y2 = g['y']({'tp': z, 'nt': nt})
            src(0.13 if i % 2 else 0.07)
            cr.rectangle(sx, y1, STRIP_W, max(0.6, y2 - y1 - 0.4))
            cr.fill()
        src(0.22)
        cr.set_line_width(1)
        cr.move_to(sx - 5, g['mid'])
        cr.line_to(sx + STRIP_W + 5, g['mid'])
        cr.stroke()
        # Every line ends in a tick.
        for pid, y in g['ys'].items():
            if pid not in self._byid:
                continue      # measured for the creed shown before
            on = pid in lines_on
            disputed = self._byid[pid].get('disputed')
            src((0.9 if on else 0.18) if active else (0.38 if not disputed else 0.5))
            cr.set_line_width(2 if on else 1.4)
            cr.move_to(g['gx'] - 6, y)
            cr.line_to(g['gx'] + 4, y)
            cr.stroke()
        # One dot per verse, larger when more lines use it.
        for ref, v in self._verses.items():
            if active and ref in refs_on:
                continue
            src(0.16 if active else 0.55)
            r = 1.7 + 0.9 * (len(v['lines']) - 1)
            cr.arc(sx + STRIP_W / 2, g['y'](v['link']), r, 0, 2 * math.pi)
            cr.fill()
        if active:
            ports = g.get('ports', {})
            for e in ports.values():
                yt = e['y']
                src(0.25)
                cr.set_line_width(1)
                cr.move_to(sx - 2, e['py'])
                cr.line_to(sx + STRIP_W / 2, yt)
                cr.line_to(sx + STRIP_W + 2, e['py'])
                cr.line_to(g['lx'] - 4, e['py'])
                cr.stroke()
            prog = self._progress
            for p, link in active:
                e = ports.get(link['ref'])
                y1 = g['ys'].get(p['id'])
                if e is None or y1 is None:
                    continue
                x1, x2, y2 = g['gx'] + 4, sx - 2, e['py']
                dx = max(24.0, (x2 - x1) * 0.5)
                n = len([x for x in link['witness'] if x])
                width = {'w': 1.5, 't': 1.0, 'f': 1.2}[link['kind']] + 0.6 * n
                alpha = {'w': 0.95, 't': 0.6, 'f': 0.85}[link['kind']]
                pts = ((x1, y1), (x1 + dx, y1), (x2 - dx, y2), (x2, y2))
                cr.set_line_width(width)
                if link['kind'] == 'f':
                    src(alpha * prog)
                    cr.set_dash([5, 3])
                else:
                    src(alpha)
                    if prog < 1:
                        length = _bezier_length(*pts)
                        cr.set_dash([length * prog, length + 1])
                cr.move_to(*pts[0])
                cr.curve_to(*pts[1], *pts[2], *pts[3])
                cr.stroke()
                cr.set_dash([])
                src(1.0)
                cr.arc(sx + STRIP_W / 2, e['y'], 3.4, 0, 2 * math.pi)
                cr.fill()
        elif g.get('books'):
            for e in g['books']:
                if abs(e['py'] - e['y']) > 2:
                    src(0.12)
                    cr.set_line_width(1)
                    cr.move_to(sx + STRIP_W + 1, e['y'])
                    cr.line_to(g['lx'] - 4, e['py'])
                    cr.stroke()

    def _draw_hstrip(self, area, cr, w, h):
        """The strip turned sideways, for a narrow pane: dots only."""
        if not self._built:
            return
        ink = area.get_color()
        hc = high_contrast()
        refs_on = {link['ref'] for _p, link in self._active()}
        active = bool(refs_on)

        def x(tp, nt):
            return (w / 2 + 3 + tp * (w / 2 - 3)) if nt else tp * (w / 2 - 3)

        for i, (b, _o, _n) in enumerate(creeds.data().get('books', [])):
            a, z, nt = creeds.data()['bookspan'][b]
            cr.set_source_rgba(ink.red, ink.green, ink.blue,
                               lift(0.13 if i % 2 else 0.07, hc))
            cr.rectangle(x(a, nt), 8, max(0.5, x(z, nt) - x(a, nt) - 0.3), 10)
            cr.fill()
        for ref, v in self._verses.items():
            on = ref in refs_on
            cr.set_source_rgba(ink.red, ink.green, ink.blue,
                               lift((1.0 if on else 0.15) if active else 0.55, hc))
            cr.arc(x(v['link']['tp'], v['link']['nt']), 13, 3.6 if on else 1.8,
                   0, 2 * math.pi)
            cr.fill()


# ── helpers ──────────────────────────────────────────────────────────────

_WITNESS_FULL = {
    'Cyril': 'Cyril of Jerusalem, Catechetical Lectures, c. 350',
    'Philaret': 'Philaret of Moscow, Longer Catechism, 1839',
    'Orthodox Creed': 'An Orthodox Creed, General Baptists, 1679',
    'Larger Catechism': 'Westminster Larger Catechism, 1648',
    'Westminster': 'Westminster Confession of Faith, 1647',
}


def _fold(word: str) -> str:
    w = word.lower().replace('æ', 'ae').replace('œ', 'oe').replace('j', 'i')
    w = w.replace('v', 'u')
    return ''.join(c for c in w if c.isalpha())


#: The marks' colour: a mid grey that reads on the light papers and the dark,
#: never the accent (these are not links) and never clay (the two-accent law).
_MARK = '#8a8780'


def _coined(markup: str) -> str:
    return f'<span underline="single" underline_color="{_MARK}">{markup}</span>'


def _disputed(markup: str) -> str:
    return f'<span underline="error" underline_color="{_MARK}">{markup}</span>'


def _replace_words(markup: str, word: str, wrap) -> str:
    """Wrap every whole-word `word` in `markup`."""
    import re
    return re.sub(r'\b' + re.escape(word) + r'\b', lambda m: wrap(m.group(0)),
                  markup)


def _vbox(spacing: int, css: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.add_css_class(css)
    return box


def _label(text: str, css: str) -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=0, wrap=True)
    lab.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lab.add_css_class(css)
    return lab
