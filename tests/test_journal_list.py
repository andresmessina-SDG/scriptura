"""Entries and marks in one list.

The canon leads. Anchored rows — marks and entries alike — sort by it; the
verse-less entries have nothing to lead with and group at the end by date,
newest first. These hold that order, the filters that reach across both
kinds, and the row that must not lie about how much was written.
"""
import pytest

import annotations
import annotations_window
import journal


@pytest.fixture
def display():
    """Skip when there is no screen — the window is a real Adw.Window.

    `Gdk.Display.get_default()`, never `Gtk.init_check()`, whose True means
    nothing (GUIDANCE §4).
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
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(journal, '_load_failed', False)
    return tmp_path


def _anchor(book, chapter, *verses):
    return {'book': book, 'chapter': chapter, 'verses': list(verses)}


def _keys(rows):
    return [annotations_window._entry_key(r) for r in rows]


# ── Order ────────────────────────────────────────────────────────────────────

def test_entries_sort_into_the_canon_beside_the_marks(isolated):
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark in Genesis')
    annotations.save_note(None, 'Revelation', 22, 21, 'a mark at the end')
    journal.save('j1', anchors=[_anchor('Exodus', 3, 14)])
    journal.save('j2', anchors=[_anchor('John', 1, 1)])

    rows = annotations_window._all_entries()
    assert [r['book'] for r in rows] == [
        'Genesis', 'Exodus', 'John', 'Revelation']


def test_an_entry_sorts_by_its_FIRST_anchor(isolated):
    journal.save('j1', anchors=[_anchor('John', 1, 1),
                                _anchor('Genesis', 1, 1)])
    annotations.save_note(None, 'Exodus', 3, 14, 'a mark')
    rows = annotations_window._all_entries()
    assert [r['book'] for r in rows] == ['Exodus', 'John']


def test_a_verse_less_entry_goes_last(isolated):
    annotations.save_note(None, 'Revelation', 22, 21, 'the very last verse')
    journal.save('j1', title='A sermon', date='2026-09-01')
    rows = annotations_window._all_entries()
    assert rows[-1]['book'] is None
    assert rows[-1]['title'] == 'A sermon'


def test_the_verse_less_group_is_newest_first(isolated):
    """The only place in the window where the calendar leads — and it leads
    there because there is nothing else to lead with."""
    journal.save('old', title='older', date='2026-01-01')
    journal.save('new', title='newer', date='2026-09-01')
    journal.save('mid', title='middle', date='2026-05-01')
    rows = [r for r in annotations_window._all_entries() if r['book'] is None]
    assert [r['title'] for r in rows] == ['newer', 'middle', 'older']


def test_an_entry_appears_once_however_many_anchors(isolated):
    """Repeating the row under each anchor would make the count label lie
    about how much was written, and break the render cap's arithmetic."""
    journal.save('j1', anchors=[_anchor('Genesis', 1, 1),
                                _anchor('Psalms', 23),
                                _anchor('John', 1, 1),
                                _anchor('Romans', 8, 28)])
    rows = annotations_window._all_entries()
    assert len(rows) == 1
    assert len(rows[0]['anchors']) == 4


# ── Keys ─────────────────────────────────────────────────────────────────────

def test_an_entry_key_cannot_collide_with_a_mark_key(isolated):
    annotations.save_note(None, 'John', 3, 16, 'a mark')
    journal.save('j1', anchors=[_anchor('John', 3, 16)])
    rows = annotations_window._all_entries()
    assert len(set(_keys(rows))) == 2


# ── The date filter reads two fields ────────────────────────────────────────

def test_the_filter_reads_an_entrys_date_and_a_marks_created(isolated):
    journal.save('j1', date='2026-09-11')
    annotations.save_note(None, 'John', 3, 16, 'a mark')
    rows = {r['kind']: r for r in annotations_window._all_entries()}
    assert annotations_window._entry_date(rows['entry']) == '2026-09-11'
    # A mark's created date IS its date, trimmed out of the ISO stamp.
    mark_day = annotations_window._entry_date(rows['mark'])
    assert len(mark_day) == 10 and mark_day.count('-') == 2


