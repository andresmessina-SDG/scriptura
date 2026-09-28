"""The journal editor's formatting row.

Every button writes the same notation the reader could have typed, so the
tests are about the text in the buffer, not about the styling — that is
test_journal_markup's job. What matters here is that a press is reversible,
that it works on a selection and on a bare cursor, and that nothing it writes
is notation journal_markup cannot read back.
"""
import pytest

import annotation_editors
import writing_page
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
    """The body as written — folded markers included, as the app reads it."""
    buf = editor.body.get_buffer()
    return buf.get_text(*buf.get_bounds(), True)


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
        # The formatting tools, the style and font menus, and Find.
        assert buttons == len(annotation_editors._TOOLS) + 3
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


# ── A reference answers a click ──────────────────────────────────────────────

class _Gesture:
    def __init__(self, state=0):
        self._state = state

    def get_current_event_state(self):
        return self._state


def test_a_click_on_a_reference_offers_it(isolated, display):
    """The caret lands, and a card says where the reference goes — the
    way a link in Pages answers a click. A plain tooltip used to fire
    wherever the pointer rested, over the words being written."""
    win = _open()
    try:
        ed = _editor(win)
        assert not ed.body.get_has_tooltip()
        _set(ed, 'see John 3:16')
        offered = []
        ed._ref_at = lambda x, y: (4, 13, 'John', 3, 16)
        ed._offer_ref = offered.append
        ed.refs = [(4, 13, 'John', 3, 16)]
        ed._on_body_click(_Gesture(), 1, 0, 0)
        assert offered == [(4, 13, 'John', 3, 16)]
    finally:
        win.destroy()


def test_ctrl_click_goes_straight_there(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'see John 3:16')
        went = []
        ed._on_navigate = lambda *a: went.append(a)
        ed._ref_at = lambda x, y: (4, 13, 'John', 3, 16)
        ed.refs = [(4, 13, 'John', 3, 16)]
        from gi.repository import Gdk
        ed._on_body_click(_Gesture(Gdk.ModifierType.CONTROL_MASK), 1, 0, 0)
        assert went == [('John', 3, 16)]
    finally:
        win.destroy()


def test_the_card_names_the_passage_and_never_takes_the_keyboard(
        isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'see John 3:16')
        ed._offer_ref((4, 13, 'John', 3, 16))
        assert '3:16' in ed._ref_go.get_label()
        assert not ed._ref_card.get_can_focus()
        went = []
        ed._on_navigate = lambda *a: went.append(a)
        ed._ref_go.emit('clicked')
        assert went == [('John', 3, 16)]
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
        ed._restyle.flush()      # the count rides the reference debounce
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
        ed._restyle.flush()
        assert not ed._words.get_visible()
    finally:
        win.destroy()


# ── Enter, inside a list ─────────────────────────────────────────────────────
#
# Pressed for real: the newline goes into the buffer the way the key puts it
# there, so these test the path the reader uses and not a handler called by
# name.

def _enter(editor, at=None):
    """Press Enter — at `at`, or at the end of the body."""
    buf = editor.body.get_buffer()
    buf.place_cursor(buf.get_end_iter() if at is None
                     else buf.get_iter_at_offset(at))
    buf.insert_at_cursor('\n')


def test_enter_continues_a_bullet_list(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '- one')
        _enter(ed)
        assert _text(ed) == '- one\n- '
    finally:
        win.destroy()


def test_enter_numbers_the_next_item(isolated, display):
    """The reported defect: the numbered-list button, an item, Enter — and
    the list stopped."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '1. one')
        _enter(ed)
        assert _text(ed) == '1. one\n2. '
        ed.body.get_buffer().insert_at_cursor('two')
        _enter(ed)
        assert _text(ed) == '1. one\n2. two\n3. '
    finally:
        win.destroy()


def test_enter_continues_a_quote(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '> quoted')
        _enter(ed)
        assert _text(ed) == '> quoted\n> '
    finally:
        win.destroy()


def test_a_heading_is_one_line(isolated, display):
    """A second heading conjured under the first is never what Enter meant."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '# Sermon')
        _enter(ed)
        assert _text(ed) == '# Sermon\n'
    finally:
        win.destroy()


def test_enter_in_prose_is_still_a_plain_newline(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'a paragraph')
        _enter(ed)
        assert _text(ed) == 'a paragraph\n'
    finally:
        win.destroy()


