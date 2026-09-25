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
from family_card import paint_track, redraw_on_contrast
from i18n import _, ngettext

#: The name column's width: the tracks start where it ends, in every row
#: and in the axis above them, and fill the rest of the column.
NAME_W = 300
ROW_SPACING = 16
#: The Line reads as a page, not a spreadsheet: past this it stays centred.
COLUMN_MAX = 860
#: Below this width the rows stack: name above, track below.
STACK_BELOW = 560


def _clamped(child):
    """`child` held to the Line's column, centred when the pane is wider."""
    clamp = Adw.Clamp(maximum_size=COLUMN_MAX, tightening_threshold=COLUMN_MAX)
    clamp.set_child(child)
    return clamp


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

        self._box = Gtk.Box(spacing=ROW_SPACING)
        self._box.set_margin_start(14)
        self._box.set_margin_end(14)
        self._box.set_margin_top(7)
        self._box.set_margin_bottom(7)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_size_request(NAME_W, -1)
        self._text = text
        # Both labels ask for almost no width, so the name column is exactly
        # NAME_W in every row and every track starts at the same x.
        self._name = Gtk.Label(label=record['name'], xalign=0)
        self._name.set_ellipsize(Pango.EllipsizeMode.END)
        self._name.set_max_width_chars(1)
        self._name.add_css_class('family-line-name')
        # Four names outrun the column; the whole name on hover. (A screen
        # reader hears it whole from the row's own label.)
        if self._name.create_pango_layout(
                record['name']).get_pixel_size()[0] > NAME_W:
            self._name.set_tooltip_text(record['name'])
        text.append(self._name)
        self._meta = Gtk.Label(xalign=0)
        self._meta.set_ellipsize(Pango.EllipsizeMode.END)
        self._meta.set_max_width_chars(1)
        self._meta.add_css_class('family-line-meta')
        text.append(self._meta)
        self._box.append(text)

        self._track = Gtk.DrawingArea(hexpand=True)
        self._track.set_content_width(160)
        self._track.set_content_height(18)
        self._track.set_valign(Gtk.Align.CENTER)
        if self.spot is not None:
            spot = self.spot
            self._track.set_draw_func(lambda a, cr, w, h: paint_track(
                cr, w, h, spot, a.get_color(), pad=6.0, r=4.0))
            redraw_on_contrast(self._track)
        self._box.append(self._track)
        self.set_child(self._box)

    def refresh(self, installed, reading):
        self.installed = installed
        self.reading = reading
        tradition = _(bible_family.TRADITIONS.get(
            self.record.get('tradition'), ''))
        # The year it is plotted at; its full dates are on the Card. A long
        # date line ("2016 (as Berean Study Bible) · 2022 (renamed) · …")
        # crowded the row and pushed "Installed" out of sight.
        parts = [str(self.record['year']), tradition]
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
        self._box.set_spacing(4 if stacked else ROW_SPACING)
        self._text.set_size_request(-1 if stacked else NAME_W, -1)

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


class _Menu(Gtk.Box):
    """One filter as a quiet button that opens its choices. At rest it
    names the filter ("All traditions"); once narrowed it names the choice
    and grows a × that puts the filter back. `choices` is [(key, label)],
    the first being the unfiltered one; `on_pick(key)` runs on a choice."""

    def __init__(self, name, choices, on_pick, clear_words='', shown=None):
        """`name` is what the filter is ("Tradition"), for screen readers,
        which would otherwise hear only "Catholic". `shown` formats the
        visible label from the choice (the sort's "Sort: {choice}")."""
        super().__init__()
        self.add_css_class('linked')
        self.add_css_class('family-filter')
        self._name = name
        self._choices = choices
        self._on_pick = on_pick
        self._shown = shown or '{choice}'
        self._key = choices[0][0]

        self._button = Gtk.MenuButton()
        self._button.add_css_class('flat')
        self._label = Gtk.Label()
        inner = Gtk.Box(spacing=4)
        inner.append(self._label)
        inner.append(Gtk.Image.new_from_icon_name('scriptura-pan-down-symbolic'))
        self._button.set_child(inner)
        pop = Gtk.Popover()
        pop.add_css_class('menu')
        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        items.set_margin_top(4)
        items.set_margin_bottom(4)
        first = None
        self._checks = {}
        for key, label in choices:
            check = Gtk.CheckButton(label=label)
            if first is None:
                first = check
                check.set_active(True)
            else:
                check.set_group(first)
            check.connect('toggled', self._on_toggled, key)
            self._checks[key] = check
            items.append(check)
        pop.set_child(items)
        self._pop = pop
        self._button.set_popover(pop)
        self.append(self._button)

        self._clear = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        self._clear.add_css_class('flat')
        self._clear.set_tooltip_text(clear_words)
        set_accessible_label(self._clear, clear_words)
        self._clear.connect('clicked', self._on_clear)
        self._clear.set_visible(False)
        self._clearable = bool(clear_words)
        self.append(self._clear)
        self._show()

    @property
    def key(self):
        return self._key

    def pick(self, key):
        """Choose `key`, as a click on it would."""
        self._checks[key].set_active(True)

    def clear(self):
        """Back to the first, unfiltered choice."""
        self.pick(self._choices[0][0])

    def _on_clear(self, _button):
        # The × hides itself once the filter is clear; the keyboard goes
        # back to the menu rather than vanishing with it.
        self.clear()
        self._button.grab_focus()

    def _on_toggled(self, check, key):
        if not check.get_active():
            return
        self._key = key
        self._show()
        self._pop.popdown()
        self._on_pick(key)

    def _show(self):
        label = dict(self._choices)[self._key]
        self._label.set_label(self._shown.format(choice=label))
        narrowed = self._key != self._choices[0][0]
        self._clear.set_visible(self._clearable and narrowed)
        if narrowed:
            self.add_css_class('narrowed')
        else:
            self.remove_css_class('narrowed')
        set_accessible_label(self._button, _('{filter}: {choice}').format(
            filter=self._name, choice=label))


