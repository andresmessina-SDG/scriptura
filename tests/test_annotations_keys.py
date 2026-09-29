"""Esc in the Annotations window, and the rows a new page leaves behind.

The window used to borrow the main window's Esc-close: a bubble key
controller that ran before the writing-mode shortcut, so Esc never left
writing mode — it closed the window instead — and Esc over a reference card
closed the card and the window together. The earlier tests called
`_leave_writing_mode()` by hand and never saw it. These go through the
controllers the window actually has.
"""
import types

import pytest
from gi.repository import Gdk, Gtk

import annotations
import annotations_window
import journal
import sermons
import window


@pytest.fixture
def display():
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
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(journal, '_load_failed', False)
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 'sermons.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    monkeypatch.setattr(sermons, '_load_failed', False)
    return tmp_path


def _window():
    return annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)


def _capture_keys(win):
    return [c for c in win.observe_controllers()
            if isinstance(c, Gtk.EventControllerKey)
            and c.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE]


def _press(ctl, keyval):
    return ctl.emit('key-pressed', keyval, 0, 0)


def test_escape_in_writing_mode_is_taken_before_anything_below_it(
        isolated, display):
    """Capture phase runs before every bubble handler — the toast overlay
    that ate the first Esc, and any close-on-Esc — so the mode is left."""
    win = _window()
    try:
        win._set_writing_mode(True)
        handled = [c for c in _capture_keys(win) if _press(c, Gdk.KEY_Escape)]
        assert handled, 'no capture-phase handler took Esc in writing mode'
        assert not win._writing_mode
        # Out of the mode, the capture handler stands aside.
        assert not any(_press(c, Gdk.KEY_Escape) for c in _capture_keys(win))
    finally:
        win.destroy()


def test_the_main_window_does_not_attach_its_esc_close(monkeypatch):
    """The Annotations window owns its Esc; a second, bubble-phase close
    would run ahead of it again."""
    seen = {}
    made = types.SimpleNamespace(present=lambda: None,
                                 connect=lambda *a: None,
                                 get_visible=lambda: True)
    monkeypatch.setattr(window, 'AnnotationsWindow', lambda **kw: made)
    fake = types.SimpleNamespace(
        _annotations_win=None, _on_annotations_navigate=None,
        _refresh_panes=None, pane1=types.SimpleNamespace(module='KJV'),
        _refresh_plan_dots=lambda: None,
        _attach_esc_close=lambda win, slot, esc=True: seen.update(esc=esc))
    window.BibleWindow._open_annotations(fake)
    assert seen == {'esc': False}


def test_attach_esc_close_without_esc_adds_no_key_controller(display):
    win = Gtk.Window()
    try:
        def keys():
            return [c for c in win.observe_controllers()
                    if isinstance(c, Gtk.EventControllerKey)]
        before = len(keys())   # GTK's own window controllers
        fake = types.SimpleNamespace()
        window.BibleWindow._attach_esc_close(fake, win, 'slot', esc=False)
        assert len(keys()) == before
        window.BibleWindow._attach_esc_close(fake, win, 'slot')
        assert len(keys()) == before + 1
    finally:
        win.destroy()


def _escape_shortcut(win):
    """What the window's own Esc does once nothing below has taken it."""
    return win._on_escape()


def test_escape_while_typing_does_not_close_the_window(isolated, display):
    journal.save('e1', title='Kept', body='words')
    win = _window()
    closed = []
    win.close = lambda: closed.append(True)
    try:
        win.set_mode('journal')
        win.select_entry('e1')
        for field in (win._entry_editor.body, win._entry_editor.title,
                      win._search_entry):
            field.grab_focus()
            win.set_focus(field)
            assert _escape_shortcut(win) is False
        assert not closed
    finally:
        win.destroy()


def test_escape_elsewhere_closes_the_window(isolated, display):
    win = _window()
    closed = []
    win.close = lambda: closed.append(True)
    try:
        win.set_focus(None)
        assert _escape_shortcut(win) is True
        assert closed
    finally:
        win.destroy()