def test_an_empty_item_ends_the_list(isolated, display):
    """Enter twice is how every editor says done."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '- one')
        _enter(ed)
        _enter(ed)
        assert _text(ed) == '- one\n'
    finally:
        win.destroy()


def test_an_empty_numbered_item_ends_the_list(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '1. one\n2. ')
        _enter(ed)
        assert _text(ed) == '1. one\n'
    finally:
        win.destroy()


def test_the_caret_lands_after_the_new_marker(isolated, display):
    """A marker the reader has to walk past by hand is worse than none."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '- one')
        _enter(ed)
        buf = ed.body.get_buffer()
        at = buf.get_iter_at_mark(buf.get_insert())
        assert at.get_offset() == len('- one\n- ')
    finally:
        win.destroy()


def test_splitting_an_item_renumbers_the_rest(isolated, display):
    """1. 2. 2. 3. is a list that has to be retyped by hand."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '1. one\n2. two\n3. three')
        _enter(ed, len('1. one'))
        assert _text(ed) == '1. one\n2. \n3. two\n4. three'
    finally:
        win.destroy()


def test_a_run_that_starts_high_keeps_its_own_first_number(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '3. three\n4. four')
        _enter(ed, len('3. three'))
        assert _text(ed) == '3. three\n4. \n5. four'
    finally:
        win.destroy()


def test_a_caret_inside_the_marker_gets_a_plain_newline(isolated, display):
    """Splitting the marker itself is not making an item."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '- one')
        _enter(ed, 1)
        assert _text(ed) == '-\n one'
    finally:
        win.destroy()


