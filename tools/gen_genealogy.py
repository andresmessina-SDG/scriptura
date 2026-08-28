#!/usr/bin/env python3
"""Build the static genealogy plates, and audit the table they come from.

Follows the atlas (`tools/gen_maps.py`): geometry is computed, aesthetics are
parameters, and the build FAILS on the things a chart must never quietly get
wrong. A clean run prints zero `!` lines.

The guarantees, and why each exists:

  * **Every edge cites a verse, and the verse parses.** An uncited edge is an
    assertion, and the whole design rests on a reader being able to check any
    line against the text in front of them.
  * **Every edge's ends are people the table knows.** A typo'd id silently
    drops a generation out of a chart; the first run of this check found ten
    people who had surface names but no records.
  * **Every telescoped edge names who does list the missing names.** "Three
    generations omitted" with no cross-citation tells a reader something is
    missing and gives them no way to look.
  * **Every declared chart draws.** A chart whose chain cannot be walked
    renders as an empty box in the app with no error anywhere.
  * **No chart's text runs off its own plate.** Measured, not eyeballed.

    ./tools/gen_genealogy.py --check          # audit only
    ./tools/gen_genealogy.py --out plates/    # audit, then write SVGs
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import genealogy_bridge as gb        # noqa: E402
import genealogy_layout as gl        # noqa: E402
import genealogy_svg as gsvg         # noqa: E402

def _linguas() -> list[str]:
    """The shipped languages, read off po/LINGUAS rather than restated here.

    A language added to LINGUAS and not to this list would be a language
    whose plates nobody audits, which is exactly the failure this file is
    supposed to make impossible."""
    path = os.path.join(ROOT, 'po', 'LINGUAS')
    with open(path, encoding='utf-8') as f:
        return [ln.strip() for ln in f
                if ln.strip() and not ln.startswith('#')]


LANGUAGES = _linguas()

_warnings: list[str] = []


def warn(msg: str) -> None:
    _warnings.append(msg)
    print('! ' + msg)


def audit() -> None:
    doc = gb.document()
    people = doc['people']

    for e in doc['edges']:
        ref = e['ref']
        where = '%s %d:%d' % (ref['book'], ref['chapter'], ref['verse'])
        for end in ('parent', 'child'):
            if e[end] not in people:
                warn('edge at %s names unknown person %r' % (where, e[end]))
        if e['mother'] and e['mother'] not in people:
            warn('edge at %s names unknown mother %r' % (where, e['mother']))
        if e['kind'] == 'descends':
            if not e['omits']:
                warn('telescoped edge at %s does not say how many it omits'
                     % where)
            if not e['cross']:
                warn('telescoped edge at %s omits %d generations and cites '
                     'nobody who names them' % (where, e['omits']))
            elif gb.parse_ref(e['cross']) is None:
                warn('telescoped edge at %s has an unparsable cross-citation '
                     '%r' % (where, e['cross']))

    # A person on no chart is not an error. Ahaziah, Joash, Amaziah and
    # Jehoiakim are exactly the men Matthew leaves out, and the table holds
    # them so a reader who double-clicks one gets told who DOES name him; Ham
    # and Japheth are Noah's other sons, cited but off the drawn line.
    # Reported as a count so a curator can watch it, never as a failure.
    drawn: set[str] = set()
    for c in doc['charts']:
        drawn |= gb.chart_people(c['id'])
    undrawn = sorted(pid for pid in people if pid not in drawn)
    if undrawn:
        print('  %d people are looked up but not drawn: %s'
              % (len(undrawn), ', '.join(undrawn[:8])
                 + ('…' if len(undrawn) > 8 else '')))

    for c in doc['charts']:
        if not gb.chart_people(c['id']):
            warn('chart %r draws nobody — its chain could not be walked'
                 % c['id'])
        if c['companion'] and gb.chart(c['companion']) is None:
            warn('chart %r names companion %r, which does not exist'
                 % (c['id'], c['companion']))
        if c['structure'] == 'witnesses':
            for side in ('left', 'right'):
                if gb.chart(c[side]) is None:
                    warn('witness chart %r names %s side %r, which does not '
                         'exist' % (c['id'], side, c[side]))

    for r in doc['readings']:
        if gb.chart(r['chart']) is None:
            warn('reading %r is attached to unknown chart %r'
                 % (r['title'][:40], r['chart']))
        if not r['attribution']:
            warn('reading %r carries no attribution' % r['title'][:40])


def _kjv() -> "object | None":
    """A reader for the KJV with Apocrypha, if this machine has one.

    Optional on purpose: the audit still runs without it and says so. When it
    is there, every citation in the table gets read against the text it cites,
    which is the only check that can tell a right reference from a plausible
    one.
    """
    import shutil
    if shutil.which('diatheke') is None:
        return None
    probe = subprocess.run(['diatheke', '-b', 'KJVA', '-k', 'Genesis 5:3'],
                           capture_output=True, text=True)
    if probe.returncode or 'Seth' not in probe.stdout:
        return None

    cache: dict[str, str] = {}

    def verse(ref: str) -> str:
        if ref not in cache:
            m = re.match(r'^(.+?) (\d+):(\d+)', ref)
            if m is None:
                cache[ref] = ''
            else:
                out = subprocess.run(
                    ['diatheke', '-b', 'KJVA', '-o', '', '-k',
                     '%s %s:%s' % m.groups()],
                    capture_output=True, text=True).stdout
                cache[ref] = ' '.join(
                    re.sub(r'<[^>]*>', '', out).replace('(KJVA)', '').split())
        return cache[ref]

    return verse


def audit_citations() -> None:
    """Every edge must be named by the verse it cites.

    The rule the table follows, and the reason only one end is required: an
    edge cites **the verse where the newer name first appears**. Genesis and
    Chronicles run forwards, so that is the child's verse and the parent was
    named earlier ("Lamech begat a son" in 5:28, "he called his name Noah" in
    5:29 — the edge cites 5:29). Luke runs backwards, so it is the parent's
    verse and the child closed the verse before. Requiring both ends would
    fail 21 correct citations; requiring neither would let a typo through, and
    a wrong reference under a true statement is the failure this whole table
    is built to prevent.
    """
    verse = _kjv()
    if verse is None:
        print('  no KJVA via diatheke — citations parsed, not read')
        return

    doc = gb.document()
    people = doc['people']

    def named(pid: str, text: str) -> bool:
        p = people.get(pid)
        if p is None:
            return False
        low = text.lower()
        return any(re.search(r'(?<![a-z])' + re.escape(f.lower()) + r'(?![a-z])',
                             low)
                   for f in [p['name']] + list(p['also']))

    checked = 0
    for e in doc['edges']:
        ref = e['ref']
        where = '%s %d:%d' % (ref['book'], ref['chapter'], ref['verse'])
        text = verse(where)
        if not text:
            warn('citation %s could not be read from the KJV' % where)
            continue
        checked += 1
        if not (named(e['parent'], text) or named(e['child'], text)):
            warn('%s names neither %s nor %s' % (where, e['parent'], e['child']))
        if e['mother'] and not named(e['mother'], text):
            warn('%s does not name %s, who is hung on it' % (where, e['mother']))

    # A lifespan is a number read off a verse; if the person is not in it, the
    # number came from somewhere else.
    for ls in doc['lifespans']:
        for key in ('ref', 'death_ref'):
            r = ls.get(key)
            if not r:
                continue
            where = '%s %d:%d' % (r['book'], r['chapter'], r['verse'])
            text = verse(where)
            checked += 1
            if text and not named(ls['person'], text):
                warn('%s is cited for %s, who is not named in it'
                     % (where, ls['person']))
    print('  %d citations read against the KJV' % checked)


def pango_measure() -> gl.Measure | None:
    """A real text measurement, if this machine has a font engine.

    The layout's `gl.estimate` is not an upper bound on Pango — it comes out
    narrower for nearly every string on these charts — so auditing with it and
    calling the result safe would be a guarantee nobody had checked. PangoCairo
    needs no display and no window, only an image surface, so the audit can
    measure the way the widget does. `None` when the bindings are missing, and
    the audit says so rather than quietly dropping to the estimate.
    """
    try:
        import gi
        gi.require_version('Pango', '1.0')
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import Pango, PangoCairo
        import cairo
        # Imported here, not at the top: this is the one thing in the tool
        # that needs GTK on the machine, and an audit should still run on one
        # without it. Everything the charts are computed from is GTK-free.
        from genealogy_reader import SERIF
    except (ImportError, ValueError):
        return None

    # Everything is measured in the serif, including the rows the widget
    # sets in sans: `gl.Measure` takes no face, so one has to stand for both,
    # and the serif is the wider of the two — which errs towards reporting an
    # overflow that is not there rather than missing one that is.
    layout = PangoCairo.create_layout(cairo.Context(
        cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)))
    weights = {'bold': Pango.Weight.BOLD, 'semibold': Pango.Weight.SEMIBOLD}
    cache: dict[tuple[str, float, str], float] = {}

    def measure(text: str, size: float, weight: str = 'normal') -> float:
        key = (text, size, weight)
        got = cache.get(key)
        if got is None:
            desc = Pango.FontDescription.from_string('%s %.1f' % (SERIF, size))
            desc.set_weight(weights.get(weight, Pango.Weight.NORMAL))
            layout.set_font_description(desc)
            layout.set_text(text, -1)
            got = cache[key] = float(layout.get_pixel_size().width)
        return got

    return measure


def pango_ink() -> "object | None":
    """The box a string actually inks, not the box its line box claims.

    The overlap check needs this and the width alone will not do it: a line
    box carries the font's leading above and below the glyphs, and two wrapped
    lines of a caption 17px apart have line boxes that touch while nothing a
    reader can see does. Ink extents are what is on the paper.
    """
    try:
        import gi
        gi.require_version('Pango', '1.0')
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import Pango, PangoCairo
        import cairo
        from genealogy_reader import SERIF, _SANS
    except (ImportError, ValueError):
        return None

    layout = PangoCairo.create_layout(cairo.Context(
        cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)))
    weights = {'bold': Pango.Weight.BOLD, 'semibold': Pango.Weight.SEMIBOLD}
    cache: dict[tuple, tuple[float, float, float, float]] = {}

    def ink(p: gl.Prim) -> tuple[float, float, float, float]:
        key = (p.text, p.size, p.weight, p.style, p.serif)
        got = cache.get(key)
        if got is None:
            desc = Pango.FontDescription.from_string(
                '%s %.1f' % (SERIF if p.serif else _SANS, p.size))
            desc.set_weight(weights.get(p.weight, Pango.Weight.NORMAL))
            if p.style == 'italic':
                desc.set_style(Pango.Style.ITALIC)
            layout.set_font_description(desc)
            layout.set_text(p.text, -1)
            box, _log = layout.get_pixel_extents()
            got = cache[key] = (float(box.x), float(box.y), float(box.width),
                                float(box.height),
                                float(layout.get_pixel_size().width))
        ox, oy, w, h, line_w = got
        # The widget draws a layout with its TOP at `y - size`, and anchors it
        # by the line width, not the ink width.
        x = (p.x if p.anchor == 'start' else
             p.x - line_w / 2 if p.anchor == 'middle' else p.x - line_w)
        return (x + ox, p.y - p.size + oy, w, h)

    return ink


#: The widths the reader can hand a chart. Its floor is `MIN_LAYOUT_PX`; below
#: that it lays out at the floor and paints the plate down, and above it the
#: pane and the reading size decide. Charts are checked across the range
#: because every defect his screenshots found lived at one end of it.
COLLISION_WIDTHS = (700.0, 760.0, 820.0, 900.0, 1040.0)


def audit_collisions(lang: str, ink, measure: gl.Measure) -> None:
    """Nothing a plate draws may be drawn on top of anything else.

    The check that was missing, and the one his narrow screenshots made
    obvious: the plate audit asked only whether text stayed inside the plate,
    which a verse chip sitting squarely on top of a name does. These figures
    have a fixed set of columns and narrowing them reflows nothing, so a
    translated name — or an English one at 700px, six pixels from touching —
    ran straight into the chip beside it.

    Two boxes that share space are reported unless they are consecutive lines
    of a wrapped caption, where a descender may pass an ascender and no reader
    sees a collision. A chip is never exempt: it is a filled shape, and
    anything under it is gone.

    Rules count too, and for three weeks they did not. This compared text
    against text and text against chips, so the one thing it could not see
    was a line drawn through a word — which is exactly what shipped: the two
    column rails on the side-by-side chart were struck through `Jechonias`,
    `Neri`, `Mary`, `Joseph` and «Иехония» in every language and both themes.
    A rule is thin, so only a line that crosses a glyph box by more than a
    third of its height is reported — and only a rule painted AFTER the text
    it crosses, because that is what a strike-through is. The lifespan
    chart's axis gridlines cross three of its labels and are drawn before
    them, so the text is on top and nothing is struck; the two column rails
    were appended last, which is precisely how they came to be drawn through
    every name on their column.
    """
    for width in COLLISION_WIDTHS:
        for c in gb.charts():
            plate = gl.build(c['id'], measure, width)
            boxes = []
            for n, p in enumerate(plate.prims):
                if p.kind == 'text' and p.text.strip():
                    boxes.append((ink(p), 'text', p.text[:34], n))
                elif p.kind == 'chip':
                    boxes.append(((p.x, p.y, p.w, p.h), 'chip', p.text[:34], n))
                elif p.kind == 'line' and abs(p.x2 - p.x) < 0.5:
                    boxes.append(((p.x - 0.7, min(p.y, p.y2), 1.4,
                                   abs(p.y2 - p.y)), 'rule', p.role, n))
            for i, (a, ka, ta, na) in enumerate(boxes):
                for b, kb, tb, nb in boxes[i + 1:]:
                    ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                    oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                    if ox <= 0.5 or oy <= 0.5:
                        continue
                    if 'rule' in (ka, kb):
                        # A vertical rule against a word: what matters is how
                        # much of the word's height it crosses, not the sliver
                        # of the rule it happens to be — and whether the rule
                        # is painted over the word or under it.
                        other, on_top = ((a, nb > na) if kb == 'rule'
                                         else (b, na > nb))
                        if ka == kb or not on_top or oy / other[3] <= 0.34:
                            continue
                    elif ('chip' not in (ka, kb)
                            and oy / min(a[3], b[3]) <= 0.25):
                        continue
                    warn('[%s] chart %r at %.0fpx: %r is drawn over %r '
                         '(%.0fpx)' % (lang, c['id'], width, ta, tb, oy))


def audit_names(lang: str, measure: gl.Measure) -> None:
    """No preview of a collapsed run may end inside a name.

    These charts exist to say who was called what, so a name trimmed to
    `Naasso…` is worse than no name: a reader cannot tell it from a
    misspelling, and two thirds of the previews on the Matthew, Luke and
    side-by-side charts ended that way, in all three languages and at every
    width. The ellipsis stands where a name would be, not inside one.
    """
    for width in COLLISION_WIDTHS:
        for c in gb.charts():
            plate = gl.build(c['id'], measure, width)
            for p in plate.prims:
                if (p.kind != 'text' or not p.text.endswith('…')
                        or gl.NAME_SEP not in p.text):
                    continue
                if not p.text.endswith(gl.NAME_SEP + '…'):
                    warn('[%s] chart %r at %.0fpx: a name is cut in half — '
                         '%r' % (lang, c['id'], width, p.text[-30:]))


def audit_plates(width: float, lang: str = 'en',
                 measure: gl.Measure | None = None) -> None:
    """Nothing a plate draws may fall outside it.

    Measured with Pango where it is available, which is what the widget
    actually casts in; `gl.estimate` only when this machine has no font
    engine, and it under-measures, so a clean run then proves less.

    Run once per shipped language. English fits by accident — every name and
    every note on these plates is translated, and Spanish and Russian are
    both longer than the English in places ("Mahalaleel" is one row, "born
    of" is two words, "родил" is one). A plate audited only in English is
    audited in the one language whose widths nobody chose."""
    measure = measure or gl.estimate
    for c in gb.charts():
        plate = gl.build(c['id'], measure, width)
        if plate.height <= 0:
            warn('[%s] chart %r produced an empty plate' % (lang, c['id']))
            continue
        if not plate.alt:
            warn('[%s] chart %r has no text equivalent — it would be '
                 'invisible to a screen reader' % (lang, c['id']))
        for p in plate.prims:
            if p.kind == 'text':
                w = measure(p.text, p.size, p.weight)
                x0 = (p.x if p.anchor == 'start' else
                      p.x - w / 2 if p.anchor == 'middle' else p.x - w)
                if x0 < -1 or x0 + w > plate.width + 1:
                    warn('[%s] chart %r: %r runs from %.0f to %.0f on a '
                         '%.0f-wide plate' % (lang, c['id'], p.text[:36], x0,
                                              x0 + w, plate.width))
            elif p.kind in ('rect', 'band', 'chip'):
                if p.x < -1 or p.x + p.w > plate.width + 1:
                    warn('[%s] chart %r: a %s runs from %.0f to %.0f on a '
                         '%.0f-wide plate' % (lang, c['id'], p.kind, p.x,
                                              p.x + p.w, plate.width))
            if p.y > plate.height + 1 or p.y2 > plate.height + 1:
                warn('[%s] chart %r: a %s sits below the plate (%.0f > %.0f)'
                     % (lang, c['id'], p.kind, max(p.y, p.y2), plate.height))


def _locale_tree() -> str | None:
    """Compile po/*.po into a throwaway tree and point i18n at it.

    `i18n.localedir()` resolves next to the installed package, so a run from
    a source checkout sees English and nothing else — which would make the
    per-language plate audit below silently pass by measuring English three
    times. Compiling here keeps the audit honest without a meson install.
    """
    import shutil
    import subprocess
    import tempfile

    if shutil.which('msgfmt') is None:
        print('  msgfmt not installed — auditing English only')
        return None

    po_dir = os.path.join(ROOT, 'po')
    base = tempfile.mkdtemp(prefix='genealogy-locale-')
    built = False
    for code in LANGUAGES:
        po = os.path.join(po_dir, code + '.po')
        if not os.path.isfile(po):
            continue
        out = os.path.join(base, code, 'LC_MESSAGES')
        os.makedirs(out, exist_ok=True)
        r = subprocess.run(['msgfmt', '-o',
                            os.path.join(out, 'scriptura.mo'), po],
                           capture_output=True, text=True)
        if r.returncode:
            warn('po/%s.po does not compile: %s' % (code, r.stderr.strip()))
        else:
            built = True
    if not built:
        return None

    import i18n
    i18n._localedir_cache = base
    return base


def _as_msgids(texts: set[str]) -> set[str]:
    """The English source of each trimmed string, dropping what has none.

    Comparing the trimmed strings themselves would compare Russian words with
    English ones and call every one of them a new failure. It would also
    accuse the sample lists — "Isaac · Jacob · Judah…" is composed at run time
    out of person names and is *meant* to run out — of a translation bug. Only
    strings that came from the catalogue can be compared across languages, so
    only those are reported.
    """
    import i18n

    cat = getattr(i18n._catalogue(), '_catalog', None) or {}
    if not cat:                       # English: the string IS the msgid
        return set(texts)
    back = {v: k for k, v in cat.items() if isinstance(k, str) and v}
    return {back[t] for t in texts if t in back}


def audit_every_language(width: float) -> None:
    """The plate audit, run in each language the app ships.

    [[i18n-width-traps]]: a translated string in a container sized to the
    English fits English and overflows everything else. These plates measure
    their text rather than assuming it, so this is a check that the measuring
    is actually right — and it is the only check that would catch a Russian
    note running off the edge of a chart nobody looked at in Russian.
    """
    import i18n

    tree = _locale_tree()
    measure = pango_measure()
    ink = pango_ink()
    if measure is None:
        print('  no PangoCairo — measuring with the layout estimate, which '
              'under-measures; treat a clean run as provisional')
    codes = ['en'] + (LANGUAGES if tree else [])
    done: list[str] = []
    trimmed: dict[str, set[str]] = {}
    before = os.environ.get('LANGUAGE')
    try:
        for code in codes:
            if code == 'en':
                os.environ.pop('LANGUAGE', None)
            else:
                os.environ['LANGUAGE'] = code
            i18n._catalogue()          # re-resolve for the new env
            if code != 'en' and i18n.current_language() != code:
                warn('%s did not load — its plates were not audited' % code)
                continue
            gl._trimmed.clear()
            audit_plates(width, code, measure)
            trimmed[code] = _as_msgids(gl._trimmed)
            audit_names(code, measure or gl.estimate)
            if ink is not None:
                audit_collisions(code, ink, measure or gl.estimate)
            done.append(code)
    finally:
        if before is None:
            os.environ.pop('LANGUAGE', None)
        else:
            os.environ['LANGUAGE'] = before
        i18n._catalogue()
    print('  plates audited in: %s (%s)%s'
          % (', '.join(done),
             'Pango' if measure else 'estimate',
             '' if ink is not None else '; no overlap check without PangoCairo'))

    # A sentence cut mid-word is the defect a reader actually sees, and until
    # his screenshots nothing here looked for it: the audit only asked whether
    # text stayed inside the plate, and an ellipsis always does. Thirteen of
    # the Matthew chart's fifty-two strings were arriving as "The line breaks
    # its own grammar at her: Jesus is bor…" — in English. Name lists are
    # exempt: "Isaac \u00b7 Jacob \u00b7 Judah\u2026" is a preview and is meant to
    # run out.
    for code in done:
        prose = [t for t in trimmed.get(code, set()) if ' \u00b7 ' not in t]
        for text in sorted(prose):
            warn('[%s] %r is cut mid-sentence at %.0fpx'
                 % (code, text.split('\x04')[-1][:64], width))
    for code in done:
        if code == 'en':
            continue
        extra = trimmed.get(code, set()) - trimmed.get('en', set())
        for text in sorted(extra):
            # A msgid carrying a context comes back joined by \x04; the
            # context is bookkeeping and only the English belongs in a report.
            warn('[%s] %r is cut short on its plate; the English fits'
                 % (code, text.split('\x04')[-1][:64]))


def write(out_dir: str, width: float) -> None:
    os.makedirs(out_dir, exist_ok=True)
    # The estimate, not Pango: a plate is an SVG, and the face it ends up in
    # is whatever the machine that opens it has. Laying it out against this
    # machine's fonts would bake one viewer's metrics into a shared file.
    for c in gb.charts():
        plate = gl.build(c['id'], gl.estimate, width)
        for theme, dark in (('light', False), ('dark', True)):
            path = os.path.join(out_dir, '%s-%s.svg' % (c['id'], theme))
            with open(path, 'w', encoding='utf-8') as f:
                f.write(gsvg.render(plate, dark=dark))
            print('  %s  %.0fx%.0f' % (os.path.basename(path), plate.width,
                                       plate.height))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', help='directory to write SVG plates into')
    ap.add_argument('--width', type=float, default=760.0)
    ap.add_argument('--check', action='store_true',
                    help='audit only; do not write anything')
    args = ap.parse_args()

    doc = gb.document()
    print('%d people · %d edges · %d charts · %d readings'
          % (len(doc['people']), len(doc['edges']), len(doc['charts']),
             len(doc['readings'])))
    audit()
    audit_citations()
    audit_every_language(args.width)

    if _warnings:
        print('\n%d warning(s)' % len(_warnings))
        return 1
    print('clean')
    if args.out and not args.check:
        print('\nwriting plates to %s' % args.out)
        write(args.out, args.width)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
