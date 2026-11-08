import re

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gtk, GLib, Pango
import a11y
from a11y import set_accessible_label
from gtk_utils import clear_children, DelayedSpinner
import content
import settings
import sword_bridge
import tasks
from i18n import _, ngettext, book_label, current_language


def _set_names():
    """{set id: (name, one line on what it is)} for the chooser."""
    return {
        'openbible': (_('OpenBible'), _('340,000 links, ranked by readers’ votes')),
        'tsk': (_('Treasury'), _('The Treasury of Scripture Knowledge')),
        'ubs': (_('Parallels'), _('Parallel accounts and Old Testament quotations (UBS)')),
        'thompson': (_('Thompson'), _('Thompson’s chains, each link leading to the next')),
        'dictionaries': (_('Dictionaries'), _('Articles in your dictionaries that cite this verse')),
    }


class CrossRefPanel(Gtk.Box):
    def __init__(self, on_ref_clicked, on_close, on_ref_right_clicked=None, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._on_ref_clicked = on_ref_clicked
        self._on_close = on_close
        self._on_ref_right_clicked = on_ref_right_clicked
        self._build_ui()

    def _build_ui(self):
        # No separator rule — a faint .crossref-bar surface tint reads as a calm
        # tray attached to the reading page (matches the popover/search de-ruling).
        self.add_css_class('crossref-bar')

        # Single-row chips layout: source-verse eyebrow on the left, scrollable
        # outline chips in the middle, close button on the right.
        ref_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ref_row.set_margin_start(12)
        ref_row.set_margin_end(8)
        ref_row.set_margin_top(6)
        ref_row.set_margin_bottom(6)

        # The caption is the set chooser: "OpenBible · John 3:16 ⌄" opens a
        # small list of the sets this install has. With one set there is
        # nothing to choose, and it reads as a plain caption again.
        self._title = Gtk.Label(xalign=0)
        self._title.add_css_class('dim-label')
        self._title.add_css_class('caption')
        self._chevron = Gtk.Image.new_from_icon_name('scriptura-pan-down-symbolic')
        self._chevron.add_css_class('dim-label')
        self._chevron.set_pixel_size(12)
        caption = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        caption.append(self._title)
        caption.append(self._chevron)
        self._set_button = Gtk.MenuButton()
        self._set_button.set_child(caption)
        self._set_button.add_css_class('flat')
        self._set_button.add_css_class('crossref-set-button')
        self._set_button.set_valign(Gtk.Align.CENTER)
        set_pop = Gtk.Popover()
        set_pop.set_has_arrow(True)
        self._set_popover = set_pop
        self._set_list = Gtk.ListBox()
        self._set_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._set_list.add_css_class('navigation-sidebar')
        self._set_list.connect('row-activated', self._on_set_row_activated)
        set_pop.set_child(self._set_list)
        self._set_button.set_popover(set_pop)
        ref_row.append(self._set_button)
        self._compact = False
        self._sets = []
        self._active_set = None
        self._place = None
        self._article_pop = None
        self._module = None

        ref_scroll = Gtk.ScrolledWindow()
        # EXTERNAL (not AUTOMATIC) horizontally: no scrollbar is drawn — the slim
        # chips no longer hide it, and a bar across them read as strikethrough.
        ref_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        ref_scroll.set_hexpand(True)
        ref_scroll.set_valign(Gtk.Align.CENTER)
        self._ref_scroll = ref_scroll
        # With no scrollbar, drive horizontal scroll from the wheel/trackpad
        # ourselves — GTK won't translate a vertical wheel to horizontal here.
        wheel = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES)
        wheel.connect('scroll', self._on_wheel_scroll)
        ref_scroll.add_controller(wheel)
        self._ref_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        # A bare Box of chips reports as `generic`; as a named group an AT
        # user hears what the row of references belongs to.
        a11y.set_role(self._ref_box, Gtk.AccessibleRole.GROUP)
        a11y.labelled_by(self._ref_box, self._title)
        ref_scroll.set_child(self._ref_box)
        ref_row.append(ref_scroll)

        # Delayed loading indicator: a warm TSK/OpenBible lookup resolves
        # well under the perception threshold and never flashes it. Lives
        # beside the close button, not among the chips, so `_clear_refs`
        # can't sweep it away.
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self._spinner.set_valign(Gtk.Align.CENTER)
        ref_row.append(self._spinner)
        self._delayed_spinner = DelayedSpinner(self._spinner)

        close_btn = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.set_valign(Gtk.Align.CENTER)
        close_btn.set_tooltip_text(_('Hide cross-references'))
        set_accessible_label(close_btn, _('Hide cross-references'))
        close_btn.connect('clicked', lambda _: self._on_close())
        ref_row.append(close_btn)

        a11y.set_role(ref_row, Gtk.AccessibleRole.TOOLBAR)
        set_accessible_label(ref_row, _('Cross-references'))
        self.append(ref_row)

    def set_compact(self, compact):
        """Narrow windows: drop the 'Cross-references · Ref' eyebrow so the
        single-row bar spends its scarce width on the cross-ref chips rather
        than the title (which otherwise leaves room for one clipped chip).
        The current verse is already shown in the pane header."""
        # The chooser stays: only the verse drops out of it.
        self._compact = compact
        self._update_caption()

    def _on_wheel_scroll(self, _ctrl, dx, dy):
        # Map whichever axis the device reports onto the row's horizontal scroll.
        adj = self._ref_scroll.get_hadjustment()
        delta = dx if abs(dx) > abs(dy) else dy
        adj.set_value(adj.get_value() + delta * 60)
        return True

    def load(self, book, chapter, verse, module=None):
        """`module` is the Bible the verse was read in: its language ranks
        the dictionaries, ahead of the interface's."""
        if self._article_pop is not None:
            self._article_pop.popdown()   # its chip is about to go
        self._place = (book, chapter, verse)
        if module is not None:
            self._module = module
        langs = (content.language_code(self._module) if self._module else '',
                 content.normalise_language(current_language()))
        self._update_caption()
        self._clear_refs()
        self._delayed_spinner.start()

        # Latest-wins per panel: stepping verses faster than the TSK lookup
        # can't let an older verse's refs land over the newer ones, and a
        # raised lookup clears the spinner via the no-source message
        # instead of stranding it.
        tasks.submit(
            f'crossref:{id(self)}',
            lambda _t: self._lookup(book, chapter, verse, langs),
            self._show_lookup,
            on_error=lambda _exc: self._show_refs(None))

    @staticmethod
    def _lookup(book, chapter, verse, langs=()):
        """Worker thread: the sets on offer, the one to show, its refs."""
        sets = sword_bridge.crossref_sets(langs)
        pick = settings.get('crossref_set')
        active = pick if pick in sets else sword_bridge.default_crossref_set(sets)
        return sets, active, sword_bridge.get_cross_refs(
            book, chapter, verse, active, langs)

    def _show_lookup(self, result):
        sets, active, refs = result
        if sets != self._sets or active != self._active_set:
            self._sets, self._active_set = sets, active
            self._build_set_list()
            self._update_caption()
        return self._show_refs(refs)

    def _update_caption(self):
        names = _set_names()
        choosing = len(self._sets) > 1
        name = names[self._active_set][0] if self._active_set in names else ''
        if self._place:
            book, chapter, verse = self._place
            ref = f'{book_label(book)} {chapter}:{verse}'
        else:
            ref = ''
        if choosing:
            text = name if self._compact or not ref else \
                _('{set} · {ref}').format(set=name, ref=ref)
        else:
            text = _('Cross-references · {book} {chapter}:{verse}').format(
                book=book_label(self._place[0]), chapter=self._place[1],
                verse=self._place[2]) if self._place else _('Cross-references')
        self._title.set_text(text)
        self._chevron.set_visible(choosing)
        # The MenuButton's own toggle takes the clicks and the focus, so
        # that is the one to switch off: with one set, Tab must pass the
        # caption by and Enter must not open a list of one.
        toggle = self._set_button.get_first_child()
        for w in (self._set_button, toggle):
            w.set_can_target(choosing)
            w.set_focusable(choosing)
        self._set_button.set_visible(choosing or not self._compact)
        if choosing:
            tip = _('Cross-reference set: {name}').format(name=name)
            self._set_button.set_tooltip_text(tip)
            set_accessible_label(self._set_button, tip)
        else:
            self._set_button.set_tooltip_text(None)

    def _build_set_list(self):
        clear_children(self._set_list)
        names = _set_names()
        for set_id in self._sets:
            name, desc = names[set_id]
            row = Gtk.ListBoxRow()
            row._set_id = set_id
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hb.set_margin_start(6)
            hb.set_margin_end(6)
            hb.set_margin_top(4)
            hb.set_margin_bottom(4)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1,
                           hexpand=True)
            title = Gtk.Label(label=name, xalign=0)
            text.append(title)
            sub = Gtk.Label(label=desc, xalign=0)
            sub.add_css_class('dim-label')
            sub.add_css_class('caption')
            text.append(sub)
            hb.append(text)
            tick = Gtk.Image.new_from_icon_name('scriptura-object-select-symbolic')
            tick.set_opacity(1.0 if set_id == self._active_set else 0.0)
            hb.append(tick)
            row.set_child(hb)
            set_accessible_label(row, f'{name}. {desc}')
            # SELECTED is a tristate: GTK reads it as an int, not a bool.
            row.update_state([Gtk.AccessibleState.SELECTED],
                             [int(set_id == self._active_set)])
            self._set_list.append(row)

    def _on_set_row_activated(self, _listbox, row):
        self._set_popover.popdown()
        if row._set_id == self._active_set:
            return
        settings.put('crossref_set', row._set_id)
        if self._place:
            self.load(*self._place)

    def _clear_refs(self):
        clear_children(self._ref_box)

    def _show_refs(self, refs):
        self._delayed_spinner.stop()
        self._clear_refs()
        # The shipped parallels alone cover a few thousand verses: on the
        # rest, say where the full sets come from rather than "none found".
        only_parallels = self._sets == ['ubs']
        if refs is None or (only_parallels and not refs):
            msg = _('Install the TSK module or download OpenBible cross-references.')
            lbl = Gtk.Label(label=msg)
            lbl.add_css_class('dim-label')
            self._ref_box.append(lbl)
            a11y.announce(self._title, msg)
        elif not refs:
            msg = _('No cross-references found.')
            lbl = Gtk.Label(label=msg)
            lbl.add_css_class('dim-label')
            self._ref_box.append(lbl)
            a11y.announce(self._title, msg)
        else:
            # The chips appear silently beside the reading text; say how many
            # arrived so the count is not a purely visual fact.
            if isinstance(refs[0], sword_bridge.Article):
                said = ngettext('{n} article', '{n} articles', len(refs))
            else:
                said = ngettext('{n} cross-reference', '{n} cross-references',
                                len(refs))
            a11y.announce(self._title, said.format(n=len(refs)))
            for ref in refs:
                if isinstance(ref, sword_bridge.Article):
                    self._ref_box.append(self._article_chip(ref))
                    continue
                ref_book, ref_ch, ref_v, label = ref[:4]
                # Thompson's links carry their chain: (short, full) heading.
                chain = ref[4:6] if len(ref) >= 6 else None
                # The label arrives already written — "Genesis 12:3" from
                # OpenBible, "Ge 1:2" from TSK — and both are English, because
                # both are built in a data layer that has no business knowing
                # the interface language. Under a Russian interface a chip
                # read "Genesis 12:3" beside «Бытие 1» in the pane. Rebuilt
                # here, at the point of display, and only when the catalogue
                # actually translates the name — so an English run keeps TSK's
                # compact abbreviations exactly as before.
                shown = book_label(ref_book)
                if shown != ref_book:
                    label = f'{shown} {ref_ch}:{ref_v}'
                if chain:
                    # "The Man of Sorrows → Mr 7:34": a long chain name is
                    # cut at its end, never the verse. Its width is fixed so
                    # a narrow bar scrolls the chips instead of crushing them.
                    name_lbl = Gtk.Label(label=chain[0])
                    if len(chain[0]) > 24:
                        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                        name_lbl.set_width_chars(22)
                        name_lbl.set_max_width_chars(22)
                    ref_lbl = Gtk.Label(label=_('→ {ref}').format(ref=label))
                    inner = Gtk.Box(spacing=4)
                    inner.append(name_lbl)
                    inner.append(ref_lbl)
                    btn = Gtk.Button()
                    btn.set_child(inner)
                    btn.set_tooltip_text(chain[1])
                    set_accessible_label(btn, _('{chain}, next: {ref}').format(
                        chain=chain[1], ref=label))
                else:
                    btn = Gtk.Button(label=label)
                btn.add_css_class('xref-chip')
                btn.connect('clicked', self._make_handler(ref_book, ref_ch, ref_v))
                if self._on_ref_right_clicked:
                    rc = Gtk.GestureClick.new()
                    rc.set_button(3)
                    rc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
                    rc.connect('pressed', self._make_right_handler(btn, ref_book, ref_ch, ref_v))
                    btn.add_controller(rc)
                self._ref_box.append(btn)
        return GLib.SOURCE_REMOVE

    def _article_chip(self, art):
        btn = Gtk.Button(label=art.label)
        btn.add_css_class('xref-chip')
        btn.connect('clicked', lambda b: self._open_article(b, art))
        return btn

    def _open_article(self, chip, art):
        """The article in a peek above its chip, built as the word peek
        builds one: serif headword, the dictionary named, the text."""
        pop = self._article_pop
        if pop is None:
            # Parented to the bar, not the chip: the chips are rebuilt on
            # every verse, and a popover must not outlive its parent.
            pop = Gtk.Popover()
            pop.set_parent(self)
            pop.set_position(Gtk.PositionType.TOP)
            self._article_pop = pop
        ok, bounds = chip.compute_bounds(self)
        rect = Gdk.Rectangle()
        if ok:
            rect.x, rect.y = int(bounds.get_x()), int(bounds.get_y())
            rect.width, rect.height = int(bounds.get_width()), int(bounds.get_height())
        pop.set_pointing_to(rect)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root = self.get_root()
        win_w = root.get_width() if root is not None else 0
        body.set_size_request(360 if win_w <= 0 else max(260, min(360, win_w - 24)), -1)
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        spinner.set_margin_top(28)
        spinner.set_margin_bottom(28)
        body.append(spinner)
        pop.set_child(body)
        pop.popup()
        title = art.label.split(' · ', 1)[-1]
        source = art.label.split(' · ', 1)[0]

        def show(raw):
            if pop.get_child() is not body:
                return GLib.SOURCE_REMOVE   # a newer article took the peek
            clear_children(body)
            head = Gtk.Label(label=title, xalign=0)
            head.add_css_class('dict-headword')
            head.set_ellipsize(Pango.EllipsizeMode.END)
            head.set_margin_start(18)
            head.set_margin_end(18)
            head.set_margin_top(10)
            head.set_margin_bottom(2)
            body.append(head)
            cap = Gtk.Label(label=source, xalign=0)
            cap.add_css_class('caption')
            cap.add_css_class('dim-label')
            cap.set_margin_start(18)
            cap.set_margin_bottom(6)
            body.append(cap)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_propagate_natural_height(True)
            scroll.set_max_content_height(320)
            scroll.set_min_content_height(140)
            tv = Gtk.TextView(editable=False, cursor_visible=False,
                              wrap_mode=Gtk.WrapMode.WORD)
            tv.set_left_margin(18)
            tv.set_right_margin(18)
            tv.set_top_margin(4)
            tv.set_bottom_margin(14)
            tv.set_pixels_below_lines(3)
            tv.set_pixels_inside_wrap(3)
            from pane import _html_to_markup
            from pane_peek import _strip_leading_headword
            html = _strip_leading_headword(raw or '', title)
            buf = tv.get_buffer()
            try:
                buf.insert_markup(buf.get_end_iter(), _html_to_markup(
                    html, Adw.StyleManager.get_default().get_dark()), -1)
            except Exception:
                buf.set_text(re.sub(r'<[^>]+>', '', html))
            scroll.set_child(tv)
            body.append(scroll)
            return GLib.SOURCE_REMOVE

        import verse_articles
        tasks.submit(f'crossref-article:{id(self)}',
                     lambda _t: verse_articles.article_text(art.module, art.key, art.nth),
                     show, on_error=lambda _e: show(''))

    def _make_handler(self, book, chapter, verse):
        return lambda _: self._on_ref_clicked(book, chapter, verse)

    def _make_right_handler(self, widget, book, chapter, verse):
        def handler(gesture, n_press, x, y):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._on_ref_right_clicked(book, chapter, verse, widget)
        return handler
