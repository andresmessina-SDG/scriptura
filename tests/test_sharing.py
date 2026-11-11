"""Sharing keeps the selected words, citation and destination together."""
from types import SimpleNamespace

import cairo
import gi
import pytest
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

import annotation_dialogs
import content
import export_dialog
import passage_export
import passage_print
import pane as pane_module
import sword_bridge
import verse_card


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(content, 'load_chapter', lambda *a: [
        (16, '<w>For</w><w>God</w> loved the world.'),
        (18, 'The eighteenth verse.')])
    monkeypatch.setattr(sword_bridge, 'chapter_headings', lambda *a: {})
    monkeypatch.setattr(sword_bridge, 'chapter_titles', lambda *a: {})
    monkeypatch.setattr(sword_bridge, 'module_info', lambda *a: {})
    monkeypatch.setattr(sword_bridge, 'mapped_chapter', lambda *a: None)
    monkeypatch.setattr(sword_bridge, 'chapter_lines', lambda *a: None)
    monkeypatch.setattr(passage_export, 'interlinear_module_for', lambda *a: None)
    said, copied = [], []
    clipboard = SimpleNamespace(set=copied.append)
    pane = SimpleNamespace(module='KJV', book='John', chapter=3,
                           _on_toast=said.append,
                           view=SimpleNamespace(get_clipboard=lambda: clipboard),
                           get_root=lambda: None,
                           reading_appearance=lambda: {})
    return pane, said, copied


def _sheet(cls, source):
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display')
    Adw.init()
    return cls(source[0], [16, 18])


def test_copy_preserves_word_boundaries_and_gaps(source):
    annotation_dialogs.copy_verse(source[0], [16, 18],
                                 SimpleNamespace(popdown=lambda: None))
    text = source[2][0]
    assert text.startswith('John 3:16, 18 (KJV)\n')
    assert 'For God loved the world.' in text


@pytest.mark.parametrize('cls', [export_dialog.ExportSheet, export_dialog.CardSheet])
def test_sheet_keeps_original_passage_after_navigation(cls, source, monkeypatch, tmp_path):
    sheet = _sheet(cls, source)
    calls = []
    monkeypatch.setattr(content, 'load_chapter',
                        lambda *a: calls.append(a) or [(16, 'Original passage.')])
    # Audio or linked navigation can advance the pane while its sheet is open.
    source[0].module, source[0].book, source[0].chapter = 'ASV', 'Romans', 8
    path = tmp_path / ('card.png' if cls is export_dialog.CardSheet else 'passage.md')
    sheet._dialog = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(export_dialog.tasks, 'submit',
                        lambda **kw: kw['apply'](kw['work'](None)))
    sheet._on_chosen(SimpleNamespace(save_finish=lambda r: Gio.File.new_for_path(str(path))), None)
    # The card reads its words when the sheet opens, so it reads nothing now;
    # the text export reads the place it opened on.
    assert calls == ([] if cls is export_dialog.CardSheet else [('KJV', 'John', 3)])
    assert path.exists()


def test_card_copy_keeps_original_passage(source, monkeypatch):
    sheet = _sheet(export_dialog.CardSheet, source)
    source[0].chapter = 4
    calls = []
    monkeypatch.setattr(verse_card, 'render_bytes', lambda **kw: calls.append(kw))
    sheet._card_bytes()
    assert calls[0]['reference'] == 'John 3:16, 18'


def test_failed_clipboard_keeps_card_open(source, monkeypatch):
    sheet = _sheet(export_dialog.CardSheet, source)
    closed = []
    sheet._dialog = SimpleNamespace(close=lambda: closed.append(True))
    source[0].get_root = lambda: SimpleNamespace(
        get_clipboard=lambda: SimpleNamespace(set_content=lambda p: False))
    sheet._copy()
    assert not closed
    assert source[1] and source[1][-1] != 'Card copied'


def test_card_render_failure_is_reported(source, monkeypatch):
    sheet = _sheet(export_dialog.CardSheet, source)
    def fail():
        raise RuntimeError('render failed')
    monkeypatch.setattr(sheet, '_card_bytes', fail)
    sheet._copy()
    assert source[1]


