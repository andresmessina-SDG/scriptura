"""family_card.py — the Card: everything about one English Bible.

A side sheet from the right, like Search. Sans header block, then the
sections top to bottom: where it lands on the Line, where it came from, what
it translates, notes, sources, and the actions. Every Bible it names is a
link to that Bible's Card, with Back to return.

The headings and sentences are translated; the facts themselves (names,
makers, notes, sources) stay English for now (decided 2026-09-24).

`paint_track` is the Line's track and marks, shared with the compare
popover's small tick so the two cannot drift apart.
"""

import math

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk, GLib

import bible_family
from a11y import set_accessible_label
from i18n import _, N_, ngettext


def paint_track(cr, w, h, spot, ink, pad=4.0, r=3.0):
    """The Line's track across `w`, with `spot`'s mark on it, in `ink`
    (anything with red/green/blue). A filled dot on a soft range where
    published charts place a Bible, a ring where Scriptura measured it, a
    bracket over the zone where only its makers' description is known. A
    Bible past the free end is pinned there."""
    cy = h / 2

    def x(v):
        return pad + min(max(v, 0.0), 1.0) * (w - 2 * pad)

    def faint(alpha=0.3):
        cr.set_source_rgba(ink.red, ink.green, ink.blue, alpha)

    # A ring must read as hollow: nothing of the track crosses its inside.
    hole = ((x(spot.value) - r - 1, x(spot.value) + r + 1)
            if spot.kind == 'measured' else None)
    faint()
    cr.set_line_width(1.0)
    segments = [(pad, w - pad)] if hole is None else \
        [(pad, hole[0]), (hole[1], w - pad)]
    for a, b in segments:
        if b > a:
            cr.move_to(a, cy)
            cr.line_to(b, cy)
    tick = r - 0.5
    for bound, _name in bible_family.ZONES[:-1]:
        tx = round(x(bound)) + 0.5
        if hole is None or not hole[0] <= tx <= hole[1]:
            cr.move_to(tx, cy - tick)
            cr.line_to(tx, cy + tick)
    cr.stroke()

    if spot.kind == 'band':
        faint(0.25)
        cr.set_line_width(r * 5 / 3)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(x(spot.low), cy)
        cr.line_to(x(spot.high), cy)
        cr.stroke()
        cr.set_source_rgba(ink.red, ink.green, ink.blue, 1.0)
        cr.arc(x(spot.value), cy, r, 0, 2 * math.pi)
        cr.fill()
    elif spot.kind == 'measured':
        cr.set_source_rgba(ink.red, ink.green, ink.blue, 1.0)
        cr.set_line_width(max(1.4, r * 0.45))
        cr.arc(x(spot.value), cy, r - 0.3, 0, 2 * math.pi)
        cr.stroke()
    else:
        cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.8)
        cr.set_line_width(1.4)
        lo, hi = x(spot.low) + 2, x(spot.high) - 2
        cr.move_to(lo, cy - r - 0.5)
        cr.line_to(lo, cy - 1)
        cr.line_to(hi, cy - 1)
        cr.line_to(hi, cy - r - 0.5)
        cr.stroke()


def short_name(record):
    """What a Bible is called in running text: its name when that is short
    ("The Message"), else its abbreviation ("ESV"), else its name without
    the parenthesis."""
    name = record['name'].split(' (')[0]
    abbr = record.get('abbr', '')
    if len(name) <= 16 or not abbr or len(abbr) > 7:
        return name
    return abbr


_CLASS_WORDS = {
    'formal': N_('word for word'),
    'expanded': N_('an expanded translation'),
    'intermediate': N_('between word for word and thought for thought'),
    'functional': N_('thought for thought'),
    'paraphrase': N_('a paraphrase'),
}


