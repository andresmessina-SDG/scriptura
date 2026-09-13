"""The Sermons page: the list, its groups, its editor and its doors.

The page machinery is the journal's — one list, one render cap, one autosave
— so these hold only what is different: series lead the order and draw the
group headings, the type dropdown asks whether a sermon has been preached,
the editor writes a big idea and a delivery history, and the collecting doors
land text in the right place whether or not the manuscript is open.
"""
import pytest

import annotations
import annotations_window
import journal
import sermons


@pytest.fixture
def display():
    """Skip when there is no screen — the window is a real Adw.Window."""
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
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 'sermons.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    monkeypatch.setattr(sermons, '_load_failed', False)
    return tmp_path


def _anchor(book, chapter, *verses):
    return {'book': book, 'chapter': chapter, 'verses': list(verses)}


def _open_sermons(**kw):
    win = annotations_window.AnnotationsWindow(
        on_navigate=lambda *a: None, **kw)
    win.set_mode('sermons')
    return win


def _rows(win):
    row = win._list.get_first_child()
    while row is not None:
        if hasattr(row, '_entry'):
            yield row
        row = row.get_next_sibling()


def _headings(win):
    """The group captions, in the order they are drawn."""
    from gi.repository import Gtk
    found = []
    row = win._list.get_first_child()
    while row is not None:
        if not hasattr(row, '_entry'):
            # Labels nest: a named series heading carries its rename button
            # on a line of its own inside the caption box.
            def walk(widget):
                child = widget.get_first_child()
                while child is not None:
                    if isinstance(child, Gtk.Label):
                        found.append(child.get_text())
                    elif isinstance(child, Gtk.Box):
                        walk(child)
                    child = child.get_next_sibling()
            box = row.get_child()
            if isinstance(box, Gtk.Box):
                walk(box)
        row = row.get_next_sibling()
    return found


def _sower(sermon_id='s1', **kw):
    fields = dict(title='The Sower Went Forth',
                  idea='The seed is never the problem; the soil is.',
                  body='## I. The seed that is scattered',
                  anchors=[_anchor('Matthew', 13)],
                  series={'name': 'Parables of the Kingdom', 'part': 3})
    fields.update(kw)
    sermons.save(sermon_id, **fields)


# ── The rows ────────────────────────────────────────────────────────────────

def test_a_sermon_appears_once_at_its_first_passage(isolated):
    sermons.save('s1', title='The Sower',
                 anchors=[_anchor('Matthew', 13), _anchor('Isaiah', 55, 10)])
    rows = [r for r in annotations_window._all_entries()
            if r['kind'] == 'sermon']
    assert len(rows) == 1
    assert (rows[0]['book'], rows[0]['chapter']) == ('Matthew', 13)


def test_a_sermon_with_no_passage_is_legal(isolated):
    sermons.save('s1', title='A funeral homily')
    row = [r for r in annotations_window._all_entries()
           if r['kind'] == 'sermon'][0]
    assert row['book'] is None


def test_the_page_shows_only_sermons(isolated, display):
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    journal.save('j1', title='an entry', anchors=[_anchor('John', 1, 1)])
    _sower()
    win = _open_sermons()
    try:
        assert {r._entry['kind'] for r in _rows(win)} == {'sermon'}
        win.set_mode('journal')
        assert {r._entry['kind'] for r in _rows(win)} == {'entry'}
    finally:
        win.destroy()


def test_the_type_dropdown_asks_whether_it_has_been_preached(isolated,
                                                             display):
    _sower('preached', preached=['2026-02-08'])
    _sower('waiting', title='The Least of All Seeds')
    win = _open_sermons()
    try:
        assert [r._entry['id'] for r in _rows(win)] == ['preached', 'waiting']
        win._type_drop.set_selected(1)          # Preached
        assert [r._entry['id'] for r in _rows(win)] == ['preached']
        win._type_drop.set_selected(2)          # Not yet preached
        assert [r._entry['id'] for r in _rows(win)] == ['waiting']
    finally:
        win.destroy()


