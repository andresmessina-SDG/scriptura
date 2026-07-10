"""Module Manager — install, update, and remove content from every source.

Tabs are the user's content kinds (Bibles / Commentaries / Study Tools /
Books & More), not the app's supply chains: each tab merges every source
that can feed it (CrossWire SWORD catalogue, eBible.org, the curated
packs, the open databases) and badges each row with where it comes from.
Browse lists default to the UI language so the eBible catalogue's ~1,500
languages don't drown the list; the filter is a visible, removable chip,
and a search query widens back to every language so the default can
never dead-end a search.
"""
import logging
import os
import threading
from datetime import datetime
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Pango
from a11y import set_accessible_label
from gtk_utils import clear_children
import sword_bridge
import open_data
import ebible_bridge
import catena_bridge
import imagery_bridge
import archaeology_bridge
import interlinear_data
import lexicon_data
import content

_log = logging.getLogger('scriptura.modules')


def N_(message):
    """No-op gettext marker for strings in module-level data; translated at
    display time via _()."""
    return message


_LANG_NAMES = {
    'en': N_('English'), 'de': N_('German'), 'fr': N_('French'), 'es': N_('Spanish'),
    'it': N_('Italian'), 'pt': N_('Portuguese'), 'nl': N_('Dutch'), 'ru': N_('Russian'),
    'el': N_('Greek'), 'he': N_('Hebrew'), 'la': N_('Latin'), 'ar': N_('Arabic'),
    'zh': N_('Chinese'), 'ja': N_('Japanese'), 'ko': N_('Korean'), 'sv': N_('Swedish'),
    'fi': N_('Finnish'), 'da': N_('Danish'), 'no': N_('Norwegian'), 'pl': N_('Polish'),
    'cs': N_('Czech'), 'sk': N_('Slovak'), 'hu': N_('Hungarian'), 'ro': N_('Romanian'),
    'uk': N_('Ukrainian'), 'bg': N_('Bulgarian'), 'hr': N_('Croatian'), 'sr': N_('Serbian'),
    'af': N_('Afrikaans'), 'fa': N_('Persian'), 'tr': N_('Turkish'), 'vi': N_('Vietnamese'),
    'id': N_('Indonesian'), 'sw': N_('Swahili'), 'tl': N_('Tagalog'),
}

# eBible uses ISO 639-3 codes ('eng', 'spa'), SWORD mostly 639-1 ('en',
# 'es'); a merged language filter needs one canonical key or the default
# silently excludes a whole source. Majors map to two-letter; everything
# else passes through unchanged.
_ISO3TO2 = {
    'eng': 'en', 'spa': 'es', 'deu': 'de', 'ger': 'de', 'fra': 'fr',
    'fre': 'fr', 'ita': 'it', 'por': 'pt', 'nld': 'nl', 'dut': 'nl',
    'rus': 'ru', 'ell': 'el', 'gre': 'el', 'heb': 'he', 'lat': 'la',
    'ara': 'ar', 'zho': 'zh', 'chi': 'zh', 'jpn': 'ja', 'kor': 'ko',
    'swe': 'sv', 'fin': 'fi', 'dan': 'da', 'nor': 'no', 'nob': 'no',
    'nno': 'no', 'pol': 'pl', 'ces': 'cs', 'cze': 'cs', 'slk': 'sk',
    'slo': 'sk', 'hun': 'hu', 'ron': 'ro', 'rum': 'ro', 'ukr': 'uk',
    'bul': 'bg', 'hrv': 'hr', 'srp': 'sr', 'afr': 'af', 'fas': 'fa',
    'per': 'fa', 'tur': 'tr', 'vie': 'vi', 'ind': 'id', 'swh': 'sw',
    'swa': 'sw', 'tgl': 'tl',
}


def _norm_lang(code):
    code = (code or '').strip().lower()
    return _ISO3TO2.get(code, code)


def _lang_label(code):
    raw = _LANG_NAMES.get(code.lower(), '')
    # Guard the empty case: _('') returns the .po metadata header, not ''.
    name = _(raw) if raw else ''
    return f'{name} ({code})' if name else code


def _eb_lang_display(lang_code, lang_name):
    """eBible language for a row subtitle, rendered like the CrossWire
    rows ('Latin (la)') when the code normalizes to a known language;
    the catalogue's self-name ('Latine') otherwise."""
    norm = _norm_lang(lang_code)
    if norm in _LANG_NAMES:
        return _lang_label(norm)
    return lang_name or _lang_label(lang_code)


def _ui_lang():
    """The user's interface language code ('en', 'es', …) — the default
    browse-list language filter."""
    for var in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        val = os.environ.get(var)
        if val:
            return val.split('.')[0].split('_')[0].lower() or 'en'
    return 'en'


# ── Tabs: the user's content kinds, each fed by every capable source ────────
#
# 'sword_types' claims catalogue/installed SWORD categories; 'catch_all'
# sweeps any category no tab claims (odd third-party confs) into Books &
# More rather than losing it. 'lang_default' pre-selects the UI language
# in the browse filter — deliberately NOT on Study Tools, where the
# content (Greek/Hebrew lexicons, morphology) is inherently cross-language.
_TABS = (
    {'id': 'bibles', 'title': N_('Bibles'),
     'sword_types': ('Biblical Texts',), 'ebible': True,
     'lang_default': True, 'catch_all': False},
    {'id': 'commentaries', 'title': N_('Commentaries'),
     'sword_types': ('Commentaries',), 'ebible': False,
     'lang_default': True, 'catch_all': False},
    {'id': 'study', 'title': N_('Study Tools'),
     'sword_types': ('Lexicons / Dictionaries', 'Glossaries'),
     'ebible': False, 'lang_default': False, 'catch_all': False},
    {'id': 'books', 'title': N_('Books & More'),
     'sword_types': ('Generic Books', 'Daily Devotional'), 'ebible': False,
     'lang_default': True, 'catch_all': True},
)

_CLAIMED_TYPES = {t for tab in _TABS for t in tab['sword_types']}


def _tab_of_type(sword_type):
    for tab in _TABS:
        if sword_type in tab['sword_types']:
            return tab['id']
    return 'books'  # the catch-all


