"""A verse as an image: type on the app's own paper, and nothing else.

The one place this app could cheapen itself, so the rules are the house law
taken literally — no photographs, no gradients, no sunsets, no script faces,
no accent colour. The card is the reading surface, framed. What makes it look
like Scriptura rather than like every other Bible app is that it is set in the
same bundled serif the app reads with, on the same paper.

Drawn with cairo and Pango rather than by snapshotting a widget. That was a
measurement, not a preference: this path needs no display server at all, so a
card renders the same on a machine with no compositor, in a test, or from a
headless build. The widget path needs a window that has actually been mapped,
and offscreen surfaces in this codebase have already proved unreliable for
dialogs and popovers. A cairo surface is also genuinely CAIRO, which sidesteps
the GPU glyph-clip the app works around elsewhere.

Rendered from DATA — the verse text and an appearance — never from the live
reading pane, so exporting a card can never disturb the scroll invariant.
"""
from __future__ import annotations

import io

import cairo
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

from i18n import N_

#: The papers a card may be cast on: the app's own light tones. A reader in
#: night mode still gets a warm card — a black square is a poor thing to send
#: someone — but the one nearest their own paper is what opens.
CARD_PAPERS: list[tuple[str, str]] = [
    (N_('Paper'), '#f7f4ee'),
    (N_('White'), '#fbfbfb'),
    (N_('Sepia'), '#f8f1e3'),
    (N_('Green'), '#dce8d0'),
]

#: Shapes offered, in the order they are offered. Wide is here by Andres's
#: call (2026-07-26) against the research doc's lean, and it is the one that
#: needed its own tuning — see `_metrics`.
SHAPES: dict[str, tuple[int, int]] = {
    'square': (1080, 1080),
    'portrait': (1080, 1350),
    'wide': (1920, 1080),
}

#: The reading serif and the label sans — the app's two voices, and the
#: clutter threshold is three.
SERIF = 'Newsreader'
SANS = 'Roboto'


def _rgb(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore


def nearest_paper(surface: str | None) -> str:
    """The card paper closest to the reader's own.

    A dark reading paper gets the default warm one rather than a nearest.
    Measured, because the obvious implementation is wrong: by plain RGB
    distance the slate #1e1e1e comes out closest to the GREEN paper, that
    being merely the darkest of the four, and a night reader would have got a
    green card for no reason they could name. There is no near neighbour to a
    dark paper in a set of light ones, and pretending otherwise picks by an
    accident of arithmetic.
    """
    if not surface:
        return CARD_PAPERS[0][1]
    try:
        want = _rgb(surface)
    except (ValueError, IndexError):
        return CARD_PAPERS[0][1]
    from pane import is_dark_paper          # lazy: pane is heavy
    if is_dark_paper(surface):
        return CARD_PAPERS[0][1]
    return min((p for _name, p in CARD_PAPERS),
               key=lambda p: sum((a - b) ** 2 for a, b in zip(_rgb(p), want)))


def _metrics(width: int, height: int) -> tuple[int, int]:
    """Margin and text-column width for a shape.

    Both keyed to the SHORTER side, so a 16:9 card does not get a margin
    proportional to its width and a text box squashed between two voids. The
    column is capped as well: a line of type running the whole width of a
    wide card is a line nobody can read back to the start of.
    """
    margin = int(min(width, height) * 0.11)
    return margin, min(width - margin * 2, int(width * 0.66)
                       if width > height else width - margin * 2)


def _layout(ctx, text, family, px, width, *, align=Pango.Alignment.CENTER,
            tracking=0):
    layout = PangoCairo.create_layout(ctx)
    desc = Pango.FontDescription()
    desc.set_family(family)
    desc.set_absolute_size(px * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_width(width * Pango.SCALE)
    layout.set_alignment(align)
    layout.set_wrap(Pango.WrapMode.WORD)
    if tracking:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(tracking) * Pango.SCALE))
        layout.set_attributes(attrs)
    layout.set_text(text, -1)
    return layout


