"""family_read.py — Read the difference: one verse down the Line.

The third view of The Bible Family Tree (decided 2026-09-25). One verse in
every English Bible the data knows and the reader has, from word for word at
the top to free at the bottom, so the spectrum is something read, not a
number. The Bibles installed, by default; with All Bibles, one the app can
install but the reader lacks keeps its place as a quiet row that offers the
install. Above them, the Greek or Hebrew with a
gloss under each word, when the interlinear is installed.

It opens at the verse being read; a reference field, ‹ › and a few verses
that show the spread well move it.
"""

import difflib
import re
import threading

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk, Pango

import bible_family
import content
import interlinear_data
import settings
import sword_bridge
from a11y import set_accessible_label
from family_card import paint_track, place_sentences, redraw_on_contrast
from family_line import COLUMN_MAX, STACK_BELOW, _Menu, line_group
from gtk_utils import clear_children
from i18n import _, book_label

#: The name column: narrower than the Line's, the verse needs the room.
NAME_W = 200
#: Verses that show the spread well, as quick picks under the field.
SHOWCASE = (('John', 3, 16), ('Psalms', 23, 1), ('Romans', 3, 23),
            ('Genesis', 1, 1), ('Philippians', 2, 6))
_REF_RE = re.compile(r'^(.+?)\s+(\d+)(?::(\d+))?$')
#: Where the New Testament starts in the app's 66 books.
_FIRST_NT = 39


def _books():
    import window           # at call time: window imports the panes
    return window.BOOKS


def readable(book):
    """Whether the view can show a verse of `book`: one of the 66."""
    return book in _books()


def parse_reference(text):
    """`John 3:16`, `jn 3`, `Juan 3:16` → (book, chapter, verse), clamped to
    the book, or None. A chapter with no verse means its first."""
    m = _REF_RE.match(text.strip())
    if not m:
        return None
    from overlays import match_book
    book = match_book(m.group(1).strip().lower().replace(' ', ''), _books())
    if book is None:
        return None
    chapter = max(1, min(int(m.group(2)), sword_bridge.chapter_count(book)))
    verse = max(1, min(int(m.group(3) or 1),
                       sword_bridge.verse_count(book, chapter)))
    return book, chapter, verse


def step(ref, delta):
    """The verse before (-1) or after (+1) `ref`, across chapters and books;
    `ref` itself at either end of the Bible."""
    book, chapter, verse = ref
    books = _books()
    verse += delta
    if verse < 1:
        chapter -= 1
        if chapter < 1:
            i = books.index(book) - 1
            if i < 0:
                return ref
            book = books[i]
            chapter = sword_bridge.chapter_count(book)
        verse = sword_bridge.verse_count(book, chapter)
    elif verse > sword_bridge.verse_count(book, chapter):
        verse, chapter = 1, chapter + 1
        if chapter > sword_bridge.chapter_count(book):
            i = books.index(book) + 1
            if i >= len(books):
                return ref
            book, chapter = books[i], 1
    return book, chapter, verse


def app_ref(module, book, chapter, verse):
    """(book, chapter, verse) in the app's numbering from a verse as
    `module` numbers it. A Vulgate psalm counts its title as verses 1-2, so
    its "amplius lava me" is verse 4 there and the KJV's verse 2. A title
    (app verse 0) or no verse at all reads from the first verse."""
    import annotations
    return book, chapter, max(1, annotations.app_verse(module, book, chapter,
                                                       verse) or 1)


def ref_label(ref):
    return f'{book_label(ref[0])} {ref[1]}:{ref[2]}'


def rows_for(ref, installed):
    """[(record, module)] for the verse `ref`, in the Line's order: every
    Bible in the data with an installed text (`module`), and every one the
    app can install whose scope holds the verse (`module` None)."""
    nt = _books().index(ref[0]) >= _FIRST_NT
    rows = []
    for record in bible_family.translations():
        module = bible_family.installed_module(record['id'], installed)
        if module is None:
            scope = record.get('scope')
            if (not record.get('installable') or scope == 'partial'
                    or scope == ('ot' if nt else 'nt')):
                continue
        rows.append((record, module))

    def key(row):
        spot = bible_family.place_of(row[0])
        return (line_group(spot)[0], spot.value if spot else 0.0,
                row[0]['name'].lower())
    rows.sort(key=key)
    return rows