def test_continuing_a_list_is_one_undo(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        buf = ed.body.get_buffer()
        _set(ed, '1. one\n2. two')
        _enter(ed, len('1. one'))
        buf.undo()
        assert _text(ed) == '1. one\n2. two'
    finally:
        win.destroy()


def test_opening_an_entry_does_not_continue_anything(isolated, display):
    """`populate` sets a body full of newlines; none of them is a keystroke."""
    win = _open()
    try:
        ed = _editor(win)
        ed.populate({'kind': 'entry', 'id': 'x', 'title': 't',
                     'body': '- one\n- two\n', 'date': '2026-09-12',
                     'anchors': [], 'tags': []})
        assert _text(ed) == '- one\n- two\n'
    finally:
        win.destroy()


# ── One line, one marker ─────────────────────────────────────────────────────

def test_a_bullet_replaces_a_number(isolated, display):
    """'- 1. one' is a bullet whose text reads '1. one'."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '1. one')
        ed._prefix('- ')
        assert _text(ed) == '- one'
    finally:
        win.destroy()


def test_numbering_replaces_a_bullet(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '- one\n- two', 0, 11)
        ed._number()
        assert _text(ed) == '1. one\n2. two'
    finally:
        win.destroy()


def test_a_heading_replaces_a_quote(isolated, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '> one')
        ed._prefix('# ')
        assert _text(ed) == '# one'
    finally:
        win.destroy()


def test_a_selection_ending_at_a_line_start_leaves_that_line_alone(
        isolated, display):
    """A drag that stops at the head of a line has not reached into it."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'one\ntwo', 0, 4)
        ed._prefix('- ')
        assert _text(ed) == '- one\ntwo'
    finally:
        win.destroy()


# ── A pair has to close against a word ───────────────────────────────────────

def test_bold_ignores_the_space_a_drag_took_with_it(isolated, display):
    """'**word **' is notation the renderer does not read back, so the press
    would have done nothing the reader could see."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'the word here', 4, 9)
        ed._wrap('**')
        assert _text(ed) == 'the **word** here'
        assert 'md-strong' in {t for _a, _b, t
                               in journal_markup.spans(_text(ed))}
    finally:
        win.destroy()


# ── The restyle is local, and must still be exact ────────────────────────────
#
# Every span the subset knows is decided inside one line, so an edit can only
# change the styling of the lines it touched and `_restyle_body` re-reads only
# those. That is worth a great deal on a sermon manuscript — the whole-body
# pass cost 9.3ms of every keystroke at 8,000 words — but it is only safe
# while it tags *identically* to reading the whole body.

_TAGS = ('md-strong', 'md-emphasis', 'md-heading', 'md-subheading',
         'md-rule', 'md-quote', 'md-bullet', 'md-marker')


def _merge(spans):
    """Adjacent ranges of one tag are a single run once applied to a buffer.

    `**` yields two abutting `md-marker` spans; GTK stores them as one. Both
    sides of the comparison have to say so or they never agree.
    """
    out = []
    for a, b, name in sorted(spans, key=lambda t: (t[2], t[0], t[1])):
        if out and out[-1][2] == name and out[-1][1] == a:
            out[-1] = (out[-1][0], b, name)
        else:
            out.append((a, b, name))
    return sorted(out)


def _tags_on(buf):
    """The spans actually carried by the buffer, read back off the tags."""
    out, table = [], buf.get_tag_table()
    for name in _TAGS:
        tag = table.lookup(name)
        it = buf.get_start_iter()
        open_at = [0] if it.starts_tag(tag) else []
        while it.forward_to_tag_toggle(tag):
            if it.starts_tag(tag):
                open_at.append(it.get_offset())
            else:
                out.append((open_at.pop(), it.get_offset(), name))
    return _merge(out)


def test_editing_tags_exactly_as_a_whole_body_pass_would(isolated, display):
    """Edit all over a body and the tags must match a full re-read every time.

    Insertions, deletions that swallow a line break, and an edit far from the
    caret's last position — the three ways a local pass could leave a stale
    tag behind.
    """
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '# Title\n\nSome **bold** and *italic*.\n> quoted\n- one\n---\n'
                 '#### Arrival\n')
        buf = ed.body.get_buffer()
        edits = [
            (0, '*'), (3, '**x** '), (30, '\n> new quote\n'),
            (1, ''), (12, '1. numbered\n'), (5, '\n\n'),
        ]
        for offset, text in edits:
            at = min(offset, buf.get_char_count())
            buf.insert(buf.get_iter_at_offset(at), text)
            assert _tags_on(buf) == _merge(journal_markup.spans(_text(ed))), (
                f'stale tags after inserting {text!r} at {at}')
        for a, b in ((4, 18), (0, 3), (9, 25)):
            a = min(a, buf.get_char_count())
            b = min(b, buf.get_char_count())
            buf.delete(buf.get_iter_at_offset(a), buf.get_iter_at_offset(b))
            assert _tags_on(buf) == _merge(journal_markup.spans(_text(ed))), (
                f'stale tags after deleting {a}..{b}')
    finally:
        win.destroy()


# ── The page: face, measure, hanging markers ─────────────────────────────────

@pytest.fixture
def own_settings(tmp_path, monkeypatch):
    import settings
    monkeypatch.setattr(settings, '_FILE', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(settings, '_cache', None)
    return settings


def test_the_font_menu_offers_every_writing_face(isolated, own_settings,
                                                 display):
    win = _open()
    try:
        ed = _editor(win)
        assert tuple(ed._font_choices) == writing_page.WRITING_FONTS
        # A glyph and an arrow, so it reads as a menu and not as a label.
        assert ed._font_button.get_always_show_arrow()
        assert ed._font_label.get_label() == 'Newsreader'
        assert ed._font_choices['Newsreader'].get_active()
    finally:
        win.destroy()


def test_choosing_a_face_sets_every_sheet(isolated, own_settings, display):
    """One face for the writing, whichever page it was chosen on."""
    win = _open()
    try:
        entry = _editor(win)
        sermon = win._sermon_editor
        entry._font_choices['EB Garamond'].set_active(True)
        assert own_settings.get('writing_font') == 'EB Garamond'
        assert sermon._font_label.get_label() == 'EB Garamond'
        css = writing_page._WRITING_CSS.to_string()
        assert '"EB Garamond"' in css
        # the reading page's leading, not the face's own
        assert 'line-height: 1.5' in css
    finally:
        win.destroy()


def test_an_unknown_face_falls_back_to_the_default(isolated, own_settings,
                                                   display):
    own_settings.put('writing_font', 'Comic Sans MS')
    writing_page.refresh_writing_style()
    assert '"Newsreader"' in writing_page._WRITING_CSS.to_string()


def test_the_column_takes_the_reading_measure(isolated, own_settings, display):
    """125 characters a line with the list hidden, 139 in writing mode —
    the view meant to be best read worst. Centred at the reading width."""
    win = _open()
    try:
        ed = _editor(win)
        table = ed.body.get_buffer().get_tag_table()
        ed._fit_page(1000)
        side = (1000 - 540) // 2
        assert ed.body.get_left_margin() == side
        assert ed.body.get_right_margin() == side
        assert table.lookup('md-quote').get_property('left-margin') == side + 20
        assert table.lookup('md-bullet').get_property('left-margin') == side + 22
        # a sheet narrower than the measure keeps the old margin
        ed._fit_page(400)
        assert ed.body.get_left_margin() == writing_page._BODY_MARGIN
    finally:
        win.destroy()


def _hang_for(ed, marker):
    buf = ed.body.get_buffer()
    it = buf.get_iter_at_offset(_text(ed).index(marker))
    tags = [t for t in it.get_tags() if t in ed._hangs.values()]
    return tags[0] if tags else None


def _write_on(ed, needle):
    """Put the caret on the line holding `needle`, as a writer would."""
    buf = ed.body.get_buffer()
    ed._set_writing(True)
    buf.place_cursor(buf.get_iter_at_offset(_text(ed).index(needle)))


def _hidden(ed, needle):
    buf = ed.body.get_buffer()
    it = buf.get_iter_at_offset(_text(ed).index(needle))
    return it.has_tag(buf.get_tag_table().lookup('md-hidden'))


def test_markers_hang_in_the_margin_on_the_line_being_written(
        isolated, own_settings, display):
    """The words start on the column's edge; the marker sits left of it. A
    negative indent alone pulls the WRAPPED lines in, so the paragraph has
    to start out in the margin by the marker's width as well."""
    win = _open()
    try:
        ed = _editor(win)
        ed._fit_page(1000)
        side = ed.body.get_left_margin()
        _set(ed, '## Arrival\n\n> In peace\n\n#### Debrief\n\n- a list')
        for marker, edge in (('## ', side), ('> ', side + 20),
                             ('#### ', side), ('- ', side + 22)):
            _write_on(ed, marker)
            tag = _hang_for(ed, marker)
            assert tag is not None, marker
            width = -tag.get_property('indent')
            assert width > 0, marker
            assert tag.get_property('left-margin') == edge - width, marker
    finally:
        win.destroy()


def test_markers_fold_off_the_line_being_written(isolated, own_settings,
                                                 display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '## Arrival\n\nSome **bold** words\n\n- item\n2. two')
        # A page opened, not yet written in, reads clean.
        assert _hidden(ed, '## ') and _hidden(ed, '**') and _hidden(ed, '- ')
        _write_on(ed, 'Some')
        assert not _hidden(ed, '**')
        assert _hidden(ed, '## ') and _hidden(ed, '- ')
        # Nothing hangs where the marker is folded away.
        assert _hang_for(ed, '## ') is None
        # A list's number is never folded: it is the item's number.
        assert not _hidden(ed, '2. ')
        _write_on(ed, 'Arrival')
        assert not _hidden(ed, '## ') and _hidden(ed, '**')
    finally:
        win.destroy()


def test_folded_markers_are_still_saved(isolated, own_settings, display):
    """The data rule: a marker out of sight is still the entry. Read with
    hidden text left out, the body would have been saved without them."""
    win = _open()
    try:
        ed = _editor(win)
        body = '## Arrival\n\nSome **bold** words\n\n> quoted\n\n- item\n\n---'
        _set(ed, body)
        assert _hidden(ed, '**')
        entry = {'id': journal.new_id(), 'anchors': []}
        ed.write(entry)
        assert entry['body'] == body
        assert journal.get(entry['id'])['body'] == body
    finally:
        win.destroy()


def test_a_selection_shows_every_line_it_touches(isolated, own_settings,
                                                 display):
    """So what is copied is the entry as written, markers and all."""
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '## One\n\nSome **bold**\n\n- item\n\nafter')
        ed._set_writing(True)
        buf = ed.body.get_buffer()
        buf.select_range(buf.get_start_iter(),
                         buf.get_iter_at_offset(_text(ed).index('item') + 2))
        assert not any(_hidden(ed, m) for m in ('## ', '**', '- '))
    finally:
        win.destroy()


