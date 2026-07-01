"""archaeology_reader.py — the "Scripture in Stone" pane subsystem.

Renders the bundled archaeology gallery (archaeology_bridge) as a short
illustrated book: a frontispiece, then artifacts grouped into era "chapters"
in biblical sequence. Each artifact is a plate (image · title · provenance ·
caption) followed by tappable verse chips; clicking a chip drives the Bible
pane to that passage via the pane's word-study navigation callback (the same
channel a Strong's link uses → window._go_to).

Layout is magazine-style: a comfortable narrow measure for text, with images
allowed to run wider — so a wide / single pane reads like long-form rather
than a thin centred column. Prose is selectable (native right-click Copy), and
the document scales with the app's reading font size (the .stone-* sizes are
em-relative, so one base size on .stone-page scales the whole thing).

Unlike the imagery/catena readers it is NOT verse-keyed — it's a standalone
document you open and read, so it ignores the partnered Bible's navigation and
renders once. A Contents button jumps between chapters.
"""

import logging
import math
import re

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Graphene, GdkPixbuf

import archaeology_bridge

_log = logging.getLogger('scriptura.archaeology')

# Cairo font-face slant/weight aliases for the map's text overlays.
cairo_normal = cairo.FONT_SLANT_NORMAL
cairo_italic = cairo.FONT_SLANT_ITALIC
cairo_book = cairo.FONT_WEIGHT_NORMAL
cairo_bold = cairo.FONT_WEIGHT_BOLD

_TEXT_W = 680    # comfortable reading measure
_IMG_W = 920     # images run wider than the text

# Bounds of the bundled biblical-world base map (the crop in build/data).
_MAP_BOUNDS = (11.0, 50.0, 24.0, 43.0)   # lon_min, lon_max, lat_min, lat_max

# Faint orientation labels on the find-spot map (lat, lon, text). Seas are set
# in italic, land regions in spaced uppercase, key cities in plain small caps —
# enough to read the geography at a glance without competing with the markers.
_SEA_LABELS = [
    (34.0, 18.5, 'Mediterranean Sea'),
    (25.6, 35.2, 'Red Sea'),
    (28.4, 48.6, 'Persian Gulf'),
]
_REGION_LABELS = [
    (27.2, 30.0, 'EGYPT'),
    (25.8, 44.0, 'ARABIA'),
    (39.2, 32.5, 'ASIA  MINOR'),
    (39.6, 21.8, 'GREECE'),
    (35.6, 41.2, 'MESOPOTAMIA'),
]
_CITY_LABELS = [
    (31.78, 35.23, 'Jerusalem'),
    (36.36, 43.15, 'Nineveh'),
    (32.54, 44.42, 'Babylon'),
]


class ArchaeologyReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._built = False
        self._chapter_anchors: dict[str, Gtk.Widget] = {}
        self._verse_anchors: dict[tuple, Gtk.Widget] = {}
        self._entry_anchors: dict[str, Gtk.Widget] = {}
        self._sections: list[tuple] = []     # (divider, [(plate, search_text)])
        self._apparatus: list[Gtk.Widget] = []  # glossary / further-reading
        self._front = None
        self._scroll_target = None
        self._scroll_tries = 0
        self._map_points: list = []
        self._map_screen: list = []
        self._map_pts_raw: list = []
        self._map_pixbuf = None
        self._map_dialog = None
        self._map_area = None
        self._map_hover = None      # entry under the cursor (hover-to-identify)
        self._map_here = None       # entry being read when the map was opened
        self._map_tick = 0          # frame-clock tick for the "you are here" pulse
        self._tl_dialog = None
        self._tl_area = None
        self._tl_points: list = []
        self._tl_screen: list = []
        self._tl_hover = None
        self._build_widget()

    @property
    def widget(self):
        return self._root

    # ── construction ────────────────────────────────────────────────────────
    def _build_widget(self):
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Slim top bar with a Contents jump menu (the "book" affordance).
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.add_css_class('stone-topbar')
        self._search = Gtk.SearchEntry(placeholder_text=_('Search artifacts'))
        self._search.add_css_class('stone-search')
        self._search.set_hexpand(False)
        self._search.set_max_width_chars(28)
        self._search.connect('search-changed', self._on_search)
        self._contents_btn = Gtk.MenuButton(
            icon_name='view-list-symbolic', tooltip_text=_('Contents'))
        self._contents_btn.add_css_class('flat')
        # Icon-only buttons need an explicit accessible name — a tooltip is
        # not a reliable AT-SPI label for Orca/screen readers.
        self._contents_btn.update_property(
            [Gtk.AccessibleProperty.LABEL], [_('Contents')])
        self._contents_pop = Gtk.Popover()
        self._contents_btn.set_popover(self._contents_pop)
        self._timeline_btn = Gtk.Button(
            icon_name='scriptura-timeline-symbolic',
            tooltip_text=_('Timeline — when they date from'))
        self._timeline_btn.add_css_class('flat')
        self._timeline_btn.update_property(
            [Gtk.AccessibleProperty.LABEL], [_('Timeline')])
        self._timeline_btn.connect('clicked', lambda *_a: self._open_timeline())
        self._map_btn = Gtk.Button(
            icon_name='mark-location-symbolic',
            tooltip_text=_('Map — where these were found'))
        self._map_btn.add_css_class('flat')
        self._map_btn.update_property(
            [Gtk.AccessibleProperty.LABEL], [_('Map')])
        self._map_btn.connect('clicked', lambda *_a: self._open_map())
        bar.append(self._search)
        bar.append(Gtk.Box(hexpand=True))
        bar.append(self._timeline_btn)
        bar.append(self._map_btn)
        bar.append(self._contents_btn)
        self._root.append(bar)

        self._scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self._page.add_css_class('stone-page')
        self._scroller.set_child(self._page)
        self._root.append(self._scroller)

        # Font scaling: the .stone-* sizes are em-relative, so one base
        # font-size on .stone-page scales the whole document. Driven by the
        # app's reading font-size (apply_font_size, called by the pane).
        self._font_provider = Gtk.CssProvider()
        self._page.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Trimmed right-click menu for the read-only prose. GtkLabel's stock
        # selection menu carries inert Cut/Paste/Delete items and can't be
        # pruned via public API, so we suppress it (claim the secondary click)
        # and show our own Copy / Select All popover, wired to the label.
        self._menu_target: Gtk.Label | None = None
        actions = Gio.SimpleActionGroup()
        a_copy = Gio.SimpleAction.new('copy', None)
        a_copy.connect('activate', self._menu_copy)
        a_sel = Gio.SimpleAction.new('select-all', None)
        a_sel.connect('activate', self._menu_select_all)
        actions.add_action(a_copy)
        actions.add_action(a_sel)
        self._root.insert_action_group('stonetext', actions)
        model = Gio.Menu()
        model.append(_('Copy'), 'stonetext.copy')
        model.append(_('Select All'), 'stonetext.select-all')
        self._text_menu = Gtk.PopoverMenu.new_from_model(model)
        self._text_menu.set_has_arrow(False)
        self._text_menu.set_parent(self._root)

    @staticmethod
    def _clamp(child, width):
        c = Adw.Clamp(maximum_size=width, tightening_threshold=int(width * 0.85))
        c.set_child(child)
        return c

    def _label(self, text, css, selectable=False, xalign=0):
        lbl = Gtk.Label(label=text, xalign=xalign, wrap=True)
        lbl.add_css_class(css)
        if selectable:
            lbl.set_selectable(True)
            # A selectable label shows a blinking text caret only while it has
            # focus; making it non-focusable removes the "editable field" look
            # (the caret) while mouse drag-select and right-click Copy still
            # work. This is read-only prose — there's nothing to type into.
            lbl.set_focusable(False)
            gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
            gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            gesture.connect('pressed', self._on_label_secondary, lbl)
            lbl.add_controller(gesture)
            # Same double-click dictionary peek as the reading view.
            if self._pane is not None:
                self._pane._attach_dict_to_label(lbl)
        return lbl

    # ── trimmed Copy / Select All menu ─────────────────────────────────────────
    def _on_label_secondary(self, gesture, _n, x, y, label):
        # Claim the secondary click so GtkLabel's stock menu never opens, then
        # show our own at the cursor.
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._menu_target = label
        ok, pt = label.compute_point(self._root, Graphene.Point().init(x, y))
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = (
            (int(pt.x), int(pt.y), 1, 1) if ok else (0, 0, 1, 1))
        self._text_menu.set_pointing_to(rect)
        self._text_menu.popup()

    def _menu_copy(self, *_):
        lbl = self._menu_target
        if lbl is None:
            return
        ok, start, end = lbl.get_selection_bounds()
        text = lbl.get_text()[start:end] if ok else lbl.get_text()
        lbl.get_clipboard().set(text)

    def _menu_select_all(self, *_):
        if self._menu_target is not None:
            self._menu_target.select_region(0, -1)

    # ── rendering ─────────────────────────────────────────────────────────────
    def render(self):
        """Build the document once (idempotent)."""
        if self._built:
            return
        doc = archaeology_bridge.document()

        self._front = self._clamp(self._frontispiece(doc), _TEXT_W)
        self._page.append(self._front)
        for chap in doc['chapters']:
            if not chap['entries']:
                continue
            divider = self._clamp(
                self._era_divider(chap['title'], chap['intro']), _TEXT_W)
            self._chapter_anchors[chap['id']] = divider
            self._page.append(divider)
            plates: list[tuple] = []
            for entry in chap['entries']:
                plate = self._plate(entry)
                self._page.append(plate)
                self._entry_anchors[entry['image']] = plate
                plates.append((plate, self._search_text(entry)))
                # Map each referenced verse to this plate, so a Bible 'related
                # artifact' marker can scroll the gallery straight to it.
                for r in entry['refs']:
                    self._verse_anchors[(r['book'], r['chapter'], r['verse'])] = plate
            self._sections.append((divider, plates))

        # Closing reference sections (scholarly apparatus).
        if doc['terms']:
            sec = self._clamp(self._glossary_section(doc['terms']), _TEXT_W)
            self._chapter_anchors['_glossary'] = sec
            self._apparatus.append(sec)
            self._page.append(sec)
        if doc['reading']:
            sec = self._clamp(self._reading_section(doc['reading']), _TEXT_W)
            self._chapter_anchors['_reading'] = sec
            self._apparatus.append(sec)
            self._page.append(sec)

        self._build_contents(doc)
        self.apply_font_size(getattr(self._pane, '_font_size', None))
        self._built = True

    def _frontispiece(self, doc):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-front')
        box.append(self._label(doc['title'], 'stone-front-title', selectable=True))
        if doc['subtitle']:
            box.append(self._label(doc['subtitle'], 'stone-front-sub',
                                   selectable=True))
        if doc['body']:
            for para in doc['body'].split('\n\n'):
                box.append(self._label(para.strip(), 'stone-front-body',
                                       selectable=True))
        return box

    def _era_divider(self, title, intro=''):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-era')
        box.append(self._label(title, 'stone-era-title'))
        # De-ruled: chapter/section headers group by whitespace, not a
        # separator (the app's house style — see the UI coherence pass).
        if intro:
            box.append(self._label(intro, 'stone-era-intro', selectable=True))
        return box

    def _glossary_section(self, terms):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-apparatus')
        box.append(self._era_divider(_('Glossary')))
        for t in terms:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            row.add_css_class('stone-term')
            row.append(self._label(t['term'], 'stone-term-name', selectable=True))
            row.append(self._label(t['definition'], 'stone-term-def',
                                   selectable=True))
            box.append(row)
        return box

    def _reading_section(self, reading):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-apparatus')
        box.append(self._era_divider(_('Sources & further reading')))
        for r in reading:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            row.add_css_class('stone-read')
            row.append(self._label(r['title'], 'stone-read-title', selectable=True))
            if r['note']:
                row.append(self._label(r['note'], 'stone-read-note',
                                       selectable=True))
            box.append(row)
        return box

    def _plate(self, entry):
        plate = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        plate.add_css_class('stone-plate')

        pic = Gtk.Picture()
        pic.set_filename(archaeology_bridge.image_path(entry['image']))
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_can_shrink(True)
        pic.set_hexpand(True)
        pic.set_size_request(-1, 420)          # uniform plate band
        pic.set_alternative_text(entry['title'])
        pic.add_css_class('stone-pic')
        # Click to zoom — inscriptions and reliefs reward a closer look.
        click = Gtk.GestureClick()
        click.connect('released', lambda *_a, e=entry: self._zoom(e))
        pic.add_controller(click)
        pic.set_cursor(Gdk.Cursor.new_from_name('pointer', None))
        n_views = 1 + len(entry.get('details', []))
        pic.set_tooltip_text(
            _('Click to enlarge') if n_views == 1
            else ngettext('Click to enlarge — {n} view',
                          'Click to enlarge — {n} views', n_views).format(n=n_views))
        plate.append(self._clamp(pic, _IMG_W))

        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        txt.add_css_class('stone-text')
        txt.append(self._label(entry['title'], 'stone-title', selectable=True))

        meta_bits = [b for b in (entry['place'], entry['date'],
                                 entry['holding']) if b]
        if meta_bits:
            txt.append(self._label(' · '.join(meta_bits), 'stone-meta',
                                   selectable=True))

        if entry.get('provenance'):
            # How the object is known — excavated in context vs. market-bought —
            # is the field's whole point: it shows why a piece earns its place.
            txt.append(self._label(
                _('Provenance · {text}').format(text=entry['provenance']),
                'stone-prov', selectable=True))

        txt.append(self._label(entry['caption'], 'stone-caption', selectable=True))

        if entry.get('details'):
            n = len(entry['details'])
            hint = self._label(
                ngettext('{n} detail closeup — click the image to view',
                         '{n} detail closeups — click the image to view',
                         n).format(n=n),
                'stone-views')
            txt.append(hint)

        if entry['refs']:
            # WrapBox (not a plain HBox): the chip row wraps to new lines on a
            # narrow pane instead of summing every chip's width into one wide
            # min that would clip the whole document.
            chips = Adw.WrapBox(child_spacing=0, line_spacing=6)
            chips.add_css_class('stone-chips')
            lead = self._label(_('Attests'), 'stone-chips-lead')
            lead.set_valign(Gtk.Align.CENTER)
            chips.append(lead)
            for ref in entry['refs']:
                chips.append(self._verse_chip(ref))
            txt.append(chips)

        if entry.get('related'):
            # "See also" — jump to a thematically related artifact in the gallery
            # (a wrapping flow, since titles are long). Turns the list into a web.
            txt.append(self._label(_('See also'), 'stone-chips-lead'))
            flow = Adw.WrapBox(child_spacing=0, line_spacing=6)
            flow.add_css_class('stone-seealso')
            for r in entry['related']:
                flow.append(self._related_chip(r))
            txt.append(flow)

        if entry['credit']:
            txt.append(self._credit(entry))
        plate.append(self._clamp(txt, _TEXT_W))
        return plate

    def _related_chip(self, rel):
        """A chip that jumps to another artifact's plate within the gallery."""
        btn = Gtk.Button(label=rel['title'])
        btn.add_css_class('stone-chip')
        btn.add_css_class('stone-chip-rel')
        # Content-width pill, not stretched to the full cell; ellipsize a long
        # title rather than force the chip (and the document) wider than a
        # narrow pane.
        btn.set_halign(Gtk.Align.START)
        btn.set_can_shrink(True)
        btn.set_tooltip_text(_('Go to {title}').format(title=rel['title']))
        btn.connect('clicked', lambda _b, img=rel['image']: self.scroll_to_entry(img))
        return btn

    def _zoom(self, entry):
        """Open the artifact full-size in a dialog. When the entry has detail
        closeups, present them as a swipeable carousel (full view first, then
        each detail with its own caption). Inscriptions reward the closer look."""
        root = self._root.get_root()
        if root is None:
            return
        meta = ' · '.join(b for b in (entry['place'], entry['date'],
                                      entry['holding']) if b)
        pages = [(entry['image'], meta)]
        pages += [(d['image'], d['caption']) for d in entry.get('details', [])]

        dialog = Adw.Dialog()
        dialog.set_title(entry['title'])
        dialog.set_content_width(1000)
        dialog.set_content_height(800)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        if len(pages) == 1:
            view.set_content(self._zoom_page(*pages[0]))
        else:
            carousel = Adw.Carousel(hexpand=True, vexpand=True)
            for img, cap in pages:
                carousel.append(self._zoom_page(img, cap))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(carousel)
            box.append(Adw.CarouselIndicatorDots(carousel=carousel,
                                                 margin_top=6, margin_bottom=6))
            view.set_content(box)
        dialog.set_child(view)
        dialog.present(root)

    def _zoom_page(self, image, caption):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        pic = Gtk.Picture.new_for_filename(archaeology_bridge.image_path(image))
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_can_shrink(True)
        scroll.set_child(pic)
        box.append(scroll)
        if caption:
            lbl = Gtk.Label(label=caption, xalign=0, wrap=True)
            lbl.add_css_class('stone-caption')
            lbl.add_css_class('stone-zoom-caption')
            box.append(lbl)
        return box

    def _credit(self, entry):
        """The photo credit line — a link to the source (the Commons file page,
        which carries the full attribution and licence) when one is recorded,
        so a reader can click through to verify or learn more."""
        lbl = Gtk.Label(xalign=0, wrap=True)
        lbl.add_css_class('stone-credit')
        if entry.get('source'):
            text = GLib.markup_escape_text(entry['credit'])
            url = GLib.markup_escape_text(entry['source'])
            lbl.set_markup(f'<a href="{url}">{text}</a>')   # opens in browser
        else:
            lbl.set_text(entry['credit'])
            lbl.set_selectable(True)
            lbl.set_focusable(False)
        return lbl

    def _verse_chip(self, ref):
        btn = Gtk.Button(label=ref['label'])
        btn.add_css_class('stone-chip')
        btn.set_can_shrink(True)
        btn.set_tooltip_text(
            _('Open {ref} in the Bible pane').format(ref=ref['label']))
        btn.connect('clicked', lambda _b, r=ref: self._open_ref(r))
        return btn

    def _open_ref(self, ref):
        """Drive the Bible pane to this passage. Reuses the pane's word-study
        navigation callback (→ window._go_to), which updates the global nav and
        loads the partnered Bible pane; the artifact pane itself isn't
        verse-keyed, so it stays put."""
        cb = getattr(self._pane, '_on_word_study_navigate', None)
        if cb:
            cb(ref['book'], ref['chapter'], ref['verse'])

    # ── search / filter ────────────────────────────────────────────────────────
    @staticmethod
    def _search_text(entry):
        """The haystack a plate matches against — everything a reader might
        reasonably type: title, place, date, museum, provenance, caption, the
        verses it attests, and the artifacts it links to."""
        parts = [entry['title'], entry['place'], entry['date'],
                 entry['holding'], entry.get('provenance', ''),
                 entry['caption']]
        parts += [r['label'] for r in entry['refs']]
        parts += [r['title'] for r in entry.get('related', [])]
        return ' '.join(parts).lower()

    def _on_search(self, search):
        q = search.get_text().strip().lower()
        # Frontispiece and the reference sections aren't artifacts — hide them
        # while a query is active so the result list reads clean.
        searching = bool(q)
        if self._front is not None:
            self._front.set_visible(not searching)
        for w in self._apparatus:
            w.set_visible(not searching)
        for divider, plates in self._sections:
            any_visible = False
            for plate, text in plates:
                hit = (not searching) or (q in text)
                plate.set_visible(hit)
                any_visible = any_visible or hit
            divider.set_visible(any_visible)

    # ── font scaling ──────────────────────────────────────────────────────────
    def apply_font_size(self, pt):
        """Scale the whole document from the app's reading font size (the
        .stone-* sizes are em-relative). Called on render and whenever the
        pane's appearance changes."""
        if not pt:
            return
        self._font_provider.load_from_data(
            f'.stone-page {{ font-size: {pt}pt; }}'.encode())

    # ── contents jump ─────────────────────────────────────────────────────────
    def _build_contents(self, doc):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-contents')
        for chap in doc['chapters']:
            if not chap['entries']:
                continue
            btn = Gtk.Button(label=chap['title'])
            btn.add_css_class('flat')
            btn.set_halign(Gtk.Align.FILL)
            btn.get_child().set_xalign(0)
            btn.connect('clicked', lambda _b, cid=chap['id']: self._jump(cid))
            box.append(btn)
        for cid, title in (('_glossary', _('Glossary')),
                           ('_reading', _('Sources & further reading'))):
            if cid not in self._chapter_anchors:
                continue
            btn = Gtk.Button(label=title)
            btn.add_css_class('flat')
            btn.add_css_class('stone-contents-apx')
            btn.set_halign(Gtk.Align.FILL)
            btn.get_child().set_xalign(0)
            btn.connect('clicked', lambda _b, c=cid: self._jump(c))
            box.append(btn)
        self._contents_pop.set_child(box)

    def _jump(self, chapter_id):
        self._contents_pop.popdown()
        anchor = self._chapter_anchors.get(chapter_id)
        if anchor is None:
            return

        def scroll():
            ok, rect = anchor.compute_bounds(self._page)
            if ok:
                self._scroller.get_vadjustment().set_value(rect.get_y())
            return False

        # Defer so a freshly-realised layout has valid bounds.
        GLib.idle_add(scroll)

    # ── scroll to a specific artifact (from a Bible verse marker) ──────────────
    def scroll_to_verse(self, book, chapter, verse):
        """Scroll to the plate of the artifact that references this verse, and
        flash it. Called when a 'related artifact' marker is clicked in a Bible
        pane (the gallery may have just been revealed, so retry until laid out)."""
        self.render()
        w = self._verse_anchors.get((book, chapter, verse))
        if w is None:
            return
        self._scroll_target = w
        self._scroll_tries = 0
        GLib.timeout_add(40, self._do_scroll)

    def _do_scroll(self):
        w = self._scroll_target
        if w is None:
            return False
        self._scroll_tries += 1
        ok, rect = w.compute_bounds(self._page)
        if not ok:
            return self._scroll_tries < 25      # retry until the pane lays out
        self._scroller.get_vadjustment().set_value(max(0, rect.get_y() - 8))
        w.add_css_class('stone-flash')
        GLib.timeout_add(1400,
                         lambda: w.remove_css_class('stone-flash') or False)
        self._scroll_target = None
        return False

    def scroll_to_entry(self, image):
        """Scroll to a specific artifact's plate (used by the map) and flash it."""
        self.render()
        w = self._entry_anchors.get(image)
        if w is None:
            return
        self._scroll_target = w
        self._scroll_tries = 0
        GLib.timeout_add(40, self._do_scroll)

    # ── map (where the artifacts were found) ──────────────────────────────────
    _HIT = 22.0    # click / hover tolerance in px (generous hit targets)

    def _open_map(self):
        """Show the bundled biblical-world map with a marker at every artifact's
        find-spot. Hover a marker to read its name; click to jump the gallery to
        it. If a marker exists for the artifact currently being read, it is
        ringed as a gentle "you are here"."""
        root = self._root.get_root()
        if root is None:
            return
        pts = [e for c in archaeology_bridge.document()['chapters']
               for e in c['entries']
               if e.get('lat') is not None and e.get('lon') is not None]
        self._map_points = self._jitter(pts)
        self._map_screen = []
        self._map_hover = None
        self._map_here = self._current_entry()
        try:
            self._map_pixbuf = GdkPixbuf.Pixbuf.new_from_file(
                archaeology_bridge.map_path())
        except Exception:
            _log.exception('failed to load the biblical-world map')
            self._map_pixbuf = None

        area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        area.set_draw_func(self._draw_map, None)
        area.set_cursor(Gdk.Cursor.new_from_name('pointer', None))
        self._map_area = area
        click = Gtk.GestureClick()
        click.connect('released', self._on_map_click)
        area.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_map_motion)
        motion.connect('leave', self._on_map_leave)
        area.add_controller(motion)
        # Gentle pulse for the "you are here" ring (only if there's one to draw).
        if self._map_here is not None:
            self._map_tick = area.add_tick_callback(
                lambda a, _c, _d: (a.queue_draw() or True), None)

        title = Adw.WindowTitle(title=_('Where they were found'))
        if self._map_here is not None:
            title.set_subtitle(
                _('Reading: {title}').format(title=self._map_here['title']))
        header = Adw.HeaderBar()
        header.set_title_widget(title)

        dialog = Adw.Dialog()
        dialog.set_title(_('Where they were found'))
        dialog.set_content_width(1060)
        dialog.set_content_height(620)
        dialog.connect('closed', self._on_map_closed)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(area)
        dialog.set_child(view)
        self._map_dialog = dialog
        dialog.present(root)

    def _on_map_closed(self, _dialog):
        if self._map_tick and self._map_area is not None:
            self._map_area.remove_tick_callback(self._map_tick)
        self._map_tick = 0
        self._map_area = None

    def _current_entry(self):
        """The artifact whose plate is at the top of the viewport — used so the
        map can orient the reader to where they are. None if nothing maps."""
        adj = self._scroller.get_vadjustment().get_value()
        by_image = {e['image']: e
                    for c in archaeology_bridge.document()['chapters']
                    for e in c['entries']
                    if e.get('lat') is not None and e.get('lon') is not None}
        best, best_y = None, -1.0
        for image, w in self._entry_anchors.items():
            if image not in by_image:
                continue
            ok, rect = w.compute_bounds(self._page)
            if not ok:
                continue
            y = rect.get_y()
            # The topmost plate at or just above the viewport top.
            if y <= adj + 80 and y > best_y:
                best_y, best = y, by_image[image]
        if best is None:                 # scrolled above the first plate
            return next(iter(by_image.values()), None)
        return best

    def _jitter(self, pts):
        """Spread artifacts sharing a find-spot into a small ring so each marker
        stays clickable (e.g. the many finds at Jerusalem or Nineveh)."""
        self._map_pts_raw = pts
        groups: dict = {}
        for e in pts:
            groups.setdefault((round(e['lat'], 2), round(e['lon'], 2)), []).append(e)
        out = []
        for members in groups.values():
            n = len(members)
            if n == 1:
                e = members[0]
                out.append((e['lat'], e['lon'], 0.0, 0.0, e))
            else:
                r = 9.0 + 1.9 * n
                for i, e in enumerate(members):
                    a = 2 * math.pi * i / n - math.pi / 2
                    out.append((e['lat'], e['lon'],
                                r * math.cos(a), r * math.sin(a), e))
        return out

    def _nearby_count(self, lat, lon, deg=0.6):
        """How many find-spots fall within ~deg° of a point — lets a city label
        double as a 'N finds here' badge without a separate cluttered marker."""
        return sum(1 for e in getattr(self, '_map_pts_raw', [])
                   if abs(e['lat'] - lat) <= deg and abs(e['lon'] - lon) <= deg)

    @staticmethod
    def _project(lon, lat, ox, oy, dw, dh):
        lon0, lon1, lat0, lat1 = _MAP_BOUNDS
        return (ox + (lon - lon0) / (lon1 - lon0) * dw,
                oy + (lat1 - lat) / (lat1 - lat0) * dh)

    @staticmethod
    def _stroked_text(cr, x, y, text, size, *, italic=False, bold=False,
                      align='left', alpha=1.0):
        """Draw legible text over any background: a dark halo then light glyphs."""
        slant = cairo_italic if italic else cairo_normal
        weight = cairo_bold if bold else cairo_book
        cr.select_font_face('sans-serif', slant, weight)
        cr.set_font_size(size)
        ext = cr.text_extents(text)
        if align == 'center':
            x -= ext.width / 2 + ext.x_bearing
        elif align == 'right':
            x -= ext.width + ext.x_bearing
        cr.set_source_rgba(0, 0, 0, 0.55 * alpha)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            cr.move_to(x + dx, y + dy)
            cr.show_text(text)
        cr.set_source_rgba(1, 1, 1, 0.92 * alpha)
        cr.move_to(x, y)
        cr.show_text(text)
        return ext.width

    @staticmethod
    def _axis_text(cr, x, y, text, size, ink, alpha, align='center'):
        """Plain text in the theme's foreground colour — for the timeline, which
        sits on a solid background and so needs no halo (unlike the map)."""
        cr.select_font_face('sans-serif', cairo_normal, cairo_book)
        cr.set_font_size(size)
        ext = cr.text_extents(text)
        if align == 'center':
            x -= ext.width / 2 + ext.x_bearing
        cr.set_source_rgba(ink[0], ink[1], ink[2], alpha)
        cr.move_to(x, y)
        cr.show_text(text)

    def _draw_map(self, _area, cr, w, h, _data):
        pb = self._map_pixbuf
        if pb is None:
            return
        pw, ph = pb.get_width(), pb.get_height()
        scale = min(w / pw, h / ph)
        dw, dh = pw * scale, ph * scale
        ox, oy = (w - dw) / 2, (h - dh) / 2
        cr.save()
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.paint()
        cr.restore()

        # Orientation labels (drawn under the markers).
        for lat, lon, text in _SEA_LABELS:
            px, py = self._project(lon, lat, ox, oy, dw, dh)
            self._stroked_text(cr, px, py, text, 13, italic=True,
                               align='center', alpha=0.75)
        for lat, lon, text in _REGION_LABELS:
            px, py = self._project(lon, lat, ox, oy, dw, dh)
            self._stroked_text(cr, px, py, text, 13, bold=True,
                               align='center', alpha=0.7)
        # City labels as legible pills above their (often dense) swarm, with the
        # nearby find-count folded in so a busy spot reads as "Jerusalem · 14".
        for lat, lon, name in _CITY_LABELS:
            px, py = self._project(lon, lat, ox, oy, dw, dh)
            n = self._nearby_count(lat, lon)
            text = f'{name} · {n}' if n >= 3 else name
            self._pill_label(cr, px, py - 30, text)

        # Markers.
        self._map_screen = []
        for lat, lon, jx, jy, e in self._map_points:
            bx, by = self._project(lon, lat, ox, oy, dw, dh)
            px, py = bx + jx, by + jy
            self._map_screen.append((px, py, e))
            hovered = e is self._map_hover
            rr, ir = (7.5, 5.0) if hovered else (5.5, 3.4)
            cr.set_source_rgba(1, 1, 1, 0.96)             # white ring
            cr.arc(px, py, rr, 0, 6.2831853)
            cr.fill()
            cr.set_source_rgba(0.70, 0.42, 0.26, 1)       # clay dot
            cr.arc(px, py, ir, 0, 6.2831853)
            cr.fill()

        # "You are here" ring on the currently-read artifact (gentle pulse).
        if self._map_here is not None:
            for px, py, e in self._map_screen:
                if e is self._map_here:
                    t = GLib.get_monotonic_time() / 1e6
                    pulse = 0.5 + 0.5 * math.sin(t * 3.0)
                    cr.set_source_rgba(0.20, 0.52, 0.89, 0.85)
                    cr.set_line_width(2.5)
                    cr.arc(px, py, 11 + 3 * pulse, 0, 6.2831853)
                    cr.stroke()
                    break

        # Hover name card (drawn last, on top of everything).
        if self._map_hover is not None:
            for px, py, e in self._map_screen:
                if e is self._map_hover:
                    self._draw_name_card(cr, px, py, e, w, h)
                    break

    def _draw_name_card(self, cr, px, py, e, w, h):
        title, place = e['title'], e.get('place', '')
        cr.select_font_face('sans-serif', cairo_normal, cairo_bold)
        cr.set_font_size(14)
        tw = cr.text_extents(title).width
        cr.select_font_face('sans-serif', cairo_normal, cairo_book)
        cr.set_font_size(11.5)
        pw_ = cr.text_extents(place).width if place else 0
        cw = max(tw, pw_) + 22
        ch = 44 if place else 28
        # Prefer above the marker; flip below / clamp to stay on screen.
        cx = min(max(px - cw / 2, 6), w - cw - 6)
        cy = py - ch - 14
        if cy < 6:
            cy = py + 16
        self._rounded_rect(cr, cx, cy, cw, ch, 8)
        cr.set_source_rgba(0.12, 0.10, 0.09, 0.92)
        cr.fill()
        cr.select_font_face('sans-serif', cairo_normal, cairo_bold)
        cr.set_font_size(14)
        cr.set_source_rgba(1, 1, 1, 0.98)
        cr.move_to(cx + 11, cy + 19)
        cr.show_text(title)
        if place:
            cr.select_font_face('sans-serif', cairo_normal, cairo_book)
            cr.set_font_size(11.5)
            cr.set_source_rgba(0.82, 0.70, 0.58, 0.95)
            cr.move_to(cx + 11, cy + 35)
            cr.show_text(place)

    def _pill_label(self, cr, cx, cy, text):
        """A small dark rounded pill centred at (cx, cy) with light text — reads
        cleanly over a busy marker swarm where plain stroked text would not."""
        cr.select_font_face('sans-serif', cairo_normal, cairo_bold)
        cr.set_font_size(11.5)
        ext = cr.text_extents(text)
        pw, ph = ext.width + 16, 20
        self._rounded_rect(cr, cx - pw / 2, cy - ph / 2, pw, ph, 9)
        cr.set_source_rgba(0.12, 0.10, 0.09, 0.82)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.96)
        cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy + 4)
        cr.show_text(text)

    @staticmethod
    def _rounded_rect(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    def _nearest(self, x, y):
        best, bd = None, self._HIT * self._HIT
        for px, py, e in self._map_screen:
            d = (px - x) ** 2 + (py - y) ** 2
            if d < bd:
                bd, best = d, e
        return best

    def _on_map_motion(self, _ctrl, x, y):
        hit = self._nearest(x, y)
        if hit is not self._map_hover:
            self._map_hover = hit
            if self._map_area is not None:
                self._map_area.queue_draw()

    def _on_map_leave(self, _ctrl):
        if self._map_hover is not None:
            self._map_hover = None
            if self._map_area is not None:
                self._map_area.queue_draw()

    def _on_map_click(self, _gesture, _n, x, y):
        best = self._nearest(x, y)
        if best is not None:
            if self._map_dialog is not None:
                self._map_dialog.close()
            self.scroll_to_entry(best['image'])

    # ── timeline (when the artifacts date from) ────────────────────────────────
    _CENTURY = re.compile(r'(\d+)\s*(?:st|nd|rd|th)?\s*c(?:entury|\.)')
    _NUMBER = re.compile(r'\d+')

    @classmethod
    def _parse_year(cls, date):
        """A representative year for a date string ('9th century BC' → -850,
        'c. AD 81' → 81), or None when it can't be placed (e.g. 'Roman era')."""
        s = date.lower().replace('–', '-').replace('—', '-')
        if not s:
            return None
        bc, ad = 'bc' in s, 'ad' in s
        m = cls._CENTURY.search(s)
        if m:
            year = (int(m.group(1)) - 1) * 100 + 50      # century midpoint
        else:
            m = cls._NUMBER.search(s)
            if not m:
                return None
            year = int(m.group())
        if bc and ad:
            return 0                                     # spans the turn of era
        if bc:
            return -year
        if ad:
            return year
        return None                                      # no era token → skip

    def _open_timeline(self):
        """A chronological axis of the artifacts; hover a tick to read it, click
        to jump. The gallery's spine is chronological, so this is the 'when' that
        partners the map's 'where'."""
        root = self._root.get_root()
        if root is None:
            return
        self.render()
        items = []
        for c in archaeology_bridge.document()['chapters']:
            for e in c['entries']:
                y = self._parse_year(e['date'])
                if y is not None and -1450 <= y <= 150:   # keep to the biblical era
                    items.append((y, e))
        items.sort(key=lambda t: t[0])
        self._tl_points = items
        self._tl_screen = []
        self._tl_hover = None

        area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        area.set_draw_func(self._draw_timeline, None)
        area.set_cursor(Gdk.Cursor.new_from_name('pointer', None))
        self._tl_area = area
        click = Gtk.GestureClick()
        click.connect('released', self._on_tl_click)
        area.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_tl_motion)
        motion.connect('leave', self._on_tl_leave)
        area.add_controller(motion)

        dialog = Adw.Dialog()
        dialog.set_title(_('When they date from'))
        dialog.set_content_width(1080)
        dialog.set_content_height(540)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(area)
        dialog.set_child(view)
        self._tl_dialog = dialog
        dialog.present(root)

    @staticmethod
    def _year_label(yv):
        if yv < 0:
            return f'{-yv} BC'
        return f'AD {yv}' if yv > 0 else 'AD 1'

    def _draw_timeline(self, _area, cr, w, h, _data):
        items = self._tl_points
        if not items:
            return
        years = [y for y, _ in items]
        lo, hi = min(years), max(years)
        span = max(hi - lo, 100)
        lo, hi = lo - span * 0.04, hi + span * 0.04
        ml, mr, axis_y = 56, 28, h - 64
        plot_w = w - ml - mr

        def xof(year):
            return ml + (year - lo) / (hi - lo) * plot_w

        # Unlike the map (which sits on a dark photo), the timeline sits on the
        # themed dialog background — so its grid/axis/labels follow the theme.
        ink = (1, 1, 1) if Adw.StyleManager.get_default().get_dark() else (0, 0, 0)

        # Century gridlines + labels.
        step = 100 if (hi - lo) <= 1300 else 200
        cr.set_line_width(1)
        gv = math.ceil(lo / step) * step
        while gv <= hi:
            gx = xof(gv)
            cr.set_source_rgba(*ink, 0.09)
            cr.move_to(gx, 30)
            cr.line_to(gx, axis_y)
            cr.stroke()
            self._axis_text(cr, gx, axis_y + 20, self._year_label(gv), 11,
                            ink, 0.7)
            gv += step

        # Axis line.
        cr.set_source_rgba(*ink, 0.32)
        cr.set_line_width(1.5)
        cr.move_to(ml, axis_y)
        cr.line_to(w - mr, axis_y)
        cr.stroke()

        # Lay artifacts out in stacked lanes so close dates don't overlap.
        self._tl_screen = []
        lanes: list[float] = []
        rowh, base, mingap = 17, axis_y - 26, 15
        placed = []
        for year, e in items:
            x = xof(year)
            lane = next((i for i, lx in enumerate(lanes) if x - lx > mingap), None)
            if lane is None:
                lanes.append(x)
                lane = len(lanes) - 1
            else:
                lanes[lane] = x
            placed.append((x, base - lane * rowh, e))

        for x, y, e in placed:
            self._tl_screen.append((x, y, e))
            hovered = e is self._tl_hover
            cr.set_source_rgba(0.70, 0.42, 0.26, 0.45)   # stem to the axis
            cr.set_line_width(1)
            cr.move_to(x, axis_y)
            cr.line_to(x, y)
            cr.stroke()
            rr, ir = (7.0, 4.5) if hovered else (5.0, 3.2)
            cr.set_source_rgba(1, 1, 1, 0.96)
            cr.arc(x, y, rr, 0, 6.2831853)
            cr.fill()
            cr.set_source_rgba(0.70, 0.42, 0.26, 1)
            cr.arc(x, y, ir, 0, 6.2831853)
            cr.fill()

        if self._tl_hover is not None:
            for x, y, e in self._tl_screen:
                if e is self._tl_hover:
                    self._draw_name_card(cr, x, y, e, w, h)
                    break

    @staticmethod
    def _nearest_in(screen, x, y, tol):
        best, bd = None, tol * tol
        for px, py, e in screen:
            d = (px - x) ** 2 + (py - y) ** 2
            if d < bd:
                bd, best = d, e
        return best

    def _on_tl_motion(self, _ctrl, x, y):
        hit = self._nearest_in(self._tl_screen, x, y, 16.0)
        if hit is not self._tl_hover:
            self._tl_hover = hit
            if self._tl_area is not None:
                self._tl_area.queue_draw()

    def _on_tl_leave(self, _ctrl):
        if self._tl_hover is not None:
            self._tl_hover = None
            if self._tl_area is not None:
                self._tl_area.queue_draw()

    def _on_tl_click(self, _gesture, _n, x, y):
        best = self._nearest_in(self._tl_screen, x, y, 16.0)
        if best is not None:
            if self._tl_dialog is not None:
                self._tl_dialog.close()
            self.scroll_to_entry(best['image'])
