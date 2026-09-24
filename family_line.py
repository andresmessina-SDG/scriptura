"""family_line.py — the Line: every English Bible on one track.

The first view of The Bible Family Tree, opened in a pane from the module
list like The Book of Generations. One row per Bible — name, year and
tradition on the left, its mark on the Line on the right, every track the
same width so the eye reads straight down. Pressing a row opens its Card.

Filters (decided 2026-09-24): availability, tradition (seven chips), era,
and a sort — by place on the Line (the default, grouped by zone), by year
(grouped by era) or by name.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk, Pango

import bible_family
from a11y import set_accessible_label
from family_card import paint_track
from i18n import _, ngettext

#: The track's width, the same in every row and in the axis above them.
TRACK_W = 240
#: Below this width the rows stack: name above, track below.
STACK_BELOW = 560


class _Row(Gtk.ListBoxRow):
    """One Bible. Its facts are fixed; `installed` and `reading` follow the
    app's modules and are refreshed on every render."""

    def __init__(self, record):
        super().__init__()
        self.record = record
        self.spot = bible_family.place_of(record)
        self.chip = bible_family.tradition_chip(record)
        self.era = bible_family.era(record)
        self.installed = None
        self.reading = False

        self._box = Gtk.Box(spacing=12)
        self._box.set_margin_start(14)
        self._box.set_margin_end(14)
        self._box.set_margin_top(7)
        self._box.set_margin_bottom(7)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1,
                       hexpand=True)
        self._name = Gtk.Label(label=record['name'], xalign=0)
        self._name.set_ellipsize(Pango.EllipsizeMode.END)
        self._name.add_css_class('family-line-name')
        text.append(self._name)
        self._meta = Gtk.Label(xalign=0)
        self._meta.set_ellipsize(Pango.EllipsizeMode.END)
        self._meta.add_css_class('family-line-meta')
        text.append(self._meta)
        self._box.append(text)

        self._track = Gtk.DrawingArea()
        self._track.set_content_width(TRACK_W)
        self._track.set_content_height(18)
        self._track.set_valign(Gtk.Align.CENTER)
        if self.spot is not None:
            spot = self.spot
            self._track.set_draw_func(lambda a, cr, w, h: paint_track(
                cr, w, h, spot, a.get_color(), pad=6.0, r=4.0))
        self._box.append(self._track)
        self.set_child(self._box)

    def refresh(self, installed, reading):
        self.installed = installed
        self.reading = reading
        tradition = _(bible_family.TRADITIONS.get(
            self.record.get('tradition'), ''))
        parts = [str(self.record.get('year_label', self.record['year'])),
                 tradition]
        if reading:
            parts.append(_('You are reading this'))
        elif installed:
            parts.append(_('Installed'))
        self._meta.set_label(' · '.join(p for p in parts if p))
        self._name.remove_css_class('accent')
        if reading:
            self._name.add_css_class('accent')
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [self._sentence(tradition)])

    def _sentence(self, tradition):
        """What a screen reader says for the row: the facts, where it lands
        and whether you have it."""
        from family_card import place_sentences
        where = ' '.join(place_sentences(self.record))
        have = (_('You are reading this.') if self.reading
                else _('Installed.') if self.installed
                else _('Not installed.'))
        return '{}, {}, {}. {} {}'.format(
            self.record['name'], self.record['year'], tradition, where, have)

    def set_stacked(self, stacked):
        self._box.set_orientation(Gtk.Orientation.VERTICAL if stacked
                                  else Gtk.Orientation.HORIZONTAL)
        self._box.set_spacing(4 if stacked else 12)
        self._track.set_hexpand(stacked)
        self._track.set_halign(Gtk.Align.FILL if stacked else Gtk.Align.END)

    # ── ordering ──────────────────────────────────────────────────────────

    def group(self, sort):
        """The header group this row sits in under `sort`, as (order, key)."""
        if sort == 'year':
            return (self.era, 'era')
        if sort == 'name':
            return (0, '')
        if self.spot is None:
            return (99, 'none')
        zone = next(i for i, (bound, _n) in enumerate(bible_family.ZONES)
                    if self.spot.value < bound)
        described = self.spot.kind == 'class'
        return (zone * 2 + described, 'zone')

    def sort_key(self, sort):
        name = self.record['name'].lower()
        if sort == 'year':
            return (self.record['year'], name)
        if sort == 'name':
            return (name,)
        value = self.spot.value if self.spot is not None else 0.0
        return (self.group(sort)[0], value, name)