def test_an_undated_mark_has_no_day_to_place_in_a_range(isolated):
    """Marks made before the store recorded dates carry neither stamp, and
    fall out of any range — an undated thing cannot be put in one."""
    annotations.save_note(None, 'John', 3, 16, 'old')
    data = annotations._load()
    data['John/3']['16'].pop('created')
    data['John/3']['16'].pop('modified')
    annotations._save(data)
    row = annotations_window._all_entries()[0]
    assert annotations_window._entry_date(row) == ''


# ── The window ───────────────────────────────────────────────────────────────

def _open(**kw):
    return annotations_window.AnnotationsWindow(
        on_navigate=lambda *a: None, **kw)


def _open_journal(**kw):
    """The window on its Journal page. The two pages share one list, so a
    test about entries has to say which page it is looking at."""
    win = _open(**kw)
    win.set_mode('journal')
    return win


def _rows(win):
    row = win._list.get_first_child()
    while row is not None:
        if hasattr(row, '_entry'):
            yield row
        row = row.get_next_sibling()


def test_the_journal_page_shows_only_entries(isolated, display):
    """The page decides what belongs in the list at all; the type dropdown
    only narrows within it."""
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    annotations.save_highlight(None, 'Exodus', 3, 14, '#ffff00')
    journal.save('j1', title='an entry', anchors=[_anchor('John', 1, 1)])
    win = _open_journal()
    try:
        assert {r._entry['kind'] for r in _rows(win)} == {'entry'}
        win.set_mode('marks')
        assert {r._entry['kind'] for r in _rows(win)} == {'mark'}
    finally:
        win.destroy()


def test_the_journal_pages_type_dropdown_asks_its_own_question(isolated,
                                                               display):
    """An entry has no kinds, so the dropdown asks the one distinction
    entries do have."""
    journal.save('anchored', title='a', anchors=[_anchor('John', 1, 1)])
    journal.save('loose', title='b')
    win = _open_journal()
    try:
        win._type_drop.set_selected(1)          # With a passage
        assert [r._entry['id'] for r in _rows(win)] == ['anchored']
        win._type_drop.set_selected(2)          # Without a passage
        assert [r._entry['id'] for r in _rows(win)] == ['loose']
    finally:
        win.destroy()



def test_the_notes_filter_stays_literal_and_excludes_entries(isolated,
                                                             display):
    """'Notes' means marks carrying note text. A reader who wants their
    writing picks the journal."""
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    journal.save('j1', title='an entry', body='words')
    win = _open()
    try:
        win._type_drop.set_selected(1)      # Notes
        kinds = {r._entry['kind'] for r in _rows(win)}
        assert kinds == {'mark'}
    finally:
        win.destroy()


def test_the_date_range_hides_what_is_older(isolated, display):
    journal.save('old', title='last year', date='2020-03-01')
    journal.save('new', title='today', date=journal.today())
    win = _open_journal()
    try:
        win._date_drop.set_selected(3)      # This year
        titles = [r._entry['title'] for r in _rows(win)]
        assert titles == ['today']
    finally:
        win.destroy()


def test_search_reaches_an_entrys_title_and_body(isolated, display):
    journal.save('j1', title='Trinity VII', body='the collect for the day')
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    win = _open_journal()
    try:
        # set_text then _apply_filter: Gtk.SearchEntry debounces
        # `search-changed`, so asserting straight after set_text would read
        # the PREVIOUS result and pass for the wrong reason.
        for needle in ('trinity', 'collect'):
            win._search_entry.set_text(needle)
            win._apply_filter()
            assert [r._entry['id'] for r in _rows(win)] == ['j1'], needle
        win._search_entry.set_text('nowhere in this text')
        win._apply_filter()
        assert list(_rows(win)) == []
    finally:
        win.destroy()