def test_the_count_is_named_for_the_page(isolated, display):
    _sower()
    win = _open_sermons()
    try:
        assert 'sermon' in win._count_lbl.get_text()
    finally:
        win.destroy()


def test_a_reader_with_marks_and_no_sermons_is_not_told_the_app_is_empty(
        isolated, display):
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    win = _open_sermons()
    try:
        assert not list(_rows(win))
        win.set_mode('marks')
        assert list(_rows(win))
    finally:
        win.destroy()


# ── Series ──────────────────────────────────────────────────────────────────

def test_series_group_and_lead_the_list(isolated, display):
    _sower('advent', title='A Voice in the Wilderness',
           anchors=[_anchor('Isaiah', 40)],
           series={'name': 'Advent 2025', 'part': 2})
    _sower('part3')
    _sower('part2', title='A Man Sowed Good Seed',
           series={'name': 'Parables of the Kingdom', 'part': 2})
    _sower('loose', title='Remember Now Thy Creator',
           anchors=[_anchor('Ecclesiastes', 12)], series=None)
    win = _open_sermons()
    try:
        assert [r._entry['id'] for r in _rows(win)] == [
            'advent', 'part2', 'part3', 'loose']
        assert _headings(win) == ['Advent 2025', 'Parables of the Kingdom',
                                  'No series']
    finally:
        win.destroy()


def test_a_series_sorts_by_its_parts_not_by_the_canon(isolated, display):
    """A preacher working backwards through a book is ordinary, and the
    series IS the order they were preached in."""
    _sower('one', title='First', anchors=[_anchor('Revelation', 1)],
           series={'name': 'A series', 'part': 1})
    _sower('two', title='Second', anchors=[_anchor('Genesis', 1)],
           series={'name': 'A series', 'part': 2})
    win = _open_sermons()
    try:
        assert [r._entry['id'] for r in _rows(win)] == ['one', 'two']
    finally:
        win.destroy()


def test_an_unnumbered_sermon_sits_after_the_numbered_ones(isolated, display):
    _sower('numbered', series={'name': 'A series', 'part': 1})
    _sower('unnumbered', title='Not placed yet',
           series={'name': 'A series'})
    win = _open_sermons()
    try:
        assert [r._entry['id'] for r in _rows(win)] == ['numbered',
                                                        'unnumbered']
    finally:
        win.destroy()


def test_the_series_headings_are_not_drawn_when_sorting_by_date(isolated,
                                                               display):
    """Out of series order a heading would appear and reappear down the
    list, which is a heading that means nothing."""
    _sower()
    win = _open_sermons()
    try:
        assert _headings(win) == ['Parables of the Kingdom']
        win._sort_drop.set_selected(1)          # Recently preached
        assert _headings(win) == []
    finally:
        win.destroy()


def test_the_sort_resets_when_the_page_changes(isolated, display):
    """'Recently preached' means nothing on a page with no preaching
    dates."""
    _sower()
    win = _open_sermons()
    try:
        win._sort_drop.set_selected(1)
        win.set_mode('journal')
        assert win._sort_drop.get_selected() == 0
    finally:
        win.destroy()


# ── The date column and the date filter ─────────────────────────────────────

def test_the_row_shows_the_day_it_was_last_preached(isolated):
    _sower(preached=['2024-03-03', '2026-02-08'])
    row = [r for r in annotations_window._all_entries()
           if r['kind'] == 'sermon'][0]
    assert '2026' in annotations_window._preached_label(row)


def test_a_sermon_never_preached_shows_no_day(isolated):
    _sower()
    row = [r for r in annotations_window._all_entries()
           if r['kind'] == 'sermon'][0]
    assert annotations_window._preached_label(row) == ''


def test_the_date_filter_reads_the_preaching_day(isolated):
    _sower(preached=['2026-02-08'])
    row = [r for r in annotations_window._all_entries()
           if r['kind'] == 'sermon'][0]
    assert annotations_window._entry_date(row) == '2026-02-08'


