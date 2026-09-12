"""The journal editor's formatting row.

Every button writes the same notation the reader could have typed, so the
tests are about the text in the buffer, not about the styling — that is
test_journal_markup's job. What matters here is that a press is reversible,
that it works on a selection and on a bare cursor, and that nothing it writes
is notation journal_markup cannot read back.
"""
import pytest

import annotation_editors
import annotations
import annotations_window
import journal
import journal_markup


@pytest.fixture
def display():
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
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(journal, '_load_failed', False)
    return tmp_path


def _editor(win):
    return win._entry_editor


def _open():
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    win.set_mode('journal')
    return win


def _text(editor):
    buf = editor.body.get_buffer()
    return buf.get_text(*buf.get_bounds(), False)


def _set(editor, text, start=None, end=None):
    buf = editor.body.get_buffer()
    buf.set_text(text)
    if start is not None:
        buf.select_range(buf.get_iter_at_offset(start),
                         buf.get_iter_at_offset(end if end is not None
                                                else start))


# ── Wrapping ─────────────────────────────────────────────────────────────────

def test_bold_wraps_the_selection(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'the word here', 4, 8)
        ed._wrap('**')
        assert _text(ed) == 'the **word** here'
    finally:
        win.destroy()


def test_pressing_bold_again_takes_it_off(isolated, display):
    """The selection after a wrap is the wrapped word, so the second press
    is the same gesture — it must undo rather than double the markers."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'the word here', 4, 8)
        ed._wrap('**')
        ed._wrap('**')
        assert _text(ed) == 'the word here'
    finally:
        win.destroy()


def test_bold_with_no_selection_leaves_the_cursor_between(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'ab', 1)
        ed._wrap('**')
        assert _text(ed) == 'a****b'
        buf = ed.body.get_buffer()
        assert buf.get_iter_at_mark(buf.get_insert()).get_offset() == 3
    finally:
        win.destroy()


def test_bold_comes_off_a_selection_that_includes_the_markers(isolated,
                                                              display):
    """Selecting the whole '**word**' by hand and pressing bold has to take
    the bold off, not wrap it in a second pair."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '**word**', 0, 8)
        ed._wrap('**')
        assert _text(ed) == 'word'
    finally:
        win.destroy()


def test_italic_never_chops_a_bold_pair_in_half(isolated, display):
    """'**word**' starts and ends with '*', so an unguarded unwrap would
    strip one star off each end and leave notation that renders wrong."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '**word**', 0, 8)
        ed._wrap('*')
        assert _text(ed) != '*word*'
        assert 'md-strong' in {t for _a, _b, t
                               in journal_markup.spans(_text(ed))}
    finally:
        win.destroy()


# ── Line markers ─────────────────────────────────────────────────────────────

def test_a_list_marks_every_selected_line(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'one\ntwo\nthree', 0, 13)
        ed._prefix('- ')
        assert _text(ed) == '- one\n- two\n- three'
        ed._prefix('- ')
        assert _text(ed) == 'one\ntwo\nthree'
    finally:
        win.destroy()


def test_a_half_marked_range_is_completed_not_cleared(isolated, display):
    """All or nothing: one press makes the range a list, and only then does
    the next press take it back."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '- one\ntwo', 0, 9)
        ed._prefix('- ')
        assert _text(ed) == '- one\n- two'
    finally:
        win.destroy()


def test_quote_marks_the_line_the_cursor_is_on(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'one\ntwo', 5)
        ed._prefix('> ')
        assert _text(ed) == 'one\n> two'
    finally:
        win.destroy()


# ── What the buttons write is what the renderer reads ────────────────────────

def test_every_tool_writes_notation_the_renderer_knows(isolated, display):
    """A button that wrote notation journal_markup does not recognise would
    leave the reader looking at literal asterisks."""
    win = _open()
    try:
        ed = _editor(win)
        for _icon, _label, kind, marker in annotation_editors._TOOLS:
            _set(ed, 'word', 0, 4)
            getattr(ed, '_' + kind)(marker)
            tags = {t for _a, _b, t in journal_markup.spans(_text(ed))}
            assert tags - {'md-marker'}, f'{marker!r} styled nothing'
    finally:
        win.destroy()


def test_the_row_is_built_and_parented(isolated, display):
    """The orphan guard, for the row rather than the editor: a toolbar built
    and never appended answers every other assertion in this file."""
    win = _open()
    try:
        ed = _editor(win)
        found = []

        def walk(w):
            child = w.get_first_child()
            while child is not None:
                if child.get_css_classes() and 'journal-tools' in \
                        child.get_css_classes():
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(ed)
        assert len(found) == 1
        buttons = 0
        child = found[0].get_first_child()
        while child is not None:
            buttons += 1
            child = child.get_next_sibling()
        assert buttons == len(annotation_editors._TOOLS)
    finally:
        win.destroy()


def test_the_placeholder_goes_away_once_there_is_writing(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '')
        assert ed._body_hint.get_visible()
        _set(ed, 'a')
        assert not ed._body_hint.get_visible()
    finally:
        win.destroy()


# ── What a press costs to take back ──────────────────────────────────────────