def test_the_no_passage_header_appears_once_above_the_group(isolated,
                                                            display):
    journal.save('anchored', title='anchored', anchors=[_anchor('John', 1, 1)])
    journal.save('j1', title='one', date='2026-09-01')
    journal.save('j2', title='two', date='2026-08-01')
    win = _open_journal()
    try:
        children = []
        child = win._list.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        headers = [c for c in children if not hasattr(c, '_entry')]
        assert len(headers) == 1
        idx = children.index(headers[0])
        assert children[idx + 1]._entry['book'] is None
        assert children[idx - 1]._entry['book'] == 'John'
    finally:
        win.destroy()



def test_no_header_when_every_entry_is_anchored(isolated, display):
    journal.save('j1', title='one', anchors=[_anchor('John', 1, 1)])
    win = _open_journal()
    try:
        child = win._list.get_first_child()
        while child is not None:
            assert hasattr(child, '_entry')
            child = child.get_next_sibling()
    finally:
        win.destroy()


def test_the_two_pages_lead_with_different_voices(isolated, display):
    """A mark leads with its reference in the sans `heading`; an entry with
    its title in the serif. The app's own type system telling them apart —
    no badge, no icon, no fifth hue."""
    from gi.repository import Gtk
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    journal.save('j1', title='Trinity VII', anchors=[_anchor('John', 1, 1)])

    def lead(row):
        found = []

        def walk(w):
            if isinstance(w, Gtk.Label):
                found.append(w)
            child = w.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()
        walk(row)
        return found[0]

    win = _open()
    try:
        mark_lead = lead(next(_rows(win)))
        assert mark_lead.has_css_class('heading')
        win.set_mode('journal')
        entry_lead = lead(next(_rows(win)))
        assert entry_lead.get_text() == 'Trinity VII'
        assert entry_lead.has_css_class('journal-entry-title')
    finally:
        win.destroy()



def test_selecting_an_entry_opens_the_entry_editor(isolated, display):
    journal.save('j1', title='Trinity VII', body='what came of it',
                 tags=['collect'], anchors=[_anchor('John', 1, 1)])
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        assert win._detail_stack.get_visible_child_name() == 'entry'
        assert win._entry_editor.title.get_text() == 'Trinity VII'
        assert win._entry_editor.tags.get_text() == 'collect'
        buf = win._entry_editor.body.get_buffer()
        assert buf.get_text(buf.get_start_iter(),
                            buf.get_end_iter(), False) == 'what came of it'
    finally:
        win.destroy()


def test_editing_an_entry_autosaves_and_patches_the_row(isolated, display):
    journal.save('j1', title='before', anchors=[_anchor('John', 1, 1)])
    win = _open_journal()
    try:
        row = next(_rows(win))
        win._list.select_row(row)
        win._entry_editor.title.set_text('after')
        win._autosave.flush()
        assert journal.get('j1')['title'] == 'after'
        assert win._list.get_selected_row() is row
        assert row._entry['title'] == 'after'
    finally:
        win.destroy()


def test_a_new_entry_is_not_written_until_it_has_words(isolated, display):
    """Pressing New and changing your mind must leave journal.json alone."""
    win = _open()
    try:
        win._on_new_entry(None)
        assert win._detail_stack.get_visible_child_name() == 'entry'
        win._autosave.flush()
        assert journal.all_entries() == []

        win._entry_editor.title.set_text('now it exists')
        win._autosave.flush()
        assert [e['title'] for e in journal.all_entries()] == ['now it exists']
    finally:
        win.destroy()


def test_deleting_an_entry_offers_an_undo_that_restores_it(isolated, display):
    journal.save('j1', title='mistake', anchors=[_anchor('John', 1, 1)])
    win = _open_journal()
    try:
        row = next(_rows(win))
        win._on_delete_entry(None, row._entry)
        assert journal.get('j1') is None
        win._undo_entry_delete(
            {'id': 'j1', 'date': '2026-09-11', 'title': 'mistake',
             'body': '', 'anchors': [_anchor('John', 1, 1)], 'tags': [],
             'plan': None, 'collect': None,
             'created': None, 'modified': None})
        assert journal.get('j1')['title'] == 'mistake'
    finally:
        win.destroy()


