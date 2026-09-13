import logging
import os
import re
from datetime import date, datetime, timedelta

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, Gtk, Adw, GLib, Pango
from a11y import set_accessible_label
from i18n import current_language, format_date
from gtk_utils import Autosave, clear_children
import annotation_dialogs
import annotation_editors
from annotation_editors import _HL_NAMES
import annotations
import ebible_bridge
import journal
import journal_import
import journal_markup
import motion
import passage_export
import passage_print
import sermons
import sword_bridge
from empty_state import compact_empty_state

_log = logging.getLogger('scriptura.annotations_window')

_BOOK_ORDER = {book: i for i, book in enumerate(sword_bridge._ALL_BOOKS)}

# Strip / swatch / note-card / tag-chip CSS rules are defined in data/style.css
# (the `journal-*` class names predate the rename) and loaded once at app
# startup by styles.load_app_css().

_HIGHLIGHT_CLASS = {
    '#ffff00': 'strip-yellow',
    '#90ee90': 'strip-green',
    '#add8e6': 'strip-blue',
    '#ffa500': 'strip-orange',
}


# Per-hue class for the small list-row badge dot (coloured to its highlight;
# the name beside it stays the colourblind-safe cue).
_HL_DOT_CLASS = {
    '#ffff00': 'journal-dot-yellow',
    '#90ee90': 'journal-dot-green',
    '#add8e6': 'journal-dot-blue',
    '#ffa500': 'journal-dot-orange',
}


# Cap the synchronous list build so a large store doesn't rebuild every rich
# row on each filter keystroke; a footer pulls the next slice on demand.
_RENDER_CAP = 200


def N_(message):
    """No-op gettext marker for strings in module-level data; translated at
    display time via _()."""
    return message


# Highlight-color display names (shown as swatch tooltips), translated at
# display via _(). Replaces deriving the name from the CSS class.

#: The window's pages, in order. A sermon manuscript system is planned and
#: will be a third line here, which is the reason this is a table and the
#: reason the list is filtered by mode rather than split into two widgets:
#: the render cap, the Show-more footer, the preserved selection, the tag
#: manager and the autosave are all one implementation serving every page.
_MODES = [('marks', N_('Annotations'), 'scriptura-annotations-symbolic'),
          ('journal', N_('Journal'), 'scriptura-journal-symbolic'),
          ('sermons', N_('Sermons'), 'scriptura-sermons-symbolic')]

#: The type dropdown asks a different question on each page. On the marks
#: page it is the kind of mark; on the journal page an entry has no kinds,
#: so it asks the one distinction entries do have; on the sermons page it
#: asks the one a manuscript has, which is whether it has been preached.
_TYPE_VALUES = {
    'marks': [N_('All types'), N_('Notes'), N_('Highlights'),
              N_('Underlines')],
    'journal': [N_('All entries'), N_('With a passage'),
                N_('Without a passage')],
    'sermons': [N_('All sermons'), N_('Preached'), N_('Not yet preached')],
}

#: Which store each page reads. `marks` is not here: it is the annotations
#: store and is assembled verse by verse rather than listed.
_WRITING_KIND = {'journal': 'entry', 'sermons': 'sermon'}


def _switcher_face(label, icon):
    """One segment of the page switcher: its glyph and its name.

    A toggle's own `icon-name` is used only when it has no label, so an
    icon-and-word segment has to be built as a child.
    """
    face = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    face.set_halign(Gtk.Align.CENTER)
    face.append(Gtk.Image.new_from_icon_name(icon))
    face.append(Gtk.Label(label=label))
    return face


#: The translation a quoted verse is set in, per interface language; first
#: one installed wins. A mark belongs to a place in scripture rather than to
#: a module, so the words it is quoted with follow the language the reader
#: has the app in — not whichever pane happens to be open, which quoted a
#: Russian reader's note back at them in the English text beside it.
#:
#: Each list opens with what that language's welcome bundle installs and
#: opens on, so a reader who took the bundle is quoted the text they were
#: given: BSB, NBLA, and the Russian Open Bible (welcome.py opens the Russian
#: tiers on it because CrossWire's other modern Russian editions are the
#: Muslim-idiom CARS texts). The rest are what a reader who declined the
#: bundle is likely to have instead, ending with the eBible import of the
#: same language. None of them installed falls back to the reading module.
_QUOTE_MODULES = {
    'en': ('BSB', 'ASV', 'KJV', 'eBible: engwebp'),
    'es': ('NBLA', 'LBLA', 'SpaRV1909',
           'eBible: spaRV1909', 'eBible: spaonbv'),
    'ru': ('RusOpenBible', 'RusSynodalLIO', 'RusSynodal', 'eBible: russyn'),
}


def quote_module():
    """The module the detail pane quotes from, or None to use the reading one.

    Costs one `module_names()` and one `installed_ids()` per detail selection,
    and only until the first hit — which for a reader who took their welcome
    bundle is the first name in the list.
    """
    prefs = _QUOTE_MODULES.get(current_language(), ())
    if not prefs:
        return None
    sword = ebible = None
    for name in prefs:
        if name.startswith(ebible_bridge.PREFIX):
            if ebible is None:
                ebible = ebible_bridge.installed_ids()
            if name[len(ebible_bridge.PREFIX):] in ebible:
                return name
        else:
            if sword is None:
                sword = set(sword_bridge.module_names())
            if name in sword:
                return name
    return None


def verse_quote(module, book, chapter, verse):
    """The verse's own words out of one module, or '' if it cannot render it.

    `verse` is app space, as everything leaving the store is; the module is
    asked for its own number first, or a Synodal psalter quotes the line
    above the one the note is on.
    """
    try:
        target = annotations.module_verse(module, book, chapter, verse)
        return passage_export.verse_text(module, book, chapter, [target])
    except Exception:
        _log.exception('verse text for the annotation detail failed')
        return ''


def _all_entries():
    data = annotations._load()
    entries = []
    for key, verses in data.items():
        parts = key.split('/')
        if len(parts) != 2:
            continue
        book, chapter_str = parts
        try:
            chapter = int(chapter_str)
        except ValueError:
            continue
        entries.extend(_marks_in_chapter(book, chapter, verses))
    entries.extend(_journal_rows())
    entries.extend(_sermon_rows())
    return _in_reading_order(entries)


def marks_on(book, chapter):
    """Every mark and chapter note on one chapter, in verse order.

    The whole chapter, not only the verses a sermon is anchored to: a
    manuscript on Matthew 13:1-9 will happily use the note left on 13:23,
    and a door that hid it would be answering a narrower question than the
    one the reader asked.
    """
    verses = annotations._load().get(annotations._chapter_key(book, chapter))
    if not verses:
        return []
    rows = _marks_in_chapter(book, chapter, verses)
    # Chapter notes first — what is true of the whole passage stands above
    # what is true of one line of it — then by verse.
    return sorted(rows, key=lambda r: (not r['is_chapter_note'],
                                       r['app_verse'] or 0))


def _marks_in_chapter(book, chapter, verses):
    """The marks stored under one chapter key, as list rows.

    Pulled out of `_all_entries` when the sermon editor needed the same rows
    for one chapter: the shape a mark takes in this window is decided in one
    place, or the two readers of the store disagree about what a mark is.
    """
    entries = []
    for verse_str, anno in verses.items():
        if verse_str == 'chapter_note':
            continue
        # `verse_str` is the store key, which for a line two versifications
        # print differently carries an OSIS sub-verse letter (`1!b`). The
        # key is what writes and deletes address; the app verse under it is
        # what a reference, a sort and a jump speak.
        app_verse = annotations._base_verse(verse_str)
        if app_verse is None:
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
            'kind': 'mark',
            # `verse` is app space, which is what the store now holds and
            # what every reference, sort and jump below speaks. Writes go
            # back through annotations.* with module=None — no lens, the
            # number is already the one the store wants.
            'book': book, 'chapter': chapter,
            'verse': verse_str, 'app_verse': app_verse,
            'highlight': h, 'underline': u, 'note': n,
            'tags': tgs, 'is_chapter_note': False,
            'created': anno.get('created'),
            'modified': anno.get('modified'),
        })
    chapter_note = verses.get('chapter_note')
    if chapter_note:
        if isinstance(chapter_note, str):
            cn_text, cn_tags, cn_mod = chapter_note, [], None
        elif isinstance(chapter_note, dict):
            cn_text = chapter_note.get('note', '')
            cn_tags = chapter_note.get('tags', [])
            cn_mod = chapter_note.get('modified')
        else:
            cn_text, cn_tags, cn_mod = '', [], None
        if cn_text.strip() or cn_tags:
            entries.append({
                'kind': 'mark',
                'book': book, 'chapter': chapter,
                'verse': None, 'app_verse': None,
                'highlight': None, 'underline': False,
                'note': cn_text, 'tags': cn_tags,
                'is_chapter_note': True,
                'created': (chapter_note.get('created')
                            if isinstance(chapter_note, dict) else None),
                'modified': cn_mod,
            })
    return entries


def _journal_rows():
    """Journal entries in the same flat shape the marks use.

    An entry appears ONCE, at its first anchor, with the rest carried in
    `anchors` for the detail pane. Repeating the row under each anchor would
    make the count label lie about how much was written and would break the
    render cap's arithmetic.

    `book` is None for a verse-less entry — a sermon, a conversation, a
    season — which is legal, and is what sorts it into the No-passage group.
    """
    rows = []
    for entry in journal.all_entries():
        first = entry['anchors'][0] if entry['anchors'] else None
        verses = first['verses'] if first else []
        rows.append({
            'kind': 'entry',
            'id': entry['id'],
            'book': first['book'] if first else None,
            'chapter': first['chapter'] if first else None,
            'app_verse': verses[0] if verses else None,
            'verse': None,
            # A mark's vocabulary, left empty: an entry has no hue, no rule
            # and no single verse, and the row builder branches on `kind`
            # rather than asking these.
            'highlight': None, 'underline': False, 'note': None,
            'is_chapter_note': False,
            'title': entry['title'], 'body': entry['body'],
            'date': entry['date'], 'anchors': entry['anchors'],
            'plan': entry['plan'], 'collect': entry['collect'],
            'tags': entry['tags'],
            'created': entry['created'], 'modified': entry['modified'],
        })
    return rows


