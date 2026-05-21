import json
import os
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango
import sword_bridge

_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'search_history.json')
_HISTORY_MAX = 10


def _load_history():
    try:
        with open(_HISTORY_FILE, encoding='utf-8') as f:
            data = json.load(f)
        # Defensive: file could have been hand-edited to a non-list (dict, scalar).
        if not isinstance(data, list):
            return []
        # Filter out entries missing the required keys.
        return [e for e in data
                if isinstance(e, dict) and 'query' in e and 'module' in e]
    except Exception:
        return []


def _save_history(query, module):
    history = _load_history()
    entry = {'query': query, 'module': module}
    history = [e for e in history if e != entry]  # remove duplicate
    history.insert(0, entry)
    history = history[:_HISTORY_MAX]
    try:
        with open(_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False)
    except Exception:
        pass

SECTIONS = [
    ('Pentateuch',       ['Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy']),
    ('History',          ['Joshua', 'Judges', 'Ruth', '1 Samuel', '2 Samuel', '1 Kings',
                          '2 Kings', '1 Chronicles', '2 Chronicles', 'Ezra', 'Nehemiah', 'Esther']),
    ('Wisdom & Poetry',  ['Job', 'Psalms', 'Proverbs', 'Ecclesiastes', 'Song of Solomon']),
    ('Major Prophets',   ['Isaiah', 'Jeremiah', 'Lamentations', 'Ezekiel', 'Daniel']),
    ('Minor Prophets',   ['Hosea', 'Joel', 'Amos', 'Obadiah', 'Jonah', 'Micah',
                          'Nahum', 'Habakkuk', 'Zephaniah', 'Haggai', 'Zechariah', 'Malachi']),
    ('Gospels & Acts',   ['Matthew', 'Mark', 'Luke', 'John', 'Acts']),
    ('Pauline Epistles', ['Romans', '1 Corinthians', '2 Corinthians', 'Galatians',
                          'Ephesians', 'Philippians', 'Colossians', '1 Thessalonians',
                          '2 Thessalonians', '1 Timothy', '2 Timothy', 'Titus', 'Philemon']),
    ('General Epistles', ['Hebrews', 'James', '1 Peter', '2 Peter', '1 John',
                          '2 John', '3 John', 'Jude', 'Revelation']),
]

_BOOK_TO_SECTION = {book: sec for sec, books in SECTIONS for book in books}


def _searchable_modules():
    """Modules suitable for full-text search — Bibles and commentaries
    (both are book/chapter/verse-keyed, which Whoosh indexing assumes).
    Excludes devotionals (date-keyed), lexicons / generic books (no verse
    key space), and internal-use morphology modules (browsable via the
    lexicon panel instead)."""
    keep = []
    for name in sword_bridge.module_names():
        if sword_bridge.is_internal_use(name):
            continue
        t = sword_bridge.module_type(name)
        if t in ('Biblical Texts', 'Commentaries'):
            keep.append(name)
    return keep

_CSS = """
.search-panel {
    background-color: @window_bg_color;
    border-top: 1px solid alpha(@borders, 0.5);
    border-left: 1px solid alpha(@borders, 0.5);
    /* Bigger radius + diagonal shadow — mirror of .menu-panel's
       shape but with the X offset reversed (panel slides in from
       right, so the shadow drops to the LEFT + slightly down). */
    border-top-left-radius: 20px;
    box-shadow: -5px 3px 24px -4px alpha(black, 0.25),
                -2px 1px 4px alpha(black, 0.12);
}
.bar-fill       { background-color: #4a9fd4; border-radius: 3px; min-height: 10px; }
.bar-fill-sub   { background-color: #6dbf7e; border-radius: 3px; min-height: 10px; }
.bar-label-active { color: @accent_color; font-weight: bold; }
.result-ref     { font-weight: bold; }
"""


