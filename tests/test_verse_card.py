"""The verse card: what it is cast on, and that it draws at all.

No display anywhere in this file — that is the point of the cairo path, and
these tests are the proof of it.
"""
import struct

import verse_card
from verse_card import CARD_PAPERS, SHAPES, nearest_paper, render

VERSE = ('For God so loved the world, that he gave his only begotten Son, '
         'that whosoever believeth in him should not perish, but have '
         'everlasting life.')
LONG = VERSE * 6


def _png_size(path):
    """Width and height straight out of the IHDR, so the assertion is about
    the file rather than about what we asked for."""
    with open(path, 'rb') as f:
        head = f.read(24)
    assert head[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', head[16:24])


def _card(tmp_path, **kwargs):
    args = dict(text=VERSE, reference='John 3:16', translation='KJV',
                paper='#f7f4ee', ink='#1c1a17')
    args.update(kwargs)
    path = str(tmp_path / 'card.png')
    return render(path, **args)


# ── The paper ────────────────────────────────────────────────────────────────

def test_a_dark_reading_paper_gets_the_warm_default_not_a_nearest():
    """Measured, because the obvious implementation is wrong: by RGB distance
    the slate is closest to the GREEN paper, that being merely the darkest of
    four light ones, and a night reader would have got a green card for no
    reason they could name."""
    assert nearest_paper('#1e1e1e') == CARD_PAPERS[0][1]
    assert nearest_paper('#000000') == CARD_PAPERS[0][1]


def test_a_light_reading_paper_keeps_its_own():
    for _name, value in CARD_PAPERS:
        assert nearest_paper(value) == value


def test_an_unreadable_colour_falls_back_rather_than_raising():
    assert nearest_paper(None) == CARD_PAPERS[0][1]
    assert nearest_paper('') == CARD_PAPERS[0][1]
    assert nearest_paper('not-a-colour') == CARD_PAPERS[0][1]


# ── The drawing ──────────────────────────────────────────────────────────────

def test_every_shape_writes_a_png_of_that_shape(tmp_path):
    for shape, (width, height) in SHAPES.items():
        assert _png_size(_card(tmp_path, shape=shape)) == (width, height)


def test_an_unknown_shape_falls_back_to_square(tmp_path):
    assert _png_size(_card(tmp_path, shape='hexagon')) == SHAPES['square']


def test_a_long_passage_sets_smaller_rather_than_overflowing(tmp_path):
    """The card is a fixed export size, so the type answers to the text."""
    import cairo
    from gi.repository import Pango
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 1080, 1080)
    ctx = cairo.Context(surface)
    short = verse_card._fit(ctx, VERSE, 800, 560, 67)
    long_ = verse_card._fit(ctx, LONG, 800, 560, 67)
    assert long_.get_pixel_size().height <= 560
    short_px = short.get_font_description().get_size() / Pango.SCALE
    long_px = long_.get_font_description().get_size() / Pango.SCALE
    assert long_px < short_px


def test_a_wide_card_caps_its_measure(tmp_path):
    """A line running the full width of a 1920px card is one nobody can read
    back to the start of."""
    margin, column = verse_card._metrics(1920, 1080)
    assert column < 1920 - margin * 2
    # A square is not capped that way — its own margins govern.
    margin_sq, column_sq = verse_card._metrics(1080, 1080)
    assert column_sq == 1080 - margin_sq * 2


def test_the_renderer_touches_no_widget_toolkit(tmp_path):
    """The whole point of the cairo path: no GTK, no widget, no display, so a
    card renders the same in a test, on a headless build, and in the app. A
    Gtk import creeping in here would take that away silently."""
    import inspect
    source = inspect.getsource(verse_card)
    assert 'Gtk' not in source
    assert 'gi.repository' in source          # Pango only
    assert _png_size(_card(tmp_path, wordmark=True)) == SHAPES['square']


def test_the_clipboard_card_is_the_same_png_without_the_disk(tmp_path):
    """A card is more often pasted than filed, and going through a file to do
    it would leave a stray PNG behind for every paste."""
    from verse_card import render_bytes
    data = render_bytes(text=VERSE, reference='John 3:16', translation='KJV',
                        paper='#f7f4ee', ink='#1c1a17', shape='portrait')
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', data[16:24]) == SHAPES['portrait']
    # Byte-identical to what the file path writes: one drawing, two exits.
    assert data == open(_card(tmp_path, shape='portrait'), 'rb').read()
