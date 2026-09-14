"""The Today page's ground: parchment, written in the margins.

What the page stood on before this was laid paper — the wire marks of a
paper mould, the substrate of a PRINTED Bible and nothing older. The page
now carries an abecedary, which is a scribe's object, and every manuscript
that carries the Hebrew Bible or the Greek New Testament is written on skin.
So the ground is skin: a slow cloudiness where the hide took the scraper
unevenly and the faint stipple of the hair follicles, with no straight line
anywhere in it.

The field itself is the twenty-two letters in order, line after line, with
every fourth line in Greek — the way a scribe practised, and the way
Psalm 119, Lamentations and Proverbs 31 are built. Because the letters run
in ORDER they never spell anything: a reader of Hebrew finds a familiar
object rather than gibberish, and nothing can land on the Name by accident.

Two older hands surface inside it. Every eleventh Hebrew letter is set in
Paleo-Hebrew, the hand of Siloam and Lachish, and about one glyph in a
hundred in Imperial Aramaic, the chancellery hand behind the letters quoted
in Ezra. Neither script is in any font we ship, so both are drawn as paths.
That mix carries the canon's own proportion, measured off our own KJV
versification: 23,145 Old Testament verses, 7,957 New, and 269 of the Old
in Aramaic — Hebrew 73.6%, Greek 25.6%, Aramaic 0.86%.

The field keeps to the margins and the type column stands on clean skin,
which is how a codex leaf is built: a written block inside a ruled margin.
"""
import math
import random

import cairo
import gi

gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, GLib, Pango, PangoCairo  # noqa: E402

# The two bundled faces. Hebrew needs a face with real mark positioning and
# Noto Serif is fully polytonic; both ship in data/fonts, so the field can
# be set as text rather than traced. Mirrors pane.py's stacks.
_HEBREW_FONT = "Noto Serif Hebrew, SBL Hebrew, Ezra SIL, serif"
_GREEK_FONT = "Noto Serif, DejaVu Serif, Source Serif 4, serif"

# The twenty-two letters. U+05D0-05EA is twenty-SEVEN codepoints: the block
# interleaves the five final forms (kaf, mem, nun, pe and tsadi sofit), which
# are positional variants and not letters of the alphabet. A scribe writing
# out the alphabet writes twenty-two, and so does this.
_FINALS = '\u05da\u05dd\u05df\u05e3\u05e5'
_ALEF = [chr(c) for c in range(0x05d0, 0x05eb) if chr(c) not in _FINALS]
# Greek in the lower case. Half the capitals (Α Β Ε Ζ Η Ι Κ Μ Ν Ο Ρ Τ Υ Χ)
# are Latin homographs, and with no word around them a Β simply reads as a
# B — measured off a render, where a plain Latin "B" sat in the field.
_ALPHA = [chr(c) for c in range(0x03b1, 0x03ca) if c != 0x03c2]

_SIZE = 17.0        # the letters' own size
_LEAD = 44.0        # the line rhythm
_TRACK = 1.62       # advance, as a multiple of the size
_GREEK_EVERY = 4    # every fourth line is Greek

# The measure the type column asks for, the distance over which the field
# fades out as it approaches that column, and the narrowest band of
# full-strength field worth drawing at all.
_COLUMN = 790.0
_FADE = 110.0
_MIN_BAND = 26.0

# The field's weight, in CIE L* against the paper it is drawn on. A flat
# alpha does not hold across the appearance themes: compositing is linear in
# light and the eye is not, so the field that reads correctly at 0.030 on a
# dark paper lands at 2.15 on a light one and all but disappears. See
# `alpha_for`.
WEIGHT_FIELD = 3.4
WEIGHT_GROUND = 2.1

# How far down the cloud is drawn before being scaled back up.
_CLOUD_DIVISOR = 8


# ── how much ink this paper needs ─────────────────────────────────────────
def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _lstar(y: float) -> float:
    return 116 * (y ** (1 / 3)) - 16 if y > 0.008856 else 903.3 * y


