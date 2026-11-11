"""The sheets that take a passage out of the app — as a document, or as an
image.

Both are reached from the right-click study menu, beside Copy, which is the
same act at a smaller size: the menu already has the selection in hand, and a
selection is what leaving the app is about. The composition lives elsewhere
(`passage_export`, `verse_card`), which keeps those testable and keeps this
file to the choosing and the saving.

Saving goes through the task runner — a document can reach a hundred thousand
words with the fathers in it, and a card is a layout and a PNG compression.
Copying a card does NOT: it is 45–75ms measured, and a clipboard action that
lands after the reader has moved on is worse than one that costs a frame.
"""
import logging

import re

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GLib, Gtk

import catena_bridge
import content
import passage_export
import sword_bridge
import verse_card
import tasks
from a11y import set_accessible_label
from gtk_utils import file_dialog_failed
from i18n import _

_log = logging.getLogger(__name__)

#: Scope keys, in the order they are offered.
SELECTION, UNIT, CHAPTER = 'selection', 'unit', 'chapter'

#: The divine name as OSIS marks it, and two private-use marks that carry
#: it through the tag strip so it can come back as a small-caps span.
_DIVINE_RE = re.compile(r'<divineName[^>]*>(.*?)</divineName>', re.DOTALL)
_DN_OPEN, _DN_CLOSE = '\ue000', '\ue001'


def card_rows(module, book, chapter, verses, smallcaps=True,
              initial_ink=None):
    """(verse, Pango markup) for each selected verse, in reading order.

    The first letter is enlarged as the page enlarges a chapter's first, at
    its 200% and bold; `initial_ink` is its gold, or None to leave it in the
    card's ink. No red letters, by Andres's call (2026-11-11): a card is one
    ink and one gold, so it reads as a Scriptura card wherever it lands.

    Markup rather than plain text for one reason: the divine name. The KJV
    marks it `<divineName>Lord</divineName>`, and stripped to plain text the
    card read "The Lord is my shepherd", losing the printed LORD that tells
    the reader the Hebrew has the Name. With the reader's small-caps setting
    on, the card sets it as the reading view does: marked names from the
    markup, and literal capitals (BSB, Webster) by the same inscription-aware
    rule. With it off, the card shows the name as the reading view does.
    """
    from pane import (_DROPCAP_SPAN, _dropcap_split, _normalize_divine,
                      _smallcap_divine_literals)
    wanted = set(verses)
    rows = []
    for verse, html in content.load_chapter(module, book, chapter):
        if verse not in wanted:
            continue
        html = str(html)
        if smallcaps:
            html = _DIVINE_RE.sub(
                lambda m: _DN_OPEN + _normalize_divine(m.group(1)) + _DN_CLOSE,
                html)
        markup = GLib.markup_escape_text(sword_bridge.plain_text(html))
        markup = (markup.replace(_DN_OPEN, '<span variant="small-caps">')
                        .replace(_DN_CLOSE, '</span>'))
        if smallcaps:
            markup = _smallcap_divine_literals(markup)
        if not rows and (split := _dropcap_split(markup)):
            before, letter, after = split
            span = (_DROPCAP_SPAN if initial_ink is None else
                    _DROPCAP_SPAN[:-1] + f' foreground="{initial_ink}">')
            markup = f'{before}{span}{letter}</span>{after}'
        rows.append((verse, markup))
    return rows


def _card_heading(module, book, chapter, verse):
    """The title of the section `verse` stands in, or None.

    The nearest heading at or before the verse, in this chapter: a passage
    that starts inside a section still belongs to it.
    """
    headings = sword_bridge.chapter_headings(module, book, chapter) or {}
    before = [k for k in headings if k <= verse and headings[k]]
    if not before:
        return None
    return sword_bridge.plain_text(headings[max(before)][-1]) or None


def _card_original(module, book, chapter, verse):
    """The verse's Greek or Hebrew as one line, or None without data."""
    app = sword_bridge.map_verse_to_app(module, book, chapter, verse)
    words = dict(passage_export.interlinear_rows(book, chapter, [app]))
    line = ' '.join(w.surface for w in words.get(app, ()) if w.surface)
    return line.strip() or None


