"""The two editors the Annotations window shows on its right.

Pulled out of `annotations_window` when it had grown to 2,259 lines and 62
methods — the third god object in a repo that already names two. The split
is along the seam that was already there: the window owns the LIST and the
stack, an editor owns one kind of thing and the widgets that write it.

**The reason it happened now is the sermon manuscript page.** A third kind of
object needs a third editor, and adding it to the window would have put
another ~280 lines into the largest class here. Adding it to this file is a
third subclass with its own `populate` and `write`.

An editor never reaches back into the window. It is handed four callbacks —
edited, store-changed, navigate, title — and the row it is looking at, and it
touches nothing else.
"""

# NO `from __future__ import annotations` here: it binds the name
# `annotations` in this module, and this module imports the app's store of
# that name. The hints below need no future import on the Python this ships
# against.
from datetime import date
from typing import Any, Callable, TypedDict

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gtk, Adw, GLib, Pango

from a11y import set_accessible_label
from gtk_utils import Autosave, clear_children
from i18n import format_date
import annotation_dialogs
import annotations
import church_year
import journal
import journal_markup
import motion
import sermons


def N_(message):
    """No-op gettext marker for module-level data; translated at display."""
    return message


#: The four highlight hues, their display names and their swatch classes —
#: moved with the editor that draws them. The list row's dot and strip stay
#: in the window, which is what draws those.
_HL_COLORS = ['#ffff00', '#90ee90', '#add8e6', '#ffa500']

_HL_NAMES = {
    '#ffff00': N_('Yellow'),
    '#90ee90': N_('Green'),
    '#add8e6': N_('Blue'),
    '#ffa500': N_('Orange'),
}

_HL_SWATCH_CLASS = {
    '#ffff00': 'hl-swatch-yellow',
    '#90ee90': 'hl-swatch-green',
    '#add8e6': 'hl-swatch-blue',
    '#ffa500': 'hl-swatch-orange',
}


class Row(TypedDict, total=False):
    """One line of the Annotations list, whichever page it is on.

    An informal dict until it had crossed three modules — the window builds
    it, `passage_export.build_annotations` reads it, `search_panel` reads it
    — and a third kind of object was about to join. Named here because this
    is the layer that reads every field of it.

    `kind` says which half applies. A mark fills `verse`/`app_verse` and the
    mark vocabulary; an entry fills `id`, `title`, `body`, `date`, `anchors`
    and the provenance; a sermon fills those too, minus `date` and plus
    `idea`, `series` and `preached`. `book` is None ONLY for an entry or a
    sermon with no passage, and that is what sorts it into its own group.
    """
    kind: str                 # 'mark' | 'entry' | 'sermon'
    book: str | None
    chapter: int | None
    app_verse: int | None
    verse: str | None         # the store key; marks only
    highlight: str | None
    underline: bool
    note: str | None
    tags: list[str]
    is_chapter_note: bool
    created: str | None
    modified: str | None
    # Entries and sermons.
    id: str
    title: str
    body: str
    date: str
    anchors: list[dict[str, Any]]
    plan: dict[str, Any] | None
    collect: str | None
    # Sermons only.
    idea: str
    series: dict[str, Any] | None
    preached: list[str]