def _fit(ctx, text, width, max_height, start, floor=16):
    """The largest size at which the verse still fits its box.

    The card is a fixed export size, so the type answers to the text rather
    than the other way round: a long passage simply sets smaller. Stepping
    down rather than solving, because Pango's wrapping is what decides the
    height and it is cheaper to ask it than to model it.

    There is a floor, and past it the type stops shrinking — 16px on a 1080px
    card is already the smallest that is worth reading. A selection long
    enough to reach the floor and still not fit is ellipsized rather than
    allowed to overflow: the layout is centred on the card, so text taller
    than the box ran off BOTH edges and was silently clipped mid-word (a
    60-verse selection set 1080px of type into a 1080px card; a whole Psalm
    119 set 3168px). An ellipsis at least says there is more.
    """
    px = start
    while px > floor:
        layout = _layout(ctx, text, SERIF, px, width)
        if layout.get_pixel_size().height <= max_height:
            return layout
        px -= 2
    layout = _layout(ctx, text, SERIF, floor, width)
    layout.set_ellipsize(Pango.EllipsizeMode.END)
    layout.set_height(int(max_height) * Pango.SCALE)
    return layout


def render(path: str, *, text: str, reference: str, translation: str,
           paper: str, ink: str, shape: str = 'square',
           wordmark: bool = False) -> str:
    """Draw the card and write it to `path` as a PNG."""
    _draw(text=text, reference=reference, translation=translation,
          paper=paper, ink=ink, shape=shape,
          wordmark=wordmark).write_to_png(path)
    return path


def render_bytes(*, text: str, reference: str, translation: str,
                 paper: str, ink: str, shape: str = 'square',
                 wordmark: bool = False) -> bytes:
    """The same card as PNG bytes, for the clipboard — no file involved.

    A card is more often pasted than filed, and going through the disk to do
    it would leave a stray PNG behind for every paste.
    """
    buffer = io.BytesIO()
    _draw(text=text, reference=reference, translation=translation,
          paper=paper, ink=ink, shape=shape,
          wordmark=wordmark).write_to_png(buffer)
    return buffer.getvalue()


def _draw(*, text: str, reference: str, translation: str,
          paper: str, ink: str, shape: str = 'square',
          wordmark: bool = False) -> cairo.ImageSurface:
    """The card itself.

    `reference` and `translation` are both shown, always: the translation is
    the attribution, and a card outlives the app it left.
    """
    width, height = SHAPES.get(shape, SHAPES['square'])
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*_rgb(paper))
    ctx.paint()

    margin, column = _metrics(width, height)
    left = (width - column) // 2
    verse = _fit(ctx, text, column, height * 0.52, int(min(width, height) * 0.062))
    ref_px = int(min(width, height) * 0.021)
    ref = _layout(ctx, f'{reference}  ·  {translation}', SANS, ref_px, column,
                  tracking=ref_px * 0.14)

    verse_h = verse.get_pixel_size().height
    gap = int(height * 0.055)
    top = int((height - (verse_h + gap + ref.get_pixel_size().height)) / 2)

    ctx.set_source_rgb(*_rgb(ink))
    ctx.move_to(left, top)
    PangoCairo.show_layout(ctx, verse)

    # Hierarchy: the verse is loudest, the citation quiet, the mark quietest.
    # Same ink throughout — less of it, never a different colour.
    ctx.save()
    ctx.set_source_rgba(*_rgb(ink), 0.55)
    ctx.move_to(left, top + verse_h + gap)
    PangoCairo.show_layout(ctx, ref)
    ctx.restore()

    if wordmark:
        mark_px = int(min(width, height) * 0.0135)
        mark = _layout(ctx, 'SCRIPTURA', SANS, mark_px, column,
                       tracking=mark_px * 0.30)
        ctx.save()
        ctx.set_source_rgba(*_rgb(ink), 0.28)
        ctx.move_to(left, height - margin - mark.get_pixel_size().height)
        PangoCairo.show_layout(ctx, mark)
        ctx.restore()

    return surface
