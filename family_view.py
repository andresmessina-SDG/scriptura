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

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo

import bible_family
import family_layout as fl
from family_card import (high_contrast, lift, place_sentences,
                         redraw_on_contrast, short_name)
from i18n import _

DOT = 7.0               # the mark's radius, in the drawing's units
BAR_BELOW = 15          # a range bar's distance under its Bible's mark
#: A range narrower than this is one chart's point: no bar is drawn.
BAR_MIN_W = 4.0
NODE_H = 24
#: The rule under the root, and where it sits with the root folded: the
#: root, eight Bibles before 1611, filled the first screen, and the Bibles
#: people read were further down (2026-09-26).
ROOT_RULE = fl.AXIS_TOP - 52
FOLDED_RULE = 56
FOLD_SHIFT = ROOT_RULE - FOLDED_RULE
#: How far below the rule a line out of the folded root comes to full ink.
STUB_FADE = 44


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
    # Say what the drawing shows: the 1611 KJV wears the 1769 text's mark.
    shown = bible_family.node(fl.PLACED_AS.get(record['id'], record['id']))
    where = (_('Before the Line: its spelling cannot be measured.') if root
             else ' '.join(place_sentences(shown)))
    if shown is not record and not root:
        where = _('Placed as {name}: {where}').format(
            name=shown['name'], where=where)
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
        self.root = record['id'] in bible_family.family_data().get('root', {})
        self.spot = fl.spot(record['id'])
        self.bar_above = False      # its range bar, when one crosses a label
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
        self.set_left(fl.label_left(x, self.root))

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
        y0 += self._view._dy(self)
        if self.get_parent() is fixed:
            fixed.move(self, x0, y0)
        else:
            fixed.put(self, x0, y0)

    def refresh(self, reading, installed):
        self.reading = reading
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_sentence(self.record, reading, installed)])
        self._dot.queue_draw()

    def _draw_dot(self, area, cr, w, h):
        cx, cy, r = w / 2, h / 2, DOT - 1.5
        if self.reading:
            accent = Adw.StyleManager.get_default().get_accent_color_rgba()
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
            cr.set_line_width(2.0)
            cr.arc(cx, cy, r + 3.5, 0, 2 * math.pi)
            cr.stroke()
        _paint_mark(cr, cx, cy, self.spot, area.get_color())


def _paint_mark(cr, cx, cy, spot, ink):
    """A Bible's mark: filled where charts place it, a ring where Scriptura
    measured it, a dashed ring where only its makers' word is known, a thin
    ring where nothing places it (the root)."""
    r = DOT - 1.5
    kind = spot.kind if spot is not None else None
    # A fresh path: on the poster the marks share one surface with the text,
    # and an arc begun from the last label's point drew a line back to it.
    cr.new_path()
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
    cr.set_dash([])


def _overlap(a, b, slack=2):
    return (a[0] < b[2] - slack and b[0] < a[2] - slack
            and a[1] < b[3] - slack and b[1] < a[3] - slack)


def _clashes(node, others, bars=()):
    """What `node`'s label would run into: other nodes, and the range bars
    and brackets drawn under other Bibles (a bar through a label reads as a
    strike-through — the RNJB's bracket crossed NASB 2020)."""
    box = node.box()
    hits = [o for o in others if o is not node and _overlap(box, o.box())]
    hits += [o for o, bar in bars if o is not node and _overlap(box, bar)]
    return hits


def _settle(node, placed, bars=()):
    """Find `node` a side for its label clear of those already placed and
    of every bar: its own side, else the other; failing both, flip the
    neighbour it hits (HCSB, a year and a lane from TNIV, took both of
    TNIV's sides)."""
    if not _clashes(node, placed, bars):
        return
    node.set_left(not node.left)
    if not _clashes(node, placed, bars):
        return
    node.set_left(not node.left)
    for other in _clashes(node, placed):
        other.set_left(not other.left)
        if _clashes(other, placed + [node], bars):
            other.set_left(not other.left)


