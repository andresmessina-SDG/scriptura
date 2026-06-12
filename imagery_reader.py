"""imagery_reader.py — the Bible Imagery pane subsystem.

Shows imagery for the verse the partnered Bible pane is on, in two tabs
(an Adw.ViewSwitcher over an Adw.ViewStack):

  * **Art**   — illustrations/paintings/icons/glass. Harmonised by default:
    one tradition (the house-style engraving, sorted first by the bridge)
    is shown, with a "See this scene in other traditions (N)" expander
    revealing the rest — so the default view is always one coherent visual
    world.
  * **Where** — maps covering the passage, then photos of the places named
    in the verse (with a confidence cue for contested identifications).

Adaptive: the switcher only appears when *both* tabs have content; when one
is empty the populated tab is shown bare; when neither has content a single
Adw.StatusPage is shown. Mirrors catena_reader's compose-and-drive shape.
Follows the partnered Bible pane and degrades gracefully — never locks down.
"""

import logging
import os
import threading

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib

# librsvg for pixel-crisp SVG zoom (the generated maps); optional — without
# it SVGs zoom like rasters, scaled from their natural-size decode.
try:
    gi.require_version('Rsvg', '2.0')
    from gi.repository import Rsvg
    import cairo
except (ValueError, ImportError):   # pragma: no cover — runtime fallback
    Rsvg = None
from a11y import set_accessible_label

import imagery_bridge

_log = logging.getLogger('scriptura.imagery')


class _ImageryPicture(Gtk.Picture):
    """A Gtk.Picture that caps its *natural* width so the card grid can pair
    cards into two columns. A plain Gtk.Picture reports the image's intrinsic
    width as its natural width, which makes the FlowBox treat a wide map as
    needing a full row (one column); capping the natural width lets two cards
    share a row, while hexpand still lets each fill its column."""
    __gtype_name__ = 'ScripturaImageryPicture'
    NAT_CAP = 340

    def do_measure(self, orientation, for_size):
        m, n, mb, nb = Gtk.Picture.do_measure(self, orientation, for_size)
        if orientation == Gtk.Orientation.HORIZONTAL:
            if n > self.NAT_CAP:
                n = self.NAT_CAP
                if m > n:
                    m = n
            return (m, n, -1, -1)   # horizontal measures carry no baseline
        return (m, n, mb, nb)


_TRADITION_LABEL = {
    'engraving': 'Engravings',
    'old_master': 'Paintings',
    'byzantine_icon': 'Icons',
    'illumination': 'Illuminated manuscripts',
    'stained_glass': 'Stained glass',
    'watercolor': 'Watercolours',
    'cartography': 'Maps',
}


def _meta_line(item):
    """'Artist · 1866' (or just one, or the map's passage scope)."""
    bits = []
    if item.get('artist'):
        bits.append(item['artist'])
    if item.get('year'):
        bits.append(str(item['year']))
    if not bits and item.get('passage_label'):
        bits.append(item['passage_label'])
    return ' · '.join(bits)


def _credit_text(item):
    """Multi-line credit for the clipboard: title, artist · year, and the
    full attribution — ready to paste under a slide. The artist/year line
    is skipped when the attribution already names the artist (same
    redundancy rule as the card)."""
    lines = []
    if item.get('title'):
        lines.append(item['title'])
    meta = _meta_line(item)
    artist = item.get('artist')
    attribution = item.get('attribution')
    if meta and not (artist and attribution and artist in attribution):
        lines.append(meta)
    if attribution:
        lines.append(attribution)
    return '\n'.join(lines)