def test_leaving_for_the_title_folds_the_page(isolated, own_settings,
                                              display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'Some **bold** words')
        _write_on(ed, 'Some')
        assert not _hidden(ed, '**')
        ed._set_writing(False)
        assert _hidden(ed, '**')
    finally:
        win.destroy()


def test_a_marker_never_hangs_past_the_sheet(isolated, own_settings, display):
    """At a narrow window the margin is 12px; a marker wider than that
    hangs only as far as the margin goes."""
    win = _open()
    try:
        ed = _editor(win)
        ed._fit_page(300)
        _set(ed, '#### Debrief')
        _write_on(ed, 'Debrief')
        tag = _hang_for(ed, '#### ')
        assert tag.get_property('left-margin') >= 0
        assert -tag.get_property('indent') <= writing_page._BODY_MARGIN
    finally:
        win.destroy()


def test_heading_levels_are_three_sizes(isolated, own_settings, display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '# One\n## Two\n### Three\n#### Four')
        buf = ed.body.get_buffer()

        def scale(needle):
            it = buf.get_iter_at_offset(_text(ed).index(needle))
            size = 1.0
            for tag in it.get_tags():
                if tag.get_property('scale-set'):
                    size *= tag.get_property('scale')
            return round(size, 2)

        assert scale('One') == 1.25
        assert scale('Two') == 1.12
        assert scale('Three') == scale('Four') == 1.0
    finally:
        win.destroy()


