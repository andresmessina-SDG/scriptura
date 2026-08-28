"""The genealogy reader's widget: that it paints, and in which language.

`genealogy_layout` is pure geometry and is tested without GTK next door in
test_genealogy.py. This file covers the half that file cannot: the Cairo
drawing path, the Pango measurement the charts are laid out against, and the
hit list a click resolves through. All of it runs offscreen onto an image
surface — no display, no window.
"""
import struct

import cairo
import pytest
from gi.repository import GLib

import genealogy_bridge as gb
import genealogy_layout as gl
import genealogy_reader as gr
from i18n import _

WIDTH = 820


def _draw(chart_id):
    """One chart painted onto an image surface. Returns (area, surface)."""
    area = gr.ChartArea(chart_id)
    area._layout_width = float(WIDTH)
    area._refresh()
    height = max(1, int(area._plate.height))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, height)
    area._draw(None, cairo.Context(surface), WIDTH, height)
    return area, surface


@pytest.mark.parametrize('chart_id', [c['id'] for c in gb.charts()])
def test_every_chart_paints(chart_id):
    """A chart that raises mid-paint leaves a half-drawn widget and no error
    anywhere a reader can see. Every declared chart goes through the real
    Cairo path here, which is the only thing that exercises `_rgba`, the
    rounded-rect helper and the hatch and dash roles at all."""
    area, surface = _draw(chart_id)
    assert area._plate is not None
    assert surface.get_height() > 40, chart_id


@pytest.mark.parametrize('chart_id', [c['id'] for c in gb.charts()])
def test_paint_puts_ink_on_the_surface(chart_id):
    """The guard on the guard: a paint that silently drew nothing would pass
    the test above. Counts distinct pixel values, so a surface holding only
    the background fails."""
    _area, surface = _draw(chart_id)
    data = bytes(surface.get_data())
    assert len(set(data[i:i + 4] for i in range(0, len(data), 4))) > 4, chart_id


# ── the book ───────────────────────────────────────────────────────────────

def _book():
    """The reader, rendered. Offscreen: nothing here needs a window."""
    reader = gr.GenealogyReader()
    reader.ensure_built()
    return reader


def _drawn_charts():
    doc = gb.document()
    return [c['id'] for c in doc['charts']
            if not any(o['companion'] == c['id'] for o in doc['charts'])]


def test_the_book_has_a_title_page_and_one_page_per_chart():
    """Eight charts on one scroll made the reader do the finding. A chart is
    a figure to be looked at, and the page is the unit."""
    reader = _book()
    assert reader._pages == [''] + _drawn_charts()
    for cid in reader._pages:
        assert reader._stack.get_child_by_name(cid or gr._FRONT) is not None


def test_the_foot_turns_the_page_and_stops_at_the_ends():
    """A book does not wrap: the first page has no previous and the last has
    no next, and the arrows say so rather than doing nothing when pressed."""
    reader = _book()
    last = len(reader._pages) - 1
    assert reader._at == 0
    assert not reader._prev.get_sensitive() and reader._next.get_sensitive()
    reader.turn(1)
    assert reader._at == 1
    assert reader._prev.get_sensitive()
    reader.turn(-1)
    assert reader._at == 0
    reader.turn(-1)                      # off the front: stays put
    assert reader._at == 0
    reader._show(last)
    assert not reader._next.get_sensitive()
    reader.turn(1)
    assert reader._at == last


def test_the_foot_says_which_page_this_is():
    reader = _book()
    reader._show(0)
    assert reader._foot_title.get_label() == '', \
        'a book prints no running head on its title page'
    assert '1' in reader._foot_count.get_label()
    reader._show(1)
    assert reader._foot_title.get_label() == _(gb.chart(reader._pages[1])['title'])
    assert '2' in reader._foot_count.get_label()
    assert str(len(reader._pages)) in reader._foot_count.get_label()


def test_the_contents_lists_every_page_but_the_title_page():
    """A book's contents does not list itself, and it numbers the pages of
    the book — page 2 is the second page, not the second chart."""
    reader = _book()
    assert len(reader._toc_rows) == len(reader._pages) - 1
    reader._pick(3)
    assert reader._at == 3
    assert 'gen-toc-current' in reader._toc_rows[2].get_css_classes()
    assert 'gen-toc-current' not in reader._toc_rows[0].get_css_classes()


def test_a_name_carries_the_reader_to_the_chart_that_draws_it():
    """The cross-chart hop is the one navigation a printed plate cannot do,
    and paging must not have cost it."""
    reader = _book()
    reader.open_chart('luke')
    assert reader._pages[reader._at] == 'luke'
    assert reader._stack.get_visible_child_name() == 'luke'