def _chips(labels, on_pick):
    """A wrapping row of grouped toggle chips; the first starts lit.
    `labels` is [(key, text)]; `on_pick(key)` runs when one is chosen."""
    box = Adw.WrapBox(child_spacing=6, line_spacing=6)
    first = None
    for key, text in labels:
        chip = Gtk.ToggleButton(label=text)
        chip.add_css_class('family-chip')
        if first is None:
            first = chip
            chip.set_active(True)
        else:
            chip.set_group(first)
        chip.connect('toggled', lambda b, k=key:
                     b.get_active() and on_pick(k))
        box.append(chip)
    return box


class FamilyLine:
    """The pane subsystem for The Bible Family Tree's Line."""

    def __init__(self, pane=None):
        self._pane = pane
        self._rows: list[_Row] = []
        self._availability = 'all'
        self._tradition = ''
        self._era = -1
        self._sort = 'place'
        self._stacked = False
        self._counts: dict = {}
        self._scrolled_for = None
        self._build()

    @property
    def widget(self):
        return self._root

    # ── construction ─────────────────────────────────────────────────────

    def _build(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        filters = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        filters.set_margin_start(14)
        filters.set_margin_end(14)
        filters.set_margin_top(10)
        filters.set_margin_bottom(6)
        filters.append(_chips(
            [('all', _('All')), ('installed', _('Installed')),
             ('can', _('Can install'))], self._set_availability))
        filters.append(_chips(
            [('', _('All traditions'))]
            + [(k, _(t)) for k, t in bible_family.TRADITION_CHIPS],
            self._set_tradition))
        filters.append(_chips(
            [(-1, _('All eras'))]
            + [(i, _(label)) for i, (_lo, _hi, label)
               in enumerate(bible_family.ERAS)], self._set_era))
        sort_row = Gtk.Box(spacing=8)
        sort_lbl = Gtk.Label(label=_('Sort'))
        sort_lbl.add_css_class('family-line-meta')
        sort_row.append(sort_lbl)
        sort_row.append(_chips(
            [('place', _('By place on the Line')), ('year', _('By year')),
             ('name', _('By name'))], self._set_sort))
        filters.append(sort_row)
        box.append(filters)

        # The axis over the tracks: the ends of the Line, lined up with the
        # track column so the eye reads straight down.
        self._axis = Gtk.Box()
        self._axis.add_css_class('family-line-axis')
        self._axis.set_margin_start(14)
        self._axis.set_margin_end(14)
        self._axis_ends = Gtk.Box(hexpand=False)
        self._axis_ends.set_size_request(TRACK_W, -1)
        self._axis_ends.set_halign(Gtk.Align.END)
        self._axis_ends.append(Gtk.Label(label=_('Word for word'), xalign=0,
                                         hexpand=True))
        self._axis_ends.append(Gtk.Label(label=_('Free'), xalign=1))
        self._axis.append(Gtk.Box(hexpand=True))
        self._axis.append(self._axis_ends)
        box.append(self._axis)

        self._list = Gtk.ListBox()
        self._list.add_css_class('family-line-list')
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.set_filter_func(self._filter)
        self._list.set_sort_func(
            lambda a, b: (a.sort_key(self._sort) > b.sort_key(self._sort))
            - (a.sort_key(self._sort) < b.sort_key(self._sort)))
        self._list.set_header_func(self._header)
        self._list.connect('row-activated', self._on_row_activated)
        set_accessible_label(self._list, _('English Bibles on the Line'))
        self._empty = Gtk.Label(label=_('No Bible matches these filters.'))
        self._empty.add_css_class('dim-label')
        self._empty.set_margin_top(24)
        self._list.set_placeholder(self._empty)

        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_child(self._list)
        box.append(self._scroll)

        # Narrow panes stack each row: the track under the name, full width.
        self._root = Adw.BreakpointBin()
        self._root.set_size_request(280, 200)
        self._root.set_child(box)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(
            f'max-width: {STACK_BELOW}sp'))
        narrow.connect('apply', lambda _b: self._set_stacked(True))
        narrow.connect('unapply', lambda _b: self._set_stacked(False))
        self._root.add_breakpoint(narrow)

    def _ensure_rows(self):
        if self._rows:
            return
        for record in bible_family.translations():
            row = _Row(record)
            row.set_stacked(self._stacked)
            self._rows.append(row)
            self._list.append(row)

    # ── the pane's calls ─────────────────────────────────────────────────

    def render(self):
        """Refresh what is installed and read, then show the reading Bible."""
        self._ensure_rows()
        installed = self._installed_keys()
        reading = self._reading_module()
        target = None
        for row in self._rows:
            have = bible_family.installed_module(row.record['id'], installed)
            is_reading = (reading is not None
                          and bible_family.node_for_module(reading)
                          is row.record)
            row.refresh(have, is_reading)
            if is_reading:
                target = row
        self._refilter()
        # Scroll to it only when the Bible being read has changed. The pane
        # re-renders for other reasons too (a theme switch, a backup
        # restored), and each one threw the reader back to their own row.
        if target is not None and target is not self._scrolled_for:
            self._scrolled_for = target
            GLib.idle_add(lambda: self._scroll_to(target) or False)

    def reading_module(self):
        return self._reading_module()

    # ── state ────────────────────────────────────────────────────────────

    def _installed_keys(self):
        return list(getattr(self._pane, '_names', []) or [])

    def _reading_module(self):
        """The Bible being read: the other pane's, when it shows one; else
        the Bible this pane showed before it opened the Line."""
        pane = self._pane
        root = pane.get_root() if pane is not None else None
        for other in (getattr(root, 'pane1', None), getattr(root, 'pane2', None)):
            if (other is not None and other is not pane
                    and other.get_visible()
                    and bible_family.node_for_module(other.module)):
                return other.module
        came_from = getattr(pane, '_came_from', None)
        if came_from and bible_family.node_for_module(came_from):
            return came_from
        return None

    def _set_availability(self, key):
        self._availability = key
        self._refilter()

    def _set_tradition(self, key):
        self._tradition = key
        self._refilter()

    def _set_era(self, key):
        self._era = key
        self._refilter()

    def _set_sort(self, key):
        self._sort = key
        self._list.invalidate_sort()
        self._refilter()

    def _set_stacked(self, stacked):
        self._stacked = stacked
        for row in self._rows:
            row.set_stacked(stacked)
        self._axis.set_visible(not stacked)

    # ── the list's functions ─────────────────────────────────────────────

    def _filter(self, row):
        if self._availability == 'installed' and row.installed is None:
            return False
        if self._availability == 'can' and (
                row.installed is not None
                or not row.record.get('installable')):
            return False
        if self._tradition and row.chip != self._tradition:
            return False
        if self._era >= 0 and row.era != self._era:
            return False
        return True

    def _refilter(self):
        # Header counts follow the filters, so count before the list asks.
        # A zone's count holds every Bible in it, described-only ones too.
        self._counts = {}
        for row in self._rows:
            if self._filter(row):
                g = self._count_key(row)
                self._counts[g] = self._counts.get(g, 0) + 1
        self._list.invalidate_filter()
        self._list.invalidate_headers()

    def _count_key(self, row):
        order, kind = row.group(self._sort)
        return (order // 2, kind) if kind == 'zone' else (order, kind)

    def _header(self, row, before):
        group = row.group(self._sort)
        if before is not None and before.group(self._sort) == group:
            row.set_header(None)
            return
        order, kind = group
        n = self._counts.get(self._count_key(row), 0)
        if kind == 'zone':
            # A new zone gets its heading; the described-only Bibles in it
            # get a quiet line under it (under the heading too, when the
            # zone holds nothing else).
            zone = _(bible_family.ZONES[order // 2][1])
            new_zone = (before is None
                        or self._count_key(before) != self._count_key(row))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            if new_zone:
                head = Gtk.Label(label=ngettext(
                    '{zone} · {n} Bible', '{zone} · {n} Bibles', n).format(
                        zone=zone, n=n), xalign=0)
                head.add_css_class('family-line-head')
                box.append(head)
            if order % 2:
                sub = Gtk.Label(label=_('Described by their makers as '
                                        '“{zone}”').format(zone=zone), xalign=0)
                sub.add_css_class('family-line-subhead')
                box.append(sub)
            row.set_header(box)
            return
        if kind == 'era':
            text = ngettext('{era} · {n} Bible', '{era} · {n} Bibles',
                            n).format(era=_(bible_family.ERAS[order][2]), n=n)
            css = 'family-line-head'
        elif kind == 'none':
            text = ngettext('Not placed · {n} Bible', 'Not placed · {n} Bibles',
                            n).format(n=n)
            css = 'family-line-head'
        else:
            row.set_header(None)
            return
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class(css)
        row.set_header(label)

    def _scroll_to(self, row):
        ok, bounds = row.compute_bounds(self._list)
        if ok:
            adj = self._scroll.get_vadjustment()
            adj.set_value(max(0.0, bounds.get_y() - adj.get_page_size() / 3))

    def focus_last(self):
        """Put the keyboard back on the row whose Card just closed."""
        row = getattr(self, '_last_row', None)
        if row is not None and row.get_mapped():
            row.grab_focus()

    def _on_row_activated(self, _list, row):
        self._last_row = row
        root = self._pane.get_root() if self._pane is not None else None
        if root is not None and hasattr(root, 'show_family_card'):
            root.show_family_card(row.record['id'], self._pane)
