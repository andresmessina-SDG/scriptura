"""Book-wide search and printed notes, including legacy SWORD note bodies."""
from types import SimpleNamespace

import book_notes
import book_search
import sword_bridge


def test_search_finds_phrases_case_and_multiple_sections(monkeypatch):
    monkeypatch.setattr(sword_bridge, 'list_genbook_entries', lambda m: [
        ('/One', 'One', 0), ('/Two', 'Two', 0), ('/Three', 'Three', 0)])
    bodies = {'/One': '<p>Grace &amp; peace. Grace &amp; peace.</p>',
              '/Two': '<p>grace &amp; peace.</p>', '/Three': '<p>A different text.</p>'}
    monkeypatch.setattr(sword_bridge, 'load_genbook_entry', lambda m,p: bodies[p])
    task = SimpleNamespace(is_current=lambda: True)
    hits, sections, total = book_search.search_book('Book', 'grace & peace', False, task)
    assert [h[0] for h in hits] == ['/One', '/Two']
    assert (sections, total) == (2, 3)
    assert book_search.search_book('Book', 'Grace & peace', True, task)[2] == 2


def test_search_limit_preserves_total_and_cancellation_stops_loading(monkeypatch):
    monkeypatch.setattr(sword_bridge, 'list_genbook_entries', lambda m: [
        ('/One','One',0), ('/Two','Two',0)])
    loaded = []
    monkeypatch.setattr(sword_bridge, 'load_genbook_entry',
                        lambda m,p: loaded.append(p) or '<p>mercy</p>')
    hits, sections, total = book_search.search_book('Book','mercy',False,
                                                  SimpleNamespace(is_current=lambda: True),limit=1)
    assert len(hits) == 1 and sections == total == 2
    loaded.clear()
    assert book_search.search_book('Book','mercy',False,
                                   SimpleNamespace(is_current=lambda: False)) == ([],0,0)
    assert loaded == []


def test_search_does_not_join_paragraphs_or_count_inline_note_markers():
    assert book_search.plain_text('<p>holy<hi type="super" n="note">12</hi> Spirit</p>'
                                 '<p>and grace.</p>') == 'holy Spirit and grace.'


def test_classic_endnotes_keep_their_bodies_and_printed_markers():
    raw = ('<p>A word<hi type="super" n="note">3</hi>.</p>'
           '<div type="x-notes"><title>Notes</title>'
           '<p><hi type="super">3</hi> An <hi type="italic">editorial</hi> note.</p></div>')
    rendered, notes = book_notes.prepare_notes(raw)
    assert rendered == raw
    assert notes == {'3': 'An <hi type="italic">editorial</hi> note.'}


def test_legacy_inline_notes_get_markers_and_remain_as_endnotes():
    raw = '<p>Grace<note swordFootnote="1">A source note.</note> and peace.</p>'
    rendered, notes = book_notes.prepare_notes(raw)
    assert '<hi type="super" n="note">1</hi> and peace.' in rendered
    assert rendered.count('A source note.') == 1
    assert notes == {'1': 'A source note.'}


def test_legacy_printed_note_numbers_survive():
    raw = '<p>Text<note n="15" swordFootnote="1">A note.</note></p>'
    rendered, notes = book_notes.prepare_notes(raw)
    assert '<hi type="super" n="note">15</hi>' in rendered
    assert notes == {'15': 'A note.'}


def test_phrase_search_ignores_markers_but_maps_back_to_the_original_text():
    from pane_search import _book_text_offsets
    raw = 'Holy\x00\x00 Spirit\n\n and grace'
    normalized, offsets = _book_text_offsets(raw)
    assert normalized == 'Holy Spirit and grace'
    start = normalized.index('Spirit')
    end = start + len('Spirit and')
    assert raw[offsets[start]:offsets[end-1]+1] == 'Spirit\n\n and'


def test_empty_or_editorial_notes_do_not_swallow_surrounding_prose():
    raw = ('<p>A<note swordFootnote="1"/> whole sentence '
           '<note>A real note.</note> to<note n="unto">Auto-modernized</note> read.</p>')
    rendered, notes = book_notes.prepare_notes(raw)
    assert 'whole sentence' in rendered and ' read.' in rendered
    assert 'Auto-modernized' not in rendered
    assert notes == {'1': 'A real note.'}


def test_sword_attribute_notes_are_read_before_loading_another_entry(monkeypatch):
    mod = SimpleNamespace(setKeyText=lambda p: None,
                          renderText=lambda: '<p>Text<note swordFootnote="1"></note>.</p>')
    monkeypatch.setattr(sword_bridge, 'mgr', lambda: SimpleNamespace(getModule=lambda n: mod))
    monkeypatch.setattr(sword_bridge, '_collect_footnotes', lambda m: [('1','explanation','The note body.')])
    raw = sword_bridge.load_genbook_entry('Book','/Chapter')
    assert '<note swordFootnote="1">The note body.</note>' in raw


def _find_bar():
    import pytest
    from gi.repository import Gtk, Gdk
    from pane_search import PaneSearch
    if Gdk.Display.get_default() is None:
        pytest.skip('builds book search widgets; no display here')
    buf = Gtk.TextBuffer()
    pane = SimpleNamespace(_buffer=buf, view=Gtk.TextView(buffer=buf),
                           _is_genbook=True, module='TestBook')
    search = PaneSearch(pane)
    search.build_button()
    search.build_revealer()
    return search, buf


def test_a_phrase_with_a_note_marker_highlights_its_original_buffer_range():
    search, buf = _find_bar()
    buf.set_text('Holy12 Spirit\n\nand grace.')
    marker = buf.create_tag('fn_marker')
    buf.apply_tag(marker, buf.get_iter_at_offset(4), buf.get_iter_at_offset(6))
    search._live_highlight('Holy Spirit and')
    assert len(search.results) == 1
    start, end = search.results[0]
    assert buf.get_text(buf.get_iter_at_offset(start),buf.get_iter_at_offset(end),True) \
        == 'Holy12 Spirit\n\nand'


def test_more_results_keeps_later_sections_accessible():
    search, buf = _find_bar()
    search._book_hits = [(f'/Section {i}',f'Section {i}',1,'A matching phrase.')
                         for i in range(205)]
    search._book_total = 205
    search._append_book_results()
    assert search._book_drawn == 200
    assert search._book_more_row is not None
    search._on_book_row(search._book_list,search._book_more_row)
    assert search._book_drawn == 205
    assert search._book_more_row is None


def test_f3_can_find_a_book_result_with_the_find_bar_hidden():
    search, buf = _find_bar()
    buf.set_text('Mercy and more mercy.')
    search._entry = SimpleNamespace(get_text=lambda: 'mercy')
    search._rev = SimpleNamespace(get_reveal_child=lambda: False)
    search._book_jump = ('mercy', False, False)
    stepped = []
    search.step = lambda prev=False: stepped.append(prev) or True
    assert search.on_book_render()
    assert len(search.results) == 2
    assert stepped == [False]