def test_the_lineage_hop_works_on_a_book_nobody_has_opened_yet():
    """The marker beside a verse loads this module into the other pane and
    asks for a chart in the same breath. A reader with no pages yet has
    nothing to turn to, and the link would look dead."""
    reader = gr.GenealogyReader()          # deliberately not built
    reader.open_chart('matthew')
    assert reader._pages[reader._at] == 'matthew'


def test_a_companion_chart_opens_the_page_it_is_drawn_on():
    """Genesis 5's field of lives has no page of its own — it is drawn under
    the list it belongs to, and asking for it must not fall through."""
    reader = _book()
    reader._show(0)
    reader.open_chart('gen5_lives')
    assert reader._pages[reader._at] == 'gen5'


def test_every_page_keeps_its_own_scroll():
    """Turning away and back returns the reader to the line they left; a
    single shared adjustment would put them at the top of a chart they were
    halfway down."""
    reader = _book()
    assert len({id(sw) for sw in reader._scrolls}) == len(reader._pages)


def test_everything_the_app_calls_on_the_reader_exists():
    """A tripwire, and it exists because renaming one method broke a feature
    nothing tested.

    The lineage marker beside a Bible verse opens the other pane on the chart
    that draws those people, and window.py reaches the reader by name to do
    it. When the paged rewrite turned `scroll_to` into `open_chart` that call
    kept compiling and died at the click — which no test and no import check
    would ever have said."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    wanted = set()
    for name in ('window.py', 'pane.py', 'pane_content.py'):
        tree = ast.parse((root / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == '_genealogy'):
                wanted.add(node.attr)
    assert wanted, 'nothing was found to check — the scan stopped working'
    missing = [a for a in sorted(wanted)
               if not hasattr(gr.GenealogyReader, a)]
    assert not missing, f'the app calls {missing} on a reader that has none'


def test_pango_measures_wider_than_the_estimator_guesses_for_some_string():
    """The widget measures with Pango and the SVG plates with a per-character
    estimate, and the estimate is NOT an upper bound on Pango — measured over
    every string these charts draw it comes out narrower for almost all of
    them. This checks the two are genuinely different functions, because a
    `_measure` that quietly fell back to the estimator would make every
    offscreen check here meaningless."""
    area = gr.ChartArea('gen5')
    text = 'Mahalaleel begat Jared'
    assert area._measure(text, 15.0, 'bold') != gl.estimate(text, 15.0, 'bold')


def test_a_name_on_the_chart_is_clickable_where_it_is_drawn():
    """Hit regions are computed in the layout and consumed here, so a chart
    can look right and be dead to the pointer. Takes a person hit off the
    plate and asks the widget what is at its centre."""
    area, _surface = _draw('gen5')
    people = [h for h in area._plate.hits if h.kind == 'person']
    assert people, 'the spine drew no clickable name'
    hit = people[0]
    # Plate space to widget space, the way the paint does it: a chart
    # narrower than its pane is centred, so the two stopped coinciding.
    got = area._hit(area._ox + (hit.x + hit.w / 2) * area._scale,
                    (hit.y + hit.h / 2) * area._scale)
    assert got is not None and got.payload == hit.payload


def test_expanding_a_folded_run_makes_a_taller_chart():
    """The one piece of widget state that changes the drawing. Luke folds
    seven runs of ten; opening one has to rebuild the plate, not just repaint
    the old one."""
    area, _surface = _draw('luke')
    before = area._plate.height
    folds = [h for h in area._plate.hits if h.kind == 'expand']
    assert folds, 'Luke drew no folded run to open'
    area._expanded.add(int(folds[0].payload.split(':')[1]))
    area._refresh()
    assert area._plate.height > before


def test_the_chart_is_labelled_for_a_screen_reader():
    """The plate's `alt` is the whole chart in words, and the widget has to
    actually hand it to the accessibility tree — a drawing area exposes
    nothing on its own."""
    area, _surface = _draw('matthew')
    assert area._plate.alt.count('\n') > 10


def _png_ihdr(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    assert head[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', head[16:24])


def test_the_widget_and_the_plate_agree_on_height(tmp_path):
    """Same geometry, two backends: what the widget sets as its content
    height is what the SVG plate would be. They share `genealogy_layout`
    precisely so a printed plate and the chart on screen cannot drift."""
    import genealogy_svg as gsvg

    area, surface = _draw('ruth')
    out = tmp_path / 'ruth.png'
    surface.write_to_png(str(out))
    _w, h = _png_ihdr(str(out))
    svg = gsvg.render(gl.build('ruth', area._measure, float(WIDTH)))
    assert 'height="%d"' % round(area._plate.height) in svg
    assert abs(h - round(area._plate.height)) <= 1


def test_the_reading_size_scales_the_chart():
    """`apply_font_size` stored the size and never used it, so a pane set to
    23pt drew large prose around 13pt charts. The scale is a paint transform,
    not a font swap, so row pitch and chips grow with the type."""
    area, _surface = _draw('gen5')
    natural = area._plate.height
    area.set_reading_size(23)
    assert area._scale > 1.0
    assert area.get_content_height() > natural


def test_the_chart_never_loses_text_to_gain_size():
    """The cap that makes the scale safe. Growing the type lays the chart out
    narrower, and an uncapped scale at 23pt gave each chart 446px and cut
    sixteen captions mid-word — worse than not scaling at all."""
    area = gr.ChartArea('matthew')
    for pt in (12.5, 16, 19, 23, 28):
        area._reading_pt = pt
        for pane in (760.0, 820.0, 1040.0):
            plate = gl.build('matthew', area._measure,
                             max(pane / area._reading_scale(),
                                 area.MIN_LAYOUT_PX))
            cut = [p.text for p in plate.prims
                   if p.kind == 'text' and p.text.endswith('\u2026')
                   and ' \u00b7 ' not in p.text]
            assert not cut, f'{pt}pt in {pane}px: {cut}'


def test_a_resize_lays_the_chart_out_on_the_next_frame():
    """Not inside the allocation, which is where it used to happen.

    A chart's height is a function of its width, so laying out sets the
    content height — and doing that mid-allocation asks the parent to resize
    during the pass that is resizing it. A ScrolledWindow absorbs that request
    instead of passing it on, and with one chart to a page the page kept the
    height it had while the chart was empty: the chart was clipped to nothing.
    """
    area = gr.ChartArea('gen5')
    area._on_resize(None, 800, 0)
    assert area._plate is None, 'the chart laid itself out inside the allocation'
    assert area._pending
    ctx = GLib.MainContext.default()
    for _tick in range(64):        # never `_`: it shadows gettext
        if not ctx.pending():
            break
        ctx.iteration(False)
    assert area._plate is not None
    assert area.get_content_height() > 0


def test_a_paint_never_shows_the_previous_width_s_chart():
    """The plate is measured against the width it was CUT for.

    A resize sets the width the widget was handed a frame before the new
    plate exists, so a paint that compares itself to that number draws the
    previous step's chart inside the current step's pane — for every frame of
    a window drag. And once the paint has laid the new width out, the idle
    behind it must not build the same thing again."""
    area = gr.ChartArea('gen5')
    area._lay_out(800.0)
    stale = area._plate
    area._on_resize(None, 700, 0)
    assert area._plate is stale, 'the allocation laid out on the spot'
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 40)
    area._draw(None, cairo.Context(surface), 700, 40)
    assert area._plate is not stale, 'painted a plate cut for another width'
    assert area._laid_at == 700
    fresh = area._plate
    ctx = GLib.MainContext.default()
    for _tick in range(64):               # never `_`: it shadows gettext
        if not ctx.pending():
            break
        ctx.iteration(False)
    assert area._plate is fresh, 'the idle built the same width twice'


def test_a_chart_that_refuses_a_narrow_pane_is_painted_down():
    """The other half of the scale, and the one his narrow screenshots asked
    for. A chart's columns are fixed, so a pane too narrow for them gets the
    plate the chart needs, painted down — never a squeezed plate with the
    verse chip on top of the name."""
    area = gr.ChartArea('matthew')
    # Wide enough that the readability floor below does not bind, narrow
    # enough that the chart still refuses it.
    area._lay_out(620.0)
    assert area._plate.width > 620.0, 'the chart accepted a width it cannot draw'
    assert area._scale == pytest.approx(620.0 / area._plate.width)


def test_a_chart_stops_shrinking_before_it_stops_being_readable():
    """Painting down is right up to a point. At 420px the old scale put the
    Matthew glosses at 6.3px — past the size where shrinking is a way of
    reading the chart at all. It stops at the floor and scrolls sideways."""
    area = gr.ChartArea('matthew')
    area._lay_out(420.0)
    smallest = min(p.size for p in area._plate.prims
                   if p.kind in ('text', 'chip') and p.text.strip())
    assert smallest * area._scale >= gr.ChartArea.MIN_TYPE_PX - 0.01
    # And what will not fit asks for the room it needs, so the scroller
    # beside it can offer it rather than clipping the chart.
    assert area.get_content_width() > 420


def test_a_chart_narrower_than_its_pane_keeps_its_size():
    """Genesis 5 is a 421px plate. It used to be shrunk to 74% on a 520px
    pane it fits in twice over, because the scale was worked out from a fixed
    700px floor before anything was built."""
    area = gr.ChartArea('gen5')
    area._lay_out(520.0)
    assert area._plate.width <= 520.0
    assert area._scale == pytest.approx(1.0)
    assert area._ox > 0, 'a chart narrower than its pane is centred in it'
    assert area.get_content_height() == int(area._plate.height * area._scale)


def test_a_chart_painted_down_is_still_clickable_where_it_is_drawn():
    """The scale is undone on the way in whichever direction it went."""
    area = gr.ChartArea('matthew')
    area._lay_out(520.0)
    assert area._scale < 1.0
    hit = [h for h in area._plate.hits if h.kind == 'verse'][0]
    got = area._hit((hit.x + hit.w / 2) * area._scale,
                    (hit.y + hit.h / 2) * area._scale)
    assert got is not None and got.payload == hit.payload


def test_a_scaled_chart_is_still_clickable_where_it_is_drawn():
    """The guard on the guard: hit regions are plate-space and the pointer is
    widget-space, so a scale that is not undone moves every target away from
    the name it belongs to."""
    area, _surface = _draw('gen5')
    area.set_reading_size(23)
    s = area._scale
    assert s > 1.0
    hit = [h for h in area._plate.hits if h.kind == 'person'][0]
    got = area._hit(area._ox + (hit.x + hit.w / 2) * s,
                    (hit.y + hit.h / 2) * s)
    assert got is not None and got.payload == hit.payload


def test_measurements_are_cached_across_rebuilds():
    """A resize rebuilds every chart, and measuring is most of the cost: with
    eight charts on the page an uncached rebuild was 84ms a step, which is a
    visible hitch in a window drag."""
    area = gr.ChartArea('luke')
    area._layout_width = 800.0
    area._refresh()
    first = len(area._cache)
    assert first > 10
    area._layout_width = 801.0
    area._refresh()
    assert len(area._cache) < first * 2, 'the cache is not being reused'


def test_prose_captions_are_not_cut_mid_sentence():
    """What his screenshots found and no check did: the audit asked whether
    text stayed inside the plate, and an ellipsis always does. Thirteen of the
    Matthew chart's strings were arriving cut mid-word, in English. Name lists
    are exempt — a fold preview is meant to run out."""
    area = gr.ChartArea('gen5')
    for chart in gb.charts():
        plate = gl.build(chart['id'], area._measure, 760.0)
        cut = [p.text for p in plate.prims
               if p.kind == 'text' and p.text.endswith('\u2026')
               and ' \u00b7 ' not in p.text]
        assert not cut, f'{chart["id"]}: {cut}'


def test_a_scrolling_chart_does_not_chase_its_own_allocation():
    """The flicker his narrow pane showed, made into a check.

    A widget inside a horizontally scrolling viewport is allocated its
    CONTENT width, not the width the reader can see. Asking its own
    allocation how much room it had answered it with the room it had just
    requested, and the three states chased each other several times a
    second: allocated 420 it asked for 600, allocated 600 it asked for 700,
    allocated 700 it fitted and asked for nothing, and was squeezed back to
    420. The scrollbar could not be grabbed.
    """
    area = gr.ChartArea('matthew')
    area.set_viewport_width(420)
    first = (area._scale, area.get_content_width())
    assert first[1] > 420, 'a chart at the floor must ask for its own width'
    # Feed the allocation back the way GTK does. Nothing may move.
    for _round in range(6):
        area._on_resize(None, max(420, area.get_content_width()), 0)
        if area._pending:
            GLib.source_remove(area._pending)
            area._pending = 0
            area._refresh_idle()
        assert (area._scale, area.get_content_width()) == first


def test_the_viewport_not_the_allocation_decides_the_scale():
    """The narrow half of the same rule: what the reader can see is what the
    chart is fitted to, whatever width the widget has been handed."""
    area = gr.ChartArea('gen5')
    area.set_viewport_width(900)
    wide = area._scale
    area._lay_out(2000.0)          # an allocation far past the viewport
    assert area._scale == wide
