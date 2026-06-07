import logging
import threading
from datetime import datetime
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Pango
import sword_bridge
import open_data
import ebible_bridge
import catena_bridge
import imagery_bridge

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

def _lang_label(code):
    name = _LANG_NAMES.get(code.lower(), '')
    return f'{name} ({code})' if name else code


# Installed modules are grouped by kind. SWORD reports finer-grained types;
# these fold them into a few human sections, in display order.
_KIND_ORDER = ['Bibles', 'Commentaries', 'Lexicons & Dictionaries',
               'Devotionals', 'Books & Other']
_KIND_MAP = {
    'Biblical Texts': 'Bibles',
    'Commentaries': 'Commentaries',
    'Lexicons / Dictionaries': 'Lexicons & Dictionaries',
    'Glossaries': 'Lexicons & Dictionaries',
    'Daily Devotional': 'Devotionals',
}


def _display_kind(module_type):
    return _KIND_MAP.get(module_type, 'Books & Other')


# The eBible catalogue has ~1,500+ translations and PreferencesGroup rows
# aren't virtualised, so rendering them all is laggy. We materialise only the
# first slice of any result set and invite the user to search to narrow it —
# a 1,500-item list is found by searching, not scrolling.
_EB_RENDER_CAP = 200


def _fmt_size(raw):
    """SWORD InstallSize (bytes, as a string) → '2.3 MB'."""
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return ''
    if n <= 0:
        return ''
    for unit in ('bytes', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            if unit == 'bytes':
                return f'{int(n)} bytes'
            return f'{n:.1f} {unit}'
        n /= 1024
    return ''


def _short_license(text):
    """Trim a DistributionLicense string to something subtitle-sized."""
    if not text:
        return ''
    text = text.strip()
    return text if len(text) <= 28 else text[:27].rstrip() + '…'


def _ago(dt):
    """Humanise a catalogue timestamp as 'updated 3 days ago'."""
    if dt is None:
        return ''
    secs = (datetime.now() - dt).total_seconds()
    if secs < 3600:
        return 'updated less than an hour ago'
    if secs < 86400:
        h = int(secs // 3600)
        return f'updated {h} hour{"s" if h != 1 else ""} ago'
    days = int(secs // 86400)
    if days < 30:
        return f'updated {days} day{"s" if days != 1 else ""} ago'
    months = days // 30
    return f'updated {months} month{"s" if months != 1 else ""} ago'


class ModuleManagerWindow(Adw.Window):
    def __init__(self, on_modules_changed=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title('Module Manager')
        self.set_default_size(640, 720)
        self._on_modules_changed = on_modules_changed
        self._all_modules = []
        self._has_catalog = False
        self._lang_codes = ['']
        self._updating_filters = False
        self._eb_catalog = []
        self._eb_lang_codes = ['']
        self._pulse_source = None
        self._op_busy = False
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
        # Transient busy / error line (hidden unless there's a message).
        self._status = Gtk.Label(label='', wrap=True, xalign=0)
        self._status.add_css_class('dim-label')
        self._status.set_visible(False)

        # Refresh is contextual to the catalogue freshness, not a big blue
        # button — it lives as the browse group's header suffix.
        self._cw_refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic')
        self._cw_refresh_btn.add_css_class('flat')
        self._cw_refresh_btn.set_valign(Gtk.Align.CENTER)
        self._cw_refresh_btn.set_tooltip_text('Refresh catalogue from CrossWire')
        self._cw_refresh_btn.connect('clicked', self._on_refresh_clicked)

        # One search filters both the installed sections and the catalogue.
        self._cw_search = Gtk.SearchEntry()
        self._cw_search.set_placeholder_text('Search installed and catalogue…')
        self._cw_search.set_hexpand(True)
        self._cw_search.connect('search-changed', self._on_search_changed)

        # Installed modules, grouped by kind, are rebuilt into this container.
        self._installed_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=18)

        # Browse-catalogue refinement filters (apply to the available list).
        # These are inline single-select ListBoxes, NOT Gtk.DropDowns: a
        # DropDown opens its OWN nested autohide popover, and opening that
        # inside this filter popover steals the parent's outside-click grab and
        # never returns it — orphaning the popover (stuck open; even its own
        # button can't dismiss it). A ListBox selects in place, no child popup.
        self._cat_list = Gtk.ListBox()
        self._cat_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._cat_list.add_css_class('boxed-list')
        self._cat_list.add_css_class('module-filter-list')
        self._cat_list.connect('row-selected', self._on_filter_changed)

        self._lang_list = Gtk.ListBox()
        self._lang_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._lang_list.add_css_class('boxed-list')
        self._lang_list.add_css_class('module-filter-list')
        self._lang_list.connect('row-selected', self._on_filter_changed)

        self._strongs_check = Gtk.CheckButton(label="Strong's")
        self._strongs_check.set_tooltip_text("Only modules with Strong's numbers")
        self._strongs_check.set_valign(Gtk.Align.CENTER)
        self._strongs_check.connect('toggled', self._on_filter_changed)

        # The filters collapse into a popover in the Browse catalogue header,
        # next to refresh — full dropdowns inline crush the title and stretch
        # tall, so the section gets a compact "Filter" button instead.
        filt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        filt_box.set_margin_top(12)
        filt_box.set_margin_bottom(12)
        filt_box.set_margin_start(12)
        filt_box.set_margin_end(12)
        filt_box.set_size_request(190, -1)

        # Category and Language each get their own fixed-height scroll with a
        # pinned caption above, so the section labels stay visible while you
        # scroll (a single merged scroll hid them, reading as a raw dump).
        # Heights are FIXED (min == max) and the total kept ~320px: (1) a popover
        # taller than the short modules window gets resized-to-fit AFTER it maps,
        # and that post-map resize snaps an autohide popover shut (the ~1s flash
        # / "invisible window"); a definite size that fits never resizes. (2)
        # ListBox rows open no nested popup, so — unlike the old Gtk.DropDowns —
        # picking a filter can't steal the popover's outside-click grab.
        for label, lst, height in (('Category', self._cat_list, 88),
                                    ('Language', self._lang_list, 104)):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(height)
            scroll.set_max_content_height(height)
            scroll.add_css_class('module-filter-scroll')
            scroll.set_child(lst)

            field = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            cap = Gtk.Label(label=label, xalign=0)
            cap.add_css_class('caption')
            cap.add_css_class('dim-label')
            field.append(cap)
            field.append(scroll)
            filt_box.append(field)
        filt_box.append(self._strongs_check)

        filter_popover = Gtk.Popover()
        filter_popover.set_child(filt_box)
        self._filter_btn = Gtk.MenuButton(icon_name='view-more-symbolic')
        self._filter_btn.add_css_class('flat')
        self._filter_btn.set_valign(Gtk.Align.CENTER)
        self._filter_btn.set_tooltip_text('Filter the catalogue')
        self._filter_btn.set_popover(filter_popover)

        header_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6)
        header_controls.append(self._filter_btn)
        header_controls.append(self._cw_refresh_btn)

        self._browse_group = Adw.PreferencesGroup()
        self._browse_group.set_title('Browse catalogue')
        self._browse_group.set_header_suffix(header_controls)
        self._available_rows = []

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.append(self._status)
        box.append(self._cw_search)
        box.append(self._installed_container)
        box.append(self._browse_group)

        clamp = Adw.Clamp(child=box, maximum_size=720)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(clamp)
        self._stack.add_titled_with_icon(
            scroll, 'modules', 'Modules', 'application-x-addon-symbolic')

    # ── Open Databases tab ────────────────────────────────────────────────────

    def _build_open_db_tab(self):
        self._open_db_group = Adw.PreferencesGroup()
        self._open_db_group.set_title('Open databases')
        self._open_db_group.set_description(
            'Open-access data behind the word-study features — cross-references, '
            'Hebrew and Greek lexicons, grammatical parsing, plus the commentary '
            'and imagery packs.')
        self._open_db_rows = []

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.append(self._open_db_group)

        clamp = Adw.Clamp(child=box, maximum_size=720)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(clamp)
        self._stack.add_titled_with_icon(
            scroll, 'open_databases', 'Databases', 'network-server-symbolic')

    # ── eBible tab ────────────────────────────────────────────────────────────

    def _build_ebible_tab(self):
        self._eb_search = Gtk.SearchEntry()
        self._eb_search.set_placeholder_text('Search by name or language…')
        self._eb_search.set_hexpand(True)
        self._eb_search.connect('search-changed', lambda _: self._eb_apply_filter())

        self._eb_lang_list = Gtk.ListBox()
        self._eb_lang_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._eb_lang_list.add_css_class('boxed-list')
        self._eb_lang_list.add_css_class('module-filter-list')
        self._eb_lang_list.connect('row-selected', self._eb_on_lang_changed)

        # Language filter in a popover — same inline ListBox design as the
        # Modules tab. A Gtk.DropDown here opened a nested popup that stole the
        # popover's outside-click grab and left it stuck open; a ListBox selects
        # in place, so the popover stays dismissable.
        filt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        filt_box.set_margin_top(12)
        filt_box.set_margin_bottom(12)
        filt_box.set_margin_start(12)
        filt_box.set_margin_end(12)
        filt_box.set_size_request(190, -1)
        cap = Gtk.Label(label='Language', xalign=0)
        cap.add_css_class('caption')
        cap.add_css_class('dim-label')
        eb_lang_scroll = Gtk.ScrolledWindow()
        eb_lang_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        eb_lang_scroll.set_min_content_height(220)
        eb_lang_scroll.set_max_content_height(220)
        eb_lang_scroll.add_css_class('module-filter-scroll')
        eb_lang_scroll.set_child(self._eb_lang_list)
        filt_box.append(cap)
        filt_box.append(eb_lang_scroll)
        filter_popover = Gtk.Popover()
        filter_popover.set_child(filt_box)
        self._eb_filter_btn = Gtk.MenuButton(icon_name='view-more-symbolic')
        self._eb_filter_btn.add_css_class('flat')
        self._eb_filter_btn.set_valign(Gtk.Align.CENTER)
        self._eb_filter_btn.set_tooltip_text('Filter translations')
        self._eb_filter_btn.set_popover(filter_popover)

        self._eb_refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic')
        self._eb_refresh_btn.add_css_class('flat')
        self._eb_refresh_btn.set_valign(Gtk.Align.CENTER)
        self._eb_refresh_btn.set_tooltip_text('Refresh catalogue from eBible.org')
        self._eb_refresh_btn.connect('clicked', self._on_eb_refresh)

        header_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6)
        header_controls.append(self._eb_filter_btn)
        header_controls.append(self._eb_refresh_btn)

        self._eb_group = Adw.PreferencesGroup()
        self._eb_group.set_title('Translations')
        self._eb_group.set_header_suffix(header_controls)
        self._eb_rows = []

        self._eb_status = Gtk.Label(label='', xalign=0, wrap=True)
        self._eb_status.add_css_class('dim-label')
        self._eb_status.set_visible(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.append(self._eb_status)
        box.append(self._eb_search)
        box.append(self._eb_group)

        clamp = Adw.Clamp(child=box, maximum_size=720)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(clamp)
        self._stack.add_titled_with_icon(
            scroll, 'ebible', 'eBible', 'web-browser-symbolic')

    # ── CrossWire data ────────────────────────────────────────────────────────

    def _clear_box(self, box):
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _populate(self):
        try:
            self._all_modules = sword_bridge.list_available_modules()
            self._has_catalog = True
        except Exception as e:
            _log.info('no module catalogue cached yet: %s', e)
            self._has_catalog = False
            # Degraded state: list what's installed (no kinds/licences/sizes).
            self._all_modules = [
                {'name': n, 'description': '', 'type': '', 'lang': '',
                 'features': set(), 'license': '', 'size': '', 'installed': True}
                for n in sword_bridge.module_names()
            ]
        self._status.set_visible(False)

        self._rebuild_installed()
        self._rebuild_filter_options()
        self._apply_filter()
        self._populate_open_db()

    def _matches(self, mod, query):
        return (query in mod['name'].lower()
                or query in mod.get('description', '').lower())

    def _rebuild_installed(self):
        self._clear_box(self._installed_container)
        query = self._cw_search.get_text().strip().lower()
        installed = [m for m in self._all_modules if m['installed']]
        if query:
            installed = [m for m in installed if self._matches(m, query)]

        if not installed:
            group = Adw.PreferencesGroup()
            group.set_title('Installed')
            group.set_description(
                'No installed modules match your search.' if query else
                'No modules yet — install one from the catalogue below to get '
                'started.')
            self._installed_container.append(group)
            return

        if self._has_catalog:
            buckets = {}
            for mod in installed:
                buckets.setdefault(_display_kind(mod['type']), []).append(mod)
            kinds = [k for k in _KIND_ORDER if buckets.get(k)]
        else:
            buckets = {'Installed': installed}
            kinds = ['Installed']

        for kind in kinds:
            mods = sorted(buckets[kind],
                          key=lambda m: (m.get('description') or m['name']).lower())
            group = Adw.PreferencesGroup()
            # Titles are markup-parsed, so the "&" in "Lexicons & Dictionaries"
            # / "Books & Other" must be escaped.
            group.set_title(GLib.markup_escape_text(f'{kind} ({len(mods)})'))
            for mod in mods:
                group.add(self._make_row(mod, installed=True))
            self._installed_container.append(group)

    def _populate_open_db(self):
        for row in self._open_db_rows:
            self._open_db_group.remove(row)
        self._open_db_rows = []
        rows = [self._make_catena_row(), self._make_imagery_row()]
        for src in open_data.get_sources():
            rows.append(self._make_db_source_row(src))
        for row in rows:
            self._open_db_group.add(row)
            self._open_db_rows.append(row)

    def _make_db_source_row(self, src):
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(src['label']))
        row.set_subtitle(GLib.markup_escape_text(src['description']))
        if src['installed']:
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    src['label'], lambda: self._do_db_remove(src['id'])))
        else:
            btn = Gtk.Button(label='Download')
            btn.add_css_class('suggested-action')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked', lambda b, sid=src['id']: self._on_db_download(b, sid))
        row.add_suffix(btn)
        return row

    def _make_catena_row(self):
        row = Adw.ActionRow()
        row.set_title('Historical Commentaries')
        if catena_bridge.is_installed():
            n = catena_bridge.pack_info().get('quote_count', '')
            row.set_subtitle(
                f'{n} quotations from the church fathers to the Reformers, '
                'verse by verse' if n else
                'Church-history commentary, verse by verse')
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    'Historical Commentaries', self._do_catena_remove))
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

    def _do_catena_remove(self):
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

    def _make_imagery_row(self):
        row = Adw.ActionRow()
        row.set_title('Bible Imagery')
        if imagery_bridge.is_installed():
            n = imagery_bridge.pack_info().get('image_count', '')
            row.set_subtitle(
                f'{n} illustrations, maps, and place photos, verse by verse'
                if n else
                'Illustrations, maps, and place photos, verse by verse')
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    'Bible Imagery', self._do_imagery_remove))
        else:
            row.set_subtitle(
                'Illustrations, historical maps, and photographs of the '
                'places named in each verse · large download')
            btn = Gtk.Button(label='Download')
            btn.add_css_class('suggested-action')
            btn.connect('clicked', self._on_imagery_download)
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    def _on_imagery_download(self, btn):
        btn.set_sensitive(False)
        btn.set_label('Downloading…')
        base = 'Downloading Bible Imagery…'
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
                imagery_bridge.download_and_install(on_progress=_progress)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_imagery, err)

        threading.Thread(target=work, daemon=True).start()

    def _do_imagery_remove(self):
        imagery_bridge.remove_pack()
        if self._on_modules_changed:
            self._on_modules_changed()
        self._populate_open_db()

    def _finish_imagery(self, err):
        if err:
            _log.error('imagery download error: %s', err)
            self._set_busy(False, f"Couldn't download Bible Imagery — {err}")
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
        cur_cat  = self._selected_filter_text(self._cat_list)
        cur_lang = self._selected_filter_text(self._lang_list)

        self._fill_filter_list(self._cat_list,
                               ['All Categories'] + cats, cur_cat)
        self._fill_filter_list(self._lang_list,
                               ['All Languages'] + [_lang_label(c) for c in langs],
                               cur_lang)
        self._lang_codes = [''] + langs
        self._updating_filters = False

    def _selected_filter_text(self, listbox):
        row = listbox.get_selected_row()
        return row.get_child().get_label() if row else ''

    def _fill_filter_list(self, listbox, items, cur_text):
        child = listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            listbox.remove(child)
            child = nxt
        sel_row = None
        for text in items:
            lbl = Gtk.Label(label=text, xalign=0)
            # Ellipsize long entries (e.g. "Cults / Unorthodox / …") so one
            # outlier can't force the whole popover wide; full text on hover.
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_tooltip_text(text)
            lbl.set_margin_top(4); lbl.set_margin_bottom(4)
            lbl.set_margin_start(10); lbl.set_margin_end(10)
            row = Gtk.ListBoxRow()
            row.set_child(lbl)
            listbox.append(row)
            if text == cur_text:
                sel_row = row
        listbox.select_row(sel_row or listbox.get_row_at_index(0))

    def _catalog_status(self):
        if not self._has_catalog:
            return 'No catalogue cached yet — refresh to download the module list.'
        n = sum(1 for m in self._all_modules if not m['installed'])
        ago = _ago(sword_bridge.catalog_timestamp())
        return ' · '.join(p for p in (f'{n} modules available', ago) if p)

    def _apply_filter(self):
        for row in self._available_rows:
            self._browse_group.remove(row)
        self._available_rows = []
        self._browse_group.set_description(self._catalog_status())

        available = [m for m in self._all_modules if not m['installed']]

        cat_row = self._cat_list.get_selected_row()
        if cat_row and cat_row.get_index() > 0:
            chosen = cat_row.get_child().get_label()
            available = [m for m in available if m['type'] == chosen]

        lang_row = self._lang_list.get_selected_row()
        lang_idx = lang_row.get_index() if lang_row else 0
        if 0 < lang_idx < len(self._lang_codes):
            available = [m for m in available if m['lang'] == self._lang_codes[lang_idx]]

        if self._strongs_check.get_active():
            available = [m for m in available if 'StrongsNumbers' in m.get('features', set())]

        query = self._cw_search.get_text().strip().lower()
        if query:
            available = [m for m in available if self._matches(m, query)]

        if not available:
            placeholder = Adw.ActionRow()
            placeholder.set_title('No modules match your filters' if self._has_catalog
                                  else 'No catalogue cached yet')
            placeholder.set_sensitive(False)
            self._browse_group.add(placeholder)
            self._available_rows.append(placeholder)
            return

        for mod in available:
            row = self._make_row(mod, installed=False)
            self._browse_group.add(row)
            self._available_rows.append(row)

    def _on_search_changed(self, *_):
        self._rebuild_installed()
        self._apply_filter()

    def _on_filter_changed(self, *_):
        # Live: the catalogue rebuilds below the (fixed) header the popover is
        # anchored to, so it doesn't move the popover or cost it its grab — and
        # the lists open no nested popup, so the popover stays put while you
        # refine. (No deferral needed now that the DropDowns are gone.)
        if not self._updating_filters:
            self._apply_filter()

    def _on_tab_changed(self, stack, _):
        if stack.get_visible_child_name() == 'ebible' and not self._eb_catalog:
            self._eb_load_catalog()

    # ── CrossWire rows ────────────────────────────────────────────────────────

    def _make_row(self, mod, installed):
        row = Adw.ActionRow()
        key = mod['name']
        friendly = mod.get('description') or key
        row.set_title(GLib.markup_escape_text(friendly[:80]))

        meta = []
        if mod.get('lang'):
            meta.append(_lang_label(mod['lang']))
        if 'StrongsNumbers' in mod.get('features', set()):
            meta.append("Strong's")
        size = _fmt_size(mod.get('size'))
        if size:
            meta.append(size)
        lic = _short_license(mod.get('license', ''))
        if lic:
            meta.append(lic)
        # The raw module key as a dim monospace tag, friendly name as the title.
        subtitle = f'<tt>{GLib.markup_escape_text(key)}</tt>'
        if meta:
            subtitle += '  ·  ' + GLib.markup_escape_text(' · '.join(meta))
        row.set_subtitle(subtitle)

        if installed:
            btn = Gtk.Button(icon_name='user-trash-symbolic')
            btn.add_css_class('flat')
            btn.set_tooltip_text('Remove module')
            btn.connect(
                'clicked',
                lambda b, n=key, f=friendly, r=row: self._confirm_remove(b, n, f, r))
        else:
            btn = Gtk.Button(label='Install')
            btn.add_css_class('suggested-action')
            btn.connect('clicked',
                        lambda b, n=key, r=row: self._on_install(b, n, r))
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    # ── Shared busy / progress ────────────────────────────────────────────────

    def _set_busy(self, busy, status='', show_bar=True):
        # Per-row installs/removes give their feedback on the row itself (a
        # spinner), so they pass show_bar=False — the global progress bar is
        # reserved for window-level work (refresh, import, database downloads).
        self._cw_refresh_btn.set_sensitive(not busy)
        self._status.set_text(status)
        self._status.set_visible(bool(status))
        if busy and show_bar:
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

    def _row_spinner(self, row, button):
        """Swap a row's action button for a spinner while it installs/removes.
        The list is rebuilt on completion, so the spinner row is transient."""
        row.remove(button)
        spinner = Gtk.Spinner()
        spinner.set_valign(Gtk.Align.CENTER)
        spinner.start()
        row.add_suffix(spinner)

    def _trash_button(self, on_confirm):
        """A flat trash-icon remove button; `on_confirm` runs when clicked."""
        btn = Gtk.Button(icon_name='user-trash-symbolic')
        btn.add_css_class('flat')
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text('Remove')
        btn.connect('clicked', lambda _b: on_confirm())
        return btn

    def _confirm_remove_generic(self, friendly, on_confirm):
        """Confirmation dialog for removing a non-SWORD pack/source."""
        dialog = Adw.AlertDialog()
        dialog.set_heading('Remove?')
        dialog.set_body(
            f'“{friendly}” will be removed. You can download it again later.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('remove', 'Remove')
        dialog.set_response_appearance('remove',
                                       Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response',
                       lambda _d, r: on_confirm() if r == 'remove' else None)
        dialog.present(self)

    def _pulse(self):
        self._progress.pulse()
        return GLib.SOURCE_CONTINUE

    # ── CrossWire network ops ─────────────────────────────────────────────────

    def _on_refresh_clicked(self, _btn):
        if self._op_busy:
            return
        self._op_busy = True
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
        self._op_busy = False
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
        dialog = Adw.Dialog()
        dialog.set_title('Import Module')
        dialog.set_content_width(440)
        dialog.set_content_height(420)

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda _b: dialog.close())
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
            lambda _b: self._do_import(zip_bytes, rows, dialog))

        dialog.set_child(tv)
        dialog.present(self)

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

    def _do_import(self, zip_bytes, rows, dialog):
        selected = [m['name'] for m, c, _k in rows if c.get_active()]
        cipher_keys = {
            m['name']: k.get_text().strip()
            for m, c, k in rows
            if c.get_active() and k is not None and k.get_text().strip()
        }
        if not selected:
            return
        dialog.close()
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

    def _on_install(self, btn, name, row):
        if self._op_busy:
            return
        self._op_busy = True
        self._row_spinner(row, btn)
        self._set_busy(True, show_bar=False)

        def work():
            err = None
            try:
                sword_bridge.install_module(name)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_change, err, name, 'install')

        threading.Thread(target=work, daemon=True).start()

    def _confirm_remove(self, btn, name, friendly, row):
        dialog = Adw.AlertDialog()
        dialog.set_heading('Remove module?')
        dialog.set_body(
            f'“{friendly}” will be removed from your library. '
            'You can reinstall it from the catalogue later.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('remove', 'Remove')
        dialog.set_response_appearance('remove',
                                       Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', self._on_remove_response, btn, name, row)
        dialog.present(self)

    def _on_remove_response(self, _dialog, response, btn, name, row):
        if response == 'remove':
            self._on_remove(btn, name, row)

    def _on_remove(self, btn, name, row):
        if self._op_busy:
            return
        self._op_busy = True
        self._row_spinner(row, btn)
        self._set_busy(True, show_bar=False)

        def work():
            err = None
            try:
                sword_bridge.remove_module(name)
            except Exception as e:
                err = str(e)
            GLib.idle_add(self._finish_change, err, name, 'remove')

        threading.Thread(target=work, daemon=True).start()

    def _finish_change(self, err, name, action='install'):
        self._op_busy = False
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

    def _do_db_remove(self, source_id):
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
            self._eb_rebuild_lang_list()
            self._eb_apply_filter()
        else:
            self._eb_status.set_text(
                'No catalogue cached yet — refresh to download it.')
            self._eb_status.set_visible(True)
            self._eb_group.set_description('')

    def _eb_rebuild_lang_list(self):
        langs = sorted(set(
            e.get('languageCode', '').strip()
            for e in self._eb_catalog
            if e.get('languageCode', '').strip()
            and e.get('downloadable', '').strip() == 'True'
        ), key=lambda c: _lang_label(c))
        self._updating_filters = True
        cur = self._selected_filter_text(self._eb_lang_list)
        self._fill_filter_list(
            self._eb_lang_list,
            ['All Languages'] + [_lang_label(c) for c in langs], cur)
        self._eb_lang_codes = [''] + langs
        self._updating_filters = False

    def _eb_on_lang_changed(self, *_):
        # Live: the ListBox opens no nested popup, so picking a language can't
        # steal the popover's grab (the old DropDown's did, hence the former
        # popdown-on-select workaround). Guard against the rebuild's own
        # select_row firing this mid-populate.
        if not self._updating_filters:
            self._eb_apply_filter()

    def _eb_apply_filter(self):
        query      = self._eb_search.get_text().strip().lower()
        lang_row   = self._eb_lang_list.get_selected_row()
        lang_idx   = lang_row.get_index() if lang_row else 0
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

        # Clear and re-render. The render cap keeps the result set small enough
        # to build synchronously — which, unlike the old idle-batched append,
        # doesn't relayout the list across several main-loop turns under an open
        # filter popover. That repeated relayout was breaking the popover's
        # outside-click grab; a single synchronous pass (as the Modules tab
        # does) keeps it dismissable.
        for row in self._eb_rows:
            self._eb_group.remove(row)
        self._eb_rows = []

        n = len(filtered)
        self._eb_group.set_description(
            f'{n} translation{"s" if n != 1 else ""} · eBible.org')
        self._eb_status.set_visible(False)
        self._eb_status.set_text('')

        if not filtered:
            placeholder = Adw.ActionRow()
            placeholder.set_title('No translations match your search')
            placeholder.set_sensitive(False)
            self._eb_group.add(placeholder)
            self._eb_rows.append(placeholder)
            return

        installed = ebible_bridge.installed_ids()
        shown = filtered[:_EB_RENDER_CAP]
        for tid, title, lang_code, lang_name, entry in shown:
            row = self._eb_make_row(tid, title, lang_code, lang_name, entry,
                                    installed=tid in installed)
            self._eb_group.add(row)
            self._eb_rows.append(row)
        if n > len(shown):
            footer = self._eb_more_row(len(shown), n)
            self._eb_group.add(footer)
            self._eb_rows.append(footer)

    def _eb_more_row(self, shown, total):
        """A dim, non-interactive footer row noting the result set was capped.
        It's a real ActionRow so it inherits the boxed-list styling exactly."""
        row = Adw.ActionRow()
        row.set_title(
            f'Showing the first {shown} of {total:,} — '
            'refine your search to see more')
        row.set_sensitive(False)
        row.add_prefix(Gtk.Image.new_from_icon_name('system-search-symbolic'))
        return row

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
            btn = self._trash_button(
                lambda t=tid, ti=title: self._confirm_remove_generic(
                    ti, lambda: self._do_eb_remove(t)))
        else:
            btn = Gtk.Button(label='Download')
            btn.add_css_class('suggested-action')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked', lambda b, t=tid, e=entry: self._on_eb_download(b, t, e))
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
            self._eb_status.set_visible(True)
        else:
            self._eb_catalog = ebible_bridge.catalog_entries()
            self._eb_rebuild_lang_list()
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
            self._eb_status.set_visible(True)
            btn.set_sensitive(True)
            btn.set_label('Download')
        else:
            if self._on_modules_changed:
                self._on_modules_changed()
            self._eb_apply_filter()
        return GLib.SOURCE_REMOVE

    def _do_eb_remove(self, tid):
        ebible_bridge.remove_translation(tid)
        if self._on_modules_changed:
            self._on_modules_changed()
        self._eb_apply_filter()
