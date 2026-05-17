import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango
import annotations
import sword_bridge

_BOOK_ORDER = {book: i for i, book in enumerate(sword_bridge._ALL_BOOKS)}

_STRIP_CSS = b"""
.strip-yellow { background-color: #d4be62; border-radius: 3px 0 0 3px; }
.strip-green  { background-color: #8db58a; border-radius: 3px 0 0 3px; }
.strip-blue   { background-color: #7fa3c1; border-radius: 3px 0 0 3px; }
.strip-orange { background-color: #c8a575; border-radius: 3px 0 0 3px; }
.strip-plain  { background-color: alpha(@borders, 0.6); border-radius: 3px 0 0 3px; }
"""

_HIGHLIGHT_CLASS = {
    '#ffff00': 'strip-yellow',
    '#90ee90': 'strip-green',
    '#add8e6': 'strip-blue',
    '#ffa500': 'strip-orange',
}

_css_loaded = False


def _ensure_strip_css():
    global _css_loaded
    if _css_loaded:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_STRIP_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_loaded = True


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


class StudyJournalWindow(Adw.Window):
    def __init__(self, on_navigate, on_annotation_changed=None, **kwargs):
        super().__init__(**kwargs)
        self._on_navigate = on_navigate
        self._on_annotation_changed = on_annotation_changed
        self._entries = []
        self._updating = False
        self.set_title('Study Journal')
        self.set_default_size(660, 720)

        _ensure_strip_css()

        self._build_ui()
        self._reload()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # ── Header ────────────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic')
        refresh_btn.set_tooltip_text('Refresh')
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda _: self._reload())
        header.pack_start(refresh_btn)

        export_btn = Gtk.Button(icon_name='document-save-symbolic')
        export_btn.set_tooltip_text('Export to text file')
        export_btn.connect('clicked', self._on_export)
        header.pack_end(export_btn)

        # ── Filter bar ────────────────────────────────────────────────────────
        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filter_bar.set_margin_start(12)
        filter_bar.set_margin_end(12)
        filter_bar.set_margin_top(6)
        filter_bar.set_margin_bottom(6)

        filter_bar.append(Gtk.Label(label='Show:'))
        self._type_drop = Gtk.DropDown(
            model=Gtk.StringList.new(['All', 'Notes', 'Highlights', 'Underlines'])
        )
        self._type_drop.connect('notify::selected', lambda *_: self._apply_filter())
        filter_bar.append(self._type_drop)

        filter_bar.append(Gtk.Label(label='Module:'))
        self._mod_drop = Gtk.DropDown(model=Gtk.StringList.new(['All']))
        self._mod_drop.connect('notify::selected', lambda *_: self._apply_filter())
        filter_bar.append(self._mod_drop)

        filter_bar.append(Gtk.Label(label='Book:'))
        self._book_drop = Gtk.DropDown(model=Gtk.StringList.new(['All']))
        self._book_drop.connect('notify::selected', lambda *_: self._apply_filter())
        filter_bar.append(self._book_drop)

        filter_bar.append(Gtk.Label(label='Tag:'))
        self._tag_drop = Gtk.DropDown(model=Gtk.StringList.new(['All']))
        self._tag_drop.connect('notify::selected', lambda *_: self._apply_filter())
        filter_bar.append(self._tag_drop)

        toolbar_view.add_top_bar(filter_bar)
        toolbar_view.add_top_bar(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Count label ───────────────────────────────────────────────────────
        self._count_lbl = Gtk.Label(label='', xalign=0)
        self._count_lbl.set_margin_start(12)
        self._count_lbl.set_margin_top(8)
        self._count_lbl.set_margin_bottom(2)
        self._count_lbl.add_css_class('dim-label')

        # ── Results list ──────────────────────────────────────────────────────
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class('boxed-list')
        self._list.connect('row-activated', self._on_row_activated)

        list_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        list_wrap.set_margin_start(12)
        list_wrap.set_margin_end(12)
        list_wrap.set_margin_top(4)
        list_wrap.set_margin_bottom(12)
        list_wrap.append(self._count_lbl)
        list_wrap.append(self._list)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(list_wrap)
        toolbar_view.set_content(scroll)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _reload(self):
        self._updating = True
        self._entries = _all_entries()

        modules = ['All'] + sorted({e['module'] for e in self._entries})
        books = ['All'] + [b for b in sword_bridge._ALL_BOOKS
                           if any(e['book'] == b for e in self._entries)]

        all_tags = ['All'] + sorted({t for e in self._entries for t in e.get('tags', [])})

        self._mod_drop.set_model(Gtk.StringList.new(modules))
        self._mod_drop.set_selected(0)
        self._book_drop.set_model(Gtk.StringList.new(books))
        self._book_drop.set_selected(0)
        self._tag_drop.set_model(Gtk.StringList.new(all_tags))
        self._tag_drop.set_selected(0)
        self._type_drop.set_selected(0)

        self._updating = False
        self._apply_filter()

    def _filtered_entries(self):
        type_map = {0: 'all', 1: 'notes', 2: 'highlights', 3: 'underlines'}
        tf = type_map.get(self._type_drop.get_selected(), 'all')

        modules = ['All'] + sorted({e['module'] for e in self._entries})
        mi = self._mod_drop.get_selected()
        mf = modules[mi] if mi < len(modules) else 'All'

        books = ['All'] + [b for b in sword_bridge._ALL_BOOKS
                           if any(e['book'] == b for e in self._entries)]
        bi = self._book_drop.get_selected()
        bf = books[bi] if bi < len(books) else 'All'

        all_tags = ['All'] + sorted({t for e in self._entries for t in e.get('tags', [])})
        ti = self._tag_drop.get_selected()
        tag_filter = all_tags[ti] if ti < len(all_tags) else 'All'

        result = []
        for e in self._entries:
            if mf != 'All' and e['module'] != mf:
                continue
            if bf != 'All' and e['book'] != bf:
                continue
            if tf == 'notes' and not e['note']:
                continue
            if tf == 'highlights' and not e['highlight']:
                continue
            if tf == 'underlines' and not e['underline']:
                continue
            if tag_filter != 'All' and tag_filter not in e.get('tags', []):
                continue
            result.append(e)
        return result

    def _apply_filter(self):
        if self._updating:
            return
        filtered = self._filtered_entries()

        child = self._list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

        n = len(filtered)
        self._count_lbl.set_text(f'{n} entr{"y" if n == 1 else "ies"}')

        if not filtered:
            if not self._entries:
                title = 'No annotations yet'
                desc = 'Right-click a verse to highlight it or add a note.'
            else:
                title = 'Nothing matches these filters'
                desc = 'Try a wider Type, Module, Book, or Tag.'
            empty = Adw.StatusPage(
                icon_name='document-edit-symbolic',
                title=title,
                description=desc,
            )
            empty.set_vexpand(True)
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.set_child(empty)
            self._list.append(row)
            self._list.remove_css_class('boxed-list')
            return

        self._list.add_css_class('boxed-list')
        for entry in filtered:
            self._list.append(self._make_row(entry))

    # ── Row builder ───────────────────────────────────────────────────────────

    def _make_row(self, entry):
        row = Gtk.ListBoxRow()
        row._entry = entry

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # Left color strip
        strip = Gtk.Box()
        strip.set_size_request(5, -1)
        if entry.get('is_chapter_note'):
            strip.add_css_class('strip-plain')
        else:
            css_class = _HIGHLIGHT_CLASS.get(entry['highlight'], 'strip-plain') \
                        if entry['highlight'] else 'strip-plain'
            strip.add_css_class(css_class)
        outer.append(strip)

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        content.set_hexpand(True)
        content.set_margin_start(10)
        content.set_margin_end(10)
        content.set_margin_top(8)
        content.set_margin_bottom(8)

        # Reference + module
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if entry.get('is_chapter_note'):
            ref_text = f'{entry["book"]} {entry["chapter"]} — Chapter Note'
        else:
            ref_text = f'{entry["book"]} {entry["chapter"]}:{entry["verse"]}'
        ref = Gtk.Label(label=ref_text, xalign=0, hexpand=True)
        ref.add_css_class('heading')
        top.append(ref)

        mod_lbl = Gtk.Label(label=entry['module'], xalign=1)
        mod_lbl.add_css_class('dim-label')
        top.append(mod_lbl)
        content.append(top)

        # Type badges
        if not entry.get('is_chapter_note'):
            badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if entry['highlight']:
                lbl = Gtk.Label(label='● Highlight', xalign=0)
                lbl.add_css_class('dim-label')
                badges.append(lbl)
            if entry['underline']:
                lbl = Gtk.Label(label='▁ Underline', xalign=0)
                lbl.add_css_class('dim-label')
                badges.append(lbl)
            if entry['note']:
                lbl = Gtk.Label(label='📝 Note', xalign=0)
                lbl.add_css_class('dim-label')
                badges.append(lbl)
            content.append(badges)

        # Note preview
        if entry['note']:
            note_lbl = Gtk.Label(label=entry['note'], xalign=0, wrap=True)
            note_lbl.set_lines(3)
            note_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(note_lbl)

        # Tags
        tags = entry.get('tags', [])
        if tags:
            tags_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            for t in tags:
                chip = Gtk.Label(label=f'#{t}', xalign=0)
                chip.add_css_class('dim-label')
                tags_box.append(chip)
            content.append(tags_box)

        outer.append(content)

        # Trash button
        del_btn = Gtk.Button(icon_name='user-trash-symbolic')
        del_btn.add_css_class('flat')
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_margin_end(6)
        del_btn.set_tooltip_text('Delete annotation')
        del_btn.connect('clicked', self._on_delete_entry, entry)
        outer.append(del_btn)

        row.set_child(outer)
        return row

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_delete_entry(self, _btn, entry):
        annotations.delete_annotation(
            entry['module'], entry['book'], entry['chapter'],
            None if entry.get('is_chapter_note') else entry['verse']
        )
        self._reload()
        if self._on_annotation_changed:
            self._on_annotation_changed()

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, '_entry'):
            e = row._entry
            self._on_navigate(e['module'], e['book'], e['chapter'], e['verse'] or 1)

    def _on_export(self, _btn):
        dialog = Gtk.FileChooserNative(
            title='Export Study Journal',
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.set_current_name('study_journal.txt')
        dialog.connect('response', self._on_export_response)
        dialog.show()

    def _on_export_response(self, dialog, response):
        if response != Gtk.ResponseType.ACCEPT:
            return
        gfile = dialog.get_file()
        path = gfile.get_path() if gfile else None
        if not path:
            # Non-local URI (gvfs / network share) — get_path() returns None.
            self._show_export_error('Please choose a location on this computer.')
            return
        lines = ['Study Journal', '=' * 40, '']
        for e in self._filtered_entries():
            if e.get('is_chapter_note'):
                lines.append(f'{e["book"]} {e["chapter"]} — Chapter Note  ({e["module"]})')
            else:
                lines.append(f'{e["book"]} {e["chapter"]}:{e["verse"]}  ({e["module"]})')
                types = []
                if e['highlight']:
                    types.append('Highlight')
                if e['underline']:
                    types.append('Underline')
                if types:
                    lines.append(f'  [{", ".join(types)}]')
            if e['note']:
                lines.append(f'  {e["note"]}')
            if e.get('tags'):
                lines.append(f'  Tags: {", ".join("#" + t for t in e["tags"])}')
            lines.append('')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
        except Exception as ex:
            self._show_export_error(f'Could not write to {path}:\n{ex}')

    def _show_export_error(self, msg):
        dlg = Adw.MessageDialog(transient_for=self, modal=True,
                                heading='Export failed', body=msg)
        dlg.add_response('ok', 'OK')
        dlg.present()
