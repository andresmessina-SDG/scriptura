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


def _labels(row):
    stack, out = [row], []
    while stack:
        w = stack.pop()
        if hasattr(w, 'get_label') and isinstance(w.get_label(), str):
            out.append(w.get_label())
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def test_a_mark_without_a_note_shows_its_verse(isolated, display, monkeypatch):
    """A row said only a colour, so finding a mark meant opening each one."""
    monkeypatch.setattr(annotations_window.annotation_editors.MarkEditor,
                        '_verse_text', lambda self, b, c, v: 'For God so\nloved')
    annotations.save_highlight('KJVA', 'John', 3, 16, '#ffff00')
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'my note')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        john = _select(win, 'John', 3, 16)
        assert 'For God so loved' in _labels(john)
        genesis = _select(win, 'Genesis', 1, 1)
        assert 'my note' in _labels(genesis)
        assert 'For God so loved' not in _labels(genesis)
    finally:
        win.destroy()


def test_the_list_follows_a_mark_made_elsewhere(isolated, display):
    """No Refresh button: a save from the reading view rebuilds the list, but
    a save made while this window is in use leaves the rows alone."""
    annotations.save_highlight('KJVA', 'John', 3, 16, '#ffff00')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        win.get_visible = lambda: True
        win.is_active = lambda: True
        annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
        assert not win._store_reload_pending

        win.is_active = lambda: False
        annotations.save_underline('KJVA', 'Mark', 1, 1, True)
        annotations.save_note('KJVA', 'Mark', 1, 1, 'twice, one rebuild')
        assert win._store_reload_pending
        win._reload_from_store()
        assert len(list(_rows(win))) == 3
    finally:
        win.destroy()
    assert annotations._on_change is None


def test_a_mark_made_elsewhere_leaves_the_open_manuscript_alone(
        isolated, display, monkeypatch):
    """The live list rebuilds the detail pane too. Re-populating the open
    sermon with the words it already holds moved the cursor to the end,
    dropped the scroll and cleared the undo history — for underlining a
    verse in the reading view."""
    import sermons
    monkeypatch.setattr(sermons, 'SERMONS_FILE',
                        str(isolated / 'sermons.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    body = '\n'.join(f'Paragraph {i} of the manuscript.' for i in range(80))
    sermons.save('s1', title='The Sower', body=body,
                 anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []}])
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        win.select_sermon('s1')
        buf = win._sermon_editor.body.get_buffer()
        buf.place_cursor(buf.get_iter_at_offset(600))
        buf.begin_user_action()
        buf.insert_at_cursor(' amen')
        buf.end_user_action()
        win._autosave.flush()
        assert buf.get_can_undo()

        win.get_visible = lambda: True
        win.is_active = lambda: False
        annotations.save_underline('KJVA', 'Mark', 1, 1, True)
        win._reload_from_store()

        assert win._current_entry['id'] == 's1'
        assert buf.get_iter_at_mark(buf.get_insert()).get_offset() == 605
        assert buf.get_can_undo()
        assert buf.get_text(*buf.get_bounds(), False) == body[:600] + ' amen' + body[600:]
    finally:
        win.destroy()


def test_restore_writes_the_pending_edit_before_replacing_the_stores(
        monkeypatch):
    """A restore reloads the Annotations window, and the reload flushes the
    autosave: the pre-restore words went over the restored store, while
    the editor showed the restored ones. The flush now comes first."""
    import types
    import backup
    from window import BibleWindow

    order = []
    fake = types.SimpleNamespace(
        _annotations_win=types.SimpleNamespace(
            _autosave=types.SimpleNamespace(flush=lambda: order.append('flush')),
            get_visible=lambda: True, _reload=lambda: order.append('reload')),
        pane1=types.SimpleNamespace(_fetch_and_render=lambda: None),
        pane2=types.SimpleNamespace(_fetch_and_render=lambda: None),
        _menu_panel_built=False, _toast=lambda *_a: None)
    monkeypatch.setattr(backup, 'restore',
                        lambda payload: order.append('restore') or [])
    BibleWindow._on_restore_confirm(fake, None, 'replace', {})
    assert order == ['flush', 'restore', 'reload']


def test_closing_the_main_window_flushes_the_annotations_window(monkeypatch):
    """The Annotations window is transient, not an application window, so
    closing the main window ends the process without ever closing or
    destroying it — and a GLib timeout dies with the process. A sentence
    typed into a sermon within the autosave delay of clicking the main
    window's close button was the one sentence that never reached disk."""
    import types
    import settings
    import module_positions
    from window import BibleWindow

    flushed = []
    fake = types.SimpleNamespace(
        _annotations_win=types.SimpleNamespace(
            _autosave=types.SimpleNamespace(flush=lambda: flushed.append(1))),
        is_maximized=lambda: True, _current_loc=('Genesis', 1),
        pane1=types.SimpleNamespace(module='KJVA',
                                    _save_position_to_module_state=lambda: None),
        pane2=types.SimpleNamespace(module='KJVA',
                                    _save_position_to_module_state=lambda: None))
    monkeypatch.setattr(settings, 'put', lambda *_a: None)
    monkeypatch.setattr(settings, 'flush', lambda: None)
    monkeypatch.setattr(module_positions, 'flush', lambda: None)
    BibleWindow._on_close_request(fake, None)
    assert flushed == [1]