class SearchPanel(Gtk.Box):
    def __init__(self, on_result_clicked, on_close):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_result_clicked = on_result_clicked
        self._on_close = on_close
        self._results = []
        self._filter_book = None
        self._expanded_section = None
        self._populate_gen = 0
        # F3 / Shift+F3 step-through pointer into `_results`. Reset to -1
        # whenever a fresh search starts so the first F3 lands on result 0.
        self._current_idx = -1

        self.set_size_request(420, -1)
        self.set_vexpand(True)
        self.add_css_class('search-panel')

        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._build_ui()

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_start(12)
        header.set_margin_end(8)
        header.set_margin_top(10)
        header.set_margin_bottom(6)

        title = Gtk.Label(label='Search', xalign=0, hexpand=True)
        title.add_css_class('title-3')
        header.append(title)

        close_btn = Gtk.Button(icon_name='window-close-symbolic')
        close_btn.add_css_class('flat')
        close_btn.set_tooltip_text('Close search (Esc)')
        close_btn.connect('clicked', lambda _: self._on_close())
        header.append(close_btn)

        self.append(header)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Module + query ────────────────────────────────────────────────────
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        controls.set_margin_start(12)
        controls.set_margin_end(12)
        controls.set_margin_top(8)
        controls.set_margin_bottom(6)

        names = _searchable_modules()
        self._module_drop = Gtk.DropDown(model=Gtk.StringList.new(names), hexpand=True)
        controls.append(self._module_drop)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._entry = Gtk.Entry(hexpand=True, placeholder_text='Search…')
        self._entry.connect('activate', self._on_search)
        entry_row.append(self._entry)
        self._case_btn = Gtk.ToggleButton(label='Aa')
        self._case_btn.set_tooltip_text('Match case')
        self._case_btn.add_css_class('flat')
        self._case_btn.connect('toggled', self._on_case_toggled)
        entry_row.append(self._case_btn)
        search_btn = Gtk.Button(icon_name='system-search-symbolic')
        search_btn.set_tooltip_text('Search')
        search_btn.connect('clicked', self._on_search)
        entry_row.append(search_btn)
        controls.append(entry_row)

        self.append(controls)

        # ── Count + spinner ───────────────────────────────────────────────────
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_row.set_margin_start(12)
        status_row.set_margin_end(12)
        status_row.set_margin_bottom(4)

        self._count_label = Gtk.Label(label='', xalign=0, hexpand=True)
        self._count_label.add_css_class('dim-label')
        status_row.append(self._count_label)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        status_row.append(self._spinner)

        self.append(status_row)

        # ── Chart area (scrollable, capped height) ────────────────────────────
        self._chart_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self._chart_box.set_margin_start(8)
        self._chart_box.set_margin_end(8)
        self._chart_box.set_margin_top(4)
        self._chart_box.set_margin_bottom(4)

        chart_scroll = Gtk.ScrolledWindow()
        chart_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chart_scroll.set_propagate_natural_height(True)
        chart_scroll.set_max_content_height(200)
        chart_scroll.set_child(self._chart_box)
        self.append(chart_scroll)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Results list ──────────────────────────────────────────────────────
        self._results_scroll = Gtk.ScrolledWindow(vexpand=True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_start(8)
        outer.set_margin_end(8)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)

        self._results_list = Gtk.ListBox()
        self._results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._results_list.add_css_class('boxed-list')
        self._results_list.connect('row-activated', self._on_row_activated)
        outer.append(self._results_list)

        self._results_scroll.set_child(outer)
        self.append(self._results_scroll)

    # ── Public ────────────────────────────────────────────────────────────────

    def prepare_for_show(self, module_name):
        self.set_module(module_name)
        if not self._results:
            self._show_history()

    def set_module(self, module_name):
        names = _searchable_modules()
        self._module_drop.set_model(Gtk.StringList.new(names))
        if module_name in names:
            self._module_drop.set_selected(names.index(module_name))

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_indexing_start(self):
        GLib.idle_add(self._update_indexing_status, "Building search index…", True)

    def _on_indexing_progress(self, book_idx, total, book_name):
        GLib.idle_add(self._update_indexing_status,
                      f'Building search index… {book_name} ({book_idx}/{total})',
                      True)

    def _on_indexing_done(self):
        GLib.idle_add(self._update_indexing_status, "", False)

    def _update_indexing_status(self, text, show_spinner):
        self._count_label.set_text(text)
        if show_spinner:
            self._spinner.set_visible(True)
            self._spinner.start()
        else:
            self._spinner.stop()
            self._spinner.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _current_module(self):
        names = _searchable_modules()
        idx = self._module_drop.get_selected()
        return names[idx] if names and idx < len(names) else None

    def _on_search(self, *_):
        query = self._entry.get_text().strip()
        if not query:
            return
        module = self._current_module()
        if not module:
            return

        self._results = []
        self._current_idx = -1
        self._filter_book = None
        self._expanded_section = None
        self._clear_chart()
        self._clear_results()
        self._count_label.set_text('Searching…')
        self._spinner.set_visible(True)
        self._spinner.start()

        case = self._case_btn.get_active()

        def run():
            results = sword_bridge.search_module(
                module,
                query,
                on_indexing_start=self._on_indexing_start,
                on_indexing_progress=self._on_indexing_progress,
                on_indexing_done=self._on_indexing_done,
                case_sensitive=case,
            )
            _save_history(query, module)
            GLib.idle_add(self._on_search_done, results)

        threading.Thread(target=run, daemon=True).start()

    def _on_case_toggled(self, _btn):
        # Re-run the current query so the result list reflects the new
        # case mode without the user having to hit Enter again.
        if self._entry.get_text().strip():
            self._on_search()

    def _on_search_done(self, results):
        self._spinner.stop()
        self._spinner.set_visible(False)

        truncated_msg = None
        if results and results[-1][0] == '':
            truncated_msg = results[-1][3]
            results = results[:-1]

        self._results = results
        self._current_idx = -1
        total = len(results)
        if truncated_msg:
            self._count_label.set_text(truncated_msg)
        else:
            self._count_label.set_text(f'{total} verse{"s" if total != 1 else ""} found')

        self._rebuild_chart()
        self._populate_results(self._results)
        if not self._results and not truncated_msg:
            self._results_list.append(self._make_empty_row(
                'No matches',
                'Try a different word or phrase, or pick another module'))
        return GLib.SOURCE_REMOVE

    def _make_empty_row(self, title, description):
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        # Adw.StatusPage's `.compact` class isn't reliably honored across
        # distro themes (Zorin's themed Adwaita ignored it), so we
        # hand-roll the compact empty state — explicit 48px icon, manual
        # centering. See study_journal._compact_empty_state for the
        # canonical version.
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_start(16)
        body.set_margin_end(16)
        body.set_margin_top(24)
        body.set_margin_bottom(24)
        body.set_halign(Gtk.Align.CENTER)
        body.set_valign(Gtk.Align.CENTER)

        image = Gtk.Image.new_from_icon_name('system-search-symbolic')
        image.set_pixel_size(48)
        image.set_halign(Gtk.Align.CENTER)
        image.add_css_class('dim-label')
        body.append(image)

        title_lbl = Gtk.Label(label=title)
        title_lbl.add_css_class('heading')
        title_lbl.set_wrap(True)
        title_lbl.set_justify(Gtk.Justification.CENTER)
        title_lbl.set_halign(Gtk.Align.CENTER)
        body.append(title_lbl)

        desc_lbl = Gtk.Label(label=description)
        desc_lbl.add_css_class('dim-label')
        desc_lbl.set_wrap(True)
        desc_lbl.set_justify(Gtk.Justification.CENTER)
        desc_lbl.set_halign(Gtk.Align.CENTER)
        desc_lbl.set_max_width_chars(40)
        body.append(desc_lbl)

        row.set_child(body)
        return row

    def _show_history(self):
        history = _load_history()
        if not history:
            self._count_label.set_text('')
            self._clear_results()
            self._results_list.append(self._make_empty_row(
                'Search this module',
                "Type a word or phrase above. The chart shows where matches "
                "cluster across the Bible"))
            return
        self._count_label.set_text('Recent searches')
        self._clear_results()
        for entry in history:
            row = Gtk.ListBoxRow()
            row._history = entry

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_start(10)
            box.set_margin_end(10)
            box.set_margin_top(8)
            box.set_margin_bottom(8)

            icon = Gtk.Image.new_from_icon_name('document-open-recent-symbolic')
            icon.add_css_class('dim-label')
            box.append(icon)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
            query_lbl = Gtk.Label(label=entry['query'], xalign=0)
            query_lbl.add_css_class('result-ref')
            mod_lbl = Gtk.Label(label=entry['module'], xalign=0)
            mod_lbl.add_css_class('dim-label')
            text_box.append(query_lbl)
            text_box.append(mod_lbl)
            box.append(text_box)

            row.set_child(box)
            self._results_list.append(row)

    # ── Chart ─────────────────────────────────────────────────────────────────

    def _section_counts(self):
        counts = {sec: 0 for sec, _ in SECTIONS}
        for book, *_ in self._results:
            sec = _BOOK_TO_SECTION.get(book)
            if sec:
                counts[sec] += 1
        return counts

    def _book_counts(self, books):
        counts = {b: 0 for b in books}
        for book, *_ in self._results:
            if book in counts:
                counts[book] += 1
        return counts

    def _clear_chart(self):
        child = self._chart_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._chart_box.remove(child)
            child = nxt

    def _rebuild_chart(self):
        self._clear_chart()
        sec_counts = self._section_counts()
        max_val = max(sec_counts.values(), default=1) or 1

        for sec_name, sec_books in SECTIONS:
            count = sec_counts.get(sec_name, 0)
            expanded = (sec_name == self._expanded_section)
            btn = self._bar_button(sec_name, count, max_val, sub=False, active=expanded)
            btn.connect('clicked', self._on_section_clicked, sec_name, sec_books)
            self._chart_box.append(btn)

            if expanded:
                sub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                sub_box.set_margin_start(16)
                book_counts = self._book_counts(sec_books)
                sub_max = max(book_counts.values(), default=1) or 1
                for book in sec_books:
                    bc = book_counts[book]
                    if bc == 0:
                        continue
                    bb = self._bar_button(book, bc, sub_max, sub=True,
                                          active=(book == self._filter_book))
                    bb.connect('clicked', self._on_book_clicked, book)
                    sub_box.append(bb)
                self._chart_box.append(sub_box)

    def _bar_button(self, label_text, count, max_val, sub=False, active=False):
        btn = Gtk.Button()
        btn.add_css_class('flat')

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(4)
        row.set_margin_end(4)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        lbl = Gtk.Label(label=label_text, xalign=0)
        lbl.set_size_request(130 if not sub else 110, -1)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        if active:
            lbl.add_css_class('bar-label-active')
        row.append(lbl)

        bar_container = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER)
        if count > 0:
            bar = Gtk.Box()
            bar.add_css_class('bar-fill' if not sub else 'bar-fill-sub')
            bar.set_size_request(max(4, int(110 * count / max_val)), 10)
            bar_container.append(bar)
        row.append(bar_container)

        count_lbl = Gtk.Label(label=str(count) if count else '—', xalign=1)
        count_lbl.add_css_class('dim-label')
        count_lbl.set_size_request(28, -1)
        row.append(count_lbl)

        btn.set_child(row)
        return btn

    def _on_section_clicked(self, _btn, sec_name, sec_books):
        if self._expanded_section == sec_name:
            self._expanded_section = None
            self._filter_book = None
        else:
            self._expanded_section = sec_name
            self._filter_book = None
        self._rebuild_chart()
        self._populate_results(self._filtered_results())

    def _on_book_clicked(self, _btn, book):
        self._filter_book = None if self._filter_book == book else book
        self._rebuild_chart()
        self._populate_results(self._filtered_results())

    def _filtered_results(self):
        if self._filter_book:
            return [r for r in self._results if r[0] == self._filter_book]
        if self._expanded_section:
            sec_books = set(next((b for s, b in SECTIONS if s == self._expanded_section), []))
            return [r for r in self._results if r[0] in sec_books]
        return self._results

    # ── Results ───────────────────────────────────────────────────────────────

    def _clear_results(self):
        self._populate_gen += 1  # cancel any in-progress batch
        child = self._results_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results_list.remove(child)
            child = nxt

    def _make_result_row(self, book, ch, v, text):
        row = Gtk.ListBoxRow()
        row._nav = (book, ch, v)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        ref = Gtk.Label(label=f'{book} {ch}:{v}', xalign=0)
        ref.add_css_class('result-ref')
        snippet = text[:200] + ('…' if len(text) > 200 else '')
        body = Gtk.Label(label=snippet, xalign=0, wrap=True)
        body.set_lines(2)
        body.set_ellipsize(Pango.EllipsizeMode.END)
        body.add_css_class('dim-label')
        box.append(ref)
        box.append(body)
        row.set_child(box)
        return row

    # Cap the number of result rows rendered as widgets. The Whoosh
    # search itself returns up to MAX_SEARCH_RESULTS (5000) which F3
    # step-through can walk; the visible list just bloats GtkListBox and
    # drags later UI interactions. 500 is plenty for visual browsing —
    # users narrow down via the book filter or a more specific query.
    _DISPLAY_CAP = 500

    def _populate_results(self, results):
        self._clear_results()
        gen = self._populate_gen
        total = len(results)
        pending = list(results[:self._DISPLAY_CAP])
        display_truncated = total > self._DISPLAY_CAP

        def add_batch():
            if self._populate_gen != gen:
                return GLib.SOURCE_REMOVE
            batch = pending[:100]
            del pending[:100]
            for book, ch, v, text in batch:
                self._results_list.append(self._make_result_row(book, ch, v, text))
            if pending and self._populate_gen == gen:
                GLib.idle_add(add_batch)
            elif display_truncated and self._populate_gen == gen:
                # Final batch done — append a footer row hinting that
                # the visible list is capped. F3 still steps through the
                # full underlying _results so the user isn't cut off
                # from the truncated portion.
                hint = self._make_empty_row(
                    f'Showing first {self._DISPLAY_CAP} of {total}',
                    'F3 walks the full list; narrow the query or use a book filter for fewer matches.')
                self._results_list.append(hint)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(add_batch)

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, '_nav'):
            book, ch, v = row._nav
            self._on_result_clicked(book, ch, v)
            self._on_close()
        elif hasattr(row, '_history'):
            entry = row._history
            self.set_module(entry['module'])
            self._entry.set_text(entry['query'])
            self._on_search()

    # ── F3 / Shift+F3 step-through ───────────────────────────────────────
    def step_result(self, prev=False):
        """Move to the next (or previous) result and navigate to it.
        Keeps the panel open so the user can keep stepping. Wraps around
        the result list. Returns True if a navigation happened."""
        if not self._results:
            return False
        n = len(self._results)
        if prev:
            self._current_idx = (self._current_idx - 1) % n
        else:
            self._current_idx = (self._current_idx + 1) % n
        book, ch, v, _text = self._results[self._current_idx]
        self._on_result_clicked(book, ch, v)
        # Update the count label so the user knows where they are
        self._count_label.set_text(
            f'Result {self._current_idx + 1} of {n}')
        return True