def test_mapped_passage_cites_the_translation_numbering(source, monkeypatch):
    monkeypatch.setattr(sword_bridge, 'mapped_chapter', lambda *a: ('Psalms', 22))
    text = passage_export.build('KJV', 'Psalms', 23, [16], notes=False)
    assert text.startswith('# Ps 22:16 KJV\n')


def test_split_passage_cites_both_printed_chapters(source, monkeypatch):
    monkeypatch.setattr(sword_bridge, 'mapped_chapter', lambda *a: ('Psalms', 114))
    monkeypatch.setattr(sword_bridge, 'chapter_lines', lambda *a: [
        (16, 'Psalms', 114, 9), (18, 'Psalms', 115, 1)])
    text = passage_export.build('KJV', 'Psalms', 116, [16, 18], notes=False)
    assert text.startswith('# Ps 114:9; Ps 115:1 KJV\n')


def test_print_preparation_failure_is_reported(source, monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError('load failed')
    monkeypatch.setattr(passage_print, 'build_operation', fail)
    passage_print.print_passage(source[0], [16])
    assert source[1] == ['Could not print the passage']


def test_print_error_result_is_reported(source, monkeypatch):
    monkeypatch.setattr(passage_print, 'build_operation', lambda *a, **kw:
                        SimpleNamespace(run=lambda *a: Gtk.PrintOperationResult.ERROR))
    passage_print.print_passage(source[0], [16])
    assert source[1] == ['Could not print the passage']


def test_unbroken_card_text_fits_horizontally():
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 1080, 1080))
    layout = verse_card._fit(ctx, 'x' * 200, 800, 560, 67)
    assert layout.get_pixel_size().width <= 800


def test_export_keeps_underlining_and_mapped_note_citation(source, monkeypatch):
    monkeypatch.setattr(sword_bridge, 'mapped_chapter', lambda *a: ('Psalms', 22))
    monkeypatch.setattr(passage_export.annotations_store, 'get_annotations',
                        lambda *a: {'16': {'underline': True}})
    text = passage_export.build('KJV', 'Psalms', 23, [16])
    assert '**Ps 22:16** — underlined' in text


def test_study_layers_look_up_the_app_verse_not_the_rendered_key(source, monkeypatch):
    monkeypatch.setattr(sword_bridge, 'map_verse_to_app', lambda *a: 17)
    calls = []
    for name in ('interlinear_rows', 'variant_rows', 'catena_rows'):
        monkeypatch.setattr(passage_export, name,
                            lambda b, ch, vs: calls.append((b, ch, vs)) or [])
    passage_export.build('KJV', 'John', 3, [16], notes=False,
                         interlinear=True, variants=True, catena=True)
    assert calls == [('John', 3, [17])] * 3


def test_sharing_decodes_entities_without_losing_literal_brackets(source, monkeypatch):
    monkeypatch.setattr(content, 'load_chapter', lambda *a:
                        [(16, '<w>A</w>&amp; B &lt;aside&gt; &#8220;word&#8221;')])
    expected = 'A & B <aside> “word”'
    assert passage_export.verse_text('KJV', 'John', 3, [16]) == expected
    assert expected in passage_export.build('KJV', 'John', 3, [16],
                                            notes=False, markdown=False)
    assert r'\<aside\>' in passage_export.build('KJV', 'John', 3, [16], notes=False)
    annotation_dialogs.copy_verse(source[0], [16],
                                 SimpleNamespace(popdown=lambda: None))
    assert expected in source[2][0]


def test_selection_copy_omits_visible_footnote_markers(source):
    buffer = Gtk.TextBuffer()
    buffer.set_text('For Goda loved the world.b')
    tag = buffer.create_tag('fn_marker')
    for start, end in ((7, 8), (25, 26)):
        buffer.apply_tag(tag, buffer.get_iter_at_offset(start), buffer.get_iter_at_offset(end))
    buffer.select_range(*buffer.get_bounds())
    fake = SimpleNamespace(_module='KJV', _book='John', _chapter=3,
                           _buffer=buffer, _verses_in_range=lambda *a: [16, 18])
    view = SimpleNamespace(get_clipboard=source[0].view.get_clipboard,
                           stop_emission_by_name=lambda *a: None)
    pane_module.BiblePane._on_copy_clipboard(fake, view)
    assert source[2] == ['John 3:16, 18 (KJV)\nFor God loved the world.']