def place_sentences(record):
    """What the Card says about a Bible's place, as a list of sentences."""
    spot = bible_family.place_of(record)
    sp = record.get('spectrum', {})
    if spot is None:
        return [_('It has no place on the Line.')]
    zone = bible_family.zone_label(spot.value)
    if spot.kind == 'band':
        n = sp.get('n', 1)
        out = [ngettext('{n} published chart places it in “{zone}”.',
                        '{n} published charts place it in “{zone}”.',
                        n).format(n=n, zone=zone)]
        if 'measured' in sp:
            out.append(_('Scriptura measured it too; the charts’ place is '
                         'the one shown.'))
        return out
    if spot.kind == 'measured':
        out = [_('Measured in Scriptura: “{zone}”.').format(zone=zone)]
        if spot.value > 1.0:
            out.append(_('It measured freer still than The Message, so it '
                         'sits at the free end.'))
        if record.get('archaic'):
            out.append(_('Its older English reads a little freer on the '
                         'measure than it is; its place allows for that.'))
        elif sp.get('measured_note'):
            note = sp['measured_note']
            out.append(note[0].upper() + note[1:] + '.')
        return out
    return [_('Its makers describe it as {kind}; no chart has placed it.')
            .format(kind=_(_CLASS_WORDS[sp['class']]))]


def _escaped(template):
    """A translated sentence made safe to put into markup; its {fields}
    survive, since braces are not markup."""
    return GLib.markup_escape_text(template)


def _markup_link(target, text):
    return '<a href="{}">{}</a>'.format(
        GLib.markup_escape_text(target), GLib.markup_escape_text(text))