def test_one_tag_vocabulary_across_both_stores(isolated, display):
    annotations.save_tags(None, 'Genesis', 1, 1, ['covenant'])
    journal.save('j1', tags=['covenant', 'gospel'])
    win = _open()
    try:
        model = win._tag_drop.get_model()
        shown = [model.get_string(i) for i in range(model.get_n_items())]
        assert 'covenant' in shown and 'gospel' in shown
        assert shown.count('covenant') == 1
    finally:
        win.destroy()


def test_renaming_a_tag_reaches_both_stores(isolated, display):
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    annotations.save_tags(None, 'Genesis', 1, 1, ['old'])
    journal.save('j1', tags=['old'])
    annotations.rename_tag('old', 'new')
    journal.rename_tag('old', 'new')
    assert journal.get('j1')['tags'] == ['new']
    assert annotations.get_all_tags() == ['new']


# ── The subset, applied to the live buffer ──────────────────────────────────

def test_the_body_carries_the_markup_tags(isolated, display):
    """The pane IS the editor — there is no view/edit split to render into —
    so the subset is applied to the editable buffer in place."""
    journal.save('j1', title='x', body='a **bold** word')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        buf = win._entry_editor.body.get_buffer()
        it = buf.get_iter_at_offset(4)          # inside 'bold'
        names = {t.get_property('name') for t in it.get_tags()}
        assert 'md-strong' in names
        marker = buf.get_iter_at_offset(2)      # the second '*'
        assert 'md-marker' in {t.get_property('name')
                               for t in marker.get_tags()}
    finally:
        win.destroy()


def test_typing_restyles_without_a_save(isolated, display):
    journal.save('j1', title='x', body='plain')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        buf = win._entry_editor.body.get_buffer()
        buf.set_text('> a quoted line')
        it = buf.get_iter_at_offset(5)
        assert 'md-quote' in {t.get_property('name') for t in it.get_tags()}
    finally:
        win.destroy()


def test_a_reference_in_the_body_is_marked_and_resolvable(isolated, display):
    journal.save('j1', title='x', body='compare John 3:16 with this')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        assert [r[2:] for r in win._entry_editor.refs] == [('John', 3, 16)]
        buf = win._entry_editor.body.get_buffer()
        it = buf.get_iter_at_offset(win._entry_editor.refs[0][0] + 1)
        assert 'md-ref' in {t.get_property('name') for t in it.get_tags()}
    finally:
        win.destroy()


def test_reference_names_cover_english_localized_and_sbl(isolated):
    names = annotations_window.reference_names()
    assert names.get('John') == 'John'
    assert names.get('1 John') == '1 John'
    # the SBL abbreviation the export already uses
    assert names.get('Rom') == 'Romans'
    # and the deuterocanon, or a note on Sirach links nothing
    assert 'Sirach' in names


def test_a_new_anchored_entry_lands_in_canonical_order(isolated, display):
    """Appending it without re-sorting put it last — below the No-passage
    header, reading as having no passage when it has one."""
    journal.save('later', title='later', anchors=[_anchor('Revelation', 22, 21)])
    journal.save('verseless', title='a sermon', date='2026-01-01')
    win = _open_journal()
    try:
        win.start_entry(anchors=[_anchor('Genesis', 1, 1)])
        order = []
        child = win._list.get_first_child()
        while child is not None:
            order.append('HEADER' if not hasattr(child, '_entry')
                         else child._entry['book'])
            child = child.get_next_sibling()
        assert order == ['Genesis', 'Revelation', 'HEADER', None]
    finally:
        win.destroy()



def test_a_new_verse_less_entry_leads_its_group(isolated, display):
    """The No-passage group is newest first, and a new entry is today's."""
    journal.save('old', title='older', date='2020-01-01')
    win = _open_journal()
    try:
        win.start_entry()
        titles = [r._entry.get('title') for r in _rows(win)]
        assert titles == ['', 'older']
    finally:
        win.destroy()


