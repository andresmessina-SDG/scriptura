import logging
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk
import sword_bridge
import open_data
import ebible_bridge
import catena_bridge

_log = logging.getLogger('scriptura.modules')

_LANG_NAMES = {
    'en': 'English', 'de': 'German', 'fr': 'French', 'es': 'Spanish',
    'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'ru': 'Russian',
    'el': 'Greek', 'he': 'Hebrew', 'la': 'Latin', 'ar': 'Arabic',
    'zh': 'Chinese', 'ja': 'Japanese', 'ko': 'Korean', 'sv': 'Swedish',
    'fi': 'Finnish', 'da': 'Danish', 'no': 'Norwegian', 'pl': 'Polish',
    'cs': 'Czech', 'sk': 'Slovak', 'hu': 'Hungarian', 'ro': 'Romanian',
    'uk': 'Ukrainian', 'bg': 'Bulgarian', 'hr': 'Croatian', 'sr': 'Serbian',
    'af': 'Afrikaans', 'fa': 'Persian', 'tr': 'Turkish', 'vi': 'Vietnamese',
    'id': 'Indonesian', 'sw': 'Swahili', 'tl': 'Tagalog',
}

_DESC_CROSSWIRE = (
    'The SWORD Project by CrossWire Bible Society provides hundreds of Bible translations, '
    'commentaries, lexicons, and devotional works. Modules tagged with "Strong\'s" include '
    'original-language word tagging for Hebrew and Greek study. Most modules are in the '
    'public domain or freely licensed; a handful require separate permission from their publishers.'
)

_DESC_OPEN_DB = (
    'These open-access databases extend word-study features built into the app. '
    'The TSK (Treasury of Scripture Knowledge) supplies cross-references; '
    'Strong\'s lexicons power the Hebrew and Greek definition panel; '
    'MorphGNT adds grammatical parsing for every Greek New Testament word. '
    'All sources are freely redistributable.'
)

_DESC_EBIBLE = (
    'eBible.org curates over 1,500 Bible translations in more than 1,000 languages, '
    'contributed by Bible societies and mission organizations worldwide. Only translations '
    'that are freely downloadable are listed here. These are stored separately from SWORD '
    'modules and do not require the SWORD library. Note: some translations cover only the '
    'New Testament or select books, and formatting quality varies by source.'
)


def _lang_label(code):
    name = _LANG_NAMES.get(code.lower(), '')
    return f'{name} ({code})' if name else code


def _desc_label(text):
    lbl = Gtk.Label(label=text, wrap=True, xalign=0)
    lbl.add_css_class('dim-label')
    lbl.set_margin_bottom(12)
    return lbl