def test_ctrl_w_closes_from_anywhere(isolated, display):
    journal.save('e1', title='Kept', body='words')
    win = _window()
    closed = []
    win.close = lambda: closed.append(True)
    try:
        win.set_mode('journal')
        win.select_entry('e1')
        win.set_focus(win._entry_editor.body)
        shortcuts = [c for c in win.observe_controllers()
                     if isinstance(c, Gtk.ShortcutController)]
        triggers = [str(s.get_trigger().to_string())
                    for c in shortcuts for s in c]
        assert '<Control>w' in triggers
        win._close_window()
        assert closed
    finally:
        win.destroy()


def test_escape_closes_the_reference_card_and_stops_there(isolated, display):
    journal.save('e1', title='Kept', body='See John 3:16 today.')
    win = _window()
    try:
        win.set_mode('journal')
        win.select_entry('e1')
        ed = win._entry_editor
        hit = [r for r in ed.refs if r[2] == 'John'][0]
        ed._offer_ref(hit)
        assert ed._ref_card.get_visible()
        assert ed._dismiss_ref_card() is True
        assert not ed._ref_card.get_visible()
        # No card up: Esc is not the body's to take.
        assert ed._dismiss_ref_card() is False
    finally:
        win.destroy()


def _row_ids(win):
    out = []
    row = win._list.get_first_child()
    while row is not None:
        if hasattr(row, '_entry'):
            out.append(row._entry.get('id'))
        row = row.get_next_sibling()
    return out


def _settle():
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


@pytest.mark.parametrize('mode', ['journal', 'sermons'])
def test_a_new_page_left_unwritten_leaves_the_list(isolated, display, mode):
    if mode == 'journal':
        journal.save('kept', title='Kept', body='words')
    else:
        sermons.save('kept', title='Kept', body='words')
    win = _window()
    try:
        win.set_mode(mode)
        fresh = (win.start_entry() if mode == 'journal'
                 else win.start_sermon())
        assert fresh['id'] in _row_ids(win)
        win.select_entry('kept') if mode == 'journal' else win.select_sermon('kept')
        _settle()
        assert _row_ids(win) == ['kept']
        assert win._count_lbl.get_text().startswith('1 ')
    finally:
        win.destroy()


def test_a_new_page_with_words_stays(isolated, display):
    journal.save('kept', title='Kept', body='words')
    win = _window()
    try:
        win.set_mode('journal')
        fresh = win.start_entry()
        win._entry_editor.title.set_text('Begun')
        win.select_entry('kept')
        _settle()
        assert fresh['id'] in _row_ids(win)
        assert journal.get(fresh['id'])['title'] == 'Begun'
    finally:
        win.destroy()


def _all_triggers(root):
    found = set()

    def walk(w):
        for c in w.observe_controllers():
            if isinstance(c, Gtk.ShortcutController):
                for s in c:
                    found.add(s.get_trigger().to_string())
        child = w.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()
    walk(root)
    return found


def test_every_key_the_writing_section_names_is_bound(isolated, display):
    """The shortcuts dialog's Writing rows are typed by hand; this holds
    them to the controllers the window and its editors really carry."""
    section = dict(window.BibleWindow._SHORTCUT_SECTIONS)['Writing']
    win = _window()
    try:
        bound = _all_triggers(win)
        for desc, kind, value in section:
            if kind != 'accel':
                continue
            for accel in value.split():
                trig = Gtk.ShortcutTrigger.parse_string(accel).to_string()
                assert trig in bound, f'{desc}: {accel} is not bound'
    finally:
        win.destroy()


def test_ctrl_n_starts_what_the_page_is_for(isolated, display):
    win = _window()
    try:
        win.set_mode('sermons')
        win._new_from_keys()
        assert win._current_entry['kind'] == 'sermon'
        win.set_mode('marks')
        win._new_from_keys()
        assert win._current_entry['kind'] == 'entry'
    finally:
        win.destroy()


# ── Found in the bug check ───────────────────────────────────────────────────

def test_in_writing_mode_esc_closes_the_find_bar_first(isolated, display):
    """The find bar stays open in writing mode. Its own Esc used to run first;
    the capture handler must leave it that, or Esc threw the writer out of
    the mode with the bar still open."""
    journal.save('e1', title='Kept', body='words and words')
    win = _window()
    try:
        win.set_mode('journal')
        win.select_entry('e1')
        win._set_writing_mode(True)
        win._entry_editor.find.open()
        assert not any(_press(c, Gdk.KEY_Escape) for c in _capture_keys(win))
        assert win._writing_mode
    finally:
        win.destroy()