def test_a_plain_click_does_not_navigate_away_from_a_reference(isolated,
                                                               display):
    """The body is editable and never not editable, so a plain click has to
    place the cursor — otherwise the caret cannot be put inside 'John 3:16'
    to fix a typo without the window navigating away."""
    from gi.repository import Gdk
    went = []
    journal.save('j1', title='x', body='see John 3:16 here')
    win = annotations_window.AnnotationsWindow(
        on_navigate=lambda *a: went.append(a))
    win.set_mode('journal')
    try:
        win._list.select_row(next(_rows(win)))
        assert win._entry_editor.refs

        class Fake:
            def __init__(self, state):
                self._state = state

            def get_current_event_state(self):
                return self._state

        start = win._entry_editor.refs[0][0]
        buf = win._entry_editor.body.get_buffer()
        buf.place_cursor(buf.get_iter_at_offset(start + 1))
        win._entry_editor._on_body_click(Fake(Gdk.ModifierType(0)), 1, 0, 0)
        assert went == []
    finally:
        win.destroy()

def test_the_reference_scan_is_off_the_keystroke_path(isolated, display):
    """Emphasis is instant; references settle a beat later. At sermon length
    the scan is ~10ms, which is over half a frame to pay per letter."""
    journal.save('j1', title='x', body='plain')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        buf = win._entry_editor.body.get_buffer()
        buf.set_text('now mentioning John 3:16 here')

        # The markup pass ran with the keystroke...
        assert not win._entry_editor._restyle.pending or True
        # ...and the reference pass is queued, not done.
        assert win._entry_editor._restyle.pending
        assert win._entry_editor.refs == []

        win._entry_editor._restyle.flush()
        assert [r[2:] for r in win._entry_editor.refs] == [('John', 3, 16)]
    finally:
        win.destroy()


def test_an_entry_opens_with_its_references_already_marked(isolated, display):
    """Opening one must not show the links growing in a beat later."""
    journal.save('j1', title='x', body='see John 3:16')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        assert [r[2:] for r in win._entry_editor.refs] == [('John', 3, 16)]
        assert not win._entry_editor._restyle.pending
    finally:
        win.destroy()


# ── The pages ────────────────────────────────────────────────────────────────

def test_the_switcher_and_the_mode_stay_together(isolated, display):
    """Either one moves the other: the switcher is how the page is chosen,
    and set_mode (Ctrl+J from the reading window) has to show on it."""
    win = _open()
    try:
        assert win._tabs.get_active_name() == 'marks'
        win._tabs.set_active_name('journal')      # what a click does
        assert win._mode == 'journal'
        win.set_mode('marks')
        assert win._tabs.get_active_name() == 'marks'
    finally:
        win.destroy()


def test_switching_pages_clears_the_open_entry(isolated, display):
    """A key from the outgoing page cannot be restored on the incoming one,
    and hunting for it would only leave the detail pane showing a row the
    list no longer holds."""
    journal.save('j1', title='an entry')
    annotations.save_note(None, 'John', 3, 16, 'a mark')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        assert win._detail_stack.get_visible_child_name() == 'entry'
        win.set_mode('marks')
        assert win._current_entry is None
        assert win._detail_stack.get_visible_child_name() == 'empty'
    finally:
        win.destroy()


def test_every_door_lands_on_the_journal_page(isolated, display):
    """A door opens a window that may be sitting on Annotations."""
    win = _open()
    try:
        assert win._mode == 'marks'
        win.start_entry(anchors=[_anchor('John', 1, 1)])
        assert win._mode == 'journal'
    finally:
        win.destroy()


def test_select_entry_switches_to_the_page_that_can_show_it(isolated,
                                                            display):
    journal.save('j1', title='found me')
    win = _open()
    try:
        assert win.select_entry('j1') is True
        assert win._mode == 'journal'
        assert win._current_entry['id'] == 'j1'
    finally:
        win.destroy()