def test_card_clipboard_offers_serializable_png(source):
    sheet = _sheet(export_dialog.CardSheet, source)
    providers, closed = [], []
    source[0].get_root = lambda: SimpleNamespace(get_clipboard=lambda:
        SimpleNamespace(set_content=lambda p: providers.append(p) or True))
    sheet._dialog = SimpleNamespace(close=lambda: closed.append(True))
    sheet._copy()
    assert closed and source[1] == ['Card copied']
    provider = providers[0]
    assert provider.ref_formats().contain_mime_type('image/png')
    assert any(t.is_a(Gdk.Texture.__gtype__)
               for t in provider.ref_formats().get_gtypes())
    stream = Gio.MemoryOutputStream.new_resizable()
    done = []
    def written(obj, result, *a):
        done.append(obj.write_mime_type_finish(result))
    provider.write_mime_type_async('image/png', stream, GLib.PRIORITY_DEFAULT,
                                   None, written)
    import time
    deadline = time.monotonic() + 5
    while not done and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(False)
    assert done == [True]
    stream.close(None)
    assert stream.steal_as_bytes().get_data() == sheet._card_bytes()


@pytest.mark.parametrize('cls', [export_dialog.ExportSheet, export_dialog.CardSheet])
def test_failed_write_reports_failure_not_success(cls, source, monkeypatch, tmp_path):
    sheet = _sheet(cls, source)
    sheet._dialog = SimpleNamespace(close=lambda: None)
    def submit(**kw):
        try:
            kw['work'](None)
        except Exception as exc:
            kw['on_error'](exc)
        else:
            pytest.fail('writing to a missing directory should fail')
    monkeypatch.setattr(export_dialog.tasks, 'submit', submit)
    path = tmp_path / 'missing' / 'file'
    sheet._on_chosen(SimpleNamespace(save_finish=lambda r: Gio.File.new_for_path(str(path))), None)
    assert source[1] == ['Could not write the image' if cls is export_dialog.CardSheet
                         else 'Could not write the file']


@pytest.mark.parametrize('cls', [export_dialog.ExportSheet, export_dialog.CardSheet])
def test_cancelled_save_keeps_sheet_open(cls, source, monkeypatch):
    sheet = _sheet(cls, source)
    closed, submitted = [], []
    sheet._dialog = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(export_dialog.tasks, 'submit', lambda **kw: submitted.append(kw))
    def cancelled(result):
        raise GLib.Error.new_literal(Gtk.dialog_error_quark(), 'cancelled',
                                     Gtk.DialogError.DISMISSED)
    sheet._on_chosen(SimpleNamespace(save_finish=cancelled), None)
    assert not closed and not submitted and not source[1]


def test_a_long_card_cuts_at_a_whole_verse_and_cites_only_that(source, monkeypatch):
    rows = [(v, f'Verse {v} of a psalm too long for any card to carry whole. ' * 2)
            for v in range(1, 177)]
    monkeypatch.setattr(content, 'load_chapter', lambda *a: rows)
    sheet = export_dialog.CardSheet.__new__(export_dialog.CardSheet)
    sheet._module, sheet._book, sheet._chapter = 'KJV', 'Psalms', 119
    sheet._verses = list(range(1, 177))
    sheet._rows = export_dialog.card_rows('KJV', 'Psalms', 119, sheet._verses)
    sheet._counts = {}
    sheet._shape = lambda: 'square'
    shown = sheet._shown()
    assert 1 < len(shown) < 176
    assert sheet._is_cut()
    assert sheet._reference() == f'Psalms 119:1{passage_export.EN_DASH}{len(shown)}'


def test_shown_count_keeps_a_passage_that_fits_and_one_verse_that_does_not():
    assert verse_card.shown_count(['For God so loved the world.'] * 3) == 3
    assert verse_card.shown_count(['word ' * 5000]) == 1
    assert verse_card.shown_count([]) == 0