def _measure(layout, text, base_size, size):
    """How wide `text` sets as a lane name: bold, `size` of the base."""
    desc = Pango.FontDescription.from_string('Adwaita Sans')
    desc.set_size(int(size * base_size))
    desc.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(desc)
    layout.set_width(-1)
    layout.set_text(text, -1)
    return layout.get_pixel_size()[0]


def lane_labels(lanes, measure):
    """(size, [(lane, lines)]): each lane's name broken to fit its lane,
    and the size that lets every word fit. `measure(text, size)` gives a
    width in pixels."""
    gap = min((b.x - a.x for a, b in zip(lanes, lanes[1:])), default=80.0)
    size = 0.68
    while size > 0.56 and max(measure(word, size) for lane in lanes
                              for word in lane.name.split()) > gap - 6:
        size -= 0.02
    return size, [(lane, _wrap_words(lane.name, gap - 6,
                                     lambda t: measure(t, size)))
                  for lane in lanes]


def _wrap_words(text, width, measure):
    """`text` broken between words into lines no wider than `width` where a
    word allows; a '·' stays with the word before it."""
    words = text.replace(' · ', '\u00a0· ').split(' ')
    lines: list[str] = []
    for word in words:
        word = word.replace('\u00a0', ' ')
        if lines and measure(f'{lines[-1]} {word}') <= width:
            lines[-1] = f'{lines[-1]} {word}'
        else:
            lines.append(word)
    return lines


def _bar(node):
    """The rectangle of the range bar or bracket drawn under a Bible in the
    'by literalness' arrangement, or None."""
    here = node.spot
    if here is None or here.kind not in ('band', 'class'):
        return None
    if (here.kind == 'band'
            and fl.line_x(here.high) - fl.line_x(here.low) < BAR_MIN_W):
        return None
    y = node.y + (-BAR_BELOW if node.bar_above else BAR_BELOW)
    return (fl.line_x(here.low) - 3, y - 4, fl.line_x(here.high) + 3, y + 3)


