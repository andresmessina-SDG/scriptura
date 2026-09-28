"""A mark's note is writing, so it is set as the journal is: the writing
face and leading, and the reading measure. It was the chrome's sans at the
full width of the pane — the one writing surface left outside the rule that
nothing the reader types is set in the sans."""
import pytest
from gi.repository import Gdk, Gtk

import annotations
import annotation_editors
import settings
import writing_page


@pytest.fixture
def display():
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display')


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)


def _mark_editor():
    return annotation_editors.MarkEditor(
        on_edited=lambda *a: None, on_store_changed=lambda *a: None,
        on_navigate=lambda *a: None, on_title=lambda *a: None,
        on_flush=lambda: None, on_row_changed=lambda *a: None,
        on_regroup=lambda: None, reading_module=lambda: 'KJV',
        quote=lambda *a: '', on_collect=None, on_open_entry=lambda *a: None)


def test_the_note_wears_the_writing_face(isolated, display):
    ed = _mark_editor()
    assert ed.note.has_css_class('writing-note')
    writing_page.refresh_writing_style()
    css = writing_page._WRITING_CSS.to_string()
    assert '.writing-note' in css


def test_the_note_keeps_the_reading_measure(isolated, display, monkeypatch):
    monkeypatch.setattr(settings, 'get', lambda k, *a: 540
                        if k == 'reading_width' else settings.default(k))
    ed = _mark_editor()
    ed._fit_note(1000)
    assert ed.note.get_left_margin() == ed.note.get_right_margin() == 230
    # Narrower than the measure: the note's own margin, never less.
    ed._fit_note(400)
    assert ed.note.get_left_margin() == 12


def test_add_to_the_sermon_sits_beside_the_verse_chip(isolated, display):
    annotations.save_note(None, 'John', 3, 16, 'Given, not lent.')
    import annotations_window
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        row = win._list.get_row_at_index(0)
        win._list.select_row(row)
        ed = win._mark_editor
        assert ed._collect_btn.get_parent() is ed._go_box
        # The chip first, then the door.
        assert ed._go_box.get_last_child() is ed._collect_btn
        # Repopulating does not lose it.
        win._populate_detail(row._entry)
        assert ed._collect_btn.get_parent() is ed._go_box
    finally:
        win.destroy()


def test_opening_a_note_does_not_restyle_the_whole_app(isolated, display,
                                                        monkeypatch):
    """Loading the writing sheet's CSS restyles every widget on the display.
    It is for a change of face or leading, not for every note opened."""
    writing_page.refresh_writing_style()
    loads = []
    real = writing_page._WRITING_CSS.load_from_data
    monkeypatch.setattr(writing_page._WRITING_CSS, 'load_from_data',
                        lambda data: loads.append(1) or real(data))
    _mark_editor()
    _mark_editor()
    assert loads == []
