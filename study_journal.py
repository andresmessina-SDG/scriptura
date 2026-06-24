import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango
from a11y import set_accessible_label
from gtk_utils import clear_children
import annotations
import sword_bridge
from empty_state import compact_empty_state

_BOOK_ORDER = {book: i for i, book in enumerate(sword_bridge._ALL_BOOKS)}

# Strip / swatch / journal-card / tag-chip CSS rules are defined in
# data/style.css and loaded once at app startup by styles.load_app_css().

_HIGHLIGHT_CLASS = {
    '#ffff00': 'strip-yellow',
    '#90ee90': 'strip-green',
    '#add8e6': 'strip-blue',
    '#ffa500': 'strip-orange',
}

_HL_SWATCH_CLASS = {
    '#ffff00': 'hl-swatch-yellow',
    '#90ee90': 'hl-swatch-green',
    '#add8e6': 'hl-swatch-blue',
    '#ffa500': 'hl-swatch-orange',
}

# Per-hue class for the small list-row badge dot (coloured to its highlight;
# the name beside it stays the colourblind-safe cue).
_HL_DOT_CLASS = {
    '#ffff00': 'journal-dot-yellow',
    '#90ee90': 'journal-dot-green',
    '#add8e6': 'journal-dot-blue',
    '#ffa500': 'journal-dot-orange',
}

_HL_COLORS = ['#ffff00', '#90ee90', '#add8e6', '#ffa500']

# Cap the synchronous list build so a large journal doesn't rebuild every
# rich row on each filter keystroke; a footer pulls the next slice on demand.
_RENDER_CAP = 200


def N_(message):
    """No-op gettext marker for strings in module-level data; translated at
    display time via _()."""
    return message


# Highlight-color display names (shown as swatch tooltips), translated at
# display via _(). Replaces deriving the name from the CSS class.
_HL_NAMES = {
    '#ffff00': N_('Yellow'),
    '#90ee90': N_('Green'),
    '#add8e6': N_('Blue'),
    '#ffa500': N_('Orange'),
}


def _all_entries():
    data = annotations._load()
    entries = []
    for key, verses in data.items():
        parts = key.split('/', 2)
        if len(parts) != 3:
            continue
        module, book, chapter_str = parts
        try:
            chapter = int(chapter_str)
        except ValueError:
            continue
        for verse_str, anno in verses.items():
            try:
                verse = int(verse_str)
            except ValueError:
                continue
            if isinstance(anno, str):
                anno = {'highlight': anno, 'underline': False, 'note': None}
            if not isinstance(anno, dict):
                continue
            h = anno.get('highlight')
            u = anno.get('underline', False)
            n = anno.get('note')
            tgs = anno.get('tags', [])
            if not (h or u or n or tgs):
                continue
            entries.append({
                'module': module, 'book': book,
                'chapter': chapter, 'verse': verse,
                'highlight': h, 'underline': u, 'note': n,
                'tags': tgs, 'is_chapter_note': False,
            })
        chapter_note = verses.get('chapter_note')
        if chapter_note:
            if isinstance(chapter_note, str):
                cn_text, cn_tags = chapter_note, []
            elif isinstance(chapter_note, dict):
                cn_text, cn_tags = chapter_note.get('note', ''), chapter_note.get('tags', [])
            else:
                cn_text, cn_tags = '', []
            if cn_text.strip() or cn_tags:
                entries.append({
                    'module': module, 'book': book,
                    'chapter': chapter, 'verse': None,
                    'highlight': None, 'underline': False,
                    'note': cn_text, 'tags': cn_tags,
                    'is_chapter_note': True,
                })
    entries.sort(key=lambda e: (
        _BOOK_ORDER.get(e['book'], 999), e['chapter'], e['verse'] or 0
    ))
    return entries


def _entry_key(e):
    return (e['module'], e['book'], e['chapter'],
            None if e.get('is_chapter_note') else e['verse'])