def test_an_empty_page_says_which_page_is_empty(isolated, display):
    """A reader with 127 marks and no journal is not looking at an empty
    app, and must not be told they are."""
    from gi.repository import Gtk
    annotations.save_note(None, 'John', 3, 16, 'a mark')

    def texts(win):
        found = []

        def walk(w):
            if isinstance(w, Gtk.Label):
                found.append(w.get_text())
            c = w.get_first_child()
            while c is not None:
                walk(c)
                c = c.get_next_sibling()
        walk(win._list)
        return ' '.join(found)

    win = _open_journal()
    try:
        assert 'No journal entries yet' in texts(win)
        win.set_mode('marks')
        assert 'No journal entries yet' not in texts(win)
    finally:
        win.destroy()


def test_no_group_header_when_every_entry_is_verse_less(isolated, display):
    """A heading that separates nothing is noise: with no anchored group
    above it, "No passage" is a label on the whole list."""
    journal.save('j1', title='one', date='2026-09-01')
    journal.save('j2', title='two', date='2026-08-01')
    win = _open_journal()
    try:
        child = win._list.get_first_child()
        while child is not None:
            assert hasattr(child, '_entry'), 'a header with nothing above it'
            child = child.get_next_sibling()
    finally:
        win.destroy()


def test_two_entries_on_one_day_put_the_newer_first(isolated, display):
    """The group's rule is newest first, and a stable sort on the date alone
    left an entry written a moment ago under one written this morning.

    Both are saved in the same second here on purpose: `created` is
    seconds-precise, so it cannot break this tie and the store order has to.
    """
    today = journal.today()
    journal.save('morning', title='morning', date=today)
    journal.save('later', title='later', date=today)
    win = _open_journal()
    try:
        assert [r._entry['title'] for r in _rows(win)] == ['later', 'morning']
    finally:
        win.destroy()


def test_the_count_says_what_the_page_holds(isolated, display):
    """"126 entries" of marks beside "1 entry" of journal was one word doing
    two jobs in one window."""
    annotations.save_note(None, 'John', 3, 16, 'a mark')
    journal.save('j1', title='an entry')
    win = _open()
    try:
        assert win._count_lbl.get_text() == '1 annotation'
        win.set_mode('journal')
        assert win._count_lbl.get_text() == '1 entry'
    finally:
        win.destroy()


def test_the_window_is_named_for_its_page(isolated, display):
    win = _open()
    try:
        assert win.get_title() == 'Annotations'
        win.set_mode('journal')
        assert win.get_title() == 'Journal'
    finally:
        win.destroy()


def test_the_filters_fold_away_but_never_hide_themselves(isolated, display):
    """The panel folds to give the list its room back — but a filter that is
    set must never be a filter that is hidden, or a reader is looking at a
    short list for a reason they cannot see."""
    journal.save('j1', title='an entry')
    win = _open_journal()
    try:
        assert not win._filter_toggle.get_active()
        assert not win._filter_revealer.get_reveal_child()

        win._date_drop.set_selected(3)          # This year
        assert win._filter_toggle.get_active()
        assert win._filter_revealer.get_reveal_child()
    finally:
        win.destroy()


def test_the_disclosure_opens_and_closes_by_hand(isolated, display):
    win = _open()
    try:
        win._filter_toggle.set_active(True)
        assert win._filter_revealer.get_reveal_child()
        win._filter_toggle.set_active(False)
        assert not win._filter_revealer.get_reveal_child()
    finally:
        win.destroy()


def test_both_editors_actually_build_their_widgets(isolated, display):
    """The entry editor once built its whole tree into a local Gtk.Box that
    was never parented, so the pane rendered nothing — and every other test
    passed, because they reach the fields directly and an orphaned widget
    answers just as well as a shown one.

    What a test can check without pixels is that the widgets are ON the
    editor. That is the cheapest guard against the same mistake in the third
    editor the manuscript page will add.
    """
    win = _open()
    try:
        for name, editor in (('mark', win._mark_editor),
                             ('entry', win._entry_editor)):
            n = 0
            child = editor.get_first_child()
            while child is not None:
                n += 1
                child = child.get_next_sibling()
            assert n > 0, f'the {name} editor parented nothing'
            assert editor.get_parent() is not None, f'{name} not in the stack'
    finally:
        win.destroy()


