"""The Family view and the Family Tree page: built and walked, never shown.
Skips without a display (building GTK widgets without one segfaults)."""
import types

import pytest
from gi.repository import Gdk, GLib, Gtk

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


def _page(monkeypatch, view='family', outline=False, notes=True):
    import settings
    store = {'family_tree_view': view, 'family_tree_outline': outline,
             'family_tree_notes': notes}
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


@pytest.mark.parametrize('lit', [None, {'esv', 'rsv'}])
def test_the_drawing_paints_every_line_whether_or_not_one_is_lit(lit):
    """A renamed local once turned `lit` into a bool after the first line,
    and the next line of descent raised: the drawing stopped partway."""
    import cairo
    view, _opened = _view()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1180, 1833)
    view._paint(cairo.Context(surf), 1180, 1833, fv._PLATE_INK,
                fv.PLATE_BASE, lit)


def test_the_poster_paints_in_black_on_one_page_whatever_the_theme():
    import cairo
    view, _opened = _view()
    for arrangement in ('family', 'line'):
        view.set_arrangement(arrangement, animate=False)
        w, h = 842, 1191                    # A3, points
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        fv.paint_plate(view, cr, w, h)
        surf.flush()
        data, stride = surf.get_data(), surf.get_stride()
        # the title band has dark ink in it; nothing is drawn light-on-dark
        dark = sum(1 for y in range(10, 40) for x in range(20, 300)
                   if data[y * stride + x * 4] < 90)
        assert dark > 200, arrangement


def test_the_print_job_is_one_page(monkeypatch):
    page, _store = _page(monkeypatch)
    page._ensure_family()
    op = page.build_print()
    assert op.get_n_pages_to_print() in (-1, 1)   # set before the dialog
    assert page._print_btn.get_visible()
    page._list_btn.set_active(True)
    assert not page._print_btn.get_visible()


def test_a_mark_starts_its_own_path():
    """On the poster a mark followed a label on one surface; an arc begun
    from the label's point drew a line from the text to the mark."""
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 40)
    cr = cairo.Context(surf)
    cr.move_to(5, 5)                    # where a label left the pen
    fv._paint_mark(cr, 150, 20, None, fv._PLATE_INK)
    surf.flush()
    data, stride = surf.get_data(), surf.get_stride()
    stray = sum(1 for x in range(20, 120) for y in range(0, 40)
                if data[y * stride + x * 4 + 3])
    assert stray == 0


def test_the_print_job_itself_writes_the_poster(monkeypatch, tmp_path):
    """The whole job, not just the painter: GTK runs it to a PDF file with
    no dialog, through the same draw-page wiring the Print button uses."""
    page, _store = _page(monkeypatch)
    page._ensure_family()
    op = page.build_print()
    out = tmp_path / 'family.pdf'
    op.set_export_filename(str(out))
    result = op.run(Gtk.PrintOperationAction.EXPORT, None)
    assert result == Gtk.PrintOperationResult.APPLY
    data = out.read_bytes()
    assert data.startswith(b'%PDF') and len(data) > 10000


def test_printing_mid_slide_finishes_the_slide_first(monkeypatch):
    page, _store = _page(monkeypatch)
    page._ensure_family()
    skipped = []

    class Running:
        def skip(self):
            skipped.append(True)
            page.family._animation = None
    page.family._animation = Running()
    monkeypatch.setattr(page, 'build_print', lambda: types.SimpleNamespace(
        run=lambda *_a: None))
    page.print_poster()
    assert skipped == [True]


def test_show_node_turns_to_the_family_and_keeps_the_bible(monkeypatch):
    """The Card's Show in the Family: from the Line, the page turns to the
    Family; the drawing or the list, whichever the reader chose, holds the
    Bible so the keyboard lands on it."""
    page, store = _page(monkeypatch, view='line')
    page.show_node('rsv')
    assert page._stack.get_visible_child_name() == 'family'
    assert store['family_tree_view'] == 'family'
    assert page.family._last is page.family._nodes['rsv']

    page, _store = _page(monkeypatch, view='line', outline=True)
    page.show_node('rsv')
    assert page._stack.get_visible_child_name() == 'outline'
    assert page.outline._last.record['id'] == 'rsv'


def test_a_scroll_before_layout_waits_for_the_page():
    """A pane just turned to the Family has no page yet: a scroll then was
    clamped to the top, and the Bible asked for sat below the fold."""
    import family_layout as fl
    view, _opened = _view()
    node, done = view._nodes['rsv'], []
    view.scroll_to(node, lambda: done.append(True))
    assert done == []
    view._scroll.get_vadjustment().configure(0, 0, fl.HEIGHT, 1, 10, 600)
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)
    assert done == [True]
    assert view._scroll.get_vadjustment().get_value() == node.y - 200