# The eBible catalogue has ~1,500+ translations (CrossWire ~400) and
# PreferencesGroup rows aren't virtualised, so rendering a whole result set
# is laggy — and idle-batched appends are not an option here: the repeated
# relayout under an open filter popover breaks its outside-click grab. So
# every browse list materialises only the first slice of any result set,
# synchronously, with a Load-more footer row appending the next slice on
# demand.
_RENDER_CAP = 150


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
        return _('updated less than an hour ago')
    if secs < 86400:
        h = int(secs // 3600)
        return ngettext('updated {h} hour ago', 'updated {h} hours ago', h).format(h=h)
    days = int(secs // 86400)
    if days < 30:
        return ngettext('updated {d} day ago', 'updated {d} days ago', days).format(d=days)
    months = days // 30
    return ngettext('updated {m} month ago', 'updated {m} months ago', months).format(m=months)


def _fmt_progress(base, done, total):
    """Append a translated percent/size detail to a base progress message.
    Shares the '{pct}% (…)' / '{done} MB' msgids with welcome.py."""
    if total > 0:
        detail = _('{pct}% ({done} of {total} MB)').format(
            pct=int(done * 100 / total), done=done >> 20, total=total >> 20)
    else:
        detail = _('{done} MB').format(done=done >> 20)
    return f'{base} {detail}'


class ModuleManagerWindow(Adw.Window):
    def __init__(self, on_modules_changed=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title(_('Module Manager'))
        self.set_default_size(640, 720)
        self._on_modules_changed = on_modules_changed
        self._all_modules = []
        self._has_catalog = False
        self._eb_catalog = []
        self._updates = []
        self._updating_filters = False
        self._pulse_source = None
        self._op_busy = False
        self._closed = False
        self._flash_source = None
        self._tabs = {}
        self.add_css_class('module-manager')
        self._build_ui()
        self.connect('close-request', self._on_close_request)
        self._populate()

    # ── Window chrome ─────────────────────────────────────────────────────────

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._import_btn = Gtk.Button(icon_name='folder-download-symbolic')
        self._import_btn.set_tooltip_text(_('Import module from file'))
        set_accessible_label(self._import_btn, _('Import module from file'))
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

        # Window-level status strip: transient errors + a Retry for the
        # failed operation (raw exception text alone left no way forward).
        self._status = Gtk.Label(label='', wrap=True, xalign=0, hexpand=True)
        self._status.add_css_class('dim-label')
        self._retry_btn = Gtk.Button(label=_('Retry'))
        self._retry_btn.add_css_class('flat')
        self._retry_btn.set_valign(Gtk.Align.CENTER)
        self._retry_cb = None
        self._retry_btn.connect('clicked', self._on_retry)
        self._status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                   spacing=8)
        self._status_bar.set_margin_start(12)
        self._status_bar.set_margin_end(12)
        self._status_bar.set_margin_top(4)
        self._status_bar.set_margin_bottom(4)
        self._status_bar.append(self._status)
        self._status_bar.append(self._retry_btn)
        self._status_bar.set_visible(False)
        toolbar_view.add_top_bar(self._status_bar)

        self._stack = Adw.ViewStack()
        # Label-only tabs: Adw.ViewSwitcher renders an empty icon slot for
        # icon-less pages, so the inline switcher's LABELS mode is the
        # supported way to drop icons (four titled tabs with icons truncate
        # at this width, and the icons added nothing the words don't).
        switcher = Adw.InlineViewSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_display_mode(Adw.InlineViewSwitcherDisplayMode.LABELS)
        header.set_title_widget(switcher)

        for spec in _TABS:
            self._build_tab(spec)
        toolbar_view.set_content(self._stack)

    # ── One tab = one content kind ────────────────────────────────────────────

    def _build_tab(self, spec):
        t = {'spec': spec, 'filtered': [], 'shown': 0, 'browse_rows': [],
             'lang_codes': [''], 'lang_sel': ''}
        self._tabs[spec['id']] = t

        # Search + the language chip live on one row above the lists.
        t['search'] = Gtk.SearchEntry()
        t['search'].set_placeholder_text(_('Search installed and catalogue…'))
        t['search'].set_hexpand(True)
        t['search'].connect('search-changed',
                            lambda _e, tid=spec['id']: self._refresh_tab(tid))

        # Language filter: an inline single-select ListBox in a popover, NOT
        # a Gtk.DropDown — a DropDown opens its OWN nested autohide popover,
        # and opening that inside this popover steals the parent's
        # outside-click grab and never returns it (stuck popover). A ListBox
        # selects in place, no child popup. Fixed height so the popover
        # never resizes after it maps (a post-map resize snaps an autohide
        # popover shut).
        t['lang_list'] = Gtk.ListBox()
        t['lang_list'].set_selection_mode(Gtk.SelectionMode.SINGLE)
        t['lang_list'].add_css_class('module-filter-list')
        t['lang_list'].connect(
            'row-selected',
            lambda _l, _r, tid=spec['id']: self._on_lang_selected(tid))

        # Type-to-filter: the Bibles union spans eBible's thousand-plus
        # languages, mostly bare ISO codes — scrolling that is hopeless,
        # three typed letters are not.
        t['lang_search'] = Gtk.SearchEntry()
        t['lang_search'].set_placeholder_text(_('Filter languages…'))
        t['lang_search'].connect(
            'search-changed',
            lambda _e, tid=spec['id']:
                self._tabs[tid]['lang_list'].invalidate_filter())
        t['lang_list'].set_filter_func(
            lambda row, tid=spec['id']: self._lang_row_visible(tid, row))

        # The popover's own content padding is stripped (.module-filter-pop)
        # so the list can bleed to the right edge — the overlay scrollbar
        # then rides the card's edge instead of crossing the option text.
        filt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        filt_box.set_margin_top(12)
        filt_box.set_margin_bottom(12)
        filt_box.set_margin_start(12)
        t['lang_search'].set_margin_end(12)
        filt_box.set_size_request(210, -1)
        t['lang_scroll'] = Gtk.ScrolledWindow()
        t['lang_scroll'].set_policy(Gtk.PolicyType.NEVER,
                                    Gtk.PolicyType.AUTOMATIC)
        t['lang_scroll'].set_min_content_height(220)
        t['lang_scroll'].set_max_content_height(220)
        t['lang_scroll'].add_css_class('module-filter-scroll')
        t['lang_scroll'].set_child(t['lang_list'])
        filt_box.append(t['lang_search'])
        filt_box.append(t['lang_scroll'])

        popover = Gtk.Popover()
        popover.add_css_class('module-filter-pop')
        popover.set_child(filt_box)
        popover.connect(
            'show', lambda _p, tid=spec['id']: self._on_filter_open(tid))
        # The chip: shows the active language, opens the filter popover.
        # Its ✕ companion (visible only while a language is active) drops
        # back to All — the filter must be visibly removable, or the
        # default reads as "the catalogue is English-only".
        # The chip and its ✕ share one capsule (`.module-lang-chip`, see
        # style.css) so the pair reads as a single removable filter chip.
        t['chip'] = Gtk.MenuButton()
        t['chip'].add_css_class('flat')
        t['chip'].set_popover(popover)
        set_accessible_label(t['chip'], _('Filter by language'))
        t['chip_clear'] = Gtk.Button(icon_name='window-close-symbolic')
        t['chip_clear'].add_css_class('flat')
        t['chip_clear'].set_tooltip_text(_('Show all languages'))
        set_accessible_label(t['chip_clear'], _('Show all languages'))
        t['chip_clear'].connect(
            'clicked', lambda _b, tid=spec['id']: self._set_lang(tid, ''))
        # FILL, not CENTER: the capsule stretches to the search entry's
        # height, so the row reads as two equal-weight controls.
        t['chip_clear'].add_css_class('chip-clear')
        t['chip_box'] = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        t['chip_box'].add_css_class('module-chip')
        t['chip_box'].set_valign(Gtk.Align.FILL)
        t['chip_box'].append(t['chip'])
        t['chip_box'].append(t['chip_clear'])

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_row.append(t['search'])
        if spec['id'] == 'bibles':
            # Strong's as its own toggle chip — a useful refinement was
            # buried as a checkbox at the popover's foot; as a chip it is
            # discoverable and speaks the same capsule grammar.
            t['strongs'] = Gtk.ToggleButton(label=_("Strong's"))
            t['strongs'].add_css_class('flat')
            t['strongs'].set_tooltip_text(_("Only modules with Strong's numbers"))
            set_accessible_label(t['strongs'], _("Only modules with Strong's numbers"))
            strongs_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            strongs_box.add_css_class('module-chip')
            strongs_box.set_valign(Gtk.Align.FILL)
            strongs_box.append(t['strongs'])

            def _on_strongs(btn, tid=spec['id'], box=strongs_box):
                if btn.get_active():
                    box.add_css_class('active')
                else:
                    box.remove_css_class('active')
                self._refresh_tab(tid)
            t['strongs'].connect('toggled', _on_strongs)
            search_row.append(strongs_box)
        search_row.append(t['chip_box'])

        # Curated packs pinned on top, before anything installed/browsable.
        t['curated'] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t['installed_box'] = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=18)
        t['updates_group'] = Adw.PreferencesGroup()
        t['updates_group'].set_visible(False)

        t['refresh'] = Gtk.Button(icon_name='view-refresh-symbolic')
        t['refresh'].add_css_class('flat')
        t['refresh'].set_valign(Gtk.Align.CENTER)
        t['refresh'].set_tooltip_text(_('Refresh the catalogue'))
        set_accessible_label(t['refresh'], _('Refresh the catalogue'))
        t['refresh'].connect(
            'clicked', lambda _b, tid=spec['id']: self._on_refresh(tid))

        t['browse_group'] = Adw.PreferencesGroup()
        t['browse_group'].set_title(_('Browse catalogue'))
        t['browse_group'].set_header_suffix(t['refresh'])

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for m in ('start', 'end'):
            getattr(box, f'set_margin_{m}')(12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.append(search_row)
        box.append(t['curated'])
        box.append(t['updates_group'])
        box.append(t['installed_box'])
        box.append(t['browse_group'])

        clamp = Adw.Clamp(child=box, maximum_size=720)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(clamp)
        # Label-only switcher tabs: four titled tabs with icons truncate
        # at the default width, and the icons add nothing the words don't.
        self._stack.add_titled(scroll, spec['id'], _(spec['title']))

    # ── Data gathering ────────────────────────────────────────────────────────

    def _populate(self):
        try:
            self._all_modules = sword_bridge.list_available_modules()
            self._has_catalog = True
        except Exception as e:
            _log.info('no module catalogue cached yet: %s', e)
            self._has_catalog = False
            # Degraded state: classify what's installed from its local conf
            # so each module still lands on its right tab.
            self._all_modules = [
                {'name': n, 'description': '',
                 'type': sword_bridge.module_type(n),
                 'lang': sword_bridge.module_language(n),
                 'features': set(), 'license': '', 'size': '',
                 'version': '', 'locked': False, 'installed': True}
                for n in sword_bridge.module_names()
            ]
        self._eb_catalog = ebible_bridge.catalog_entries() or []
        self._updates = sword_bridge.available_updates() if self._has_catalog else []
        for tab_id in self._tabs:
            self._refresh_tab(tab_id, full=True)

    def _refresh_tab(self, tab_id, full=False):
        """Re-render one tab against current data. `full` also rebuilds the
        language filter options and curated rows (data changed, not just
        the user's filter/search)."""
        t = self._tabs[tab_id]
        if full:
            self._rebuild_curated(t)
            self._rebuild_lang_options(t)
        self._rebuild_updates(t)
        self._rebuild_installed(t)
        self._rebuild_browse(t)
        self._sync_chip(t)

    # ── Curated packs (pinned rows) ───────────────────────────────────────────

    def _rebuild_curated(self, t):
        clear_children(t['curated'])
        tab_id = t['spec']['id']
        if tab_id == 'books':
            group = Adw.PreferencesGroup()
            group.set_title(_('Curated for Scriptura'))
            group.set_description(
                _('Hand-assembled companions, built for this app.'))
            group.add(self._make_catena_row())
            group.add(self._make_archaeology_row())
            group.add(self._make_imagery_row())
            group.add(self._make_interlinear_row(interlinear_data.GREEK))
            group.add(self._make_interlinear_row(interlinear_data.HEBREW))
            t['curated'].append(group)
        elif tab_id == 'bibles':
            # Pinned here too: someone browsing Greek/Hebrew texts should
            # meet the interlinears beside them, without knowing about the
            # curated shelf in Books & More (same pattern as the catena pin
            # below).
            group = Adw.PreferencesGroup()
            group.set_title(_('Curated for Scriptura'))
            group.add(self._make_interlinear_row(interlinear_data.GREEK))
            group.add(self._make_interlinear_row(interlinear_data.HEBREW))
            t['curated'].append(group)
        elif tab_id == 'commentaries':
            # Also pinned here: someone hunting commentaries should meet it
            # without knowing about the curated shelf in Books & More. Same
            # quiet title so the row doesn't float context-free (no
            # description line — compact here, the full shelf explains it).
            group = Adw.PreferencesGroup()
            group.set_title(_('Curated for Scriptura'))
            group.add(self._make_catena_row())
            t['curated'].append(group)
        elif tab_id == 'study':
            group = Adw.PreferencesGroup()
            group.set_title(_('Open databases'))
            group.set_description(
                _('Open-access data behind the word-study features — '
                  'cross-references, Hebrew and Greek lexicons, and '
                  'grammatical parsing.'))
            for src in open_data.get_sources():
                group.add(self._make_db_source_row(src))
            group.add(self._make_lexicon_pack_row())
            t['curated'].append(group)

    def _make_catena_row(self):
        row = Adw.ActionRow()
        row.set_title(_('Historical Commentaries'))
        if catena_bridge.is_installed():
            n = catena_bridge.pack_info().get('quote_count', '')
            row.set_subtitle(
                _('{n} quotations from the church fathers to the Reformers, '
                  'verse by verse').format(n=n) if n else
                _('Church-history commentary, verse by verse'))
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    _('Historical Commentaries'), self._do_catena_remove))
        else:
            row.set_subtitle(
                _('How the church read each verse, from the fathers to the '
                  'Reformers · ~31 MB download'))
            btn = Gtk.Button(label=_('Download'))
            btn.add_css_class('suggested-action')
            btn.connect('clicked', self._on_catena_download)
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    def _make_interlinear_row(self, name=interlinear_data.GREEK):
        hebrew = interlinear_data.is_hebrew(name)
        title = (_('Interlinear — Hebrew OT') if hebrew
                 else _('Interlinear — Greek NT'))
        row = Adw.ActionRow()
        row.set_title(title)
        if interlinear_data.is_installed(name):
            row.set_subtitle(
                _('Every OT word with gloss, parsing, and Strong’s — '
                  'Tyndale House data (CC BY)') if hebrew else
                _('Every NT word with gloss, parsing, and Strong’s — '
                  'Tyndale House data (CC BY)'))
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    title, lambda: self._do_interlinear_remove(name)))
        else:
            row.set_subtitle(
                _('The Hebrew Old Testament word by word — gloss, parsing, '
                  'and Strong’s under each word · ~16 MB download')
                if hebrew else
                _('The Greek New Testament word by word — gloss, parsing, '
                  'and Strong’s under each word · ~7 MB download'))
            btn = Gtk.Button(label=_('Download'))
            btn.add_css_class('suggested-action')
            btn.connect('clicked', self._on_interlinear_download, name)
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    def _make_imagery_row(self):
        row = Adw.ActionRow()
        row.set_title(_('Bible Imagery'))
        if imagery_bridge.is_installed():
            n = imagery_bridge.pack_info().get('image_count', '')
            row.set_subtitle(
                _('{n} illustrations, maps, and place photos, verse by verse').format(n=n)
                if n else
                _('Illustrations, maps, and place photos, verse by verse'))
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    _('Bible Imagery'), self._do_imagery_remove))
        else:
            row.set_subtitle(
                _('Illustrations, historical maps, and photographs of the '
                  'places named in each verse · large download'))
            btn = Gtk.Button(label=_('Download'))
            btn.add_css_class('suggested-action')
            btn.connect('clicked', self._on_imagery_download)
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    def _make_archaeology_row(self):
        """Scripture in Stone ships inside the app — nothing to download,
        but it must be discoverable next to its curated siblings."""
        row = Adw.ActionRow()
        row.set_title(_(archaeology_bridge.DISPLAY_NAME))
        row.set_subtitle(
            _('Artifacts, inscriptions, and excavated places in biblical '
              'sequence — open it from any pane’s module picker'))
        tag = Gtk.Label(label=_('Included'))
        tag.add_css_class('caption')
        tag.add_css_class('dim-label')
        tag.set_valign(Gtk.Align.CENTER)
        row.add_suffix(tag)
        return row

    def _make_db_source_row(self, src):
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(src['label']))
        row.set_subtitle(GLib.markup_escape_text(src['description']))
        if src['installed']:
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    src['label'], lambda: self._do_db_remove(src['id'])))
        else:
            btn = Gtk.Button(label=_('Download'))
            btn.add_css_class('suggested-action')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked', lambda b, sid=src['id']: self._on_db_download(b, sid))
        row.add_suffix(btn)
        return row

    # ── Language filter (chip + popover list) ─────────────────────────────────

    def _tab_sword_modules(self, t, installed):
        spec = t['spec']
        out = []
        for m in self._all_modules:
            if m['installed'] != installed:
                continue
            claimed = m['type'] in spec['sword_types'] or (
                spec['catch_all'] and m['type'] not in _CLAIMED_TYPES)
            if claimed:
                out.append(m)
        return out

    def _rebuild_lang_options(self, t):
        langs = {_norm_lang(m['lang'])
                 for m in self._tab_sword_modules(t, installed=False)
                 if m['lang']}
        if t['spec']['ebible']:
            langs |= {_norm_lang(e.get('languageCode'))
                      for e in self._eb_catalog
                      if e.get('downloadable', '').strip() == 'True'
                      and e.get('languageCode', '').strip()}
        codes = sorted(langs, key=lambda c: _lang_label(c))
        # The UI language is the one privileged row, pinned right under
        # "All languages"; the rest stay alphabetical and reachable by the
        # type-to-filter above the list.
        ui = _ui_lang()
        if ui in codes:
            codes.remove(ui)
            codes.insert(0, ui)
        if t['lang_sel'] == '' and t['spec']['lang_default'] \
                and ui == (codes[0] if codes else '') \
                and not t.get('lang_touched'):
            t['lang_sel'] = ui
        if t['lang_sel'] and t['lang_sel'] not in codes:
            t['lang_sel'] = ''
        t['lang_codes'] = [''] + codes

        self._updating_filters = True
        clear_children(t['lang_list'])
        t['lang_rows'] = []
        sel_row = None
        for code in t['lang_codes']:
            text = _('All languages') if not code else _lang_label(code)
            lbl = Gtk.Label(label=text, xalign=0, hexpand=True)
            # Ellipsize long entries so one outlier can't force the whole
            # popover wide; full text on hover.
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_tooltip_text(text)
            check = Gtk.Image.new_from_icon_name('object-select-symbolic')
            check.set_visible(code == t['lang_sel'])
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_margin_top(4); box.set_margin_bottom(4)
            # end margin keeps the checkmark and text clear of the overlay
            # scrollbar riding the popover's right edge
            box.set_margin_start(10); box.set_margin_end(16)
            box.append(lbl)
            box.append(check)
            row = Gtk.ListBoxRow()
            row.set_child(box)
            row._label_text = text.lower()
            row._check = check
            t['lang_list'].append(row)
            t['lang_rows'].append(row)
            if code == t['lang_sel']:
                sel_row = row
        t['lang_list'].select_row(sel_row or t['lang_list'].get_row_at_index(0))
        self._updating_filters = False

    def _lang_row_visible(self, tab_id, row):
        query = self._tabs[tab_id]['lang_search'].get_text().strip().lower()
        return not query or query in row._label_text

    def _on_filter_open(self, tab_id):
        """Popover opening: fresh filter, and the current selection in view
        (a picker that opens somewhere mid-alphabet hides your own state)."""
        t = self._tabs[tab_id]
        t['lang_search'].set_text('')
        GLib.idle_add(self._scroll_filter_to_selection, tab_id)

    def _scroll_filter_to_selection(self, tab_id):
        t = self._tabs[tab_id]
        row = t['lang_list'].get_selected_row()
        if row is not None:
            adj = t['lang_scroll'].get_vadjustment()
            alloc = row.get_allocation()
            adj.set_value(max(0.0, alloc.y - (adj.get_page_size()
                                              - alloc.height) / 2))
        return GLib.SOURCE_REMOVE

    def _on_lang_selected(self, tab_id):
        if self._updating_filters:
            return
        t = self._tabs[tab_id]
        row = t['lang_list'].get_selected_row()
        idx = row.get_index() if row else 0
        t['lang_sel'] = t['lang_codes'][idx] if idx < len(t['lang_codes']) else ''
        t['lang_touched'] = True  # user's explicit pick outlives repopulates
        for r in t.get('lang_rows', []):
            r._check.set_visible(r is row)
        self._refresh_tab(tab_id)

    def _set_lang(self, tab_id, code):
        t = self._tabs[tab_id]
        t['lang_sel'] = code
        t['lang_touched'] = True
        self._rebuild_lang_options(t)
        self._refresh_tab(tab_id)

    def _sync_chip(self, t):
        active = bool(t['lang_sel'])
        t['chip'].set_label(_lang_label(t['lang_sel']) if active
                            else _('All languages'))
        t['chip_clear'].set_visible(active)
        if active:
            t['chip_box'].add_css_class('active')
        else:
            t['chip_box'].remove_css_class('active')

    # ── Updates ───────────────────────────────────────────────────────────────

    def _rebuild_updates(self, t):
        group = t['updates_group']
        # PreferencesGroup has no clear API for rows; track and remove.
        for row in t.get('update_rows', []):
            group.remove(row)
        t['update_rows'] = []
        mine = [(m, old) for m, old in self._updates
                if _tab_of_type(m['type']) == t['spec']['id']]
        group.set_visible(bool(mine))
        if not mine:
            return
        group.set_title(ngettext('{n} update available',
                                 '{n} updates available',
                                 len(mine)).format(n=len(mine)))
        for mod, old in mine:
            row = Adw.ActionRow()
            row.set_title(GLib.markup_escape_text(
                (mod.get('description') or mod['name'])[:80]))
            row.set_subtitle(GLib.markup_escape_text(
                _('Update from v{old} to v{new}').format(
                    old=old, new=mod['version'])))
            btn = Gtk.Button(label=_('Update'))
            btn.add_css_class('suggested-action')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked',
                        lambda b, m=mod, r=row: self._on_install(b, m, r))
            row.add_suffix(btn)
            group.add(row)
            t['update_rows'].append(row)

    # ── Installed section ─────────────────────────────────────────────────────

    def _matches(self, mod, query):
        return (query in mod['name'].lower()
                or query in mod.get('description', '').lower())

    def _rebuild_installed(self, t):
        clear_children(t['installed_box'])
        query = t['search'].get_text().strip().lower()

        entries = []   # (sort_key, (src, payload))
        for mod in self._tab_sword_modules(t, installed=True):
            if query and not self._matches(mod, query):
                continue
            entries.append(((mod.get('description') or mod['name']).lower(),
                            ('sword', mod)))
        if t['spec']['ebible']:
            installed_ids = ebible_bridge.installed_ids()
            by_id = {e.get('translationId', '').strip(): e
                     for e in self._eb_catalog}
            for tid in sorted(installed_ids):
                entry = by_id.get(tid, {})
                title = (entry.get('shortTitle') or tid).strip()
                lang_code = entry.get('languageCode', '').strip()
                lang_name = entry.get('languageName', '').strip()
                if query and query not in title.lower() \
                        and query not in tid.lower():
                    continue
                entries.append((title.lower(),
                                ('ebible', (tid, title, lang_code,
                                            lang_name, entry))))

        n = len(entries)   # edition count, before folding
        entries = self._fold_editions(entries)
        group = Adw.PreferencesGroup()
        group.set_title(_('Installed') + (f' ({n})' if n else ''))
        if not entries:
            group.set_description(
                _('No installed modules match your search.') if query else
                _('Nothing yet — install something from the catalogue below.'))
        for _key, item in sorted(entries, key=lambda e: e[0]):
            group.add(self._entry_row(item, installed=True))
        t['installed_box'].append(group)

    # ── Browse (merged catalogue) ─────────────────────────────────────────────

    def _catalog_status(self, t):
        parts = []
        if self._has_catalog:
            n = len(self._tab_sword_modules(t, installed=False))
            parts.append(ngettext('{n} CrossWire module',
                                  '{n} CrossWire modules', n).format(n=n))
        if t['spec']['ebible'] and self._eb_catalog:
            n = sum(1 for e in self._eb_catalog
                    if e.get('downloadable', '').strip() == 'True')
            parts.append(ngettext('{n} eBible translation',
                                  '{n} eBible translations', n).format(n=n))
        ago = _ago(sword_bridge.catalog_timestamp())
        if ago:
            parts.append(ago)
        if t['search'].get_text().strip() and t['lang_sel']:
            parts.append(_('searching all languages'))
        return ' · '.join(parts)

    def _rebuild_browse(self, t):
        group = t['browse_group']
        for row in t['browse_rows']:
            group.remove(row)
        t['browse_rows'] = []
        group.set_description(self._catalog_status(t))

        query = t['search'].get_text().strip().lower()
        # A search query widens to every language: the language default is
        # a browsing convenience and must never make a search dead-end.
        lang = '' if query else t['lang_sel']

        merged = []   # (sort_key, ('sword', mod) | ('ebible', tuple))
        for mod in self._tab_sword_modules(t, installed=False):
            if lang and _norm_lang(mod['lang']) != lang:
                continue
            if t.get('strongs') and t['strongs'].get_active() \
                    and 'StrongsNumbers' not in mod.get('features', set()):
                continue
            if query and not self._matches(mod, query):
                continue
            merged.append(((mod.get('description') or mod['name']).lower(),
                           ('sword', mod)))
        if t['spec']['ebible']:
            if not (t.get('strongs') and t['strongs'].get_active()):
                installed_ids = ebible_bridge.installed_ids()
                for entry in self._eb_catalog:
                    if entry.get('downloadable', '').strip() != 'True':
                        continue
                    tid = entry.get('translationId', '').strip()
                    if not tid or tid in installed_ids:
                        continue
                    title = (entry.get('shortTitle') or tid).strip()
                    lang_code = entry.get('languageCode', '').strip()
                    lang_name = entry.get('languageName', '').strip()
                    if lang and _norm_lang(lang_code) != lang:
                        continue
                    if query and query not in title.lower() \
                            and query not in lang_name.lower() \
                            and query not in tid.lower():
                        continue
                    merged.append((title.lower(),
                                   ('ebible', (tid, title, lang_code,
                                               lang_name, entry))))

        if not merged:
            placeholder = Adw.ActionRow()
            if self._has_catalog or (t['spec']['ebible'] and self._eb_catalog):
                placeholder.set_title(_('No modules match your filters'))
            else:
                placeholder.set_title(
                    _('No catalogue cached yet — refresh to download the '
                      'module list.'))
            placeholder.set_sensitive(False)
            group.add(placeholder)
            t['browse_rows'].append(placeholder)
            return

        merged = self._fold_editions(merged)
        merged.sort(key=lambda e: e[0])
        t['filtered'] = [item for _k, item in merged]
        t['shown'] = 0
        self._append_browse_rows(t)

    def _append_browse_rows(self, t):
        """Materialise the next _RENDER_CAP slice of the filtered result,
        followed by a Load-more footer while results remain (see the
        _RENDER_CAP note up top for why the list is capped + synchronous)."""
        group = t['browse_group']
        chunk = t['filtered'][t['shown']:t['shown'] + _RENDER_CAP]
        for item in chunk:
            row = self._entry_row(item, installed=False)
            group.add(row)
            t['browse_rows'].append(row)
        t['shown'] += len(chunk)
        if t['shown'] < len(t['filtered']):
            footer = Adw.ActionRow()
            footer.set_title(
                _('Load more — showing the first {shown} of {total}').format(
                    shown=f"{t['shown']:,}", total=f"{len(t['filtered']):,}"))
            footer.set_activatable(True)
            footer.add_prefix(Gtk.Image.new_from_icon_name('view-more-symbolic'))
            footer.connect('activated', lambda _r: self._on_more(t))
            group.add(footer)
            t['browse_rows'].append(footer)

    def _on_more(self, t):
        # The footer is always the last row; swap it for the next slice.
        footer = t['browse_rows'].pop()
        t['browse_group'].remove(footer)
        self._append_browse_rows(t)

    # ── Rows ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _fold_editions(entries):
        """Fold cross-source editions of one translation
        (content.EDITION_WORKS) into ('group', (work_id, [items])) entries.
        Folding runs over the survivors of the current filters only, and a
        group left with a single member stays a plain row — an expander
        hiding one child would be pure friction."""
        by_work = {}
        out = []
        for sort_key, item in entries:
            src, payload = item
            key = payload['name'] if src == 'sword' else payload[0]
            work = content.edition_work(src, key)
            if work is None:
                out.append((sort_key, item))
                continue
            if work not in by_work:
                members = []
                by_work[work] = members
                out.append((content.edition_work_title(work).lower(),
                            ('group', (work, members))))
            by_work[work].append(item)
        return [(k, it[1][1][0]) if it[0] == 'group' and len(it[1][1]) == 1
                else (k, it)
                for k, it in out]

    def _entry_row(self, item, installed):
        src, payload = item
        if src == 'group':
            return self._make_group_row(*payload, installed=installed)
        if src == 'sword':
            return self._make_sword_row(payload, installed)
        return self._make_eb_row(*payload, installed=installed)

    def _make_group_row(self, work, items, installed):
        """One expandable row per translation; each edition keeps its full
        row (badges, metadata, its own action button) underneath."""
        row = Adw.ExpanderRow()
        row.set_title(GLib.markup_escape_text(content.edition_work_title(work)))
        sources = []
        for src, _p in items:
            label = 'CrossWire' if src == 'sword' else 'eBible.org'
            if label not in sources:
                sources.append(label)
        row.set_subtitle(GLib.markup_escape_text(
            ngettext('{n} edition', '{n} editions',
                     len(items)).format(n=len(items))
            + '  ·  ' + ' · '.join(sources)))
        for item in items:
            row.add_row(self._entry_row(item, installed))
        return row

    def _make_sword_row(self, mod, installed):
        row = Adw.ActionRow()
        key = mod['name']
        friendly = mod.get('description') or key
        row.set_title(GLib.markup_escape_text(friendly[:80]))

        meta = []
        # A language label on every row is catalogue noise when it's the
        # user's own language — name it only where it informs (Latin,
        # Greek, enm, …), like a library that doesn't label English books
        # "English" in an English library.
        if mod.get('lang') and _norm_lang(mod['lang']) != _ui_lang():
            meta.append(_lang_label(mod['lang']))
        if 'StrongsNumbers' in mod.get('features', set()):
            meta.append(_("Strong's"))
        if mod.get('locked'):
            meta.append(_('Locked'))
        size = _fmt_size(mod.get('size'))
        if size:
            meta.append(size)
        lic = _short_license(mod.get('license', ''))
        if lic:
            meta.append(lic)
        meta.append('CrossWire')
        # The raw module key as a dim monospace tag, friendly name as the title.
        subtitle = f'<tt>{GLib.markup_escape_text(key)}</tt>'
        subtitle += '  ·  ' + GLib.markup_escape_text(' · '.join(meta))
        row.set_subtitle(subtitle)

        if installed:
            btn = self._trash_button(
                lambda n=key, f=friendly, r=row: self._confirm_remove(n, f, r))
            btn.set_tooltip_text(_('Remove module'))
            set_accessible_label(btn, _('Remove module'))
        else:
            btn = Gtk.Button(label=_('Install'))
            btn.add_css_class('suggested-action')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked',
                        lambda b, m=mod, r=row: self._on_install(b, m, r))
        row.add_suffix(btn)
        return row

    def _make_eb_row(self, tid, title, lang_code, lang_name, entry, installed):
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(title))
        parts = []
        # Same rule as the CrossWire rows: the user's own language goes
        # unsaid; only a differing language earns its label.
        if (lang_code or lang_name) and _norm_lang(lang_code) != _ui_lang():
            parts.append(_eb_lang_display(lang_code, lang_name))
        license_ = (entry.get('licenseType') or '').strip()
        if license_:
            parts.append(license_)
        parts.append('eBible.org')
        row.set_subtitle(GLib.markup_escape_text('  ·  '.join(parts)))

        if installed:
            btn = self._trash_button(
                lambda t_=tid, ti=title: self._confirm_remove_generic(
                    ti, lambda: self._do_eb_remove(t_)))
        else:
            # Same verb as the CrossWire rows — the user is installing a
            # module either way; which wire it arrives over is plumbing.
            btn = Gtk.Button(label=_('Install'))
            btn.add_css_class('suggested-action')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked',
                        lambda b, t_=tid, e=entry: self._on_eb_download(b, t_, e))
        row.add_suffix(btn)
        return row

    # ── One async runner for every operation ──────────────────────────────────
    #
    # Every network/disk operation goes through here: one gate
    # (`_op_busy`), one thread pattern, one _closed guard — and a visible
    # answer when an operation is refused, instead of a silent no-op.

    def _run_async(self, work, on_done, busy_msg='', show_bar=True, retry=None):
        """Run work() on a daemon thread; on_done(err) on the main loop.
        Returns False (with visible feedback) if another operation holds
        the gate. `retry` re-runs the whole operation from the error strip."""
        if self._op_busy:
            self._flash(_('Waiting for the current operation to finish…'))
            return False
        self._op_busy = True
        self._set_busy(True, busy_msg, show_bar=show_bar)

        def runner():
            err = None
            try:
                work()
            except Exception as e:
                err = str(e)
            GLib.idle_add(finish, err)

        def finish(err):
            if self._closed:
                return GLib.SOURCE_REMOVE
            self._op_busy = False
            self._set_busy(False)
            if err:
                _log.error('operation failed: %s', err)
                self._set_error(err, retry)
            on_done(err)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=runner, daemon=True).start()
        return True

    def _set_busy(self, busy, status='', show_bar=True):
        if self._closed:
            return
        # Per-row installs/removes give their feedback on the row itself (a
        # spinner), so they pass show_bar=False — the global progress bar is
        # reserved for window-level work (refresh, import, pack downloads).
        if busy:
            self._status_bar.set_visible(False)
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

    def _set_progress_text(self, text):
        if not self._closed:
            self._progress.set_text(text)
        return GLib.SOURCE_REMOVE

    def _set_error(self, message, retry=None):
        self._status.set_text(message)
        self._retry_cb = retry
        self._retry_btn.set_visible(retry is not None)
        self._status_bar.set_visible(True)

    def _on_retry(self, _btn):
        cb = self._retry_cb
        self._retry_cb = None
        self._status_bar.set_visible(False)
        if cb is not None:
            cb()

    def _flash(self, message):
        """Transient, self-clearing status line (busy-gate refusals)."""
        self._status.set_text(message)
        self._retry_btn.set_visible(False)
        self._status_bar.set_visible(True)
        if self._flash_source is not None:
            GLib.source_remove(self._flash_source)
        self._flash_source = GLib.timeout_add(2500, self._end_flash)

    def _end_flash(self):
        self._flash_source = None
        if not self._closed and self._retry_cb is None:
            self._status_bar.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _row_spinner(self, row, button):
        """Swap a row's action button for a spinner while it installs/removes.
        The list is rebuilt on completion, so the spinner row is transient."""
        row.remove(button)
        spinner = Gtk.Spinner()
        spinner.set_valign(Gtk.Align.CENTER)
        spinner.start()
        row.add_suffix(spinner)

    def _trash_button(self, on_confirm):
        """A flat trash-icon remove button; `on_confirm` runs when clicked.
        Hover-revealed (`.module-row-action`) per the house row-action rule."""
        btn = Gtk.Button(icon_name='user-trash-symbolic')
        btn.add_css_class('flat')
        btn.add_css_class('module-row-action')
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(_('Remove'))
        set_accessible_label(btn, _('Remove'))
        btn.connect('clicked', lambda _b: on_confirm())
        return btn

    def _pulse(self):
        self._progress.pulse()
        return GLib.SOURCE_CONTINUE

    def _on_close_request(self, _win):
        # Mark closed so the daemon workers' idle callbacks early-return
        # instead of mutating finalized widgets, and stop the pulse.
        self._closed = True
        if self._pulse_source is not None:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None
        return False

    def _modules_changed(self):
        if self._on_modules_changed:
            self._on_modules_changed()

    # ── SWORD install / update / remove ───────────────────────────────────────

    def _on_install(self, btn, mod, row):
        name = mod['name']
        if mod.get('locked') and not sword_bridge.is_encrypted_module(name):
            # Enciphered module fresh from the catalogue: ask for the key
            # up front rather than letting it install and render garbage.
            self._prompt_cipher_install(btn, mod, row)
            return
        self._start_install(btn, name, row)

    def _start_install(self, btn, name, row, cipher_key=None):
        def work():
            sword_bridge.install_module(name)
            if cipher_key:
                sword_bridge.set_cipher_key(name, cipher_key)

        def done(err):
            self._modules_changed()
            self._populate()

        if self._run_async(work, done, show_bar=False,
                           retry=lambda: self._start_install(
                               btn, name, row, cipher_key)):
            self._row_spinner(row, btn)

    def _prompt_cipher_install(self, btn, mod, row):
        dialog = Adw.AlertDialog()
        dialog.set_heading(_('Unlock Module'))
        dialog.set_body(
            _('“{name}” is enciphered. Enter the unlock key from the '
              'publisher to install it.').format(
                name=mod.get('description') or mod['name']))
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_property('placeholder-text',
                           _('Paste the unlock key from the publisher'))
        dialog.set_extra_child(entry)
        dialog.add_response('cancel', _('Cancel'))
        dialog.add_response('install', _('Install'))
        dialog.set_response_appearance('install',
                                       Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('install')
        dialog.set_close_response('cancel')
        dialog.connect(
            'response',
            lambda _d, r: self._start_install(
                btn, mod['name'], row, entry.get_text().strip() or None)
            if r == 'install' else None)
        dialog.present(self)

    def _confirm_remove(self, name, friendly, row):
        dialog = Adw.AlertDialog()
        dialog.set_heading(_('Remove module?'))
        dialog.set_body(
            _('“{name}” will be removed from your library. '
              'You can reinstall it from the catalogue later.').format(name=friendly))
        dialog.add_response('cancel', _('Cancel'))
        dialog.add_response('remove', _('Remove'))
        dialog.set_response_appearance('remove',
                                       Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect(
            'response',
            lambda _d, r: self._start_remove(name, row) if r == 'remove' else None)
        dialog.present(self)

    def _start_remove(self, name, row):
        def done(err):
            self._modules_changed()
            self._populate()

        self._run_async(lambda: sword_bridge.remove_module(name), done,
                        show_bar=False,
                        retry=lambda: self._start_remove(name, row))

    # ── Refresh (per tab: every catalogue that feeds it) ─────────────────────

    def _on_refresh(self, tab_id):
        wants_ebible = self._tabs[tab_id]['spec']['ebible']

        def work():
            sword_bridge.refresh_source()
            if wants_ebible:
                GLib.idle_add(self._set_progress_text,
                              _('Downloading eBible catalog…'))
                ebible_bridge.download_catalog_sync()

        def done(err):
            if not err:
                self._populate()

        self._run_async(work, done,
                        busy_msg=_('Downloading module list from CrossWire…'),
                        retry=lambda: self._on_refresh(tab_id))

    # ── Curated pack / database downloads ────────────────────────────────────

    def _pack_download(self, btn, name, download):
        """Shared flow for the catena/imagery/database downloads: byte
        progress on the window bar, button disabled while running."""
        base = _('Downloading {name}…').format(name=name)

        def progress(done_b, total):
            GLib.idle_add(self._set_progress_text,
                          _fmt_progress(base, done_b, total))

        def done(err):
            self._modules_changed()
            self._populate()

        if self._run_async(lambda: download(progress), done, busy_msg=base,
                           retry=lambda: self._pack_download(
                               btn, name, download)):
            btn.set_sensitive(False)
            btn.set_label(_('Downloading…'))

    def _on_catena_download(self, btn):
        self._pack_download(
            btn, _('Historical Commentaries'),
            lambda p: catena_bridge.download_and_install(on_progress=p))

    def _on_imagery_download(self, btn):
        self._pack_download(
            btn, _('Bible Imagery'),
            lambda p: imagery_bridge.download_and_install(on_progress=p))

    def _on_db_download(self, btn, source_id):
        src = next((s for s in open_data.get_sources() if s['id'] == source_id), None)
        if src is None:
            return
        self._pack_download(
            btn, src['label'],
            lambda p: open_data.download_source(source_id, on_progress=p))

    def _make_lexicon_pack_row(self):
        row = Adw.ActionRow()
        row.set_title(_('Scholar’s Greek Lexicon'))
        if lexicon_data.is_installed():
            row.set_subtitle(
                _('Abbott-Smith + full Liddell-Scott-Jones — Tyndale House '
                  'data (CC BY)'))
            btn = self._trash_button(
                lambda: self._confirm_remove_generic(
                    _('Scholar’s Greek Lexicon'), self._do_lexicon_remove))
        else:
            row.set_subtitle(
                _('Upgrade Greek definitions to Abbott-Smith, with the full '
                  'Liddell-Scott-Jones one click deeper · ~7 MB download'))
            btn = Gtk.Button(label=_('Download'))
            btn.add_css_class('suggested-action')
            btn.connect('clicked', self._on_lexicon_download)
        btn.set_valign(Gtk.Align.CENTER)
        row.add_suffix(btn)
        return row

    def _on_lexicon_download(self, btn):
        self._pack_download(
            btn, _('Scholar’s Greek Lexicon'),
            lambda p: lexicon_data.download_and_build(on_progress=p))

    def _do_lexicon_remove(self):
        lexicon_data.remove()
        self._modules_changed()
        self._populate()

    def _on_interlinear_download(self, btn, name):
        label = (_('Interlinear — Hebrew OT')
                 if interlinear_data.is_hebrew(name)
                 else _('Interlinear — Greek NT'))
        self._pack_download(
            btn, label,
            lambda p: interlinear_data.download_and_build(name,
                                                          on_progress=p))

    def _do_interlinear_remove(self, name):
        interlinear_data.remove(name)
        self._modules_changed()
        self._populate()

    def _do_catena_remove(self):
        catena_bridge.remove_pack()
        self._modules_changed()
        self._populate()

    def _do_imagery_remove(self):
        imagery_bridge.remove_pack()
        self._modules_changed()
        self._populate()

    def _do_db_remove(self, source_id):
        open_data.remove_source(source_id)
        self._populate()

    def _confirm_remove_generic(self, friendly, on_confirm):
        """Confirmation dialog for removing a non-SWORD pack/source."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_('Remove?'))
        dialog.set_body(
            _('“{name}” will be removed. You can download it again later.').format(
                name=friendly))
        dialog.add_response('cancel', _('Cancel'))
        dialog.add_response('remove', _('Remove'))
        dialog.set_response_appearance('remove',
                                       Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response',
                       lambda _d, r: on_confirm() if r == 'remove' else None)
        dialog.present(self)

    # ── eBible download / remove ─────────────────────────────────────────────

    # eBible download phase codes → translated status text. The text lives
    # here, not in the (English-free) ebible_bridge backend — same i18n
    # boundary as the search-truncation message.
    _EB_STATUS = {
        'download': N_('Downloading…'),
        'parse': N_('Parsing USFM…'),
        'save': N_('Saving…'),
    }

    def _on_eb_download(self, btn, tid, entry):
        title = (entry.get('shortTitle') or tid).strip()

        def on_status(code):
            GLib.idle_add(self._set_progress_text,
                          _(self._EB_STATUS.get(code, code)))

        def done(err):
            self._modules_changed()
            self._populate()

        if self._run_async(
                lambda: ebible_bridge.download_translation_sync(
                    tid, entry, on_status=on_status),
                done, busy_msg=_('Downloading {name}…').format(name=title),
                retry=lambda: self._on_eb_download(btn, tid, entry)):
            btn.set_sensitive(False)
            btn.set_label(_('Installing…'))

    def _do_eb_remove(self, tid):
        ebible_bridge.remove_translation(tid)
        self._modules_changed()
        self._populate()

    # ── Import module from file (sideload) ────────────────────────────────────

    def _on_import_clicked(self, _btn):
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Import SWORD Module'))
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name(_('SWORD module (.zip)'))
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
            self._flash(_('Drop a SWORD module .zip file to import it.'))
            return False
        self._load_zip_path(path)
        return True

    def _load_zip_path(self, path):
        state = {}

        def work():
            with open(path, 'rb') as f:
                state['data'] = f.read()
            state['mods'] = sword_bridge.inspect_module_zip(state['data'])

        def done(err):
            if not err and state.get('mods'):
                self._show_import_sheet(state['mods'], state['data'])

        self._run_async(work, done, busy_msg=_('Reading module file…'),
                        retry=lambda: self._load_zip_path(path))

    def _show_import_sheet(self, mods, zip_bytes):
        dialog = Adw.Dialog()
        dialog.set_title(_('Import Module'))
        dialog.set_content_width(440)
        dialog.set_content_height(420)

        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        cancel = Gtk.Button(label=_('Cancel'))
        cancel.connect('clicked', lambda _b: dialog.close())
        header.pack_start(cancel)
        install = Gtk.Button(label=_('Install'))
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
            checked = [(m, c, k) for m, c, k in rows if c.get_active()]
            needs_key = any(
                k is not None and not k.get_text().strip()
                for _m, _c, k in checked)
            install.set_sensitive(bool(checked) and not needs_key)
            # Button label matches the action (see the collision table in
            # ROADMAP.md): a single selected module that's already installed
            # reads Update / Reinstall / Replace; anything else is Install.
            if len(checked) == 1:
                verb, _hint, _warn = self._collision_verb(checked[0][0])
                install.set_label(_(verb))
            else:
                install.set_label(_('Install'))

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
            meta.append(_('Locked'))
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
            key_entry.set_property('placeholder-text', _('Paste the unlock key from the publisher'))
            key_entry.set_margin_start(28)
            key_entry.set_margin_top(4)
            inner.append(key_entry)

        box.append(card)
        return (mod, check, key_entry)

    @staticmethod
    def _collision_verb(mod):
        """Return (verb, subtext, warn) describing install vs installed.
        The verb is an N_-marked msgid — translate with _() at display."""
        if not mod.get('installed'):
            return N_('Install'), '', False
        new_v = mod.get('version', '')
        old_v = mod.get('installed_version', '')
        if not new_v or not old_v:
            # Can't compare meaningfully — treat as a plain reinstall.
            return N_('Reinstall'), _('Already installed'), False
        cmp = sword_bridge.cmp_version(new_v, old_v)
        if cmp > 0:
            return N_('Update'), _('Update from v{old} to v{new}').format(old=old_v, new=new_v), False
        if cmp == 0:
            return N_('Reinstall'), _('Already installed (v{old})').format(old=old_v), False
        return N_('Replace'), _('Replace v{old} with older v{new}').format(old=old_v, new=new_v), True

    def _do_import(self, zip_bytes, rows, dialog):
        selected = [m['name'] for m, c, _k in rows if c.get_active()]
        cipher_keys = {
            m['name']: k.get_text().strip()
            for m, c, k in rows
            if c.get_active() and k is not None and k.get_text().strip()
        }
        if not selected:
            return
        label = (selected[0] if len(selected) == 1
                 else ngettext('{n} module', '{n} modules',
                               len(selected)).format(n=len(selected)))

        def done(err):
            if not err:
                self._modules_changed()
            self._populate()

        if self._run_async(
                lambda: sword_bridge.install_module_from_zip(
                    zip_bytes, selected, cipher_keys),
                done, busy_msg=_('Installing {label}…').format(label=label),
                retry=lambda: self._do_import(zip_bytes, rows, dialog)):
            dialog.close()