class FamilyCard(Gtk.Box):
    """The Card as a side sheet. `show(node_id, installed, reading)` opens it
    on one Bible; links inside it move to other Bibles, Back returns."""

    def __init__(self, on_close, on_open, on_install, on_compare):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('search-panel')
        self._on_close = on_close
        self._on_open = on_open
        self._on_install = on_install
        self._on_compare = on_compare
        self._history: list[str] = []
        self._installed: list[str] = []
        self._reading = ''
        self._open_here = True
        self._can_compare = True

        header = Gtk.Box(spacing=6)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(10)
        header.set_margin_bottom(4)
        self._back = Gtk.Button(icon_name='scriptura-go-previous-symbolic')
        self._back.add_css_class('flat')
        self._back.set_tooltip_text(_('Back'))
        set_accessible_label(self._back, _('Back'))
        self._back.connect('clicked', lambda _b: self._go_back())
        header.append(self._back)
        title = Gtk.Label(label=_('About this translation'),
                          xalign=0, hexpand=True)
        title.set_margin_start(6)
        title.add_css_class('title-4')
        header.append(title)
        close_btn = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.set_tooltip_text(_('Close (Esc)'))
        set_accessible_label(close_btn, _('Close'))
        close_btn.connect('clicked', lambda _b: self._on_close())
        header.append(close_btn)
        self._close_btn = close_btn
        self.append(header)

        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER,
                                Gtk.PolicyType.AUTOMATIC)
        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._body.set_margin_start(18)
        self._body.set_margin_end(18)
        self._body.set_margin_bottom(20)
        self._scroll.set_child(self._body)
        self.append(self._scroll)

    # ── public ───────────────────────────────────────────────────────────

    def show(self, node_id, installed, reading, open_here=True,
             can_compare=True):
        """Open on one Bible. `installed` is the app's module keys, and
        `reading` the Bible being read. `open_here` says whether Open goes to
        this pane or the other; `can_compare` whether there is a Bible pane
        to compare a verse from."""
        self._installed = list(installed)
        self._reading = reading
        self._open_here = open_here
        self._can_compare = can_compare
        self._history = []
        self._render(node_id)

    def focus_start(self):
        self._close_btn.grab_focus()

    @property
    def node_id(self):
        return self._history[-1] if self._history else None

    # ── navigation ───────────────────────────────────────────────────────

    def _go_to(self, node_id):
        if bible_family.node(node_id) is not None:
            self._render(node_id)
            self._back.grab_focus()

    def _go_back(self):
        if len(self._history) > 1:
            self._history.pop()
            self._render(self._history.pop())
            (self._back if self._back.get_visible()
             else self._close_btn).grab_focus()

    def _on_link(self, _label, uri):
        if uri.startswith('card:'):
            # After the click has finished: the Card is rebuilt, and the
            # label that was clicked, and held the keyboard, goes with it.
            node_id = uri[len('card:'):]
            GLib.idle_add(lambda: self._go_to(node_id) or GLib.SOURCE_REMOVE)
            return True
        return False        # a web source: GTK opens it in the browser

    # ── building ─────────────────────────────────────────────────────────

    def _render(self, node_id):
        record = bible_family.node(node_id)
        self._history.append(node_id)
        self._back.set_visible(len(self._history) > 1)
        child = self._body.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._body.remove(child)
            child = nxt
        self._build_header(record)
        self._build_place(record)
        self._build_descent(record)
        self._build_texts(record)
        self._build_notes(record)
        self._build_sources(record)
        self._build_actions(record)
        self._scroll.get_vadjustment().set_value(0)

    def _label(self, text, *classes, markup=False):
        lbl = Gtk.Label(xalign=0, wrap=True)
        lbl.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        if markup:
            lbl.set_markup(text)
            lbl.connect('activate-link', self._on_link)
        else:
            lbl.set_label(text)
        for c in classes:
            lbl.add_css_class(c)
        self._body.append(lbl)
        return lbl

    def _section(self, title):
        head = self._label(title, 'family-card-section')
        head.set_margin_top(20)
        head.set_margin_bottom(6)

    def _build_header(self, record):
        kicker = ' · '.join(
            _(v) for v in (bible_family.TRADITIONS.get(record.get('tradition')),
                           bible_family.SCOPES.get(record.get('scope')))
            if v)
        if kicker:
            self._label(kicker, 'family-card-kicker').set_margin_top(8)
        self._label(record['name'], 'family-card-title')
        meta = ' · '.join(str(x) for x in (
            record.get('year_label', record['year']), record.get('by')) if x)
        self._label(meta, 'family-card-meta')
        if bible_family.node_for_module(self._reading) is record:
            self._label(_('You are reading this'),
                        'family-card-reading').set_margin_top(4)

    def _build_place(self, record):
        self._section(_('Where it lands'))
        spot = bible_family.place_of(record)
        if spot is not None:
            area = Gtk.DrawingArea(hexpand=True)
            area.set_content_height(22)
            area.set_draw_func(lambda a, cr, w, h: paint_track(
                cr, w, h, spot, a.get_color(), pad=7.0, r=5.0))
            self._body.append(area)
            ends = Gtk.Box()
            ends.add_css_class('family-card-axis')
            ends.append(Gtk.Label(label=_('Word for word'), xalign=0,
                                  hexpand=True))
            ends.append(Gtk.Label(label=_('Free'), xalign=1))
            self._body.append(ends)
        for sentence in place_sentences(record):
            self._label(sentence).set_margin_top(6)
        sp = record.get('spectrum', {})
        reason = sp.get('none') or sp.get('measured_skip')
        if spot is None and reason:
            self._label(reason[0].upper() + reason[1:] + '.', 'dim-label')
        below, above = bible_family.neighbours(record['id'])
        near = [_markup_link('card:' + n['id'], short_name(n))
                for n in (below, above) if n is not None]
        if len(near) == 2:
            self._label(_escaped(_('Near {a} and {b} on the Line.')).format(
                a=near[0], b=near[1]), 'family-card-links',
                markup=True).set_margin_top(4)
        elif near:
            self._label(_escaped(_('Near {a} on the Line.')).format(
                a=near[0]), 'family-card-links',
                markup=True).set_margin_top(4)
        if sp.get('self'):
            quote = sp['self'].strip('"“”')
            self._label('“' + quote + '”', 'family-card-body').set_margin_top(10)
            if sp.get('self_src'):
                self._label('— ' + sp['self_src'], 'family-card-meta')

    def _build_descent(self, record):
        self._section(_('Where it came from'))
        path = bible_family.descent(record['id'])
        if len(path) == 1:
            self._label(_('A fresh translation, not a revision of an '
                          'earlier English Bible.'))
        else:
            self._label(_('Newest first; each is a revision of the next, '
                          'unless it says otherwise.'), 'family-card-meta')
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            column.add_css_class('family-card-path')
            column.set_margin_top(6)
            for i, (rec, _rel) in enumerate(path):
                text = GLib.markup_escape_text(
                    '{} · {}'.format(rec['name'], rec['year']))
                if i:
                    text = _markup_link('card:' + rec['id'], '{} · {}'.format(
                        rec['name'], rec['year']))
                # The relation belongs to the row above: it says how that
                # Bible came from this one.
                if i + 1 < len(path) and path[i + 1][1] == 'para':
                    text += '  <span alpha="60%">{}</span>'.format(
                        GLib.markup_escape_text(_('reworded from the next')))
                lbl = Gtk.Label(xalign=0, wrap=True)
                lbl.set_markup(text)
                lbl.connect('activate-link', self._on_link)
                lbl.add_css_class('family-card-path-here' if i == 0
                                  else 'family-card-links')
                column.append(lbl)
            self._body.append(column)
        for heading, recs in ((_('Also drew on'),
                               bible_family.drew_on(record['id'])),
                              (_('Later Bibles from it'),
                               bible_family.descendants(record['id']))):
            if recs:
                links = ', '.join(_markup_link('card:' + r['id'], short_name(r))
                                  for r in recs)
                self._label('{}: {}'.format(
                    GLib.markup_escape_text(heading), links),
                    'family-card-links', markup=True).set_margin_top(10)

    def _build_texts(self, record):
        rows = [(label, record[key]) for label, key in
                ((_('Old Testament'), 'base_ot'),
                 (_('New Testament'), 'base_nt')) if record.get(key)]
        if not rows:
            return
        self._section(_('What it translates'))
        for label, code in rows:
            self._label(_('{part}: {text}').format(
                part=label, text=_(bible_family.BASE_TEXTS[code])))
        self._label(_('This is what explains a verse one Bible has and '
                      'another does not.'), 'dim-label').set_margin_top(4)

    def _build_notes(self, record):
        if not (record.get('note') or record.get('editions')
                or record.get('dispute')):
            return
        self._section(_('Notes'))
        if record.get('note'):
            self._label(record['note'], 'family-card-body')
        if record.get('editions'):
            self._label(_('Editions: {list}').format(
                list=', '.join(record['editions'])),
                'family-card-meta').set_margin_top(6)
        if record.get('dispute'):
            self._label(_('Sources differ: {what}').format(
                what=record['dispute']), 'family-card-meta').set_margin_top(6)

    def _build_sources(self, record):
        self._section(_('Sources'))
        for key in record.get('src', []):
            label, url = bible_family.source(key)
            if url:
                self._label(_markup_link(url, label),
                            'family-card-source', markup=True)
            else:
                self._label(label, 'family-card-meta')
        self._label(_(bible_family.CONFIDENCE[record['check']]),
                    'family-card-meta').set_margin_top(6)

    def _build_actions(self, record):
        have = bible_family.installed_module(record['id'], self._installed)
        # Wraps: in Russian the two buttons are wider than the sheet, and a
        # row that cannot wrap pushed the sheet out past its right margin.
        row = Adw.WrapBox(child_spacing=8, line_spacing=8)
        row.set_margin_top(22)
        if have is not None:
            if have != self._reading:
                open_btn = Gtk.Button(label=_('Open in this pane')
                                      if self._open_here
                                      else _('Open in the other pane'))
                open_btn.add_css_class('suggested-action')
                open_btn.add_css_class('pill')
                open_btn.connect('clicked', lambda _b: self._on_open(have))
                row.append(open_btn)
            if self._can_compare:
                cmp_btn = Gtk.Button(label=_('Compare this verse'))
                cmp_btn.add_css_class('pill')
                cmp_btn.connect('clicked', lambda _b: self._on_compare())
                row.append(cmp_btn)
        elif record.get('installable'):
            query = record['installable'][0]
            inst = Gtk.Button(label=_('Install'))
            inst.add_css_class('pill')
            inst.connect('clicked', lambda _b: self._on_install(query))
            row.append(inst)
        if row.get_first_child() is not None:
            self._body.append(row)
