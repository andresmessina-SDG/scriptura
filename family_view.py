"""family_view.py — the Family: the Bibles people read, and where they
came from, drawn down the page in time.

The lines, axis, lanes and margin notes are painted; every Bible is a real
button placed over them, so each is focusable, has a sentence for screen
readers, and opens its Card. Arrow keys walk the family: Up to the parent,
Down to the eldest child, Left and Right to the nearest Bible either side.
Hovering or focusing a Bible lights its whole line and dims the rest.

The drawing keeps its size and scrolls inside its frame in a narrow pane,
rather than shrinking its type (the genealogy lesson). The outline is the
same family as an indented list, for readers who want it without a drawing.
"""

import math

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Adw, Gdk, Gtk, Pango, PangoCairo

import bible_family
import family_layout as fl
from family_card import place_sentences, short_name
from i18n import _

DOT = 7.0               # the mark's radius, in the drawing's units
NODE_H = 24


def _sentence(record, reading, installed):
    """What a screen reader says for a Bible in the Family."""
    line = bible_family.descent(record['id'])
    if len(line) > 1:
        parent, rel = line[1]
        came = (_('Reworded from {name}.') if rel == 'para'
                else _('Revision of {name}.')).format(name=parent['name'])
    else:
        came = _('Not a revision of an earlier English Bible.')
    root = record['id'] in bible_family.family_data().get('root', {})
    where = (_('Before the Line: its spelling cannot be measured.') if root
             else ' '.join(place_sentences(record)))
    have = (_('You are reading this.') if reading
            else _('Installed.') if installed else '')
    return ' '.join(p for p in (
        '{}, {}.'.format(record['name'], record.get('year_label',
                                                    record['year'])),
        came, where, have) if p)


class _Node(Gtk.Button):
    """One Bible: its mark, short name and year, placed on the drawing."""

    def __init__(self, view, record, x, y):
        super().__init__()
        self.record = record
        self.x, self.y = x, y
        self.add_css_class('flat')
        self.add_css_class('family-node')
        self._view = view
        root = record['id'] in bible_family.family_data().get('root', {})
        self.spot = None if root else bible_family.place_of(record)
        self.reading = False

        self._dot = Gtk.DrawingArea()
        side = int(DOT * 2 + 8)
        self._dot.set_content_width(side)
        self._dot.set_content_height(side)
        self._dot.set_draw_func(self._draw_dot)
        self._name = Gtk.Label(label=short_name(record))
        self._name.add_css_class('family-node-name')
        self._year = Gtk.Label(label=str(record['year']))
        self._year.add_css_class('family-node-year')
        self._box = Gtk.Box(spacing=4)
        self.set_child(self._box)
        self.set_left(fl.label_left(x, root))

        self.connect('clicked', lambda _b: view._open_card(self))
        motion = Gtk.EventControllerMotion()
        motion.connect('enter', lambda *_a: view._light(self.record['id']))
        motion.connect('leave', lambda *_a: view._light(None))
        self.add_controller(motion)
        focus = Gtk.EventControllerFocus()
        focus.connect('enter', lambda *_a: view._light(self.record['id']))
        focus.connect('leave', lambda *_a: view._light(None))
        self.add_controller(focus)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', lambda _c, kv, _kc, _st:
                     view._walk(self, kv))
        self.add_controller(keys)

    def set_left(self, left):
        """Run the label left of the mark (True) or right of it."""
        self.left = left
        for w in (self._dot, self._name, self._year):
            if w.get_parent() is not None:
                self._box.remove(w)
        for w in ((self._year, self._name, self._dot) if left
                  else (self._dot, self._name, self._year)):
            self._box.append(w)

    def box(self):
        """The node's rectangle on the drawing: (x0, y0, x1, y1)."""
        nat = self.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        side = DOT * 2 + 8
        pad = 4     # the flat button's own padding, left and right
        x0 = (self.x - nat + pad + side / 2) if self.left \
            else (self.x - pad - side / 2)
        return (x0, self.y - NODE_H / 2, x0 + nat, self.y + NODE_H / 2)

    def place(self, fixed):
        """Put the node so its mark's centre sits on (x, y)."""
        x0, y0, _x1, _y1 = self.box()
        fixed.put(self, x0, y0)

    def refresh(self, reading, installed):
        self.reading = reading
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_sentence(self.record, reading, installed)])
        self._dot.queue_draw()

    def _draw_dot(self, area, cr, w, h):
        ink = area.get_color()
        cx, cy, r = w / 2, h / 2, DOT - 1.5
        if self.reading:
            accent = Adw.StyleManager.get_default().get_accent_color_rgba()
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
            cr.set_line_width(2.0)
            cr.arc(cx, cy, r + 3.5, 0, 2 * math.pi)
            cr.stroke()
        kind = self.spot.kind if self.spot is not None else None
        cr.set_source_rgba(ink.red, ink.green, ink.blue, 1.0)
        if kind == 'band':
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.fill()
            return
        cr.set_line_width(2.0 if kind == 'measured' else 1.4)
        if kind == 'class':
            cr.set_dash([2.0, 2.0])
        cr.arc(cx, cy, r - 0.5, 0, 2 * math.pi)
        cr.stroke()