class _Editor(Gtk.Box):
    """What both editors do the same way.

    `row` is what is open; `populate` sets it and `write` is handed one
    explicitly, because a queued write belongs to the row it was queued for
    and not to whatever is open when the timer fires.
    """

    def __init__(self, *, on_edited, on_store_changed, on_navigate,
                 on_title, on_flush, on_row_changed, on_regroup,
                 reading_module, quote, on_collect=None, on_open_entry=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._edited_cb = on_edited
        self._on_store_changed = on_store_changed
        #: Write anything queued, now — the window owns the timer.
        self._on_flush = on_flush
        #: This row's display has changed; the window owns the list.
        self._on_row_changed = on_row_changed
        #: This row belongs under a different heading now — rebuild the list.
        #: Costlier than `on_row_changed`, so it is called on leaving a field
        #: and not on every keystroke in it.
        self._on_regroup = on_regroup
        self._on_navigate = on_navigate
        self._on_title = on_title
        #: Put collected text into a sermon: (sermon_id, text, anchor). The
        #: window owns the decision of whether that goes through the open
        #: editor or the store.
        self._on_collect = on_collect
        #: Open one journal entry by id. The study door lists the entries
        #: written on the sermon's passages, and an entry is a page: it is
        #: opened, never poured into the manuscript.
        self._on_open_entry = on_open_entry
        self._reading_module = reading_module
        #: `annotations_window.verse_quote`, injected rather than imported —
        #: it resolves the interface language's preferred module, which is
        #: the window's policy and not the editor's.
        self._quote = quote
        self.row: Row | None = None
        #: Gates the edit handlers while `populate` fills the widgets:
        #: set_text() emits `changed`, and without this merely selecting a
        #: row would queue a write.
        self._loading = False
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)

    def _edited(self, *_a):
        if self._loading or self.row is None:
            return
        self._edited_cb(self.row)

    # ── Tag completion ───────────────────────────────────────────────────
    #
    # Tags are one vocabulary across marks and entries (§4: a second
    # organizing axis by the back door is exactly what the feature refuses),
    # and a free-text field is how one vocabulary quietly becomes three —
    # prayer, prayers, Prayer. The tag manager can rename them afterwards;
    # this is what stops them being made. Suggestions come from what is
    # already in use, both stores together, so the reader is offered their
    # own words and never a word list somebody else wrote.

    def _watch_tags(self, entry):
        """Offer the tags already in use as the reader types the last one."""
        self._tag_popover = Gtk.Popover()
        self._tag_popover.set_parent(entry)
        self._tag_popover.set_position(Gtk.PositionType.BOTTOM)
        # NOT autohide: an autohiding popover takes the keyboard the moment
        # it appears, and the field it is helping is the one being typed in.
        self._tag_popover.set_autohide(False)
        self._tag_popover.set_has_arrow(False)
        self._tag_list = Gtk.ListBox()
        self._tag_list.add_css_class('navigation-sidebar')
        self._tag_list.connect('row-activated', self._on_tag_chosen)
        self._tag_popover.set_child(self._tag_list)
        entry.connect('changed', self._on_tags_typed)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_tag_key)
        entry.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect('leave', lambda *_a: self._tag_popover.popdown())
        entry.add_controller(focus)

    @staticmethod
    def _tag_vocabulary():
        """Every tag in use, across all three kinds of writing."""
        return sorted(set(annotations.get_all_tags())
                      | set(journal.all_tags()) | set(sermons.all_tags()))

    @staticmethod
    def _tag_parts(text):
        """(the tags already typed, the one being typed)."""
        parts = text.split(',')
        return [p.strip() for p in parts[:-1] if p.strip()], parts[-1].strip()

    def _tag_suggestions(self, text):
        done, partial = self._tag_parts(text)
        if not partial:
            return []
        lowered = partial.casefold()
        taken = {t.casefold() for t in done}
        hits = [t for t in self._tag_vocabulary()
                if t.casefold().startswith(lowered)
                and t.casefold() not in taken and t.casefold() != lowered]
        # Whole-word matches first, then anything containing the fragment —
        # "yer" should still find "prayer" once nothing starts with it.
        if not hits:
            hits = [t for t in self._tag_vocabulary()
                    if lowered in t.casefold() and t.casefold() not in taken
                    and t.casefold() != lowered]
        return hits[:6]

    def _on_tags_typed(self, entry):
        if self._loading:
            return
        hits = self._tag_suggestions(entry.get_text())
        clear_children(self._tag_list)
        if not hits:
            self._tag_popover.popdown()
            return
        for tag in hits:
            row = Gtk.ListBoxRow()
            row._tag = tag
            label = Gtk.Label(label=tag, xalign=0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            row.set_child(label)
            self._tag_list.append(row)
        self._tag_popover.popup()

    def _on_tag_key(self, _ctl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape and self._tag_popover.get_visible():
            self._tag_popover.popdown()
            return True
        if keyval not in (Gdk.KEY_Tab, Gdk.KEY_Down):
            return False
        first = self._tag_list.get_first_child()
        if first is None or not self._tag_popover.get_visible():
            return False
        self._accept_tag(first._tag)
        return True

    def _on_tag_chosen(self, _list, row):
        self._accept_tag(row._tag)

    def _accept_tag(self, tag):
        """Put `tag` in place of the fragment, ready for the next one."""
        done, _partial = self._tag_parts(self.tags.get_text())
        self.tags.set_text(', '.join(done + [tag]) + ', ')
        self.tags.set_position(-1)
        self._tag_popover.popdown()

    def shutdown(self):
        """Give back anything that outlives the widget tree.

        A `Gtk.Popover` given a parent with `set_parent` is not owned by
        that parent — it has to be unparented by hand, or the field it is
        attached to is finalized with a child still on it.
        """
        if getattr(self, '_tag_popover', None) is not None:
            self._tag_popover.unparent()
            self._tag_popover = None

    def set_writing_mode(self, on):
        """Strip this editor to what you are writing.

        Nothing to strip on a mark: its note is a few lines beside a verse,
        not a page. The window tells every editor rather than only the open
        one, so this has to exist on all of them.
        """

    def _watch_focus(self, widget):
        """Flush a pending write when `widget` loses the keyboard.

        Leaving a field is the reader saying they are done with it, and it
        should not take another second to be true.
        """
        focus = Gtk.EventControllerFocus()
        focus.connect('leave', lambda _c: self._on_flush())
        widget.add_controller(focus)

    def _verse_text(self, book, chapter, verse):
        """The verse's own words, in the translation that fits the interface
        language, falling back to the one the reader has open.

        Both editors quote, and both fall back twice over: when none of the
        preferred modules is installed, and when the one that is cannot
        render this verse — BSB carries no deuterocanon, so a note on Sirach
        would otherwise come up blank with the words plainly on the page
        behind it.
        """
        reading = None
        if self._reading_module is not None:
            try:
                reading = self._reading_module()
            except Exception:
                reading = None
        for module in dict.fromkeys(m for m in (self._quote_module(), reading)
                                    if m):
            text = self._quote(module, book, chapter, verse)
            if text:
                return text
        return ''

    def _quote_module(self):
        # Imported at call time, not at module scope: the window imports this
        # file, so a top-level import back would be a cycle.
        from annotations_window import quote_module
        return quote_module()

    @staticmethod
    def _edited_label(entry):
        from annotations_window import _edited_label
        return _edited_label(entry)

    @staticmethod
    def _anchor_label(entry):
        from annotations_window import _anchor_label
        return _anchor_label(entry)

    def _ref_chip(self, label, book, chapter, verse):
        """An outlined chip that goes to a passage. Filled means your word,
        outlined means Scripture's place — the same rule on both pages."""
        btn = Gtk.Button(label=label)
        btn.add_css_class('ref-chip')
        btn.set_tooltip_text(_('Go to {ref}').format(ref=label))
        btn.connect('clicked',
                    lambda _b: self._on_navigate(book, chapter, verse))
        return btn

    def _mark_as_prose(self, e):
        """(text, anchor) for one mark, as a manuscript quotes it.

        The verse's own words, the reader's note under them, then the
        reference — which the body's parser turns back into a link, because
        it is spelled the way the reader's language spells it. Shared,
        because a mark pushed in from the reading page and the same mark
        pulled in from the sermon's own study door must arrive identical.
        """
        is_cn = bool(e.get('is_chapter_note'))
        ref = f'{book_label(e["book"])} {e["chapter"]}'
        if not is_cn:
            ref = f'{ref}:{e["app_verse"]}'
        parts = []
        words = '' if is_cn else self._verse_text(
            e['book'], e['chapter'], e['verse'])
        if words:
            parts.append(f'> {words} — {ref}')
        note = ' '.join((e.get('note') or '').split())
        if note:
            parts.append(note if words else f'{note} — {ref}')
        if not parts:
            parts.append(ref)
        anchor = {'book': e['book'], 'chapter': e['chapter'],
                  'verses': [] if is_cn or e.get('app_verse') is None
                  else [e['app_verse']]}
        return '\n\n'.join(parts), anchor

    @staticmethod
    def _show_quote(label, text):
        label.set_visible(False)
        if not text:
            return
        label.set_text(text)
        label.set_tooltip_text(text)
        set_accessible_label(label, text)
        label.set_visible(True)


class MarkEditor(_Editor):
    """A highlight, an underline, a note and its tags, on one verse.

    Unchanged in this move except for what it no longer reaches for: it is
    handed the row and the callbacks and owns nothing else.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self._build()

    def _build(self):
        box = self

        # Where the reference sits: an outlined chip, the same vocabulary an
        # entry's anchors use. It replaces a lone "Go to verse" button that
        # sat under the note in dead space — one way of saying "go to
        # Scripture", on both pages.
        self._go_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=4)
        self._go_box.set_halign(Gtk.Align.START)

        # The reference and the date live in the content page's header
        # (the window's header). The body opens with the verse itself: a note
        # about words you cannot see is a note you have to go and look up.
        self._verse = Gtk.Label(xalign=0)
        self._verse.set_wrap(True)
        # Four lines, then an ellipsis. Measured: Esther 8:9, the longest verse
        # in the canon, wants 218px of this pane when the window is collapsed —
        # it would push the note field, which is the thing being written in,
        # off the bottom. Capped it is a steady 70px at every width, and the
        # whole verse stays one hover (and one screen-reader stop) away.
        self._verse.set_lines(4)
        self._verse.set_ellipsize(Pango.EllipsizeMode.END)
        self._verse.add_css_class('journal-verse')
        self._verse.set_visible(False)
        box.append(self._verse)
        # Under the quote, not above it: at the top the chip sat 40px below a
        # header saying the same words and read as an echo. Here it reads as
        # "these words, and where they are".
        box.append(self._go_box)

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
            # Muted initial as a non-hue (colorblind-safe) cue — its own string
            # per language, not the name's first letter (see highlight_letter).
            letter = Gtk.Label(label=annotation_dialogs.highlight_letter(
                stored_color))
            letter.add_css_class('hl-letter')
            btn.set_child(letter)
            btn.set_tooltip_text(name)
            set_accessible_label(btn, name)
            btn.connect('clicked', self._on_hl_click, stored_color)
            swatch_box.append(btn)
            self._hl_buttons[stored_color] = btn

        clear_btn = Gtk.Button(icon_name='scriptura-edit-clear-symbolic')
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

        # The order is the entry editor's, and the two panes now read as one
        # room: what you came to write in comes BEFORE the tags, not behind
        # them. It keeps ONE caption, which the entry body does not need —
        # an unlabelled block of prose directly under a quoted verse is
        # ambiguous, where an entry's body follows a title the reader has
        # just typed into. No Save button either way: both write themselves
        # once typing pauses, as the highlight and underline always have.
        self.note = Gtk.TextView()
        self.note.set_wrap_mode(Gtk.WrapMode.WORD)
        self.note.set_left_margin(12)
        self.note.set_right_margin(12)
        self.note.set_top_margin(10)
        self.note.set_bottom_margin(12)
        self.note.add_css_class('journal-note-field')
        self.note.get_buffer().connect('changed', self._edited)
        self._watch_focus(self.note)

        note_lbl = Gtk.Label(label=_('Note'), xalign=0)
        note_lbl.add_css_class('dim-label')
        note_lbl.add_css_class('caption')
        box.append(note_lbl)

        # The same sheet the entry body sits on next door, without the
        # formatting row: a mark's note is a sentence or two, not a page, and
        # nothing renders its markup. One idiom for a field you write in —
        # which is the rule that took the card OFF both of them last pass,
        # and the rule that puts the edge back on both of them now.
        note_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        note_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        note_scroll.set_child(self.note)
        paper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        paper.add_css_class('journal-paper')
        paper.set_vexpand(True)
        paper.append(note_scroll)
        box.append(paper)

        # Into the sermon being written. A mark is where "this belongs in
        # Sunday's manuscript" is actually thought, and the note goes with
        # the verse — which is the one thing the reading page's own door
        # cannot do, because there the note is not on screen.
        self._collect_btn = Gtk.Button()
        self._collect_btn.add_css_class('flat')
        self._collect_btn.set_halign(Gtk.Align.START)
        self._collect_btn.set_visible(False)
        self._collect_btn.connect('clicked', self._on_collect_clicked)
        box.append(self._collect_btn)

        tags_lbl = Gtk.Label(label=_('Tags (comma-separated)'), xalign=0)
        tags_lbl.add_css_class('dim-label')
        tags_lbl.add_css_class('caption')
        box.append(tags_lbl)
        self.tags = Gtk.Entry()
        self.tags.set_placeholder_text(_('e.g. prayer, faith, covenant'))
        self.tags.connect('changed', self._edited)
        self._watch_focus(self.tags)
        self._watch_tags(self.tags)
        box.append(self.tags)


    def populate(self, entry):
        self.row = entry
        is_cn = bool(entry.get('is_chapter_note'))

        if is_cn:
            ref = _('{ref} — Chapter Note').format(
                ref=f'{book_label(entry["book"])} {entry["chapter"]}')
        else:
            ref = (f'{book_label(entry["book"])} {entry["chapter"]}'
                   f':{entry["app_verse"]}')
        self._on_title(ref, self._edited_label(entry))
        clear_children(self._go_box)
        if not is_cn:
            self._go_box.append(self._ref_chip(
                ref, entry['book'], entry['chapter'], entry['app_verse'] or 1))
        self._show_verse(entry)

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

        self._loading = True
        try:
            self.tags.set_text(', '.join(entry.get('tags', []) or []))
            self.note.get_buffer().set_text(entry.get('note') or '')
        finally:
            self._loading = False
        self._sync_collect_button()

    def _sync_collect_button(self):
        """Offered only when there is a sermon to add to. A door to nowhere
        is worse than no door."""
        target = sermons.most_recent() if self._on_collect else None
        self._collect_target = target['id'] if target else None
        self._collect_btn.set_visible(target is not None)
        if target is not None:
            label = _('Add to “{title}”').format(
                title=target['title'] or _('Untitled sermon'))
            self._collect_btn.set_label(label)
            set_accessible_label(self._collect_btn, label)

    def _on_collect_clicked(self, _btn):
        e = self.row
        if not e or not getattr(self, '_collect_target', None):
            return
        text, anchor = self._mark_as_prose(e)
        self._on_collect(self._collect_target, text, anchor)

    def _show_verse(self, entry):
        """Quote the verse the note is about.

        A chapter note has no single verse; the label just stays hidden, and
        the pane does not explain its absence.
        """
        if entry.get('is_chapter_note'):
            self._verse.set_visible(False)
            return
        self._show_quote(self._verse, self._verse_text(
            entry['book'], entry['chapter'], entry['verse']))

    def _on_hl_click(self, _btn, color):
        e = self.row
        if not e or e.get('is_chapter_note'):
            return
        annotations.save_highlight(
            None, e['book'], e['chapter'], e['verse'], color)
        e['highlight'] = color
        # Swatch selected styling
        for c, btn in self._hl_buttons.items():
            if c == color:
                btn.add_css_class('selected')
            else:
                btn.remove_css_class('selected')
        # The row's colour strip follows, but the window owns the row.
        self._on_row_changed(e)
        self._on_store_changed(e['book'], e['chapter'], e['verse'])

    def _on_ul_toggled(self, btn):
        e = self.row
        if not e or e.get('is_chapter_note'):
            return
        enabled = btn.get_active()
        annotations.save_underline(
            None, e['book'], e['chapter'], e['verse'], enabled)
        e['underline'] = enabled
        self._on_store_changed(e['book'], e['chapter'], e['verse'])

    def write(self, e):
        """Write the open note and tags, then patch the row that shows them.

        Deliberately no _reload(): rebuilding the list on a timer would throw
        away every row while the reader is typing into one of them, and under
        the "Recently edited" sort it would walk the open row up the sidebar
        under the cursor. The row is refilled in place instead — the same
        thing _on_hl_click does for the colour strip. The list is left
        momentarily out of that sort order, which is correct; it settles on
        the next reload.
        """
        buf = self.note.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        text = text.rstrip() or None
        raw_tags = [t.strip() for t in self.tags.get_text().split(',')
                    if t.strip()]

        if e.get('is_chapter_note'):
            annotations.save_chapter_note(
                None, e['book'], e['chapter'], text or '')
            annotations.save_chapter_note_tags(
                None, e['book'], e['chapter'], raw_tags)
        else:
            annotations.save_note(
                None, e['book'], e['chapter'], e['verse'], text)
            annotations.save_tags(
                None, e['book'], e['chapter'], e['verse'], raw_tags)

        e['note'] = text
        e['tags'] = raw_tags
        e['modified'] = annotations._now()
        self._on_row_changed(e)

        v = None if e.get('is_chapter_note') else e['verse']
        self._on_store_changed(e['book'], e['chapter'], v)


#: The journal's formatting row: glyph, name, and what the button writes.
#: Every one of them types exactly what the reader could have typed — the
#: same Markdown subset journal_markup renders — so the toolbar teaches the
#: notation rather than hiding it, and an entry written by hand and one
#: written by button are the same file. `wrap` goes around the selection;
#: `prefix` goes on the front of every line it touches.
#: The body's own left margin. Every paragraph tag below has to carry it:
#: a tag's `left-margin` REPLACES the view's rather than adding to it, so
#: when this went from 2 to 12 with the sheet, the quote's 22 and the list's
#: 18 quietly stopped being indents of 20 and 16 and became 10 and 6. The
#: blockquote and the list flattened out and nobody's test could see it.
_BODY_MARGIN = 12

_TOOLS = [
    ('scriptura-format-text-bold-symbolic', N_('Bold'), 'wrap', '**'),
    ('scriptura-format-text-italic-symbolic', N_('Italic'), 'wrap', '*'),
    ('scriptura-format-text-heading-symbolic', N_('Heading'), 'prefix', '# '),
    ('scriptura-format-text-quote-symbolic', N_('Quote'), 'prefix', '> '),
    ('scriptura-view-list-bullet-symbolic', N_('Bullet list'),
     'prefix', '- '),
    ('scriptura-view-list-ordered-symbolic', N_('Numbered list'),
     'number', ''),
]


class _ProseEditor(_Editor):
    """What a journal entry and a sermon manuscript both are.

    A title, however many passages it was written against, a body carrying
    the Markdown subset and its reference links, and tags. No highlight row
    — hue is a mark's language — and no store: the two subclasses differ in
    the fields above the body (`_build_head`), in what they put in the pane
    header, and in what they write.
    """

    #: What the subclasses say in the places this class draws for them.
    title_placeholder = N_('Untitled entry')
    body_hint = N_('Write your entry…')
    tags_example = N_('e.g. prayer, faith, covenant')
    #: The pane header when there is no passage to name.
    header_fallback = N_('Journal')

    def __init__(self, **kw):
        super().__init__(**kw)
        #: The reference scan is the one part of restyling too heavy for the
        #: keystroke path, so it rides its own, shorter debounce.
        self._restyle = Autosave(self._restyle_references,
                                 delay_ms=motion.RESTYLE_DELAY_MS)
        self.refs = []
        self._build()

    def shutdown(self):
        """Never leave a restyle armed on an editor going away."""
        self._restyle.cancel()
        super().shutdown()

    def _build(self):
        """The prose side of the pane, head to foot."""
        box = self

        # The title is not a form field — no frame, set in the reading serif
        # a step above body size. The Today page's law, one room over.
        self.title = Gtk.Entry()
        self.title.set_has_frame(False)
        self.title.set_placeholder_text(_(self.title_placeholder))
        self.title.add_css_class('journal-entry-heading')
        self.title.connect('changed', self._edited)
        self._watch_focus(self.title)
        box.append(self.title)

        # ── One line of metadata, not four ──────────────────────────────
        # Each fact used to take a whole row plus 12px of air: the day or the
        # series, the preaching dates, the passages. Measured on his window
        # that was 125px of the 318px standing between the title bar and the
        # first line you can write on — and the pane header two inches above
        # already said the series and the reference. They are all short, so
        # they share one line and wrap onto a second only when they must.
        #
        # A WrapBox and not a Box or a FlowBox. A flow box is a GRID: it
        # stretches every cell to fill its line even with homogeneous=False,
        # which put a 157px chip in a 177px cell and bled its hover 18px past
        # itself. A plain Box cannot wrap, so a long list of chips would force
        # the whole editor wider than the window. A wrap box packs at natural
        # width and folds — which is what a row of small facts wants.
        self._meta_row = Adw.WrapBox(child_spacing=self.META_GAP, line_spacing=6)
        self._meta_row.add_css_class('entry-meta')

        # Built before the row is placed, because a head puts its own groups
        # INTO the row and anything that belongs on its own line — a sermon's
        # big idea is a standfirst, not a fact — onto the page above it.
        self._build_head(box)

        # Anchor chips: outlined, where a tag chip is filled. Filled means
        # your word, outlined means Scripture's place. Last on the line,
        # because a passage is the fact most worth reading there.
        self._anchor_box = Adw.WrapBox(child_spacing=4, line_spacing=2)
        self._meta_row.append(self._anchor_box)
        self._build_meta_tail()
        box.append(self._meta_row)

        self._verse = Gtk.Label(xalign=0)
        self._verse.set_wrap(True)
        self._verse.set_lines(4)
        self._verse.set_ellipsize(Pango.EllipsizeMode.END)
        self._verse.add_css_class('journal-verse')
        self._verse.set_visible(False)
        box.append(self._verse)

        # A text view has no placeholder, and an empty bordered sheet with
        # nothing in it says less than an empty line of window did.
        self._body_hint = Gtk.Label(label=_(self.body_hint),
                                    xalign=0, yalign=0)
        self._body_hint.add_css_class('dim-label')
        self._body_hint.add_css_class('journal-entry-body')
        self._body_hint.set_margin_start(13)
        self._body_hint.set_margin_top(10)
        # Clicks belong to the view underneath, not to the words on top.
        self._body_hint.set_can_target(False)
        # Built BEFORE the buffer's handlers are connected: `_restyle_body`
        # reads it on the first `changed`, and a widget that answers only
        # after the signals are live is a crash waiting for the first path
        # that sets text a line earlier.

        self.body = Gtk.TextView()
        self.body.set_wrap_mode(Gtk.WrapMode.WORD)
        self.body.set_left_margin(_BODY_MARGIN)
        self.body.set_right_margin(_BODY_MARGIN)
        self.body.set_top_margin(10)
        self.body.set_bottom_margin(12)
        self.body.add_css_class('journal-entry-body')
        self.body.get_buffer().connect('changed', self._edited)
        self.body.get_buffer().connect('changed', self._restyle_body)
        #: Set while the list continuation writes its own newline, so that
        #: write is not read as another Enter.
        self._continuing = False
        self.body.get_buffer().connect('insert-text', self._on_body_insert)
        self._watch_focus(self.body)
        self._install_markup_tags(self.body.get_buffer())
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect('released', self._on_body_click)
        self.body.add_controller(click)
        # The tip belongs to the LINKS, not to the page. As a plain
        # tooltip it fired wherever the pointer rested in the body — a box
        # over the words you are writing, saying something that is only
        # true of a few of them.
        self.body.set_has_tooltip(True)
        self.body.connect('query-tooltip', self._on_body_tooltip)
        self.body.add_controller(self._body_shortcuts())

        body_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        body_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body_scroll.set_child(self.body)

        page = Gtk.Overlay()
        page.set_child(body_scroll)
        page.add_overlay(self._body_hint)

        # ── The sheet ───────────────────────────────────────────────────────
        # The first pass put the body flat on the window, arguing that a
        # rounded bordered box is the idiom the reading surface refuses. It
        # is — for READING. Writing is the other thing: a page needs an edge,
        # or there is nothing to say where the writing goes, and the pane
        # read as unfinished rather than quiet. The tools ride at its head,
        # where every editor the reader already uses keeps them.
        paper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        paper.add_css_class('journal-paper')
        paper.set_vexpand(True)
        self._tools = self._build_tools()
        self._tools_rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        paper.append(self._tools)
        paper.append(self._tools_rule)
        paper.append(page)
        box.append(paper)

        # The tags caption and the word count share a line: the count is
        # worth having for sermon length and is worth nothing at all as a
        # score, so it goes in the quietest place that already exists rather
        # than under the writing, where it would be read as one. Nothing is
        # shown at all until there are words.
        caption = self._tags_caption = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tags_lbl = Gtk.Label(label=_('Tags (comma-separated)'), xalign=0)
        tags_lbl.add_css_class('dim-label')
        tags_lbl.add_css_class('caption')
        tags_lbl.set_hexpand(True)
        caption.append(tags_lbl)
        self._words = Gtk.Label(xalign=1)
        self._words.add_css_class('dim-label')
        self._words.add_css_class('caption')
        self._words.set_visible(False)
        self._describe_length(self._words)
        caption.append(self._words)
        box.append(caption)
        self.tags = Gtk.Entry()
        self.tags.set_has_frame(False)
        self.tags.add_css_class('journal-tags-field')
        self.tags.set_placeholder_text(_(self.tags_example))
        self.tags.connect('changed', self._edited)
        self._watch_focus(self.tags)
        self._watch_tags(self.tags)
        box.append(self.tags)

    def _build_head(self, box):
        """What this kind of writing carries besides its passages.

        Facts go into `self._meta_row`, which is already built; only something
        that has to hold a line of its own belongs on `box`.
        """

    def _describe_length(self, label):
        """Say what the length caption means, where it means anything more
        than a count."""

    def _build_meta_tail(self):
        """Anything that belongs on the metadata line AFTER the passages.

        A second hook only because the passages are built by the base and the
        heads by the subclasses: without it a sermon's least-asked-for fact
        sat ahead of the one worth reading.
        """

    def _writing_mode_chrome(self):
        """Everything on this page that is not the title or the paper."""
        return [self._meta_row, self._verse, self._tools, self._tools_rule,
                self._tags_caption, self.tags]

    def set_writing_mode(self, on):
        """Leave the title and the sheet; take everything else away.

        The visibility each widget had is remembered rather than assumed:
        `_verse` is hidden for an entry with no passage, and restoring the
        page by setting everything visible would conjure a quote for it.
        """
        if on:
            self._pre_writing = {w: w.get_visible()
                                 for w in self._writing_mode_chrome()}
            for w in self._pre_writing:
                w.set_visible(False)
        else:
            for w, was in getattr(self, '_pre_writing', {}).items():
                w.set_visible(was)
            self._pre_writing = {}

    #: Between two groups of facts on the metadata line. Wide, because it is
    #: the only thing dividing them: middots were tried and struck out. A
    #: wrap box breaks between its own children, so a loose dot stayed at the
    #: end of the line it was meant to open ("Part 1 ·" with nothing after
    #: it); bound to the group instead, it led the next line — and at the
    #: width he actually writes at, every group takes a line of its own, so
    #: all the dots did was sit in the left margin looking like bullets.
    #: Space says "different group" without claiming to be a glyph.
    META_GAP = 22

    def _build_tools(self):
        """The formatting row across the head of the sheet."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        bar.add_css_class('journal-tools')
        accel = {'**': _('Bold (Ctrl+B)'), '*': _('Italic (Ctrl+I)')}
        for icon, label, kind, marker in _TOOLS:
            btn = Gtk.Button(icon_name=icon)
            btn.add_css_class('flat')
            btn.set_tooltip_text(accel.get(marker) or _(label))
            set_accessible_label(btn, _(label))
            btn.connect('clicked', self._on_tool, kind, marker)
            bar.append(btn)
        return bar

    def _body_shortcuts(self):
        """Ctrl+B and Ctrl+I, local to the body.

        Local scope: they mean nothing outside a text buffer, and the
        window's own accelerators must keep working everywhere else in it.
        """
        ctl = Gtk.ShortcutController()
        ctl.set_scope(Gtk.ShortcutScope.LOCAL)
        for keys, marker in (('<Control>b', '**'), ('<Control>i', '*')):
            ctl.add_shortcut(Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(keys),
                action=Gtk.CallbackAction.new(
                    lambda _w, _a, m=marker: self._wrap(m) or True)))
        return ctl

    def _on_tool(self, _btn, kind, marker):
        getattr(self, '_' + kind)(marker)

    def _wrap(self, marker):
        """Put `marker` either side of the selection, or take it off again.

        With nothing selected it writes the pair and leaves the cursor
        between them, which is how you start a bold word rather than
        finish one.
        """
        buf = self.body.get_buffer()
        # PyGObject's override returns the pair, or an empty tuple when
        # nothing is selected — not the (ok, start, end) the C call has.
        bounds = buf.get_selection_bounds()
        a, b = bounds if bounds else 2 * (
            buf.get_iter_at_mark(buf.get_insert()),)
        start, end = a.get_offset(), b.get_offset()
        text = buf.get_text(a, b, False)
        # A drag takes the space after a word with it more often than not, and
        # '**word **' is notation the renderer will not read back: the pair
        # has to close against a non-space. So the markers go around what was
        # selected LESS its outer space, and the press does something.
        if text.strip():
            start += len(text) - len(text.lstrip())
            end -= len(text) - len(text.rstrip())
            text = text.strip()
        n = len(marker)
        # One press, one undo. Without the grouping the two inserts below
        # are two steps, and Ctrl+Z leaves half a pair of markers behind.
        buf.begin_user_action()
        if self._between(buf, start - n, start) == marker \
                and self._between(buf, end, end + n) == marker:
            # The usual second press: a wrap leaves the WORD selected, so
            # the markers are just outside it. Far end first, as below.
            buf.delete(buf.get_iter_at_offset(end),
                       buf.get_iter_at_offset(end + n))
            buf.delete(buf.get_iter_at_offset(start - n),
                       buf.get_iter_at_offset(start))
            self._select(start - n, end - n)
        elif len(text) > 2 * n and text.startswith(marker) \
                and text.endswith(marker) \
                and not text[n:-n].startswith('*') \
                and not text[n:-n].endswith('*'):
            # The markers were selected along with the word. The star test
            # keeps italic from chopping '**bold**' into a dangling pair.
            inner = text[n:-n]
            buf.delete(buf.get_iter_at_offset(start),
                       buf.get_iter_at_offset(end))
            buf.insert(buf.get_iter_at_offset(start), inner)
            self._select(start, start + len(inner))
        else:
            # The far end first: inserting there leaves every offset before
            # it where it was.
            buf.insert(buf.get_iter_at_offset(end), marker)
            buf.insert(buf.get_iter_at_offset(start), marker)
            self._select(start + n, end + n)
        buf.end_user_action()
        self.body.grab_focus()

    def _prefix(self, marker):
        """Toggle a line marker on every line the selection touches.

        All or nothing: if any line in the range lacks it, the whole range
        gets it. That is what makes one press turn four lines into a list
        and the next press turn them back.
        """
        buf = self.body.get_buffer()
        # PyGObject's override returns the pair, or an empty tuple when
        # nothing is selected — not the (ok, start, end) the C call has.
        bounds = buf.get_selection_bounds()
        a, b = bounds if bounds else 2 * (
            buf.get_iter_at_mark(buf.get_insert()),)
        first, last = self._selected_lines(a, b)
        adding = not all(self._line_text(buf, n).startswith(marker)
                         for n in range(first, last + 1))
        # One press, one undo — four lines marked is not four steps back.
        buf.begin_user_action()
        # Backwards, so a line's own offset is still good when it comes up.
        for n in range(last, first - 1, -1):
            if adding:
                self._set_marker(buf, n, marker)
            else:
                at = buf.get_iter_at_line(n)[1]
                stop = buf.get_iter_at_line(n)[1]
                stop.forward_chars(len(marker))
                buf.delete(at, stop)
        buf.end_user_action()
        self.body.grab_focus()

    def _between(self, buf, start, end):
        """The text between two offsets, clamped to the buffer."""
        if start < 0 or end > buf.get_char_count():
            return ''
        return buf.get_text(buf.get_iter_at_offset(start),
                            buf.get_iter_at_offset(end), False)

    def _number(self, _marker=''):
        """Number the lines the selection touches, or take the numbers off.

        Not a prefix toggle like the others: the marker is different on
        every line, and a list that says 1. 1. 1. is not a numbered list.
        Re-numbering from 1 each time is also what makes it safe to press
        twice on a range that was already numbered from somewhere else.
        """
        buf = self.body.get_buffer()
        bounds = buf.get_selection_bounds()
        a, b = bounds if bounds else 2 * (
            buf.get_iter_at_mark(buf.get_insert()),)
        first, last = self._selected_lines(a, b)
        lines = [self._line_text(buf, n) for n in range(first, last + 1)]
        numbered = [journal_markup.numbered_marker(line) for line in lines]
        adding = not all(numbered)
        buf.begin_user_action()
        for offset in reversed(range(len(lines))):
            n = first + offset
            if adding:
                self._set_marker(buf, n, f'{offset + 1}. ')
            else:
                at = buf.get_iter_at_line(n)[1]
                stop = buf.get_iter_at_line(n)[1]
                stop.forward_chars(len(numbered[offset]))
                buf.delete(at, stop)
        buf.end_user_action()
        self.body.grab_focus()

    @staticmethod
    def _selected_lines(a, b):
        """The lines a selection actually touches.

        A drag that ends at the START of a line has not reached into it, and
        a line that marks itself a list while nothing in it looks selected is
        a press the reader undoes rather than keeps.
        """
        first, last = a.get_line(), b.get_line()
        if last > first and b.get_line_offset() == 0:
            last -= 1
        return first, last

    def _set_marker(self, buf, line, marker):
        """Open `line` with `marker`, in place of any it already carries.

        A line holds one whole-line role. Left to stack, the bullet pressed on
        a numbered line wrote '- 1. one' — a bullet whose text reads '1. one',
        which is not what either button was asked for.
        """
        existing = journal_markup.line_marker(self._line_text(buf, line))
        if existing == marker:
            return
        at = buf.get_iter_at_line(line)[1]
        if existing:
            stop = buf.get_iter_at_line(line)[1]
            stop.forward_chars(len(existing))
            buf.delete(at, stop)
            at = buf.get_iter_at_line(line)[1]
        buf.insert(at, marker)

    # ── Enter, inside a list ─────────────────────────────────────────────
    #
    # The one keystroke the notation cannot teach by being visible. A reader
    # who presses the numbered-list button and types an item expects the next
    # line to be the next item — every editor they have ever used does this —
    # and what they got was a bare line, the list broken, and the numbering
    # left to them. The marker the toolbar writes is the marker Enter carries
    # on.
    #
    # Hooked on the BUFFER and not on a key. A key controller on the view
    # would have to outrun the view's own — and, before it, the input
    # method's — to be sure of seeing Return at all; a newline arriving in
    # the buffer is the same event with none of that racing, whoever made it.

    def _on_body_insert(self, buf, at, text, _length):
        """Continue the list the newline was typed in.

        `insert-text` is RUN_LAST, so this runs BEFORE the newline goes in:
        stopping the emission leaves the line exactly as the reader sees it,
        and what is written instead is the newline plus the next marker, as
        one undo step.
        """
        if self._loading or self._continuing or text != '\n':
            return
        line_no, column = at.get_line(), at.get_line_offset()
        line = self._line_text(buf, line_no)
        marker = journal_markup.list_marker(line)
        if not marker or column < len(marker):
            return          # not a list, or the caret is inside the marker
        buf.stop_emission_by_name('insert-text')
        self._continuing = True
        buf.begin_user_action()
        try:
            if line[len(marker):].strip():
                buf.insert(at, '\n' + journal_markup.next_marker(line))
                self._renumber(buf, line_no)
            else:
                # An empty item ends the list. Pressing Enter twice is how
                # every editor says "done", and a marker on a line nobody
                # wrote in is litter the reader has to clear by hand.
                start = buf.get_iter_at_line(line_no)[1]
                buf.delete(start, buf.get_iter_at_offset(
                    start.get_offset() + len(line)))
        finally:
            buf.end_user_action()
            self._continuing = False

    def _renumber(self, buf, line_no):
        """Renumber the run of numbered lines `line_no` belongs to.

        Only the numbers change, and only where they are wrong, so the caret
        on the line just made keeps its place.
        """
        if not journal_markup.numbered_marker(self._line_text(buf, line_no)):
            return
        first, last, total = line_no, line_no, buf.get_line_count()
        while first > 0 and journal_markup.numbered_marker(
                self._line_text(buf, first - 1)):
            first -= 1
        while last + 1 < total and journal_markup.numbered_marker(
                self._line_text(buf, last + 1)):
            last += 1
        lines = [self._line_text(buf, n) for n in range(first, last + 1)]
        for n, wanted in zip(range(first, last + 1),
                             journal_markup.renumber(lines)):
            self._set_marker(buf, n,
                             journal_markup.numbered_marker(wanted))

    def _select(self, start, end):
        buf = self.body.get_buffer()
        buf.select_range(buf.get_iter_at_offset(start),
                         buf.get_iter_at_offset(end))

    @staticmethod
    def _line_text(buf, line):
        start = buf.get_iter_at_line(line)[1]
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return buf.get_text(start, end, False)

    def populate(self, entry):
        """Fill the shared fields. A subclass fills its own, inside the
        `_loading` gate this opens and closes for it."""
        self.row = entry
        self._retitle_pane()

        self._loading = True
        try:
            self.title.set_text(entry.get('title') or '')
            self.body.get_buffer().set_text(entry.get('body') or '')
            self.tags.set_text(', '.join(entry.get('tags') or []))
            self._populate_head(entry)
        finally:
            self._loading = False

        # set_text above already fired `changed`, so the markup is applied
        # and a reference pass is queued; run it now instead, so an entry
        # opens with its links rather than growing them a beat later.
        self._restyle.cancel()
        self._restyle_references()
        self._fill_anchors()
        self._show_verse(entry)

    def _populate_head(self, entry):
        """The subclass's own fields. Called with `_loading` set."""

    def _retitle_pane(self):
        """The header says WHERE, the pane says what was written — the same
        division the mark editor keeps. Putting the title up here too would
        print it twice, an inch apart."""
        self._on_title(self._anchor_label(self.row) or _(self.header_fallback),
                       '')

    def _install_markup_tags(self, buf):
        """The subset's tags, created once on the body buffer.

        `left-margin` on a tag REPLACES the view's rather than adding to it
        (the view sets 2), so the quote and bullet values below are absolute
        indents, not offsets from it.
        """
        table = buf.get_tag_table()
        if table.lookup('md-strong') is not None:
            return
        buf.create_tag('md-strong', weight=Pango.Weight.BOLD)
        buf.create_tag('md-emphasis', style=Pango.Style.ITALIC)
        buf.create_tag('md-heading', weight=Pango.Weight.BOLD, scale=1.25,
                       pixels_above_lines=12, pixels_below_lines=4)
        # A quoted passage should look quoted — that is the whole reason §6.5
        # asked for any of this, and italic-plus-a-hair was not it. A block:
        # set in, held off the paragraphs either side, and standing on a
        # faint field of its own (a text tag cannot draw the rule a quote
        # would carry in print; `paragraph-background` is the one block-level
        # mark it has). The tint is minted in _dim_markers, from live ink.
        buf.create_tag('md-quote', style=Pango.Style.ITALIC,
                       left_margin=_BODY_MARGIN + 20,
                       pixels_above_lines=6, pixels_below_lines=6)
        # A hanging indent, so a list item that wraps aligns under its own
        # words rather than under its marker.
        buf.create_tag('md-bullet', left_margin=_BODY_MARGIN + 22,
                       indent=-14)
        # The syntax stays visible and editable, but recedes. Nothing is
        # hidden from the person who typed it. GtkTextTag has no alpha
        # property, so the colour is the view's own ink knocked back — read
        # from the widget at restyle time, which is how it follows the theme.
        # Smaller as well as dimmer. At full size a '#' is the largest
        # glyph on its own heading and a '**' pair brackets the word like
        # scaffolding; at 0.8 they read as notation beside the words rather
        # than as words.
        buf.create_tag('md-marker', scale=0.8)
        # A reference is a door, so it looks like one: the accent ink and an
        # underline, the app's own link vocabulary.
        buf.create_tag('md-ref', underline=Pango.Underline.SINGLE)

    def _count_words(self, buf):
        """How long the entry is, for the one reader who needs to know.

        `str.split()` rather than a word-boundary regex: it counts runs of
        non-space, which is what a preacher timing a manuscript means by a
        word, and it does not disagree with itself across languages.

        The notation is taken off first. A '- ' and a '1. ' and a '**' pair
        are not words — measured on a list-heavy 1,080-word manuscript the
        raw split read 1,140, which is half a minute of preaching that is
        not there. `plain` is the same pass the list previews use, so the
        count can never disagree with the styling about what is notation;
        it costs 0.5ms on that manuscript, which is why this rides the
        reference debounce and not the keystroke.
        """
        text = buf.get_text(*buf.get_bounds(), False)
        words = len(journal_markup.plain(text).split())
        self._words.set_visible(bool(words))
        if words:
            self._words.set_text(self._length_label(words))

    @staticmethod
    def _length_label(words):
        """What the caption says about a body that long."""
        return ngettext('{n} word', '{n} words', words).format(n=words)

    def _restyle_body(self, buf):
        """Re-apply the subset across the whole body.

        Whole-buffer rather than around the edit: a '*' typed on line one
        changes what line one means, and the paragraph that closes a
        blockquote three lines down is not adjacent to the keystroke. A
        journal entry is a page, so this is a few kilobytes of pure-Python
        regex per keystroke — measured well under a frame.
        """
        self._body_hint.set_visible(buf.get_char_count() == 0)
        self._dim_markers(buf)
        start, end = buf.get_bounds()
        for tag in ('md-strong', 'md-emphasis', 'md-heading', 'md-quote',
                    'md-bullet', 'md-marker'):
            buf.remove_tag_by_name(tag, start, end)
        text = buf.get_text(start, end, False)
        for a, b, tag in journal_markup.spans(text):
            buf.apply_tag_by_name(tag, buf.get_iter_at_offset(a),
                                  buf.get_iter_at_offset(b))
        self._restyle.schedule()

    @staticmethod
    def _names():
        from annotations_window import reference_names
        return reference_names()

    def _restyle_references(self):
        """Mark the scripture references in the body.

        Measured at ~134 book spellings against every position: 0.8ms on a
        page but 10ms on a sermon-length entry, which is why it is not on the
        keystroke path with the rest of the styling.
        """
        buf = self.body.get_buffer()
        self._count_words(buf)
        start, end = buf.get_bounds()
        buf.remove_tag_by_name('md-ref', start, end)
        text = buf.get_text(start, end, False)
        # Kept so a click can be answered without parsing again, and so the
        # answer is the one the reader can see underlined.
        self.refs = journal_markup.reference_spans(text, self._names())
        for a, b, _book, _ch, _v in self.refs:
            buf.apply_tag_by_name('md-ref', buf.get_iter_at_offset(a),
                                  buf.get_iter_at_offset(b))

    def _on_body_click(self, gesture, n_press, x, y):
        """Ctrl+click on a reference goes there.

        **Ctrl is required, and it has to be.** The body is an editable
        field that is never not editable — there is no read-only mode, since
        autosave removed the view/edit split — so a plain click has to place
        the cursor. Without the modifier a reader could not put the caret
        inside "John 3:16" to fix a typo without the window navigating away
        from what they were writing.
        """
        if n_press != 1 or not self.refs:
            return
        state = gesture.get_current_event_state()
        if not (state & Gdk.ModifierType.CONTROL_MASK):
            return
        if self.body.get_buffer().get_has_selection():
            return
        hit = self._ref_at(x, y)
        if hit is not None:
            _a, _b, book, chapter, verse = hit
            self._on_navigate(book, chapter, verse or 1)

    def _ref_at(self, x, y):
        """The reference under widget coordinates (x, y), or None."""
        if not self.refs:
            return None
        bx, by = self.body.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, it = self.body.get_iter_at_location(bx, by)
        if not ok:
            return None
        offset = it.get_offset()
        for span in self.refs:
            if span[0] <= offset < span[1]:
                return span
        return None

    def _on_body_tooltip(self, _view, x, y, keyboard, tooltip):
        if keyboard or self._ref_at(x, y) is None:
            return False
        tooltip.set_text(_('Ctrl+click to go to this passage'))
        return True

    def _dim_markers(self, buf):
        """Point the marker and reference tags at live theme colours.

        Re-read every restyle rather than set once: a tag holds a literal
        colour, so one minted under the light theme would stay light in the
        dark one. Typing heals it immediately; this call is what makes the
        first paint after a theme flip right too.
        """
        table = buf.get_tag_table()
        tag = table.lookup('md-marker')
        if tag is not None:
            ink = self.body.get_color()
            dim = Gdk.RGBA()
            dim.red, dim.green, dim.blue = ink.red, ink.green, ink.blue
            dim.alpha = ink.alpha * 0.35
            tag.set_property('foreground-rgba', dim)
        quote = table.lookup('md-quote')
        if quote is not None:
            ink = self.body.get_color()
            field = Gdk.RGBA()
            field.red, field.green, field.blue = ink.red, ink.green, ink.blue
            field.alpha = ink.alpha * 0.06
            quote.set_property('paragraph-background-rgba', field)
        ref = table.lookup('md-ref')
        if ref is not None:
            # The desktop's accent, not a literal blue — the reader may have
            # chosen another, and a tag cannot hold a named colour.
            ref.set_property(
                'foreground-rgba',
                Adw.StyleManager.get_default().get_accent_color_rgba())

    def _fill_anchors(self):
        """The entry's passages, and the way to add another.

        The row is always shown, even with nothing in it: an entry written
        about no passage is legal, and it is exactly the entry most likely to
        want one later — a sermon that turns out to be about Romans 5 after
        all. Anchors used to be fixed at whichever door made the entry, with
        no way to add, drop or correct one.
        """
        clear_children(self._anchor_box)
        for index, anchor in enumerate(self.row.get('anchors') or []):
            self._anchor_box.append(self._anchor_chip(anchor, index))
        self._add_anchor_btn = self._add_anchor_chip()
        self._anchor_box.append(self._add_anchor_btn)
        self._anchor_row_tail()
        self._anchor_box.set_visible(True)

    def _anchor_row_tail(self):
        """Anything that belongs after the passages, on their own row."""

    @staticmethod
    def anchor_label(anchor):
        verses = anchor.get('verses') or []
        ref = f'{book_label(anchor["book"])} {anchor["chapter"]}'
        if verses:
            ref = f'{ref}:{verses[0]}'
            if len(verses) > 1:
                ref = f'{ref}\u2013{verses[-1]}'
        return ref

    def _anchor_chip(self, anchor, index):
        """The chip, and the way off it.

        Two buttons drawn as one: the name still goes to the passage in a
        single click, which a menu would have cost. The ✕ is quiet until the
        pointer is on the chip, but never invisible — an unseeable target
        that removes something is worse than a visible one that is not
        needed.
        """
        verses = anchor.get('verses') or []
        ref = self.anchor_label(anchor)
        pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        pair.add_css_class('chip-pair')
        chip = self._ref_chip(ref, anchor['book'], anchor['chapter'],
                              verses[0] if verses else 1)
        chip.add_css_class('chip-leading')
        pair.append(chip)
        # The bare ✕, which is what `module_manager` already puts on a chip
        # you can clear. `edit-clear` is a backspace arrow carrying an ✕ and
        # reads as heavy machinery beside eleven characters of reference.
        drop = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        drop.add_css_class('ref-chip')
        drop.add_css_class('chip-trailing')
        drop.set_tooltip_text(_('Remove {ref}').format(ref=ref))
        set_accessible_label(drop, _('Remove {ref}').format(ref=ref))
        drop.connect('clicked', self._on_drop_anchor, index)
        pair.append(drop)
        return pair

    def _add_anchor_chip(self):
        """A typed reference, not a book-and-chapter grid.

        The grid in the reading header is bound to that window's own
        navigation state, and a second one here would be a second way to
        spell a passage. What the journal already owns is a parser: the same
        one that turns "Juan 3:16" in the body into a link reads this field,
        so a reader spells a reference one way everywhere in the feature.
        """
        # A child rather than a label: a labelled MenuButton draws a
        # dropdown arrow, and an arrow promises a list of passages to pick
        # from rather than a field to type one into.
        button = Gtk.MenuButton()
        button.set_child(Gtk.Label(label=_('Add passage')))
        # The chip styling goes on `.add-chip > button`: a MenuButton's own
        # node is `menubutton`, and the thing that draws the outline is the
        # button inside it.
        button.add_css_class('add-chip')
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        self._anchor_entry = Gtk.Entry()
        self._anchor_entry.set_width_chars(18)
        # The example is spelled in the reader's own language, because that
        # is what the field accepts.
        self._anchor_entry.set_placeholder_text(
            _('e.g. {ref}').format(ref=f'{book_label("John")} 3:16'))
        self._anchor_entry.connect('activate', self._on_add_anchor)
        box.append(self._anchor_entry)
        add = Gtk.Button(label=_('Add'))
        add.add_css_class('suggested-action')
        add.connect('clicked', self._on_add_anchor)
        box.append(add)
        popover.set_child(box)
        popover.connect('show', lambda _p: self._anchor_entry.grab_focus())
        button.set_popover(popover)
        self._anchor_popover = popover
        return button

    def _on_add_anchor(self, widget):
        text = self._anchor_entry.get_text().strip()
        anchor = journal_markup.parse_anchor(text, self._names())
        if anchor is None:
            # Say so on the field rather than in a dialog: the reader is
            # three characters from a reference that works.
            self._anchor_entry.add_css_class('error')
            return
        self._anchor_entry.remove_css_class('error')
        self._anchor_entry.set_text('')
        # Down BEFORE the commit: committing rebuilds the chip row, and the
        # button this popover belongs to goes with it.
        self._anchor_popover.popdown()
        anchors = list(self.row.get('anchors') or [])
        if not any(a['book'] == anchor['book']
                   and a['chapter'] == anchor['chapter']
                   and (a.get('verses') or []) == anchor['verses']
                   for a in anchors):
            anchors.append(anchor)
            self._commit_anchors(anchors)

    def _on_drop_anchor(self, _btn, index):
        anchors = list(self.row.get('anchors') or [])
        if 0 <= index < len(anchors):
            del anchors[index]
            self._commit_anchors(anchors)

    def _commit_anchors(self, anchors):
        """Put `anchors` on the open entry and let everything follow.

        The row carries the FIRST anchor's place as its own — it is what the
        list sorts and groups by — so the row's own fields move with the
        list, or the sidebar keeps showing a passage the entry no longer
        claims.
        """
        self.row['anchors'] = anchors
        first = anchors[0] if anchors else None
        verses = (first.get('verses') or []) if first else []
        self.row['book'] = first['book'] if first else None
        self.row['chapter'] = first['chapter'] if first else None
        self.row['app_verse'] = verses[0] if verses else None
        had_focus = self._anchor_box.get_focus_child() is not None
        self._fill_anchors()
        # The rebuild destroys whatever was pressed, and focus would fall on
        # the first chip's ✕ — a key press away from dropping a passage you
        # did not mean to. Only when the row HAD the focus: adding a passage
        # from the reading page must not steal it from the page.
        if had_focus:
            self._add_anchor_btn.grab_focus()
        self._show_verse(self.row)
        self._retitle_pane()
        self._edited()

    def _show_verse(self, entry):
        """Quote the entry's first anchored verse.

        A whole-chapter anchor has no single verse to quote and a verse-less
        entry has none at all; the label stays hidden either way.
        """
        anchors = entry.get('anchors') or []
        if not anchors or not anchors[0].get('verses'):
            self._verse.set_visible(False)
            return
        a = anchors[0]
        self._show_quote(self._verse, self._verse_text(
            a['book'], a['chapter'], a['verses'][0]))


class EntryEditor(_ProseEditor):
    """A journal entry: the prose editor plus the day it is *about*."""

    def _build_head(self, box):
        # A calendar, not a typed date: the reader corrects the day an entry
        # is about (writing up Sunday on Tuesday is the normal case), and no
        # one should have to spell it the way the machine stores it.
        self.date_button = Gtk.MenuButton()
        self.date_button.add_css_class('flat')
        self.date_button.set_halign(Gtk.Align.START)
        self._calendar = Gtk.Calendar()
        self._calendar.connect('day-selected', self._on_entry_date)
        cal_pop = Gtk.Popover()
        cal_pop.set_child(self._calendar)
        self.date_button.set_popover(cal_pop)
        self._meta_row.append(self.date_button)

    def _populate_head(self, entry):
        self._set_entry_date(entry.get('date') or '')

    def _set_entry_date(self, iso):
        """Put `iso` on the button and the calendar. An unparseable or empty
        date shows today without writing it — the entry keeps whatever it
        has until the reader actually picks a day."""
        try:
            day = date.fromisoformat(iso)
        except ValueError:
            day = date.today()
        self.date_button.set_label(format_date(day))
        # The properties, not select_day (deprecated in GTK 4.14). `month` is
        # 0-based here while GLib.DateTime.get_month() below is 1-based —
        # they do not agree, so neither value is passed through untouched.
        self._calendar.set_property('year', day.year)
        self._calendar.set_property('month', day.month - 1)
        self._calendar.set_property('day', day.day)

    def _on_entry_date(self, calendar):
        if self._loading or self.row is None:
            return
        picked = calendar.get_date()
        iso = date(picked.get_year(), picked.get_month(),
                   picked.get_day_of_month()).isoformat()
        if iso == (self.row.get('date') or ''):
            return
        self.row['date'] = iso
        self.date_button.set_label(format_date(date.fromisoformat(iso)))
        self._edited()

    def write(self, e):
        """Write one journal entry and patch its row.

        An entry with nothing in it is never written: the id was minted when
        the editor opened and stays in memory until there are words, so a
        reader who starts an entry and changes their mind leaves journal.json
        exactly as it was.
        """
        buf = self.body.get_buffer()
        body = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        title = self.title.get_text().strip()
        tags = [t.strip() for t in self.tags.get_text().split(',')
                if t.strip()]
        e['title'] = title
        e['body'] = body
        e['tags'] = tags

        if not title and not body.strip() and journal.get(e['id']) is None:
            return

        journal.save(e['id'], date=e.get('date') or None, title=title,
                     body=body, anchors=e.get('anchors') or [], tags=tags,
                     plan=e.get('plan'), collect=e.get('collect'))
        stored = journal.get(e['id'])
        if stored is not None:
            e['created'] = stored['created']
            e['modified'] = stored['modified']
        self._on_row_changed(e)


class SermonEditor(_ProseEditor):
    """A sermon manuscript: the prose editor plus what a sermon has that an
    entry does not — a big idea, a series and the days it was preached.

    There is no date field. A sermon is written across a span and preached
    on days of its own, and the journal's "the day this is about" is
    neither; `created` orders the archive until a preaching date exists.
    """

    title_placeholder = N_('Untitled sermon')
    body_hint = N_('Write your sermon…')
    tags_example = N_('e.g. grace, kingdom, advent')
    header_fallback = N_('Sermon')

    #: Words a minute, read aloud from a manuscript. The unit a preacher
    #: actually asks in is minutes — a manuscript is written against the time
    #: it is given — and every dedicated sermon tool in the survey ships this.
    #: 130 is the middle of the ordinary spoken range; the caption says
    #: "about", and the tooltip says the rate, because a number this soft
    #: must not pretend to be a measurement.
    SPOKEN_WPM = 130

    def _describe_length(self, label):
        label.set_tooltip_text(_('About {n} words a minute, read aloud')
                               .format(n=self.SPOKEN_WPM))

    def _length_label(self, words):
        minutes = words // self.SPOKEN_WPM
        if minutes < 1:
            # Below a minute the estimate says nothing the word count does
            # not, and "≈ 0 min" under the first sentence reads as a scold.
            return super()._length_label(words)
        return '{words} · {time}'.format(
            words=super()._length_label(words),
            time=_('≈ {n} min').format(n=minutes))

    def _build_head(self, box):
        # ── The big idea ────────────────────────────────────────────────
        # One line, in the reading serif, under the title where a standfirst
        # sits. Optional: a sermon with no claim written down is not an
        # error, and nothing else in the editor depends on it.
        self.idea = Gtk.Entry()
        self.idea.set_has_frame(False)
        self.idea.set_placeholder_text(
            _('What is this sermon saying, in one sentence?'))
        self.idea.add_css_class('sermon-idea')
        self.idea.connect('changed', self._edited)
        self._watch_focus(self.idea)
        box.append(self.idea)

        # ── Series, and which part ──────────────────────────────────────
        # One indivisible group on the metadata line: "Series [ ] ⌄ Part [ ]"
        # split across a wrap would read as two unrelated fields.
        series_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        series_row.append(self._caption(_('Series')))
        self.series = Gtk.Entry()
        # Not hexpand: a full-width filled box for a series name was the
        # loudest thing in a pane whose title and big idea are frameless, and
        # a series name is a few words.
        self.series.set_width_chars(24)
        self.series.set_placeholder_text(_('None'))
        self.series.connect('changed', self._series_edited)
        self._watch_focus(self.series)
        self._watch_grouping(self.series)
        series_row.append(self.series)

        # The existing series, offered rather than retyped: a second sermon
        # joins a series, and "Parables of the Kingdom" spelled two ways is
        # two groups in the list that should have been one.
        self._series_pick = Gtk.MenuButton(
            icon_name='scriptura-pan-down-symbolic')
        self._series_pick.add_css_class('flat')
        self._series_pick.set_tooltip_text(_('Existing series'))
        set_accessible_label(self._series_pick, _('Existing series'))
        self._series_pop = Gtk.Popover()
        self._series_pop.connect(
            'show', lambda _p: self._series_pop.set_child(
                self._series_menu()))
        self._series_pick.set_popover(self._series_pop)
        series_row.append(self._series_pick)

        series_row.append(self._caption(_('Part')))
        self.part = Gtk.Entry()
        self.part.set_width_chars(3)
        self.part.set_max_width_chars(3)
        self.part.set_input_purpose(Gtk.InputPurpose.DIGITS)
        # A series in progress does not always know its length, so the part
        # may simply be blank — "part 3 of ?" has to be sayable.
        self.part.set_placeholder_text('—')
        self.part.connect('changed', self._series_edited)
        self._watch_focus(self.part)
        self._watch_grouping(self.part)
        series_row.append(self.part)
        self._meta_row.append(series_row)

        # ── Preached ────────────────────────────────────────────────────
        # Never prompted for, and legitimately empty forever: a reader who
        # does not care to record every delivery must not be nagged into it.
        #
        # No "Preached" caption any more: on the shared line it cost a word
        # to say what a date chip beside an "Add a date" button already says,
        # and the chips carry it for a screen reader instead.
        self._preached_box = Adw.WrapBox(child_spacing=4, line_spacing=2)
        self._meta_row.append(self._preached_box)

        # The liturgical day it was begun for, when a door stamped one.
        # Provenance, so it is shown and not editable: which Sunday a sermon
        # was written for cannot be recovered later, and cannot be corrected
        # here either. Last on the metadata line, being the fact asked for
        # least — and it is the GROUP that hides, or a sermon no door stamped
        # would show a middot opening nothing.
        self._day = Gtk.Label(xalign=0)
        self._day.add_css_class('dim-label')
        self._day.add_css_class('caption')
        self._day.set_valign(Gtk.Align.CENTER)
        self._day.set_visible(False)

    # ── What you already have on this passage ────────────────────────────
    #
    # Every collecting door in the app runs one way: from the reading page
    # INTO the manuscript. Nothing ran the other way, though the study is in
    # the same file and, in this window, one tab over. MANUSCRIPT_RESEARCH
    # §2.9 says no tool in the survey models the exegetical→homiletical move
    # at all. This is the smallest honest version of it: the sermon asks what
    # you already saw in this passage, and puts it where you are writing.

    def _anchor_row_tail(self):
        # Cleared first: the editor is reused row to row, and a button left
        # on the attribute after the rebuild dropped it would say a door is
        # there when it is not.
        self._study_btn = None
        if not (self.row or {}).get('anchors'):
            return              # a door to nowhere is worse than no door
        button = Gtk.MenuButton()
        button.set_child(Gtk.Label(label=_('From your study')))
        button.add_css_class('add-chip')
        tip = _('What you have already marked or written on these passages')
        button.set_tooltip_text(tip)
        set_accessible_label(button, tip)
        popover = Gtk.Popover()
        # Built on show, not on populate: the marks are a live store, and a
        # note taken in the other window five minutes ago belongs in here.
        popover.connect('show', lambda _p: popover.set_child(
            self._study_menu()))
        button.set_popover(popover)
        self._study_pop = popover
        self._study_btn = button
        self._anchor_box.append(button)

    def _study_menu(self):
        """Everything the reader has on this sermon's passages.

        A scroller, not a column: a chapter worked over for a fortnight has
        more marks than a popover can be tall, and a popover that fits
        neither above nor below its button is silently not shown at all.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        chapters = []
        for anchor in (self.row or {}).get('anchors') or []:
            key = (anchor['book'], anchor['chapter'])
            if key not in chapters:
                chapters.append(key)
        found = False
        for book, chapter in chapters:
            found = self._study_section(box, book, chapter,
                                        len(chapters) > 1) or found
        if not found:
            empty = Gtk.Label(label=_('Nothing written on this passage yet'),
                              xalign=0)
            empty.add_css_class('dim-label')
            empty.set_margin_start(8)
            empty.set_margin_end(8)
            empty.set_margin_top(4)
            empty.set_margin_bottom(4)
            box.append(empty)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_propagate_natural_width(True)
        scroll.set_max_content_height(360)
        scroll.set_child(box)
        return scroll

    def _study_section(self, box, book, chapter, name_it):
        """One chapter's marks and entries. True if it had anything."""
        from annotations_window import marks_on
        marks = marks_on(book, chapter)
        entries = journal.entries_on(book, chapter)
        if not marks and not entries:
            return False
        if name_it:
            box.append(self._study_caption(
                f'{book_label(book)} {chapter}'))
        for mark in marks:
            box.append(self._study_row(
                self._mark_ref(mark), self._mark_preview(mark),
                lambda _b, m=mark: self._insert_mark(m)))
        if entries:
            # Opened, never inserted. An entry is a page — pouring one into
            # a manuscript would be quoting yourself at length — and the row
            # that says it exists is the study menu's own idiom.
            box.append(self._study_caption(_('Written on this passage')))
            for entry in entries:
                box.append(self._study_row(
                    entry['title'] or _('Untitled entry'),
                    journal_markup.preview(entry['body']),
                    lambda _b, e=entry: self._open_entry(e['id']),
                    enabled=self._on_open_entry is not None))
        return True

    @staticmethod
    def _study_caption(text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class('dim-label')
        lbl.add_css_class('caption')
        lbl.set_margin_start(8)
        lbl.set_margin_top(6)
        return lbl

    @staticmethod
    def _study_row(head, preview, on_click, enabled=True):
        """A reference over what was written under it, as one flat button."""
        btn = Gtk.Button()
        btn.add_css_class('flat')
        btn.set_sensitive(enabled)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ref = Gtk.Label(label=head, xalign=0)
        ref.add_css_class('caption-heading')
        ref.set_ellipsize(Pango.EllipsizeMode.END)
        inner.append(ref)
        if preview:
            words = Gtk.Label(label=preview, xalign=0)
            words.add_css_class('dim-label')
            words.add_css_class('caption')
            words.set_ellipsize(Pango.EllipsizeMode.END)
            words.set_max_width_chars(34)
            inner.append(words)
        btn.set_child(inner)
        btn.connect('clicked', on_click)
        return btn

    def _mark_ref(self, mark):
        if mark.get('is_chapter_note'):
            return _('Note on {ref}').format(
                ref=f'{book_label(mark["book"])} {mark["chapter"]}')
        return f'{book_label(mark["book"])} {mark["chapter"]}:' \
               f'{mark["app_verse"]}'

    def _mark_preview(self, mark):
        """The reader's own note if there is one, else the verse's words.

        The note leads because it is the thing being looked for: the mark is
        a place, the note is what was seen there.
        """
        note = ' '.join((mark.get('note') or '').split())
        if note:
            return note
        if mark.get('is_chapter_note'):
            return ''
        return self._verse_text(mark['book'], mark['chapter'], mark['verse'])

    def _insert_mark(self, mark):
        """Put one mark into the manuscript where the caret is.

        Where the caret is, and not at the end as a collected passage from
        the reading page arrives: the reader is inside this editor, writing
        at a place they chose.
        """
        self._study_pop.popdown()
        text, _anchor = self._mark_as_prose(mark)
        buf = self.body.get_buffer()
        at = buf.get_iter_at_mark(buf.get_insert())
        here = self._line_text(buf, at.get_line())
        lead = '' if not here.strip() else '\n\n'
        buf.begin_user_action()
        buf.insert_at_cursor(f'{lead}{text}\n\n')
        buf.end_user_action()
        self.body.grab_focus()
        # Collected rather than typed, as on every other collecting door:
        # the write lands now.
        self._on_flush()

    def _open_entry(self, entry_id):
        self._study_pop.popdown()
        if self._on_open_entry is not None:
            self._on_open_entry(entry_id)

    @staticmethod
    def _caption(text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class('dim-label')
        lbl.add_css_class('caption')
        lbl.set_valign(Gtk.Align.CENTER)
        return lbl

    def _series_menu(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        names = sermons.all_series()
        if not names:
            lbl = Gtk.Label(label=_('No series yet'))
            lbl.add_css_class('dim-label')
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            box.append(lbl)
            return box
        for name in names:
            btn = Gtk.Button()
            btn.add_css_class('flat')
            btn.set_child(Gtk.Label(label=name, xalign=0))
            btn.connect('clicked', self._on_pick_series, name)
            box.append(btn)
        return box

    def _on_pick_series(self, _btn, name):
        self._series_pop.popdown()
        self.series.set_text(name)

    # ── Preaching dates ─────────────────────────────────────────────────

    def _fill_preached(self):
        """The days it was preached, oldest first, and the way to add one."""
        clear_children(self._preached_box)
        dates = (self.row.get('preached') or []) if self.row else []
        for index, iso in enumerate(dates):
            self._preached_box.append(self._date_chip(iso, index))
        if not dates:
            none_lbl = Gtk.Label(label=_('Not yet preached'), xalign=0)
            none_lbl.add_css_class('dim-label')
            none_lbl.add_css_class('caption')
            none_lbl.set_valign(Gtk.Align.CENTER)
            self._preached_box.append(none_lbl)
        self._add_date_btn = self._add_date_chip()
        self._preached_box.append(self._add_date_btn)

    def _date_chip(self, iso, index):
        """A filled chip, where a passage is outlined: a preaching date is
        the reader's own record, not Scripture's place."""
        try:
            label = format_date(date.fromisoformat(iso))
        except ValueError:
            label = iso
        pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        pair.add_css_class('chip-pair')
        chip = Gtk.Button(label=label)
        chip.add_css_class('tag-chip')
        chip.add_css_class('chip-leading')
        chip.set_can_focus(False)
        # The visible "Preached" caption is gone from the metadata line, so
        # the chip says it: sighted readers get it from the neighbouring
        # "Add a date", and a screen reader gets it here.
        set_accessible_label(chip, _('Preached {date}').format(date=label))
        pair.append(chip)
        drop = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        drop.add_css_class('tag-chip')
        drop.add_css_class('chip-trailing')
        drop.set_tooltip_text(_('Remove {date}').format(date=label))
        set_accessible_label(drop, _('Remove {date}').format(date=label))
        drop.connect('clicked', self._on_drop_date, index)
        pair.append(drop)
        return pair

    def _add_date_chip(self):
        button = Gtk.MenuButton()
        button.set_child(Gtk.Label(label=_('Add a date')))
        button.add_css_class('add-chip')
        popover = Gtk.Popover()
        calendar = Gtk.Calendar()
        # `day-selected` also fires while browsing months, which would file a
        # preaching date the reader only scrolled past; the Add button is the
        # commit, and the calendar only holds the choice.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.append(calendar)
        add = Gtk.Button(label=_('Add'))
        add.add_css_class('suggested-action')
        add.connect('clicked', self._on_add_date, calendar)
        box.append(add)
        popover.set_child(box)
        button.set_popover(popover)
        self._date_popover = popover
        return button

    def _on_add_date(self, _btn, calendar):
        picked = calendar.get_date()
        iso = date(picked.get_year(), picked.get_month(),
                   picked.get_day_of_month()).isoformat()
        self._date_popover.popdown()
        dates = list(self.row.get('preached') or [])
        if iso in dates:
            return
        # Sorted here as the store sorts it, so the chips do not jump the
        # moment the write lands.
        self.row['preached'] = sorted(dates + [iso])
        self._fill_preached()
        # The popover hands focus back to the button that opened it, and this
        # rebuild has just destroyed that button — so focus fell to the first
        # thing in the row, which is a ✕ that REMOVES a date. One space bar
        # away from undoing the date you came here to add. Put it on the new
        # add button instead, where it was.
        self._add_date_btn.grab_focus()
        self._edited()

    def _on_drop_date(self, _btn, index):
        dates = list(self.row.get('preached') or [])
        if 0 <= index < len(dates):
            del dates[index]
            self.row['preached'] = dates
            self._fill_preached()
            # Same rebuild, same trap: the ✕ that was pressed is gone, and
            # the focus it held would land on the next date's ✕.
            self._add_date_btn.grab_focus()
            self._edited()

    # ── Populate and write ──────────────────────────────────────────────

    def _retitle_pane(self):
        """The header says where this sermon belongs — which series, and
        which part of it — with the passage beneath.

        Not the passage alone, as an entry's header is: the passages are
        chips an inch below, and what a manuscript needs naming at the top
        is the series it is part 3 of.
        """
        series = (self.row or {}).get('series') or {}
        where = self._anchor_label(self.row) or ''
        name = series.get('name') or ''
        part = series.get('part')
        if name and isinstance(part, int):
            name = _('{series} · part {n}').format(series=name, n=part)
        if name:
            self._on_title(name, where)
        else:
            self._on_title(where or _(self.header_fallback), '')

    def _build_meta_tail(self):
        self._meta_row.append(self._day)

    def _writing_mode_chrome(self):
        # The big idea goes too. It is a claim ABOUT the sermon, and the
        # sermon is the thing you came here to write.
        return super()._writing_mode_chrome() + [self.idea]

    def _populate_head(self, entry):
        series = entry.get('series') or {}
        self.idea.set_text(entry.get('idea') or '')
        self.series.set_text(series.get('name') or '')
        part = series.get('part')
        self.part.set_text('' if part is None else str(part))
        self._show_day(entry.get('collect'))

    def _series_edited(self, *_a):
        """The header names the series, so it follows the field being typed
        in — a header that lags the text an inch below it reads as stale."""
        if not self._loading and self.row is not None:
            self.row['series'] = self._series_value()
            self._retitle_pane()
        self._edited()

    def _watch_grouping(self, widget):
        """Re-group the list when `widget` is left, if what it holds moved
        this sermon to another heading.

        The pane header follows the field as it is typed, but the LIST row is
        refilled in place and keeps whatever group it was drawn in — so a
        sermon just given a series went on sitting under "No series" with the
        header above it already reading the new name. Only on leaving, and
        only when the value actually changed: a full rebuild per keystroke
        would drop the caret out of the field being typed in.
        """
        focus = Gtk.EventControllerFocus()
        focus.connect(
            'enter', lambda _c: setattr(self, '_group_at_focus',
                                        self._series_value()))
        focus.connect('leave', lambda _c: self._regroup_if_moved())
        widget.add_controller(focus)

    def _regroup_if_moved(self):
        was = getattr(self, '_group_at_focus', None)
        now = self._series_value()
        self._group_at_focus = now
        if now != was and not self._loading and self.row is not None:
            self._on_regroup()

    def populate(self, entry):
        super().populate(entry)
        # Outside the gate on purpose: it rebuilds widgets rather than
        # setting text, so it emits nothing that could queue a write.
        self._fill_preached()

    def _show_day(self, collect):
        name = church_year.name_for(collect) if collect else None
        self._day.set_visible(bool(name))
        if name:
            self._day.set_text(_('Written for {day}').format(day=name))

    def _series_value(self):
        """`{name, part}` from the two fields, or None for no series.

        A part with no series is not a series — the name is what groups the
        list — and a part that is not a number is simply not one; the field
        holds what was typed either way, so nothing the reader typed is
        thrown away behind their back.
        """
        name = self.series.get_text().strip()
        if not name:
            return None
        raw = self.part.get_text().strip()
        return {'name': name, 'part': int(raw) if raw.isdigit() else None}

    def collect(self, text, anchor=None):
        """Add collected text to the end of the open manuscript.

        NOT named `append`: an editor is a `Gtk.Box`, and shadowing its own
        `append` breaks the widget tree it builds itself with.

        The buffer, not the store: this editor holds the words, and a store
        write underneath it would be overwritten by the next autosave. The
        passage joins the anchors as it does on the store path — text
        collected from the reading pane arrives with a reference, and a
        sermon quoting a passage it is not anchored to is invisible at that
        verse and in the book filter.
        """
        buf = self.body.get_buffer()
        existing = buf.get_text(*buf.get_bounds(), False)
        addition = f'\n\n{text}' if existing.strip() else text
        buf.insert(buf.get_end_iter(), addition)
        if anchor is not None:
            anchors = list(self.row.get('anchors') or [])
            if not any(a['book'] == anchor['book']
                       and a['chapter'] == anchor['chapter']
                       and (a.get('verses') or []) == (anchor.get('verses')
                                                       or [])
                       for a in anchors):
                self._commit_anchors(anchors + [anchor])
        # The insert queued a write on the debounce; this is the reader
        # collecting rather than typing, so it lands now.
        self._on_flush()

    def write(self, e):
        """Write one sermon and patch its row.

        A sermon with nothing in it is never written: the id was minted when
        the editor opened and stays in memory until there are words, so a
        reader who opens the pencil and changes their mind leaves
        sermons.json exactly as it was.
        """
        buf = self.body.get_buffer()
        body = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        title = self.title.get_text().strip()
        idea = self.idea.get_text().strip()
        tags = [t.strip() for t in self.tags.get_text().split(',')
                if t.strip()]
        series = self._series_value()
        e['title'] = title
        e['idea'] = idea
        e['body'] = body
        e['tags'] = tags
        e['series'] = series

        if (not title and not idea and not body.strip()
                and sermons.get(e['id']) is None):
            return

        sermons.save(e['id'], title=title, idea=idea, body=body,
                     anchors=e.get('anchors') or [], series=series,
                     preached=e.get('preached') or [], tags=tags,
                     collect=e.get('collect'))
        stored = sermons.get(e['id'])
        if stored is not None:
            e['created'] = stored['created']
            e['modified'] = stored['modified']
        self._on_row_changed(e)
