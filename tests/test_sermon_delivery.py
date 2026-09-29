"""The sermon delivery view: the manuscript full-screen, to preach from.

What the view shows is `journal_markup.for_delivery`'s text, so most of the
view is tested there, with no display: the notation goes, what it marked
stays as spans, and a bracketed cue is set apart from what is said. The
window tests stub `present` and `fullscreen` — a full-screen window thrown
onto the tester's desktop by the suite is the worst of the file-chooser
failure conftest guards against.
"""
import pytest

import journal_markup
import sermon_delivery

_SERMON = ('# The Sower\n'
           'A sower went out **to sow**. [pause]\n'
           '\n'
           '## The path\n'
           '- hard ground\n'
           '\n'
           '| Soil | Fruit |\n'
           '|---|---|\n'
           '| path | none |\n'
           '\n'
           '---\n'
           '> He that hath ears to hear, let him hear.')


def _tagged(text, spans, tag):
    return [text[a:b] for a, b, t in spans if t == tag]


# ── The text ────────────────────────────────────────────────────────────────

def test_the_notation_goes_and_what_it_marked_stays():
    text, spans = journal_markup.for_delivery(_SERMON)
    assert '#' not in text and '**' not in text and '>' not in text
    assert _tagged(text, spans, 'md-heading') == ['The Sower', 'The path']
    assert _tagged(text, spans, 'md-strong')[0] == 'to sow'
    assert _tagged(text, spans, 'md-quote') == [
        'He that hath ears to hear, let him hear.']
    assert '• hard ground' in text.split('\n')


def test_a_cue_is_set_apart_from_what_is_said():
    text, spans = journal_markup.for_delivery(_SERMON)
    assert _tagged(text, spans, 'md-cue') == ['[pause]']


def test_a_table_shows_its_cells_and_drops_its_delimiter_row():
    """Cells split by tabs, for the view to set on columns: spaces in a
    proportional face left the second column wandering row to row."""
    text, spans = journal_markup.for_delivery(_SERMON)
    lines = text.split('\n')
    assert 'Soil\tFruit' in lines and 'path\tnone' in lines
    assert not any('|' in line or '---' in line for line in lines)
    assert 'Soil\tFruit' in _tagged(text, spans, 'md-strong')
    assert _tagged(text, spans, 'md-table') == ['Soil\tFruit\npath\tnone']


def test_markup_inside_a_table_cell_is_styled_not_shown():
    """The editor styles bold and italic in a cell; the view showed the
    asterisks."""
    text, spans = journal_markup.for_delivery(
        '| Soil | Fruit |\n|---|---|\n| **path** | *none* [pause] |')
    assert text.split('\n')[1] == 'path\tnone [pause]'
    assert 'path' in _tagged(text, spans, 'md-strong')
    assert _tagged(text, spans, 'md-emphasis') == ['none']
    assert _tagged(text, spans, 'md-cue') == ['[pause]']


def test_a_rule_is_a_row_of_dots():
    text, spans = journal_markup.for_delivery(_SERMON)
    assert _tagged(text, spans, 'md-rule') == ['·   ·   ·']


@pytest.mark.parametrize('seconds, shown', [
    (0, '0:00'), (247, '4:07'), (3847, '1:04:07')])
def test_the_clock_reads_minutes_and_seconds_then_hours(seconds, shown):
    assert sermon_delivery._elapsed(seconds) == shown


# ── The window ──────────────────────────────────────────────────────────────

@pytest.fixture
def display(monkeypatch):
    """Skip with no screen (a widget build segfaults there), and keep the
    window off the tester's."""
    from gi.repository import Adw, Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: the delivery view is a real window')
    monkeypatch.setattr(Adw.Window, 'present', lambda self: None)
    monkeypatch.setattr(Adw.Window, 'fullscreen', lambda self: None)


def test_the_view_shows_the_text_with_its_cues_tagged(display):
    win = sermon_delivery.DeliveryWindow('The Sower', _SERMON)
    try:
        buf = win._view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        assert text == journal_markup.for_delivery(_SERMON)[0]
        at = buf.get_iter_at_offset(text.index('[pause]') + 1)
        assert 'md-cue' in [t.get_property('name') for t in at.get_tags()]
        assert not win._view.get_editable()
        assert [name for _m, name in win._headings] == ['The Sower',
                                                        'The path']
        assert win._place.get_label().startswith('The Sower')
    finally:
        win.destroy()


