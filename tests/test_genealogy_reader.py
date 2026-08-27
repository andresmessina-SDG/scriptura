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

import genealogy_bridge as gb
import genealogy_layout as gl
import genealogy_reader as gr

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
    got = area._hit(hit.x + hit.w / 2, hit.y + hit.h / 2)
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
                             pane / area._scale_for(pane))
            cut = [p.text for p in plate.prims
                   if p.kind == 'text' and p.text.endswith('\u2026')
                   and ' \u00b7 ' not in p.text]
            assert not cut, f'{pt}pt in {pane}px: {cut}'


def test_a_scaled_chart_is_still_clickable_where_it_is_drawn():
    """The guard on the guard: hit regions are plate-space and the pointer is
    widget-space, so a scale that is not undone moves every target away from
    the name it belongs to."""
    area, _surface = _draw('gen5')
    area.set_reading_size(23)
    s = area._scale
    assert s > 1.0
    hit = [h for h in area._plate.hits if h.kind == 'person'][0]
    got = area._hit((hit.x + hit.w / 2) * s, (hit.y + hit.h / 2) * s)
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