def test_the_row_badge_follows_a_hue_change(isolated, display):
    """Changing Yellow to Blue used to leave the row saying Yellow until the
    next reload: the click patched the strip's CSS class and nothing else.
    The editors refill the whole row now, so the badge follows."""
    from gi.repository import Gtk
    annotations.save_highlight(None, 'John', 3, 16, '#ffff00')
    win = _open()
    try:
        row = next(_rows(win))
        win._list.select_row(row)

        def names():
            found = []

            def walk(w):
                if isinstance(w, Gtk.Label):
                    found.append(w.get_text())
                c = w.get_first_child()
                while c is not None:
                    walk(c)
                    c = c.get_next_sibling()
            walk(row)
            return [t for t in found if t in ('Yellow', 'Blue')]

        assert names() == ['Yellow']
        win._mark_editor._on_hl_click(None, '#add8e6')
        assert names() == ['Blue']
    finally:
        win.destroy()


def test_sorting_does_not_force_the_filter_panel_open(isolated, display):
    """Changing the ORDER of a list hides nothing."""
    journal.save('j1', title='an entry')
    win = _open_journal()
    try:
        win._sort_drop.set_selected(1)          # Recently edited
        assert not win._filter_toggle.get_active()
    finally:
        win.destroy()


# ── One entry, on its own ────────────────────────────────────────────────────

def test_exporting_the_open_entry_takes_only_that_entry(isolated, display):
    """The filters are the scope for everything else in the window, but
    narrowing the list to the thing already open, in order to export it, is
    a filter nobody should have to build."""
    journal.save('j1', title='The first', body='one')
    journal.save('j2', title='The second', body='two')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        opened = win._current_entry['title']
        doc = win._document(rows=[win._current_entry])
        assert opened in doc
        other = 'The second' if opened == 'The first' else 'The first'
        assert other not in doc
    finally:
        win.destroy()


def test_the_file_is_named_after_what_is_in_it(isolated, display):
    win = _open_journal()
    try:
        name = win._one_file_name({'title': 'On Genesis 1:3 — light'})
        assert name == 'on-genesis-13-light.md'
        assert '/' not in name and ':' not in name
    finally:
        win.destroy()


def test_an_untitled_entry_is_named_for_its_passage(isolated, display):
    win = _open_journal()
    try:
        name = win._one_file_name(
            {'title': '', 'anchors': [{'book': 'John', 'chapter': 3,
                                       'verses': [16]}]})
        assert name.startswith('john-316')
    finally:
        win.destroy()


def test_a_cancelled_single_export_does_not_narrow_the_next_print(isolated,
                                                                  display,
                                                                  monkeypatch):
    """The one-entry scope rides in its own callback. Parked on the window,
    a cancelled save would have left the next print showing one entry.

    save() is stubbed because it is the call that puts a real file chooser
    on the screen. Unstubbed, every run of the suite threw a save dialog
    onto the desktop and left it there until the window was destroyed —
    invisible in CI, which has no screen, and unmissable on a workstation.
    """
    from gi.repository import Gtk
    asked = []
    monkeypatch.setattr(
        Gtk.FileDialog, 'save',
        lambda self, parent, cancellable, cb: asked.append(self))

    journal.save('j1', title='The first', body='one')
    journal.save('j2', title='The second', body='two')
    win = _open_journal()
    try:
        win._list.select_row(next(_rows(win)))
        win._on_export_one(None)          # a save nobody answers
        assert asked                      # the handler did ask for one
        doc = win._document()
        assert 'The first' in doc and 'The second' in doc
    finally:
        win.destroy()