def test_an_unpreached_sermon_falls_back_to_the_day_it_was_begun(isolated):
    """Or a manuscript written last week would fall out of "this week",
    which is exactly when a preacher looks for it."""
    _sower()
    row = [r for r in annotations_window._all_entries()
           if r['kind'] == 'sermon'][0]
    assert annotations_window._entry_date(row) == row['created'][:10]


# ── Starting one ────────────────────────────────────────────────────────────

def test_starting_a_sermon_writes_nothing_until_there_are_words(isolated,
                                                                display):
    win = _open_sermons()
    try:
        win.start_sermon()
        assert sermons.all_sermons() == []
    finally:
        win.destroy()
    assert sermons.all_sermons() == []


def test_a_started_sermon_keeps_the_passage_and_the_day_it_came_from(
        isolated, display):
    win = _open_sermons()
    try:
        row = win.start_sermon(anchors=[_anchor('Matthew', 13)],
                               collect='anglican:sexagesima')
        win._sermon_editor.title.set_text('The Sower Went Forth')
        win._autosave.flush()
        stored = sermons.get(row['id'])
        assert stored['anchors'] == [{'book': 'Matthew', 'chapter': 13,
                                      'verses': []}]
        assert stored['collect'] == 'anglican:sexagesima'
    finally:
        win.destroy()


def test_the_pencil_starts_a_sermon_on_the_sermons_page(isolated, display):
    win = _open_sermons()
    try:
        win._on_new_entry(None)
        assert win._current_entry['kind'] == 'sermon'
        win.set_mode('journal')
        win._on_new_entry(None)
        assert win._current_entry['kind'] == 'entry'
    finally:
        win.destroy()


# ── The editor ──────────────────────────────────────────────────────────────

def test_the_editor_writes_the_idea_and_the_series(isolated, display):
    win = _open_sermons()
    try:
        row = win.start_sermon()
        editor = win._sermon_editor
        editor.title.set_text('The Sower Went Forth')
        editor.idea.set_text('The seed is never the problem; the soil is.')
        editor.series.set_text('Parables of the Kingdom')
        editor.part.set_text('3')
        win._autosave.flush()
        stored = sermons.get(row['id'])
        assert stored['idea'].startswith('The seed is never')
        assert stored['series'] == {'name': 'Parables of the Kingdom',
                                    'part': 3}
    finally:
        win.destroy()


def test_a_part_with_no_series_is_not_a_series(isolated, display):
    win = _open_sermons()
    try:
        row = win.start_sermon()
        win._sermon_editor.title.set_text('Untitled but written')
        win._sermon_editor.part.set_text('3')
        win._autosave.flush()
        assert sermons.get(row['id'])['series'] is None
    finally:
        win.destroy()


def test_the_editor_has_no_date_field(isolated, display):
    """The journal's date is the day an entry is about; a sermon has a
    writing span and a preaching day, and neither is that."""
    win = _open_sermons()
    try:
        assert not hasattr(win._sermon_editor, 'date_button')
    finally:
        win.destroy()


def test_a_preaching_date_is_added_and_removed_through_the_row(isolated,
                                                               display):
    win = _open_sermons()
    try:
        row = win.start_sermon()
        win._sermon_editor.title.set_text('The Sower Went Forth')
        row['preached'] = ['2026-02-08']
        win._sermon_editor._on_drop_date(None, 0)
        win._autosave.flush()
        assert sermons.get(row['id'])['preached'] == []
    finally:
        win.destroy()


def test_the_editor_says_which_day_it_was_written_for(isolated, display):
    _sower(collect='anglican:sexagesima')
    win = _open_sermons()
    try:
        win._list.select_row(next(_rows(win)))
        assert win._sermon_editor._day.get_visible()
        assert 'Sexagesima' in win._sermon_editor._day.get_text()
    finally:
        win.destroy()


# ── Collecting ──────────────────────────────────────────────────────────────

def test_collecting_into_a_closed_sermon_goes_through_the_store(isolated,
                                                                display):
    _sower(body='the body so far')
    win = _open_sermons()
    try:
        assert win.collect_into('s1', 'Isaiah 55:10–11',
                                _anchor('Isaiah', 55, 10, 11))
        stored = sermons.get('s1')
        assert stored['body'].endswith('Isaiah 55:10–11')
        assert _anchor('Isaiah', 55, 10, 11) in stored['anchors']
    finally:
        win.destroy()