def test_cut_text_stays_at_or_above_the_readable_size():
    texts = ['Blessed are the undefiled in the way. ' * 2] * 120
    for shape, (w, h) in verse_card.SHAPES.items():
        n = verse_card.shown_count(texts, shape)
        _m, column = verse_card._metrics(w, h)
        ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, w, h))
        layout = verse_card._fit(ctx, ' '.join(texts[:n]), column,
                                 h * verse_card.VERSE_SHARE, int(min(w, h) * 0.062))
        assert not layout.is_ellipsized()
        size = layout.get_font_description().get_size() / 1024
        assert size >= int(min(w, h) * verse_card.READABLE)


def test_fit_halves_the_range_instead_of_stepping(monkeypatch):
    made = []
    real = verse_card._layout
    monkeypatch.setattr(verse_card, '_layout',
                        lambda *a, **kw: made.append(1) or real(*a, **kw))
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 1080, 1080))
    verse_card._fit(ctx, 'Blessed are the undefiled in the way. ' * 60, 840, 560, 67)
    assert len(made) <= 8


def test_balanced_lines_leave_no_lone_last_word():
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 1080, 1080))
    text = 'For God so loved the world, that he gave his only begotten Son.'
    layout = verse_card._fit(ctx, text, 840, 560, 67)
    lines = layout.get_line_count()
    width = verse_card._balanced(layout, 840)
    assert width < 840 and layout.get_line_count() == lines
    last = layout.get_line_readonly(lines - 1)
    assert ' ' in text[last.start_index:last.start_index + last.length].strip()


def test_card_sheet_preview_is_the_full_card_in_each_shape(source):
    sheet = _sheet(export_dialog.CardSheet, source)
    assert not sheet._cut_note.get_visible()
    for index, shape in enumerate(sheet._shapes):
        sheet._shape_row.set_selected(index)
        w, h = verse_card.SHAPES[shape]
        assert (sheet._card.get_width(), sheet._card.get_height()) == (w, h)
        fit = min(export_dialog.PREVIEW_W / w, export_dialog.PREVIEW_H / h)
        assert (sheet._preview.get_content_width(),
                sheet._preview.get_content_height()) == (round(w * fit), round(h * fit))


def test_card_sets_the_marked_divine_name_in_small_caps(monkeypatch):
    monkeypatch.setattr(content, 'load_chapter', lambda *a: [
        (1, '<w>The <divineName>Lord</divineName></w> is my shepherd &amp; guide;')])
    [(_v, markup)] = export_dialog.card_rows('KJVA', 'Psalms', 23, [1])
    assert markup == 'The <span variant="small-caps">Lord</span> is my shepherd &amp; guide;'
    [(_v, plain)] = export_dialog.card_rows('KJVA', 'Psalms', 23, [1], smallcaps=False)
    assert plain == 'The Lord is my shepherd &amp; guide;'


def test_card_sets_literal_capitals_but_not_an_inscription(monkeypatch):
    monkeypatch.setattr(content, 'load_chapter', lambda *a: [
        (1, 'The LORD is my shepherd.'), (2, 'HOLINESS TO THE LORD.')])
    rows = dict(export_dialog.card_rows('BSB', 'Psalms', 23, [1, 2]))
    assert rows[1] == 'The L<span variant="small-caps">ord</span> is my shepherd.'
    assert rows[2] == 'HOLINESS TO THE LORD.'


def test_card_text_with_markup_characters_renders(monkeypatch):
    monkeypatch.setattr(content, 'load_chapter', lambda *a: [(1, 'a &lt;b&gt; &amp; c')])
    [(_v, markup)] = export_dialog.card_rows('KJV', 'John', 1, [1])
    verse_card.render_bytes(text=markup, reference='John 1:1', translation='A & B',
                            paper='#f7f4ee', ink='#2b2620')


def test_an_empty_verse_opens_no_card(source, monkeypatch):
    monkeypatch.setattr(content, 'load_chapter', lambda *a: [(16, '<w></w> ')])
    opened = []
    monkeypatch.setattr(export_dialog, 'CardSheet', lambda *a: opened.append(a))
    export_dialog.share_as_image(source[0], [16])
    assert not opened
    assert source[1] == ['There is no text here to put on a card']
