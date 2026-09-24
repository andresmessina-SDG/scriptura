"""The Family view and the Family Tree page: built and walked, never shown.
Skips without a display (building GTK widgets without one segfaults)."""
import types

import pytest
from gi.repository import Gdk, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import bible_family as bf
import family_tree as ft
import family_view as fv


def _view():
    opened = []
    view = fv.FamilyView(opened.append)
    view.refresh(['KJVA', 'ESV'], 'KJVA')
    return view, opened


def test_every_family_bible_is_a_node_with_a_sentence():
    view, _opened = _view()
    assert len(view._nodes) == 37
    s = fv._sentence(bf.node('esv'), False, 'ESV')
    assert s.startswith('English Standard Version, 2001')
    assert 'Revision of Revised Standard Version.' in s
    assert s.endswith('Installed.')
    tlb = fv._sentence(bf.node('tlb'), False, None)
    assert 'Reworded from American Standard Version.' in tlb
    root = fv._sentence(bf.node('tyndale'), False, None)
    assert 'Before the Line' in root


def test_the_bible_being_read_is_marked():
    view, _opened = _view()
    assert [k for k, n in view._nodes.items() if n.reading] == ['kjv']


def test_arrow_keys_walk_the_family():
    view, _opened = _view()
    grabbed = []
    for n in view._nodes.values():
        n.grab_focus = (lambda n=n: grabbed.append(n.record['id']))
    view.scroll_to_visible = lambda node: None
    assert view._walk(view._nodes['esv'], Gdk.KEY_Up)
    assert grabbed[-1] == 'rsv'
    view._walk(view._nodes['rsv'], Gdk.KEY_Down)
    assert grabbed[-1] == bf.node('esv')['id'] or grabbed[-1] == 'nrsv'
    view._walk(view._nodes['kjv'], Gdk.KEY_Right)
    assert view._pos[grabbed[-1]][0] > view._pos['kjv'][0]
    assert not view._walk(view._nodes['kjv'], Gdk.KEY_a)


def test_lighting_a_bible_lights_its_whole_line():
    view, _opened = _view()
    view._light('esv')
    assert {'esv', 'rsv', 'asv', 'rv', 'kjv', 'tyndale'} <= view._lit
    assert view._nodes['nlt'].has_css_class('dim')
    assert not view._nodes['rsv'].has_css_class('dim')
    view._light(None)
    assert not view._nodes['nlt'].has_css_class('dim')


def test_a_click_opens_the_card_and_remembers_the_node():
    view, opened = _view()
    view._nodes['nrsv'].emit('clicked')
    assert opened == ['nrsv'] and view._last is view._nodes['nrsv']


@pytest.mark.parametrize('arrangement', ['family', 'line'])
def test_no_label_runs_into_another_or_a_bar(arrangement):
    """Every node's box (mark, name, year) measured in the real font, and
    placed as the view places it: none may overlap another, nor (by
    literalness) a range bar under another Bible. The first runs found
    'KJV 1769' in the Challoner node, HCSB in TNIV, and the RNJB's bracket
    through NASB 2020."""
    view = fv.FamilyView(lambda i: None, arrangement)
    items = [(nid, node.box()) for nid, node in view._nodes.items()]
    clashes = [(a, b) for i, (a, ba) in enumerate(items)
               for b, bb in items[i + 1:] if fv._overlap(ba, bb)]
    if arrangement == 'line':
        bars = [(nid, fv._bar(n)) for nid, n in view._nodes.items()
                if fv._bar(n) is not None]
        clashes += [(a, 'bar of ' + b) for a, ba in items for b, bar in bars
                    if a != b and fv._overlap(ba, bar)]
    assert clashes == []


def test_switching_arrangement_moves_every_bible_and_back():
    import family_layout as fl
    view, _opened = _view()
    view.set_arrangement('line', animate=False)
    assert view.arrangement == 'line'
    line = fl.positions('line')
    assert all(abs(n.x - line[k][0]) < 0.01 for k, n in view._nodes.items())
    assert view._nodes['nabre'].x == fl.NOT_PLACED_X
    assert view._nodes['tyndale'].x == fl.positions()['tyndale'][0]  # root
    view.set_arrangement('family', animate=False)
    fam = fl.positions()
    assert all(abs(n.x - fam[k][0]) < 0.01 for k, n in view._nodes.items())


def test_the_arrangement_is_remembered(monkeypatch):
    page, store = _page(monkeypatch)
    page._by_line.set_active(True)
    assert store['family_tree_arrangement'] == 'line'
    assert page.family.arrangement == 'line'
    page._list_btn.set_active(True)
    assert not page._arrangements.get_visible()