def test_collecting_into_the_open_sermon_goes_through_the_buffer(isolated,
                                                                 display):
    """A store write underneath an open editor would be overwritten by the
    next autosave."""
    _sower(body='the body so far')
    win = _open_sermons()
    try:
        win._list.select_row(next(_rows(win)))
        assert win.open_sermon_id() == 's1'
        win.collect_into('s1', 'Isaiah 55:10–11', _anchor('Isaiah', 55, 10))
        buf = win._sermon_editor.body.get_buffer()
        shown = buf.get_text(*buf.get_bounds(), False)
        assert shown.endswith('Isaiah 55:10–11')
        assert sermons.get('s1')['body'] == shown
    finally:
        win.destroy()


def test_collecting_adds_the_passage_to_the_anchors(isolated, display):
    _sower()
    win = _open_sermons()
    try:
        win._list.select_row(next(_rows(win)))
        win.collect_into('s1', 'Isaiah 55:10', _anchor('Isaiah', 55, 10))
        assert any(a['book'] == 'Isaiah'
                   for a in sermons.get('s1')['anchors'])
    finally:
        win.destroy()


def test_collecting_into_a_sermon_that_is_gone_says_so(isolated, display):
    win = _open_sermons()
    try:
        assert win.collect_into('nope', 'text') is False
    finally:
        win.destroy()


# ── Deleting ────────────────────────────────────────────────────────────────

def test_deleting_a_sermon_can_be_undone(isolated, display):
    _sower(preached=['2026-02-08'])
    win = _open_sermons()
    try:
        row = next(_rows(win))
        win._on_delete_entry(None, row._entry)
        assert sermons.all_sermons() == []
        win._undo_sermon_delete(sermons._sermon('s1', {
            'title': 'The Sower Went Forth', 'preached': ['2026-02-08']}))
        assert sermons.get('s1')['preached'] == ['2026-02-08']
    finally:
        win.destroy()


# ── Search ──────────────────────────────────────────────────────────────────

def test_app_search_finds_a_sermon_by_its_big_idea(isolated):
    import search_panel
    _sower()
    panel = search_panel.SearchPanel(
        on_result_clicked=lambda *a: None, on_close=lambda *a: None,
        on_open_entry=lambda *a: None, on_open_sermon=lambda *a: None)
    found = panel._own_matches('the soil is')
    assert [r['kind'] for r in found] == ['sermon']


def test_the_sermon_section_is_not_offered_without_a_door(isolated):
    """A row that cannot be followed is worse than no row."""
    import search_panel
    _sower()
    panel = search_panel.SearchPanel(
        on_result_clicked=lambda *a: None, on_close=lambda *a: None)
    panel._own = panel._own_matches('the soil is')
    panel._append_own([])
    labels = []
    row = panel._results_list.get_first_child()
    while row is not None:
        labels.append(row.get_child().get_label()
                      if hasattr(row.get_child(), 'get_label') else '')
        row = row.get_next_sibling()
    assert not any('sermon' in (t or '').lower() for t in labels)


# ── Export ──────────────────────────────────────────────────────────────────

def test_the_export_carries_the_idea_and_the_series(isolated):
    import passage_export
    _sower(preached=['2026-02-08'])
    rows = [r for r in annotations_window._all_entries()
            if r['kind'] == 'sermon']
    doc = passage_export.build_annotations(rows, 'KJVA', title='Sermons')
    assert 'The Sower Went Forth' in doc
    assert 'The seed is never the problem' in doc
    assert 'Parables of the Kingdom, part 3' in doc
    assert '2026-02-08' in doc


# ── Tags are one vocabulary across three stores ─────────────────────────────