class ModuleManagerWindow(Adw.Window):
    def __init__(self, on_modules_changed=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title('Module Manager')
        self.set_default_size(580, 700)
        self._on_modules_changed = on_modules_changed
        self._all_modules = []
        self._lang_codes = ['']
        self._updating_filters = False
        self._eb_catalog = []
        self._eb_lang_codes = ['']
        self._eb_populate_gen = 0
        self._pulse_source = None
        self._build_ui()
        self._populate()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._import_btn = Gtk.Button(icon_name='folder-download-symbolic')
        self._import_btn.set_tooltip_text('Import module from file')
        self._import_btn.connect('clicked', self._on_import_clicked)
        header.pack_start(self._import_btn)

        # Drag a .zip anywhere onto the window to open the same import sheet.
        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop.connect('drop', self._on_file_dropped)
        self.add_controller(drop)

        self._progress = Gtk.ProgressBar()
        self._progress.set_show_text(True)
        self._progress.set_visible(False)
        toolbar_view.add_top_bar(self._progress)

        self._stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self._build_crosswire_tab()
        self._build_open_db_tab()
        self._build_ebible_tab()

        self._stack.connect('notify::visible-child', self._on_tab_changed)
        toolbar_view.set_content(self._stack)

    # ── CrossWire tab ─────────────────────────────────────────────────────────

    def _build_crosswire_tab(self):
        self._status = Gtk.Label(label='', wrap=True, xalign=0)
        self._status.add_css_class('dim-label')
        self._status.set_margin_bottom(4)

        self._cw_refresh_btn = Gtk.Button(label='Refresh from CrossWire')
        self._cw_refresh_btn.add_css_class('suggested-action')
        self._cw_refresh_btn.connect('clicked', self._on_refresh_clicked)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_row.set_margin_bottom(8)
        top_row.append(self._cw_refresh_btn)

        self._installed_label = Gtk.Label(xalign=0)
        self._installed_label.add_css_class('heading')

        self._installed_list = Gtk.ListBox()
        self._installed_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._installed_list.add_css_class('boxed-list')

        self._available_label = Gtk.Label(xalign=0)
        self._available_label.add_css_class('heading')
        self._available_label.set_margin_top(16)

        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filter_box.set_margin_top(4)

        self._cat_drop = Gtk.DropDown(model=Gtk.StringList.new(['All Categories']))
        self._cat_drop.set_tooltip_text('Filter by category')
        self._cat_drop.connect('notify::selected', self._on_filter_changed)
        filter_box.append(self._cat_drop)

        self._lang_drop = Gtk.DropDown(model=Gtk.StringList.new(['All Languages']))
        self._lang_drop.set_tooltip_text('Filter by language')
        self._lang_drop.connect('notify::selected', self._on_filter_changed)
        filter_box.append(self._lang_drop)

        self._strongs_check = Gtk.CheckButton(label="Strong's numbers")
        self._strongs_check.set_tooltip_text("Only show modules with Strong's numbers")
        self._strongs_check.connect('toggled', self._on_filter_changed)
        filter_box.append(self._strongs_check)

        # Search entry on its own row so a narrow window doesn't crush
        # the entry into a few characters — dropdowns + checkbox can wrap
        # on the row above; the search field keeps full width below.
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_row.set_margin_top(4)
        search_row.set_margin_bottom(4)
        self._cw_search = Gtk.SearchEntry()
        self._cw_search.set_placeholder_text('Filter by name or description…')
        self._cw_search.set_hexpand(True)
        self._cw_search.connect('search-changed', self._on_filter_changed)
        search_row.append(self._cw_search)

        self._available_list = Gtk.ListBox()
        self._available_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._available_list.add_css_class('boxed-list')

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(16)
        box.append(_desc_label(_DESC_CROSSWIRE))
        box.append(top_row)
        box.append(self._status)
        box.append(self._installed_label)
        box.append(self._installed_list)
        box.append(self._available_label)
        box.append(filter_box)
        box.append(search_row)
        box.append(self._available_list)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(box)
        self._stack.add_titled_with_icon(
            scroll, 'modules', 'Modules', 'application-x-addon-symbolic')

    # ── Open Databases tab ────────────────────────────────────────────────────

    def _build_open_db_tab(self):
        self._open_db_list = Gtk.ListBox()
        self._open_db_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._open_db_list.add_css_class('boxed-list')

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(16)
        box.append(_desc_label(_DESC_OPEN_DB))
        box.append(self._open_db_list)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(box)
        self._stack.add_titled_with_icon(
            scroll, 'open_databases', 'Open Databases', 'application-x-addon-symbolic')

    # ── eBible tab ────────────────────────────────────────────────────────────

    def _build_ebible_tab(self):
        self._eb_refresh_btn = Gtk.Button(label='Refresh Catalog')
        self._eb_refresh_btn.add_css_class('suggested-action')
        self._eb_refresh_btn.connect('clicked', self._on_eb_refresh)

        self._eb_search = Gtk.SearchEntry()
        self._eb_search.set_placeholder_text('Search by name or language…')
        self._eb_search.set_hexpand(True)
        self._eb_search.connect('search-changed', lambda _: self._eb_apply_filter())

        self._eb_lang_drop = Gtk.DropDown(model=Gtk.StringList.new(['All Languages']))
        self._eb_lang_drop.set_tooltip_text('Filter by language')
        self._eb_lang_drop.connect('notify::selected', lambda *_: self._eb_apply_filter())

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_row.set_margin_bottom(4)
        top_row.append(self._eb_refresh_btn)
        top_row.append(self._eb_search)
        top_row.append(self._eb_lang_drop)

        self._eb_status = Gtk.Label(label='', xalign=0, wrap=True)
        self._eb_status.add_css_class('dim-label')
        self._eb_status.set_margin_bottom(4)

        self._eb_count = Gtk.Label(label='', xalign=0)
        self._eb_count.add_css_class('dim-label')
        self._eb_count.set_margin_bottom(4)

        self._eb_list = Gtk.ListBox()
        self._eb_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._eb_list.add_css_class('boxed-list')

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(16)
        box.append(_desc_label(_DESC_EBIBLE))
        box.append(top_row)
        box.append(self._eb_status)
        box.append(self._eb_count)
        box.append(self._eb_list)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(box)
        self._stack.add_titled_with_icon(
            scroll, 'ebible', 'eBible', 'application-x-addon-symbolic')

    # ── CrossWire data ────────────────────────────────────────────────────────

    def _clear_lists(self):
        for lb in (self._installed_list, self._available_list):
            while lb.get_row_at_index(0):
                lb.remove(lb.get_row_at_index(0))

    def _populate(self):
        self._clear_lists()
        try:
            self._all_modules = sword_bridge.list_available_modules()
        except Exception as e:
            self._status.set_text(
                f'No module list cached yet. Click "Refresh from CrossWire" to download it.\n({e})'
            )
            self._installed_label.set_text('')
            self._available_label.set_text('')
            self._add_installed_fallback()
            self._populate_open_db()
            return

        self._status.set_text('')
        installed = [m for m in self._all_modules if m['installed']]
        self._installed_label.set_text(f'Installed ({len(installed)})')
        for mod in installed:
            self._installed_list.append(self._make_row(mod, installed=True))
        if not installed:
            self._installed_list.append(self._make_empty_installed_row())

        self._rebuild_filter_options()
        self._apply_filter()
        self._populate_open_db()

    def _populate_open_db(self):
        while self._open_db_list.get_row_at_index(0):
            self._open_db_list.remove(self._open_db_list.get_row_at_index(0))
        self._open_db_list.append(self._make_catena_row())
        for src in open_data.get_sources():
            row = Adw.ActionRow()
            row.set_title(src['label'])
            row.set_subtitle(src['description'])
            if src['installed']:
                btn = Gtk.Button(label='Remove')
                btn.add_css_class('destructive-action')
                btn.connect('clicked', lambda b, sid=src['id']: self._on_db_remove(b, sid))
            else:
                btn = Gtk.Button(label='Download')
                btn.add_css_class('suggested-action')
                btn.connect('clicked', lambda b, sid=src['id']: self._on_db_download(b, sid))
            btn.set_valign(Gtk.Align.CENTER)
            row.add_suffix(btn)
            self._open_db_list.append(row)

    def _make_catena_row(self):
        row = Adw.ActionRow()
        row.set_title('Historical Commentaries')
        if catena_bridge.is_installed():
            n = catena_bridge.pack_info().get('quote_count', '')
            row.set_subtitle(
                f'{n} quotations from the church fathers to the Reformers, '
                'verse by verse' if n else
                'Church-history commentary, verse by verse')
            btn = Gtk.Button(label='Remove')
            btn.add_css_class('destructive-action')
            btn.connect('clicked', self._on_catena_remove)
        else:
            row.set_subtitle(
                'How the church read each verse, from the fathers to the '
                'Reformers · ~31 MB download')
            btn = Gtk.Button(label='Download')
            btn.add_css_class('suggested-action')
            btn.connect('clicked', self._on_catena_download)
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    def _on_catena_download(self, btn):
        btn.set_sensitive(False)
        btn.set_label('Downloading…')
        base = 'Downloading Historical Commentaries…'
        self._set_busy(True, base)

        def _progress(done, total):
            if total > 0:
                msg = f'{base} {int(done * 100 / total)}% ({done >> 20} of {total >> 20} MB)'
            else:
                msg = f'{base} {done >> 20} MB'
            GLib.idle_add(self._set_busy, True, msg)

        def work():
            err = None
            try:
                catena_bridge.download_and_install(on_progress=_progress)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_catena, err)

        threading.Thread(target=work, daemon=True).start()

    def _on_catena_remove(self, _btn):
        catena_bridge.remove_pack()
        if self._on_modules_changed:
            self._on_modules_changed()
        self._populate_open_db()

    def _finish_catena(self, err):
        if err:
            _log.error('catena download error: %s', err)
            self._set_busy(False, f"Couldn't download Historical Commentaries — {err}")
        else:
            self._set_busy(False, '')
            if self._on_modules_changed:
                self._on_modules_changed()
        self._populate_open_db()
        return GLib.SOURCE_REMOVE

    def _rebuild_filter_options(self):
        available = [m for m in self._all_modules if not m['installed']]
        cats  = sorted(set(m['type'] for m in available if m['type']))
        langs = sorted(set(m['lang'] for m in available if m['lang']),
                       key=lambda c: _lang_label(c))

        self._updating_filters = True
        cur_cat  = self._get_drop_text(self._cat_drop)
        cur_lang = self._get_drop_text(self._lang_drop)

        cat_items  = ['All Categories'] + cats
        lang_items = ['All Languages']  + [_lang_label(c) for c in langs]
        self._cat_drop.set_model(Gtk.StringList.new(cat_items))
        self._lang_drop.set_model(Gtk.StringList.new(lang_items))

        if cur_cat  in cat_items:  self._cat_drop.set_selected(cat_items.index(cur_cat))
        if cur_lang in lang_items: self._lang_drop.set_selected(lang_items.index(cur_lang))
        self._lang_codes = [''] + langs
        self._updating_filters = False

    def _get_drop_text(self, drop):
        model = drop.get_model()
        idx   = drop.get_selected()
        return model.get_string(idx) if model and idx < model.get_n_items() else ''

    def _apply_filter(self):
        while self._available_list.get_row_at_index(0):
            self._available_list.remove(self._available_list.get_row_at_index(0))

        available = [m for m in self._all_modules if not m['installed']]

        cat_idx = self._cat_drop.get_selected()
        if cat_idx > 0:
            chosen = self._cat_drop.get_model().get_string(cat_idx)
            available = [m for m in available if m['type'] == chosen]

        lang_idx = self._lang_drop.get_selected()
        if 0 < lang_idx < len(self._lang_codes):
            available = [m for m in available if m['lang'] == self._lang_codes[lang_idx]]

        if self._strongs_check.get_active():
            available = [m for m in available if 'StrongsNumbers' in m.get('features', set())]

        query = self._cw_search.get_text().strip().lower()
        if query:
            available = [m for m in available
                         if query in m['name'].lower()
                         or query in m.get('description', '').lower()]

        self._available_label.set_text(f'Available ({len(available)})')
        for mod in available:
            self._available_list.append(self._make_row(mod, installed=False))

    def _on_filter_changed(self, *_):
        if not self._updating_filters:
            self._apply_filter()

    def _on_tab_changed(self, stack, _):
        if stack.get_visible_child_name() == 'ebible' and not self._eb_catalog:
            self._eb_load_catalog()

    # ── CrossWire rows ────────────────────────────────────────────────────────

    def _add_installed_fallback(self):
        names = sword_bridge.module_names()
        self._installed_label.set_text(f'Installed ({len(names)})')
        for name in names:
            mod = {'name': name, 'description': '', 'type': '', 'lang': '', 'features': set()}
            self._installed_list.append(self._make_row(mod, installed=True))
        if not names:
            self._installed_list.append(self._make_empty_installed_row())

    def _make_empty_installed_row(self):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        lbl = Gtk.Label(
            label='No modules installed yet. Pick a Bible from the list below to get started.',
            wrap=True, xalign=0,
        )
        lbl.add_css_class('dim-label')
        lbl.set_margin_start(12)
        lbl.set_margin_end(12)
        lbl.set_margin_top(12)
        lbl.set_margin_bottom(12)
        row.set_child(lbl)
        return row

    def _make_row(self, mod, installed):
        row = Adw.ActionRow()
        row.set_title(mod['name'])

        parts = [mod.get('description') or mod.get('type') or '']
        meta  = []
        if mod.get('lang'):
            meta.append(_lang_label(mod['lang']))
        if 'StrongsNumbers' in mod.get('features', set()):
            meta.append("Strong's")
        if meta:
            parts.append(' · '.join(meta))
        subtitle = '  —  '.join(p for p in parts if p)
        if subtitle:
            row.set_subtitle(GLib.markup_escape_text(subtitle[:100]))

        if installed:
            btn = Gtk.Button(label='Remove')
            btn.add_css_class('destructive-action')
            btn.connect('clicked', lambda b, n=mod['name']: self._on_remove(b, n))
        else:
            btn = Gtk.Button(label='Install')
            btn.add_css_class('suggested-action')
            btn.connect('clicked', lambda b, n=mod['name']: self._on_install(b, n))
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    # ── Shared busy / progress ────────────────────────────────────────────────

    def _set_busy(self, busy, status=''):
        self._cw_refresh_btn.set_sensitive(not busy)
        self._status.set_text(status)
        if busy:
            self._progress.set_text(status)
            self._progress.set_visible(True)
            if self._pulse_source is None:
                self._pulse_source = GLib.timeout_add(80, self._pulse)
        else:
            self._progress.set_visible(False)
            self._progress.set_text('')
            if self._pulse_source is not None:
                GLib.source_remove(self._pulse_source)
                self._pulse_source = None

    def _pulse(self):
        self._progress.pulse()
        return GLib.SOURCE_CONTINUE

    # ── CrossWire network ops ─────────────────────────────────────────────────

    def _on_refresh_clicked(self, _btn):
        self._set_busy(True, 'Downloading module list from CrossWire…')

        def work():
            err = None
            try:
                sword_bridge.refresh_source()
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_refresh, err)

        threading.Thread(target=work, daemon=True).start()

    def _finish_refresh(self, err):
        if err:
            self._set_busy(False, f'Refresh failed: {err}')
        else:
            self._set_busy(False, '')
            self._populate()
        return GLib.SOURCE_REMOVE

    # ── Import module from file (sideload) ────────────────────────────────────

    def _on_import_clicked(self, _btn):
        dialog = Gtk.FileDialog()
        dialog.set_title('Import SWORD Module')
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name('SWORD module (.zip)')
        zip_filter.add_pattern('*.zip')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zip_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(zip_filter)
        dialog.open(self, None, self._on_import_file_chosen)

    def _on_import_file_chosen(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # user cancelled
        if gfile is not None:
            self._load_zip_path(gfile.get_path())

    def _on_file_dropped(self, _target, value, _x, _y):
        path = value.get_path() if isinstance(value, Gio.File) else None
        if not path or not path.lower().endswith('.zip'):
            self._set_busy(False, 'Drop a SWORD module .zip file to import it.')
            return False
        self._load_zip_path(path)
        return True

    def _load_zip_path(self, path):
        self._set_busy(True, 'Reading module file…')

        def work():
            err = None
            mods = None
            data = None
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                mods = sword_bridge.inspect_module_zip(data)
            except (ValueError, OSError) as e:
                err = str(e)
            GLib.idle_add(self._finish_inspect, err, mods, data)

        threading.Thread(target=work, daemon=True).start()

    def _finish_inspect(self, err, mods, data):
        if err:
            self._set_busy(False, f"Couldn't read that file — {err}")
        else:
            self._set_busy(False, '')
            if mods:
                self._show_import_sheet(mods, data)
        return GLib.SOURCE_REMOVE

    def _show_import_sheet(self, mods, zip_bytes):
        win = Adw.Window(transient_for=self, modal=True)
        win.set_title('Import Module')
        win.set_default_size(440, 420)

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda _b: win.close())
        header.pack_start(cancel)
        install = Gtk.Button(label='Install')
        install.add_css_class('suggested-action')
        header.pack_end(install)
        tv.add_top_bar(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scroller.set_child(box)
        tv.set_content(scroller)

        rows = []  # list of (mod, check, key_entry|None)
        for mod in mods:
            rows.append(self._build_import_row(box, mod))

        def refresh_install_sensitivity(*_a):
            any_checked = any(c.get_active() for _m, c, _k in rows)
            needs_key = any(
                c.get_active() and k is not None and not k.get_text().strip()
                for _m, c, k in rows)
            install.set_sensitive(any_checked and not needs_key)

        for mod, check, key_entry in rows:
            check.connect('toggled', refresh_install_sensitivity)
            if key_entry is not None:
                key_entry.connect('changed', refresh_install_sensitivity)
        refresh_install_sensitivity()

        install.connect(
            'clicked',
            lambda _b: self._do_import(zip_bytes, rows, win))

        win.set_content(tv)
        win.present()

    def _build_import_row(self, box, mod):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class('card')

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        card.append(inner)

        check = Gtk.CheckButton()
        check.set_active(True)
        name_lbl = Gtk.Label(label=mod['name'], xalign=0)
        name_lbl.add_css_class('heading')
        check.set_child(name_lbl)
        inner.append(check)

        meta = []
        if mod.get('type'):
            meta.append(mod['type'])
        if mod.get('lang'):
            meta.append(_lang_label(mod['lang']))
        if mod.get('size'):
            meta.append(f"{mod['size'] / (1 << 20):.1f} MB")
        if mod.get('locked'):
            meta.append('🔒 Locked')
        if meta:
            sub = Gtk.Label(label=' · '.join(meta), xalign=0, wrap=True)
            sub.add_css_class('dim-label')
            sub.add_css_class('caption')
            sub.set_margin_start(28)
            inner.append(sub)

        if mod.get('description'):
            desc = Gtk.Label(label=mod['description'], xalign=0, wrap=True)
            desc.add_css_class('caption')
            desc.set_margin_start(28)
            inner.append(desc)

        verb, hint, warn = self._collision_verb(mod)
        if hint:
            hint_lbl = Gtk.Label(label=hint, xalign=0, wrap=True)
            hint_lbl.add_css_class('caption')
            hint_lbl.add_css_class('warning' if warn else 'dim-label')
            hint_lbl.set_margin_start(28)
            inner.append(hint_lbl)

        key_entry = None
        if mod.get('locked'):
            key_entry = Gtk.PasswordEntry()
            key_entry.set_show_peek_icon(True)
            key_entry.set_property('placeholder-text', 'Paste the unlock key from the publisher')
            key_entry.set_margin_start(28)
            key_entry.set_margin_top(4)
            inner.append(key_entry)

        box.append(card)
        return (mod, check, key_entry)

    @staticmethod
    def _collision_verb(mod):
        """Return (verb, subtext, warn) describing install vs installed."""
        if not mod.get('installed'):
            return 'Install', '', False
        new_v = mod.get('version', '')
        old_v = mod.get('installed_version', '')
        if not new_v or not old_v:
            # Can't compare meaningfully — treat as a plain reinstall.
            return 'Reinstall', 'Already installed', False
        cmp = sword_bridge.cmp_version(new_v, old_v)
        if cmp > 0:
            return 'Update', f'Update from v{old_v} to v{new_v}', False
        if cmp == 0:
            return 'Reinstall', f'Already installed (v{old_v})', False
        return 'Replace', f'Replace v{old_v} with older v{new_v}', True

    def _do_import(self, zip_bytes, rows, win):
        selected = [m['name'] for m, c, _k in rows if c.get_active()]
        cipher_keys = {
            m['name']: k.get_text().strip()
            for m, c, k in rows
            if c.get_active() and k is not None and k.get_text().strip()
        }
        if not selected:
            return
        win.close()
        label = selected[0] if len(selected) == 1 else f'{len(selected)} modules'
        self._set_busy(True, f'Installing {label}…')

        def work():
            err = None
            try:
                sword_bridge.install_module_from_zip(zip_bytes, selected, cipher_keys)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_import, err, label)

        threading.Thread(target=work, daemon=True).start()

    def _finish_import(self, err, label):
        if err:
            _log.error('import error for %s: %s', label, err)
            self._set_busy(False, f"Couldn't import {label} — {err}")
        else:
            self._set_busy(False, f'Imported {label}.')
            if self._on_modules_changed:
                self._on_modules_changed()
            self._populate()
        return GLib.SOURCE_REMOVE

    def _on_install(self, btn, name):
        btn.set_sensitive(False)
        btn.set_label('Installing…')
        self._set_busy(True, f'Downloading and installing {name} — this may take a minute…')

        def work():
            err = None
            try:
                sword_bridge.install_module(name)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_change, err, name, 'install')

        threading.Thread(target=work, daemon=True).start()

    def _on_remove(self, btn, name):
        btn.set_sensitive(False)
        btn.set_label('Removing…')
        self._set_busy(True, f'Removing {name}…')

        def work():
            err = None
            try:
                sword_bridge.remove_module(name)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_change, err, name, 'remove')

        threading.Thread(target=work, daemon=True).start()

    def _finish_change(self, err, name, action='install'):
        if err:
            _log.error('%s error for %s: %s', action, name, err)
            verb = 'remove' if action == 'remove' else 'install'
            self._set_busy(False, f'Couldn\'t {verb} {name} — {err}')
        else:
            self._set_busy(False, '')
            if self._on_modules_changed:
                self._on_modules_changed()
        self._populate()
        return GLib.SOURCE_REMOVE

    def _on_db_download(self, btn, source_id):
        src = next((s for s in open_data.get_sources() if s['id'] == source_id), None)
        if src is None:
            return
        btn.set_sensitive(False)
        btn.set_label('Downloading…')
        base_msg = f'Downloading {src["label"]}…'
        self._set_busy(True, base_msg)

        def _progress(done, total):
            if total > 0:
                pct = int(done * 100 / total)
                msg = f'{base_msg} {pct}% ({done >> 20} of {total >> 20} MB)'
            else:
                msg = f'{base_msg} {done >> 20} MB'
            GLib.idle_add(self._set_busy, True, msg)

        def work():
            err = None
            try:
                open_data.download_source(source_id, on_progress=_progress)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_db_change, err, src['label'])

        threading.Thread(target=work, daemon=True).start()

    def _on_db_remove(self, btn, source_id):
        open_data.remove_source(source_id)
        self._populate_open_db()

    def _finish_db_change(self, err, label):
        if err:
            self._set_busy(False, f'Couldn\'t download {label} — {err}')
        else:
            self._set_busy(False, '')
        self._populate_open_db()
        return GLib.SOURCE_REMOVE

    # ── eBible data ───────────────────────────────────────────────────────────

    def _eb_load_catalog(self):
        entries = ebible_bridge.catalog_entries()
        if entries:
            self._eb_catalog = entries
            self._eb_rebuild_lang_drop()
            self._eb_apply_filter()
        else:
            self._eb_status.set_text(
                'No catalog cached yet — click "Refresh Catalog" to download it')

    def _eb_rebuild_lang_drop(self):
        langs = sorted(set(
            e.get('languageCode', '').strip()
            for e in self._eb_catalog
            if e.get('languageCode', '').strip()
            and e.get('downloadable', '').strip() == 'True'
        ), key=lambda c: _lang_label(c))
        self._eb_lang_drop.set_model(Gtk.StringList.new(['All Languages'] + [_lang_label(c) for c in langs]))
        self._eb_lang_codes = [''] + langs

    def _eb_apply_filter(self):
        query      = self._eb_search.get_text().strip().lower()
        lang_idx   = self._eb_lang_drop.get_selected()
        lang_filter = self._eb_lang_codes[lang_idx] if lang_idx < len(self._eb_lang_codes) else ''

        filtered = []
        for entry in self._eb_catalog:
            if entry.get('downloadable', '').strip() != 'True':
                continue
            tid       = entry.get('translationId', '').strip()
            title     = (entry.get('shortTitle') or tid).strip()
            lang_code = entry.get('languageCode', '').strip()
            lang_name = entry.get('languageName', '').strip()
            if lang_filter and lang_code != lang_filter:
                continue
            if query and query not in title.lower() and query not in lang_name.lower() \
                    and query not in tid.lower():
                continue
            filtered.append((tid, title, lang_code, lang_name, entry))

        # Cancel any in-flight batch and clear list
        self._eb_populate_gen += 1
        gen = self._eb_populate_gen
        child = self._eb_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._eb_list.remove(child)
            child = nxt

        n = len(filtered)
        self._eb_count.set_text(f'{n} translation{"s" if n != 1 else ""}')
        self._eb_status.set_text('')

        installed = ebible_bridge.installed_ids()
        GLib.idle_add(self._eb_batch_append, filtered, installed, 0, gen)

    def _eb_batch_append(self, filtered, installed, offset, gen):
        if gen != self._eb_populate_gen:
            return GLib.SOURCE_REMOVE
        for tid, title, lang_code, lang_name, entry in filtered[offset:offset + 150]:
            self._eb_list.append(
                self._eb_make_row(tid, title, lang_code, lang_name, entry,
                                  installed=tid in installed))
        if offset + 150 < len(filtered):
            GLib.idle_add(self._eb_batch_append, filtered, installed, offset + 150, gen)
        return GLib.SOURCE_REMOVE

    def _eb_make_row(self, tid, title, lang_code, lang_name, entry, installed):
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(title))
        parts = []
        if lang_name:
            parts.append(lang_name)
        elif lang_code:
            parts.append(_lang_label(lang_code))
        license_ = (entry.get('licenseType') or '').strip()
        if license_:
            parts.append(license_)
        if parts:
            row.set_subtitle(GLib.markup_escape_text('  ·  '.join(parts)))

        if installed:
            btn = Gtk.Button(label='Remove')
            btn.add_css_class('destructive-action')
            btn.connect('clicked', lambda b, t=tid: self._on_eb_remove(b, t))
        else:
            btn = Gtk.Button(label='Download')
            btn.add_css_class('suggested-action')
            btn.connect('clicked', lambda b, t=tid, e=entry: self._on_eb_download(b, t, e))
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    # ── eBible network ops ────────────────────────────────────────────────────

    def _on_eb_refresh(self, _btn):
        self._eb_refresh_btn.set_sensitive(False)
        self._progress.set_text('Downloading eBible catalog…')
        self._progress.set_visible(True)
        if self._pulse_source is None:
            self._pulse_source = GLib.timeout_add(80, self._pulse)

        def work():
            err = None
            try:
                ebible_bridge.download_catalog_sync()
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_eb_refresh, err)

        threading.Thread(target=work, daemon=True).start()

    def _finish_eb_refresh(self, err):
        self._eb_refresh_btn.set_sensitive(True)
        self._progress.set_visible(False)
        if self._pulse_source is not None:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None
        if err:
            self._eb_status.set_text(f'Refresh failed: {err}')
        else:
            self._eb_catalog = ebible_bridge.catalog_entries()
            self._eb_rebuild_lang_drop()
            self._eb_apply_filter()
        return GLib.SOURCE_REMOVE

    def _on_eb_download(self, btn, tid, entry):
        btn.set_sensitive(False)
        btn.set_label('Downloading…')
        title = (entry.get('shortTitle') or tid).strip()
        self._progress.set_text(f'Downloading {title}…')
        self._progress.set_visible(True)
        if self._pulse_source is None:
            self._pulse_source = GLib.timeout_add(80, self._pulse)

        def on_status(msg):
            GLib.idle_add(self._progress.set_text, msg)

        def work():
            err = None
            try:
                ebible_bridge.download_translation_sync(tid, entry, on_status=on_status)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_eb_download, err, tid, title, btn)

        threading.Thread(target=work, daemon=True).start()

    def _finish_eb_download(self, err, tid, title, btn):
        self._progress.set_visible(False)
        if self._pulse_source is not None:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None
        if err:
            self._eb_status.set_text(f'Error downloading {title}: {err}')
            btn.set_sensitive(True)
            btn.set_label('Download')
        else:
            if self._on_modules_changed:
                self._on_modules_changed()
            self._eb_apply_filter()
        return GLib.SOURCE_REMOVE

    def _on_eb_remove(self, btn, tid):
        ebible_bridge.remove_translation(tid)
        if self._on_modules_changed:
            self._on_modules_changed()
        self._eb_apply_filter()