def alpha_for(paper: tuple[float, float, float],
              ink: tuple[float, float, float],
              weight: float = WEIGHT_FIELD, cap: float = 0.16) -> float:
    """The alpha at which `ink` over `paper` sits `weight` L* off the paper.

    Bisection, not a formula: L* has no closed-form inverse through an alpha
    composite. Sixty halvings, run once per cached texture, cost nothing —
    and solving it means sepia, the dark papers, pure black and the Night
    Light dusk all come out at one perceived weight without a table of
    per-theme constants to keep in step.
    """
    base = _lstar(_luminance(paper))
    lo, hi = 0.0, cap
    for _i in range(60):
        mid = (lo + hi) / 2
        mixed = (paper[0] * (1 - mid) + ink[0] * mid,
                 paper[1] * (1 - mid) + ink[1] * mid,
                 paper[2] * (1 - mid) + ink[2] * mid)
        if abs(_lstar(_luminance(mixed)) - base) < weight:
            lo = mid
        else:
            hi = mid
    return lo


# ── the older hands, drawn ────────────────────────────────────────────────
# Paleo-Hebrew: the Iron-Age hand of the monarchy. Its letters are pictures
# — an eye, a house, water, a shepherd's crook, an ox's head, a tooth.
def _pal_ayin(cr, x, y, s):
    cr.arc(x, y, 3.4 * s, 0, 2 * math.pi)
    cr.stroke()


def _pal_taw(cr, x, y, s):
    cr.move_to(x - 3.2 * s, y - 3.2 * s)
    cr.line_to(x + 3.2 * s, y + 3.2 * s)
    cr.move_to(x + 3.2 * s, y - 3.2 * s)
    cr.line_to(x - 3.2 * s, y + 3.2 * s)
    cr.stroke()


def _pal_mem(cr, x, y, s):
    cr.move_to(x - 4 * s, y - 3 * s)
    for i, dx in enumerate((-2, 0, 2, 4)):
        cr.line_to(x + dx * s, y + (3 if i % 2 == 0 else -3) * s)
    cr.stroke()


def _pal_lamed(cr, x, y, s):
    cr.move_to(x + 1.4 * s, y - 4.4 * s)
    cr.line_to(x - 0.6 * s, y + 2.2 * s)
    cr.curve_to(x - 1.2 * s, y + 4.4 * s, x - 3.4 * s, y + 4.6 * s,
                x - 3.8 * s, y + 2.6 * s)
    cr.stroke()


def _pal_aleph(cr, x, y, s):
    cr.move_to(x - 4.2 * s, y - 3.4 * s)
    cr.line_to(x + 1.0 * s, y - 0.6 * s)
    cr.move_to(x - 4.2 * s, y + 1.0 * s)
    cr.line_to(x + 1.0 * s, y - 0.6 * s)
    cr.move_to(x - 1.4 * s, y - 2.0 * s)
    cr.line_to(x + 3.0 * s, y + 4.0 * s)
    cr.stroke()


def _pal_shin(cr, x, y, s):
    cr.move_to(x - 3.6 * s, y - 3.0 * s)
    cr.line_to(x - 1.8 * s, y + 3.0 * s)
    cr.line_to(x, y - 3.0 * s)
    cr.line_to(x + 1.8 * s, y + 3.0 * s)
    cr.line_to(x + 3.6 * s, y - 3.0 * s)
    cr.stroke()


def _pal_bet(cr, x, y, s):
    cr.move_to(x + 2.6 * s, y - 3.4 * s)
    cr.line_to(x - 2.0 * s, y - 3.4 * s)
    cr.curve_to(x - 3.6 * s, y - 3.4 * s, x - 3.6 * s, y - 0.2 * s,
                x - 2.0 * s, y - 0.2 * s)
    cr.line_to(x + 1.2 * s, y - 0.2 * s)
    cr.line_to(x - 3.0 * s, y + 3.8 * s)
    cr.stroke()


def _pal_qof(cr, x, y, s):
    cr.arc(x, y - 1.4 * s, 2.2 * s, 0, 2 * math.pi)
    cr.move_to(x, y + 0.8 * s)
    cr.line_to(x, y + 4.4 * s)
    cr.stroke()


_PALEO = [_pal_ayin, _pal_taw, _pal_mem, _pal_lamed,
          _pal_aleph, _pal_shin, _pal_bet, _pal_qof]