def test_the_tag_manager_counts_sermons_too(isolated, display):
    annotations.save_note(None, 'Genesis', 1, 1, 'a mark')
    annotations.save_tags(None, 'Genesis', 1, 1, ['kingdom'])
    _sower(tags=['kingdom'])
    win = annotations_window.TagManagerWindow()
    try:
        win._populate_tags()
        row = win._list_box.get_first_child()
        found = []
        while row is not None:
            found.append(row)
            row = row.get_next_sibling()
        # One row for one tag, counted across both stores that carry it.
        assert len(found) == 1
    finally:
        win.destroy()


def test_renaming_a_tag_reaches_the_sermons(isolated):
    _sower(tags=['kingdom'])
    journal.save('j1', title='an entry', tags=['kingdom'])
    sermons.rename_tag('kingdom', 'reign')
    journal.rename_tag('kingdom', 'reign')
    assert sermons.get('s1')['tags'] == ['reign']
    assert journal.get('j1')['tags'] == ['reign']


# ── Room to write ───────────────────────────────────────────────────────────
#
# The page is somewhere you WRITE, and it was spending more than half the
# window saying what you were writing about: 318px of chrome above the sheet
# on a 770px window, three of those rows one short fact each. These hold the
# three answers — one metadata line, a sidebar you can send away, and a mode
# that takes everything but the title and the paper.


def _meta_children(editor):
    out, c = [], editor._meta_row.get_first_child()
    while c is not None:
        out.append(c)
        c = c.get_next_sibling()
    return out


def test_the_sermon_s_facts_share_one_row(isolated, display):
    _sower(preached=['2026-02-08'])
    win = _open_sermons()
    try:
        win.select_sermon('s1')
        ed = win._sermon_editor
        # Series+Part, the preaching dates, the passages and the day a door
        # stamped: four groups on one wrap box, not four rows of the page.
        # Ordered by how often they are wanted: what it is, when it was
        # preached, what it is about, and last the day a door stamped on it.
        assert _meta_children(ed) == [ed.series.get_parent(),
                                      ed._preached_box, ed._anchor_box,
                                      ed._day]
    finally:
        win.destroy()


def test_space_divides_the_groups_and_no_glyph_does(isolated, display):
    """Two glyph dividers were tried and both failed. Loose in the wrap box a
    middot stayed at the END of the line it was meant to open ("Part 1 ·"
    with nothing after it); bound to its group it led the next line — and at
    the width he writes at every group takes a line of its own, so the dots
    just sat in the left margin reading as bullets."""
    from gi.repository import Gtk
    _sower(preached=['2026-02-08'])
    win = _open_sermons()
    try:
        win.select_sermon('s1')
        ed = win._sermon_editor
        for group in _meta_children(ed):
            first = group.get_first_child()
            assert not (isinstance(first, Gtk.Label)
                        and first.get_text() in ('·', '•', '|', '–'))
        assert ed._meta_row.get_child_spacing() == ed.META_GAP
    finally:
        win.destroy()


def test_the_journal_shares_the_row_too(isolated, display):
    journal.save('j1', title='an entry', anchors=[_anchor('John', 1, 1)])
    win = _open_sermons()
    try:
        win.set_mode('journal')
        ed = win._entry_editor
        assert len(_meta_children(ed)) == 2      # the date, then the passages
    finally:
        win.destroy()


def test_f9_sends_the_list_away_and_brings_it_back(isolated, display):
    _sower()
    win = _open_sermons()
    try:
        assert win._split_view.get_show_sidebar()
        win._toggle_sidebar()
        assert not win._split_view.get_show_sidebar()
        # The button is bound to the view, not to its own last click: the
        # split view hides the sidebar by itself when a row is opened on a
        # collapsed window, and a button still claiming the list is showing
        # would be lying about the window.
        assert not win._sidebar_btn.get_active()
        win._toggle_sidebar()
        assert win._split_view.get_show_sidebar()
        assert win._sidebar_btn.get_active()
    finally:
        win.destroy()


def test_writing_mode_leaves_the_title_and_the_sheet(isolated, display):
    _sower(preached=['2026-02-08'])
    win = _open_sermons()
    try:
        win.select_sermon('s1')
        ed = win._sermon_editor
        win._set_writing_mode(True)
        assert not win._split_view.get_show_sidebar()
        assert not win._content_tv.get_reveal_top_bars()
        for w in (ed._meta_row, ed._tools, ed._tags_caption, ed.tags, ed.idea):
            assert not w.get_visible()
        # What you came to write in, and what names it.
        assert ed.title.get_visible() and ed.body.get_visible()
    finally:
        win.destroy()