def test_the_outline_holds_every_bible_once_in_family_order():
    outline = fv.FamilyOutline(lambda i: None)
    rows = []
    child = outline._list.get_first_child()
    while child is not None:
        rows.append(child.record['id'])
        child = child.get_next_sibling()
    assert sorted(rows) == sorted(bf.family_members())
    # a parent comes before its children
    assert rows.index('rsv') < rows.index('esv') < rows.index('nrsv') or \
        rows.index('rsv') < rows.index('nrsv')
    assert rows.index('asv') < rows.index('tlb')


def _page(monkeypatch, view='family', outline=False):
    import settings
    store = {'family_tree_view': view, 'family_tree_outline': outline}
    monkeypatch.setattr(settings, 'get', lambda k: store.get(k))
    monkeypatch.setattr(settings, 'put', lambda k, v: store.__setitem__(k, v))
    pane = types.SimpleNamespace(_names=['KJVA'], _came_from='KJVA',
                                 get_root=lambda: None)
    return ft.FamilyTree(pane), store


def test_the_page_opens_on_the_family_and_remembers_the_line(monkeypatch):
    page, store = _page(monkeypatch)
    assert page._stack.get_visible_child_name() == 'family'
    page._line_btn.set_active(True)
    assert page._stack.get_visible_child_name() == 'line'
    assert store['family_tree_view'] == 'line'
    assert not page._list_btn.get_visible()
    page._family_btn.set_active(True)
    assert page._stack.get_visible_child_name() == 'family'
    page._list_btn.set_active(True)
    assert page._stack.get_visible_child_name() == 'outline'
    assert store['family_tree_outline'] is True


def test_the_page_opens_where_it_was_left(monkeypatch):
    page, _store = _page(monkeypatch, view='line')
    assert page._stack.get_visible_child_name() == 'line'
    assert page.family is None          # the drawing waits until it is asked


def test_the_outline_files_a_bible_under_the_parent_the_card_names():
    """Matthew's Bible and the NIV 2011 have two parents; the outline must
    pick the one the Card, the sentence and the Up key pick."""
    outline = fv.FamilyOutline(lambda i: None)
    for nid in ('matthew', 'niv2011'):
        assert outline._parent[nid] == bf.descent(nid)[1][0]['id'], nid


def test_the_margin_notes_are_text_a_screen_reader_reaches_in_order():
    view, _opened = _view()
    notes = []
    child = view._fixed.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label) and child.has_css_class('family-note'):
            notes.append(child.get_label())
        child = child.get_next_sibling()
    assert len(notes) == 6 and notes[0].startswith('1611')
    tops = [top for _y, top in view._note_spots]
    assert tops == sorted(tops)
    # none starts above its own year, and none runs into the next
    for (year_y, top) in view._note_spots:
        assert top >= year_y - 9


def test_the_page_is_no_wider_than_what_it_shows(monkeypatch):
    """The hidden outline once set the whole pane's minimum at 509px."""
    page, _store = _page(monkeypatch)
    page._ensure_family()
    minimum = page.widget.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
    assert minimum < 380, minimum
    outline_min = page.outline.widget.measure(Gtk.Orientation.HORIZONTAL,
                                              -1)[0]
    assert outline_min < 300, outline_min


def test_the_1611_kjv_is_spoken_as_it_is_drawn():
    """Drawn with the 1769 text's mark, so it is said to be placed as it."""
    s = fv._sentence(bf.node('kjv1611'), False, None)
    assert 'Placed as King James Version (1769 Blayney text):' in s
    assert 'It has no place on the Line.' not in s


def test_a_second_switch_mid_slide_starts_where_the_bibles_are(monkeypatch):
    """Finishing the running slide puts the Bibles at its end; the new
    slide must start there, not from the mid-slide spot it found."""
    import family_layout as fl
    view, _opened = _view()
    line_end = fl.positions('line')

    class Running:
        def skip(self):
            view._pos = dict(line_end)      # what finishing it does
            view._animation = None
    view._arrangement = 'line'
    view._pos = {k: (1.0, 2.0) for k in view._pos}     # mid-slide
    view._animation = Running()
    seen = []
    real = fl.positions
    monkeypatch.setattr(fv.fl, 'positions',
                        lambda arr='family': seen.append(dict(view._pos))
                        or real(arr))
    view.set_arrangement('family', animate=False)
    assert seen[0] == line_end