class TagManagerWindow(Adw.Window):
    """Manage every tag used by any annotation: rename (with implicit
    merge when the new name already exists) and delete."""

    def __init__(self, on_changed=None, **kwargs):
        super().__init__(**kwargs)
        self._on_changed = on_changed
        self.set_title(_('Tag Manager'))
        self.set_default_size(440, 540)
        self._build_ui()
        self._populate_tags()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrap.set_margin_start(12)
        wrap.set_margin_end(12)
        wrap.set_margin_top(12)
        wrap.set_margin_bottom(12)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        wrap.append(self._list_box)
        scroll.set_child(wrap)
        toolbar_view.set_content(scroll)

    def _populate_tags(self):
        clear_children(self._list_box)

        counts = annotations.get_tag_counts()
        if not counts:
            empty = compact_empty_state(
                icon_name='view-list-bullet-symbolic',
                title=_('No tags yet'),
                description=_('Tag annotations from the note editor to see them here.'),
            )
            self._list_box.remove_css_class('boxed-list')
            r = Gtk.ListBoxRow()
            r.set_selectable(False)
            r.set_activatable(False)
            r.set_child(empty)
            self._list_box.append(r)
            return

        self._list_box.add_css_class('boxed-list')
        for tag in sorted(counts.keys()):
            self._list_box.append(self._make_tag_row(tag, counts[tag]))

    def _make_tag_row(self, tag, count):
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(tag))
        row.set_subtitle(ngettext(
            '{n} annotation', '{n} annotations', count).format(n=count))

        rename_btn = Gtk.Button(icon_name='document-edit-symbolic')
        rename_btn.add_css_class('flat')
        rename_btn.set_valign(Gtk.Align.CENTER)
        rename_btn.set_tooltip_text(_('Rename or merge into another tag'))
        set_accessible_label(rename_btn, _('Rename or merge into another tag'))
        rename_btn.connect('clicked', self._on_rename_tag, tag)
        row.add_suffix(rename_btn)

        del_btn = Gtk.Button(icon_name='user-trash-symbolic')
        del_btn.add_css_class('flat')
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_tooltip_text(_('Remove tag from all annotations'))
        set_accessible_label(del_btn, _('Remove tag from all annotations'))
        del_btn.connect('clicked', self._on_delete_tag, tag)
        row.add_suffix(del_btn)

        return row

    def _on_rename_tag(self, _btn, tag):
        dlg = Adw.AlertDialog(
            heading=_('Rename “{tag}”').format(tag=tag),
            body=_('Type the new name. If it matches an existing tag, '
                   'the two will be merged.'),
        )
        entry = Gtk.Entry()
        entry.set_text(tag)
        entry.set_activates_default(True)
        dlg.set_extra_child(entry)
        dlg.add_response('cancel', _('Cancel'))
        dlg.add_response('rename', _('Rename'))
        dlg.set_response_appearance('rename', Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response('rename')

        def on_response(d, response):
            if response == 'rename':
                new = entry.get_text().strip()
                if new and new != tag:
                    annotations.rename_tag(tag, new)
                    self._populate_tags()
                    if self._on_changed:
                        self._on_changed()
            d.close()

        dlg.connect('response', on_response)
        dlg.present(self)

    def _on_delete_tag(self, _btn, tag):
        dlg = Adw.AlertDialog(
            heading=_('Remove “{tag}”?').format(tag=tag),
            body=_('This removes the tag from every annotation it appears '
                   'on. Notes and highlights stay where they are.'),
        )
        dlg.add_response('cancel', _('Cancel'))
        dlg.add_response('delete', _('Remove'))
        dlg.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response('cancel')

        def on_response(d, response):
            if response == 'delete':
                annotations.delete_tag(tag)
                self._populate_tags()
                if self._on_changed:
                    self._on_changed()
            d.close()

        dlg.connect('response', on_response)
        dlg.present(self)


class StudyJournalWindow(Adw.Window):
    def __init__(self, on_navigate, on_annotation_changed=None, **kwargs):
        super().__init__(**kwargs)
        self._on_navigate = on_navigate
        self._on_annotation_changed = on_annotation_changed
        self._entries = []
        self._filtered = []
        self._updating = False
        self._current_entry = None
        self._preserve_select = None
        self._preserve = None
        self._more_row = None
        self._shown = 0
        self.set_title(_('Study Journal'))
        self.set_default_size(1080, 720)

        self._build_ui()
        self._reload()

    def _build_ui(self):
        # Master/detail via NavigationSplitView: list + editor side-by-side when
        # wide, collapsing to a single navigation stack (list → entry, with a
        # back button) once the window narrows past the breakpoint below.
        self._split_view = Adw.NavigationSplitView()
        self._split_view.set_min_sidebar_width(340)
        self._split_view.set_max_sidebar_width(440)
        self._split_view.set_sidebar_width_fraction(0.34)

        # ── Sidebar page: the list + its header (refresh · tags · export) ─────
        sidebar_tv = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar_tv.add_top_bar(sidebar_header)

        refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic')
        refresh_btn.set_tooltip_text(_('Refresh'))
        set_accessible_label(refresh_btn, _('Refresh'))
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda _: self._reload())
        sidebar_header.pack_start(refresh_btn)

        tag_mgr_btn = Gtk.Button(icon_name='view-list-bullet-symbolic')
        tag_mgr_btn.set_tooltip_text(_('Manage tags'))
        set_accessible_label(tag_mgr_btn, _('Manage tags'))
        tag_mgr_btn.add_css_class('flat')
        tag_mgr_btn.connect('clicked', self._on_open_tag_manager)
        sidebar_header.pack_start(tag_mgr_btn)

        export_btn = Gtk.Button(icon_name='document-save-symbolic')
        export_btn.set_tooltip_text(_('Export to text file'))
        set_accessible_label(export_btn, _('Export to text file'))
        export_btn.connect('clicked', self._on_export)
        sidebar_header.pack_end(export_btn)

        sidebar_tv.set_content(self._build_sidebar())
        sidebar_page = Adw.NavigationPage(title=_('Study Journal'))
        sidebar_page.set_child(sidebar_tv)
        self._split_view.set_sidebar(sidebar_page)

        # ── Content page: the editor + its header. The verse ref lives in this
        # header (a WindowTitle), and the back button is added to it
        # automatically when the split view collapses. ───────────────────────
        content_tv = Adw.ToolbarView()
        content_header = Adw.HeaderBar()
        self._detail_title = Adw.WindowTitle(title='', subtitle='')
        content_header.set_title_widget(self._detail_title)
        content_tv.add_top_bar(content_header)
        content_tv.set_content(self._build_detail_stack())
        self._content_page = Adw.NavigationPage(title=_('Annotation'))
        self._content_page.set_child(content_tv)
        self._split_view.set_content(self._content_page)

        # Toasts float over the whole split view.
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._split_view)
        self.set_content(self._toast_overlay)

        # Collapse to a single page once the window can no longer hold both
        # panes side-by-side. The uncollapsed split view needs ~657px (sidebar
        # 340 + editor 317); collapsing at 660 avoids a band where the two-pane
        # layout overflows the window (the AdwToastOverlay width warning).
        bp = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse('max-width: 660px'))
        bp.add_setter(self._split_view, 'collapsed', True)
        self.add_breakpoint(bp)

    def _build_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(340, -1)

        # ── Search + filters ──────────────────────────────────────────────────
        filter_region = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        filter_region.set_margin_start(8)
        filter_region.set_margin_end(8)
        filter_region.set_margin_top(8)
        filter_region.set_margin_bottom(6)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(
            _('Search notes, tags, references…'))
        self._search_entry.connect(
            'search-changed', lambda *_: self._apply_filter())
        filter_region.append(self._search_entry)

        grid = Gtk.Grid(row_spacing=4, column_spacing=6)
        grid.set_column_homogeneous(True)

        self._type_drop = Gtk.DropDown(
            model=Gtk.StringList.new(
                [_('All types'), _('Notes'), _('Highlights'), _('Underlines')])
        )
        self._type_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._type_drop, 0, 0, 1, 1)

        self._tag_drop = Gtk.DropDown(model=Gtk.StringList.new([_('All tags')]))
        self._tag_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._tag_drop, 1, 0, 1, 1)

        self._mod_drop = Gtk.DropDown(model=Gtk.StringList.new([_('All modules')]))
        self._mod_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._mod_drop, 0, 1, 1, 1)

        # The book dropdown shows localized names but filters by the canonical
        # English key; _book_keys holds those keys parallel to the model rows
        # after the "All books" sentinel, so we match by index, not by label.
        self._book_keys: list[str] = []
        self._book_drop = Gtk.DropDown(model=Gtk.StringList.new([_('All books')]))
        self._book_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._book_drop, 1, 1, 1, 1)

        filter_region.append(grid)
        sidebar.append(filter_region)

        filter_div = Gtk.Separator()
        filter_div.add_css_class('journal-divider')
        sidebar.append(filter_div)

        # ── Count + list ──────────────────────────────────────────────────────
        self._count_lbl = Gtk.Label(label='', xalign=0)
        self._count_lbl.set_margin_start(12)
        self._count_lbl.set_margin_top(8)
        self._count_lbl.set_margin_bottom(2)
        self._count_lbl.add_css_class('dim-label')

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.set_activate_on_single_click(False)
        self._list.add_css_class('journal-list')
        self._list.connect('row-activated', self._on_row_activated)
        self._list.connect('row-selected', self._on_row_selected)

        list_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        list_wrap.set_margin_start(8)
        list_wrap.set_margin_end(8)
        list_wrap.set_margin_top(2)
        list_wrap.set_margin_bottom(8)
        list_wrap.append(self._count_lbl)
        list_wrap.append(self._list)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(list_wrap)
        sidebar.append(scroll)

        return sidebar

    def _build_detail_stack(self):
        self._detail_stack = Gtk.Stack()
        self._detail_stack.set_transition_type(
            Gtk.StackTransitionType.CROSSFADE)
        self._detail_stack.set_transition_duration(150)

        empty = Adw.StatusPage(
            icon_name='document-edit-symbolic',
            title=_('No entry selected'),
            description=_('Pick an annotation from the list to view or edit it.'),
        )
        empty.set_vexpand(True)
        self._detail_stack.add_named(empty, 'empty')

        self._detail_stack.add_named(self._build_detail_editor(), 'editor')
        self._detail_stack.set_visible_child_name('empty')
        return self._detail_stack

    def _build_detail_editor(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # The verse ref + module now live in the content page's header
        # (self._detail_title); the body starts straight at the highlight row.

        # Highlight + underline row (hidden for chapter notes). A WrapBox so the
        # controls wrap to a second line on a narrow window instead of forcing
        # the editor wider than the list (which then clips when collapsed).
        self._hl_row = Adw.WrapBox(child_spacing=8, line_spacing=6)
        hl_label = Gtk.Label(label=_('Highlight'), xalign=0)
        hl_label.set_valign(Gtk.Align.CENTER)
        self._hl_row.append(hl_label)

        # Swatches + clear stay together as one unit (never split mid-row).
        swatch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._hl_buttons = {}
        for stored_color in _HL_COLORS:
            btn = Gtk.Button()
            btn.add_css_class('hl-swatch')
            btn.add_css_class(_HL_SWATCH_CLASS[stored_color])
            name = _(_HL_NAMES[stored_color])
            # Muted initial as a non-hue (colorblind-safe) cue — see .hl-letter.
            letter = Gtk.Label(label=name[:1])
            letter.add_css_class('hl-letter')
            btn.set_child(letter)
            btn.set_tooltip_text(name)
            set_accessible_label(btn, name)
            btn.connect('clicked', self._on_hl_click, stored_color)
            swatch_box.append(btn)
            self._hl_buttons[stored_color] = btn

        clear_btn = Gtk.Button(icon_name='edit-clear-symbolic')
        clear_btn.add_css_class('flat')
        clear_btn.set_tooltip_text(_('Clear highlight'))
        set_accessible_label(clear_btn, _('Clear highlight'))
        clear_btn.connect('clicked', self._on_hl_click, None)
        swatch_box.append(clear_btn)
        self._hl_row.append(swatch_box)

        self._ul_check = Gtk.CheckButton(label=_('Underline'))
        self._ul_check.set_valign(Gtk.Align.CENTER)
        self._ul_handler = self._ul_check.connect(
            'toggled', self._on_ul_toggled)
        self._hl_row.append(self._ul_check)

        box.append(self._hl_row)

        # Tags
        tags_lbl = Gtk.Label(label=_('Tags (comma-separated)'), xalign=0)
        tags_lbl.add_css_class('dim-label')
        tags_lbl.add_css_class('caption')
        box.append(tags_lbl)
        self._tags_entry = Gtk.Entry()
        self._tags_entry.set_placeholder_text(_('e.g. prayer, faith, covenant'))
        box.append(self._tags_entry)

        # Note text
        note_lbl = Gtk.Label(label=_('Note'), xalign=0)
        note_lbl.add_css_class('dim-label')
        note_lbl.add_css_class('caption')
        box.append(note_lbl)

        self._note_view = Gtk.TextView()
        self._note_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._note_view.set_left_margin(8)
        self._note_view.set_right_margin(8)
        self._note_view.set_top_margin(6)
        self._note_view.set_bottom_margin(6)

        note_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        note_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        note_scroll.set_child(self._note_view)
        note_scroll.add_css_class('journal-note-card')
        box.append(note_scroll)

        # Action row: Go to verse + Save
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        go_btn = Gtk.Button(label=_('Go to verse'))
        go_btn.connect('clicked', self._on_detail_navigate)
        action_row.append(go_btn)

        spacer = Gtk.Box(hexpand=True)
        action_row.append(spacer)

        save_btn = Gtk.Button(label=_('Save note & tags'))
        save_btn.add_css_class('suggested-action')
        save_btn.connect('clicked', self._on_detail_save)
        action_row.append(save_btn)

        box.append(action_row)

        return box

    # ── Data ──────────────────────────────────────────────────────────────────

    def _reload(self):
        self._updating = True
        self._entries = _all_entries()

        modules = [_('All modules')] + sorted({e['module'] for e in self._entries})
        book_keys = [b for b in sword_bridge._ALL_BOOKS
                     if any(e['book'] == b for e in self._entries)]
        all_tags = [_('All tags')] + sorted(
            {t for e in self._entries for t in e.get('tags', [])})

        # Preserve current dropdown selections so a save doesn't reset filters
        prev_type = self._type_drop.get_selected()
        prev_mod_text = self._dropdown_text(self._mod_drop)
        prev_book_key = self._selected_book_key()
        prev_tag_text = self._dropdown_text(self._tag_drop)

        self._mod_drop.set_model(Gtk.StringList.new(modules))
        self._book_keys = book_keys
        self._book_drop.set_model(Gtk.StringList.new(
            [_('All books')] + [book_label(b) for b in book_keys]))
        self._tag_drop.set_model(Gtk.StringList.new(all_tags))

        self._select_by_text(self._mod_drop, modules, prev_mod_text)
        self._book_drop.set_selected(
            book_keys.index(prev_book_key) + 1 if prev_book_key in book_keys else 0)
        self._select_by_text(self._tag_drop, all_tags, prev_tag_text)
        self._type_drop.set_selected(prev_type)

        self._updating = False
        self._apply_filter()

    @staticmethod
    def _dropdown_text(drop):
        model = drop.get_model()
        idx = drop.get_selected()
        if model is None or idx >= model.get_n_items():
            return None
        return model.get_string(idx)

    @staticmethod
    def _select_by_text(drop, items, text):
        if text in items:
            drop.set_selected(items.index(text))
        else:
            drop.set_selected(0)

    def _selected_book_key(self):
        """Canonical English book name for the book dropdown's selection, or
        None for the 'All books' sentinel (index 0)."""
        idx = self._book_drop.get_selected()
        if idx >= 1 and idx - 1 < len(self._book_keys):
            return self._book_keys[idx - 1]
        return None

    def _filtered_entries(self):
        type_map = {0: 'all', 1: 'notes', 2: 'highlights', 3: 'underlines'}
        tf = type_map.get(self._type_drop.get_selected(), 'all')

        all_modules = _('All modules')
        all_tags = _('All tags')
        mf = self._dropdown_text(self._mod_drop) or all_modules
        bf_key = self._selected_book_key()
        tag_filter = self._dropdown_text(self._tag_drop) or all_tags
        q = self._search_entry.get_text().strip().lower()

        result = []
        for e in self._entries:
            if mf != all_modules and e['module'] != mf:
                continue
            if bf_key is not None and e['book'] != bf_key:
                continue
            if tf == 'notes' and not e['note']:
                continue
            if tf == 'highlights' and not e['highlight']:
                continue
            if tf == 'underlines' and not e['underline']:
                continue
            if tag_filter != all_tags and tag_filter not in e.get('tags', []):
                continue
            if q:
                disp_book = book_label(e['book'])
                ref = (f'{disp_book} {e["chapter"]}' if e.get('is_chapter_note')
                       else f'{disp_book} {e["chapter"]}:{e["verse"]}')
                haystack = ' '.join([
                    e['module'].lower(),
                    e['book'].lower(),
                    ref.lower(),
                    (e['note'] or '').lower(),
                    ' '.join(t.lower() for t in e.get('tags', [])),
                ])
                if q not in haystack:
                    continue
            result.append(e)
        return result

    def _apply_filter(self):
        if self._updating:
            return
        self._filtered = self._filtered_entries()

        # Clear existing rows (also drops any prior footer).
        clear_children(self._list)
        self._more_row = None
        self._shown = 0

        n = len(self._filtered)
        self._count_lbl.set_text(ngettext('{n} entry', '{n} entries', n).format(n=n))

        self._preserve = self._preserve_select
        self._preserve_select = None

        if not self._filtered:
            if not self._entries:
                title = _('No annotations yet')
                desc = _('Right-click a verse to highlight it or add a note.')
            else:
                title = _('No matches')
                desc = _('Try a different search or filter.')
            empty = compact_empty_state(
                icon_name='document-edit-symbolic',
                title=title,
                description=desc,
            )
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.set_child(empty)
            self._list.append(row)
            self._current_entry = None
            self._clear_detail_title()
            self._detail_stack.set_visible_child_name('empty')
            return

        # Render the first slice. If a preserved entry (set by save/delete)
        # still exists further down, keep materialising slices until it
        # appears so the edited row stays selected after the reload.
        preserve_present = self._preserve is not None and any(
            _entry_key(e) == self._preserve for e in self._filtered)
        target_row = self._append_journal_rows()
        while (target_row is None and preserve_present
               and self._shown < len(self._filtered)):
            target_row = self._append_journal_rows()

        if target_row is not None:
            self._list.select_row(target_row)
            # row-selected fires asynchronously; populate immediately too
            # so the detail pane updates with the freshly-reloaded entry
            self._current_entry = target_row._entry
            self._populate_detail(target_row._entry)
            self._detail_stack.set_visible_child_name('editor')
        elif self._preserve is not None:
            # Entry no longer exists (all annotations cleared); reset detail
            self._current_entry = None
            self._clear_detail_title()
            self._detail_stack.set_visible_child_name('empty')

    def _append_journal_rows(self):
        """Append the next _RENDER_CAP slice of self._filtered, then a
        Show-more footer if rows remain. Returns the row matching the
        preserved entry key if it lands in this slice, else None."""
        if self._more_row is not None:
            self._list.remove(self._more_row)
            self._more_row = None

        target = None
        chunk = self._filtered[self._shown:self._shown + _RENDER_CAP]
        for entry in chunk:
            row = self._make_row(entry)
            self._list.append(row)
            if self._preserve and _entry_key(entry) == self._preserve:
                target = row
        self._shown += len(chunk)

        if self._shown < len(self._filtered):
            self._more_row = self._make_more_row()
            self._list.append(self._more_row)
        return target

    def _make_more_row(self):
        remaining = len(self._filtered) - self._shown
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        btn = Gtk.Button(label=ngettext(
            'Show {n} more', 'Show {n} more', remaining).format(n=remaining))
        btn.add_css_class('flat')
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(4)
        btn.set_margin_bottom(4)
        btn.connect('clicked', lambda _b: self._append_journal_rows())
        row.set_child(btn)
        return row

    # ── Row builder ───────────────────────────────────────────────────────────

    def _make_row(self, entry):
        row = Gtk.ListBoxRow()
        row._entry = entry

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # Left color strip
        strip = Gtk.Box()
        strip.set_size_request(5, -1)
        if entry.get('is_chapter_note'):
            strip_class = 'strip-plain'
        else:
            strip_class = (_HIGHLIGHT_CLASS.get(entry['highlight'], 'strip-plain')
                           if entry['highlight'] else 'strip-plain')
        strip.add_css_class(strip_class)
        outer.append(strip)
        row._strip = strip
        row._strip_class = strip_class

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.set_hexpand(True)
        content.set_margin_start(10)
        content.set_margin_end(10)
        content.set_margin_top(8)
        content.set_margin_bottom(8)

        # Reference + module
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if entry.get('is_chapter_note'):
            ref_text = _('{ref} — Chapter Note').format(
                ref=f'{book_label(entry["book"])} {entry["chapter"]}')
        else:
            ref_text = f'{book_label(entry["book"])} {entry["chapter"]}:{entry["verse"]}'
        ref = Gtk.Label(label=ref_text, xalign=0, hexpand=True)
        ref.set_ellipsize(Pango.EllipsizeMode.END)
        ref.add_css_class('heading')
        top.append(ref)

        mod_lbl = Gtk.Label(label=entry['module'], xalign=1)
        mod_lbl.add_css_class('dim-label')
        mod_lbl.add_css_class('caption')
        top.append(mod_lbl)
        content.append(top)

        # Type badges — a hue dot coloured to the highlight (the name beside it
        # stays the colourblind-safe cue), then plain captions for underline /
        # note. No emoji: muted captions in the app's quiet vocabulary.
        if not entry.get('is_chapter_note'):
            badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            have_badge = False
            if entry['highlight']:
                have_badge = True
                hue = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                dot = Gtk.Label(label='●')
                dot.set_valign(Gtk.Align.CENTER)
                dot.add_css_class('journal-dot')
                dot_cls = _HL_DOT_CLASS.get(entry['highlight'])
                if dot_cls:
                    dot.add_css_class(dot_cls)
                hl_name = _HL_NAMES.get(entry['highlight'])
                name = Gtk.Label(
                    label=_(hl_name) if hl_name else _('Highlight'), xalign=0)
                name.add_css_class('dim-label')
                name.add_css_class('caption')
                hue.append(dot)
                hue.append(name)
                badges.append(hue)
            for present, text in ((entry['underline'], _('Underline')),
                                  (entry['note'], _('Note'))):
                if present:
                    have_badge = True
                    lbl = Gtk.Label(label=text, xalign=0)
                    lbl.add_css_class('dim-label')
                    lbl.add_css_class('caption')
                    badges.append(lbl)
            if have_badge:
                content.append(badges)

        # Note preview (single line in compact sidebar; full text in detail)
        if entry['note']:
            note_lbl = Gtk.Label(label=entry['note'], xalign=0)
            note_lbl.set_wrap(True)
            note_lbl.set_lines(2)
            note_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(note_lbl)

        # Tag chips — clicking sets the Tag filter to that tag
        tags = entry.get('tags', [])
        if tags:
            tag_flow = Gtk.FlowBox()
            tag_flow.set_selection_mode(Gtk.SelectionMode.NONE)
            tag_flow.set_max_children_per_line(20)
            tag_flow.set_row_spacing(2)
            tag_flow.set_column_spacing(4)
            tag_flow.set_homogeneous(False)
            for t in tags:
                btn = Gtk.Button(label=f'#{t}')
                btn.add_css_class('tag-chip')
                btn.set_tooltip_text(_('Filter by #{tag}').format(tag=t))
                btn.connect('clicked',
                            lambda _b, _t=t: self._filter_by_tag(_t))
                tag_flow.append(btn)
            content.append(tag_flow)

        outer.append(content)

        # Trash button
        del_btn = Gtk.Button(icon_name='user-trash-symbolic')
        del_btn.add_css_class('flat')
        del_btn.add_css_class('journal-del')
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_margin_end(6)
        del_btn.set_tooltip_text(_('Delete annotation'))
        set_accessible_label(del_btn, _('Delete annotation'))
        del_btn.connect('clicked', self._on_delete_entry, entry)
        outer.append(del_btn)

        row.set_child(outer)
        return row

    # ── Detail pane ───────────────────────────────────────────────────────────

    def _on_row_selected(self, _list, row):
        if row is None or not hasattr(row, '_entry'):
            self._current_entry = None
            self._clear_detail_title()
            self._detail_stack.set_visible_child_name('empty')
            return
        self._current_entry = row._entry
        self._populate_detail(row._entry)
        self._detail_stack.set_visible_child_name('editor')
        # When collapsed, navigate into the entry (pushes the content page +
        # its back button); side-by-side this is a visual no-op.
        self._split_view.set_show_content(True)

    def _clear_detail_title(self):
        self._detail_title.set_title('')
        self._detail_title.set_subtitle('')

    def _populate_detail(self, entry):
        is_cn = bool(entry.get('is_chapter_note'))

        if is_cn:
            ref = _('{ref} — Chapter Note').format(
                ref=f'{book_label(entry["book"])} {entry["chapter"]}')
        else:
            ref = f'{book_label(entry["book"])} {entry["chapter"]}:{entry["verse"]}'
        self._detail_title.set_title(ref)
        self._detail_title.set_subtitle(entry.get('module', ''))

        self._hl_row.set_visible(not is_cn)
        if not is_cn:
            current = entry.get('highlight')
            for color, btn in self._hl_buttons.items():
                if color == current:
                    btn.add_css_class('selected')
                else:
                    btn.remove_css_class('selected')
            # block to avoid re-firing _on_ul_toggled and looping into save
            self._ul_check.handler_block(self._ul_handler)
            self._ul_check.set_active(bool(entry.get('underline')))
            self._ul_check.handler_unblock(self._ul_handler)

        self._tags_entry.set_text(', '.join(entry.get('tags', []) or []))
        self._note_view.get_buffer().set_text(entry.get('note') or '')

    def _on_hl_click(self, _btn, color):
        e = self._current_entry
        if not e or e.get('is_chapter_note'):
            return
        annotations.save_highlight(
            e['module'], e['book'], e['chapter'], e['verse'], color)
        e['highlight'] = color
        # Swatch selected styling
        for c, btn in self._hl_buttons.items():
            if c == color:
                btn.add_css_class('selected')
            else:
                btn.remove_css_class('selected')
        # Row strip color
        row = self._row_for_entry(e)
        if row is not None and hasattr(row, '_strip'):
            new_class = (_HIGHLIGHT_CLASS.get(color, 'strip-plain')
                         if color else 'strip-plain')
            if new_class != row._strip_class:
                row._strip.remove_css_class(row._strip_class)
                row._strip.add_css_class(new_class)
                row._strip_class = new_class
        if self._on_annotation_changed:
            self._on_annotation_changed(
                e['module'], e['book'], e['chapter'], e['verse'])

    def _on_ul_toggled(self, btn):
        e = self._current_entry
        if not e or e.get('is_chapter_note'):
            return
        enabled = btn.get_active()
        annotations.save_underline(
            e['module'], e['book'], e['chapter'], e['verse'], enabled)
        e['underline'] = enabled
        if self._on_annotation_changed:
            self._on_annotation_changed(
                e['module'], e['book'], e['chapter'], e['verse'])

    def _filter_by_tag(self, tag):
        """Set the Tag filter dropdown to `tag` (no-op if not in the model)."""
        model = self._tag_drop.get_model()
        if model is None:
            return
        items = [model.get_string(i) for i in range(model.get_n_items())]
        if tag in items:
            self._tag_drop.set_selected(items.index(tag))

    def _row_for_entry(self, entry):
        child = self._list.get_first_child()
        while child:
            if getattr(child, '_entry', None) is entry:
                return child
            child = child.get_next_sibling()
        return None

    def _on_detail_save(self, _btn):
        e = self._current_entry
        if not e:
            return
        buf = self._note_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        text = text.rstrip() or None
        raw_tags = [t.strip() for t in self._tags_entry.get_text().split(',')
                    if t.strip()]

        if e.get('is_chapter_note'):
            annotations.save_chapter_note(
                e['module'], e['book'], e['chapter'], text or '')
            annotations.save_chapter_note_tags(
                e['module'], e['book'], e['chapter'], raw_tags)
        else:
            annotations.save_note(
                e['module'], e['book'], e['chapter'], e['verse'], text)
            annotations.save_tags(
                e['module'], e['book'], e['chapter'], e['verse'], raw_tags)

        if self._on_annotation_changed:
            v = None if e.get('is_chapter_note') else e['verse']
            self._on_annotation_changed(e['module'], e['book'], e['chapter'], v)

        self._toast(_('Saved'))
        self._preserve_select = _entry_key(e)
        self._reload()

    def _on_detail_navigate(self, _btn):
        e = self._current_entry
        if not e:
            return
        self._on_navigate(e['module'], e['book'], e['chapter'],
                          e['verse'] or 1)

    def _toast(self, msg):
        toast = Adw.Toast.new(msg)
        toast.set_timeout(2)
        self._toast_overlay.add_toast(toast)

    # ── Existing actions (delete / activate / export) ─────────────────────────

    def _on_delete_entry(self, _btn, entry):
        verse = None if entry.get('is_chapter_note') else entry['verse']
        annotations.delete_annotation(
            entry['module'], entry['book'], entry['chapter'], verse
        )
        # If we just deleted the currently-selected entry, the detail pane
        # will reset to empty when _reload finds no matching row to restore.
        self._preserve_select = _entry_key(entry)
        self._reload()
        if self._on_annotation_changed:
            self._on_annotation_changed(
                entry['module'], entry['book'], entry['chapter'], verse)

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, '_entry'):
            e = row._entry
            self._on_navigate(e['module'], e['book'], e['chapter'],
                              e['verse'] or 1)

    def _on_open_tag_manager(self, _btn):
        if (getattr(self, '_tag_mgr_win', None)
                and self._tag_mgr_win.get_visible()):
            self._tag_mgr_win.present()
            return
        self._tag_mgr_win = TagManagerWindow(
            on_changed=self._reload,
            transient_for=self,
            modal=False,
        )
        self._tag_mgr_win.present()

    def _on_export(self, _btn):
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Export Study Journal'))
        dialog.set_initial_name('study_journal.txt')
        dialog.save(self, None, self._on_export_finish)

    def _on_export_finish(self, dialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # cancelled, or no location chosen
        path = gfile.get_path() if gfile else None
        if not path:
            self._show_export_error(
                _('Please choose a location on this computer.'))
            return
        lines = [_('Study Journal'), '=' * 40, '']
        for e in self._filtered_entries():
            if e.get('is_chapter_note'):
                lines.append(_('{ref} — Chapter Note').format(
                    ref=f'{book_label(e["book"])} {e["chapter"]}') + f'  ({e["module"]})')
            else:
                lines.append(f'{book_label(e["book"])} {e["chapter"]}:{e["verse"]}  ({e["module"]})')
                types = []
                if e['highlight']:
                    types.append(_('Highlight'))
                if e['underline']:
                    types.append(_('Underline'))
                if types:
                    lines.append(f'  [{", ".join(types)}]')
            if e['note']:
                lines.append(f'  {e["note"]}')
            if e.get('tags'):
                lines.append('  ' + _('Tags: {tags}').format(
                    tags=', '.join('#' + t for t in e['tags'])))
            lines.append('')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
        except Exception as ex:
            self._show_export_error(
                _('Could not write to {path}:\n{error}').format(path=path, error=ex))

    def _show_export_error(self, msg):
        dlg = Adw.AlertDialog(heading=_('Export failed'), body=msg)
        dlg.add_response('ok', _('OK'))
        dlg.present(self)