# Imperial Aramaic: the Persian chancellery hand, already cursive, already
# leaning — the hand behind the documents Ezra quotes.
def _ar_aleph(cr, x, y, s):
    cr.move_to(x + 3.2 * s, y - 4.0 * s)
    cr.curve_to(x - 1.6 * s, y - 2.4 * s, x - 3.2 * s, y + 0.8 * s,
                x - 1.6 * s, y + 4.0 * s)
    cr.move_to(x + 0.6 * s, y - 3.2 * s)
    cr.line_to(x + 3.4 * s, y + 4.0 * s)
    cr.stroke()


def _ar_dalet(cr, x, y, s):
    cr.move_to(x - 3.0 * s, y - 3.2 * s)
    cr.curve_to(x + 2.0 * s, y - 3.6 * s, x + 2.6 * s, y - 0.6 * s,
                x - 0.4 * s, y + 0.6 * s)
    cr.line_to(x - 1.2 * s, y + 4.2 * s)
    cr.stroke()


_ARAM = [_ar_aleph, _ar_dalet]


# ── the ground ────────────────────────────────────────────────────────────
def draw_parchment(cr, w: float, h: float,
                   ink: tuple[float, float, float], alpha: float) -> None:
    """Skin, not paper: a slow cloudiness and the grain of the hair side.

    Deterministic, from a fixed seed — the same sheet every redraw. A random
    one would reshuffle the moment anything repainted the page.
    """
    r, g, b = ink
    rng = random.Random(1611)
    # The cloud. Few, large and weak, half lighter and half darker in strict
    # alternation so the sheet settles rather than stains: at 90 blobs of a
    # quarter the page's width it came out blotched, which reads as dirt.
    #
    # Drawn at an eighth and scaled up. A radial gradient over the whole
    # window costs ~12ms in cairo and there are forty-four of them here —
    # 286ms measured at 1366x733, which is a visible hitch even once. The
    # cloud has nothing in it above an eighth of the page's frequency, so
    # nothing is lost and the same sheet costs a fortieth of the time.
    sw, sh = max(2, int(w / _CLOUD_DIVISOR)), max(2, int(h / _CLOUD_DIVISOR))
    cloud = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
    cc = cairo.Context(cloud)
    for i in range(44):
        cx = rng.uniform(-0.2, 1.2) * sw
        cy = rng.uniform(-0.2, 1.2) * sh
        rad = (0.30 + 0.34 * rng.random()) * max(sw, sh)
        sign = 1.0 if i % 2 == 0 else -1.0
        grad = cairo.RadialGradient(cx, cy, 0, cx, cy, rad)
        grad.add_color_stop_rgba(0.0, r, g, b, alpha * sign)
        grad.add_color_stop_rgba(1.0, r, g, b, 0.0)
        cc.set_source(grad)
        cc.rectangle(0, 0, sw, sh)
        cc.fill()
    cloud.flush()
    cr.save()
    cr.scale(w / sw, h / sh)
    cr.set_source_surface(cloud, 0, 0)
    cr.get_source().set_filter(cairo.Filter.BILINEAR)
    cr.paint()
    cr.restore()
    # The follicles, in loose drifts rather than an even scatter. These are
    # single pixels and must be struck at full size.
    for _i in range(200):
        cx, cy = rng.random() * w, rng.random() * h
        for _j in range(rng.randrange(3, 9)):
            x = cx + rng.gauss(0, 15)
            y = cy + rng.gauss(0, 10)
            cr.set_source_rgba(r, g, b, alpha * 0.85 * rng.random())
            cr.arc(x, y, 0.5 + 0.45 * rng.random(), 0, 2 * math.pi)
            cr.fill()


def _margin_band(w: float) -> tuple[float, float]:
    """The margin's full-strength band and its fade, for a page `w` wide.

    The fade never eats more than half the margin, so a narrowing window
    loses the field gradually instead of at a step; and below a band of
    `_MIN_BAND` there is not enough margin left to write in, so the page
    stands on bare skin rather than on two cramped strips of letters. At
    1366 the band is 178px, at 1100 it is 70, and it closes at about 906.
    """
    edge = (w - _COLUMN) / 2
    if edge <= 0:
        return 0.0, 0.0
    fade = min(_FADE, edge * 0.55)
    band = edge - fade
    return (band, fade) if band >= _MIN_BAND else (0.0, 0.0)


