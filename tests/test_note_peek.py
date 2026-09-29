"""A verse's note, read where it is.

On the page a note was only a bold blue verse number; reading it took a
right-click, Edit Note & Tags and a dialog — the door for writing it. A click
on the marked number now opens the peek the footnotes use, with the note,
its tags and a way into the editor.
"""
import types

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gtk  # noqa: E402
import pytest  # noqa: E402

from pane import BiblePane  # noqa: E402
import pane_peek  # noqa: E402


class Targets:
    _targets_at_iter = BiblePane._targets_at_iter

    def __init__(self):
        self._show_footnotes = True


def _verse_buffer(with_note):
    buf = Gtk.TextBuffer()
    buf.insert(buf.get_end_iter(), '16 For God so loved')
    buf.apply_tag(buf.create_tag('vnum_16'), buf.get_start_iter(),
                  buf.get_end_iter())
    if with_note:
        buf.apply_tag(buf.create_tag('_note_marker'), buf.get_start_iter(),
                      buf.get_iter_at_offset(3))
    return buf


def test_the_marked_number_is_a_note_target():
    buf = _verse_buffer(with_note=True)
    targets, _it = Targets()._targets_at_iter(buf.get_iter_at_offset(1))
    assert targets['verse'] == 16 and targets['note']


def test_the_words_of_the_verse_are_not():
    buf = _verse_buffer(with_note=True)
    targets, _it = Targets()._targets_at_iter(buf.get_iter_at_offset(8))
    assert not targets['note']


def test_an_unmarked_number_is_not():
    buf = _verse_buffer(with_note=False)
    targets, _it = Targets()._targets_at_iter(buf.get_iter_at_offset(1))
    assert not targets['note']


@pytest.fixture
def display():
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display')


def _texts(w):
    out = []
    if isinstance(w, Gtk.Label):
        out.append(w.get_text())
    if isinstance(w, Gtk.Button) and w.get_label():
        out.append(w.get_label())
    c = w.get_first_child()
    while c is not None:
        out += _texts(c)
        c = c.get_next_sibling()
    return out


def _buttons(w):
    out = [w] if isinstance(w, Gtk.Button) else []
    c = w.get_first_child()
    while c is not None:
        out += _buttons(c)
        c = c.get_next_sibling()
    return out


def test_the_peek_holds_the_note_its_tags_and_the_way_in(display):
    edited = []
    box = pane_peek.note_peek_content(
        16, 'Given, not lent.', ['gospel', 'love'],
        on_edit=lambda: edited.append(True))
    texts = _texts(box)
    assert 'Given, not lent.' in texts
    assert '#gospel  #love' in texts
    edit = [b for b in _buttons(box) if b.get_label() == 'Edit note']
    assert edit
    edit[0].emit('clicked')
    assert edited


def test_a_click_on_the_marked_number_opens_it():
    buf = _verse_buffer(with_note=True)
    opened = []
    fake = types.SimpleNamespace(
        _view=types.SimpleNamespace(
            window_to_buffer_coords=lambda _w, x, y: (x, y),
            get_iter_at_location=lambda x, y: (True, buf.get_iter_at_offset(1))),
        _targets_at_iter=Targets()._targets_at_iter,
        _peek=types.SimpleNamespace(
            show_note_peek=lambda verse, it: opened.append(verse),
            show_footnote_peek=lambda *a: None),
        _set_current_verse_indicator=lambda v: None,
        _announce_verse_state=lambda v: None,
        _cursor=types.SimpleNamespace(sync_to=lambda v: None),
        _on_word_click=None, _on_verse_select=None, _on_word_study_navigate=None)
    BiblePane._on_left_click(fake, None, 1, 5, 5)
    assert opened == [16]


def test_a_long_note_leaves_room_for_its_tags_and_edit(display):
    """The footnote peek budgets 86px round its body; this one also carries
    a tags line and a button. Budgeted the same, a long note asked for more
    height than the space it was given, and a peek too tall to place is not
    shown at all."""
    avail = 320
    box = pane_peek.note_peek_content(
        16, 'word ' * 600, ['gospel', 'love'], on_edit=lambda: None,
        scroll=lambda w: pane_peek.PeekController._peek_scroller(
            w, avail, chrome=pane_peek.NOTE_PEEK_CHROME))
    # 280 of content plus its 14px margins.
    _min, natural, _b, _b2 = box.measure(Gtk.Orientation.VERTICAL, 308)
    # The popover adds its arrow and border outside the content.
    assert natural <= avail - 20
