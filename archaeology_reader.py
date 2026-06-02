"""archaeology_reader.py — the "Scripture in Stone" pane subsystem.

Renders the bundled archaeology gallery (archaeology_bridge) as a short
illustrated book: a frontispiece, then artifacts grouped into era "chapters"
in biblical sequence. Each artifact is a plate (image · title · provenance ·
caption) followed by tappable verse chips; clicking a chip drives the Bible
pane to that passage via the pane's word-study navigation callback (the same
channel a Strong's link uses → window._go_to).

Unlike the imagery/catena readers it is NOT verse-keyed — it's a standalone
document you open and read, so it ignores the partnered Bible's navigation and
renders once. A Contents button jumps between chapters. Mirrors the
compose-and-drive shape of the other pane subsystems.
"""

import logging

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

import archaeology_bridge

_log = logging.getLogger('scriptura.archaeology')


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
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        bar.append(self._contents_btn)
        self._root.append(bar)

        self._scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._page.add_css_class('stone-page')
        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=560)
        clamp.set_child(self._page)
        self._scroller.set_child(clamp)
        self._root.append(self._scroller)

    # ── rendering ─────────────────────────────────────────────────────────────
    def render(self):
        """Build the document once (idempotent)."""
        if self._built:
            return
        doc = archaeology_bridge.document()

        self._page.append(self._frontispiece(doc))
        for chap in doc['chapters']:
            if not chap['entries']:
                continue
            divider = self._era_divider(chap['title'])
            self._chapter_anchors[chap['id']] = divider
            self._page.append(divider)
            for entry in chap['entries']:
                self._page.append(self._plate(entry))

        self._build_contents(doc)
        self._built = True

    def _frontispiece(self, doc):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-front')
        title = Gtk.Label(label=doc['title'], xalign=0, wrap=True)
        title.add_css_class('stone-front-title')
        box.append(title)
        if doc['subtitle']:
            sub = Gtk.Label(label=doc['subtitle'], xalign=0, wrap=True)
            sub.add_css_class('stone-front-sub')
            box.append(sub)
        if doc['body']:
            for para in doc['body'].split('\n\n'):
                p = Gtk.Label(label=para.strip(), xalign=0, wrap=True)
                p.add_css_class('stone-front-body')
                box.append(p)
        return box

    def _era_divider(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-era')
        lbl = Gtk.Label(label=title, xalign=0, wrap=True)
        lbl.add_css_class('stone-era-title')
        box.append(lbl)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        return box

    def _plate(self, entry):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('stone-plate')

        pic = Gtk.Picture()
        pic.set_filename(archaeology_bridge.image_path(entry['image']))
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_can_shrink(True)
        pic.set_hexpand(True)
        pic.set_size_request(-1, 380)          # uniform plate band
        pic.set_alternative_text(entry['title'])
        pic.add_css_class('stone-pic')
        box.append(pic)

        title = Gtk.Label(label=entry['title'], xalign=0, wrap=True)
        title.add_css_class('stone-title')
        box.append(title)

        meta_bits = [b for b in (entry['place'], entry['date'],
                                 entry['holding']) if b]
        if meta_bits:
            meta = Gtk.Label(label=' · '.join(meta_bits), xalign=0, wrap=True)
            meta.add_css_class('stone-meta')
            box.append(meta)

        cap = Gtk.Label(label=entry['caption'], xalign=0, wrap=True)
        cap.add_css_class('stone-caption')
        box.append(cap)

        if entry['refs']:
            chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            chips.add_css_class('stone-chips')
            lead = Gtk.Label(label='Attests', xalign=0)
            lead.add_css_class('stone-chips-lead')
            chips.append(lead)
            for ref in entry['refs']:
                chips.append(self._verse_chip(ref))
            box.append(chips)

        if entry['credit']:
            credit = Gtk.Label(label=entry['credit'], xalign=0, wrap=True)
            credit.add_css_class('stone-credit')
            box.append(credit)
        return box

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