class FamilyView:
    """The drawing and its nodes, in a frame that scrolls both ways."""

    def __init__(self, on_open_card, arrangement='family'):
        self._on_open_card = on_open_card
        self._nodes: dict[str, _Node] = {}
        self._lit: set | None = None
        self._last = None
        self._arrangement = arrangement
        self._animation = None
        self._pos = fl.positions(arrangement)
        self._edges = fl.edges()
        self._lanes = fl.lanes()
        self._notes = fl.notes()
        self._root_ids = set(bible_family.family_data().get('root', {}))
        # The root starts folded; the pane restores the reader's choice.
        self._root_open = False
        self._fold = 1.0
        self._fold_anim = None
        self.on_root = None

        # The painting is the lines, axis and lane names: presentation, so a
        # screen reader walks the Bibles and notes instead.
        self._area = Gtk.DrawingArea(
            accessible_role=Gtk.AccessibleRole.PRESENTATION)
        # A size request, not just a content size: the content size is only
        # natural, and the frame squeezed the drawing to its own size.
        self._area.set_size_request(fl.WIDTH, int(fl.HEIGHT) - FOLD_SHIFT)
        self._area.set_draw_func(self._draw)
        redraw_on_contrast(self._area)
        self._fixed = Gtk.Fixed()
        overlay = Gtk.Overlay(halign=Gtk.Align.CENTER)
        overlay.set_child(self._area)
        overlay.add_overlay(self._fixed)
        self._scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._scroll.set_child(overlay)
        self.widget = self._scroll

        # The root's own line at the top, which folds and opens it. First
        # in the drawing, so Tab meets it before the Bibles.
        self._root_btn = Gtk.Button()
        self._root_btn.add_css_class('flat')
        self._root_btn.add_css_class('family-root-toggle')
        # One line: a Fixed gives a wrapping label its narrowest width.
        self._root_label = Gtk.Label(xalign=0)
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image(icon_name='scriptura-pan-end-symbolic'))
        box.append(self._root_label)
        self._root_btn.set_child(box)
        self._root_btn.connect(
            'clicked', lambda _b: self.set_root_open(not self._root_open))
        self._fixed.put(self._root_btn, 12, 10)
        self._show_root_state()

        for nid in bible_family.family_members():
            x, y = self._pos[nid]
            node = _Node(self, bible_family.node(nid), x, y)
            self._nodes[nid] = node
        # The margin notes, in the reading serif, as real labels so a screen
        # reader reaches them. The early ones fall close together where the
        # axis is compressed, so each starts below the one above.
        self._note_spots = []
        self._note_labels = []
        self._show_notes = True
        notes = []
        bottom = 0.0
        for note in self._notes:
            label = Gtk.Label(label=note.text, xalign=0, wrap=True)
            label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
            label.add_css_class('family-note')
            label.set_size_request(fl.NOTE_WIDTH, -1)
            top = max(note.y - 9, bottom + 10)
            height = label.measure(Gtk.Orientation.VERTICAL,
                                   fl.NOTE_WIDTH)[1]
            self._note_spots.append((note.y, top))
            self._note_labels.append(label)
            notes.append((top, label))
            bottom = top + height

        # Into the drawing in reading order, down the page in time: Tab and
        # a screen reader meet each note beside the Bibles of its years.
        self._settle_labels()
        things = [(n.y, 1, n) for n in self._nodes.values()]
        things += [(top, 0, label) for top, label in notes]
        for _y, is_node, w in sorted(things, key=lambda t: (t[0], t[1])):
            if is_node:
                w.place(self._fixed)
            else:
                self._fixed.put(w, fl.NOTE_LEFT, _y)
        self._apply_fold(self._fold)

    # ── the root, folded or open ─────────────────────────────────────────

    @property
    def root_open(self):
        return self._root_open

    def set_root_open(self, open_, animate=True):
        """Open the root (the Bibles before 1611) or fold it to one line.
        Folding, the root's Bibles sink onto the rule and fade while the
        drawing rises under them; the lines they gave the KJV and the
        Douay–Rheims stand straight up out of the fold."""
        if open_ == self._root_open:
            return
        self._root_open = open_
        self._show_root_state()
        if self.on_root is not None:
            self.on_root(open_)
        # A fold still running turns round from where it is.
        if self._fold_anim is not None:
            self._fold_anim.pause()
            self._fold_anim = None
        target = 0.0 if open_ else 1.0
        if not animate:
            self._apply_fold(target)
            return
        anim = Adw.TimedAnimation.new(
            self._area, self._fold, target,
            max(1, int(520 * abs(target - self._fold))),
            Adw.CallbackAnimationTarget.new(self._apply_fold))
        anim.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        anim.connect('done', lambda *_a: setattr(self, '_fold_anim', None))
        self._fold_anim = anim
        anim.play()

    def _show_root_state(self):
        if self._root_open:
            words = _('Before 1611 — the root. These texts cannot be placed '
                      'on the Line; their spelling defeats the measure.')
            tip = _('Fold the root')
            self._root_btn.add_css_class('open')
        else:
            root = sorted((bible_family.node(i) for i in self._root_ids),
                          key=lambda r: r['year'])
            words = _('Before 1611 — the root: {first} to {last}').format(
                first=f"{short_name(root[0])} {root[0]['year']}",
                last=f"{short_name(root[-1])} {root[-1]['year']}")
            tip = _('Show the root')
            self._root_btn.remove_css_class('open')
        self._root_label.set_label(words)
        self._root_btn.set_tooltip_text(tip)
        # EXPANDED is boolean-or-undefined, held as an int.
        self._root_btn.update_state([Gtk.AccessibleState.EXPANDED],
                                    [int(self._root_open)])

    def _shift(self):
        """How far the drawing has risen for the fold."""
        return round(self._fold * FOLD_SHIFT)

    def _sink(self, nid, y):
        """How far a root Bible has sunk toward the rule."""
        return (ROOT_RULE - y) * self._fold if nid in self._root_ids else 0.0

    def _dy(self, node):
        """Where a node is drawn, below where the layout puts it."""
        return self._sink(node.record['id'], node.y) - self._shift()

    def _apply_fold(self, fold):
        self._fold = fold
        shift = self._shift()
        for node in self._nodes.values():
            if node.root:
                # Gone before they reach the rule, so they never pile up
                # on it; opening, they appear in the second half.
                node.set_opacity(max(0.0, 1.0 - fold * 1.6))
                node.set_visible(fold < 1.0)
            node.place(self._fixed)
        for (_y, top), label in zip(self._note_spots, self._note_labels):
            self._fixed.move(label, fl.NOTE_LEFT, top - shift)
        self._area.set_size_request(fl.WIDTH, int(fl.HEIGHT) - shift)
        self._area.queue_draw()

    def set_notes_visible(self, visible):
        """Show or hide the margin notes and their leaders; the poster,
        which prints what is on screen, follows."""
        self._show_notes = visible
        for label in self._note_labels:
            label.set_visible(visible)
        self._area.queue_draw()

    def _settle_labels(self):
        """Each label on its natural side, then flipped where it would run
        into one placed before it (down the page, then across)."""
        order = sorted(self._nodes.values(), key=lambda n: (n.y, n.x))
        for node in order:
            node.bar_above = False
        bars = ([(n, b) for n in order if (b := _bar(n)) is not None]
                if self._arrangement == 'line' else [])
        placed: list[_Node] = []
        for node in order:
            node.set_left(fl.label_left(node.x, node.root))
            _settle(node, placed, bars)
            placed.append(node)
        # A bar no label could dodge (a bracket spans a whole zone) goes
        # above its own Bible instead, when that side is clear.
        for owner, _b in bars:
            if any(_overlap(o.box(), _bar(owner)) for o in order
                   if o is not owner):
                owner.bar_above = True
                if any(_overlap(o.box(), _bar(owner)) for o in order
                       if o is not owner):
                    owner.bar_above = False

    # ── the arrangements ─────────────────────────────────────────────────

    @property
    def arrangement(self):
        return self._arrangement

    def set_arrangement(self, arrangement, animate=True):
        """'family' (lanes) or 'line' (each Bible slid to its place on the
        Line). The Bibles glide there, time staying put; with animations
        off (GNOME's reduced motion) they are simply there."""
        if arrangement == self._arrangement:
            return
        # A slide still running is finished first, and the new one starts
        # from where that left the Bibles, not from where it found them.
        if self._animation is not None:
            self._animation.skip()
        start = dict(self._pos)
        end = fl.positions(arrangement)
        self._arrangement = arrangement

        def step(t):
            for nid, node in self._nodes.items():
                (x0, y0), (x1, y1) = start[nid], end[nid]
                node.x, node.y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                node.place(self._fixed)
            self._pos = {k: (n.x, n.y) for k, n in self._nodes.items()}
            self._area.queue_draw()

        def done(*_a):
            self._animation = None
            self._pos = end
            for nid, node in self._nodes.items():
                node.x, node.y = end[nid]
            self._settle_labels()
            for node in self._nodes.values():
                node.place(self._fixed)
            self._area.queue_draw()

        if not animate:
            step(1.0)
            done()
            return
        target = Adw.CallbackAnimationTarget.new(step)
        anim = Adw.TimedAnimation.new(self._area, 0.0, 1.0, 700, target)
        anim.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        anim.connect('done', done)
        self._animation = anim
        anim.play()

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

    def scroll_to(self, node, then=None):
        """Bring `node` into view, a third of the way down; `then` runs
        after. A frame not yet laid out has no page to scroll, and would
        clamp the scroll to the top, so this waits until it has one."""
        if node.root:
            self.set_root_open(True, animate=False)
        vadj = self._scroll.get_vadjustment()
        hadj = self._scroll.get_hadjustment()

        def go():
            vadj.set_value(max(0.0, node.y + self._dy(node)
                               - vadj.get_page_size() / 3))
            hadj.set_value(max(0.0, node.x - hadj.get_page_size() / 2))
            if then is not None:
                then()

        if vadj.get_page_size() > 0:
            go()
            return
        handler = None

        def on_changed(_adj):
            if vadj.get_page_size() > 0:
                vadj.disconnect(handler)
                # Not inside the layout that sent this: a scroll set there
                # moved the value but never the drawing.
                GLib.idle_add(lambda: go() or GLib.SOURCE_REMOVE)
        handler = vadj.connect('changed', on_changed)

    def focus_last(self):
        if self._last is not None and self._last.get_mapped():
            self._last.grab_focus()

    def show_node(self, node_id, then=None):
        """Give one Bible the keyboard, which lights its line, and scroll
        to it; `then` runs once it is in view."""
        node = self._last = self._nodes[node_id]
        if node.root:
            self.set_root_open(True, animate=False)
        node.grab_focus()
        self.scroll_to(node, then)

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
                     if k != nid and (kx - x) * sign > 4
                     and (self._root_open or k not in self._root_ids)]
            cands.sort(key=lambda k: abs(self._pos[k][0] - x)
                       + 2 * abs(self._pos[k][1] - y))
            target = cands[0] if cands else None
        else:
            return False
        if target in self._root_ids and not self._root_open:
            # Up from the KJV into the folded root: its line, which opens it.
            if keyval == Gdk.KEY_Up:
                self._root_btn.grab_focus()
            return True
        if target is not None:
            nxt = self._nodes[target]
            nxt.grab_focus()
            self.scroll_to_visible(nxt)
        return True

    def scroll_to_visible(self, node):
        vadj = self._scroll.get_vadjustment()
        top, page = vadj.get_value(), vadj.get_page_size()
        y = node.y + self._dy(node)
        if not top + 40 < y < top + page - 40:
            vadj.set_value(max(0.0, y - page / 2))

    # ── painting ─────────────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        self._paint(cr, w, h, area.get_color(),
                    area.get_pango_context().get_font_description().get_size(),
                    self._lit, hc=high_contrast(), fold=self._fold,
                    caption=False)

    def _unplaced(self, node_id):
        """Whether a Bible stands in Not placed: arranged by literalness,
        with no place on the Line and not one of the root."""
        node = self._nodes[node_id]
        return (self._arrangement == 'line' and node.spot is None
                and not node.root)

    def _paint(self, cr, w, h, ink, base_size, lit, hc=False, fold=0.0,
               caption=True):
        """The drawing under the Bibles: axis, lanes or zones, lines of
        descent, bars. `ink` is anything with red/green/blue; `lit` the
        Bibles to keep bright (None for all); `hc` lifts the faint inks for
        high contrast, but not the rules and grid, which only divide;
        `fold` how far the root is folded (1 folded); `caption` whether to
        write the root's line, which on screen is the button that folds
        it. The poster calls it too, with the root open."""
        cr.save()
        shift = round(fold * FOLD_SHIFT)
        cr.translate(0, -shift)
        h += shift

        def rgba(alpha):
            cr.set_source_rgba(ink.red, ink.green, ink.blue, alpha)

        layout = PangoCairo.create_layout(cr)
        # Points to units as on screen, so a poster sets type like the view.
        PangoCairo.context_set_resolution(layout.get_context(), 96)

        # Where the names over the lines sit: the lines of descent are cut
        # there, so no line strikes through a name.
        knockouts = []

        def text(s, x, y, size=0.8, italic=False, bold=False, width=None,
                 alpha=0.6, serif=False, anchor='left', knock=False):
            desc = Pango.FontDescription.from_string(
                'Newsreader' if serif else 'Adwaita Sans')
            desc.set_size(int(size * base_size))
            if italic:
                desc.set_style(Pango.Style.ITALIC)
            if bold:
                desc.set_weight(Pango.Weight.BOLD)
            layout.set_font_description(desc)
            layout.set_width(int(width * Pango.SCALE) if width else -1)
            layout.set_wrap(Pango.WrapMode.WORD)
            layout.set_text(s, -1)
            tw, th = layout.get_pixel_size()
            dx = {'left': 0, 'center': -tw / 2, 'right': -tw}[anchor]
            if knock:
                knockouts.append((x + dx - 4, y - 2, tw + 8, th + 4))
            cr.move_to(x + dx, y)
            rgba(lift(alpha, hc, text=True))
            PangoCairo.show_layout(cr, layout)
            return layout.get_pixel_size()[1]

        # Before 1611: the root, and a rule under it.
        # Translated, so in the sans: Newsreader has no Cyrillic. The notes
        # below stay English facts, and keep the reading serif.
        if caption:
            text(_('Before 1611 — the root. These texts cannot be placed '
                   'on the Line; their spelling defeats the measure.'),
                 24, 20, italic=True, width=fl.NOTE_LEFT - 60)
        rgba(0.15)
        cr.set_line_width(1.0)
        cr.move_to(20, ROOT_RULE - 0.5)
        cr.line_to(w - 20, ROOT_RULE - 0.5)
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

        if self._arrangement == 'family':
            # Lane names above the axis in one row, each wrapped to its own
            # lane's width and sitting on one line: staggered in two rows,
            # neighbours read as one tangle (2026-09-25).
            # In title case: in capitals "JERUSALEM" alone outran its lane
            # (60px of 59) and ran into "HOLMAN · CSB". A name that still
            # will not fit sets the whole row a size down.
            size, labels = lane_labels(
                self._lanes, lambda t, sz: _measure(layout, t, base_size, sz))
            for lane, lines in labels:
                for k, line in enumerate(reversed(lines)):
                    text(line, lane.x, fl.AXIS_TOP - 24 - 13 * k,
                         size=size, bold=True, anchor='center', alpha=0.55,
                         knock=True)
        else:
            # The Line's zones across the page, and a column for the rest.
            rgba(0.18)
            cr.set_dash([1.0, 5.0])
            for bound, _n in bible_family.ZONES[:-1]:
                x = round(fl.line_x(bound)) + 0.5
                cr.move_to(x, fl.AXIS_TOP - 18)
                cr.line_to(x, h - 20)
            cr.stroke()
            cr.set_dash([])
            lo = 0.0
            for bound, name in bible_family.ZONES:
                mid = fl.line_x((lo + min(bound, 1.0)) / 2)
                text(_(name).upper(), mid, fl.AXIS_TOP - 34, size=0.68,
                     bold=True, anchor='center', alpha=0.55, knock=True)
                lo = bound
            text(_('Not placed').upper(), fl.NOT_PLACED_X,
                 fl.AXIS_TOP - 34, size=0.68, bold=True, anchor='center',
                 alpha=0.55, knock=True)
            # Where charts place a Bible, its range as a soft bar under it;
            # where only its makers' word is known, a bracket over the zone.
            if self._animation is None:
                for nid, node in self._nodes.items():
                    here = node.spot
                    if here is None or here.kind not in ('band', 'class'):
                        continue
                    # A bar fades with its Bible when another line is lit.
                    fade = 0.3 if (lit is not None
                                   and nid not in lit) else 1.0
                    y = node.y + (-BAR_BELOW if node.bar_above
                                  else BAR_BELOW)
                    x0, x1 = fl.line_x(here.low), fl.line_x(here.high)
                    if here.kind == 'band' and x1 - x0 < BAR_MIN_W:
                        # One chart's figure has no width, and its mark
                        # already sits on it: as a bar it was a speck under
                        # the name, like dirt; as a tick, hidden behind the
                        # Bible's own line (NASB 1995).
                        continue
                    if here.kind == 'band':
                        rgba(lift(0.22, hc) * fade)
                        cr.set_line_width(4.0)
                        cr.set_line_cap(cairo.LINE_CAP_ROUND)
                        cr.move_to(x0, y)
                        cr.line_to(x1, y)
                        cr.stroke()
                    else:
                        # The bracket's ends point at its own Bible.
                        tip = 4 if node.bar_above else -4
                        rgba(lift(0.45, hc) * fade)
                        cr.set_line_width(1.3)
                        cr.move_to(x0 + 3, y + tip)
                        cr.line_to(x0 + 3, y)
                        cr.line_to(x1 - 3, y)
                        cr.line_to(x1 - 3, y + tip)
                        cr.stroke()
                cr.set_line_cap(cairo.LINE_CAP_BUTT)

        # The lines of descent, cut where they pass behind a name.
        self._knockouts = knockouts
        cr.save()
        if knockouts:
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.rectangle(0, 0, w, h)
            for kx, ky, kw, kh in knockouts:
                cr.rectangle(kx, ky, kw, kh)
            cr.clip()
        for e in self._edges:
            (ax, ay), (bx, by) = self._pos[e.parent], self._pos[e.child]
            bright = lit is None or (e.parent in lit and e.child in lit)
            strong = e.kind == 'rev'
            # A line to a Bible with no place on the Line stays faint: the
            # longest strokes ran to the two Bibles known least.
            alpha = (lift(0.55 if strong else 0.38, hc)
                     * (1 if bright else 0.25)
                     * (0.4 if self._unplaced(e.child) else 1))
            from_root = e.parent in self._root_ids
            if from_root:
                ay += (ROOT_RULE - ay) * fold
            if e.child in self._root_ids:
                by += (ROOT_RULE - by) * fold
            b = (bx, by)
            if from_root and e.child not in self._root_ids and strong:
                # A revision of a root Bible stands straight up out of the
                # fold, fading into it: the line leaves the rule above its
                # own Bible, not a Bible folded out of sight.
                ax += (b[0] - ax) * fold
                grad = cairo.LinearGradient(0, ROOT_RULE, 0,
                                            ROOT_RULE + STUB_FADE)
                grad.add_color_stop_rgba(0, ink.red, ink.green, ink.blue,
                                         alpha * (1 - fold))
                grad.add_color_stop_rgba(1, ink.red, ink.green, ink.blue,
                                         alpha)
                cr.set_source(grad)
            elif from_root:
                # Inside the root, and the root's "drew on" lines, go with it.
                rgba(alpha * (1 - fold))
            else:
                rgba(alpha)
            a = (ax, ay)
            cr.set_line_width(1.6 if strong else 1.1)
            cr.set_dash([] if strong else [1.5, 3.0] if e.kind == 'para'
                        else [5.0, 4.0])
            p0, p1, p2, p3 = fl.edge_curve(a, b)
            cr.move_to(*p0)
            cr.curve_to(*p1, *p2, *p3)
            cr.stroke()
        cr.set_dash([])
        cr.restore()

        # A note pushed down by the one above keeps a dotted leader back to
        # its year. (The notes themselves are labels, for screen readers.)
        rgba(lift(0.3, hc))
        cr.set_dash([1.0, 3.0])
        for year_y, top in (self._note_spots if self._show_notes else ()):
            if top > year_y - 9 + 1:
                cr.move_to(fl.NOTE_LEFT - 18, year_y)
                cr.line_to(fl.NOTE_LEFT - 6, top + 9)
        cr.stroke()
        cr.set_dash([])
        cr.restore()


