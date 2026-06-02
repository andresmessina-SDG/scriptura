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

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

import archaeology_bridge

_log = logging.getLogger('scriptura.archaeology')

_TEXT_W = 680    # comfortable reading measure
_IMG_W = 920     # images run wider than the text


class ArchaeologyReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._built = False
        self._chapter_anchors: dict[str, Gtk.Widget] = {}
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
        self._contents_btn = Gtk.MenuButton(
            icon_name='view-list-symbolic', tooltip_text='Contents')
        self._contents_btn.add_css_class('flat')
        self._contents_pop = Gtk.Popover()
        self._contents_btn.set_popover(self._contents_pop)
        bar.append(Gtk.Box(hexpand=True))
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

    @staticmethod
    def _clamp(child, width):
        c = Adw.Clamp(maximum_size=width, tightening_threshold=int(width * 0.85))
        c.set_child(child)
        return c

    @staticmethod
    def _label(text, css, selectable=False, xalign=0):
        lbl = Gtk.Label(label=text, xalign=xalign, wrap=True)
        lbl.add_css_class(css)
        if selectable:
            lbl.set_selectable(True)
        return lbl

    # ── rendering ─────────────────────────────────────────────────────────────
    def render(self):
        """Build the document once (idempotent)."""
        if self._built:
            return
        doc = archaeology_bridge.document()

        self._page.append(self._clamp(self._frontispiece(doc), _TEXT_W))
        for chap in doc['chapters']:
            if not chap['entries']:
                continue
            divider = self._clamp(self._era_divider(chap['title']), _TEXT_W)
            self._chapter_anchors[chap['id']] = divider
            self._page.append(divider)
            for entry in chap['entries']:
                self._page.append(self._plate(entry))

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

    def _era_divider(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-era')
        box.append(self._label(title, 'stone-era-title'))
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
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
        plate.append(self._clamp(pic, _IMG_W))

        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        txt.add_css_class('stone-text')
        txt.append(self._label(entry['title'], 'stone-title', selectable=True))

        meta_bits = [b for b in (entry['place'], entry['date'],
                                 entry['holding']) if b]
        if meta_bits:
            txt.append(self._label(' · '.join(meta_bits), 'stone-meta',
                                   selectable=True))

        txt.append(self._label(entry['caption'], 'stone-caption', selectable=True))

        if entry['refs']:
            chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            chips.add_css_class('stone-chips')
            lead = self._label('Attests', 'stone-chips-lead')
            lead.set_valign(Gtk.Align.CENTER)
            chips.append(lead)
            for ref in entry['refs']:
                chips.append(self._verse_chip(ref))
            txt.append(chips)

        if entry['credit']:
            txt.append(self._label(entry['credit'], 'stone-credit',
                                   selectable=True))
        plate.append(self._clamp(txt, _TEXT_W))
        return plate

    def _verse_chip(self, ref):
        btn = Gtk.Button(label=ref['label'])
        btn.add_css_class('stone-chip')
        btn.set_tooltip_text(f'Open {ref["label"]} in the Bible pane')
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