class _ZoomViewer(Gtk.ScrolledWindow):
    """Scroll-/button-to-zoom, drag-to-pan image view for the zoom dialog.

    Starts fitted to the viewport; zooming past fit sizes the picture
    explicitly in natural-pixel multiples so the scrolled window provides the
    panning. The antique map scans are stored at full resolution, so zooming
    actually reveals the place names the fit view is too small to show.
    """

    _MAX = 4.0    # cap display at 400% of the image's natural pixels
    _STEP = 1.4   # multiplicative zoom per scroll notch / button press

    def __init__(self, texture, vector_path=None):
        super().__init__(hexpand=True, vexpand=True)
        self._tex = texture
        self._nw = texture.get_width() or 1
        self._nh = texture.get_height() or 1
        # SVG sources stay pixel-crisp at any zoom: the base raster shows
        # during interaction, and a viewport-sized sharp render (librsvg in
        # a worker thread, ~200 ms) overlays it when the view settles —
        # re-rendering the whole sheet at 4x would take seconds.
        self._svg = None
        if vector_path is not None and Rsvg is not None:
            try:
                self._svg = Rsvg.Handle.new_from_file(vector_path)
            except GLib.Error:
                pass
        self.crisp_layer = Gtk.Picture()    # dialog pins this over the view
        self.crisp_layer.set_visible(False)
        self.crisp_layer.set_can_target(False)   # input falls through
        self._render_id = None
        self._render_gen = 0
        for adj in (self.get_hadjustment(), self.get_vadjustment()):
            adj.connect('value-changed', lambda *_a: self._invalidate_crisp())
        self._scale = None        # None == fitted; otherwise display/natural
        self._pan0 = (0.0, 0.0)
        self._pending = None      # (frac_x, frac_y, vx, vy) anchor after a zoom
        self._pinch = None        # (base_scale, frac_x, frac_y, cx, cy) during pinch
        self._changed_cb = None

        self._pic = Gtk.Picture.new_for_paintable(texture)
        self._pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._pic.set_can_shrink(True)
        self._pic.set_halign(Gtk.Align.CENTER)
        self._pic.set_valign(Gtk.Align.CENTER)
        self.set_child(self._pic)

        # Two-finger scroll pans the image — the GtkScrolledWindow does this
        # natively once the picture overflows the viewport, so we don't touch
        # scroll events. Pinch zooms; mouse users get click-drag panning and
        # the header-bar buttons.
        pinch = Gtk.GestureZoom()
        pinch.connect('begin', self._on_pinch_begin)
        pinch.connect('scale-changed', self._on_pinch_scale)
        self.add_controller(pinch)
        drag = Gtk.GestureDrag()
        drag.connect('drag-begin', self._on_drag_begin)
        drag.connect('drag-update', self._on_drag_update)
        self.add_controller(drag)

    # ── state ────────────────────────────────────────────────────────────────

    def set_changed_cb(self, cb):
        self._changed_cb = cb

    def set_texture(self, texture, vector_path=None):
        """Swap the displayed image in place, keeping the zoom/pan state —
        the map era pair shares one geometry, so the view must not jump."""
        self._tex = texture
        self._nw = texture.get_width() or 1
        self._nh = texture.get_height() or 1
        self._pic.set_paintable(texture)
        self._svg = None
        if vector_path is not None and Rsvg is not None:
            try:
                self._svg = Rsvg.Handle.new_from_file(vector_path)
            except GLib.Error:
                pass
        self._invalidate_crisp()

    # ── crisp vector overlay ─────────────────────────────────────────────────
    # Any pan or zoom hides the sharp layer (the base raster shows through);
    # once the view rests for 120 ms the visible window is re-rendered from
    # the SVG at display resolution off the main thread and overlaid.

    def _invalidate_crisp(self):
        if self._svg is None:
            return
        self.crisp_layer.set_visible(False)
        if self._render_id is not None:
            GLib.source_remove(self._render_id)
            self._render_id = None
        if self._scale is None or self._eff() <= 1.001:
            return    # the natural-size decode is already exact
        self._render_id = GLib.timeout_add(120, self._start_crisp_render)

    def _start_crisp_render(self):
        self._render_id = None
        self._render_gen += 1
        s = min(self._eff(), self._MAX)
        sf = self.get_scale_factor() or 1
        vw, vh = self.get_width(), self.get_height()
        if vw <= 0 or vh <= 0:
            return GLib.SOURCE_REMOVE
        dw, dh = self._nw * s, self._nh * s
        ox = self.get_hadjustment().get_value() - max(0.0, (vw - dw) / 2)
        oy = self.get_vadjustment().get_value() - max(0.0, (vh - dh) / 2)
        threading.Thread(
            target=self._crisp_worker, daemon=True,
            args=(self._render_gen, self._svg, sf,
                  int(vw * sf), int(vh * sf),
                  ox * sf, oy * sf, dw * sf, dh * sf)).start()
        return GLib.SOURCE_REMOVE

    def _crisp_worker(self, gen, svg, sf, w, h, ox, oy, dw, dh):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        cr.translate(-ox, -oy)
        vp = Rsvg.Rectangle()
        vp.x = vp.y = 0
        vp.width, vp.height = dw, dh
        try:
            svg.render_document(cr, vp)
        except GLib.Error:
            return
        surf.flush()
        data = GLib.Bytes.new(bytes(surf.get_data()))
        GLib.idle_add(self._apply_crisp, gen, data, w, h, surf.get_stride())

    def _apply_crisp(self, gen, data, w, h, stride):
        # a pan/zoom after this render started has already queued a fresh one
        if gen != self._render_gen or self._scale is None:
            return GLib.SOURCE_REMOVE
        self.crisp_layer.set_paintable(Gdk.MemoryTexture.new(
            w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, data, stride))
        self.crisp_layer.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _fit(self):
        vw, vh = self.get_width(), self.get_height()
        if vw <= 0 or vh <= 0:
            return 1.0
        return min(vw / self._nw, vh / self._nh)

    def _eff(self):
        return self._fit() if self._scale is None else self._scale

    def _ceil(self):
        return max(self._fit(), self._MAX)

    def can_zoom_in(self):
        return self._eff() < self._ceil() - 1e-3

    def can_zoom_out(self):
        return self._scale is not None

    # ── apply ────────────────────────────────────────────────────────────────

    def _apply(self):
        if self._scale is None:
            self._pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            self._pic.set_can_shrink(True)
            self._pic.set_hexpand(True)
            self._pic.set_vexpand(True)
            self._pic.set_size_request(-1, -1)
            self.set_cursor(None)
        else:
            self._pic.set_content_fit(Gtk.ContentFit.FILL)
            self._pic.set_can_shrink(False)
            self._pic.set_hexpand(False)
            self._pic.set_vexpand(False)
            self._pic.set_size_request(int(self._nw * self._scale),
                                       int(self._nh * self._scale))
            self.set_cursor(Gdk.Cursor.new_from_name('grab', None))
        if self._pending is not None:
            self.add_tick_callback(self._restore_anchor)
        self._invalidate_crisp()
        if self._changed_cb is not None:
            self._changed_cb()

    def _content_fraction_at(self, vx, vy):
        vw, vh = self.get_width(), self.get_height()
        if self._scale is None:
            fit = self._fit()
            iw, ih = self._nw * fit, self._nh * fit
            mx, my = max(0.0, (vw - iw) / 2), max(0.0, (vh - ih) / 2)
            fx = min(max((vx - mx) / iw, 0.0), 1.0) if iw else 0.5
            fy = min(max((vy - my) / ih, 0.0), 1.0) if ih else 0.5
        else:
            dw, dh = self._nw * self._scale, self._nh * self._scale
            fx = (self.get_hadjustment().get_value() + vx) / dw
            fy = (self.get_vadjustment().get_value() + vy) / dh
        return fx, fy

    def _restore_anchor(self, *_a):
        if self._pending is None or self._scale is None:
            return GLib.SOURCE_REMOVE
        fx, fy, vx, vy = self._pending
        self._pending = None
        dw, dh = self._nw * self._scale, self._nh * self._scale
        ha, va = self.get_hadjustment(), self.get_vadjustment()
        ha.set_value(min(max(fx * dw - vx, 0.0),
                         max(0.0, ha.get_upper() - ha.get_page_size())))
        va.set_value(min(max(fy * dh - vy, 0.0),
                         max(0.0, va.get_upper() - va.get_page_size())))
        return GLib.SOURCE_REMOVE

    def _zoom_to(self, scale, anchor):
        fit = self._fit()
        scale = max(fit, min(scale, self._ceil()))
        if scale <= fit * 1.001:
            self._scale = None
            self._pending = None
        else:
            self._scale = scale
            self._pending = anchor
        self._apply()

    # ── controls ─────────────────────────────────────────────────────────────

    def zoom_in(self):
        vw, vh = self.get_width(), self.get_height()
        fx, fy = self._content_fraction_at(vw / 2, vh / 2)
        self._zoom_to(self._eff() * self._STEP, (fx, fy, vw / 2, vh / 2))

    def zoom_out(self):
        vw, vh = self.get_width(), self.get_height()
        fx, fy = self._content_fraction_at(vw / 2, vh / 2)
        self._zoom_to(self._eff() / self._STEP, (fx, fy, vw / 2, vh / 2))

    def reset(self):
        self._scale = None
        self._pending = None
        self._apply()

    def _on_pinch_begin(self, gesture, _seq):
        ok, cx, cy = gesture.get_bounding_box_center()
        if not ok:
            cx, cy = self.get_width() / 2, self.get_height() / 2
        fx, fy = self._content_fraction_at(cx, cy)
        self._pinch = (self._eff(), fx, fy, cx, cy)

    def _on_pinch_scale(self, _gesture, scale):
        if self._pinch is None:
            return
        base, fx, fy, cx, cy = self._pinch
        self._zoom_to(base * scale, (fx, fy, cx, cy))

    def _on_drag_begin(self, _g, _x, _y):
        self._pan0 = (self.get_hadjustment().get_value(),
                      self.get_vadjustment().get_value())

    def _on_drag_update(self, _g, ox, oy):
        if self._scale is None:
            return
        h0, v0 = self._pan0
        self.get_hadjustment().set_value(h0 - ox)
        self.get_vadjustment().set_value(v0 - oy)


class ImageryReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._book = None
        self._chapter = None
        self._verse = None
        self._build_widget()

    @property
    def widget(self):
        return self._root

    # ── construction ────────────────────────────────────────────────────────

    def _build_widget(self):
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._header = Gtk.Label(xalign=0, wrap=True)
        self._header.add_css_class('title-4')
        self._header.add_css_class('imagery-header')
        self._root.append(self._header)

        self._stack = Adw.ViewStack(vexpand=True)
        self._switcher = Adw.ViewSwitcher(stack=self._stack)
        self._switcher.set_halign(Gtk.Align.CENTER)
        self._switcher.set_margin_bottom(4)
        self._root.append(self._switcher)
        self._root.append(self._stack)

        self._art_box, art_scroll = self._scrolling_list()
        self._where_box, where_scroll = self._scrolling_list()
        self._stack.add_titled_with_icon(
            art_scroll, 'art', 'Art', 'image-x-generic-symbolic')
        self._stack.add_titled_with_icon(
            where_scroll, 'where', 'Where', 'find-location-symbolic')

    def _scrolling_list(self):
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class('imagery-list')
        scroll.set_child(box)
        return box, scroll

    def _card_grid(self):
        """A run of cards that reflows to two columns when the pane is wide
        and collapses to one when narrow (a lone card still fills the width)."""
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_min_children_per_line(1)
        grid.set_max_children_per_line(2)
        grid.set_homogeneous(True)
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_valign(Gtk.Align.START)
        return grid

    # ── public drive ──────────────────────────────────────────────────────────

    def render_for(self, book, chapter, verse):
        """Show imagery for a verse (driven by the partnered Bible pane)."""
        # Skip redundant rebuilds: the same verse can be broadcast again (e.g.
        # the back-broadcast between synced panes), and rebuilding re-queries
        # the catalog and reloads every card image from disk for no change.
        if (book, chapter, verse) == (self._book, self._chapter, self._verse):
            return
        self._book, self._chapter, self._verse = book, chapter, verse
        self._clear(self._art_box)
        self._clear(self._where_box)

        if not (book and chapter and verse):
            self._header.set_text(_('Bible Imagery'))
            self._switcher.set_visible(False)
            self._art_box.append(self._status(
                'image-x-generic-symbolic',
                _('Open a Bible alongside this pane'),
                _('Navigate there to see illustrations, maps, and photos of the '
                  'places named in each verse.')))
            self._stack.set_visible_child_name('art')
            return

        try:
            art = imagery_bridge.art_for(book, chapter, verse)
            maps = imagery_bridge.maps_for(book, chapter, verse)
            places = imagery_bridge.places_for(book, chapter, verse)
        except Exception:
            _log.exception('imagery lookup failed')
            art, maps, places = [], [], []

        self._header.set_text(f'{book_label(book)} {chapter}:{verse}')
        self._build_art(art)
        self._build_where(maps, places)

        has_art = bool(art)
        has_where = bool(maps or places)
        # Tabs only earn their place when both sides have content.
        self._switcher.set_visible(has_art and has_where)
        self._stack.set_visible_child_name(
            'art' if (has_art or not has_where) else 'where')

    # ── art tab ───────────────────────────────────────────────────────────────

    def _build_art(self, items):
        if not items:
            self._art_box.append(self._status(
                'image-x-generic-symbolic', _('No illustration for this verse'),
                _('Try a neighbouring verse, or a scene the artists depicted '
                  'more often. The Where tab may still have a map or places.')))
            return

        house = items[0]['tradition']
        default = [i for i in items if i['tradition'] == house]
        others = [i for i in items if i['tradition'] != house]

        grid = self._card_grid()
        for it in default:
            grid.insert(self._image_card(it), -1)
        self._art_box.append(grid)

        if others:
            expander = Gtk.Expander(
                label=f'See this scene in other traditions ({len(others)})')
            expander.set_margin_top(4)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            inner.set_margin_top(8)
            prev = None
            tgrid = None
            for it in others:
                if it['tradition'] != prev:
                    inner.append(self._tradition_divider(it['tradition']))
                    tgrid = self._card_grid()
                    inner.append(tgrid)
                    prev = it['tradition']
                tgrid.insert(self._image_card(it), -1)
            expander.set_child(inner)
            self._art_box.append(expander)

    def _tradition_divider(self, tradition):
        lbl = Gtk.Label(label=_TRADITION_LABEL.get(tradition, tradition.title()),
                        xalign=0)
        lbl.add_css_class('caption')
        lbl.add_css_class('imagery-meta')
        return lbl

    # ── where tab ───────────────────────────────────────────────────────────

    def _build_where(self, maps, places):
        if not maps and not places:
            self._where_box.append(self._status(
                'find-location-symbolic', _('No places mapped for this verse'),
                _('Not every verse names a place. The Art tab may still have an '
                  'illustration.')))
            return

        # Lead with the modern vector map (Scriptura's modern aesthetic), then
        # the antique atlas maps for the same passage.
        maps = sorted(maps, key=lambda m: 0 if m['tradition'] == 'modern_map' else 1)
        if maps:
            mgrid = self._card_grid()
            for m in maps:
                mgrid.insert(self._image_card(m), -1)
            self._where_box.append(mgrid)

        if places:
            head = Gtk.Label(label=_('Places in this verse'), xalign=0)
            head.add_css_class('caption')
            head.add_css_class('imagery-meta')
            head.set_margin_top(4)
            self._where_box.append(head)
            pgrid = self._card_grid()
            for p in places:
                pgrid.insert(self._place_card(p), -1)
            self._where_box.append(pgrid)

    def _place_card(self, place):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class('card')
        card.add_css_class('imagery-card')
        # No hard min width: the card shrinks to fit a narrow pane (its picture
        # can_shrinks, its labels wrap). Two-column pairing is driven by the
        # picture's *natural* width cap (_ImageryPicture.NAT_CAP) instead, so
        # the grid still stays single-column until the pane is genuinely wide.

        if place['path'] and os.path.exists(place['path']):
            card.append(self._picture(
                place['path'], place['ancient_name'],
                zoom={'path': place['path'], 'title': place['ancient_name']}))

        name = place['ancient_name']
        if place.get('modern_name'):
            name = _('{ancient} · today {modern}').format(
                ancient=name, modern=place['modern_name'])
        title = Gtk.Label(label=name, xalign=0, wrap=True)
        title.add_css_class('heading')
        card.append(title)

        if place.get('caption'):
            cap = Gtk.Label(label=place['caption'], xalign=0, wrap=True)
            cap.add_css_class('caption')
            cap.add_css_class('imagery-meta')
            card.append(cap)

        # Photo credit + license — required for the CC/PD Commons photos.
        credit = ' · '.join(
            b for b in (place.get('credit'), place.get('license')) if b)
        if credit:
            attr = Gtk.Label(label=credit, xalign=0, wrap=True)
            attr.add_css_class('caption')
            attr.add_css_class('imagery-meta')
            card.append(attr)

        # Confidence cue — don't assert a contested identification as fact.
        # OpenBible confidence is 0-100 (its 0-1000 score, normalised); flag
        # low-confidence modern identifications.
        conf = place.get('confidence')
        if conf is not None and conf < 50:
            note = Gtk.Label(label=_('Traditional / uncertain identification'),
                             xalign=0, wrap=True)
            note.add_css_class('caption')
            note.add_css_class('imagery-meta')
            card.append(note)
        return card

    # ── shared card / picture / zoom ─────────────────────────────────────────

    def _image_card(self, item):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class('card')
        card.add_css_class('imagery-card')
        # See _place_card: no hard min width; pairing is natural-width-driven.

        if item['path'] and os.path.exists(item['path']):
            card.append(self._picture(item['path'], item['title'], zoom=item))

        if item.get('title'):
            title = Gtk.Label(label=item['title'], xalign=0, wrap=True)
            title.add_css_class('heading')
            card.append(title)

        meta = _meta_line(item)
        artist = item.get('artist')
        attribution = item.get('attribution')
        # Skip the "artist · year" meta line when the attribution already names
        # the artist — avoids showing "Schnorr · 1860" directly above
        # "Schnorr, Die Bibel in Bildern (1860)". Kept for maps (whose meta is a
        # passage scope, not the artist) and for items lacking attribution.
        if meta and not (artist and attribution and artist in attribution):
            meta_lbl = Gtk.Label(label=meta, xalign=0, wrap=True)
            meta_lbl.add_css_class('caption')
            meta_lbl.add_css_class('imagery-meta')
            card.append(meta_lbl)

        if attribution:
            attr = Gtk.Label(label=attribution, xalign=0, wrap=True)
            attr.add_css_class('caption')
            attr.add_css_class('imagery-meta')
            card.append(attr)
        return card

    def _picture(self, path, alt, zoom=None):
        pic = _ImageryPicture()
        pic.set_filename(path)
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_can_shrink(True)
        pic.set_hexpand(True)
        pic.set_alternative_text(alt or '')
        pic.add_css_class('imagery-pic')
        # Gtk.Picture under-requests its height, so in a verse with several
        # cards the images get squeezed to slivers (worse the more cards
        # share the pane). Reserve a definite height from the image's aspect
        # ratio at a reference card width, so each renders at a sensible,
        # orientation-aware size regardless of how many cards there are.
        paintable = pic.get_paintable()
        iw = paintable.get_intrinsic_width() if paintable is not None else 0
        ih = paintable.get_intrinsic_height() if paintable is not None else 0
        aspect = ih / iw if iw and ih else 0.7
        pic.set_size_request(-1, max(150, min(int(360 * aspect), 420)))
        if zoom is not None:
            click = Gtk.GestureClick()
            click.connect('released', lambda *_a: self._zoom(zoom))
            pic.add_controller(click)
            pic.set_cursor(self._pointer())
        return pic

    def _pointer(self):
        from gi.repository import Gdk
        return Gdk.Cursor.new_from_name('pointer', None)

    def _zoom(self, item):
        if not (item['path'] and os.path.exists(item['path'])):
            return
        root = self._root.get_root()
        dialog = Adw.Dialog()
        dialog.set_title(item.get('title') or 'Image')
        dialog.set_content_width(960)
        dialog.set_content_height(720)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        # Toasts confirm the copy actions; local to the dialog since the
        # reader has no window toast hook (and the dialog overlays the pane).
        toaster = Adw.ToastOverlay()
        toaster.set_child(view)

        try:
            texture = Gdk.Texture.new_from_filename(item['path'])
        except GLib.Error:
            texture = None

        # Generated maps ship in two eras (same geometry, different labels);
        # the present-day sibling sits beside the ancient file.
        modern_path = None
        if item['path'].endswith('_ancient.svg'):
            sibling = item['path'][:-len('_ancient.svg')] + '_modern.svg'
            if os.path.exists(sibling):
                modern_path = sibling

        # ── Copy actions — for pasting plates into slides/documents. The
        # image goes to the clipboard as a texture (pastes as PNG); the
        # credit as title / artist · year / attribution text.
        def _toast(msg):
            toaster.add_toast(Adw.Toast.new(msg))

        def _copy_image(_b):
            # Provide explicit image/png bytes: a bare texture value only
            # works for same-process pastes (local reads skip
            # serialization); browsers and other apps negotiate a mime
            # type, and image/png is what they all accept. The texture
            # value rides along for GTK-native consumers.
            png = texture.save_to_png_bytes()
            provider = Gdk.ContentProvider.new_union([
                Gdk.ContentProvider.new_for_bytes('image/png', png),
                Gdk.ContentProvider.new_for_value(texture),
            ])
            self._root.get_clipboard().set_content(provider)
            _toast(_('Image copied'))

        def _copy_credit(_b):
            self._root.get_clipboard().set(_credit_text(item))
            _toast(_('Credit copied'))

        if _credit_text(item):
            credit_btn = Gtk.Button(label=_('Copy credit'))
            credit_btn.add_css_class('flat')
            credit_btn.set_tooltip_text(
                _("Copy the artwork's title, artist, and source"))
            credit_btn.connect('clicked', _copy_credit)
            header.pack_end(credit_btn)
        if texture is not None:
            copy_btn = Gtk.Button(icon_name='edit-copy-symbolic')
            copy_btn.set_tooltip_text(_('Copy image'))
            set_accessible_label(copy_btn, _('Copy image'))
            copy_btn.connect('clicked', _copy_image)
            header.pack_end(copy_btn)

        if texture is None:
            # Fall back to a plain fitted view if the image won't decode.
            pic = Gtk.Picture.new_for_filename(item['path'])
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_can_shrink(True)
            view.add_top_bar(header)
            view.set_content(pic)
            dialog.set_child(toaster)
            if root is not None:
                dialog.present(root)
            return

        is_svg = item['path'].lower().endswith('.svg')
        viewer = _ZoomViewer(
            texture, vector_path=item['path'] if is_svg else None)

        if modern_path is not None:
            era_textures = {False: texture}

            def _on_era(btn):
                nonlocal texture
                modern = btn.get_active()
                if modern not in era_textures:
                    try:
                        era_textures[modern] = \
                            Gdk.Texture.new_from_filename(modern_path)
                    except GLib.Error:
                        btn.set_active(False)
                        return
                texture = era_textures[modern]
                viewer.set_texture(
                    texture,
                    vector_path=modern_path if modern else item['path'])

            era_btn = Gtk.ToggleButton(label=_('Today'))
            era_btn.set_tooltip_text(
                _('Switch between Bible-time and present-day names'))
            era_btn.connect('toggled', _on_era)
            header.pack_end(era_btn)

        out_btn = Gtk.Button(icon_name='zoom-out-symbolic')
        out_btn.set_tooltip_text(_('Zoom out'))
        set_accessible_label(out_btn, _('Zoom out'))
        in_btn = Gtk.Button(icon_name='zoom-in-symbolic')
        in_btn.set_tooltip_text(_('Zoom in'))
        set_accessible_label(in_btn, _('Zoom in'))
        fit_btn = Gtk.Button(icon_name='zoom-fit-best-symbolic')
        fit_btn.set_tooltip_text(_('Fit to window'))
        set_accessible_label(fit_btn, _('Fit to window'))
        out_btn.connect('clicked', lambda *_a: viewer.zoom_out())
        in_btn.connect('clicked', lambda *_a: viewer.zoom_in())
        fit_btn.connect('clicked', lambda *_a: viewer.reset())

        def _sync():
            in_btn.set_sensitive(viewer.can_zoom_in())
            out_btn.set_sensitive(viewer.can_zoom_out())
            fit_btn.set_sensitive(viewer.can_zoom_out())
        viewer.set_changed_cb(_sync)
        _sync()

        header.pack_start(out_btn)
        header.pack_start(in_btn)
        header.pack_start(fit_btn)
        view.add_top_bar(header)
        # The crisp SVG layer renders exactly the visible window, so it pins
        # to the viewport (an overlay), not to the scrolling content.
        overlay = Gtk.Overlay()
        overlay.set_child(viewer)
        overlay.add_overlay(viewer.crisp_layer)
        view.set_content(overlay)
        dialog.set_child(toaster)
        if root is not None:
            dialog.present(root)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _clear(self, box):
        child = box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _status(self, icon, title, detail):
        page = Adw.StatusPage()
        page.set_icon_name(icon)
        page.set_title(title)
        page.set_description(detail)
        page.set_vexpand(True)
        return page
