"""The menu's Appearance page, and every handler behind it.

What you judge by eye on the text: font, size, spacing, width, the paper and
ink colours, letter spacing, and the switches that change how the letters
look. It is a second page of the side panel so the page stays in view while
you set it; the settings you set once and live with are in preferences.py.

A mixin on BibleWindow, moved out of window.py verbatim: every method still
runs on the window and reads the same attributes (pane1, pane2, the scales and
labels it builds), so callers elsewhere — the keyboard zoom, the theme flip —
are unchanged.
"""

import gi
gi.require_version('PangoCairo', '1.0')
from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

import settings  # noqa: E402
from a11y import set_accessible_label  # noqa: E402
from i18n import N_, _  # noqa: E402
from pane import (DROPCAP_GOLD_DARK, DROPCAP_GOLD_LIGHT, auto_reading_ink,  # noqa: E402
                  dropcap_color_hex, valid_paper)

#: The bundled dyslexia-preference face. Its family name is also its Reserved
#: Font Name under the OFL, so this string is the font, the settings value and
#: the label all at once — it must never be translated.
OPEN_DYSLEXIC = 'OpenDyslexic'


class AppearancePageMixin:
    """The Appearance page's builders and handlers, for BibleWindow."""

    def _build_appearance_page(self):
        """The Appearance page of the menu: font, size, spacing, width,
        colour, and the switches that change how the letters look."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class('card')
        card.add_css_class('appearance-card')
        card.set_margin_start(12)
        card.set_margin_end(12)
        card.set_margin_top(6)
        card.set_margin_bottom(8)

        def _row(label_text):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=label_text, xalign=0)
            lbl.set_size_request(64, -1)
            r.append(lbl)
            return r

        # Font family — all installed system fonts, with OpenDyslexic promoted.
        # It is bundled precisely so a reader who wants it does not have to go
        # and find one, and leaving it in the alphabetical run of every
        # installed face would waste that: nobody scrolls three hundred names
        # hoping. Filtered out of the run below so it appears exactly once.
        font_row = _row(_('Font'))
        _prefix_labels = [_('System Serif'), _('System Sans-Serif'),
                          OPEN_DYSLEXIC]
        _prefix_css    = ['serif', 'sans-serif', OPEN_DYSLEXIC]
        _installed = sorted(
            f.get_name()
            for f in PangoCairo.FontMap.get_default().list_families()
            if f.get_name() != OPEN_DYSLEXIC
        )
        self._font_css_names = _prefix_css + _installed
        cur_family = settings.get('font_family') or 'serif'
        try:
            font_idx = self._font_css_names.index(cur_family)
        except ValueError:
            font_idx = 0
        self._font_drop = Gtk.DropDown(
            model=Gtk.StringList.new(_prefix_labels + _installed))
        self._font_drop.set_hexpand(True)
        self._font_drop.set_enable_search(True)
        self._font_drop.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, 'string'))
        self._font_drop.set_selected(font_idx)
        # Ellipsize the button's own label. Without a factory the DropDown's
        # minimum width is the name it is showing, and this model holds every
        # installed family — so one long font name set the minimum width of
        # the appearance card, and through it of the whole menu panel. The
        # list factory is left alone: the popover has room to spell names out,
        # and that is where you are choosing between them.
        _font_btn_factory = Gtk.SignalListItemFactory()
        _font_btn_factory.connect(
            'setup', lambda _f, i: i.set_child(
                Gtk.Label(xalign=0, hexpand=True,
                          ellipsize=Pango.EllipsizeMode.END,
                          max_width_chars=18)))
        _font_btn_factory.connect(
            'bind', lambda _f, i: i.get_child().set_label(
                i.get_item().get_string()))
        self._font_drop.set_factory(_font_btn_factory)
        # A plain factory answers for BOTH the button and the popover rows, so
        # the popover needs its own or the names ellipsize there too — the one
        # place they must not (church_drop above splits the two the same way).
        _font_list_factory = Gtk.SignalListItemFactory()
        _font_list_factory.connect(
            'setup', lambda _f, i: i.set_child(Gtk.Label(xalign=0)))
        _font_list_factory.connect(
            'bind', lambda _f, i: i.get_child().set_label(
                i.get_item().get_string()))
        self._font_drop.set_list_factory(_font_list_factory)
        # The truncated name in full, on hover. "System Sans-Serif" is 130px
        # in the ~118px the button has for its label, so English truncates
        # here too — this is not a translation problem, it is a row that
        # carries a label, a dropdown and two toggles in one line.
        def _font_tip(drop, *_a):
            item = drop.get_selected_item()
            drop.set_tooltip_text(item.get_string() if item else None)
        self._font_drop.connect('notify::selected', _font_tip)
        _font_tip(self._font_drop)
        self._font_drop.connect('notify::selected', self._on_appear_font)
        font_row.append(self._font_drop)
        # Bold + Justify ride the Font row as compact icon toggles (linked pair),
        # so they cost no extra vertical row; the dropdown narrows to make room.
        style_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        style_box.add_css_class('linked')
        style_box.add_css_class('appear-style-toggles')
        self._bold_btn = Gtk.ToggleButton(icon_name='scriptura-format-text-bold-symbolic')
        self._bold_btn.set_tooltip_text(_('Bold'))
        set_accessible_label(self._bold_btn, _('Bold'))
        self._bold_btn.set_active(bool(settings.get('font_bold')))
        self._bold_btn.connect('toggled', self._on_appear_bold)
        self._justify_btn = Gtk.ToggleButton(icon_name='scriptura-justify-symbolic')
        self._justify_btn.set_tooltip_text(_('Justified'))
        set_accessible_label(self._justify_btn, _('Justified'))
        self._justify_btn.set_active(bool(settings.get('font_justify')))
        self._justify_btn.connect('toggled', self._on_appear_justify)
        style_box.append(self._bold_btn)
        style_box.append(self._justify_btn)
        font_row.append(style_box)
        card.append(font_row)

        # The honest framing rides with the choice rather than sitting in the
        # UI as a permanent claim: shown only while OpenDyslexic is the
        # selection. The evidence does not support calling it a remedy (a 2017
        # Annals of Dyslexia study found no reading-rate gain over Arial or
        # Times), and readers who prefer it prefer it anyway — both halves have
        # to be said, or shipping the font makes a promise for it.
        self._dyslexic_note = Gtk.Label(
            label=_('A preference, not a remedy: testing has found no gain in '
                    'reading speed. Readers who find it easier find it easier '
                    'all the same.'),
            xalign=0, wrap=True)
        self._dyslexic_note.add_css_class('dim-label')
        self._dyslexic_note.add_css_class('caption')
        self._dyslexic_note.set_visible(cur_family == OPEN_DYSLEXIC)
        card.append(self._dyslexic_note)

        # Font size
        size_row = _row(_('Size'))
        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 8, 26, 0.5)
        self._size_scale.set_hexpand(True)
        self._size_scale.set_draw_value(False)
        set_accessible_label(self._size_scale, _('Font size'))
        self._size_scale.set_value(settings.get('font_size'))
        self._size_val_lbl = Gtk.Label(
            label=f'{settings.get("font_size"):.0f}pt')
        self._size_val_lbl.set_size_request(36, -1)
        self._size_scale_handler = self._size_scale.connect(
            'value-changed', self._on_appear_size)
        size_row.append(self._size_scale)
        size_row.append(self._size_val_lbl)
        card.append(size_row)

        # Line spacing
        spacing_row = _row(_('Spacing'))
        self._spacing_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1.0, 2.5, 0.1)
        self._spacing_scale.set_hexpand(True)
        self._spacing_scale.set_draw_value(False)
        set_accessible_label(self._spacing_scale, _('Line spacing'))
        self._spacing_scale.set_value(settings.get('line_spacing'))
        self._spacing_val_lbl = Gtk.Label(
            label=f'{settings.get("line_spacing"):.1f}×')
        self._spacing_val_lbl.set_size_request(36, -1)
        self._spacing_scale.connect('value-changed', self._on_appear_spacing)
        spacing_row.append(self._spacing_scale)
        spacing_row.append(self._spacing_val_lbl)
        card.append(spacing_row)

        # Reading column width — wider monitors benefit from a wider column.
        width_row = _row(_('Width'))
        self._width_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 540, 1600, 20)
        self._width_scale.set_hexpand(True)
        self._width_scale.set_draw_value(False)
        set_accessible_label(self._width_scale, _('Reading column width'))
        _cur_w = int(settings.get('reading_width') or 540)
        self._width_scale.set_value(_cur_w)
        self._width_val_lbl = Gtk.Label(label=f'{_cur_w}px')
        self._width_val_lbl.set_size_request(48, -1)
        self._width_scale.connect('value-changed', self._on_appear_width)
        width_row.append(self._width_scale)
        width_row.append(self._width_val_lbl)
        card.append(width_row)

        # ── Colour: one row of theme chips ────────────────────────────────────
        # Each chip previews its pairing — the paper name drawn in that paper's
        # auto ink, on the paper fill. Selecting one sets the paper and returns
        # the ink to auto; the dashed Custom chip opens a popover to override
        # text and/or paper. Built per active scheme by _rebuild_colour_row;
        # rebuilt on theme change via _apply_mode_theme.
        card.append(Gtk.Separator())
        colour_cap = Gtk.Label(label=_('Colour'), xalign=0)
        colour_cap.add_css_class('paper-caption')
        card.append(colour_cap)
        self._paper_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=8, homogeneous=True, hexpand=True)
        card.append(self._paper_box)
        self._rebuild_colour_row()

        card.append(Gtk.Separator())
        card.append(self._build_type_switches())
        return card

    def _build_type_switches(self):
        # ── The switches that change how the letters look ─────────────────
        # Three ship on: section headings, small caps, the coloured drop cap.
        # Behaviour switches (hover preview, the sense-unit mark, Evening
        # paper, spoken readings) are in Preferences: they change what the
        # page does, not how the type looks, so nothing about them needs the
        # page in view while they are set.
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Letter spacing leads, ahead of the taste toggles. Widening
        # tracking is the best-replicating readability lever there is — better
        # than any dyslexia face — and a reader who is struggling should not
        # have to pass nine typographic preferences to reach it. The scale
        # runs to 20% so WCAG 1.4.12's 12% is comfortably inside it.
        letter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        letter_row.append(Gtk.Label(label=_('Letter spacing'), xalign=0))
        self._letter_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 0.20, 0.01)
        self._letter_scale.set_hexpand(True)
        self._letter_scale.set_draw_value(False)
        set_accessible_label(self._letter_scale, _('Letter spacing'))
        _cur_tracking = float(settings.get('letter_spacing') or 0.0)
        self._letter_scale.set_value(_cur_tracking)
        self._letter_val_lbl = Gtk.Label(
            label=self._tracking_label(_cur_tracking))
        self._letter_val_lbl.set_size_request(52, -1)
        self._letter_scale.connect('value-changed',
                                   self._on_appear_letter_spacing)
        letter_row.append(self._letter_scale)
        letter_row.append(self._letter_val_lbl)
        adv_box.append(letter_row)

        def _adv_apply(key, active, setter_name):
            settings.put(key, active)
            for pane in (self.pane1, self.pane2):
                getattr(pane, setter_name)(active)

        def _adv_switch(label_text, key, setter_name, extra=None):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = Gtk.Label(label=label_text, xalign=0)
            # Wrap, and cap the natural width, or a long row title decides how
            # wide the whole menu is. The panel takes its width from its
            # content (see _build_menu_panel), so under Russian — where
            # "Evening paper (follows Night Light)" becomes «Вечерняя бумага
            # (следует за ночной подсветкой)» — opening Advanced shoved the
            # entire sidebar ~65px wider, and closing it snapped back.
            #
            # 30 is measured, not guessed: at 30 chars the widest English row
            # still sets on one line (244px, its natural width) while the
            # widest Russian one drops from 360px to 269px. A tighter cap
            # starts wrapping English rows for no gain.
            title.set_wrap(True)
            title.set_max_width_chars(30)
            title.set_hexpand(True)
            r.append(title)
            if extra is not None:
                r.append(extra)
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            sw.set_active(bool(settings.get(key)))
            set_accessible_label(sw, label_text)
            sw.connect('notify::active',
                       lambda s, _p: _adv_apply(key, s.get_active(),
                                                setter_name))
            r.append(sw)
            adv_box.append(r)
            return sw

        _adv_switch(_('Section headings'),
                    'show_headings', 'set_show_headings')
        _adv_switch(_('Small caps for the divine name'),
                    'smallcaps_divine', 'set_divine_smallcaps')
        _adv_switch(_('Old-style numerals'),
                    'oldstyle_numerals', 'set_oldstyle_numerals')
        _adv_switch(_('Flush poetry indents'),
                    'poetry_flush', 'set_poetry_flush')
        # Drop-cap row carries a swatch of the effective cap colour (gold
        # default; popover offers gold / custom), shown only while active.
        self._dropcap_swatch = Gtk.Button()
        self._dropcap_swatch.add_css_class('flat')
        self._dropcap_swatch.set_valign(Gtk.Align.CENTER)
        self._dropcap_swatch.set_tooltip_text(_('Drop cap colour'))
        set_accessible_label(self._dropcap_swatch, _('Drop cap colour'))
        _sw_box = Gtk.Box()
        _sw_box.add_css_class('mini-swatch')
        _sw_box.set_size_request(18, 18)
        self._dropcap_swatch_css = Gtk.CssProvider()
        _sw_box.get_style_context().add_provider(
            self._dropcap_swatch_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._dropcap_swatch.set_child(_sw_box)
        self._dropcap_swatch.set_visible(bool(settings.get('colored_dropcap')))
        self._dropcap_swatch.connect('clicked', self._on_dropcap_swatch)
        self._update_dropcap_swatch()
        cap_sw = _adv_switch(_('Coloured drop cap'),
                             'colored_dropcap', 'set_colored_dropcap',
                             extra=self._dropcap_swatch)
        cap_sw.connect(
            'notify::active',
            lambda s, _p: self._dropcap_swatch.set_visible(s.get_active()))
        return adv_box

    def _on_appear_font(self, drop, _):
        idx = drop.get_selected()
        family = self._font_css_names[idx] if idx < len(self._font_css_names) else 'serif'
        settings.put('font_family', family)
        self._dyslexic_note.set_visible(family == OPEN_DYSLEXIC)
        self.pane1.set_appearance(font_family=family)
        self.pane2.set_appearance(font_family=family)

    @staticmethod
    def _tracking_label(value):
        """0 is the face's own metrics rather than a quantity of nothing, so
        it says so — the other rows in this panel read 12pt, 1.5×, 540px, and
        '0%' there would look like a setting the reader had turned down."""
        return _('Normal') if not value else f'{value * 100:.0f}%'

    def _on_appear_letter_spacing(self, scale):
        val = round(scale.get_value(), 2)
        settings.put('letter_spacing', val)
        self._letter_val_lbl.set_text(self._tracking_label(val))
        self.pane1.set_appearance(letter_spacing=val)
        self.pane2.set_appearance(letter_spacing=val)

    # Curated reading "papers" per resolved appearance: (label, swatch, store).
    # Default stores None (warm paper in light, @view_bg_color in dark). Light
    # papers use the leading readers' values — Apple Books off-white #fbfbfb
    # (pure #fff glares) and warm gold sepia #f8f1e3, plus a restful pale-green.
    # The reading ink is auto-derived from the paper (auto_reading_ink), so each
    # chip previews its pairing — the paper name in that paper's ink — without a
    # separate ink list. Labels N_()-marked for extraction, translated at build.
    _PAPER_LIGHT = [
        (N_('Paper'), '#f7f4ee', None),
        (N_('White'), '#fbfbfb', '#fbfbfb'),
        (N_('Sepia'), '#f8f1e3', '#f8f1e3'),
        (N_('Green'), '#dce8d0', '#dce8d0'),
    ]
    _PAPER_DARK = [
        (N_('Slate'),    '#1e1e1e', None),
        (N_('Charcoal'), '#2a2622', '#2a2622'),
        (N_('Black'),    '#000000', '#000000'),
    ]

    def _current_mode_key(self):
        return f'text_color_{settings.get("color_scheme") or "default"}'

    def _current_bg_key(self):
        return f'reading_bg_{settings.get("color_scheme") or "default"}'

    def _resolved_dark(self):
        # Explicit schemes resolve deterministically; System follows appearance.
        scheme = settings.get('color_scheme') or 'default'
        if scheme == 'light':
            return False
        if scheme == 'dark':
            return True
        return Adw.StyleManager.get_default().get_dark()

    def _papers(self):
        return self._PAPER_DARK if self._resolved_dark() else self._PAPER_LIGHT

    @staticmethod
    def _ink_for(hex_bg):
        """Pick a legible label ink (warm-dark or warm-light) for a swatch fill
        by its perceived luminance."""
        r, g, b = (int(hex_bg[i:i + 2], 16) for i in (1, 3, 5))
        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return '#2b2620' if lum > 0.55 else '#e8e0d4'

    def _make_swatch(self, label, fill_hex, ink_hex, size, tooltip, on_click,
                     extra_class=None):
        """A round colour chip: `fill_hex` background, `label` drawn in `ink_hex`
        (a paper name in that paper's ink). Fixed square + centred so it stays
        circular in its homogeneous cell."""
        btn = Gtk.Button(label=label)
        btn.add_css_class('paper-swatch')
        for cls in (extra_class or '').split():
            btn.add_css_class(cls)
        btn.set_size_request(size, size)
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(tooltip)
        set_accessible_label(btn, tooltip)
        prov = Gtk.CssProvider()
        prov.load_from_data(
            (f'button.paper-swatch {{ background-color: {fill_hex}; '
             f'color: {ink_hex}; }}').encode())
        btn.get_style_context().add_provider(
            prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        btn.connect('clicked', on_click)
        return btn

    def _rebuild_colour_row(self):
        """One row of theme chips for the active scheme. Each preset chip shows
        its paper name in that paper's auto ink, on the paper fill — so the chip
        previews the whole pairing. The active paper rings it; a custom text or
        paper instead rings the dashed Custom chip, which opens a popover to
        override either colour."""
        # The drop-cap swatch is scheme-sensitive too (gold default differs
        # per scheme); it builds after the colour row, hence the guard.
        if getattr(self, '_dropcap_swatch_css', None) is not None:
            self._update_dropcap_swatch()
        child = self._paper_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._paper_box.remove(child)
            child = nxt
        paper_stored = valid_paper(settings.get(self._current_bg_key()))
        ink_stored = settings.get(self._current_mode_key())
        pnorm = (paper_stored or '').lower()
        papers = self._papers()
        preset_stores = {(v or '').lower() for _l, _s, v in papers}
        # "Custom" is active when the ink is overridden, or the paper is off-preset.
        custom = bool(ink_stored) or (bool(paper_stored) and pnorm not in preset_stores)
        for label, sw, val in papers:
            chip = self._make_swatch(
                _(label), sw, auto_reading_ink(sw), 56, _(label),
                lambda b, v=val: self._on_paper_preset(v))
            if not custom and (val or '').lower() == pnorm:
                chip.add_css_class('selected')
            self._paper_box.append(chip)
        # Dashed Custom chip: previews the active custom combo, or a neutral
        # opener. Click → popover to set a custom text and/or paper colour.
        if custom:
            eff_paper = paper_stored or papers[0][1]
            ccustom = self._make_swatch(
                _('Custom'), eff_paper, ink_stored or auto_reading_ink(eff_paper),
                56, _('Custom colours'), self._on_custom_clicked,
                extra_class='custom-swatch')
            ccustom.add_css_class('selected')
        else:
            neutral = '#3a3a3a' if self._resolved_dark() else '#e0ddd6'
            ccustom = self._make_swatch(
                _('Custom'), neutral, self._ink_for(neutral), 56,
                _('Custom colours'), self._on_custom_clicked,
                extra_class='custom-swatch')
        self._paper_box.append(ccustom)

    def _apply_paper(self, value):
        settings.put(self._current_bg_key(), value)
        self.pane1.set_appearance(bg_color=value)
        self.pane2.set_appearance(bg_color=value)

    def _apply_ink(self, value):
        settings.put(self._current_mode_key(), value)
        self.pane1.set_appearance(text_color=value)
        self.pane2.set_appearance(text_color=value)

    def _on_paper_preset(self, store_val):
        # A preset is a coordinated theme: set the paper and return ink to auto.
        self._apply_paper(store_val)
        self._apply_ink(None)
        self._rebuild_colour_row()

    def _on_custom_clicked(self, btn):
        # The single Custom chip fans out to either override via a mini-picker:
        # a live "Aa" preview of the current combo over a Text and a Paper row,
        # each showing the current colour and opening the colour dialog. The
        # dialog is parented to the window (not the popover), so dismissing the
        # popover can't orphan it; unparent is deferred to idle to avoid
        # destroying a row mid-click.
        paper_stored = valid_paper(settings.get(self._current_bg_key()))
        ink_stored = settings.get(self._current_mode_key())
        eff_paper = paper_stored or self._papers()[0][1]
        eff_ink = ink_stored or auto_reading_ink(eff_paper)

        pop = Gtk.Popover()
        pop.set_parent(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(8)

        preview = Gtk.Label(label=_('Aa'))
        preview.add_css_class('custom-preview')
        pv = Gtk.CssProvider()
        pv.load_from_data(
            (f'label.custom-preview {{ background-color: {eff_paper}; '
             f'color: {eff_ink}; }}').encode())
        preview.get_style_context().add_provider(
            pv, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box.append(preview)

        box.append(self._custom_pick_row(
            eff_ink, _('Text colour'), self._on_ink_custom_clicked, pop))
        box.append(self._custom_pick_row(
            eff_paper, _('Paper colour'), self._on_paper_custom_clicked, pop))

        pop.set_child(box)
        pop.connect('closed', lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _custom_pick_row(self, colour, label, handler, pop):
        """A popover row: a swatch of the current colour + label; opens the
        colour dialog (window-parented) after dismissing the popover."""
        row = Gtk.Button()
        row.add_css_class('flat')
        row.add_css_class('custom-pick-row')
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sw = Gtk.Box()
        sw.add_css_class('mini-swatch')
        sw.set_size_request(18, 18)
        sw.set_valign(Gtk.Align.CENTER)
        prov = Gtk.CssProvider()
        prov.load_from_data(f'box.mini-swatch {{ background-color: {colour}; }}'.encode())
        sw.get_style_context().add_provider(
            prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        inner.append(sw)
        inner.append(Gtk.Label(label=label, xalign=0, hexpand=True))
        row.set_child(inner)
        row.connect('clicked', lambda _x: (pop.popdown(), handler(None)))
        return row

    def _update_dropcap_swatch(self):
        hexcol = dropcap_color_hex(Adw.StyleManager.get_default().get_dark())
        self._dropcap_swatch_css.load_from_data(
            f'box.mini-swatch {{ background-color: {hexcol}; }}'.encode())

    def _apply_dropcap_color(self, value):
        settings.put('dropcap_color', value)
        self._update_dropcap_swatch()
        self.pane1.refresh_dropcap_color()
        self.pane2.refresh_dropcap_color()

    def _on_dropcap_swatch(self, btn):
        # Same shape as the Custom-colours chip: a small popover of pick
        # rows; the colour dialog is window-parented so dismissing the
        # popover can't orphan it.
        dark = Adw.StyleManager.get_default().get_dark()
        pop = Gtk.Popover()
        pop.set_parent(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{m}')(4)
        gold = DROPCAP_GOLD_DARK if dark else DROPCAP_GOLD_LIGHT
        box.append(self._custom_pick_row(
            gold, _('Gold (default)'),
            lambda _b: self._apply_dropcap_color(None), pop))
        box.append(self._custom_pick_row(
            dropcap_color_hex(dark), _('Custom colour…'),
            self._on_dropcap_custom_clicked, pop))
        pop.set_child(box)
        pop.connect('closed', lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _on_dropcap_custom_clicked(self, btn):
        dialog = Gtk.ColorDialog()
        dialog.set_title(_('Drop cap colour'))
        initial = Gdk.RGBA()
        initial.parse(
            dropcap_color_hex(Adw.StyleManager.get_default().get_dark()))
        dialog.choose_rgba(self, initial, None, self._on_dropcap_custom_done)

    def _on_dropcap_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # dismissed
        self._apply_dropcap_color(self._rgba_hex(rgba))

    def _on_paper_custom_clicked(self, btn):
        dialog = Gtk.ColorDialog()
        dialog.set_title(_('Custom background colour'))
        initial = Gdk.RGBA()
        stored = settings.get(self._current_bg_key())
        if not (stored and initial.parse(stored)):
            initial.parse('#ffffff')
        dialog.choose_rgba(self, initial, None, self._on_paper_custom_done)

    def _on_paper_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # dismissed
        self._apply_paper(self._rgba_hex(rgba))
        self._rebuild_colour_row()

    def _on_ink_custom_clicked(self, btn):
        dialog = Gtk.ColorDialog()
        dialog.set_title(_('Custom text colour'))
        initial = Gdk.RGBA()
        stored = settings.get(self._current_mode_key())
        if not (stored and initial.parse(stored)):
            initial.parse('#000000')
        dialog.choose_rgba(self, initial, None, self._on_ink_custom_done)

    def _on_ink_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # dismissed
        self._apply_ink(self._rgba_hex(rgba))
        self._rebuild_colour_row()

    @staticmethod
    def _rgba_hex(rgba):
        return (f'#{round(rgba.red * 255):02x}'
                f'{round(rgba.green * 255):02x}'
                f'{round(rgba.blue * 255):02x}')

    def _apply_mode_theme(self):
        """Re-apply the active scheme's saved paper + ink to both panes and
        rebuild the colour row (called when the light/dark theme changes)."""
        bg = settings.get(self._current_bg_key())
        ink = settings.get(self._current_mode_key())
        for pane in (self.pane1, self.pane2):
            pane.set_appearance(bg_color=bg, text_color=ink)
        self._rebuild_colour_row()

    def _on_appear_theme(self, btn):
        self._theme_light.set_active(btn is self._theme_light)
        self._theme_dark.set_active(btn is self._theme_dark)
        self._theme_system.set_active(btn is self._theme_system)
        if btn is self._theme_light:
            scheme, adw = 'light', Adw.ColorScheme.FORCE_LIGHT
        elif btn is self._theme_dark:
            scheme, adw = 'dark', Adw.ColorScheme.FORCE_DARK
        else:
            scheme, adw = 'default', Adw.ColorScheme.DEFAULT
        settings.put('color_scheme', scheme)
        Adw.StyleManager.get_default().set_color_scheme(adw)
        self._apply_mode_theme()

    def _on_appear_size(self, scale):
        size = round(scale.get_value(), 1)
        settings.put('font_size', size)
        self._size_val_lbl.set_text(f'{size:.0f}pt')
        self.pane1.set_appearance(font_size=size)
        self.pane2.set_appearance(font_size=size)

    def _on_appear_spacing(self, scale):
        val = round(scale.get_value(), 1)
        settings.put('line_spacing', val)
        self._spacing_val_lbl.set_text(f'{val:.1f}×')
        self.pane1.set_appearance(line_spacing=val)
        self.pane2.set_appearance(line_spacing=val)

    def _on_appear_width(self, scale):
        px = int(round(scale.get_value() / 20.0) * 20)
        settings.put('reading_width', px)
        self._width_val_lbl.set_text(f'{px}px')
        self.pane1.set_reading_width(px)
        self.pane2.set_reading_width(px)

    def _on_appear_bold(self, btn):
        bold = btn.get_active()
        settings.put('font_bold', bold)
        self.pane1.set_appearance(font_bold=bold)
        self.pane2.set_appearance(font_bold=bold)

    def _on_appear_justify(self, btn):
        justify = btn.get_active()
        settings.put('font_justify', justify)
        self.pane1.set_appearance(font_justify=justify)
        self.pane2.set_appearance(font_justify=justify)