def _overlap(a, b, slack=2):
    return (a[0] < b[2] - slack and b[0] < a[2] - slack
            and a[1] < b[3] - slack and b[1] < a[3] - slack)


def _clashes(node, others):
    return [o for o in others if o is not node
            and _overlap(node.box(), o.box())]


def _settle(node, placed):
    """Find `node` a side for its label clear of those already placed:
    its own side, else the other; failing both, flip the neighbour it
    hits (HCSB, a year and a lane from TNIV, took both of TNIV's sides)."""
    if not _clashes(node, placed):
        return
    node.set_left(not node.left)
    if not _clashes(node, placed):
        return
    node.set_left(not node.left)
    for other in _clashes(node, placed):
        other.set_left(not other.left)
        if _clashes(other, placed + [node]):
            other.set_left(not other.left)


class FamilyView:
    """The drawing and its nodes, in a frame that scrolls both ways."""

    def __init__(self, on_open_card):
        self._on_open_card = on_open_card
        self._nodes: dict[str, _Node] = {}
        self._lit: set | None = None
        self._last = None
        self._pos = fl.positions()
        self._edges = fl.edges()
        self._lanes = fl.lanes()
        self._notes = fl.notes()

        # The painting is the lines, axis and lane names: presentation, so a
        # screen reader walks the Bibles and notes instead.
        self._area = Gtk.DrawingArea(
            accessible_role=Gtk.AccessibleRole.PRESENTATION)
        # A size request, not just a content size: the content size is only
        # natural, and the frame squeezed the drawing to its own size.
        self._area.set_size_request(fl.WIDTH, int(fl.HEIGHT))
        self._area.set_draw_func(self._draw)
        self._fixed = Gtk.Fixed()
        overlay = Gtk.Overlay(halign=Gtk.Align.CENTER)
        overlay.set_child(self._area)
        overlay.add_overlay(self._fixed)
        self._scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._scroll.set_child(overlay)
        self.widget = self._scroll

        for nid in bible_family.family_members():
            x, y = self._pos[nid]
            node = _Node(self, bible_family.node(nid), x, y)
            self._nodes[nid] = node
        # Tab order runs down the page in time, then across. A label whose
        # side is taken by a neighbour runs the other way.
        # The margin notes, in the reading serif, as real labels so a screen
        # reader reaches them. The early ones fall close together where the
        # axis is compressed, so each starts below the one above.
        self._note_spots = []
        bottom = 0.0
        for note in self._notes:
            label = Gtk.Label(label=note.text, xalign=0, wrap=True)
            label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
            label.add_css_class('family-note')
            label.set_size_request(fl.NOTE_WIDTH, -1)
            top = max(note.y - 9, bottom + 10)
            self._fixed.put(label, fl.NOTE_LEFT, top)
            height = label.measure(Gtk.Orientation.VERTICAL,
                                   fl.NOTE_WIDTH)[1]
            self._note_spots.append((note.y, top))
            bottom = top + height

        order = sorted(self._nodes, key=lambda i: (self._pos[i][1],
                                                   self._pos[i][0]))
        placed: list[_Node] = []
        for nid in order:
            node = self._nodes[nid]
            _settle(node, placed)
            placed.append(node)
        for nid in order:
            self._nodes[nid].place(self._fixed)

    # ── the pane's calls ─────────────────────────────────────────────────

    def refresh(self, installed, reading):
        reading_node = (bible_family.node_for_module(reading)
                        if reading else None)
        target = None
        for nid, node in self._nodes.items():
            is_reading = reading_node is not None and \
                reading_node['id'] == nid
            node.refresh(is_reading,
                         bible_family.installed_module(nid, installed))
            if is_reading:
                target = node
        return target

    def scroll_to(self, node):
        vadj = self._scroll.get_vadjustment()
        hadj = self._scroll.get_hadjustment()
        vadj.set_value(max(0.0, node.y - vadj.get_page_size() / 3))
        hadj.set_value(max(0.0, node.x - hadj.get_page_size() / 2))

    def focus_last(self):
        if self._last is not None and self._last.get_mapped():
            self._last.grab_focus()

    # ── interaction ──────────────────────────────────────────────────────

    def _open_card(self, node):
        self._last = node
        self._on_open_card(node.record['id'])

    def _lineage(self, nid):
        """This Bible, everything it came from and everything from it."""
        seen = {nid}
        for direction in ('up', 'down'):
            stack = [nid]
            while stack:
                here = stack.pop()
                for e in self._edges:
                    nxt = (e.parent if direction == 'up' and e.child == here
                           else e.child if direction == 'down'
                           and e.parent == here else None)
                    if nxt is not None and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        return seen

    def _light(self, nid):
        self._lit = self._lineage(nid) if nid else None
        for k, node in self._nodes.items():
            if self._lit is not None and k not in self._lit:
                node.add_css_class('dim')
            else:
                node.remove_css_class('dim')
        self._area.queue_draw()

    def _walk(self, node, keyval):
        """Arrow keys move along the family; returns True when handled."""
        nid = node.record['id']
        target = None
        if keyval == Gdk.KEY_Up:
            ups = [e for e in self._edges if e.child == nid]
            ups.sort(key=lambda e: e.kind != 'rev')
            target = ups[0].parent if ups else None
        elif keyval == Gdk.KEY_Down:
            downs = [e.child for e in self._edges if e.parent == nid]
            downs.sort(key=lambda c: bible_family.node(c)['year'])
            target = downs[0] if downs else None
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            sign = 1 if keyval == Gdk.KEY_Right else -1
            x, y = self._pos[nid]
            cands = [k for k, (kx, ky) in self._pos.items()
                     if k != nid and (kx - x) * sign > 4]
            cands.sort(key=lambda k: abs(self._pos[k][0] - x)
                       + 2 * abs(self._pos[k][1] - y))
            target = cands[0] if cands else None
        else:
            return False
        if target is not None:
            nxt = self._nodes[target]
            nxt.grab_focus()
            self.scroll_to_visible(nxt)
        return True

    def scroll_to_visible(self, node):
        vadj = self._scroll.get_vadjustment()
        top, page = vadj.get_value(), vadj.get_page_size()
        if not top + 40 < node.y < top + page - 40:
            vadj.set_value(max(0.0, node.y - page / 2))

    # ── painting ─────────────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        ink = area.get_color()

        def rgba(alpha):
            cr.set_source_rgba(ink.red, ink.green, ink.blue, alpha)

        layout = PangoCairo.create_layout(cr)

        def text(s, x, y, size=0.8, italic=False, bold=False, width=None,
                 alpha=0.6, serif=False, anchor='left'):
            desc = Pango.FontDescription.from_string(
                'Newsreader' if serif else 'Adwaita Sans')
            desc.set_size(int(size * area.get_pango_context()
                              .get_font_description().get_size()))
            if italic:
                desc.set_style(Pango.Style.ITALIC)
            if bold:
                desc.set_weight(Pango.Weight.BOLD)
            layout.set_font_description(desc)
            layout.set_width(int(width * Pango.SCALE) if width else -1)
            layout.set_wrap(Pango.WrapMode.WORD)
            layout.set_text(s, -1)
            tw = layout.get_pixel_size()[0]
            dx = {'left': 0, 'center': -tw / 2, 'right': -tw}[anchor]
            cr.move_to(x + dx, y)
            rgba(alpha)
            PangoCairo.show_layout(cr, layout)
            return layout.get_pixel_size()[1]

        # Before 1611: the root, and a rule under it.
        # Translated, so in the sans: Newsreader has no Cyrillic. The notes
        # below stay English facts, and keep the reading serif.
        text(_('Before 1611 — the root. These texts cannot be placed on '
               'the Line; their spelling defeats the measure.'),
             24, 20, italic=True, width=fl.NOTE_LEFT - 60)
        rgba(0.15)
        cr.set_line_width(1.0)
        cr.move_to(20, fl.AXIS_TOP - 52.5)
        cr.line_to(w - 20, fl.AXIS_TOP - 52.5)
        cr.stroke()

        # The time axis.
        for year in fl.TICKS:
            y = round(fl.year_y(year)) + 0.5
            rgba(0.12)
            if year % 100:
                cr.set_dash([2.0, 4.0])
            cr.move_to(70, y)
            cr.line_to(fl.NOTE_LEFT - 20, y)
            cr.stroke()
            cr.set_dash([])
            text(str(year), 24, y - 8, size=0.75)
        text(_('⋮ compressed'), 24, fl.year_y(1745) - 8, size=0.75,
             alpha=0.45)

        # Lane names above the axis, staggered so neighbours never touch.
        for i, lane in enumerate(self._lanes):
            text(lane.name.upper(), lane.x, fl.AXIS_TOP - (22 if i % 2
                                                           else 40),
                 size=0.68, bold=True, anchor='center', alpha=0.55)

        # The lines of descent.
        for e in self._edges:
            a, b = self._pos[e.parent], self._pos[e.child]
            lit = self._lit is None or (e.parent in self._lit
                                        and e.child in self._lit)
            strong = e.kind == 'rev'
            rgba((0.55 if strong else 0.38) * (1 if lit else 0.25))
            cr.set_line_width(1.6 if strong else 1.1)
            cr.set_dash([] if strong else [1.5, 3.0] if e.kind == 'para'
                        else [5.0, 4.0])
            p0, p1, p2, p3 = fl.edge_curve(a, b)
            cr.move_to(*p0)
            cr.curve_to(*p1, *p2, *p3)
            cr.stroke()
        cr.set_dash([])

        # A note pushed down by the one above keeps a dotted leader back to
        # its year. (The notes themselves are labels, for screen readers.)
        rgba(0.3)
        cr.set_dash([1.0, 3.0])
        for year_y, top in self._note_spots:
            if top > year_y - 9 + 1:
                cr.move_to(fl.NOTE_LEFT - 18, year_y)
                cr.line_to(fl.NOTE_LEFT - 6, top + 9)
        cr.stroke()
        cr.set_dash([])


