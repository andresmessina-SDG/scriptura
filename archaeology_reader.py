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
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Graphene

import archaeology_bridge

_log = logging.getLogger('scriptura.archaeology')

_TEXT_W = 680    # comfortable reading measure
_IMG_W = 920     # images run wider than the text


class ArchaeologyReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._built = False
        self._chapter_anchors: dict[str, Gtk.Widget] = {}
        self._verse_anchors: dict[tuple, Gtk.Widget] = {}
        self._scroll_target = None
        self._scroll_tries = 0
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
        model.append('Copy', 'stonetext.copy')
        model.append('Select All', 'stonetext.select-all')
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

        self._page.append(self._clamp(self._frontispiece(doc), _TEXT_W))
        for chap in doc['chapters']:
            if not chap['entries']:
                continue
            divider = self._clamp(self._era_divider(chap['title']), _TEXT_W)
            self._chapter_anchors[chap['id']] = divider
            self._page.append(divider)
            for entry in chap['entries']:
                plate = self._plate(entry)
                self._page.append(plate)
                # Map each referenced verse to this plate, so a Bible 'related
                # artifact' marker can scroll the gallery straight to it.
                for r in entry['refs']:
                    self._verse_anchors[(r['book'], r['chapter'], r['verse'])] = plate

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
        GLib.timeout_add(1400, lambda: (w.remove_css_class('stone-flash')
                                        and False) or False)
        self._scroll_target = None
        return False