#: The poster's title band above the drawing and key below it.
PLATE_HEAD = 110
PLATE_FOOT = 96
#: Type on the poster, as on screen: 11pt Adwaita Sans at 96 dpi.
PLATE_BASE = 11 * Pango.SCALE
_PLATE_INK = Gdk.RGBA(red=0.1, green=0.1, blue=0.1, alpha=1.0)


def paint_plate(view, cr, page_w, page_h):
    """The Family as a poster: what the view shows, in black on white, with
    a title, a key and a source line, fitted to one page. No reading ring and
    nothing lit: the poster is the class's, not the reader's."""
    plate_w, plate_h = fl.WIDTH, PLATE_HEAD + fl.HEIGHT + PLATE_FOOT
    scale = min(page_w / plate_w, page_h / plate_h)
    cr.save()
    cr.translate((page_w - plate_w * scale) / 2, 0)
    cr.scale(scale, scale)
    ink = _PLATE_INK
    layout = PangoCairo.create_layout(cr)
    PangoCairo.context_set_resolution(layout.get_context(), 96)

    def text(s, x, y, size=1.0, bold=False, italic=False, serif=False,
             width=None, alpha=1.0, anchor='left'):
        desc = Pango.FontDescription.from_string(
            'Newsreader' if serif else 'Adwaita Sans')
        desc.set_size(int(size * PLATE_BASE))
        if bold:
            desc.set_weight(Pango.Weight.BOLD)
        if italic:
            desc.set_style(Pango.Style.ITALIC)
        layout.set_font_description(desc)
        layout.set_width(int(width * Pango.SCALE) if width else -1)
        layout.set_wrap(Pango.WrapMode.WORD)
        layout.set_text(s, -1)
        tw, th = layout.get_pixel_size()
        dx = {'left': 0, 'right': -tw}[anchor]
        cr.move_to(x + dx, y)
        cr.set_source_rgba(ink.red, ink.green, ink.blue, alpha)
        PangoCairo.show_layout(cr, layout)
        return tw, th

    # Title band.
    text(_('The Bible Family Tree'), 24, 18, size=2.0, bold=True)
    subtitle = (_('The English Bibles read today, placed by how literally '
                  'they translate')
                if view.arrangement == 'line' else
                _('The English Bibles read today, and the Bibles they came '
                  'from'))
    text(subtitle, 24, 58, size=1.15, italic=True, alpha=0.7)

    # The drawing, then the Bibles and notes on it.
    cr.save()
    cr.translate(0, PLATE_HEAD)
    view._paint(cr, fl.WIDTH, fl.HEIGHT, ink, PLATE_BASE, None)
    side = DOT * 2 + 8
    for node in view._nodes.values():
        _paint_mark(cr, node.x, node.y, node.spot, ink)
        name = short_name(node.record)
        year = str(node.record['year'])
        desc = Pango.FontDescription.from_string('Adwaita Sans')
        desc.set_size(int(0.9 * PLATE_BASE))
        desc.set_weight(Pango.Weight.BOLD)      # as text() draws it
        layout.set_width(-1)
        layout.set_font_description(desc)
        layout.set_text(name, -1)
        name_w, name_h = layout.get_pixel_size()
        top = node.y - name_h / 2
        if node.left:           # year · name · mark, ending at the mark
            x = node.x - side / 2 - 4
            text(year, x - name_w - 4, top + 1, size=0.8, alpha=0.55,
                 anchor='right')
            text(name, x - name_w, top, size=0.9, bold=True)
        else:
            x = node.x + side / 2 + 4
            text(name, x, top, size=0.9, bold=True)
            text(year, x + name_w + 4, top + 1, size=0.8, alpha=0.55)
    notes = zip(view._note_spots, view._notes) if view._show_notes else ()
    for (_year_y, top), note in notes:
        text(note.text, fl.NOTE_LEFT, top, size=0.95, italic=True,
             serif=True, width=fl.NOTE_WIDTH, alpha=0.75)
    cr.restore()

    # Key and source line.
    y = PLATE_HEAD + fl.HEIGHT + 14
    x = 24
    for spot_kind, words in (
            ('band', _('published charts place it')),
            ('measured', _('measured in Scriptura')),
            ('class', _('described by its makers')),
            (None, _('before the Line')),):
        spot = (bible_family.Place(spot_kind, 0.5, 0.5, 0.5)
                if spot_kind else None)
        _paint_mark(cr, x + DOT, y + 9, spot, ink)
        x += DOT * 2 + 6 + text(words, x + DOT * 2 + 6, y, size=0.85)[0] + 22
    x = 24
    y += 28
    for dash, width, words in (([], 1.6, _('a revision of')),
                               ([1.5, 3.0], 1.1, _('reworded from')),
                               ([5.0, 4.0], 1.1, _('drew on'))):
        cr.set_source_rgba(ink.red, ink.green, ink.blue, 0.6)
        cr.set_line_width(width)
        cr.set_dash(dash)
        cr.move_to(x, y + 9)
        cr.line_to(x + 30, y + 9)
        cr.stroke()
        cr.set_dash([])
        x += 38 + text(words, x + 38, y, size=0.85)[0] + 22
    text(_('Scriptura · every fact and its source is in the app’s Bible '
           'Family Tree'), fl.WIDTH - 24, y + 30, size=0.75, alpha=0.55,
         anchor='right')
    cr.restore()


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
            lbl = Gtk.Label(label=text, xalign=0, wrap=True)
            lbl.set_max_width_chars(1)      # wrap at the pane, not beyond
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

    def show_node(self, node_id, then=None):
        for row in self._rows():
            if row.record['id'] == node_id:
                self._last = row
                row.grab_focus()     # the list scrolls to its focus
                break
        if then is not None:
            then()

    def _rows(self):
        row = self._list.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

    def focus_last(self):
        if self._last is not None and self._last.get_mapped():
            self._last.grab_focus()