#: The card preview's box in the sheet, in points: each shape is scaled to
#: fit inside it.
PREVIEW_W, PREVIEW_H = 400, 240


def export_passage(pane, verses, popover=None):
    """Open the sheet for `verses`, which the study menu already resolved.

    `popover` is None when the door was the keyboard or the toolbar rather
    than the study menu, and `verses` may be empty with it — the sheet drops
    its selection scope and exports the chapter.
    """
    if popover is not None:
        popover.popdown()
    ExportSheet(pane, verses).present(pane.get_root())


class ExportSheet:
    """The choices, then the save. Deliberately small: a scope, what to
    include, and a format. Everything on it is a decision the reader can only
    make for themselves — nothing here is a preference worth persisting."""

    def __init__(self, pane, verses):
        self._pane = pane
        self._module, self._book, self._chapter = pane.module, pane.book, pane.chapter
        self._verses = list(verses)
        self._dialog = Adw.Dialog()
        self._dialog.set_title(_('Export passage'))
        self._dialog.set_content_width(460)

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        save = Gtk.Button(label=_('Save…'))
        save.add_css_class('suggested-action')
        save.connect('clicked', lambda _b: self._choose_file())
        header.pack_end(save)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        page.add(self._passage_group())
        page.add(self._include_group())
        page.add(self._format_group())
        view.set_content(page)
        self._dialog.set_child(view)

    def present(self, root):
        self._dialog.present(root)

    # ── The choices ──────────────────────────────────────────────────────
    def _passage_group(self):
        group = Adw.PreferencesGroup(title=_('Passage'))
        # No selection — the sheet was opened from the toolbar or a
        # shortcut, not over a verse. Offering "the selected verses" then
        # would export nothing at all.
        self._scopes = [SELECTION] if self._verses else []
        labels = [_('The selected verses')] if self._verses else []
        # A sense-unit is only offered where the module actually marks them.
        # Modules without section headings would answer with the whole
        # chapter, and two rows that do the same thing is not a choice.
        # It also needs a verse to be the unit AROUND, so it goes with the
        # selection when there is none.
        if self._verses and sword_bridge.chapter_headings(
                self._module, self._book, self._chapter):
            self._scopes.append(UNIT)
            labels.append(_('This sense-unit'))
        self._scopes.append(CHAPTER)
        labels.append(_('The whole chapter'))
        self._scope_row = Adw.ComboRow(
            title=_('Export'), model=Gtk.StringList.new(labels))
        group.add(self._scope_row)
        return group

    def _include_group(self):
        """What travels with the text.

        A layer whose data is not installed is not shown at all — an inert
        switch is a worse answer than silence, and `passage_export` would
        emit nothing for it anyway.
        """
        group = Adw.PreferencesGroup(title=_('Include'))
        self._notes_row = Adw.SwitchRow(title=_('My notes and highlights'),
                                        active=True)
        group.add(self._notes_row)
        self._layer_rows = {}
        has_interlinear = passage_export.interlinear_module_for(
            self._book) is not None
        for key, title, available in (
                ('interlinear', _('Interlinear'), has_interlinear),
                ('variants', _('Textual variants'), has_interlinear),
                ('catena', _('Voices of the fathers'),
                 catena_bridge.is_installed())):
            if not available:
                continue
            row = Adw.SwitchRow(title=title, active=False)
            group.add(row)
            self._layer_rows[key] = row
        return group

    def _format_group(self):
        group = Adw.PreferencesGroup(title=_('Format'))
        self._format_row = Adw.ComboRow(
            title=_('File'),
            model=Gtk.StringList.new([_('Markdown'), _('Plain text')]))
        group.add(self._format_row)
        return group

    # ── What was chosen ──────────────────────────────────────────────────
    def _chosen_verses(self):
        scope = self._scopes[self._scope_row.get_selected()]
        if scope == CHAPTER:
            return None
        if scope == UNIT:
            return passage_export.pericope_verses(
                self._module, self._book, self._chapter,
                self._verses[0])
        return self._verses

    def _markdown(self):
        return self._format_row.get_selected() == 0

    def _suggested_name(self):
        """`John 3.16-18.md` — the reference, with the colon out of it: a
        colon is legal here and a nuisance on any drive the file is copied
        to next."""
        ref = passage_export.rendered_reference(
            self._module, self._book, self._chapter, self._chosen_verses())
        stem = ref.replace(':', '.').replace(passage_export.EN_DASH, '-')
        return f'{stem}.{"md" if self._markdown() else "txt"}'

    # ── The save ─────────────────────────────────────────────────────────
    def _choose_file(self):
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Export passage'))
        dialog.set_initial_name(self._suggested_name())
        dialog.save(self._pane.get_root(), None, self._on_chosen)

    def _on_chosen(self, dialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error as err:
            if file_dialog_failed(err):
                self._report(_('Could not open the file chooser'))
            return
        path = gfile.get_path() if gfile else None
        if not path:
            self._report(_('Please choose a location on this computer.'))
            return
        self._dialog.close()
        pane, verses = self._pane, self._chosen_verses()
        module, book, chapter = self._module, self._book, self._chapter
        notes = self._notes_row.get_active()
        layers = {key: row.get_active()
                  for key, row in self._layer_rows.items()}
        markdown = self._markdown()

        def work(_token):
            document = passage_export.build(
                module, book, chapter, verses,
                notes=notes, markdown=markdown, **layers)
            with open(path, 'w', encoding='utf-8') as out:
                out.write(document)
            return path

        tasks.submit(key=f'passage-export:{id(pane)}', work=work,
                     apply=lambda _p: self._report(
                         _('Exported {name}').format(
                             name=GLib.path_get_basename(path))),
                     on_error=lambda _e: self._report(
                         _('Could not write the file')))

    def _report(self, message):
        if self._pane._on_toast:
            self._pane._on_toast(message)


def share_as_image(pane, verses, popover=None):
    """Open the card sheet for `verses`."""
    if popover is not None:
        popover.popdown()
    # A verse the module leaves empty made a card of a citation and nothing
    # else, which says nothing to whoever it is sent to.
    if not passage_export.verse_text(pane.module, pane.book, pane.chapter,
                                     list(verses)):
        if pane._on_toast:
            pane._on_toast(_('There is no text here to put on a card'))
        return
    CardSheet(pane, verses).present(pane.get_root())


class CardSheet:
    """Paper, shape, wordmark — and nothing else.

    The look itself is not offered: there is one house card, and a gallery of
    templates is how this feature cheapens itself. What a reader chooses here
    is which of the app's own papers it is cast on and what shape it needs to
    be for wherever it is going.
    """

    def __init__(self, pane, verses):
        self._pane = pane
        self._module, self._book, self._chapter = pane.module, pane.book, pane.chapter
        self._verses = list(verses)
        # Read once: the preview redraws on every choice, and the card must
        # carry the words the sheet opened on.
        from pane import dropcap_color_hex
        self._rows = card_rows(
            self._module, self._book, self._chapter, self._verses,
            getattr(pane, '_smallcaps_divine', True),
            dropcap_color_hex(False)
            if getattr(pane, '_colored_dropcap', True) else None)
        self._counts: dict[tuple[str, bool], int] = {}
        first = self._rows[0][0] if self._rows else None
        self._heading = (_card_heading(self._module, self._book,
                                       self._chapter, first)
                         if first is not None
                         and getattr(pane, '_show_headings', True) else None)
        # One verse at most: under a passage the line would crowd the card,
        # and it would no longer be the words of the one verse it sits under.
        self._original = (_card_original(self._module, self._book,
                                         self._chapter, first)
                          if len(self._rows) == 1 else None)
        self._dialog = Adw.Dialog()
        self._dialog.set_title(_('Share as image'))
        self._dialog.set_content_width(460)

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        save = Gtk.Button(label=_('Save…'))
        save.add_css_class('suggested-action')
        save.connect('clicked', lambda _b: self._choose_file())
        header.pack_end(save)
        # A card is more often pasted than filed, so the copy sits beside the
        # save rather than behind it.
        copy = Gtk.Button(icon_name='scriptura-edit-copy-symbolic')
        copy.set_tooltip_text(_('Copy the card'))
        set_accessible_label(copy, _('Copy the card'))
        copy.connect('clicked', lambda _b: self._copy())
        header.pack_end(copy)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        # The card itself, redrawn as the reader chooses: paper and shape
        # are judged by eye, and a choice made blind is a guess.
        shown = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        # A drawing area, not a picture: a picture sizes itself from its
        # texture, and the wide card came out squeezed into the last shape's
        # box. Its content size is exactly the scaled card.
        self._card = None
        self._preview = Gtk.DrawingArea(accessible_role=Gtk.AccessibleRole.IMG,
                                        halign=Gtk.Align.CENTER)
        self._preview.set_draw_func(self._paint_preview)
        self._preview.set_overflow(Gtk.Overflow.HIDDEN)
        self._preview.add_css_class('card-preview')
        box.append(self._preview)
        self._cut_note = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                   visible=False)
        self._cut_note.add_css_class('caption')
        self._cut_note.add_css_class('dim-label')
        box.append(self._cut_note)
        shown.add(box)
        page.add(shown)

        group = Adw.PreferencesGroup(title=_('Card'))
        self._paper_row = Adw.ComboRow(
            title=_('Paper'),
            model=Gtk.StringList.new([_(name) for name, _hex
                                      in verse_card.CARD_PAPERS]))
        # Opens on the one nearest the reader's own, which for a dark reading
        # paper is the warm default rather than a nearest — see nearest_paper.
        appearance = self._pane.reading_appearance()
        current = verse_card.nearest_paper(appearance.get('surface'))
        for index, (_name, value) in enumerate(verse_card.CARD_PAPERS):
            if value == current:
                self._paper_row.set_selected(index)
                break
        group.add(self._paper_row)

        self._shapes = list(verse_card.SHAPES)
        self._shape_row = Adw.ComboRow(
            title=_('Shape'),
            model=Gtk.StringList.new([_('Square'), _('Portrait'), _('Wide')]))
        group.add(self._shape_row)

        self._mark_row = Adw.SwitchRow(title=_('Show the app’s name'),
                                       active=False)
        group.add(self._mark_row)
        # Offered only where there is a line to show.
        self._original_row = Adw.SwitchRow(
            title=(_('Show the Hebrew') if self._original
                   and any('\u0590' <= c <= '\u05ff' for c in self._original)
                   else _('Show the Greek')),
            active=False, visible=self._original is not None)
        group.add(self._original_row)
        page.add(group)
        view.set_content(page)
        self._dialog.set_child(view)

        self._paper_row.connect('notify::selected', self._refresh)
        self._shape_row.connect('notify::selected', self._refresh)
        self._mark_row.connect('notify::active', self._refresh)
        self._original_row.connect('notify::active', self._refresh)
        self._refresh()

    def present(self, root):
        self._dialog.present(root)

    def _paper(self):
        return verse_card.CARD_PAPERS[self._paper_row.get_selected()][1]

    def _shape(self):
        return self._shapes[self._shape_row.get_selected()]

    def _shown_original(self):
        return self._original if self._original_row.get_active() else None

    def _shown(self):
        """The verses this shape can carry at a readable size, from the first."""
        key = (self._shape(), self._shown_original() is not None)
        if key not in self._counts:
            self._counts[key] = verse_card.shown_count(
                [text for _v, text in self._rows], key[0],
                self._heading, self._shown_original())
        return self._rows[:self._counts[key]]

    def _is_cut(self):
        return len(self._shown()) < len(self._rows)

    def _reference(self):
        # A cut card cites only what it carries; a whole one cites the
        # selection as made. In the reader's language: a Russian card read
        # "Gen 1:1" under Russian text.
        verses = ([v for v, _t in self._shown()] if self._is_cut()
                  else self._verses)
        return passage_export.rendered_reference(
            self._module, self._book, self._chapter, verses, localized=True)

    def _card_args(self):
        from pane import auto_reading_ink
        paper = self._paper()
        return dict(
            text=' '.join(text for _v, text in self._shown()).strip(),
            reference=self._reference(),
            translation=passage_export.version_label(self._module),
            paper=paper, ink=auto_reading_ink(paper),
            shape=self._shape(), wordmark=self._mark_row.get_active(),
            heading=self._heading, original=self._shown_original())

    def _card_bytes(self):
        return verse_card.render_bytes(**self._card_args())

    def _refresh(self, *_args):
        args = self._card_args()
        width, height = verse_card.SHAPES[args['shape']]
        fit = min(PREVIEW_W / width, PREVIEW_H / height)
        self._preview.set_content_width(round(width * fit))
        self._preview.set_content_height(round(height * fit))
        try:
            self._card = verse_card.draw(**args)
        except Exception:
            # Copy and save report their own failure; a preview that cannot
            # draw must not take the sheet down with it.
            _log.exception('Could not draw the card preview')
            self._card = None
        self._preview.queue_draw()
        self._preview.update_property([Gtk.AccessibleProperty.LABEL],
                                      [args['reference']])
        if self._is_cut():
            self._cut_note.set_label(
                _('The card shows {shown}; the rest does not fit.').format(
                    shown=args['reference']))
        self._cut_note.set_visible(self._is_cut())

    def _copy(self):
        """Put the card on the clipboard, the way the imagery plates do.

        Explicit `image/png` bytes AND the texture, in that order: a bare
        texture value only survives a same-process paste, because a local read
        skips serialisation entirely. Every other application negotiates a
        mime type, and image/png is the one they all accept — the texture
        rides along for GTK-native consumers.

        Synchronous rather than on the task runner: a card is 45–75ms to draw
        (measured), and a copy that lands after the reader has moved on is
        worse than a copy that costs a frame.
        """
        try:
            png = GLib.Bytes.new(self._card_bytes())
            provider = Gdk.ContentProvider.new_union([
                Gdk.ContentProvider.new_for_bytes('image/png', png),
                Gdk.ContentProvider.new_for_value(Gdk.Texture.new_from_bytes(png)),
            ])
            if not self._pane.get_root().get_clipboard().set_content(provider):
                self._report(_('Could not copy the image'))
                return
        except Exception:
            _log.exception('Could not copy verse card')
            self._report(_('Could not copy the image'))
            return
        self._dialog.close()
        self._report(_('Card copied'))

    def _paint_preview(self, _area, cr, width, height):
        if self._card is None:
            return
        cr.scale(width / self._card.get_width(), height / self._card.get_height())
        cr.set_source_surface(self._card, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()

    def _choose_file(self):
        dialog = Gtk.FileDialog()
        dialog.set_title(_('Share as image'))
        stem = self._reference().replace(':', '.').replace(
            passage_export.EN_DASH, '-')
        dialog.set_initial_name(f'{stem}.png')
        dialog.save(self._pane.get_root(), None, self._on_chosen)

    def _on_chosen(self, dialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error as err:
            if file_dialog_failed(err):
                self._report(_('Could not open the file chooser'))
            return
        path = gfile.get_path() if gfile else None
        if not path:
            self._report(_('Please choose a location on this computer.'))
            return
        self._dialog.close()
        pane, args = self._pane, self._card_args()

        def work(_token):
            return verse_card.render(path, **args)

        tasks.submit(key=f'verse-card:{id(pane)}', work=work,
                     apply=lambda _p: self._report(
                         _('Saved {name}').format(
                             name=GLib.path_get_basename(path))),
                     on_error=lambda _e: self._report(
                         _('Could not write the image')))

    def _report(self, message):
        if self._pane._on_toast:
            self._pane._on_toast(message)
