"""The reader never presses Save.

A note and its tags write themselves once typing pauses, which is what the
highlight and the underline beside them have always done — the pane had two
save models and now has one. These hold the three things that model can get
wrong: writing the words under the wrong mark, throwing the list away while
someone is typing into it, and resurrecting a note on its way to the bin.
"""
import pytest

import annotations
import annotations_window


@pytest.fixture
def display():
    """Skip when there is no screen: the window is a real Adw.Window.

    `Gdk.Display.get_default()`, never `Gtk.init_check()` — the latter
    returns True with no display and the GTK paths below then segfault
    (GUIDANCE §4).
    """
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: the Annotations window is a real '
                    'Adw.Window')


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_verse_map_cache', {})
    return tmp_path


def _rows(win):
    row = win._list.get_first_child()
    while row is not None:
        if hasattr(row, '_entry'):
            yield row
        row = row.get_next_sibling()


def _select(win, book, chapter, verse):
    for row in _rows(win):
        e = row._entry
        if (e['book'], e['chapter'], e['app_verse']) == (book, chapter, verse):
            win._list.select_row(row)
            return row
    raise AssertionError(f'no row for {book} {chapter}:{verse}')


def _type(win, text):
    win._mark_editor.note.get_buffer().set_text(text)


def test_typing_then_pausing_reaches_the_store(isolated, display):
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        _select(win, 'Genesis', 1, 1)
        _type(win, 'in the beginning')
        assert win._autosave.pending
        win._autosave.flush()
        assert annotations.get_annotations(
            'KJVA', 'Genesis', 1)['1']['note'] == 'in the beginning'
    finally:
        win.destroy()


def test_merely_opening_an_entry_queues_no_write(isolated, display):
    """_populate_detail calls set_text, which emits `changed`. Without the
    gate, clicking down a list would rewrite every mark it passed."""
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'first')
    annotations.save_note('KJVA', 'John', 3, 16, 'second')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        _select(win, 'Genesis', 1, 1)
        assert not win._autosave.pending
        _select(win, 'John', 3, 16)
        assert not win._autosave.pending
    finally:
        win.destroy()


def test_switching_entries_files_the_words_under_the_one_being_left(
        isolated, display):
    """The trap this whole design turns on. The fields still hold the
    outgoing entry's text when the selection changes; flushing after
    _populate_detail had run would file Genesis's words under John's."""
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'first')
    annotations.save_note('KJVA', 'John', 3, 16, 'second')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        _select(win, 'Genesis', 1, 1)
        _type(win, 'rewritten')
        _select(win, 'John', 3, 16)          # no flush of our own
        assert annotations.get_annotations(
            'KJVA', 'Genesis', 1)['1']['note'] == 'rewritten'
        assert annotations.get_annotations(
            'KJVA', 'John', 3)['16']['note'] == 'second'
    finally:
        win.destroy()


def test_a_write_patches_the_open_row_and_does_not_rebuild_the_list(
        isolated, display):
    """No _reload() on a timer: rebuilding would throw away every row while
    the reader is typing into one, and under "Recently edited" it would walk
    the open row up the sidebar under the cursor. The row object must be the
    same one afterwards, carrying the new words."""
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'first')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        row = _select(win, 'Genesis', 1, 1)
        _type(win, 'patched in place')
        win._autosave.flush()

        assert win._list.get_selected_row() is row
        assert row._entry['note'] == 'patched in place'
        labels = []
        def walk(w):
            from gi.repository import Gtk
            if isinstance(w, Gtk.Label):
                labels.append(w.get_text())
            child = w.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()
        walk(row)
        assert 'patched in place' in labels
    finally:
        win.destroy()


def test_deleting_drops_the_queued_write_instead_of_filing_it(
        isolated, display):
    """Undo restores what was deleted; a pending write must not restore what
    was typed on the way to deleting it."""
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'first')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        row = _select(win, 'Genesis', 1, 1)
        _type(win, 'about to be deleted')
        assert win._autosave.pending
        win._on_delete_entry(None, row._entry)
        assert not win._autosave.pending
        assert annotations.get_annotations('KJVA', 'Genesis', 1) == {}
    finally:
        win.destroy()


def test_closing_the_window_flushes_what_is_still_queued(isolated, display):
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        _select(win, 'Genesis', 1, 1)
        _type(win, 'last words')
        win.emit('close-request')
        assert annotations.get_annotations(
            'KJVA', 'Genesis', 1)['1']['note'] == 'last words'
    finally:
        win.destroy()


def test_tags_autosave_too(isolated, display):
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'first')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        _select(win, 'Genesis', 1, 1)
        win._mark_editor.tags.set_text('creation, covenant')
        win._autosave.flush()
        assert annotations.get_annotations(
            'KJVA', 'Genesis', 1)['1']['tags'] == ['creation', 'covenant']
    finally:
        win.destroy()