def _sermon_rows():
    """Sermons in the same flat shape the marks and entries use.

    A sermon appears ONCE, at its first anchor, the rest carried in
    `anchors` — the same rule an entry follows, and for the same reason: a
    repeated row would make the count lie about how much was written.

    There is no `date`. The date column shows the last day it was preached,
    and a sermon that has not been preached shows nothing there rather than
    a day it never had.
    """
    rows = []
    for sermon in sermons.all_sermons():
        first = sermon['anchors'][0] if sermon['anchors'] else None
        verses = first['verses'] if first else []
        rows.append({
            'kind': 'sermon',
            'id': sermon['id'],
            'book': first['book'] if first else None,
            'chapter': first['chapter'] if first else None,
            'app_verse': verses[0] if verses else None,
            'verse': None,
            'highlight': None, 'underline': False, 'note': None,
            'is_chapter_note': False,
            'title': sermon['title'], 'body': sermon['body'],
            'idea': sermon['idea'], 'series': sermon['series'],
            'preached': sermon['preached'], 'anchors': sermon['anchors'],
            'collect': sermon['collect'], 'tags': sermon['tags'],
            'created': sermon['created'], 'modified': sermon['modified'],
        })
    return rows


def _is_writing(entry):
    """Whether this row is a page of the reader's own writing (an entry or a
    sermon) rather than a mark in a margin."""
    return entry.get('kind') in ('entry', 'sermon')


def _series_name(entry):
    """The series a sermon belongs to, or '' — what the list groups by."""
    series = entry.get('series') or {}
    return series.get('name') or ''


def _series_part(entry):
    """Its number in that series. Unnumbered sermons sort after numbered
    ones rather than before them, which is where a reader looks for the one
    they have not placed yet."""
    series = entry.get('series') or {}
    part = series.get('part')
    return part if isinstance(part, int) else 10 ** 6


def _in_series_order(entries):
    """Series first, each in its own order; then everything unfiled.

    The canon leads everywhere else in this window, and it leads here too —
    but only within the group a sermon belongs to. A series IS the order the
    sermons were preached in, and sorting a series by the canon would put
    part 4 above part 2 the moment a preacher works backwards through a
    book, which is ordinary.
    """
    order = {id(e): i for i, e in enumerate(entries)}
    filed = [e for e in entries if _series_name(e)]
    unfiled = [e for e in entries if not _series_name(e)]
    filed.sort(key=lambda e: (_series_name(e).casefold(), _series_part(e),
                              order[id(e)]))
    unfiled.sort(key=lambda e: (
        e['book'] is None,
        _BOOK_ORDER.get(e['book'], 999) if e['book'] else 0,
        e['chapter'] or 0, e['app_verse'] or 0))
    return filed + unfiled


def _in_reading_order(entries):
    """The canon leads; the ones with nothing to lead with come last.

    Two passes rather than one clever key. Anchored rows sort by the canon,
    as everything in this app does. Verse-less entries have no place in it,
    so they group at the end by date, newest first — the only spot in the
    window where the calendar leads, and it leads there because there is
    nothing else.
    """
    # The position each row arrived in, which for the journal is store
    # order — the last written is the last here.
    order = {id(e): i for i, e in enumerate(entries)}
    anchored = [e for e in entries if e['book'] is not None]
    unanchored = [e for e in entries if e['book'] is None]
    anchored.sort(key=lambda e: (
        _BOOK_ORDER.get(e['book'], 999), e['chapter'] or 0,
        e['app_verse'] or 0
    ))
    # By the day it is about, then by when it was written, then by where it
    # sits in the store. Sorting on the date alone left a stable sort holding
    # same-day entries in store order, so one written a moment ago sat UNDER
    # one written this morning in a group whose whole rule is newest first —
    # and `created` cannot break that tie on its own, being seconds-precise.
    unanchored.sort(key=lambda e: (e.get('date') or '', e.get('created') or '',
                                   order[id(e)]), reverse=True)
    return anchored + unanchored


def _entry_key(e):
    if _is_writing(e):
        return (e['kind'], e['id'])
    return (e['book'], e['chapter'],
            None if e.get('is_chapter_note') else e['verse'])


def _entry_date(e):
    """The day a row is filed under for the date filter.

    An entry's `date` is the day it is *about* and the reader can correct it;
    a mark has no such field, and its `created` IS its date. One control over
    two fields, because a reader looking for something written around Lent
    does not care which kind of thing it was. A mark from before the store
    recorded dates has neither, and falls out of any range — an undated thing
    cannot be placed in one.
    """
    if e.get('kind') == 'entry':
        return e.get('date') or ''
    if e.get('kind') == 'sermon':
        # The day it was last preached, and the day it was begun until then.
        # A sermon written last Lent and never preached is still findable in
        # "this year", which is what the filter is for.
        preached = e.get('preached') or []
        if preached:
            return preached[-1]
    stamp = e.get('created') or e.get('modified') or ''
    return stamp[:10]


def _preached_label(entry):
    """The day a sermon was last preached, or '' when it never was."""
    preached = entry.get('preached') or []
    if not preached:
        return ''
    try:
        return format_date(date.fromisoformat(preached[-1]))
    except ValueError:
        return ''


def _series_part_label(entry):
    """"Part 3" for a numbered sermon in a series, else ''. The series name
    itself is the group heading, so the row says only which one this is."""
    part = (entry.get('series') or {}).get('part')
    if not isinstance(part, int):
        return ''
    return _('Part {n}').format(n=part)


def _edited_label(entry):
    """"Edited <date>" for an entry that carries a timestamp, else ''.

    Set the way the Today page sets a date, not with a numeric format: the
    order is the translator's, and Spanish and Russian put the day first.
    Marks made before the store recorded dates simply have none.
    """
    stamp = entry.get('modified') or entry.get('created')
    if not isinstance(stamp, str) or not stamp:
        return ''
    try:
        when = datetime.fromisoformat(stamp).date()
    except ValueError:
        return ''
    return _('Edited {date}').format(date=format_date(when))


#: The spellings, and the language they were built for. ONE dict object per
#: language, handed back unchanged — journal_markup caches its compiled
#: matcher on this object's identity, so returning a fresh copy each call
#: would miss that cache every time.
_REF_NAMES: dict[str, str] = {}
_REF_LANG: str | None = None


def reference_names():
    """Every spelling a reference in prose may wear → its English book.

    Built from what the repo already has: the localized full name for the
    interface language (`book_label`, i.e. window.BOOKS through gettext),
    the canonical English name, and the SBL abbreviation. Rebuilt when the
    language changes, because `book_label` answers differently then.

    Localized abbreviations — "Jn", «Ин.» — come from SWORD's own locale
    files (`sword_bridge.book_abbreviations`), which ship a curated table per
    language. They were left out at first because no such table existed
    anywhere in the repo and inventing one would have put wrong
    abbreviations into two languages; it is a curation job, and SWORD had
    already done it. A language with no locale file simply keeps the full
    names, which is what the parser had before.
    """
    global _REF_NAMES, _REF_LANG
    lang = current_language()
    if _REF_LANG == lang:
        return _REF_NAMES
    names: dict[str, str] = {}
    for book in sword_bridge._ALL_BOOKS + list(sword_bridge.DEUTEROCANON):
        for spelling in (book, book_label(book),
                         passage_export.abbreviate(book)):
            if spelling:
                names[spelling] = book
    # After the full names, so a curated abbreviation never displaces a
    # spelling the app itself uses, and only for books this app knows.
    for abbrev, book in sword_bridge.book_abbreviations(lang).items():
        names.setdefault(abbrev, book)
    _REF_NAMES, _REF_LANG = names, lang
    return names


def _anchor_label(entry):
    """The reference on an entry's row: its first anchor, and how many more.

    The rest are chips in the detail pane. A verse-less entry has none and
    gets no line at all — the pane does not explain their absence either.
    """
    anchors = entry.get('anchors') or []
    if not anchors:
        return ''
    first = anchors[0]
    ref = f'{book_label(first["book"])} {first["chapter"]}'
    verses = first.get('verses') or []
    if verses:
        ref = f'{ref}:{verses[0]}'
        if len(verses) > 1:
            ref = f'{ref}–{verses[-1]}'
    extra = len(anchors) - 1
    if extra:
        ref = _('{ref} +{n} more').format(ref=ref, n=extra)
    return ref