def _word_key(token):
    """What a word is compared by: its letters, whatever its case or the
    punctuation around it ("World," and "world" are one word)."""
    return re.sub(r'\W', '', token.lower())


def marked(text, before):
    """`text` as Pango markup with the words it shares with `before` faded,
    so the words that differ from the Bible above keep full ink. Word by
    word, in order: a moved word counts as a difference. With no `before`
    (the first Bible) nothing fades."""
    tokens = re.findall(r'\S+|\s+', text)
    if not before:
        return GLib.markup_escape_text(text)
    words = [(i, _word_key(t)) for i, t in enumerate(tokens)
             if not t.isspace() and _word_key(t)]
    prior = [_word_key(t) for t in before.split() if _word_key(t)]
    shared = set()
    matcher = difflib.SequenceMatcher(None, prior, [k for _i, k in words],
                                      autojunk=False)
    for block in matcher.get_matching_blocks():
        for j in range(block.b, block.b + block.size):
            shared.add(words[j][0])
    out = []
    for i, t in enumerate(tokens):
        esc = GLib.markup_escape_text(t)
        out.append(f'<span alpha="58%">{esc}</span>' if i in shared else esc)
    return ''.join(out)


def gloss_text(gloss):
    """(what the gloss line shows, whether it is the object marker). TAHOT
    glosses את, which marks the definite object and has no English, as
    "<obj.>": jargon to a reader, so it leaves the line."""
    if '<obj.>' not in gloss:
        return gloss, False
    return gloss.replace('<obj.>', '').strip(), True


def verse_text(module, ref):
    """The verse's words in `module`, or ''. Safe off the UI thread, as the
    compare popover's fetch is."""
    book, chapter, verse = ref
    want = sword_bridge.map_target_verse(module, book, chapter, verse)
    html = next((h for v, h in content.load_chapter(module, book, chapter)
                 if v == want), '')
    return sword_bridge.plain_text(html).strip()