def test_leaving_writing_mode_does_not_conjure_a_quote(isolated, display):
    """`_verse` is hidden for a sermon with no passage. Restoring the page by
    setting everything visible would give it one."""
    _sower(anchors=[])
    win = _open_sermons()
    try:
        win.select_sermon('s1')
        ed = win._sermon_editor
        assert not ed._verse.get_visible()
        win._set_writing_mode(True)
        win._set_writing_mode(False)
        assert not ed._verse.get_visible()
        assert ed._meta_row.get_visible() and ed.tags.get_visible()
    finally:
        win.destroy()


def test_escape_is_only_swallowed_when_there_is_a_mode_to_leave(isolated,
                                                                display):
    _sower()
    win = _open_sermons()
    try:
        assert win._leave_writing_mode() is False
        win._set_writing_mode(True)
        assert win._leave_writing_mode() is True
        assert not win._writing_mode
        assert win._leave_writing_mode() is False
    finally:
        win.destroy()


def test_the_top_edge_reveals_the_header_only_in_writing_mode(isolated,
                                                              display):
    _sower()
    win = _open_sermons()
    try:
        win._on_top_edge_motion(None, 500, 2)
        assert win._content_tv.get_reveal_top_bars()   # never hidden anyway
        win._set_writing_mode(True)
        assert not win._content_tv.get_reveal_top_bars()
        win._on_top_edge_motion(None, 500, 2)
        assert win._content_tv.get_reveal_top_bars()
        # Hover, never a latch: pointer away from the edge, header gone.
        win._on_top_edge_motion(None, 500, 400)
        assert not win._content_tv.get_reveal_top_bars()
    finally:
        win.destroy()


def test_the_manuscript_continues_a_list_too(isolated, display):
    """The prose editor is shared, and the sermon page is where the lists
    are: points, sub-points, an order of service."""
    win = _open_sermons()
    try:
        buf = win._sermon_editor.body.get_buffer()
        buf.set_text('1. First point')
        buf.place_cursor(buf.get_end_iter())
        buf.insert_at_cursor('\n')
        assert buf.get_text(*buf.get_bounds(), False) == '1. First point\n2. '
    finally:
        win.destroy()


# ── The pulpit copy ─────────────────────────────────────────────────────────

def _menu_labels(box):
    """Every label in a built menu, in order."""
    from gi.repository import Gtk
    out = []

    def walk(widget):
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                out.append(child.get_text())
            else:
                walk(child)
            child = child.get_next_sibling()

    walk(box)
    return out


def test_the_open_sermon_can_be_printed_on_its_own(isolated, display):
    """The header's print button is the LIST. What a preacher prints is the
    one manuscript they are about to carry into the pulpit."""
    win = _open_sermons()
    try:
        win.start_sermon()
        win._sermon_editor.title.set_text('The Sower Went Forth')
        win._autosave.flush()
        labels = _menu_labels(win._build_transfer_menu())
        assert 'Print this sermon…' in labels
    finally:
        win.destroy()


def test_printing_one_sermon_prints_only_that_sermon(isolated, display):
    win = _open_sermons()
    try:
        sermons.save('s1', title='Elsewhere', body='not this one')
        row = win.start_sermon()
        win._sermon_editor.title.set_text('The Sower Went Forth')
        win._autosave.flush()
        rows = [e for e in win._entries if e.get('id') == row['id']]
        doc = win._document(markdown=False, rows=rows,
                            title=win._one_document_name(rows[0]))
        if doc is None:
            pytest.skip('no translation installed to quote from')
        assert 'Elsewhere' not in doc
        # Headed by the sermon, not by the shelf it is filed on.
        assert doc.splitlines()[0] == 'The Sower Went Forth'
    finally:
        win.destroy()


# ── The chapter door, backwards ─────────────────────────────────────────────