def _entry_day_label(entry):
    """An entry's own date, set the translator's way and with no verb on it.

    A mark's caption says "Edited <date>" because that is when it was
    touched. An entry's date is the day it is *about*, so it stands bare —
    same place, same dim caption, one word's difference, which is how the
    distinction gets learned without being explained.
    """
    raw = entry.get('date') or ''
    try:
        return format_date(date.fromisoformat(raw))
    except ValueError:
        return ''


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

        # One vocabulary across all three stores. Two tag namespaces in one
        # window is the second organizing axis arriving by the back door.
        counts = dict(annotations.get_tag_counts())
        for tag, n in sermons.tag_counts().items():
            counts[tag] = counts.get(tag, 0) + n
        for tag, n in journal.tag_counts().items():
            counts[tag] = counts.get(tag, 0) + n
        if not counts:
            empty = compact_empty_state(
                icon_name='scriptura-view-list-bullet-symbolic',
                title=_('No tags yet'),
                description=_('Tag an annotation or a journal entry to see it here.'),
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
        # Not "{n} annotations": the count spans marks AND journal entries
        # now that tags are one vocabulary, so it counts uses of the tag
        # rather than things of one kind.
        row.set_subtitle(ngettext(
            'Used {n} time', 'Used {n} times', count).format(n=count))

        rename_btn = Gtk.Button(icon_name='scriptura-document-edit-symbolic')
        rename_btn.add_css_class('flat')
        rename_btn.set_valign(Gtk.Align.CENTER)
        rename_btn.set_tooltip_text(_('Rename or merge into another tag'))
        set_accessible_label(rename_btn, _('Rename or merge into another tag'))
        rename_btn.connect('clicked', self._on_rename_tag, tag)
        row.add_suffix(rename_btn)

        del_btn = Gtk.Button(icon_name='scriptura-user-trash-symbolic')
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
                    journal.rename_tag(tag, new)
                    sermons.rename_tag(tag, new)
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
                journal.delete_tag(tag)
                sermons.delete_tag(tag)
                self._populate_tags()
                if self._on_changed:
                    self._on_changed()
            d.close()

        dlg.connect('response', on_response)
        dlg.present(self)


class AnnotationsWindow(Adw.Window):
    def __init__(self, on_navigate, on_annotation_changed=None,
                 reading_module=None, new_entry=None, new_sermon=None,
                 select=None, **kwargs):
        super().__init__(**kwargs)
        self._on_navigate = on_navigate
        self._on_annotation_changed = on_annotation_changed
        # A callable returning the module the reader is in, so the detail pane
        # can quote the verse. Marks no longer belong to a module, so the
        # window has to be told which one to read the words out of.
        self._reading_module = reading_module
        self._entries = []
        self._filtered = []
        self._updating = False
        self._current_entry = None
        self._preserve_select = None
        self._preserve = None
        self._more_row = None
        self._shown = 0
        #: Writing mode (F11). Read by the top-edge reveal, which runs on
        #: every pointer move and must never fire outside the mode.
        self._writing_mode = False
        # `_pending` is the entry a queued write belongs to, captured when
        # it was queued rather than read at flush time, so a write can never
        # land on whatever happens to be selected when the timer fires. The
        # editors do the writing; the timer is the window's because both of
        # them share it.
        self._pending = None
        self._autosave = Autosave(self._write_detail)
        self._no_passage_shown = False
        self._series_shown = None
        self._has_anchored = False
        #: Which kind of thing the list is showing. A sermon manuscript is
        #: planned as a third, which is why this is a mode rather than a
        #: boolean and why the tabs are built from a table.
        self._mode = 'marks'
        self.set_title(_('Annotations'))
        self.set_default_size(1080, 720)
        # The last keystrokes before the window is shut are the ones most
        # likely to be lost; the timer may still be running when it closes.
        self.connect('close-request', self._on_close_request)

        self._build_ui()
        self._reload()
        if new_entry is not None:
            self.start_entry(**new_entry)
        if new_sermon is not None:
            self.start_sermon(**new_sermon)
        if select is not None:
            self.select_entry(select)

    def _build_ui(self):
        # Master/detail via OverlaySplitView, which is what the main window
        # already uses for its own panels. NavigationSplitView came first and
        # was right until the pane became somewhere you WRITE: it can only
        # hide a sidebar by collapsing the window, so at any comfortable width
        # the list was permanent and the editor got what was left. Here the
        # sidebar is a thing you show and hide (the button in the editor's
        # header, or F9), and collapsing merely makes it overlay instead of
        # push. It also replaces the automatic back button with an affordance
        # that works at every width, not only the narrow ones.
        self._split_view = Adw.OverlaySplitView()
        self._split_view.set_min_sidebar_width(340)
        self._split_view.set_max_sidebar_width(440)
        self._split_view.set_sidebar_width_fraction(0.34)

        # ── Sidebar page: the list + its header (refresh · tags · export) ─────
        sidebar_tv = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar_tv.add_top_bar(sidebar_header)

        refresh_btn = Gtk.Button(icon_name='scriptura-view-refresh-symbolic')
        refresh_btn.set_tooltip_text(_('Refresh'))
        set_accessible_label(refresh_btn, _('Refresh'))
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda _: self._reload())
        sidebar_header.pack_start(refresh_btn)

        tag_mgr_btn = Gtk.Button(icon_name='scriptura-view-list-bullet-symbolic')
        tag_mgr_btn.set_tooltip_text(_('Manage tags'))
        set_accessible_label(tag_mgr_btn, _('Manage tags'))
        tag_mgr_btn.add_css_class('flat')
        tag_mgr_btn.connect('clicked', self._on_open_tag_manager)
        sidebar_header.pack_start(tag_mgr_btn)

        self._new_btn = Gtk.Button(icon_name='scriptura-document-edit-symbolic')
        self._new_btn.add_css_class('flat')
        self._new_btn.connect('clicked', self._on_new_entry)
        self._label_new_button()
        sidebar_header.pack_end(self._new_btn)

        # One control for everything that moves writing in or out of the
        # window, rather than a third and fourth header button: the page as
        # a document, the open entry on its own, and the way back in.
        export_btn = Gtk.MenuButton(
            icon_name='scriptura-document-save-symbolic')
        export_btn.set_tooltip_text(_('Export and import'))
        set_accessible_label(export_btn, _('Export and import'))
        export_btn.add_css_class('flat')
        self._transfer_pop = Gtk.Popover()
        self._transfer_pop.connect(
            'show', lambda _p: self._transfer_pop.set_child(
                self._build_transfer_menu()))
        export_btn.set_popover(self._transfer_pop)
        sidebar_header.pack_end(export_btn)

        print_btn = Gtk.Button(icon_name='scriptura-document-print-symbolic')
        print_btn.set_tooltip_text(_('Print'))
        set_accessible_label(print_btn, _('Print'))
        print_btn.add_css_class('flat')
        print_btn.connect('clicked', self._on_print)
        sidebar_header.pack_end(print_btn)

        # No title in this header. The tabs just below it name the page, and
        # with a title here the window read "Annotations / Annotations |
        # Journal" — a container sharing its name with one of the things
        # inside it. Blanking it also gives the five buttons their room at
        # the 340px minimum.
        sidebar_header.set_title_widget(Gtk.Box())
        sidebar_tv.set_content(self._build_sidebar())
        self._split_view.set_sidebar(sidebar_tv)

        # ── Content side: the editor + its header. The verse ref lives in
        # this header (a WindowTitle), and the sidebar toggle leads it. ──────
        content_tv = Adw.ToolbarView()
        self._content_header = Adw.HeaderBar()
        self._sidebar_btn = Gtk.ToggleButton(
            icon_name='scriptura-sidebar-show-symbolic')
        self._sidebar_btn.add_css_class('flat')
        self._sidebar_btn.set_tooltip_text(_('Show the list (F9)'))
        set_accessible_label(self._sidebar_btn, _('Show the list'))
        self._sidebar_btn.set_active(True)
        self._sidebar_btn.connect(
            'toggled', lambda b: self._split_view.set_show_sidebar(
                b.get_active()))
        # Bound both ways: the split view hides its own sidebar when the
        # window collapses and a row is opened, and a button still claiming
        # the list is showing would be lying about the window.
        self._split_view.connect(
            'notify::show-sidebar',
            lambda *_: self._sidebar_btn.set_active(
                self._split_view.get_show_sidebar()))
        self._content_header.pack_start(self._sidebar_btn)
        self._detail_title = Adw.WindowTitle(title='', subtitle='')
        self._content_header.set_title_widget(self._detail_title)
        content_tv.add_top_bar(self._content_header)
        content_tv.set_content(self._build_detail_stack())
        self._content_tv = content_tv
        self._split_view.set_content(content_tv)

        # Toasts float over the whole split view.
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._split_view)
        self.set_content(self._toast_overlay)

        # Collapse to a single page once the window can no longer hold both
        # panes side-by-side. 660 was measured against the mark editor and the
        # sidebar's 340px size request; both are lower than the truth. The
        # sermon editor's minimum is 429 (the Series row alone is 397 —
        # set_width_chars is a MINIMUM in GTK, not a hint) and the sidebar
        # measures 374, so anything under 803 squeezed the two panes instead
        # of collapsing them and the quote and body were cut mid-word. 810 is
        # that sum with a little air.
        bp = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse('max-width: 810px'))
        bp.add_setter(self._split_view, 'collapsed', True)
        self.add_breakpoint(bp)

        self._install_shortcuts()
        self._watch_top_edge()

    # ── Room to write ─────────────────────────────────────────────────────────

    def _install_shortcuts(self):
        """F9 for the list, F11 for writing mode, Esc out of it.

        This window bound no keys at all until now, so nothing here displaces
        anything. F11 is deliberately the SAME key as the reading mode in the
        main window: one gesture for "take the room away from the chrome and
        give it to the words", wherever the reader is standing.
        """
        ctl = Gtk.ShortcutController()
        ctl.set_scope(Gtk.ShortcutScope.GLOBAL)
        for accel, fn in (('F9', self._toggle_sidebar),
                          ('F11', self._toggle_writing_mode),
                          ('Escape', self._leave_writing_mode)):
            ctl.add_shortcut(Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string(accel),
                Gtk.CallbackAction.new(lambda *_a, fn=fn: fn())))
        self.add_controller(ctl)

    def _toggle_sidebar(self):
        self._split_view.set_show_sidebar(
            not self._split_view.get_show_sidebar())
        return True

    def _toggle_writing_mode(self):
        self._set_writing_mode(not self._writing_mode)
        return True

    def _leave_writing_mode(self):
        """Esc, but only when there is a mode to leave.

        Returning False when there is none lets Esc go on doing whatever it
        did before — closing a popover, clearing the search — instead of
        being swallowed by a mode nobody is in.
        """
        if not self._writing_mode:
            return False
        self._set_writing_mode(False)
        return True

    def _set_writing_mode(self, on):
        """Give the window to the words: no list, no header, no metadata,
        no tools row, no tags — the title and the sheet.

        Every editor is told, not just the open one: the reader can switch
        rows while in the mode, and a page that rebuilt its chrome on the way
        in would arrive wearing it.
        """
        self._writing_mode = bool(on)
        for ed in (self._mark_editor, self._entry_editor, self._sermon_editor):
            ed.set_writing_mode(on)
            # With the header gone there is nothing above the title but the
            # window edge, and 16px against a rounded corner reads as a
            # mistake rather than as room.
            ed.set_margin_top(32 if on else 16)
        self._content_tv.set_reveal_top_bars(not on)
        if on:
            self._split_view.set_show_sidebar(False)
            self._toast(_('Writing mode — Esc, F11, or hover the top edge '
                          'to leave'))
        else:
            self._split_view.set_show_sidebar(
                not self._split_view.get_collapsed())

    def _watch_top_edge(self):
        """In writing mode the header comes back while the pointer is at the
        top edge, and folds again the moment it leaves.

        Without this the mode has no visible way out and no way to move the
        window: the header carries the close button. Hover, never a latch —
        pointer gone, header gone (his rule for the reveal cluster).
        """
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_top_edge_motion)
        self.add_controller(motion)

    def _on_top_edge_motion(self, _c, _x, y):
        if not self._writing_mode:
            return
        # Two thresholds, not one: revealing and hiding at the same line makes
        # the header flicker when the pointer rests on it.
        if y <= 4:
            self._content_tv.set_reveal_top_bars(True)
        elif y > 64:
            self._content_tv.set_reveal_top_bars(False)

    def _build_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(340, -1)

        # ── Search + filters ──────────────────────────────────────────────────
        filter_region = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        filter_region.set_margin_start(8)
        filter_region.set_margin_end(8)
        filter_region.set_margin_top(8)
        filter_region.set_margin_bottom(6)

        # A segmented switcher, each page named and drawn. The first pass
        # used the underline tabs (.module-tabs), on the argument that the
        # app already owned that vocabulary — but there it filters ONE list,
        # and here it chooses which kind of writing you are looking at. Adw's
        # toggle group says that: a single control, the pages side by side
        # inside it, the selection sliding between them. Icons because the
        # third page is coming and three words in a row is a menu, not a
        # switcher. In the sidebar body and not the header — the header
        # already carries five buttons, and at the 340px minimum a segmented
        # control beside them would not fit.
        self._tabs = Adw.ToggleGroup()
        self._tabs.add_css_class('round')
        self._tabs.add_css_class('page-switcher')
        self._tabs.set_halign(Gtk.Align.CENTER)
        for mode, label, icon in _MODES:
            toggle = Adw.Toggle(name=mode)
            # No tooltip: the segment already says its name in words, and a
            # tooltip that repeats a visible label only drops a box over the
            # search field below it. The child's label is what a screen
            # reader reads, too.
            toggle.set_child(_switcher_face(_(label), icon))
            self._tabs.add(toggle)
        self._tabs.set_active_name(self._mode)
        self._tabs.connect('notify::active-name', self._on_mode_switched)
        filter_region.append(self._tabs)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(
            _('Search notes, tags, references…'))
        # Three words, never four: the sidebar is 340px at its narrowest and
        # the sermons line named four things, so it ellipsized at every width
        # the pane can take. References are still searched — the placeholder
        # is an example, not the index.
        self._search_placeholders = {
            'marks': _('Search notes, tags, references…'),
            'journal': _('Search entries, tags, references…'),
            'sermons': _('Search sermons, series, tags…'),
        }
        self._search_entry.connect(
            'search-changed', lambda *_: self._apply_filter())
        self._search_entry.set_hexpand(True)

        # The five facets fold away. Measured off his screenshots: search,
        # tabs and the grid put the first row ~260px down a ~720px pane —
        # 36% of the window was filter before there was anything to filter,
        # and on the Journal page six controls governed one entry. A chevron
        # rather than a funnel because the icon set has no funnel and the
        # app's vocabulary is quiet text, not new glyphs.
        self._filter_toggle = Gtk.ToggleButton(
            icon_name='scriptura-pan-down-symbolic')
        self._filter_toggle.add_css_class('flat')
        self._filter_toggle.set_tooltip_text(_('Filters'))
        set_accessible_label(self._filter_toggle, _('Filters'))
        self._filter_toggle.connect(
            'toggled', lambda b: self._filter_revealer.set_reveal_child(
                b.get_active()))

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        search_row.append(self._search_entry)
        search_row.append(self._filter_toggle)
        filter_region.append(search_row)

        grid = Gtk.Grid(row_spacing=4, column_spacing=6)
        grid.set_column_homogeneous(True)

        self._type_drop = Gtk.DropDown(
            model=Gtk.StringList.new(
                [_(v) for v in _TYPE_VALUES[self._mode]])
        )
        self._type_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._type_drop, 0, 0, 1, 1)

        self._tag_drop = Gtk.DropDown(model=Gtk.StringList.new([_('All tags')]))
        self._tag_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._tag_drop, 1, 0, 1, 1)

        #: Per page, because the pages do not sort by the same thing. The
        #: sermons page leads with the series, which is the order they were
        #: preached in, and offers the day they were last preached — the
        #: question a preacher actually asks of an archive.
        self._sort_values = {
            'marks': [N_('Canonical order'), N_('Recently edited')],
            'journal': [N_('Canonical order'), N_('Recently edited')],
            'sermons': [N_('By series'), N_('Recently preached'),
                        N_('Recently edited')],
        }
        self._sort_drop = Gtk.DropDown(
            model=Gtk.StringList.new(
                [_(v) for v in self._sort_values[self._mode]])
        )
        self._sort_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._sort_drop, 0, 1, 1, 1)

        # The book dropdown shows localized names but filters by the canonical
        # English key; _book_keys holds those keys parallel to the model rows
        # after the "All books" sentinel, so we match by index, not by label.
        self._book_keys: list[str] = []
        self._book_drop = Gtk.DropDown(model=Gtk.StringList.new([_('All books')]))
        self._book_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._book_drop, 1, 1, 1, 1)

        # Full width, on a row of its own. The 2x2 grid above is full — the
        # sort control took the cell the module filter vacated — and a fifth
        # half-width cell would both leave a hole and be the place Russian
        # breaks first: «В этом месяце» has no room in ~160px. A date range
        # is also a wider statement than a facet, so the width reads as
        # deliberate rather than left over.
        self._date_drop = Gtk.DropDown(
            model=Gtk.StringList.new(
                [_('Any time'), _('This week'), _('This month'),
                 _('This year')])
        )
        self._date_drop.connect(
            'notify::selected', lambda *_: self._apply_filter())
        grid.attach(self._date_drop, 0, 2, 2, 1)

        self._filter_revealer = Gtk.Revealer()
        self._filter_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._filter_revealer.set_transition_duration(
            motion.DURATION_STANDARD)
        self._filter_revealer.set_child(grid)
        filter_region.append(self._filter_revealer)
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

        # Retitled per page in `_sync_empty_detail`: "Pick an annotation" is
        # the wrong sentence to read beside a list of sermons.
        self._empty_detail = Adw.StatusPage(
            icon_name='scriptura-document-edit-symbolic')
        self._empty_detail.set_vexpand(True)
        self._sync_empty_detail()
        self._detail_stack.add_named(self._empty_detail, 'empty')

        common = dict(
            on_edited=self._on_detail_edited,
            on_store_changed=self._on_store_changed,
            on_navigate=self._on_navigate,
            on_title=self._set_detail_title,
            on_flush=self._autosave.flush,
            on_row_changed=self._refill_row,
            on_regroup=self._regroup,
            reading_module=self._reading_module,
            quote=verse_quote,
            on_collect=self._collect_from_editor,
            on_open_entry=self.select_entry,
        )
        self._mark_editor = annotation_editors.MarkEditor(**common)
        self._entry_editor = annotation_editors.EntryEditor(**common)
        self._sermon_editor = annotation_editors.SermonEditor(**common)
        self._detail_stack.add_named(self._mark_editor, 'editor')
        self._detail_stack.add_named(self._entry_editor, 'entry')
        self._detail_stack.add_named(self._sermon_editor, 'sermon')
        self._detail_stack.set_visible_child_name('empty')
        return self._detail_stack

    # ── Data ──────────────────────────────────────────────────────────────────

    def _reload(self):
        self._updating = True
        self._entries = _all_entries()

        # The appendix too, or a note taken in Tobit would be missing from
        # the filter that is supposed to list every book the store holds.
        book_keys = [b for b in (sword_bridge._ALL_BOOKS
                                 + list(sword_bridge.DEUTEROCANON))
                     if any(e['book'] == b for e in self._entries)]
        all_tags = [_('All tags')] + sorted(
            {t for e in self._entries for t in e.get('tags', [])})

        # Preserve current dropdown selections so a save doesn't reset filters
        prev_type = self._type_drop.get_selected()
        prev_book_key = self._selected_book_key()
        prev_tag_text = self._dropdown_text(self._tag_drop)

        self._book_keys = book_keys
        self._book_drop.set_model(Gtk.StringList.new(
            [_('All books')] + [book_label(b) for b in book_keys]))
        self._tag_drop.set_model(Gtk.StringList.new(all_tags))

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

    def _date_floor(self):
        """The earliest date the range filter admits, or '' for any time.

        Presets, not a picker: a date picker is the wrong instrument for
        "sometime last spring", which is what the date is actually for.
        """
        idx = self._date_drop.get_selected()
        if idx <= 0:
            return ''
        today = date.today()
        if idx == 1:
            return (today - timedelta(days=today.weekday())).isoformat()
        if idx == 2:
            return today.replace(day=1).isoformat()
        return today.replace(month=1, day=1).isoformat()

    def _filtered_entries(self):
        page_kind = _WRITING_KIND.get(self._mode)
        idx = self._type_drop.get_selected()
        if self._mode == 'journal':
            tf = {1: 'anchored', 2: 'unanchored'}.get(idx, 'all')
        elif self._mode == 'sermons':
            tf = {1: 'preached', 2: 'unpreached'}.get(idx, 'all')
        else:
            tf = {1: 'notes', 2: 'highlights', 3: 'underlines'}.get(idx, 'all')

        all_tags = _('All tags')
        bf_key = self._selected_book_key()
        tag_filter = self._dropdown_text(self._tag_drop) or all_tags
        q = self._search_entry.get_text().strip().lower()
        floor = self._date_floor()

        result = []
        for e in self._entries:
            is_writing = _is_writing(e)
            # The page decides what belongs here at all; the dropdown below
            # only narrows within it.
            if e.get('kind') != (page_kind or 'mark'):
                continue
            if bf_key is not None and e['book'] != bf_key:
                continue
            if tf == 'notes' and not e['note']:
                continue
            if tf == 'highlights' and not e['highlight']:
                continue
            if tf == 'underlines' and not e['underline']:
                continue
            if tf == 'anchored' and e['book'] is None:
                continue
            if tf == 'unanchored' and e['book'] is not None:
                continue
            if tf == 'preached' and not e.get('preached'):
                continue
            if tf == 'unpreached' and e.get('preached'):
                continue
            if tag_filter != all_tags and tag_filter not in e.get('tags', []):
                continue
            if floor:
                when = _entry_date(e)
                if not when or when < floor:
                    continue
            if q:
                if e['book'] is None:
                    ref = ''
                else:
                    disp_book = book_label(e['book'])
                    ref = (f'{disp_book} {e["chapter"]}'
                           if e.get('is_chapter_note') or is_writing
                           else f'{disp_book} {e["chapter"]}:{e["app_verse"]}')
                haystack = ' '.join([
                    (e['book'] or '').lower(),
                    ref.lower(),
                    (e['note'] or '').lower(),
                    (e.get('title') or '').lower(),
                    (e.get('idea') or '').lower(),
                    _series_name(e).lower(),
                    (e.get('body') or '').lower(),
                    ' '.join(t.lower() for t in e.get('tags', [])),
                ])
                if q not in haystack:
                    continue
            result.append(e)

        sort = self._sort_drop.get_selected()
        if self._mode == 'sermons':
            if sort == 1:
                # Most recently preached. One never preached has no day to
                # sort by and goes to the bottom, not to 1970.
                result.sort(key=lambda e: (e.get('preached') or [''])[-1],
                            reverse=True)
            elif sort == 2:
                result.sort(key=lambda e: (e.get('modified')
                                           or e.get('created') or ''),
                            reverse=True)
            else:
                result = _in_series_order(result)
        elif sort == 1:
            # Most recently touched first. Entries made before the store kept
            # dates have none, and sort to the bottom rather than to 1970.
            result.sort(key=lambda e: (e.get('modified')
                                       or e.get('created') or ''),
                        reverse=True)
        return result

    def _filters_are_set(self):
        """Whether anything is narrowing the list.

        The sort is deliberately not counted: changing the ORDER of a list
        hides nothing, and forcing the panel open for it would punish the
        one control in there that cannot surprise anyone.
        """
        return any(d.get_selected() > 0 for d in
                   (self._type_drop, self._tag_drop, self._book_drop,
                    self._date_drop))

    def _sync_filter_disclosure(self):
        """A filter that is set is never a filter that is hidden.

        The panel folds to give the list its room back, but the moment
        anything is narrowing the list the panel opens itself — a reader
        must never be looking at a short list for a reason they cannot see.
        """
        if self._filters_are_set() and not self._filter_toggle.get_active():
            self._filter_toggle.set_active(True)

    def _apply_filter(self):
        if self._updating:
            return
        self._sync_filter_disclosure()
        # A rebuild re-populates the detail pane from whatever row it
        # restores, so anything still queued has to reach the store first.
        self._autosave.flush()
        self._filtered = self._filtered_entries()

        # Whatever is open stays open if the new list still holds it. Read it
        # BEFORE the clear below: emptying the list emits row-selected(None),
        # which drops _current_entry. Without this, reordering the list or
        # narrowing a filter that still contains the open entry closes it —
        # and a re-sort is not a change of what you are reading.
        open_key = (_entry_key(self._current_entry)
                    if self._current_entry is not None else None)

        # Clear existing rows (also drops any prior footer).
        clear_children(self._list)
        self._more_row = None
        self._shown = 0
        self._no_passage_shown = False
        #: Which series heading has been drawn, so the next row knows
        #: whether it opens a new one. None means none yet — distinct from
        #: '', which is the No-series group having been drawn already.
        self._series_shown = None
        # A heading that separates nothing is noise: when every row is
        # verse-less there is no group above for "No passage" to be below.
        self._has_anchored = any(e['book'] is not None for e in self._filtered)

        n = len(self._filtered)
        # Per page: "126 entries" of marks beside "1 entry" of journal was
        # one word doing two jobs in one window.
        if self._mode == 'journal':
            counted = ngettext('{n} entry', '{n} entries', n).format(n=n)
        elif self._mode == 'sermons':
            counted = ngettext('{n} sermon', '{n} sermons', n).format(n=n)
        else:
            counted = ngettext('{n} annotation', '{n} annotations',
                               n).format(n=n)
        self._count_lbl.set_text(counted)

        self._preserve = self._preserve_select
        self._preserve_select = None
        if self._preserve is None and open_key is not None and any(
                _entry_key(e) == open_key for e in self._filtered):
            self._preserve = open_key

        if not self._filtered:
            # "None yet" and "none that match" are different things to be
            # told, and the answer is per page: a reader with 127 marks and
            # no journal is not looking at an empty app.
            page_kind = _WRITING_KIND.get(self._mode, 'mark')
            on_page = any(e.get('kind') == page_kind for e in self._entries)
            if on_page:
                title = _('No matches')
                desc = _('Try a different search or filter.')
            elif self._mode == 'journal':
                title = _('No journal entries yet')
                desc = _('Write about a passage or about the day — '
                         'the pencil above starts one.')
            elif self._mode == 'sermons':
                title = _('No sermons yet')
                desc = _('Write a manuscript here, and collect verses into '
                         'it from the reading page.')
            else:
                title = _('No annotations yet')
                desc = _('Right-click a verse to highlight it or add a note.')
            empty = compact_empty_state(
                icon_name='scriptura-document-edit-symbolic',
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
        target_row = self._append_rows()
        while (target_row is None and preserve_present
               and self._shown < len(self._filtered)):
            target_row = self._append_rows()

        if target_row is not None:
            self._list.select_row(target_row)
            # row-selected fires asynchronously; populate immediately too
            # so the detail pane updates with the freshly-reloaded entry
            self._current_entry = target_row._entry
            self._populate_detail(target_row._entry)
            self._detail_stack.set_visible_child_name(
                self._stack_page(target_row._entry))
        elif self._preserve is not None:
            # Entry no longer exists (all annotations cleared); reset detail
            self._current_entry = None
            self._clear_detail_title()
            self._detail_stack.set_visible_child_name('empty')

    def _append_rows(self):
        """Append the next _RENDER_CAP slice of self._filtered, then a
        Show-more footer if rows remain. Returns the row matching the
        preserved entry key if it lands in this slice, else None."""
        if self._more_row is not None:
            self._list.remove(self._more_row)
            self._more_row = None

        target = None
        chunk = self._filtered[self._shown:self._shown + _RENDER_CAP]
        for entry in chunk:
            # Series lead the sermons page, and a series heading is drawn
            # wherever the name changes — including the empty one, which is
            # the No-series group at the end. The list is already in that
            # order, so this needs no lookahead.
            if self._grouping_by_series():
                name = _series_name(entry)
                if name != self._series_shown:
                    self._series_shown = name
                    self._list.append(self._make_group_row(
                        name or _('No series'), series=name))
            # The list is already ordered with the verse-less entries last,
            # so one flag is enough: the header goes in ahead of the first of
            # them, wherever the render cap happens to have got to.
            elif (entry['book'] is None and not self._no_passage_shown
                    and self._has_anchored):
                self._no_passage_shown = True
                self._list.append(self._make_group_row(_('No passage')))
            row = self._make_row(entry)
            self._list.append(row)
            if self._preserve and _entry_key(entry) == self._preserve:
                target = row
        self._shown += len(chunk)

        if self._shown < len(self._filtered):
            self._more_row = self._make_more_row()
            self._list.append(self._more_row)
        return target

    def _grouping_by_series(self):
        """Whether the list is in series order, which is the only order the
        series headings mean anything in. Sorted by date, a heading would
        appear and reappear down the list."""
        return self._mode == 'sermons' and self._sort_drop.get_selected() == 0

    def _make_group_row(self, title, series=None):
        """A section rule in a printed index, not a GTK header: a dim caption
        under a hairline, no box and no fill.

        A named series carries one more thing: the way to rename it. The
        heading IS the series — nothing else in the window names it twice —
        so the misspelling is read here, and until now correcting it meant
        opening every sermon in the series and retyping the field.
        """
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row._series = series or None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        rule = Gtk.Separator()
        rule.add_css_class('journal-divider')
        rule.set_margin_bottom(8)
        box.append(rule)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class('dim-label')
        lbl.add_css_class('caption')
        lbl.set_margin_start(10)
        lbl.set_margin_bottom(4)
        lbl.set_hexpand(True)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        line.append(lbl)
        if series:
            rename = Gtk.Button(icon_name='scriptura-document-edit-symbolic')
            rename.add_css_class('flat')
            rename.add_css_class('dim-label')
            rename.set_valign(Gtk.Align.CENTER)
            tip = _('Rename “{series}”').format(series=series)
            rename.set_tooltip_text(tip)
            set_accessible_label(rename, tip)
            rename.connect('clicked', self._on_rename_series, series)
            line.append(rename)
        box.append(line)
        box.set_margin_top(10)
        row.set_child(box)
        return row

    def _on_rename_series(self, _btn, series):
        """Rename a series across every sermon in it.

        A merge as well as a rename, exactly as the tag manager's is: typing
        a name already in use joins the two groups, which is the shape of the
        mistake — the same series entered twice, spelled differently.
        """
        self._autosave.flush()
        dlg = Adw.AlertDialog(
            heading=_('Rename “{series}”').format(series=series),
            body=_('Every sermon in this series is renamed. If the name '
                   'matches another series, the two are joined.'),
        )
        entry = Gtk.Entry()
        entry.set_text(series)
        entry.set_activates_default(True)
        dlg.set_extra_child(entry)
        dlg.add_response('cancel', _('Cancel'))
        dlg.add_response('rename', _('Rename'))
        dlg.set_response_appearance('rename', Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response('rename')

        dlg.connect('response', lambda _d, response: (
            self._rename_series(series, entry.get_text().strip())
            if response == 'rename' else None))
        dlg.present(self)

    def _rename_series(self, old, new):
        """Do it, and put the list back together around it."""
        if not new or new == old:
            return
        sermons.rename_series(old, new)
        # The open sermon's row is stale the moment the store changed — it
        # carries the old name in `series` — so the editor is repopulated
        # from what the reload found, under the same selection.
        self._preserve_select = (_entry_key(self._current_entry)
                                 if self._current_entry is not None else None)
        self._reload()

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
        btn.connect('clicked', lambda _b: self._append_rows())
        row.set_child(btn)
        return row

    # ── Row builder ───────────────────────────────────────────────────────────

    def _make_row(self, entry):
        row = Gtk.ListBoxRow()
        row._entry = entry
        self._fill_row(row, entry)
        return row

    def _fill_row(self, row, entry):
        """Build (or rebuild) one row's contents in place.

        Autosave calls this after a write so the preview, the badges and the
        date follow what was just typed. Rebuilding the child rather than the
        row keeps the ListBoxRow itself — and so the selection, and so the
        reader's place in the list — untouched.
        """
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # Left color strip
        strip = Gtk.Box()
        strip.set_size_request(5, -1)
        if _is_writing(entry):
            # No strip on the Journal page. On the Annotations page the strip
            # IS the highlight hue — it carries the one thing a mark row has
            # to say at a glance. Every entry wearing the same ink said
            # nothing: a constant is decoration in the costume of a signal.
            strip_class = 'strip-none'
        elif entry.get('is_chapter_note'):
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

        # The two kinds carry the same geometry with the voices inverted.
        # A mark leads with its reference, which is structure, so it is set
        # in the sans `heading`. An entry leads with its title, which is the
        # reader's own prose, so it is set in the serif and the reference
        # drops to a dim caption beneath it. That is the app's own type
        # system telling them apart — no badge, no icon, no new hue.
        is_entry = _is_writing(entry)
        is_sermon = entry.get('kind') == 'sermon'
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if is_sermon:
            lead_text = entry.get('title') or _('Untitled sermon')
        elif is_entry:
            lead_text = entry.get('title') or _('Untitled entry')
        elif entry.get('is_chapter_note'):
            lead_text = _('{ref} — Chapter Note').format(
                ref=f'{book_label(entry["book"])} {entry["chapter"]}')
        else:
            lead_text = (f'{book_label(entry["book"])} {entry["chapter"]}'
                         f':{entry["app_verse"]}')
        lead = Gtk.Label(label=lead_text, xalign=0, hexpand=True)
        lead.set_ellipsize(Pango.EllipsizeMode.END)
        lead.add_css_class('journal-entry-title' if is_entry else 'heading')
        top.append(lead)

        if is_sermon:
            # The day it was last preached, and nothing at all when it has
            # not been — an archive that invents a date for a sermon still
            # being written is lying about the one thing this column says.
            when = _preached_label(entry)
        elif is_entry:
            when = _entry_day_label(entry)
        else:
            when = _edited_label(entry)
        if when:
            when_lbl = Gtk.Label(label=when, xalign=1)
            when_lbl.add_css_class('dim-label')
            when_lbl.add_css_class('caption')
            top.append(when_lbl)
        content.append(top)

        if is_sermon:
            # The big idea is the caption where an entry shows its
            # reference: a list of claims reads better than a list of
            # filenames, and the passage is a chip in the editor anyway.
            caption = entry.get('idea') or _anchor_label(entry)
            part = _series_part_label(entry)
            if part:
                caption = f'{part} · {caption}' if caption else part
            if caption:
                cap_lbl = Gtk.Label(label=caption, xalign=0)
                cap_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                cap_lbl.add_css_class('dim-label')
                cap_lbl.add_css_class('caption')
                content.append(cap_lbl)
        elif is_entry:
            anchor_text = _anchor_label(entry)
            if anchor_text:
                anchor_lbl = Gtk.Label(label=anchor_text, xalign=0)
                anchor_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                anchor_lbl.add_css_class('dim-label')
                anchor_lbl.add_css_class('caption')
                content.append(anchor_lbl)

        # Type badges — a hue dot coloured to the highlight (the name beside it
        # stays the colourblind-safe cue), then plain captions for underline /
        # note. No emoji: muted captions in the app's quiet vocabulary.
        if not entry.get('is_chapter_note') and not is_entry:
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

        # Preview: two lines of what was written (full text in the detail
        # pane). An entry previews its body, since its title is the lead.
        # Joined into one line first — a two-line cap counts soft wraps, so
        # a paragraphed entry drew every paragraph and the row grew to the
        # length of the writing. Entries lose their notation with it; a
        # mark's note has none to lose.
        preview = (journal_markup.preview(entry.get('body') or '') if is_entry
                   else ' '.join((entry['note'] or '').split()))
        if preview:
            note_lbl = Gtk.Label(label=preview, xalign=0)
            note_lbl.set_wrap(True)
            note_lbl.set_lines(2)
            note_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(note_lbl)

        # Tag chips — clicking sets the Tag filter to that tag
        tags = entry.get('tags', [])
        if tags:
            # A WrapBox, not a FlowBox: a flow box stretches every cell to
            # fill its line, so a chip's hover fill ran on past the chip.
            tag_flow = Adw.WrapBox(child_spacing=4, line_spacing=2)
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
        del_btn = Gtk.Button(icon_name='scriptura-user-trash-symbolic')
        del_btn.add_css_class('flat')
        del_btn.add_css_class('journal-del')
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_margin_end(6)
        if is_sermon:
            del_label = _('Delete sermon')
        elif is_entry:
            del_label = _('Delete entry')
        else:
            del_label = _('Delete annotation')
        del_btn.set_tooltip_text(del_label)
        set_accessible_label(del_btn, del_label)
        del_btn.connect('clicked', self._on_delete_entry, entry)
        outer.append(del_btn)

        row.set_child(outer)

    # ── Detail pane ───────────────────────────────────────────────────────────

    def _on_row_selected(self, _list, row):
        # Before anything else: the fields still hold the outgoing entry's
        # text, and _populate_detail is about to overwrite them. Flushing
        # after that point would file this entry's words under the next one.
        self._autosave.flush()
        if row is None or not hasattr(row, '_entry'):
            self._current_entry = None
            self._clear_detail_title()
            self._detail_stack.set_visible_child_name('empty')
            return
        self._current_entry = row._entry
        self._populate_detail(row._entry)
        self._detail_stack.set_visible_child_name(
            self._stack_page(row._entry))
        # When collapsed the sidebar overlays the editor, so opening a row
        # has to get the list out of the way; side-by-side it stays put.
        if self._split_view.get_collapsed():
            self._split_view.set_show_sidebar(False)

    def _on_close_request(self, _win):
        self._autosave.flush()
        return False

    def destroy(self):
        """Never leave a write armed on a window that is going away.

        `close-request` covers the reader closing it, but not a window
        destroyed outright — and **a GLib timeout outlives its window**, so a
        pending write lands later, into whatever the store points at by then.
        GTK4 has no ::destroy signal to hang this on and `unrealize` never
        fires for a window that was never shown, so the override goes here:
        destroy() is the one teardown path everything takes.

        Flush rather than cancel: the words are the reader's, and a window
        being taken down is not them changing their mind.
        """
        self._autosave.flush()
        self._entry_editor.shutdown()
        self._sermon_editor.shutdown()
        self._mark_editor.shutdown()
        super().destroy()

    #: Which editor, and which page of the stack, one row belongs to.
    _EDITORS = {'entry': 'entry', 'sermon': 'sermon'}

    def _editor_for(self, entry):
        kind = entry.get('kind')
        if kind == 'sermon':
            return self._sermon_editor
        if kind == 'entry':
            return self._entry_editor
        return self._mark_editor

    def _stack_page(self, entry):
        return self._EDITORS.get(entry.get('kind'), 'editor')

    def _set_detail_title(self, title, subtitle):
        self._detail_title.set_title(title)
        self._detail_title.set_subtitle(subtitle)

    def _refill_row(self, entry):
        """One row's display has changed. The editors own the writing; the
        list is the window's."""
        row = self._row_for_entry(entry)
        if row is not None:
            self._fill_row(row, entry)

    def _regroup(self):
        """An open row's series changed, so it belongs under a different
        heading. Only the series-ordered sermons list draws any, so every
        other page can leave its rows where they are."""
        if self._grouping_by_series():
            self._apply_filter()

    def _on_store_changed(self, book, chapter, verse):
        if self._on_annotation_changed:
            self._on_annotation_changed(book, chapter, verse)

    def _populate_detail(self, entry):
        self._editor_for(entry).populate(entry)

    def _write_detail(self):
        """Write whatever is queued, to the row it was queued for."""
        e = self._pending
        self._pending = None
        if e is not None:
            self._editor_for(e).write(e)

    def _on_detail_edited(self, entry):
        """An edit in either editor: queue a write for the row that is open
        *now*, so the timer cannot misfile it later."""
        self._pending = entry
        self._autosave.schedule()

    def _clear_detail_title(self):
        self._detail_title.set_title('')
        self._detail_title.set_subtitle('')

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

    def _on_mode_switched(self, group, _pspec):
        """The switcher moved. A toggle group is always on exactly one
        segment, so there is no off state to guard against here."""
        self.set_mode(group.get_active_name())

    def set_mode(self, mode):
        """Show one of the window's pages.

        The list, the render cap, the preserved selection, the detail stack
        and the autosave are all shared — a page is which rows the filter
        admits and which question the type dropdown asks, not a second copy
        of the machinery.
        """
        if mode == self._mode:
            return
        self._autosave.flush()
        self._mode = mode
        if self._tabs.get_active_name() != mode:
            self._tabs.set_active_name(mode)
        self._updating = True
        self._type_drop.set_model(
            Gtk.StringList.new([_(v) for v in _TYPE_VALUES[mode]]))
        self._type_drop.set_selected(0)
        # The sort asks a different question per page too, so its model is
        # swapped with the type's — and reset, or "Recently preached" would
        # carry over to a page that has no preaching dates.
        self._sort_drop.set_model(
            Gtk.StringList.new([_(v) for v in self._sort_values[mode]]))
        self._sort_drop.set_selected(0)
        self._search_entry.set_placeholder_text(
            self._search_placeholders[mode])
        self._updating = False
        # Nothing on the outgoing page is worth restoring on the incoming
        # one, and a stale key would only make _apply_filter hunt for a row
        # that cannot be there.
        self._current_entry = None
        self._preserve_select = None
        self._clear_detail_title()
        self._sync_empty_detail()
        self._detail_stack.set_visible_child_name('empty')
        self._label_new_button()
        self._retitle()
        self._apply_filter()

    def _sync_empty_detail(self):
        """What the right-hand pane says with nothing open, per page."""
        if self._mode == 'sermons':
            title = _('No sermon selected')
            desc = _('Pick a sermon from the list to write in it.')
        elif self._mode == 'journal':
            title = _('No entry selected')
            desc = _('Pick an entry from the list to view or edit it.')
        else:
            title = _('No entry selected')
            desc = _('Pick an annotation from the list to view or edit it.')
        self._empty_detail.set_title(title)
        self._empty_detail.set_description(desc)

    def _page_name(self):
        names = {mode: label for mode, label, _icon in _MODES}
        return _(names.get(self._mode, _MODES[0][1]))

    def _retitle(self):
        """The window's name follows its page — what the task switcher and
        the screen reader announce."""
        self.set_title(self._page_name())

    def _toast(self, msg):
        toast = Adw.Toast.new(msg)
        toast.set_timeout(2)
        self._toast_overlay.add_toast(toast)

    # ── Existing actions (delete / activate / export) ─────────────────────────

    def _on_delete_entry(self, _btn, entry):
        # Cancel, not flush: writing the note back out on the way to deleting
        # it would resurrect what the reader just asked to remove.
        if self._pending is entry:
            self._autosave.cancel()
            self._pending = None
        if entry.get('kind') == 'entry':
            self._delete_journal_entry(entry)
            return
        if entry.get('kind') == 'sermon':
            self._delete_sermon(entry)
            return
        verse = None if entry.get('is_chapter_note') else entry['verse']
        removed = annotations.delete_annotation(
            None, entry['book'], entry['chapter'], verse
        )
        # If we just deleted the currently-selected entry, the detail pane
        # will reset to empty when _reload finds no matching row to restore.
        self._preserve_select = _entry_key(entry)
        self._reload()
        if self._on_annotation_changed:
            self._on_annotation_changed(
                entry['book'], entry['chapter'], verse)
        if removed is None:
            return
        # Deletion is otherwise irreversible — offer an undo while the
        # toast lasts (default timeout, unlike _toast's quick 2s).
        toast = Adw.Toast.new(_('Note deleted') if verse is None
                              else _('Annotation deleted'))
        toast.set_button_label(_('Undo'))
        toast.connect('button-clicked', self._on_undo_delete,
                      entry, verse, removed)
        self._toast_overlay.add_toast(toast)

    def _delete_journal_entry(self, entry):
        removed = journal.delete(entry['id'])
        self._preserve_select = _entry_key(entry)
        self._reload()
        if removed is None:
            return
        toast = Adw.Toast.new(_('Entry deleted'))
        toast.set_button_label(_('Undo'))
        toast.connect('button-clicked',
                      lambda _t: self._undo_entry_delete(removed))
        self._toast_overlay.add_toast(toast)

    def _delete_sermon(self, entry):
        removed = sermons.delete(entry['id'])
        self._preserve_select = _entry_key(entry)
        self._reload()
        if removed is None:
            return
        toast = Adw.Toast.new(_('Sermon deleted'))
        toast.set_button_label(_('Undo'))
        toast.connect('button-clicked',
                      lambda _t: self._undo_sermon_delete(removed))
        self._toast_overlay.add_toast(toast)

    def _undo_sermon_delete(self, removed):
        sermons.restore(removed)
        self._preserve_select = ('sermon', removed['id'])
        self._reload()

    def _undo_entry_delete(self, removed):
        journal.restore(removed)
        self._preserve_select = ('entry', removed['id'])
        self._reload()

    def select_entry(self, entry_id):
        """Open an existing entry by id — the door app search comes through.

        Clears the filters first: a search result that answers with an empty
        list because the type dropdown was left on Highlights is worse than
        no result at all.
        """
        self._autosave.flush()
        key = ('entry', entry_id)
        if not any(_entry_key(e) == key for e in self._entries):
            return False
        self.set_mode('journal')
        self._updating = True
        self._search_entry.set_text('')
        for drop in (self._type_drop, self._tag_drop, self._book_drop,
                     self._date_drop):
            drop.set_selected(0)
        self._updating = False
        self._preserve_select = key
        self._apply_filter()
        return True

    def show_entries_on(self, book, chapter):
        """Open the journal on what has been written about one chapter.

        The book filter, not a chapter one: the window has no chapter facet
        and inventing one for this door would put a sixth control in the
        panel to serve a single caller. The book narrows the list to the
        neighbourhood and the first entry on the chapter is selected, which
        is the one the reader asked for.
        """
        self._autosave.flush()
        self.set_mode('journal')
        self._updating = True
        self._search_entry.set_text('')
        for drop in (self._type_drop, self._tag_drop, self._date_drop):
            drop.set_selected(0)
        self._book_drop.set_selected(
            self._book_keys.index(book) + 1 if book in self._book_keys else 0)
        self._updating = False
        for entry in self._entries:
            if entry.get('kind') != 'entry':
                continue
            if any(a['book'] == book and a['chapter'] == chapter
                   for a in entry.get('anchors') or []):
                self._preserve_select = _entry_key(entry)
                break
        self._apply_filter()
        self._sync_filter_disclosure()

    def show_sermons_on(self, book, chapter):
        """Open the sermons page on what has been preached from one chapter.

        The journal's door one page over, filter for filter — the book
        narrows the list and the first sermon anchored on the chapter is
        selected. What it answers is the question an archive exists for: you
        are standing in this passage, and you have been here before.
        """
        self._autosave.flush()
        self.set_mode('sermons')
        self._updating = True
        self._search_entry.set_text('')
        for drop in (self._type_drop, self._tag_drop, self._date_drop):
            drop.set_selected(0)
        self._book_drop.set_selected(
            self._book_keys.index(book) + 1 if book in self._book_keys else 0)
        self._updating = False
        for entry in self._entries:
            if entry.get('kind') != 'sermon':
                continue
            if any(a['book'] == book and a['chapter'] == chapter
                   for a in entry.get('anchors') or []):
                self._preserve_select = _entry_key(entry)
                break
        self._apply_filter()
        self._sync_filter_disclosure()

    def _label_new_button(self):
        """The pencil starts whatever the page is for. On the Annotations
        page there is nothing to start — a mark is made at a verse — so it
        keeps offering the journal, which is where writing begins."""
        label = (_('New sermon') if self._mode == 'sermons'
                 else _('New journal entry'))
        self._new_btn.set_tooltip_text(label)
        set_accessible_label(self._new_btn, label)

    def _on_new_entry(self, _btn):
        """Start a page of writing from the window itself — no anchors.

        This is the door you come through when the writing is not about a
        passage you have open. The Today and verse doors bring their own.
        """
        if self._mode == 'sermons':
            self.start_sermon()
        else:
            self.start_entry()

    def start_entry(self, anchors=None, plan=None, collect=None, date=None):
        """Open a fresh entry in the editor, focused and ready to type.

        The id is minted here and carried on the row; **nothing is written
        until there are words**, so a reader who comes through a door and
        changes their mind leaves journal.json exactly as it was.

        `plan` and `collect` are provenance the caller knows and the entry
        never will again — which plan day it came out of, and which Sunday.
        They cost nothing to record now and cannot be recovered later.
        """
        self.set_mode('journal')
        anchors = list(anchors or [])
        first = anchors[0] if anchors else None
        verses = first['verses'] if first else []
        row_entry = {
            'kind': 'entry', 'id': journal.new_id(),
            'book': first['book'] if first else None,
            'chapter': first['chapter'] if first else None,
            'app_verse': verses[0] if verses else None,
            'verse': None,
            'highlight': None, 'underline': False, 'note': None,
            'is_chapter_note': False,
            'title': '', 'body': '', 'date': date or journal.today(),
            'anchors': anchors, 'plan': plan, 'collect': collect, 'tags': [],
            'created': None, 'modified': None,
        }
        self._autosave.flush()
        self._entries.append(row_entry)
        # Back into reading order, or the new row is simply last — which for
        # an anchored entry means it lands BELOW the No-passage header and
        # reads as having no passage when it has one.
        self._entries = _in_reading_order(self._entries)
        # Clear the filters that would hide it. A brand-new entry has no
        # tags and no book, so leaving them set would answer the New button
        # with an empty list.
        self._updating = True
        self._search_entry.set_text('')
        for drop in (self._type_drop, self._tag_drop, self._book_drop,
                     self._date_drop):
            drop.set_selected(0)
        self._updating = False
        self._preserve_select = _entry_key(row_entry)
        self._apply_filter()
        self._entry_editor.title.grab_focus()
        return row_entry

    def start_sermon(self, anchors=None, collect=None, series=None):
        """Open a fresh sermon in the editor, focused and ready to type.

        The id is minted here and carried on the row; **nothing is written
        until there are words**, so a reader who opens the pencil and changes
        their mind leaves sermons.json exactly as it was.

        `collect` is provenance the caller knows and the manuscript never
        will again — which Sunday it was begun for. It costs nothing now and
        cannot be recovered later.
        """
        self.set_mode('sermons')
        anchors = list(anchors or [])
        first = anchors[0] if anchors else None
        verses = first['verses'] if first else []
        row_entry = {
            'kind': 'sermon', 'id': sermons.new_id(),
            'book': first['book'] if first else None,
            'chapter': first['chapter'] if first else None,
            'app_verse': verses[0] if verses else None,
            'verse': None,
            'highlight': None, 'underline': False, 'note': None,
            'is_chapter_note': False,
            'title': '', 'idea': '', 'body': '',
            'anchors': anchors, 'series': series, 'preached': [],
            'collect': collect, 'tags': [],
            'created': None, 'modified': None,
        }
        self._autosave.flush()
        self._entries.append(row_entry)
        self._entries = _in_reading_order(self._entries)
        # Clear the filters that would hide it: a brand-new sermon has no
        # tags, no series and no passage, so leaving them set would answer
        # the pencil with an empty list.
        self._updating = True
        self._search_entry.set_text('')
        for drop in (self._type_drop, self._tag_drop, self._book_drop,
                     self._date_drop):
            drop.set_selected(0)
        self._updating = False
        self._preserve_select = _entry_key(row_entry)
        self._apply_filter()
        self._sermon_editor.title.grab_focus()
        return row_entry

    def select_sermon(self, sermon_id):
        """Open an existing sermon by id — the door app search comes through,
        and the one a collecting toast comes back through."""
        self._autosave.flush()
        key = ('sermon', sermon_id)
        if not any(_entry_key(e) == key for e in self._entries):
            self._reload()
        if not any(_entry_key(e) == key for e in self._entries):
            return False
        self.set_mode('sermons')
        self._updating = True
        self._search_entry.set_text('')
        for drop in (self._type_drop, self._tag_drop, self._book_drop,
                     self._date_drop):
            drop.set_selected(0)
        self._updating = False
        self._preserve_select = key
        self._apply_filter()
        return True

    def open_sermon_id(self):
        """The sermon currently open in the editor, or None — so a collecting
        door can tell whether to write through the store or the buffer."""
        if (self._current_entry is not None
                and self._current_entry.get('kind') == 'sermon'):
            return self._current_entry.get('id')
        return None

    def _collect_from_editor(self, sermon_id, text, anchor=None):
        """A mark being put into a sermon from this window's own editor."""
        if not self.collect_into(sermon_id, text, anchor):
            return
        sermon = sermons.get(sermon_id)
        self._toast(_('Added to “{title}”').format(
            title=(sermon or {}).get('title') or _('Untitled sermon')))

    def collect_into(self, sermon_id, text, anchor=None):
        """Add collected text to a sermon, wherever it currently lives.

        Two paths, and the split matters: a sermon OPEN in the editor owns
        its buffer, and writing underneath it would be overwritten by the
        next autosave — so the open one is appended to in the buffer, and
        every other one through the store.
        """
        if self.open_sermon_id() == sermon_id:
            self._sermon_editor.collect(text, anchor)
            return True
        if sermons.append(sermon_id, text, anchor) is None:
            return False
        self._reload()
        return True

    def _on_undo_delete(self, _toast, entry, verse, removed):
        annotations.restore_annotation(
            None, entry['book'], entry['chapter'], verse, removed)
        self._preserve_select = _entry_key(entry)
        self._reload()
        if self._on_annotation_changed:
            self._on_annotation_changed(
                entry['book'], entry['chapter'], verse)

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, '_entry'):
            e = row._entry
            # A verse-less entry has nowhere to go, and must not navigate to
            # whatever chapter happens to be open.
            if e['book'] is None:
                return
            self._on_navigate(e['book'], e['chapter'], e['app_verse'] or 1)

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

    def _export_module(self):
        """The translation an export or a print quotes from.

        The same rule the detail pane follows: the interface language's own
        text where it is installed, the reading module otherwise. A document
        that leaves the app should carry the words the reader was reading.
        """
        reading = None
        if self._reading_module is not None:
            try:
                reading = self._reading_module()
            except Exception:
                reading = None
        return quote_module() or reading

    def _document(self, markdown=True, rows=None, title=None):
        """A document from `rows`, or from the filtered list.

        The filters ARE the scopes — one entry, a season, the lot — so there
        is no second scope picker saying the same thing twice. `rows` is the
        one exception: exporting the entry already open should not make the
        reader build a filter to describe it.

        A document of one sermon is headed by that sermon. Headed "Sermons"
        it would name the shelf over a page that is plainly one manuscript,
        and the one printed sheet a preacher carries wants its own name at
        the top.
        """
        module = self._export_module()
        if not module:
            return None
        return passage_export.build_annotations(
            self._filtered_entries() if rows is None else rows,
            module, markdown=markdown, title=title or self._page_name())

    def _build_transfer_menu(self):
        """Built on show, because what it offers depends on the page and on
        whether anything is open."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        page = Gtk.Button()
        page.add_css_class('flat')
        page.set_child(Gtk.Label(
            label=_('Export {page}…').format(page=self._page_name()),
            xalign=0))
        page.connect('clicked', self._on_export)
        box.append(page)

        one = Gtk.Button()
        one.add_css_class('flat')
        if self._mode == 'sermons':
            one_label = _('Export this sermon…')
        elif self._mode == 'journal':
            one_label = _('Export this entry…')
        else:
            one_label = _('Export this annotation…')
        one.set_child(Gtk.Label(label=one_label, xalign=0))
        one.set_sensitive(self._current_entry is not None)
        one.connect('clicked', self._on_export_one)
        box.append(one)

        # Print, twice, for the same reason export is offered twice: the
        # header's own print button is the LIST, and the one thing a preacher
        # prints is the single manuscript they are about to carry into the
        # pulpit — not the archive it is filed in.
        print_one = Gtk.Button()
        print_one.add_css_class('flat')
        if self._mode == 'sermons':
            print_label = _('Print this sermon…')
        elif self._mode == 'journal':
            print_label = _('Print this entry…')
        else:
            print_label = _('Print this annotation…')
        print_one.set_child(Gtk.Label(label=print_label, xalign=0))
        print_one.set_sensitive(self._current_entry is not None)
        print_one.connect('clicked', self._on_print_one)
        box.append(print_one)

        if self._mode == 'journal':
            box.append(Gtk.Separator(
                orientation=Gtk.Orientation.HORIZONTAL))
            incoming = Gtk.Button()
            incoming.add_css_class('flat')
            incoming.set_child(Gtk.Label(label=_('Import entries…'), xalign=0))
            incoming.connect('clicked', self._on_import)
            box.append(incoming)
        return box

    def _on_export(self, _btn):
        self._autosave.flush()
        self._transfer_pop.popdown()
        dialog = Gtk.FileDialog()
        # Named for its page, like the document, the file name and the
        # print job. The title said "Export Annotations" over a save dialog
        # that was about to write journal.md.
        dialog.set_title(f"{_('Export')} — {self._page_name()}")
        dialog.set_initial_name(
            {'journal': 'journal.md', 'sermons': 'sermons.md'}.get(
                self._mode, 'annotations.md'))
        dialog.save(self, None, self._on_export_finish)

    def _on_export_finish(self, dialog, result, rows=None):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # cancelled, or no location chosen
        path = gfile.get_path() if gfile else None
        if not path:
            self._show_export_error(
                _('Please choose a location on this computer.'))
            return
        text = self._document(
            rows=rows,
            title=self._one_document_name(rows[0]) if rows else None)
        if text is None:
            self._show_export_error(
                _('No translation is installed to quote from.'))
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as ex:
            self._show_export_error(
                _('Could not write to {path}:\n{error}').format(
                    path=path, error=ex))

    def _on_export_one(self, _btn):
        """The open entry, on its own.

        The filters are the scopes for everything else — one entry, a season,
        the lot — but narrowing the list to the thing already open, in order
        to export it, is a filter the reader should not have to build.
        """
        if self._current_entry is None:
            return
        self._autosave.flush()
        self._transfer_pop.popdown()
        # Carried in the callback rather than parked on the window: a scope
        # left behind by a cancelled save would quietly become the scope of
        # the next print.
        rows = [self._current_entry]
        dialog = Gtk.FileDialog()
        dialog.set_title(f"{_('Export')} — {self._page_name()}")
        dialog.set_initial_name(self._one_file_name(self._current_entry))
        dialog.save(self, None,
                    lambda d, r: self._on_export_finish(d, r, rows))

    @staticmethod
    def _one_file_name(entry):
        """A file named after what is in it, not after the window.

        Down to letters, digits and dashes: this is offered into a save
        dialog, and a name carrying a colon or a slash is a name some file
        system will refuse.
        """
        stem = (entry.get('title') or '').strip()
        if not stem:
            stem = _anchor_label(entry) or _('entry')
        stem = re.sub(r'[^\w\s-]', '', stem, flags=re.UNICODE).strip()
        stem = re.sub(r'\s+', '-', stem).lower()
        return f'{stem[:60] or "entry"}.md'

    def _on_print(self, _btn):
        """Print what the list is showing, on the same paper as a passage."""
        self._print(None)

    def _on_print_one(self, _btn):
        """The open sermon on its own — the copy that goes to the pulpit.

        Named for what is in it, as the exported file is: a print queue
        showing "Sermons" three times over says nothing about which of them
        is the one to collect.
        """
        if self._current_entry is None:
            return
        self._transfer_pop.popdown()
        entry = self._current_entry
        self._print([entry], self._one_document_name(entry))

    def _one_document_name(self, entry):
        """What one entry's own document is called."""
        return ((entry.get('title') or '').strip()
                or _anchor_label(entry) or self._page_name())

    def _print(self, rows, job_name=None):
        """Print `rows` (or the whole filtered list), on a passage's paper."""
        self._autosave.flush()
        text = self._document(markdown=False, rows=rows, title=job_name)
        if not text:
            self._show_export_error(
                _('No translation is installed to quote from.'))
            return
        operation = passage_print.build_text_operation(text, job_name)
        try:
            operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, self)
        except Exception:
            # A refused portal, no printers, a cancelled job — none of them
            # is a reason to take the window down.
            _log.exception('printing the annotations failed')
            self._toast(_('Could not print'))

    def _on_import(self, _btn):
        """Take Markdown files in as entries."""
        self._transfer_pop.popdown()
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Import entries'))
        text = Gtk.FileFilter()
        text.set_name(_('Text and Markdown files'))
        for pattern in ('*.md', '*.markdown', '*.txt'):
            text.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(text)
        dialog.set_filters(filters)
        dialog.set_default_filter(text)
        dialog.open_multiple(self, None, self._on_import_finish)

    def _on_import_finish(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # cancelled
        added, failed = 0, 0
        for i in range(files.get_n_items()):
            path = files.get_item(i).get_path()
            if not path:
                failed += 1
                continue
            try:
                with open(path, encoding='utf-8') as f:
                    raw = f.read()
                stamp = os.stat(path).st_mtime
            except (OSError, UnicodeDecodeError):
                # A binary file with a .txt name, a permission, a race —
                # none of them is a reason to abandon the other nine files.
                _log.exception('could not read %s', path)
                failed += 1
                continue
            entry = journal_import.read(raw, path, stamp)
            if entry is None:
                failed += 1
                continue
            journal.save(journal.new_id(), date=entry['date'],
                         title=entry['title'], body=entry['body'],
                         tags=entry['tags'])
            added += 1
        self.set_mode('journal')
        self._reload()
        if added:
            self._toast(ngettext('Imported {n} entry', 'Imported {n} entries',
                                 added).format(n=added))
        if failed:
            self._toast(ngettext('{n} file could not be read',
                                 '{n} files could not be read',
                                 failed).format(n=failed))

    def _show_export_error(self, msg):
        dlg = Adw.AlertDialog(heading=_('Export failed'), body=msg)
        dlg.add_response('ok', _('OK'))
        dlg.present(self)