class _Row(Gtk.ListBoxRow):
    """One Bible: name, year and track on the left; its verse on the right,
    or the offer to install it."""

    def __init__(self, record, module, reading, on_install):
        super().__init__()
        self.record = record
        self.module = module
        self.spot = bible_family.place_of(record)
        self._reading = reading
        self.empty = False      # an installed text without this verse
        self.plain = ''

        # No side margins: the list has them, so each row's rule ends where
        # the card of the original above does.
        self._box = Gtk.Box(spacing=16)
        self._box.set_margin_top(10)
        self._box.set_margin_bottom(10)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_size_request(NAME_W, -1)
        # The track expands within the column only: its hexpand would
        # otherwise reach the column, which then took a different share of
        # every row and the verses started at different places.
        left.set_hexpand(False)
        left.set_valign(Gtk.Align.START)
        self._left = left
        # Two lines before it is cut: "King James Version (1769…" hid the
        # year that tells the two KJVs apart.
        name = Gtk.Label(label=record['name'], xalign=0, wrap=True, lines=2)
        name.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(1)
        name.add_css_class('family-line-name')
        if reading:
            name.add_css_class('accent')
        if name.create_pango_layout(
                record['name']).get_pixel_size()[0] > 2 * NAME_W:
            name.set_tooltip_text(record['name'])
        left.append(name)
        # The year and the track on one line: stacked, the names took more
        # height than the verses, and five Bibles filled a screen.
        facts = Gtk.Box(spacing=10)
        # Four figures wide in every row, so every track starts at one x.
        year = Gtk.Label(label=str(record['year']), xalign=0, width_chars=4)
        year.add_css_class('family-line-meta')
        year.add_css_class('numeric')
        facts.append(year)
        if self.spot is not None:
            track = Gtk.DrawingArea(hexpand=True)
            track.set_content_width(100)
            track.set_content_height(12)
            track.set_valign(Gtk.Align.CENTER)
            spot = self.spot
            track.set_draw_func(lambda a, cr, w, h: paint_track(
                cr, w, h, spot, a.get_color(), pad=5.0, r=3.5))
            redraw_on_contrast(track)
            facts.append(track)
        left.append(facts)
        self._box.append(left)

        if module is not None:
            self.text = Gtk.Label(xalign=0, wrap=True, hexpand=True)
            self.text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.text.set_valign(Gtk.Align.START)
            self.text.add_css_class('family-read-verse')
            self._box.append(self.text)
        else:
            self.text = None
            install = Gtk.Button(label=_('Install to read it here'))
            install.add_css_class('flat')
            install.add_css_class('family-read-install')
            install.set_halign(Gtk.Align.START)
            install.set_valign(Gtk.Align.START)
            install.connect('clicked',
                            lambda _b: on_install(record['installable'][0]))
            self._box.append(install)
        self.set_child(self._box)
        self._speak('')

    def set_text(self, text):
        """Its verse, once fetched. A Bible without it (a text of part of
        the Bible) leaves the list: see FamilyRead's filter."""
        self.plain = text
        self.text.set_label(text)
        self.empty = not text
        self._speak(text)

    def show_marks(self, before):
        """Fade the words shared with `before`, the verse of the Bible above;
        None shows the verse plain."""
        self.text.set_markup(marked(self.plain, before))

    def _speak(self, text):
        where = ' '.join(place_sentences(self.record))
        if self.module is None:
            tail = _('Not installed.')
        else:
            tail = text
            if self._reading:
                tail = _('You are reading this.') + ' ' + tail
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ['{}, {}. {} {}'.format(self.record['name'], self.record['year'],
                                    where, tail)])

    def set_stacked(self, stacked):
        self._box.set_orientation(Gtk.Orientation.VERTICAL if stacked
                                  else Gtk.Orientation.HORIZONTAL)
        self._box.set_spacing(6 if stacked else 16)
        self._left.set_size_request(-1 if stacked else NAME_W, -1)