def test_the_chapter_door_opens_the_sermon_it_promised(isolated, display):
    sermons.save('s1', title='elsewhere', anchors=[_anchor('Genesis', 1, 1)])
    sermons.save('s2', title='here', anchors=[_anchor('Matthew', 13, 1)])
    win = _open_sermons()
    try:
        win.show_sermons_on('Matthew', 13)
        assert win._mode == 'sermons'
        assert win._current_entry is not None
        assert win._current_entry['id'] == 's2'
        assert win._selected_book_key() == 'Matthew'
    finally:
        win.destroy()


def test_the_store_answers_from_the_passage(isolated, display):
    """`sermons_on` was written for this door and had no caller at all."""
    sermons.save('s1', title='a', anchors=[_anchor('Matthew', 13),
                                           _anchor('Isaiah', 6, 8)])
    assert [s['id'] for s in sermons.sermons_on('Isaiah', 6)] == ['s1']
    assert sermons.sermons_on('Isaiah', 7) == []


# ── A series can be renamed ─────────────────────────────────────────────────

def _heading_buttons(win):
    out = []
    row = win._list.get_first_child()
    while row is not None:
        if not hasattr(row, '_entry') and getattr(row, '_series', None):
            out.append(row._series)
        row = row.get_next_sibling()
    return out


def test_a_named_series_heading_offers_a_rename(isolated, display):
    sermons.save('s1', title='a', series={'name': 'Advent 2025', 'part': 1})
    sermons.save('s2', title='b')
    win = _open_sermons()
    try:
        # The No-series heading is a caption and nothing else: there is no
        # series there to rename.
        assert _heading_buttons(win) == ['Advent 2025']
    finally:
        win.destroy()


def test_renaming_a_series_carries_every_sermon_in_it(isolated, display):
    sermons.save('s1', title='a', series={'name': 'Advent 2025', 'part': 1})
    sermons.save('s2', title='b', series={'name': 'Advent 2025', 'part': 2})
    sermons.save('s3', title='c', series={'name': 'Lent', 'part': 1})
    win = _open_sermons()
    try:
        win._rename_series('Advent 2025', 'Advent')
        assert {s['id']: s['series']['name'] for s in sermons.all_sermons()} \
            == {'s1': 'Advent', 's2': 'Advent', 's3': 'Lent'}
        assert 'Advent' in _heading_buttons(win)
    finally:
        win.destroy()


def test_renaming_into_an_existing_series_joins_the_two(isolated, display):
    """The shape of the mistake is the same series entered twice, spelled
    differently — so the rename has to double as a merge."""
    sermons.save('s1', title='a', series={'name': 'Advent 2025', 'part': 1})
    sermons.save('s2', title='b', series={'name': 'Advent', 'part': 2})
    win = _open_sermons()
    try:
        win._rename_series('Advent 2025', 'Advent')
        assert sermons.all_series() == ['Advent']
        assert _heading_buttons(win) == ['Advent']
    finally:
        win.destroy()


# ── How long it runs ────────────────────────────────────────────────────────

def _count(editor, body):
    editor.body.get_buffer().set_text(body)
    editor._restyle.flush()
    return editor._words.get_text()


def test_the_notation_is_not_counted_as_words(isolated, display):
    """A '- ' and a '1. ' are not words: on a list-heavy manuscript the raw
    split read half a minute of preaching that is not there."""
    win = _open_sermons()
    try:
        win.start_sermon()
        assert '3' in _count(win._sermon_editor, '- one\n- two\n- **three**')
    finally:
        win.destroy()


def test_a_manuscript_says_how_long_it_runs(isolated, display):
    win = _open_sermons()
    try:
        win.start_sermon()
        editor = win._sermon_editor
        label = _count(editor, ' '.join(['word'] * (editor.SPOKEN_WPM * 9)))
        assert 'min' in label and '9' in label
    finally:
        win.destroy()


def test_under_a_minute_says_nothing_about_minutes(isolated, display):
    """"≈ 0 min" under the first sentence reads as a scold."""
    win = _open_sermons()
    try:
        win.start_sermon()
        assert 'min' not in _count(win._sermon_editor, 'one two three')
    finally:
        win.destroy()


