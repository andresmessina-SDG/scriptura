"""genealogy_svg.py — the static plate backend.

Writes a `genealogy_layout.Plate` out as a self-contained SVG. This is the
printable, shareable, exportable form of a chart, and it is the *source of
truth* the live widget is checked against: both consume the same primitives
from the same layout, so a plate and the on-screen chart cannot drift.

Following the atlas (`tools/gen_maps.py`): geometry is computed, aesthetics
are parameters. The palette lives here and nowhere else, so a role the layout
emits — `thread`, `omit`, `agree`, `band2` — is coloured in exactly one place.

**Colours are literal, and the theme is a render parameter.** The obvious
thing — CSS custom properties plus a `prefers-color-scheme` block, one file
that follows the reader — produces a plate that renders *entirely black*
under librsvg, which is the renderer this app actually has. librsvg does not
resolve `var()`. So a plate is built for a theme, the way an atlas map is
built for an era, and `render(plate, dark=True)` is the night one.

Every plate carries `<title>` and `<desc>`, and the `<desc>` is the layout's
text equivalent verbatim. A drawn tree is invisible to a screen reader without
one, and an SVG that omits it is not accessible just because it is vector.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from genealogy_layout import Plate, Prim

#: role → (light, dark). The light column is Scriptura's reading paper and the
#: two-accent law's colours; the dark column is their night forms.
#:
#:   thread  — the covenant line, in the Today page's sanctioned reading gold.
#:             It is the one thing that makes the charts read as one system.
#:   link    — "goes to the Bible", the accent's job. Verse chips only.
#:   omit    — clay, "leaves the current surface": a cross-citation, or a gap
#:             the writer left that this list cannot fill.
#:   band1-4 — the highlighter palette, verbatim from data/style.css. Those are
#:             CONTENT colours, the same standing a highlight has, so a mother
#:             band adds no third chrome accent.
PALETTE: dict[str, tuple[str, str]] = {
    'ink':          ('#221c17', '#ece4d8'),
    'ink-soft':     ('#4e453c', '#c5baa9'),
    'muted':        ('#857a6d', '#8d8175'),
    'rule':         ('#ded5c8', '#352d25'),
    'rule-soft':    ('#ebe3d7', '#272119'),
    'thread':       ('#9c7a1a', '#d0af57'),
    'thread-wash':  ('#9c7a1a', '#d0af57'),
    'omit':         ('#a9744f', '#cd9b74'),
    'link':         ('#2f6b9e', '#82b5e0'),
    'agree':        ('#7fa87c', '#8fb98c'),
    'life':         ('#7098b8', '#85abcb'),
    'hatch-life':   ('#c9b256', '#d4be62'),
    'band1':        ('#7fa87c', '#8fb98c'),
    'band2':        ('#7098b8', '#85abcb'),
    'band3':        ('#bd9765', '#cda87c'),
    'band4':        ('#c9b256', '#d4be62'),
    'chip-on':      ('#221c17', '#ece4d8'),
    'chip-off':     ('#857a6d', '#8d8175'),
    'chip-dead':    ('#ded5c8', '#352d25'),
    'paper':        ('#f7f3ec', '#16130f'),
}

_SANS = ('"Adwaita Sans","Inter",-apple-system,"Segoe UI",'
         'system-ui,sans-serif')
#: The reader's chain, written the way CSS wants it. Newsreader first so a
#: plate and the live chart set in one face; Noto Serif next because
#: Newsreader has no Cyrillic, it ships with the app, and a Russian plate
#: must fall neither to a sans nor to whichever serif the machine owns.
_SERIF = ('Newsreader,"Noto Serif","Source Serif 4",Charter,Georgia,'
          '"Times New Roman",serif')

_WEIGHTS = {'normal': '400', 'semibold': '600', 'bold': '700'}


def _style_block() -> str:
    """Font families only. Every colour is written onto its own element.

    A stylesheet here would be one more thing librsvg has to agree with; the
    font stacks are the one part it handles the same way a browser does, and
    they still need a real fallback because neither face is guaranteed."""
    return ('  <style>\n'
            '    text { font-family: %s; }\n'
            '    text.ser { font-family: %s; }\n'
            '  </style>\n' % (_SANS, _SERIF))


#: Set for the duration of one render() call. Not a parameter on every helper
#: because the primitive writers are already dense enough; guarded by the fact
#: that render() is synchronous and single-threaded.
_dark = False


def _fill(role: str) -> str:
    pair = PALETTE.get(role) or PALETTE['ink']
    return pair[1] if _dark else pair[0]


def _text(p: Prim) -> str:
    anchor = {'start': 'start', 'middle': 'middle', 'end': 'end'}[p.anchor]
    cls = ' class="ser"' if p.serif else ''
    style = ' font-style="italic"' if p.style == 'italic' else ''
    return ('  <text x="%.1f" y="%.1f" font-size="%.1f" font-weight="%s" '
            'text-anchor="%s" fill="%s"%s%s>%s</text>\n'
            % (p.x, p.y, p.size, _WEIGHTS.get(p.weight, '400'), anchor,
               _fill(p.role), style, cls, escape(p.text)))


def _prim(p: Prim) -> str:
    if p.kind == 'line':
        dash = (' stroke-dasharray="%s"' % ' '.join('%g' % d for d in p.dash)
                if p.dash else '')
        return ('  <line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="%s" stroke-width="%.1f"%s/>\n'
                % (p.x, p.y, p.x2, p.y2, _fill(p.role),
                   2.5 if p.role == 'thread' else
                   (1.4 if p.role in ('rule', 'rule-soft', 'muted') else 2.0),
                   dash))
    if p.kind == 'hatch':
        return ('  <line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="%s" stroke-width="1.6"/>\n'
                % (p.x, p.y, p.x2, p.y2, _fill(p.role)))
    if p.kind == 'poly':
        pts = ' '.join('%.1f,%.1f' % (x, y) for x, y in p.points)
        return ('  <polyline points="%s" fill="none" stroke="%s" '
                'stroke-width="1.8"/>\n' % (pts, _fill(p.role)))
    if p.kind == 'dot':
        return ('  <circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>\n'
                % (p.x, p.y, p.r, _fill(p.role)))
    if p.kind in ('rect', 'band'):
        # `thread-wash` and the hatched life bar are the two roles that paint
        # at reduced strength; everything else is solid.
        op = ''
        if p.role == 'thread-wash':
            op = ' fill-opacity="0.13"'
        elif p.role == 'life':
            op = ' fill-opacity="0.55"'
        elif p.role == 'hatch-life':
            op = ' fill="url(#g-taken)"'
        body = ('  <rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                'rx="%.1f"%s%s/>\n'
                % (p.x, p.y, p.w, p.h, p.r,
                   '' if p.role == 'hatch-life' else ' fill="%s"' % _fill(p.role),
                   op))
        return body
    if p.kind == 'chip':
        out = ''
        if p.role == 'chip-on':
            out += ('  <rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                    'rx="%.1f" fill="%s"/>\n'
                    % (p.x, p.y, p.w, p.h, p.r, _fill(p.role)))
            tcol = _fill('paper')
        else:
            out += ('  <rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                    'rx="%.1f" fill="none" stroke="%s" stroke-opacity="0.5"/>\n'
                    % (p.x, p.y, p.w, p.h, p.r, _fill(p.role)))
            tcol = _fill(p.role)
        out += ('  <text x="%.1f" y="%.1f" font-size="%.1f" font-weight="%s" '
                'text-anchor="middle" fill="%s">%s</text>\n'
                % (p.x + p.w / 2, p.y + p.h / 2 + p.size * 0.36, p.size,
                   _WEIGHTS.get(p.weight, '500'), tcol, escape(p.text)))
        return out
    if p.kind == 'text':
        return _text(p)
    return ''


def render(plate: Plate, standalone: bool = True, dark: bool = False) -> str:
    """The plate as SVG source, painted for one theme.

    `standalone` adds the XML declaration, for a file written to disk; the
    in-app path embeds the fragment and does not want it."""
    global _dark
    _dark = dark
    body = [_style_block(),
            '  <defs>\n'
            '    <pattern id="g-taken" width="6" height="6" '
            'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">\n'
            '      <line x1="0" y1="0" x2="0" y2="6" stroke="%s" '
            'stroke-width="3"/>\n'
            '    </pattern>\n'
            '  </defs>\n' % _fill('hatch-life')]
    body.append('  <rect width="100%%" height="100%%" fill="%s"/>\n'
                % _fill('paper'))
    for p in plate.prims:
        body.append(_prim(p))

    head = ('<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 %.0f %.0f" width="%.0f" height="%.0f" '
            'role="img" aria-labelledby="g-title g-desc">\n'
            '  <title id="g-title">%s</title>\n'
            '  <desc id="g-desc">%s</desc>\n'
            % (plate.width, plate.height, plate.width, plate.height,
               escape(plate.title or 'Genealogy'),
               escape(plate.alt or plate.subtitle)))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' if standalone else ''
    return xml + head + ''.join(body) + '</svg>\n'