def _margin_weight(x: float, w: float, band: float, fade: float) -> float:
    """How much of the field stands at `x`: full in the margin, nothing over
    the column, and a soft fade between, so the type never sits on letters."""
    if band <= 0:
        return 0.0
    dist = min(x, w - x)          # distance in from the nearer edge
    if dist <= band:
        return 1.0
    if dist >= band + fade:
        return 0.0
    return (band + fade - dist) / fade


def draw_abecedary(cr, w: float, h: float,
                   ink: tuple[float, float, float], alpha: float) -> None:
    """The alphabet in order, line after line, kept to the margins."""
    r, g, b = ink
    band, fade = _margin_band(w)
    if band <= 0:
        return
    rng = random.Random(119)
    layout = PangoCairo.create_layout(cr)
    heb, grk = Pango.FontDescription(), Pango.FontDescription()
    for desc, family in ((heb, _HEBREW_FONT), (grk, _GREEK_FONT)):
        desc.set_family(family)
        desc.set_absolute_size(_SIZE * Pango.SCALE)
    adv = _SIZE * _TRACK
    y, row, n = _LEAD / 2, 0, 0
    while y < h + _LEAD:
        greek = row % _GREEK_EVERY == _GREEK_EVERY - 1
        seq = _ALPHA if greek else _ALEF
        desc = grk if greek else heb
        # Each line starts a little further along than the last, so the
        # rows do not stack into columns.
        x = -((row * 0.41 * adv) % adv)
        i = 0
        while x < w + adv:
            n += 1
            weight = _margin_weight(x, w, band, fade)
            if weight <= 0.0:
                x += adv
                i += 1
                continue
            a = alpha * weight * (0.82 if greek else 1.0)
            if n % 97 == 0:
                cr.set_source_rgba(r, g, b, a * 0.92)
                cr.set_line_width(0.9)
                rng.choice(_ARAM)(cr, x, y, _SIZE / 9)
            elif not greek and n % 11 == 0:
                cr.set_source_rgba(r, g, b, a * 0.80)
                cr.set_line_width(0.9)
                _PALEO[i % len(_PALEO)](cr, x, y, _SIZE / 9)
            else:
                layout.set_font_description(desc)
                layout.set_text(seq[i % len(seq)], -1)
                gw, gh = layout.get_pixel_size()
                cr.set_source_rgba(r, g, b, a)
                cr.move_to(x - gw / 2, y - gh / 2)
                PangoCairo.show_layout(cr, layout)
            x += adv
            i += 1
        y += _LEAD
        row += 1


# ── the cached sheet ──────────────────────────────────────────────────────
# The page repaints on every frame of an animation — the menu sliding in
# while the page slides away — and this sheet costs far more than a frame to
# draw. It is struck once per (size, paper, ink) and then blitted, so a
# repaint is one texture and the drawing never runs during an animation.
_cache: dict[tuple, Gdk.Texture] = {}


def sheet(width: int, height: int, paper: tuple[float, float, float],
          ink: tuple[float, float, float]) -> 'Gdk.Texture | None':
    """The whole ground as one texture, cached."""
    if width <= 0 or height <= 0:
        return None
    key = (width, height,
           tuple(round(c, 4) for c in paper), tuple(round(c, 4) for c in ink))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    draw_parchment(cr, width, height, ink,
                   alpha_for(paper, ink, WEIGHT_GROUND) * 0.58)
    draw_abecedary(cr, width, height, ink, alpha_for(paper, ink))
    surface.flush()
    # Straight from the cairo buffer: a GdkPixbuf round trip would copy the
    # sheet twice and unpremultiply it on the way through for nothing.
    texture = Gdk.MemoryTexture.new(
        width, height, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
        GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride())
    # One sheet in hand and one on the way out: a window being resized would
    # otherwise grow the cache without bound.
    if len(_cache) > 3:
        _cache.clear()
    _cache[key] = texture
    return texture


def forget() -> None:
    """Drop every cached sheet — the ink or the paper has changed."""
    _cache.clear()