class FamilyLine:
    """The pane subsystem for The Bible Family Tree's Line."""

    def __init__(self, pane=None):
        self._pane = pane
        self._rows: list[_Row] = []
        self._availability = 'all'
        self._tradition = ''
        self._era = -1
        self._query = ''
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

        bar = Gtk.Box(spacing=8)
        bar.set_margin_start(14)
        bar.set_margin_end(14)
        bar.set_margin_top(8)
        bar.set_margin_bottom(4)
        filters = Adw.WrapBox(child_spacing=6, line_spacing=4, hexpand=True)
        # Find a Bible by name, abbreviation or year: 126 rows are too many
        # to scan for one.
        self._search = Gtk.SearchEntry(placeholder_text=_('Find a Bible'))
        self._search.set_width_chars(12)
        set_accessible_label(self._search, _('Find a Bible'))
        self._search.connect('search-changed', self._on_search)
        self._search.connect('stop-search', lambda e: e.set_text(''))
        filters.append(self._search)
        self._avail_menu = _Menu(
            _('Availability'),
            [('all', _('All Bibles')), ('installed', _('Installed')),
             ('can', _('Can install'))], self._set_availability,
            clear_words=_('Show every Bible again'))
        self._trad_menu = _Menu(
            _('Tradition'),
            [('', _('All traditions'))]
            + [(k, _(t)) for k, t in bible_family.TRADITION_CHIPS],
            self._set_tradition,
            clear_words=_('Show every tradition again'))
        self._era_menu = _Menu(
            _('Era'),
            [(-1, _('All eras'))]
            + [(i, _(label)) for i, (_lo, _hi, label)
               in enumerate(bible_family.ERAS)], self._set_era,
            clear_words=_('Show every era again'))
        for m in (self._avail_menu, self._trad_menu, self._era_menu):
            filters.append(m)
        bar.append(filters)
        self._bar = bar
        self._filters = filters
        self._sort_menu = _Menu(
            _('Sort'),
            [('place', _('Place on the Line')), ('year', _('Year')),
             ('name', _('Name'))], self._set_sort,
            shown=_('Sort: {choice}'))
        self._sort_menu.set_valign(Gtk.Align.START)
        bar.append(self._sort_menu)
        box.append(_clamped(bar))

        # The axis over the tracks: the ends of the Line, lined up with the
        # track column so the eye reads straight down.
        self._axis = Gtk.Box(spacing=ROW_SPACING)
        self._axis.add_css_class('family-line-axis')
        self._axis.set_margin_start(14)
        self._axis.set_margin_end(14)
        spacer = Gtk.Box()
        spacer.set_size_request(NAME_W, -1)
        self._axis.append(spacer)
        ends = Gtk.Box(hexpand=True)
        ends.append(Gtk.Label(label=_('Word for word'), xalign=0,
                              hexpand=True))
        ends.append(Gtk.Label(label=_('Free'), xalign=1))
        self._axis.append(ends)
        self._axis_clamp = _clamped(self._axis)
        box.append(self._axis_clamp)

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
        self._scroll.set_child(_clamped(self._list))
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
        from family_tree import reading_module
        return reading_module(self._pane)

    def _on_search(self, entry):
        self._query = entry.get_text()
        self._refilter()

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
        # Narrow: the sort joins the filters' wrapping row, so they share
        # the width instead of each taking a line of its own beside it.
        # Wide: it stands apart at the right.
        sort = self._sort_menu
        if stacked and sort.get_parent() is self._bar:
            self._bar.remove(sort)
            self._filters.append(sort)
        elif not stacked and sort.get_parent() is self._filters:
            self._filters.remove(sort)
            self._bar.append(sort)
        self._stacked = stacked
        for row in self._rows:
            row.set_stacked(stacked)
        self._axis_clamp.set_visible(not stacked)

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
        if self._query and not bible_family.matches(row.record, self._query):
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

    def show_node(self, node_id):
        """Bring one Bible's row into view and give it the keyboard. Filters
        that hide it are cleared first: a row asked for by name must show."""
        self._ensure_rows()
        row = next((r for r in self._rows if r.record['id'] == node_id), None)
        if row is None:
            return
        if not self._filter(row):
            self._search.set_text('')
            for menu in (self._avail_menu, self._trad_menu, self._era_menu):
                menu.clear()
            self._query, self._availability = '', 'all'
            self._tradition, self._era = '', -1
            self._refilter()
        self._last_row = row
        row.grab_focus()
        vadj = self._scroll.get_vadjustment()

        def go():
            self._scroll_to(row)
            return GLib.SOURCE_REMOVE

        if vadj.get_page_size() > 0:
            GLib.idle_add(go)
            return
        handler = None

        def on_changed(_adj):
            # A pane just turned to the Family Tree has no page yet, and a
            # scroll before it has one clamps to the top.
            if vadj.get_page_size() > 0:
                vadj.disconnect(handler)
                GLib.idle_add(go)
        handler = vadj.connect('changed', on_changed)

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