def _ink_total(view, hc):
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1180, 1833)
    view._paint(cairo.Context(surf), 1180, 1833, fv._PLATE_INK,
                fv.PLATE_BASE, None, hc=hc)
    surf.flush()
    return sum(surf.get_data()[3::4])


def test_high_contrast_lifts_the_drawing():
    view, _opened = _view()
    # Mostly text by area, which rises only from 0.6 to 0.7.
    assert _ink_total(view, True) > _ink_total(view, False) * 1.05


def test_the_poster_ignores_high_contrast(monkeypatch):
    """The poster is black on white paper whatever the desktop asks."""
    import cairo
    view, _opened = _view()

    def plate():
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 842, 1191)
        fv.paint_plate(view, cairo.Context(surf), 842, 1191)
        surf.flush()
        return bytes(surf.get_data())

    plain = plate()
    monkeypatch.setattr(fv, 'high_contrast', lambda: True)
    assert plate() == plain


# ── The margin notes can be put away ────────────────────────────────────────

def _notes_shown(view):
    return [lbl.get_visible() for lbl in view._note_labels]


def test_the_margin_notes_can_be_put_away_and_it_is_remembered(monkeypatch):
    page, store = _page(monkeypatch)
    assert page._notes_btn.get_visible()
    assert _notes_shown(page.family) == [True] * 6
    page._notes_btn.set_active(False)
    assert store['family_tree_notes'] is False
    assert _notes_shown(page.family) == [False] * 6
    # Opened again, the Family comes back as it was left.
    again, _store = _page(monkeypatch, notes=False)
    assert _notes_shown(again.family) == [False] * 6
    # The notes belong to the drawing: no switch for them on the Line.
    page._line_btn.set_active(True)
    assert not page._notes_btn.get_visible()


def test_the_poster_leaves_out_the_notes_the_screen_leaves_out():
    import cairo

    def ink(view):
        w, h = 842, 1191
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        fv.paint_plate(view, cr, w, h)
        surf.flush()
        data = bytes(surf.get_data())
        return sum(1 for i in range(0, len(data), 4) if data[i] < 160)

    view, _opened = _view()
    with_notes = ink(view)
    view.set_notes_visible(False)
    assert ink(view) < with_notes


# ── 2026-09-25: lanes, unplaced lines, bars ──────────────────────────────

def _real_measure():
    import cairo
    from gi.repository import Pango, PangoCairo
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))
    layout = PangoCairo.create_layout(cr)
    PangoCairo.context_set_resolution(layout.get_context(), 96)
    base = 11 * Pango.SCALE
    return lambda t, size: fv._measure(layout, t, base, size)


def test_lane_names_sit_in_one_row_and_never_touch():
    """Staggered over two rows the names read as one tangle, and in
    capitals JERUSALEM (60px) outran its 59px lane into HOLMAN · CSB."""
    import family_layout as fl
    measure = _real_measure()
    size, labels = fv.lane_labels(fl.lanes(), measure)
    widths = [(lane.x, max(measure(line, size) for line in lines))
              for lane, lines in labels]
    for (xa, wa), (xb, wb) in zip(widths, widths[1:]):
        assert xa + wa / 2 + 4 <= xb - wb / 2, (xa, xb)
    assert max(len(lines) for _l, lines in labels) <= 2


def test_a_dot_stays_with_the_word_before_it():
    wide = lambda t: len(t) * 7
    assert fv._wrap_words('Douay · NAB', 53, wide) == ['Douay ·', 'NAB']
    assert fv._wrap_words('NIV', 53, wide) == ['NIV']


def test_every_lane_name_cuts_the_lines_behind_it():
    import cairo
    import family_layout as fl
    from gi.repository import Gdk
    view = fv.FamilyView(lambda i: None, 'family')
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50))
    view._paint(cr, fl.WIDTH, fl.HEIGHT, Gdk.RGBA(red=0, green=0, blue=0,
                                                  alpha=1), 11 * 1024, None)
    for lane in fl.lanes():
        assert any(x <= lane.x <= x + w for x, _y, w, _h in view._knockouts)


def test_lines_to_the_unplaced_are_faint_by_literalness_only():
    view = fv.FamilyView(lambda i: None, 'line')
    assert view._unplaced('nabre') and view._unplaced('nrsvue')
    assert not view._unplaced('esv') and not view._unplaced('tyndale')
    view.set_arrangement('family', animate=False)
    assert not view._unplaced('nabre')


def test_a_range_of_one_chart_draws_no_bar():
    """NASB 1995's range is one chart's 0.23: as a bar, a speck under its
    name; as a tick, hidden behind its own line. Its mark says it."""
    view = fv.FamilyView(lambda i: None, 'line')
    assert fv._bar(view._nodes['nasb1995']) is None
    assert fv._bar(view._nodes['nkjv']) is not None
