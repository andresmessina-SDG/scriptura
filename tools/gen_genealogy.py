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
            done.append(code)
    finally:
        if before is None:
            os.environ.pop('LANGUAGE', None)
        else:
            os.environ['LANGUAGE'] = before
        i18n._catalogue()
    print('  plates audited in: %s (%s)'
          % (', '.join(done),
             'Pango' if measure else 'estimate'))

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
