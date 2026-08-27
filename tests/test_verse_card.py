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


def test_a_passage_past_the_type_floor_is_ellipsized_not_clipped(tmp_path):
    """Shrinking has a floor; past it the text must not simply overflow.

    Regression: _fit returned its floor-size layout whether or not it fitted.
    The layout is centred, so anything taller than the box ran off BOTH edges
    and was clipped mid-word with nothing to show it had been. A 60-verse
    selection set 1080px of type into a 1080px card; a whole Psalm 119 set
    3168px.
    """
    import cairo
    from gi.repository import Pango
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 1080, 1080))
    huge = VERSE * 120
    layout = verse_card._fit(ctx, huge, 800, 560, 67)
    assert layout.get_pixel_size().height <= 560
    # It reached the floor, so it is the ellipsis doing the work, not the size.
    assert layout.get_font_description().get_size() / Pango.SCALE == 16
    assert layout.get_ellipsize() != Pango.EllipsizeMode.NONE


def test_every_shape_survives_a_passage_past_the_floor(tmp_path):
    """The card is centred, so an overflow shows up as a negative top — check
    the composed geometry, not just the verse layout, for all three shapes."""
    import cairo
    huge = VERSE * 120
    for shape, (w, h) in SHAPES.items():
        ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, w, h))
        _margin, column = verse_card._metrics(w, h)
        verse = verse_card._fit(ctx, huge, column, h * 0.52,
                                int(min(w, h) * 0.062))
        ref_px = int(min(w, h) * 0.021)
        ref = verse_card._layout(ctx, 'Ps 119:1-176  ·  KJV',
                                 verse_card.SANS, ref_px, column)
        verse_h = verse.get_pixel_size().height
        top = int((h - (verse_h + int(h * 0.055)
                        + ref.get_pixel_size().height)) / 2)
        assert verse_h <= h * 0.52 + 1, f'{shape} overflows its box'
        assert top >= 0, f'{shape} clips at the top edge'


def test_a_very_long_card_still_writes_a_valid_png(tmp_path):
    path = _card(tmp_path, text=VERSE * 120)
    assert _png_size(path) == SHAPES['square']

# ── The serif is a chain, and Russian is why ─────────────────────────────

CYRILLIC = 'В начале Бог создал небо и землю'


def _resolved_family(text, family):
    """The family Pango actually casts `text` in — not the one we asked for.

    A family list resolves per glyph, so asking is not knowing: `Newsreader`
    carries no Cyrillic, and the interesting question is what catches the
    fall.
    """
    import gi
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 200)
    layout = PangoCairo.create_layout(cairo.Context(surface))
    desc = Pango.FontDescription()
    desc.set_family(family)
    desc.set_absolute_size(20 * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    run = layout.get_iter().get_run_readonly()
    return run.item.analysis.font.describe().get_family()


def test_the_reading_serif_is_a_family_list_ending_in_a_generic():
    """Both surfaces cast in a chain, not in one family. A bare 'Newsreader'
    sends every Cyrillic glyph to whatever fontconfig picks for an unknown
    family, which on this machine is a SANS face — so a Russian verse card
    came out in the wrong voice entirely, and so did the printed handout."""
    import passage_print
    for module in (verse_card, passage_print):
        chain = [f.strip() for f in module.SERIF.split(',')]
        assert chain[0] == 'Newsreader', module.__name__
        assert chain[-1] == 'serif', module.__name__
        assert len(chain) > 2, module.__name__


def test_cyrillic_falls_through_the_chain_to_a_serif():
    """The functional half: the fallback has to be a serif, or the chain is
    decorative. Named families in the chain count; so does anything the
    generic `serif` resolves to, since the Flatpak runtime ships none of
    Georgia, Charter or Source Serif 4."""
    import passage_print
    for module in (verse_card, passage_print):
        named = {f.strip().strip("'\"") for f in module.SERIF.split(',')}
        family = _resolved_family(CYRILLIC, module.SERIF)
        assert family in named or 'serif' in family.lower(), (
            f'{module.__name__}: Cyrillic fell to {family!r}')


def test_latin_still_reads_in_newsreader():
    """The guard on the guard: a chain that fixed Russian by giving up the
    app's own serif for English would be a regression, not a fix."""
    assert _resolved_family('In the beginning', verse_card.SERIF) == 'Newsreader'
