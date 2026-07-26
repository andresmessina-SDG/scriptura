"""The sheets that take a passage out of the app — as a document, or as an
image.

Both are reached from the right-click study menu, beside Copy, which is the
same act at a smaller size: the menu already has the selection in hand, and a
selection is what leaving the app is about. The composition lives elsewhere
(`passage_export`, `verse_card`), which keeps those testable and keeps this
file to the choosing and the saving.

Both gathers run on the task runner: the document one reads SQLite and the
SWORD modules and can reach a hundred thousand words when the fathers are in
it, and the card one lays out and compresses a PNG. Either is long enough on
the UI thread to show.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

import catena_bridge
import passage_export
import sword_bridge
import verse_card
import tasks
from i18n import _

#: Scope keys, in the order they are offered.
SELECTION, UNIT, CHAPTER = 'selection', 'unit', 'chapter'


def export_passage(pane, verses, popover):
    """Open the sheet for `verses`, which the study menu already resolved."""
    popover.popdown()
    ExportSheet(pane, verses).present(pane.get_root())


class ExportSheet:
    """The choices, then the save. Deliberately small: a scope, what to
    include, and a format. Everything on it is a decision the reader can only
    make for themselves — nothing here is a preference worth persisting."""

    def __init__(self, pane, verses):
        self._pane = pane
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
        self._scopes = [SELECTION]
        labels = [_('The selected verses')]
        # A sense-unit is only offered where the module actually marks them.
        # Modules without section headings would answer with the whole
        # chapter, and two rows that do the same thing is not a choice.
        if sword_bridge.chapter_headings(
                self._pane._module, self._pane._book, self._pane._chapter):
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
            self._pane._book) is not None
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
                self._pane._module, self._pane._book, self._pane._chapter,
                self._verses[0])
        return self._verses

    def _markdown(self):
        return self._format_row.get_selected() == 0

    def _suggested_name(self):
        """`John 3.16-18.md` — the reference, with the colon out of it: a
        colon is legal here and a nuisance on any drive the file is copied
        to next."""
        ref = passage_export.format_reference(
            self._pane._book, self._pane._chapter, self._chosen_verses())
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
        except GLib.Error:
            return                      # cancelled, or nowhere chosen
        path = gfile.get_path() if gfile else None
        if not path:
            self._report(_('Please choose a location on this computer.'))
            return
        self._dialog.close()
        pane, verses = self._pane, self._chosen_verses()
        module, book, chapter = pane._module, pane._book, pane._chapter
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


def share_as_image(pane, verses, popover):
    """Open the card sheet for `verses`."""
    popover.popdown()
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
        self._verses = list(verses)
        self._dialog = Adw.Dialog()
        self._dialog.set_title(_('Share as image'))
        self._dialog.set_content_width(460)

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        save = Gtk.Button(label=_('Save…'))
        save.add_css_class('suggested-action')
        save.connect('clicked', lambda _b: self._choose_file())
        header.pack_end(save)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
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
        page.add(group)
        view.set_content(page)
        self._dialog.set_child(view)

    def present(self, root):
        self._dialog.present(root)

    def _paper(self):
        return verse_card.CARD_PAPERS[self._paper_row.get_selected()][1]

    def _reference(self):
        return passage_export.format_reference(
            self._pane._book, self._pane._chapter, self._verses)

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
        except GLib.Error:
            return
        path = gfile.get_path() if gfile else None
        if not path:
            self._report(_('Please choose a location on this computer.'))
            return
        self._dialog.close()
        pane, verses = self._pane, self._verses
        module, book, chapter = pane._module, pane._book, pane._chapter
        paper = self._paper()
        shape = self._shapes[self._shape_row.get_selected()]
        wordmark = self._mark_row.get_active()
        reference = self._reference()

        def work(_token):
            from pane import auto_reading_ink
            text = passage_export.verse_text(module, book, chapter, verses)
            return verse_card.render(
                path, text=text, reference=reference, translation=module,
                paper=paper, ink=auto_reading_ink(paper), shape=shape,
                wordmark=wordmark)

        tasks.submit(key=f'verse-card:{id(pane)}', work=work,
                     apply=lambda _p: self._report(
                         _('Saved {name}').format(
                             name=GLib.path_get_basename(path))),
                     on_error=lambda _e: self._report(
                         _('Could not write the image')))

    def _report(self, message):
        if self._pane._on_toast:
            self._pane._on_toast(message)
