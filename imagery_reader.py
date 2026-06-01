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

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

import imagery_bridge

_log = logging.getLogger('scriptura.imagery')

_TRADITION_LABEL = {
    'engraving': 'Engravings',
    'old_master': 'Paintings',
    'byzantine_icon': 'Icons',
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

    # ── public drive ──────────────────────────────────────────────────────────

    def render_for(self, book, chapter, verse):
        """Show imagery for a verse (driven by the partnered Bible pane)."""
        self._book, self._chapter, self._verse = book, chapter, verse
        self._clear(self._art_box)
        self._clear(self._where_box)

        if not (book and chapter and verse):
            self._header.set_text('Bible Imagery')
            self._switcher.set_visible(False)
            self._art_box.append(self._status(
                'image-x-generic-symbolic',
                'Open a Bible alongside this pane',
                'Navigate there to see illustrations, maps, and photos of the '
                'places named in each verse.'))
            self._stack.set_visible_child_name('art')
            return

        try:
            art = imagery_bridge.art_for(book, chapter, verse)
            maps = imagery_bridge.maps_for(book, chapter, verse)
            places = imagery_bridge.places_for(book, chapter, verse)
        except Exception:
            _log.exception('imagery lookup failed')
            art, maps, places = [], [], []

        self._header.set_text(f'{book} {chapter}:{verse}')
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
                'image-x-generic-symbolic', 'No illustration for this verse',
                'Try a neighbouring verse, or a scene the artists depicted '
                'more often. The Where tab may still have a map or places.'))
            return

        house = items[0]['tradition']
        default = [i for i in items if i['tradition'] == house]
        others = [i for i in items if i['tradition'] != house]

        for it in default:
            self._art_box.append(self._image_card(it))

        if others:
            expander = Gtk.Expander(
                label=f'See this scene in other traditions ({len(others)})')
            expander.set_margin_top(4)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            inner.set_margin_top(8)
            prev = None
            for it in others:
                if it['tradition'] != prev:
                    inner.append(self._tradition_divider(it['tradition']))
                    prev = it['tradition']
                inner.append(self._image_card(it))
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
                'find-location-symbolic', 'No places mapped for this verse',
                'Not every verse names a place. The Art tab may still have an '
                'illustration.'))
            return

        # Lead with the modern vector map (Scriptura's modern aesthetic), then
        # the antique atlas maps for the same passage.
        maps = sorted(maps, key=lambda m: 0 if m['tradition'] == 'modern_map' else 1)
        for m in maps:
            self._where_box.append(self._image_card(m))

        if places:
            head = Gtk.Label(label='Places in this verse', xalign=0)
            head.add_css_class('caption')
            head.add_css_class('imagery-meta')
            head.set_margin_top(4)
            self._where_box.append(head)
            for p in places:
                self._where_box.append(self._place_card(p))

    def _place_card(self, place):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class('card')
        card.add_css_class('imagery-card')

        if place['path'] and os.path.exists(place['path']):
            card.append(self._picture(
                place['path'], place['ancient_name'],
                zoom={'path': place['path'], 'title': place['ancient_name']}))

        name = place['ancient_name']
        if place.get('modern_name'):
            name = f'{name} · today {place["modern_name"]}'
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
            note = Gtk.Label(label='Traditional / uncertain identification',
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
        pic = Gtk.Picture.new_for_filename(path)
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
        view.add_top_bar(Adw.HeaderBar())
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        pic = Gtk.Picture.new_for_filename(item['path'])
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_can_shrink(True)
        scroll.set_child(pic)
        view.set_content(scroll)
        dialog.set_child(view)
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