def test_a_journal_entry_is_not_timed(isolated, display):
    """An entry is read, not preached; the minutes belong to the manuscript."""
    win = _open_sermons()
    try:
        win.set_mode('journal')
        win.start_entry()
        editor = win._entry_editor
        assert 'min' not in _count(editor, ' '.join(['word'] * 600))
    finally:
        win.destroy()


# ── What you already have on this passage ───────────────────────────────────

def test_the_study_door_is_absent_with_no_passage(isolated, display):
    """A door to nowhere is worse than no door."""
    win = _open_sermons()
    try:
        win.start_sermon(anchors=[_anchor('Matthew', 13, 1)])
        assert win._sermon_editor._study_btn is not None
        # The same editor, a row with no passage: the door has to go away
        # again, and say so.
        win.start_sermon()
        assert win._sermon_editor._study_btn is None
    finally:
        win.destroy()


def test_the_study_door_appears_once_there_is_a_passage(isolated, display):
    win = _open_sermons()
    try:
        win.start_sermon(anchors=[_anchor('Matthew', 13, 1)])
        assert win._sermon_editor._study_btn.get_parent() is not None
    finally:
        win.destroy()


def test_a_mark_on_the_passage_goes_in_where_the_caret_is(isolated, display):
    """The quote the reading page pushes in and the one the sermon pulls in
    must be the same words."""
    annotations.save_note(None, 'Matthew', 13, 23, 'The soil is the hearer.')
    win = _open_sermons()
    try:
        win.start_sermon(anchors=[_anchor('Matthew', 13, 1)])
        editor = win._sermon_editor
        buf = editor.body.get_buffer()
        buf.set_text('Opening line.')
        buf.place_cursor(buf.get_end_iter())
        marks = annotations_window.marks_on('Matthew', 13)
        assert len(marks) == 1
        editor._insert_mark(marks[0])
        body = buf.get_text(*buf.get_bounds(), False)
        assert body.startswith('Opening line.\n\n')
        assert 'The soil is the hearer.' in body
        assert 'Matthew 13:23' in body
    finally:
        win.destroy()


def test_the_study_door_lists_the_marks_and_the_entries(isolated, display):
    annotations.save_note(None, 'Matthew', 13, 23, 'The soil is the hearer.')
    journal.save('j1', title='Sowing in Galilee',
                 anchors=[{'book': 'Matthew', 'chapter': 13, 'verses': []}])
    win = _open_sermons()
    try:
        win.start_sermon(anchors=[_anchor('Matthew', 13, 1)])
        labels = _menu_labels(win._sermon_editor._study_menu())
        assert any('Matthew 13:23' in t for t in labels)
        assert 'Sowing in Galilee' in labels
        assert 'Written on this passage' in labels
    finally:
        win.destroy()


def test_the_study_door_says_so_when_there_is_nothing(isolated, display):
    win = _open_sermons()
    try:
        win.start_sermon(anchors=[_anchor('Habakkuk', 2, 4)])
        labels = _menu_labels(win._sermon_editor._study_menu())
        assert 'Nothing written on this passage yet' in labels
    finally:
        win.destroy()


def test_the_study_menu_says_what_was_preached_here(isolated, display,
                                                    monkeypatch):
    """The row the journal has had all along, on the page a preacher stands
    on: you are in this passage, and you have been here before."""
    from gi.repository import Gtk
    import annotation_dialogs
    monkeypatch.setattr(annotation_dialogs.annotations, 'get_annotations',
                        lambda *a: {})
    sermons.save('s1', title='The Sower Went Forth',
                 anchors=[_anchor('Matthew', 13, 1)])

    class _Pane:
        _module, _book, _chapter = 'KJV', 'Matthew', 13
        _view = Gtk.TextView()
        _buffer = _view.get_buffer()

    popover = annotation_dialogs.build_study_menu(_Pane(), [1], 10, 10)
    labels = _menu_labels(popover.get_child())
    assert '1 sermon on this chapter' in labels