def test_one_press_is_one_undo(isolated, display):
    """Two inserts ungrouped are two undo steps, and one Ctrl+Z would leave
    half a pair of markers in the text."""
    win = _open()
    try:
        ed = _editor(win)
        buf = ed.body.get_buffer()
        _set(ed, 'the word here', 4, 8)
        ed._wrap('**')
        buf.undo()
        assert _text(ed) == 'the word here'
    finally:
        win.destroy()


def test_one_press_is_one_undo_for_a_list(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        buf = ed.body.get_buffer()
        _set(ed, 'one\ntwo\nthree', 0, 13)
        ed._prefix('- ')
        buf.undo()
        assert _text(ed) == 'one\ntwo\nthree'
    finally:
        win.destroy()


# ── The tip belongs to the links ─────────────────────────────────────────────

def test_the_body_tooltip_only_answers_over_a_reference(isolated, display):
    """As a plain tooltip it fired wherever the pointer rested in the body:
    a box over the words you are writing."""
    win = _open()
    try:
        ed = _editor(win)
        assert ed.body.get_tooltip_text() is None
        _set(ed, 'see John 3:16')
        ed._restyle.cancel()
        ed._restyle_references()
        assert ed.refs, 'the reference was not marked'

        class Tip:
            text = None

            def set_text(self, t):
                self.text = t

        tip = Tip()
        ed.refs = [(4, 13, 'John', 3, 16)]
        # Keyboard mode has no pointer to be over anything.
        assert ed._on_body_tooltip(ed.body, 0, 0, True, tip) is False

        # A probe's view has no allocation, so the real hit test cannot be
        # driven from coordinates. Stand in for it at the one seam that
        # matters: which offset the pointer landed on.
        class FakeIter:
            def __init__(self, offset):
                self._offset = offset

            def get_offset(self):
                return self._offset

        class FakeView:
            def __init__(self, offset):
                self._offset = offset

            def window_to_buffer_coords(self, *_a):
                return (0, 0)

            def get_iter_at_location(self, *_a):
                return (True, FakeIter(self._offset))

        ed.body = FakeView(6)               # inside "John 3:16"
        assert ed._on_body_tooltip(None, 0, 0, False, tip) is True
        assert tip.text

        tip.text = None
        ed.body = FakeView(1)               # on "see"
        assert ed._on_body_tooltip(None, 0, 0, False, tip) is False
        assert tip.text is None
    finally:
        win.destroy()


# ── How the subset is set ────────────────────────────────────────────────────

def test_the_paragraph_tags_indent_past_the_body_margin(isolated, display):
    """A tag's `left-margin` REPLACES the view's instead of adding to it, so
    raising the body's margin silently flattened the quote and the list to
    an indent of 10px and 6px. Whatever the body carries, these must be
    clear of it."""
    win = _open()
    try:
        ed = _editor(win)
        table = ed.body.get_buffer().get_tag_table()
        body = ed.body.get_left_margin()
        for name in ('md-quote', 'md-bullet'):
            tag = table.lookup(name)
            assert tag.get_property('left-margin') >= body + 16, name
    finally:
        win.destroy()


def test_a_marker_is_smaller_than_the_words_it_marks(isolated, display):
    """Dimmed was not enough: at full size a '#' is the largest glyph on its
    own heading line."""
    win = _open()
    try:
        table = _editor(win).body.get_buffer().get_tag_table()
        assert table.lookup('md-marker').get_property('scale') < 1.0
    finally:
        win.destroy()


def test_a_quotation_is_set_apart_from_the_lines_around_it(isolated, display):
    """§6.5 asked for the subset because a quoted passage wants to look
    quoted; italic and a hair of indent was not that."""
    win = _open()
    try:
        quote = _editor(win).body.get_buffer().get_tag_table() \
            .lookup('md-quote')
        assert quote.get_property('pixels-above-lines') > 0
        assert quote.get_property('pixels-below-lines') > 0
    finally:
        win.destroy()


# ── Numbered lists ───────────────────────────────────────────────────────────

def test_a_numbered_list_counts_from_one(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'one\ntwo\nthree', 0, 13)
        ed._number()
        assert _text(ed) == '1. one\n2. two\n3. three'
    finally:
        win.destroy()


def test_pressing_it_again_takes_the_numbers_off(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'one\ntwo', 0, 7)
        ed._number()
        ed._number()
        assert _text(ed) == 'one\ntwo'
    finally:
        win.destroy()


def test_a_badly_numbered_range_is_renumbered_not_doubled(isolated, display):
    """A list that says 1. 1. 1. is not a numbered list, which is why this
    is not a prefix toggle like the others."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '1. one\ntwo\n1. three', 0, 19)
        ed._number()
        assert _text(ed) == '1. one\n2. two\n3. three'
    finally:
        win.destroy()


def test_the_renderer_indents_a_numbered_line(isolated, display):
    """Same tag as a bullet — what the styling does with either is indent
    the line and hang its marker."""
    tags = {t for _a, _b, t in journal_markup.spans('1. one')}
    assert 'md-bullet' in tags


# ── Length, not score ────────────────────────────────────────────────────────

def test_the_word_count_follows_the_writing(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'one two three')
        assert '3' in ed._words.get_text()
        assert ed._words.get_visible()
    finally:
        win.destroy()


def test_an_empty_entry_is_not_told_it_has_no_words(isolated, display):
    """A count is worth having for sermon length and worth nothing as a
    score; '0 words' under an empty page is only the second thing."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '')
        assert not ed._words.get_visible()
    finally:
        win.destroy()