class FamilyRead:
    """The pane subsystem for Read the difference."""

    def __init__(self, pane=None):
        self._pane = pane
        self.ref = None
        self._rows: list[_Row] = []
        self._stacked = False
        self._fetch_id = 0
        self._last_row = None
        self._rows_key = None
        self._build()

    @property
    def widget(self):
        return self._root

    # ── construction ─────────────────────────────────────────────────────

    def _build(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Wraps: in a narrow pane, and in Russian, one row of controls set
        # the view wider than the pane and cut its right side off.
        bar = Adw.WrapBox(child_spacing=6, line_spacing=6)
        bar.set_margin_start(14)
        bar.set_margin_end(14)
        bar.set_margin_top(8)
        self._entry = Gtk.Entry(placeholder_text=_('John 3:16'))
        self._entry.set_width_chars(14)
        set_accessible_label(self._entry, _('Verse to read'))
        self._entry.connect('activate', self._on_entry)
        where = Gtk.Box(spacing=6)
        where.append(self._entry)
        nav = Gtk.Box()
        nav.add_css_class('linked')
        prev = Gtk.Button(icon_name='scriptura-go-previous-symbolic')
        prev.set_tooltip_text(_('Previous verse'))
        set_accessible_label(prev, _('Previous verse'))
        prev.connect('clicked', lambda _b: self._step(-1))
        nxt = Gtk.Button(icon_name='scriptura-go-next-symbolic')
        nxt.set_tooltip_text(_('Next verse'))
        set_accessible_label(nxt, _('Next verse'))
        nxt.connect('clicked', lambda _b: self._step(1))
        nav.append(prev)
        nav.append(nxt)
        where.append(nav)
        bar.append(where)
        # Installed by default: a reader with ten Bibles met forty offers
        # to install between them (decided 2026-09-25).
        self._show_all = settings.get('family_read_rows') == 'all'
        self._rows_menu = _Menu(
            _('Availability'),
            [('installed', _('Installed')), ('all', _('All Bibles'))],
            self._set_rows)
        self._rows_menu.set_margin_start(6)
        if self._show_all:
            self._rows_menu.pick('all')
        bar.append(self._rows_menu)
        self._marks_btn = Gtk.ToggleButton(label=_('Mark differences'))
        self._marks_btn.add_css_class('flat')
        # A choice within the view, set like the Family's arrangements: a
        # filled button here was the heaviest thing on the page.
        self._marks_btn.add_css_class('family-pill')
        self._marks_btn.set_valign(Gtk.Align.CENTER)
        self._marks_btn.set_tooltip_text(
            _('Fade the words each Bible shares with the one above it (the '
              'first, with the one below), so the words that differ stand '
              'out'))
        self._marks_btn.set_active(settings.get('family_read_marks')
                                   is not False)
        self._marks_btn.connect('toggled', self._on_marks)
        bar.append(self._marks_btn)
        box.append(_clamped(bar))

        picks = Adw.WrapBox(child_spacing=2, line_spacing=0)
        picks.set_margin_start(14)
        picks.set_margin_end(14)
        try_label = Gtk.Label(label=_('Try:'))
        try_label.add_css_class('family-line-meta')
        try_label.set_margin_end(4)
        picks.append(try_label)
        for ref in SHOWCASE:
            b = Gtk.Button(label=ref_label(ref))
            b.add_css_class('flat')
            b.add_css_class('family-read-pick')
            b.connect('clicked', lambda _b, r=ref: self.show_verse(*r))
            picks.append(b)
        box.append(_clamped(picks))

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._source = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                               spacing=6)
        self._source.set_margin_start(14)
        self._source.set_margin_end(14)
        self._source.set_margin_top(12)
        self._source.set_margin_bottom(4)
        page.append(self._source)

        self._list = Gtk.ListBox()
        self._list.add_css_class('family-line-list')
        self._list.add_css_class('family-read-list')
        self._list.set_margin_start(14)
        self._list.set_margin_end(14)
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.set_filter_func(
            lambda row: not row.empty
            and (self._show_all or row.module is not None))
        self._list.set_header_func(self._header)
        self._list.connect('row-activated', self._on_row_activated)
        set_accessible_label(self._list, _('One verse in English Bibles, '
                                           'from word for word to free'))
        self._empty = Gtk.Label(
            label=_('No English Bible you have installed is in the Family '
                    'Tree. Choose All Bibles to see the ones you can '
                    'install.'),
            wrap=True, justify=Gtk.Justification.CENTER)
        self._empty.add_css_class('dim-label')
        self._empty.set_margin_top(24)
        self._empty.set_margin_start(14)
        self._empty.set_margin_end(14)
        self._list.set_placeholder(self._empty)
        page.append(self._list)

        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER,
                                Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_child(_clamped(page))
        box.append(self._scroll)

        self._root = Adw.BreakpointBin()
        self._root.set_size_request(280, 200)
        self._root.set_child(box)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(
            f'max-width: {STACK_BELOW}sp'))
        narrow.connect('apply', lambda _b: self._set_stacked(True))
        narrow.connect('unapply', lambda _b: self._set_stacked(False))
        self._root.add_breakpoint(narrow)

    # ── the page's calls ─────────────────────────────────────────────────

    def render(self):
        """Rebuild the rows for what is installed now, at the same verse and
        the same place in the list: a Bible just installed from its row
        shows its verse where the reader left it."""
        if self.ref is None:
            self.ref = self._reading_verse()
        self._show(keep_place=True)

    def follow_reading(self):
        """Turn to the verse being read beside this pane."""
        self.ref = self._reading_verse()
        self._show()

    def show_verse(self, book, chapter, verse):
        self.ref = (book, chapter, verse)
        self._show()

    def focus_last(self):
        """Put the keyboard back on the row whose Card just closed."""
        row = self._last_row
        if row is not None and row.get_mapped():
            row.grab_focus()

    # ── state ────────────────────────────────────────────────────────────

    def _reading_verse(self):
        """The verse being read: in the other pane when it shows a Bible,
        else where this pane was before it turned to the Family Tree. John
        3:16 when neither has one of the 66 books."""
        pane = self._pane
        root = pane.get_root() if pane is not None else None
        for other in (getattr(root, 'pane1', None),
                      getattr(root, 'pane2', None)):
            if (other is not None and other is not pane
                    and other.get_visible() and other._is_verse_navigable()
                    and other.book in _books()):
                verses = other.current_verses()
                verse = (verses[0] if verses
                         else other._find_topmost_visible_verse())
                return app_ref(other.module, other.book, other.chapter,
                               verse)
        book = getattr(pane, 'book', None)
        if book in _books():
            return app_ref(getattr(pane, '_came_from', None), book,
                           pane.chapter,
                           getattr(pane, '_selected_verse', None))
        return SHOWCASE[0]

    def _on_entry(self, entry):
        ref = parse_reference(entry.get_text())
        if ref is None:
            entry.add_css_class('error')
            GLib.timeout_add(600, lambda: entry.remove_css_class('error')
                             or GLib.SOURCE_REMOVE)
            return
        self.show_verse(*ref)

    def _step(self, delta):
        if self.ref is not None:
            self.show_verse(*step(self.ref, delta))

    def _set_rows(self, key):
        self._show_all = key == 'all'
        settings.put('family_read_rows', key)
        # The menu's pick() at build time comes before the list exists.
        if hasattr(self, '_list'):
            self._list.invalidate_filter()
            self._list.invalidate_headers()

    def _on_marks(self, btn):
        settings.put('family_read_marks', btn.get_active())
        self._apply_marks()

    def _apply_marks(self):
        """Each verse against the one shown above it. The Bibles offered
        for install have no verse, so they never come between two that do,
        whichever the menu shows."""
        on = self._marks_btn.get_active()
        shown = [r for r in self._rows if r.module is not None and not r.empty]
        for i, row in enumerate(shown):
            # The first has none above it: it is read against the one below,
            # or it alone kept full ink and looked like the one that differs.
            other = shown[i - 1] if i else (shown[1] if len(shown) > 1
                                            else None)
            row.show_marks(other.plain if on and other else None)

    def _set_stacked(self, stacked):
        self._stacked = stacked
        for row in self._rows:
            row.set_stacked(stacked)

    # ── building the page for one verse ──────────────────────────────────

    def _show(self, keep_place=False):
        ref = self.ref
        self._entry.set_text(ref_label(ref))
        self._show_source(ref)
        installed = list(getattr(self._pane, '_names', []) or [])
        from family_tree import reading_module
        reading = reading_module(self._pane)
        # None when no Bible the data knows is being read: nothing is marked.
        node = bible_family.node_for_module(reading) if reading else None
        reading_id = node['id'] if node else None
        rows = rows_for(ref, installed)
        key = ([(r['id'], m) for r, m in rows], reading_id)
        # The same Bibles as the verse before (the next verse, a re-render
        # for a theme): keep the rows and the reader's place, and change
        # only the words. Rebuilding fifty rows cost ~90ms a step.
        if key != self._rows_key:
            self._rows_key = key
            # remove_all: a child walk meets the row headers too, which are
            # the list's children but not its to remove.
            self._list.remove_all()
            self._rows = []
            for record, module in rows:
                row = _Row(record, module, record['id'] == reading_id,
                           self._install)
                row.set_stacked(self._stacked)
                self._rows.append(row)
                self._list.append(row)
            if not keep_place:
                self._scroll.get_vadjustment().set_value(0)

        self._fetch_id += 1
        fetch_id = self._fetch_id
        wanted = [(row, row.module) for row in self._rows if row.module]

        def fetch():
            texts = []
            for row, module in wanted:
                # A later verse asked for: stop, and leave SWORD to its fetch.
                if fetch_id != self._fetch_id:
                    return
                texts.append((row, verse_text(module, ref)))
            GLib.idle_add(fill, texts)

        def fill(texts):
            if fetch_id == self._fetch_id:
                for row, text in texts:
                    row.set_text(text)
                self._apply_marks()
                self._list.invalidate_filter()
                self._list.invalidate_headers()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=fetch, daemon=True).start()

    def _show_source(self, ref):
        """The Greek or Hebrew with its gloss, or the way to install it."""
        clear_children(self._source)
        hebrew = _books().index(ref[0]) < _FIRST_NT
        name = interlinear_data.HEBREW if hebrew else interlinear_data.GREEK
        if not interlinear_data.is_installed(name):
            door = Gtk.Button(
                label=_('See the Hebrew behind these: install the Hebrew '
                        'interlinear') if hebrew
                else _('See the Greek behind these: install the Greek '
                       'interlinear'))
            door.add_css_class('flat')
            door.add_css_class('family-read-install')
            door.set_halign(Gtk.Align.START)
            door.connect('clicked', lambda _b: self._install(''))
            self._source.append(door)
            return
        words = [w for w in interlinear_data.load_chapter(name, ref[0],
                                                          ref[1])
                 if w.verse == ref[2]]
        if not words:
            return
        kicker = Gtk.Label(
            label=_('The Hebrew, read right to left, with a word-by-word '
                    'gloss') if hebrew
            else _('The Greek, with a word-by-word gloss'), xalign=0,
            wrap=True)
        # Wrapped: on one line, in Russian in a narrow pane, it set the
        # column wider than the pane and cut off the card beneath it.
        kicker.add_css_class('family-card-kicker')
        self._source.append(kicker)
        # Centred in its card, each line of words (decided 2026-09-25).
        wrap = Adw.WrapBox(child_spacing=12, line_spacing=8, align=0.5)
        if hebrew:
            # Right to left: the first word at the right, lines filling
            # leftward, as the Hebrew is read.
            wrap.set_direction(Gtk.TextDirection.RTL)
        glosses = []
        for w in words:
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            surface = Gtk.Label(label=w.surface, xalign=0)
            surface.add_css_class('family-read-hebrew' if hebrew
                                  else 'family-read-greek')
            cell.append(surface)
            shown, marker = gloss_text(w.gloss)
            if marker:
                cell.set_tooltip_text(_('Marks the definite object; English '
                                        'does not translate it'))
            glosses.append(shown)
            # A space keeps an emptied gloss line its height.
            gloss = Gtk.Label(label=shown or ' ', xalign=0)
            gloss.add_css_class('interlinear-gloss')
            if shown.startswith('<') and shown.rstrip('.,;·').endswith('>'):
                gloss.add_css_class('interlinear-gloss-implicit')
            cell.append(gloss)
            wrap.append(cell)
        set_accessible_label(wrap, ' '.join(g for g in glosses if g))
        # The original in a card of its own above the Bibles, as the
        # prototype drew it (2026-09-25).
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class('family-read-source')
        card.append(wrap)
        self._source.append(card)

    def _header(self, row, before):
        group = line_group(row.spot)
        if before is not None and line_group(before.spot) == group:
            row.set_header(None)
            return
        order, kind = group
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if kind == 'none':
            head = Gtk.Label(label=_('Not placed'), xalign=0)
            head.add_css_class('family-line-head')
            box.append(head)
        else:
            zone = _(bible_family.ZONES[order // 2][1])
            if before is None or line_group(before.spot)[0] // 2 != order // 2:
                head = Gtk.Label(label=zone, xalign=0)
                head.add_css_class('family-line-head')
                box.append(head)
            if order % 2:
                sub = Gtk.Label(label=_('Described by their makers as '
                                        '“{zone}”').format(zone=zone),
                                xalign=0)
                sub.add_css_class('family-line-subhead')
                box.append(sub)
        row.set_header(box)

    # ── doors ────────────────────────────────────────────────────────────

    def _install(self, query):
        root = self._pane.get_root() if self._pane is not None else None
        if root is not None and hasattr(root, 'open_bibles'):
            root.open_bibles(query)

    def _on_row_activated(self, _list, row):
        self._last_row = row
        root = self._pane.get_root() if self._pane is not None else None
        if root is not None and hasattr(root, 'show_family_card'):
            root.show_family_card(row.record['id'], self._pane)


def _clamped(child):
    clamp = Adw.Clamp(maximum_size=COLUMN_MAX, tightening_threshold=COLUMN_MAX)
    clamp.set_child(child)
    return clamp
