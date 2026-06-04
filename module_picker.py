"""module_picker.py — the pane's module selector.

A MenuButton whose popover lists the installed modules (with a search
field and language chips), flips to a per-module info page, and offers
removal behind a confirmation. Extracted from BiblePane; it reaches back
to the pane for the module list, the active module, switching, and the
refresh/toast callbacks — the same composition style as LexiconPanel,
GenbookReader, CatenaReader, and PaneSearch.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango

import sword_bridge
import content


class ModulePicker:
    # Module languages never change at runtime. The chips call _lang_of()
    # for every module on every keystroke / chip toggle; uncached that's
    # many SWORD/SQLite probes. Class-level so all panes share the cache.
    _lang_cache: dict = {}

    def __init__(self, pane):
        self._pane = pane
        self._search = ''
        self._kind = 'all'
        self._lang = 'All'
        self._info_name = None
        self._build()

    # ── public surface used by the pane ───────────────────────────────────────

    @property
    def menu_button(self):
        return self._button

    def set_current_label(self, name):
        self._label.set_label(sword_bridge.display_name(name))

    @classmethod
    def invalidate_lang_cache(cls):
        cls._lang_cache.clear()

    # ── construction ──────────────────────────────────────────────────────────

    def _build(self):
        self._button = Gtk.MenuButton()
        self._button.set_hexpand(False)
        self._button.set_size_request(120, -1)
        self._button.add_css_class('flat')
        self._button.add_css_class('pane-module-button')
        self._label = Gtk.Label(
            label=sword_bridge.display_name(self._pane._module), xalign=0)
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self._label.set_max_width_chars(32)
        self._label.add_css_class('pane-module-title')
        label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        label_box.append(self._label)
        label_box.append(Gtk.Image.new_from_icon_name('pan-down-symbolic'))
        self._button.set_child(label_box)
        self._popover = self._build_popover()
        self._button.set_popover(self._popover)
        # Populate before the popover maps (not on its 'show' signal): building
        # the list afterwards resizes the popover post-map, which costs it the
        # autohide grab and leaves it stuck open on a click-away.
        self._button.set_create_popup_func(self._before_popup)

    def _before_popup(self, _button):
        self._refresh()

    def _build_popover(self):
        pop = Gtk.Popover()
        pop.set_has_arrow(True)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(150)
        # Let each page drive its own height so a short tab (one-item
        # Imagery) doesn't reserve the full list height of dead space.
        stack.set_vhomogeneous(False)
        self._stack = stack

        # ── List page ────────────────────────────────────────────────
        list_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        list_page.set_size_request(340, -1)
        list_page.set_margin_start(8)
        list_page.set_margin_end(8)
        list_page.set_margin_top(8)
        list_page.set_margin_bottom(8)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._search_entry = Gtk.SearchEntry(hexpand=True)
        self._search_entry.set_placeholder_text('Filter modules…')
        self._search_entry.connect('search-changed', self._on_search_changed)
        search_row.append(self._search_entry)

        # Language demoted to a filter menu — only ever shown for a
        # multilingual library (see _build_lang_menu).
        self._lang_button = Gtk.MenuButton(icon_name='scriptura-globe-symbolic')
        self._lang_button.add_css_class('flat')
        self._lang_button.set_tooltip_text('Filter by language')
        self._lang_button.set_valign(Gtk.Align.CENTER)
        lang_pop = Gtk.Popover()
        lang_pop.set_has_arrow(True)
        self._lang_popover = lang_pop
        self._lang_list = Gtk.ListBox()
        self._lang_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._lang_list.add_css_class('navigation-sidebar')
        self._lang_list.connect('row-activated', self._on_lang_row_activated)
        lang_pop.set_child(self._lang_list)
        self._lang_button.set_popover(lang_pop)
        search_row.append(self._lang_button)
        list_page.append(search_row)

        # Kind tabs (underline style). Built from the kinds actually installed.
        self._tabs_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._tabs_box.add_css_class('module-tabs')
        self._tabs_box.set_halign(Gtk.Align.CENTER)
        list_page.append(self._tabs_box)

        list_scroll = Gtk.ScrolledWindow(vexpand=True)
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # Shrink-to-fit: the popover follows the list's natural height up to
        # a cap, then scrolls — instead of a fixed 420 with empty space.
        list_scroll.set_propagate_natural_height(True)
        list_scroll.set_min_content_height(120)
        list_scroll.set_max_content_height(360)
        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.add_css_class('navigation-sidebar')
        self._listbox.add_css_class('module-list')
        self._listbox.connect('row-activated', self._on_row_activated)
        list_scroll.set_child(self._listbox)
        list_page.append(list_scroll)

        stack.add_named(list_page, 'list')

        # ── Info page ────────────────────────────────────────────────
        info_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info_page.set_size_request(340, -1)
        info_page.set_margin_start(8)
        info_page.set_margin_end(8)
        info_page.set_margin_top(8)
        info_page.set_margin_bottom(8)

        info_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        back_btn.add_css_class('flat')
        back_btn.set_tooltip_text('Back to list')
        back_btn.connect('clicked', lambda _b: stack.set_visible_child_name('list'))
        info_header.append(back_btn)
        self._info_title = Gtk.Label(xalign=0, hexpand=True)
        self._info_title.add_css_class('heading')
        self._info_title.set_wrap(True)
        info_header.append(self._info_title)
        info_page.append(info_header)
        info_page.append(Gtk.Separator())

        info_scroll = Gtk.ScrolledWindow(vexpand=True)
        info_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        info_scroll.set_propagate_natural_height(True)
        info_scroll.set_min_content_height(160)
        info_scroll.set_max_content_height(360)
        self._info_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_scroll.set_child(self._info_body)
        info_page.append(info_scroll)

        # Pinned at the bottom of the info page — deliberate, behind a
        # confirmation. Hidden for system modules and when this is the
        # pane's last remaining module.
        self._remove_btn = Gtk.Button()
        self._remove_btn.set_child(Adw.ButtonContent(
            icon_name='user-trash-symbolic', label='Remove module'))
        self._remove_btn.add_css_class('destructive-action')
        self._remove_btn.set_margin_top(4)
        self._remove_btn.connect('clicked', self._on_remove_clicked)
        info_page.append(self._remove_btn)

        stack.add_named(info_page, 'info')
        stack.set_visible_child_name('list')

        pop.set_child(stack)
        return pop

    # ── list page ──────────────────────────────────────────────────────────────

    # Kind tabs, in display order. The picker shows 'All' plus only the
    # kinds actually installed.
    _TAB_DEFS = [('all', 'All'), ('bible', 'Bibles'),
                 ('commentary', 'Commentary'), ('imagery', 'Imagery'),
                 ('books', 'Books')]
    # Section order + headers for the grouped 'All' view.
    _KIND_ORDER = ['bible', 'commentary', 'imagery', 'books']
    _KIND_HEADERS = {'bible': 'Translations', 'commentary': 'Commentary',
                     'imagery': 'Imagery', 'books': 'Books & Confessions'}
    # Collapse SWORD's redundant ISO variants so the language menu isn't
    # a wall of near-duplicates (en/eng, es/spa, la/lat).
    _LANG_NORMALIZE = {'eng': 'en', 'spa': 'es', 'lat': 'la',
                       'fra': 'fr', 'deu': 'de', 'ger': 'de'}
    _LANG_NAMES = {'All': 'All languages', 'en': 'English',
                   'enm': 'Middle English', 'es': 'Spanish', 'grc': 'Greek',
                   'la': 'Latin', 'ru': 'Russian', 'fr': 'French',
                   'de': 'German', 'he': 'Hebrew'}

    @staticmethod
    def _clear(container):
        child = container.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            container.remove(child)
            child = nxt

    def _lang_of(self, name):
        cached = self._lang_cache.get(name)
        if cached is not None:
            return cached
        raw = (content.language(name) or '').lower()
        norm = self._LANG_NORMALIZE.get(raw, raw)
        self._lang_cache[name] = norm
        return norm

    def _refresh(self):
        self._stack.set_visible_child_name('list')
        if self._search_entry.get_text():
            self._search_entry.set_text('')
        self._search = ''
        self._kind = 'all'
        self._build_tabs()
        self._build_lang_menu()
        self._rebuild_list()

    def _build_tabs(self):
        self._clear(self._tabs_box)
        kinds = {content.kind(name) for name in self._pane._names}
        present = [k for k, _ in self._TAB_DEFS if k == 'all' or k in kinds]
        if self._kind not in present:
            self._kind = 'all'

        # 'All' plus a single kind = nothing to filter; hide the bar.
        if len(present) <= 2:
            self._tabs_box.set_visible(False)
            self._kind = 'all'
            return
        self._tabs_box.set_visible(True)

        labels = dict(self._TAB_DEFS)
        for k in present:
            btn = Gtk.ToggleButton(label=labels[k])
            if k == self._kind:
                btn.set_active(True)
            btn.connect('toggled', self._on_tab_toggled, k)
            self._tabs_box.append(btn)

    def _on_tab_toggled(self, btn, kind_value):
        if not btn.get_active():
            # Enforce "exactly one active": snap the current tab back on.
            if self._kind == kind_value:
                btn.set_active(True)
            return
        if self._kind == kind_value:
            return
        self._kind = kind_value
        self._build_tabs()
        self._rebuild_list()

    def _build_lang_menu(self):
        self._clear(self._lang_list)
        langs = {self._lang_of(name) for name in self._pane._names}
        langs.discard('')

        # Single-language library: the menu is dead UI weight. Hide it.
        if len(langs) <= 1:
            self._lang_button.set_visible(False)
            self._lang = 'All'
            return
        self._lang_button.set_visible(True)
        self._lang_button.remove_css_class('accent')
        if self._lang != 'All':
            self._lang_button.add_css_class('accent')

        for v in ['All'] + sorted(langs):
            row = Gtk.ListBoxRow()
            row._lang_value = v
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hb.set_margin_start(8)
            hb.set_margin_end(8)
            hb.set_margin_top(4)
            hb.set_margin_bottom(4)
            lbl = Gtk.Label(
                label=self._LANG_NAMES.get(v, v), xalign=0, hexpand=True)
            hb.append(lbl)
            tick = Gtk.Image.new_from_icon_name('object-select-symbolic')
            tick.set_visible(v == self._lang)
            hb.append(tick)
            row.set_child(hb)
            self._lang_list.append(row)

    def _on_lang_row_activated(self, _listbox, row):
        self._lang = row._lang_value
        self._lang_popover.popdown()
        self._build_lang_menu()
        self._rebuild_list()

    def _on_search_changed(self, entry):
        self._search = entry.get_text().strip().lower()
        self._rebuild_list()

    def _rebuild_list(self):
        self._clear(self._listbox)

        q = self._search
        # Bucket matching modules by kind, preserving the pane's order.
        buckets: dict = {k: [] for k in self._KIND_ORDER}
        for name in self._pane._names:
            k = content.kind(name)
            if self._kind != 'all' and k != self._kind:
                continue
            if self._lang != 'All' and self._lang_of(name) != self._lang:
                continue
            if q and q not in name.lower() \
                    and q not in sword_bridge.display_name(name).lower():
                continue
            buckets.setdefault(k, []).append(name)

        grouped = self._kind == 'all'
        any_match = False
        for k in self._KIND_ORDER:
            names = buckets.get(k) or []
            if not names:
                continue
            any_match = True
            if grouped:
                self._listbox.append(self._make_header(self._KIND_HEADERS[k]))
            # Float the marquee packs to the top of their group so they're
            # the first thing seen, not buried after the plain modules.
            ordered = sorted(names, key=lambda n: content.feature_card(n) is None)
            for name in ordered:
                self._listbox.append(self._make_row(name))

        if not any_match:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            lbl = Gtk.Label(label='No modules match this filter.', xalign=0.5)
            lbl.add_css_class('dim-label')
            lbl.set_margin_start(12)
            lbl.set_margin_end(12)
            lbl.set_margin_top(20)
            lbl.set_margin_bottom(20)
            row.set_child(lbl)
            self._listbox.append(row)

    def _make_header(self, text):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        lbl = Gtk.Label(label=text.upper(), xalign=0)
        lbl.add_css_class('caption')
        lbl.add_css_class('dim-label')
        lbl.add_css_class('module-section-header')
        lbl.set_margin_start(8)
        lbl.set_margin_top(10)
        lbl.set_margin_bottom(2)
        row.set_child(lbl)
        return row

    def _info_button(self, name):
        btn = Gtk.Button(icon_name='dialog-information-symbolic')
        btn.add_css_class('flat')
        btn.add_css_class('circular')
        # Ghosted until the row is hovered/focused (see CSS) so the list
        # isn't a vertical rail of repeated info icons.
        btn.add_css_class('module-info-btn')
        btn.set_tooltip_text('Module info')
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect('clicked', lambda _b, _n=name: self._show_info(_n))
        return btn

    def _make_row(self, name):
        card = content.feature_card(name)
        if card:
            return self._make_feature_row(name, card)
        row = Gtk.ListBoxRow()
        row._module_name = name
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.set_margin_start(8)
        hb.set_margin_end(4)
        hb.set_margin_top(2)
        hb.set_margin_bottom(2)
        lbl = Gtk.Label(label=sword_bridge.display_name(name), xalign=0, hexpand=True)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        if name == self._pane._module:
            lbl.add_css_class('accent')
        hb.append(lbl)
        hb.append(self._info_button(name))
        row.set_child(hb)
        return row

    def _make_feature_row(self, name, card):
        """Richer row for the marquee packs — leading icon, curated title,
        and a one-line tagline — so they read as features, not list filler."""
        row = Gtk.ListBoxRow()
        row._module_name = name
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hb.set_margin_start(8)
        hb.set_margin_end(4)
        hb.set_margin_top(6)
        hb.set_margin_bottom(6)
        icon = Gtk.Image.new_from_icon_name(card['icon'])
        icon.add_css_class('module-feature-icon')
        icon.set_valign(Gtk.Align.CENTER)
        hb.append(icon)
        text = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
        title = Gtk.Label(label=sword_bridge.display_name(name), xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class('module-feature-title')
        if name == self._pane._module:
            title.add_css_class('accent')
        text.append(title)
        sub = Gtk.Label(label=card['tagline'], xalign=0)
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.add_css_class('caption')
        sub.add_css_class('dim-label')
        text.append(sub)
        hb.append(text)
        hb.append(self._info_button(name))
        row.set_child(hb)
        return row

    def _on_row_activated(self, _listbox, row):
        if not hasattr(row, '_module_name'):
            return
        name = row._module_name
        self._popover.popdown()
        if name != self._pane._module:
            self._pane._apply_module_change(name)

    # ── info page + removal ────────────────────────────────────────────────────

    def _show_info(self, name):
        self._info_title.set_label(name)
        self._info_name = name
        self._remove_btn.set_visible(self._can_remove(name))
        child = self._info_body.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._info_body.remove(child)
            child = nxt

        info = content.info(name)

        def _add_field(label, value, multiline=False):
            if not value:
                return
            cap = Gtk.Label(label=label, xalign=0)
            cap.add_css_class('caption')
            cap.add_css_class('dim-label')
            cap.set_margin_top(6)
            self._info_body.append(cap)
            val = Gtk.Label(label=str(value), xalign=0,
                            wrap=multiline, selectable=True)
            if multiline:
                val.set_max_width_chars(40)
            self._info_body.append(val)

        _add_field('Description', info.get('description', ''), multiline=True)
        _add_field('Language',    info.get('language', ''))
        _add_field('Version',     info.get('version', ''))
        _add_field('Type',        info.get('type', ''))
        _add_field('Copyright',   info.get('copyright', ''), multiline=True)
        _add_field('License',     info.get('license', ''))
        _add_field('About',       info.get('about', ''), multiline=True)

        if self._info_body.get_first_child() is None:
            empty = Gtk.Label(
                label='No metadata available for this module.', xalign=0)
            empty.add_css_class('dim-label')
            empty.set_margin_top(12)
            self._info_body.append(empty)

        self._stack.set_visible_child_name('info')

    def _can_remove(self, name):
        """Removable only if it isn't the pane's last module and isn't a
        read-only system SWORD module."""
        if len(self._pane._names) <= 1:
            return False
        return content.can_remove(name)

    def _on_remove_clicked(self, _btn):
        name = self._info_name
        if not name:
            return
        self._popover.popdown()
        self._confirm_remove(name)

    def _confirm_remove(self, name):
        disp = sword_bridge.display_name(name)
        dialog = Adw.AlertDialog(
            heading=f'Remove {disp}?',
            body=('This deletes the module from your library. You can '
                  're-download or re-import it later from the Module Manager.'))
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('remove', 'Remove')
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect(
            'response',
            lambda _d, resp: resp == 'remove' and self._do_remove(name))
        dialog.present(self._pane)

    def _do_remove(self, name):
        disp = sword_bridge.display_name(name)
        try:
            content.remove(name)
        except Exception as e:
            if self._pane._on_toast:
                self._pane._on_toast(f"Couldn't remove {disp} — {e}")
            return
        if self._pane._on_toast:
            self._pane._on_toast(f'Removed {disp}')
        # Refresh both panes (and fall back if a pane showed this module).
        if self._pane._on_modules_changed:
            self._pane._on_modules_changed()
        else:
            self._pane.refresh_modules()