def test_in_writing_mode_esc_closes_the_reference_card_first(isolated,
                                                              display):
    journal.save('e1', title='Kept', body='See John 3:16 today.')
    win = _window()
    try:
        win.set_mode('journal')
        win.select_entry('e1')
        win._set_writing_mode(True)
        ed = win._entry_editor
        ed._offer_ref([r for r in ed.refs if r[2] == 'John'][0])
        assert not any(_press(c, Gdk.KEY_Escape) for c in _capture_keys(win))
        assert win._writing_mode
    finally:
        win.destroy()


def _group_titles(win):
    out = []
    row = win._list.get_first_child()
    while row is not None:
        if hasattr(row, '_series'):
            labels = []
            c = row.get_child()
            stack = [c]
            while stack:
                w = stack.pop()
                if isinstance(w, Gtk.Label):
                    labels.append(w.get_text())
                k = w.get_first_child()
                while k is not None:
                    stack.append(k)
                    k = k.get_next_sibling()
            out.append(' '.join(labels))
        row = row.get_next_sibling()
    return out


def test_dropping_the_only_verse_less_page_drops_its_heading(isolated,
                                                              display):
    journal.save('kept', title='Kept', body='words',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': [16]}])
    win = _window()
    try:
        win.set_mode('journal')
        win.start_entry()
        assert any('No passage' in t for t in _group_titles(win))
        win.select_entry('kept')
        _settle()
        assert not any('No passage' in t for t in _group_titles(win))
    finally:
        win.destroy()


def test_dropping_the_only_unseriesed_sermon_drops_its_heading(isolated,
                                                                display):
    sermons.save('kept', title='Kept', body='words',
                 series={'name': 'Parables', 'part': 1})
    win = _window()
    try:
        win.set_mode('sermons')
        win.start_sermon()
        assert any('No series' in t for t in _group_titles(win))
        win.select_sermon('kept')
        _settle()
        titles = _group_titles(win)
        assert not any('No series' in t for t in titles)
        assert any('Parables' in t for t in titles)
    finally:
        win.destroy()


def test_a_heading_stays_when_show_more_follows(isolated, display,
                                                 monkeypatch):
    """At the render cap the row above "Show more" is not the end of its
    group; the rest of the group is past the button."""
    monkeypatch.setattr(annotations_window, '_RENDER_CAP', 2)
    journal.save('kept', title='Kept', body='words',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': [16]}])
    journal.save('later', title='Later', body='words', date='2020-01-01')
    win = _window()
    try:
        win.set_mode('journal')
        fresh = win.start_entry()
        # Kept, then No passage over the fresh page, then Show more.
        assert win._more_row is not None
        win.select_entry('kept')
        _settle()
        assert fresh['id'] not in _row_ids(win)
        assert any('No passage' in t for t in _group_titles(win))
    finally:
        win.destroy()


def test_escape_closes_the_tag_manager(isolated, display):
    """Every other window of the app closes on Esc; the tag manager did not."""
    win = annotations_window.TagManagerWindow()
    closed = []
    win.close = lambda: closed.append(True)   # a window never shown ignores close()
    keys = [c for c in win.observe_controllers()
            if isinstance(c, Gtk.EventControllerKey)]
    assert any(_press(c, Gdk.KEY_Escape) for c in keys)
    assert closed


def test_a_gesture_with_a_key_shows_the_key():
    """A 'literal' row draws "No Shortcut" beside its text, so Ctrl + click
    read as if it had no shortcut at all. A gesture made with a key held
    is a 'gesture' row, and the key draws as a keycap."""
    for _section, rows in window.BibleWindow._SHORTCUT_SECTIONS:
        for desc, kind, value in rows:
            if kind == 'literal':
                assert 'Ctrl' not in value, desc
            if kind == 'gesture':
                ok, _key, mods = Gtk.accelerator_parse(value[0])
                assert ok and mods, desc