def test_esc_leaves_and_stops_the_clock(display):
    from gi.repository import Gdk
    win = sermon_delivery.DeliveryWindow('The Sower', _SERMON)
    # close() does nothing to a window never shown, which this one is not.
    closed = []
    win.close = lambda: closed.append(True)
    try:
        assert win._on_key(None, Gdk.KEY_Escape, 0, 0)
        assert closed
        win.emit('close-request')
        assert win._tick == 0
    finally:
        win.destroy()


def test_a_line_down_is_one_line_at_the_readers_spacing(display, monkeypatch):
    """↓ moved 1.5 × the type size whatever the spacing: at 2.0× that is
    three quarters of a line, and the text shifts under the eye by a
    different amount each press."""
    import settings
    from gi.repository import Gdk, Gtk
    monkeypatch.setattr(settings, 'get', lambda key, *a: 2.0
                        if key == 'line_spacing' else None)
    win = sermon_delivery.DeliveryWindow('The Sower', _SERMON)
    try:
        win._size = 30
        # The view's own is reset by a text view that was never laid out.
        adj = Gtk.Adjustment(lower=0, upper=10000, page_size=100)
        win._scroll.get_vadjustment = lambda: adj
        win._on_key(None, Gdk.KEY_Down, 0, 0)
        assert adj.get_value() == 60
    finally:
        win.destroy()


def test_an_untitled_sermon_is_named_sermon(display):
    win = sermon_delivery.DeliveryWindow('', 'Words.')
    try:
        assert win.get_title() == 'Sermon'
    finally:
        win.destroy()


# ── The door, in the sermon editor ──────────────────────────────────────────

def test_the_sermon_editor_opens_the_view_on_its_own_manuscript(
        display, monkeypatch, tmp_path):
    import annotations_window
    import sermons
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 's.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    win.set_mode('sermons')
    try:
        win.start_sermon()
        editor = win._sermon_editor
        tips = [b.get_tooltip_text() for b in _children(editor._tools)]
        assert 'Preach from this (F5)' in tips
        editor.title.set_text('The Sower')
        editor.body.get_buffer().set_text(_SERMON)
        view = editor._deliver()
        try:
            assert view.get_title() == 'The Sower'
            assert view.get_transient_for() is win
            buf = view._view.get_buffer()
            assert buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                                True).startswith('The Sower\nA sower')
        finally:
            view.destroy()
    finally:
        win.destroy()


def test_a_second_press_brings_back_the_open_view_not_another(
        display, monkeypatch, tmp_path):
    """With a projector beside the laptop the Annotations window stays in
    reach while the view is up, and a second F5 or a double-click stacked
    a second full-screen view that Esc then only half dismissed."""
    import annotations_window
    import sermons
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 's.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    win.set_mode('sermons')
    try:
        win.start_sermon()
        editor = win._sermon_editor
        editor.body.get_buffer().set_text('Words.')
        first = editor._deliver()
        try:
            assert editor._deliver() is first
            # Edited since: the view must show what is written now.
            editor.body.get_buffer().set_text('Other words.')
            fresh = editor._deliver()
            assert fresh is not first
            buf = fresh._view.get_buffer()
            assert buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                                True) == 'Other words.'
            fresh.destroy()
        finally:
            first.destroy()
        second = editor._deliver()
        try:
            assert second is not first
        finally:
            second.destroy()
    finally:
        win.destroy()


def test_f5_is_the_windows_and_only_for_an_open_sermon(
        display, monkeypatch, tmp_path):
    """F5 from the list as well as the manuscript: a local key on the
    editor did nothing with the sermon picked in the list, where the
    keyboard stays after a click on its row."""
    import annotation_editors
    import annotations_window
    import sermons
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 's.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    opened = []
    monkeypatch.setattr(annotation_editors.SermonEditor, '_deliver',
                        lambda self: opened.append(self))
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        win.set_mode('journal')
        win.start_entry()
        win._deliver_sermon()
        assert opened == []
        win.set_mode('sermons')
        win.start_sermon()
        win._deliver_sermon()
        assert opened == [win._sermon_editor]
    finally:
        win.destroy()


def test_the_journal_editor_has_no_such_door(display):
    import annotations_window
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        tips = [b.get_tooltip_text()
                for b in _children(win._entry_editor._tools)]
        assert 'Preach from this (F5)' not in tips
    finally:
        win.destroy()


def _children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()