class FamilyOutline:
    """The same family as an indented list: parents above their children,
    in time order, for readers who want it without the drawing."""

    def __init__(self, on_open_card):
        self._on_open_card = on_open_card
        self._list = Gtk.ListBox()
        self._list.add_css_class('family-outline')
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.connect('row-activated', self._on_row)
        self._last = None
        members = set(bible_family.family_members())
        edges = fl.edges()
        # A Bible's main parent is the first in the data, as everywhere
        # else (the Card, the sentence, the Up key): Matthew's Bible sat
        # under Coverdale here while the Card called it Tyndale's.
        main: dict = {}
        for e in edges:
            if e.kind != 'drew':
                main.setdefault(e.child, e)
        self._parent = {c: e.parent for c, e in main.items()}
        kids: dict[str, list] = {}
        for child, e in main.items():
            kids.setdefault(e.parent, []).append(child)
        roots = sorted((i for i in members if i not in main),
                       key=lambda i: bible_family.node(i)['year'])
        done: set[str] = set()

        def add(nid, depth):
            if nid in done:
                return
            done.add(nid)
            rec = bible_family.node(nid)
            row = Gtk.ListBoxRow()
            row.record = rec
            text = '{} · {}'.format(rec['name'], rec['year'])
            if depth and main[nid].kind == 'para':
                text += '  ' + _('(reworded)')
            lbl = Gtk.Label(label=text, xalign=0)
            lbl.set_margin_start(14 + depth * 22)
            lbl.set_margin_top(5)
            lbl.set_margin_bottom(5)
            if depth:
                lbl.add_css_class('family-outline-child')
            row.set_child(lbl)
            self._list.append(row)
            for c in sorted(kids.get(nid, []),
                            key=lambda i: bible_family.node(i)['year']):
                add(c, depth + 1)

        for r in roots:
            add(r, 0)
        clamp = Adw.Clamp(maximum_size=720)
        clamp.set_child(self._list)
        self.widget = Gtk.ScrolledWindow(vexpand=True)
        self.widget.set_policy(Gtk.PolicyType.NEVER,
                               Gtk.PolicyType.AUTOMATIC)
        self.widget.set_child(clamp)

    def _on_row(self, _list, row):
        self._last = row
        self._on_open_card(row.record['id'])

    def focus_last(self):
        if self._last is not None and self._last.get_mapped():
            self._last.grab_focus()