# ── The style menu ───────────────────────────────────────────────────────────

def test_the_style_menu_sets_and_clears_a_heading(isolated, own_settings,
                                                  display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'Arrival\n- item', 0)
        ed._set_style('## ')
        assert _text(ed) == '## Arrival\n- item'
        # Set, not toggled: the same choice again leaves it a subheading.
        ed._set_style('## ')
        assert _text(ed) == '## Arrival\n- item'
        ed._set_style('# ')
        assert _text(ed) == '# Arrival\n- item'
        ed._set_style('')
        assert _text(ed) == 'Arrival\n- item'
        # Body takes a list off too, as it does in Pages.
        buf = ed.body.get_buffer()
        buf.place_cursor(buf.get_iter_at_offset(_text(ed).index('item')))
        ed._set_style('')
        assert _text(ed) == 'Arrival\nitem'
    finally:
        win.destroy()


def test_the_style_menu_shows_its_keys(isolated, own_settings, display):
    win = _open()
    try:
        ed = _editor(win)
        assert set(ed._style_choices) == {'', '# ', '## ', '### '}
    finally:
        win.destroy()


# ── The buttons show what the caret is in ────────────────────────────────────

def test_the_buttons_press_for_what_the_caret_is_in(isolated, own_settings,
                                                    display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, 'Some **bold** words\n> quoted\n- item\n1. first')
        buttons = ed._tool_buttons
        buf = ed.body.get_buffer()

        def at(needle):
            buf.place_cursor(buf.get_iter_at_offset(_text(ed).index(needle)))

        at('bold')
        buf.place_cursor(buf.get_iter_at_offset(_text(ed).index('bold') + 2))
        assert buttons['**'].get_active() and not buttons['*'].get_active()
        at('words')
        assert not buttons['**'].get_active()
        at('quoted')
        assert buttons['> '].get_active()
        at('item')
        assert buttons['- '].get_active() and not buttons['> '].get_active()
        at('first')
        assert buttons['number'].get_active()
    finally:
        win.destroy()


def test_a_press_never_takes_the_caret_from_the_body(isolated, own_settings,
                                                     display):
    win = _open()
    try:
        ed = _editor(win)
        for btn in ed._tool_buttons.values():
            assert not btn.get_focus_on_click()
        assert not ed._style_button.get_focus_on_click()
        assert not ed._font_button.get_focus_on_click()
    finally:
        win.destroy()


# ── Saved ────────────────────────────────────────────────────────────────────

def test_saved_shows_after_a_write_and_only_then(isolated, own_settings,
                                                 display):
    win = _open()
    try:
        ed = _editor(win)
        fade = ed._saved_fade
        assert ed._saved.get_opacity() == 0
        _set(ed, 'words')
        entry = {'id': journal.new_id(), 'anchors': []}
        ed.write(entry)
        assert fade.get_value_to() == 1 and ed._saved_source
        ed._unflash_saved()
        assert fade.get_value_to() == 0 and not ed._saved_source
        # An empty entry is never written, so nothing is said to be saved.
        fade.skip()
        _set(ed, '')
        ed.title.set_text('')
        ed.write({'id': journal.new_id(), 'anchors': []})
        assert fade.get_value_to() == 0 and not ed._saved_source
    finally:
        win.destroy()


def test_a_heading_turned_to_prose_stops_hanging(isolated, own_settings,
                                                 display):
    win = _open()
    try:
        ed = _editor(win)
        _set(ed, '## Arrival')
        buf = ed.body.get_buffer()
        buf.delete(buf.get_start_iter(), buf.get_iter_at_offset(3))
        assert not set(buf.get_start_iter().get_tags()) & set(ed._hangs.values())
    finally:
        win.destroy()
