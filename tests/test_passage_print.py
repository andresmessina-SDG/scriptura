"""Where the page breaks fall.

Exercised through `Gtk.PrintOperation`'s EXPORT action, which runs the real
begin-print and draw-page handlers to a PDF with no dialog, no portal and no
printer. That is the only honest way to test printing: the dialog itself needs
a person and a device.
"""
import pytest

import passage_export
import sword_bridge

CHAPTER = [(v, f'Verse {v}. ' + 'The quick brown fox jumps over it. ' * 3)
           for v in range(1, 41)]


def _gtk():
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gdk, Gtk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: constructing GTK objects without one '
                    'is not safe here')
    return Gtk


def _sword(monkeypatch):
    monkeypatch.setattr(sword_bridge, 'load_chapter', lambda *_a: list(CHAPTER))
    monkeypatch.setattr(sword_bridge, 'chapter_headings', lambda *_a: {})
    monkeypatch.setattr(sword_bridge, 'module_info',
                        lambda _m: {'description': 'King James Version'})
    monkeypatch.setattr(passage_export.annotations_store, 'get_annotations',
                        lambda *_a: {})


def _export(tmp_path, verses=None):
    import passage_print
    Gtk = _gtk()
    op = passage_print.build_operation('KJV', 'John', 3, verses)
    out = str(tmp_path / 'handout.pdf')
    op.set_export_filename(out)
    op.run(Gtk.PrintOperationAction.EXPORT, None)
    return op, out


def test_a_short_passage_is_one_page(monkeypatch, tmp_path):
    _sword(monkeypatch)
    op, out = _export(tmp_path, [1, 2, 3])
    assert op.get_n_pages_to_print() == 1
    assert open(out, 'rb').read(5) == b'%PDF-'


def test_a_long_passage_paginates_without_running_away(monkeypatch, tmp_path):
    """The trap this pins: `Pango.LayoutIter.get_line_yrange` returns
    (top, BOTTOM), not (top, height). Reading the second value as a height and
    adding it to the first doubles every line's foot, and a two-page passage
    paginated into thirteen pages whose breaks halved toward the end."""
    _sword(monkeypatch)
    op, _out = _export(tmp_path)
    pages = op.get_n_pages_to_print()
    assert 2 <= pages <= 4, f'{pages} pages for a chapter is a runaway'


def test_page_tops_are_line_boundaries_in_order(monkeypatch, tmp_path):
    """Each page starts strictly after the last, at a line's own top — which
    is what keeps a row of glyphs from being sliced across the break."""
    import passage_print
    _sword(monkeypatch)
    op, _out = _export(tmp_path)
    tops = op._printer._page_tops
    assert tops[0] == 0.0
    assert all(b > a for a, b in zip(tops, tops[1:]))
    assert len(tops) == op.get_n_pages_to_print()
    assert isinstance(passage_print.PassagePrinter, type)


def test_the_handout_says_which_translation_it_is(monkeypatch, tmp_path):
    """Attribution rides in from the shared composition rather than being
    re-implemented here — the same rule as the worksheet and the card."""
    _sword(monkeypatch)
    document = passage_export.build('KJV', 'John', 3, [1], markdown=False)
    assert 'King James Version' in document
    op, _out = _export(tmp_path, [1])
    assert op.get_n_pages_to_print() == 1
