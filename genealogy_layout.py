"""genealogy_layout.py — geometry for the genealogy charts.

Computed, never drawn. This module turns a chart id from `genealogy_bridge`
into a flat list of primitives with absolute coordinates, plus the hit regions
that make the live widget clickable. It imports no GTK and touches no drawing
API, so the same geometry feeds three consumers:

  * `genealogy_reader` — paints the primitives with Cairo, and uses the hit
    regions for expand / focus / navigate.
  * `genealogy_svg` — writes the same primitives out as an SVG plate, for
    print, export and `tools/gen_genealogy.py`.
  * the tests — assert on coordinates without a display.

**Text is measured, never assumed.** Every layout takes a `measure(text, size,
weight) -> width` callable. The reader passes Pango; the SVG writer passes an
estimator. This is not decoration: a translated string in a fixed container
overflows, and this app has shipped that bug twice — the paper chips and the
Module Manager tabs were both broken in Spanish for weeks. A chart whose
column widths were computed from English name lengths would break the same
way the moment `Мафусал` is longer than `Methuselah`.

Roles, not colours. A primitive says what it *is* (`thread`, `omit`, `link`,
`band2`) and each backend maps that to its own palette, so the plate follows
the app's light/dark theme without the geometry knowing about either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import genealogy_bridge as gb
from i18n import _, C_, N_, ngettext


def C_person(name: str) -> str:
    """A person's name in the reader's language, by surface form."""
    return C_('person', name)

Measure = Callable[[str, float, str], float]

# ── grid ───────────────────────────────────────────────────────────────────
# Spacing on the app's 4px grid (data/style.css: "multiples of 4"), so a chart
# sits on the same rhythm as everything around it.
PAD = 24
ROW = 56              # generation pitch on a spine
ROW_TIGHT = 32        # pitch inside a collapsed run
SPINE_X = 128         # the thread's column
NODE_GAP = 22         # thread to name
NAME_GAP = 16         # name to the verse chip on its row
CHIP_H = 20
DOT_R = 5.5
DOT_R_MAJOR = 7


@dataclass
class Prim:
    """One drawable. `kind` picks the shape; `role` picks the colour."""
    kind: Literal['line', 'poly', 'rect', 'dot', 'text', 'chip', 'band', 'hatch']
    role: str = 'ink'
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    r: float = 0.0
    text: str = ''
    size: float = 13.0
    weight: str = 'normal'      # normal | semibold | bold
    style: str = 'normal'       # normal | italic
    anchor: str = 'start'       # start | middle | end
    dash: tuple[float, ...] = ()
    points: list[tuple[float, float]] = field(default_factory=list)
    arrow: bool = False
    serif: bool = False


@dataclass
class Hit:
    """A clickable region. `kind` says what a click means."""
    x: float
    y: float
    w: float
    h: float
    kind: Literal['person', 'verse', 'expand', 'tradition', 'chart']
    payload: str
    label: str = ''


@dataclass
class Plate:
    width: float
    height: float
    prims: list[Prim] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    title: str = ''
    subtitle: str = ''
    #: Read aloud in place of the drawing. A tree is invisible to a screen
    #: reader without one (§6), and this is the same text the SVG carries in
    #: its <desc>.
    alt: str = ''


def estimate(text: str, size: float, weight: str = 'normal') -> float:
    """Fallback text measurement for backends with no font engine.

    An average advance of 0.58em, 0.62 for bold, and **it is not an upper
    bound**: measured against Pango over every string these charts draw, it
    comes out narrower for essentially all of them and by as much as 68% on
    short ones, where a glyph's own side bearings outweigh any average. It
    was documented here as "deliberately generous", which would have made a
    plate that passes an audit under this function safe under Pango; it is
    not, and `tools/gen_genealogy.py` measures with Pango whenever it can
    rather than trusting this.

    What it is good for is a backend with no font engine at all — the SVG
    writer, where the viewer picks the face anyway — and for keeping the
    layout pure.
    """
    per = 0.62 if weight in ('bold', 'semibold') else 0.58
    return len(text) * size * per


# ── shared pieces ──────────────────────────────────────────────────────────

def _chip(p: list[Prim], h: list[Hit], x: float, y: float, label: str,
          role: str, measure: Measure, payload: str,
          kind: Literal['verse', 'chart'] = 'verse') -> float:
    """A verse chip, right-hand column. Returns its width.

    Colour earns attention only on tappable chips (the house rule), so this is
    the one place a chart is allowed a link colour."""
    w = measure(label, 11.0, 'normal') + 20
    p.append(Prim('chip', role, x=x, y=y, w=w, h=CHIP_H, r=CHIP_H / 2,
                  text=label, size=11.0))
    h.append(Hit(x, y, w, CHIP_H, kind, payload, label))
    return w


def _alt_for_chain(edges: list[gb.Edge], title: str) -> str:
    """The text equivalent of a drawn chain.

    Not a summary — the same information in reading order, because this is
    what a screen-reader user gets *instead of* the picture, and a chart that
    degrades to "a diagram of Matthew 1" has told them nothing."""
    parts: list[str] = [title]
    for e in edges:
        # Child first. Every label in `gb.KIND_LABELS` reads from the younger
        # end — "son of", "descended from", "born of" — so parent-first spelt
        # each generation backwards: "Adam — son of — Seth" told a screen
        # reader that Adam was Seth's son, for all 165 edges, in every
        # language. The drawn chart still runs ancestor-downwards; only this
        # sentence has to agree with its own preposition.
        line = '%s — %s — %s (%s)' % (
            gb.person_name(e['child']), gb.kind_label(e['kind']),
            gb.person_name(e['parent']), gb.ref_label(e['ref']))
        if e['mother']:
            line += ', ' + _('mother: %s') % gb.person_name(e['mother'])
        if e['kind'] == 'descends' and e['omits']:
            line += '. ' + _('%(n)d generations omitted here; %(where)s names '
                             'them.') % {'n': e['omits'],
                                         'where': gb.cross_label(e['cross'])}
        parts.append(line)
    return '\n'.join(parts)


# ── A · the descent spine ──────────────────────────────────────────────────

#: A chain shorter than this is drawn whole. Genesis 5 is ten names and every
#: one of them is a plain "begat", so a rule that only asked "is this run
#: plain?" folded the entire chart into a single row reading "9 generations,
#: collapsed" — technically true and completely useless.
COLLAPSE_MIN_CHAIN = 15
#: Runs shorter than this are not worth a click.
COLLAPSE_MIN_RUN = 5
#: Never fold the opening or closing rows: a chart has to show where it starts
#: and where it arrives.
COLLAPSE_KEEP_ENDS = 2
#: One fold never swallows more than this. Luke's chain is sixty-seven plain
#: begettings end to end, so an uncapped rule folded sixty-three of them into
#: a single row and the chart lost its middle entirely. Chunking leaves
#: periodic anchors the reader can navigate by.
COLLAPSE_MAX_RUN = 10


def _collapsible(edges: list[gb.Edge]) -> list[tuple[int, int]]:
    """Runs of plain generations that may be drawn collapsed.

    A run is collapsible only when every edge in it is an ordinary "begat"
    with no mother, no note and no omission — collapsing anything else would
    hide the very thing the chart exists to show."""
    if len(edges) < COLLAPSE_MIN_CHAIN:
        return []
    lo, hi = COLLAPSE_KEEP_ENDS, len(edges) - COLLAPSE_KEEP_ENDS
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(lo, hi):
        e = edges[i]
        plain = (e['kind'] == 'son' and not e['mother'] and not e['note']
                 and not e['omits'])
        if plain and start is None:
            start = i
        elif not plain and start is not None:
            runs += _chunk(start, i)
            start = None
    if start is not None:
        runs += _chunk(start, hi)
    return runs


def _chunk(start: int, stop: int) -> list[tuple[int, int]]:
    """Split one plain run into folds of at most COLLAPSE_MAX_RUN.

    A tail shorter than COLLAPSE_MIN_RUN is drawn out rather than folded on
    its own — a fold that hides three names costs a click and saves a row."""
    if stop - start < COLLAPSE_MIN_RUN:
        return []
    out: list[tuple[int, int]] = []
    i = start
    while stop - i >= COLLAPSE_MIN_RUN:
        out.append((i, min(i + COLLAPSE_MAX_RUN, stop)))
        i = out[-1][1]
    return out


def spine(cid: str, measure: Measure = estimate, width: float = 720,
          expanded: set[int] | None = None,
          collapse: bool = True) -> Plate:
    """Structure A. One vertical thread, generations as de-ruled rows.

    Two kinds of gap, drawn differently and never conflated:

      * a **collapsed run** is ours, hatched, and opens on click;
      * a **telescoped edge** is the writer's, dashed, and can never open —
        the names are not in this list, so the chart cites who does name them
        instead.

    A chart that drew both the same way would teach the reader that Matthew
    left out four generations between Solomon and Rehoboam, which he did not.
    """
    c = gb.chart(cid)
    if c is None:
        return Plate(width, 0)
    edges = gb.chain(c['root'], c['leaf'], gb.passage_book(c['passage']))
    expanded = expanded or set()

    # The left gutter holds the mother labels, and "the wife of Uriah" is
    # wider than the 84px a fixed spine_x left for it — it ran off the plate.
    # Measure the widest one that will actually be drawn, in whatever
    # language this is; every translation of it is longer than the English.
    mother_w = 0.0
    for e in edges:
        if e['mother']:
            mother_w = max(mother_w,
                           measure(gb.person_name(e['mother']), 12.5, 'normal'))
    gutter = max(SPINE_X, PAD + mother_w + 52)

    # Matthew's register rail lives outside the verse chips; without the
    # reservation the band labels printed straight through them. Reserved
    # from the widest label the rail will actually draw, in this language:
    # one specimen count string stood for all of them, and «От переселения
    # до Христа» is 30px wider than it — in English the widest band label
    # already overhung its own reservation by eight.
    rail_w = (max([measure(_(lab), 10.5, 'semibold')
                   for lab in REGISTER_LABELS]
                  + [measure(_('%(n)d written, %(claim)d claimed')
                             % {'n': 88, 'claim': 88}, 10.5, 'normal')]) + 27
              if c['register'] else 0.0)

    # The width this chart cannot be drawn below, measured before anything is
    # placed. A spine has a fixed set of columns — mother, thread, name, verse
    # chip, register rail — and narrowing the plate does not reflow them: the
    # chip is placed from the right edge and lands on top of the name. At 700
    # the Spanish and Russian Matthew both did exactly that, and the English
    # cleared it by six pixels, which is the whole [[i18n-width-traps]] story
    # over again. So the plate takes the width it needs and the reader paints
    # it down to the pane instead of squeezing it.
    drawn = [c['root']] + [e['child'] for e in edges]
    refs = [e['ref'] for e in edges]
    if edges:
        refs.append(_own_ref(edges[-1]['child'], edges[-1]['ref']))
    need = (gutter + NODE_GAP + NAME_GAP + PAD + rail_w
            + max([measure(gb.person_name(pid), 16.5, 'bold')
                   for pid in drawn] + [0.0])
            + max([measure(gb.ref_label(r), 11.0, 'normal') + 20
                   for r in refs] + [0.0]))
    # …and wide enough that the mother-label cap below never binds. A name is
    # the one thing on this chart that must not be cut.
    width = max(width, need, gutter / 0.36)

    # And no wider than the chart can use. A pane wider than the chart used
    # to widen the chart, because the verse chips are placed from the right
    # edge and the names from the left: on Genesis 5 at a 1040px pane the
    # citation stood 615px from the name it belongs to, across empty paper
    # with nothing to carry the eye. The plate stops growing where the last
    # thing on it stops gaining — the widest a collapsed run's preview can
    # spend, on the charts that have runs, and `need` on the charts that do
    # not. `genealogy_reader` centres a plate narrower than its pane.
    # `need` is a floor — the width at which nothing collides — and a chart
    # sitting exactly on it reads as crowded: the name and its chip clear
    # each other by one NAME_GAP and no more. The cap gets a gutter's worth
    # of air on top, so the pair reads as a pair.
    roomy = need + 2 * NAME_GAP
    for s0, e0 in (_collapsible(edges) if collapse else []):
        roomy = max(roomy, gutter + NODE_GAP + PAD + rail_w
                    + measure(NAME_SEP.join(gb.person_name(edges[k]['child'])
                                            for k in range(s0, e0)),
                              12.5, 'normal'))
    width = min(width, max(roomy, gutter / 0.36))

    # Capped so a mother label long enough to need half the plate ellipsizes
    # rather than pushing the whole chart off the right edge. The cap is the
    # last resort, not the everyday case: «la que fue mujer de Urías» is the
    # Reina-Valera's own phrase for Matt 1:6 and wants 187px, and the width
    # above is chosen so it fits whole.
    spine_x = min(gutter, width * 0.36)
    rail_x = width - PAD - 5
    right = width - rail_w if c['register'] else width
    expanded = expanded or set()
    runs = _collapsible(edges) if collapse else []
    open_runs = {i for i, _r in enumerate(runs) if i in expanded}

    p: list[Prim] = []
    h: list[Hit] = []
    y: float = PAD + 8

    # Register bands (Matthew counts his own list; nobody else does).
    band_rows: list[tuple[float, float, str, int]] = []

    # How much taller this row grew than ROW, written by the closure and read
    # by the caller: a two-line gloss has to push everything below it down.
    extra = [0.0]

    def _person_row(pid: str, ref_label: str, ref_payload: str,
                    major: bool, gloss: str, mother: str) -> None:
        extra[0] = 0.0
        p.append(Prim('dot', 'thread', x=spine_x, y=y,
                      r=DOT_R_MAJOR if major else DOT_R))
        name = gb.person_name(pid)
        size = 16.5 if major else 15.5
        p.append(Prim('text', 'ink', x=spine_x + NODE_GAP, y=y - 4,
                      text=name, size=size,
                      weight='bold' if major else 'semibold'))
        nw = measure(name, size, 'bold' if major else 'semibold')
        h.append(Hit(spine_x + NODE_GAP, y - 16, nw, 22, 'person', pid, name))
        if gloss:
            # The gloss gets the whole width and up to two lines. It always
            # was on its own line — the name sits on the chip's baseline and
            # the gloss one under it — but its budget subtracted the chip
            # anyway, leaving 110px for a 430px sentence: thirteen of the
            # Matthew chart's fifty-two strings came out cut, in English,
            # before any translation. The 4px drop is what buys that: at +14
            # the gloss's cap height reached into the chip's bottom edge,
            # which is why the chip was being subtracted in the first place.
            lines = _wrap(gloss, right - PAD - spine_x - NODE_GAP, 13.0,
                          measure, max_lines=3)
            for n, line in enumerate(lines):
                p.append(Prim('text', 'muted', x=spine_x + NODE_GAP,
                              y=y + 18 + n * 17, text=line,
                              size=13.0, style='italic', serif=True))
            extra[0] = 17.0 * (len(lines) - 1)
        if mother:
            mn = _ellipsize(gb.person_name(mother), spine_x - PAD - 52,
                            12.5, measure)
            mw = measure(mn, 12.5, 'normal')
            p.append(Prim('line', 'omit', x=spine_x, y=y,
                          x2=spine_x - 36, y2=y))
            p.append(Prim('text', 'omit', x=spine_x - 44, y=y + 4,
                          text=mn, size=12.5, anchor='end'))
            h.append(Hit(spine_x - 44 - mw, y - 10, mw, 20,
                         'person', mother, mn))
        if ref_label:
            cw = measure(ref_label, 11.0, 'normal') + 20
            _chip(p, h, right - PAD - cw, y - CHIP_H / 2 - 3,
                  ref_label, 'link', measure, ref_payload)

    # The root, then one row per edge (each row is the edge's CHILD).
    if edges:
        first = edges[0]
        _person_row(c['root'], gb.ref_label(first['ref']),
                    _ref_payload(first['ref']),
                    major=True,          # the head of the chart always is
                    gloss=_gloss(c['root']), mother='')
        band_rows.append((y, y, c['root'], 0))
        y += ROW + extra[0]

    run_at = {r[0]: i for i, r in enumerate(runs)}
    i = 0
    while i < len(edges):
        e = edges[i]
        ri = run_at.get(i)
        if ri is not None and ri not in open_runs:
            s0, e0 = runs[ri]
            n = e0 - s0
            top = y - ROW + 12
            p.append(Prim('line', 'thread', x=spine_x, y=top,
                          x2=spine_x, y2=top + 60))
            for k in range(2):
                yy = top + 22 + k * 16
                p.append(Prim('hatch', 'thread', x=spine_x - 8, y=yy + 4,
                              x2=spine_x + 8, y2=yy - 2))
            label = ngettext('%d generation, collapsed',
                             '%d generations, collapsed', n) % n
            p.append(Prim('text', 'muted', x=spine_x + NODE_GAP, y=top + 26,
                          text=label, size=12.5, weight='semibold'))
            run_names = [gb.person_name(edges[k]['child'])
                         for k in range(s0, e0)]
            names = NAME_SEP.join(run_names)
            p.append(Prim('text', 'muted', x=spine_x + NODE_GAP, y=top + 44,
                          text=_ellipsize_names(
                              run_names, right - spine_x - NODE_GAP - PAD,
                              12.5, measure),
                          size=12.5, style='italic', serif=True))
            h.append(Hit(spine_x + NODE_GAP, top + 12,
                         max(measure(label, 12.5, 'semibold'),
                             measure(names, 12.5, 'normal')) * 0.6 + 40, 40,
                         'expand', '%s:%d' % (cid, ri), label))
            y = top + 60 + ROW - 12
            i = e0
            continue

        # A telescoped edge: the writer's own omission.
        if e['kind'] == 'descends' and e['omits']:
            top = y - ROW + 14
            p.append(Prim('line', 'omit', x=spine_x, y=top,
                          x2=spine_x, y2=top + 54, dash=(5, 6)))
            label = ngettext('%d generation omitted',
                             '%d generations omitted', e['omits']) % e['omits']
            # The count and the chip share the top line; the note gets the
            # whole width under them, and wraps. Every other arrangement was
            # worse: chip beside the note left 197px for "Ahaziah, Joash and
            # Amaziah stand between them in Chronicles", which needs 506 and
            # came out as "Chronicles…" — the one thing on the row a reader
            # cannot reconstruct. The count is short in every language and the
            # chip is a fixed reference, so those two fit together.
            full = right - PAD - (spine_x + NODE_GAP)
            cw = 0.0
            cross = gb.cross_label(e['cross']) if e['cross'] else ''
            if cross:
                cw = measure(cross, 11.0, 'normal') + 20
            # The count never gets cut: "3 gener…" is the one thing on this
            # row a reader cannot reconstruct, and in a narrow pane the chip
            # beside it was doing exactly that. If they do not both fit, the
            # chip goes below instead.
            beside = cw and measure(label, 12.5, 'semibold') + 12 + cw <= full
            if cross and beside:
                _chip(p, h, right - PAD - cw, top + 22 - CHIP_H / 2 - 3,
                      cross, 'omit', measure, _payload_text(e['cross']))
            p.append(Prim('text', 'omit', x=spine_x + NODE_GAP, y=top + 22,
                          text=label, size=12.5, weight='semibold'))
            note_lines: list[str] = []
            if e['note']:
                note_lines = _wrap(_(e['note']), full, 12.5, measure,
                                   max_lines=3)
                for n, line in enumerate(note_lines):
                    p.append(Prim('text', 'omit', x=spine_x + NODE_GAP,
                                  y=top + 42 + n * 17, text=line,
                                  size=12.5, style='italic', serif=True))
            grown = 17 * max(0, len(note_lines) - 1)
            if cross and not beside:
                # Clear of the note's LAST line, not of its first: at +46 the
                # chip was drawn through the descenders of the line above it
                # whenever the note ran to two lines, which in Russian is
                # every width from 700 to 900.
                _chip(p, h, spine_x + NODE_GAP, top + 54 + grown, cross,
                      'omit', measure, _payload_text(e['cross']))
                grown += 34
            y = top + 54 + ROW - 14 + grown
        elif e['kind'] in ('husband', 'born_of', 'supposed'):
            # Not a begetting, and the chart says so on the line itself.
            top = y - ROW + 16
            p.append(Prim('line', 'muted', x=spine_x, y=top,
                          x2=spine_x, y2=top + 40, dash=(2, 4)))
            p.append(Prim('text', 'muted', x=spine_x + NODE_GAP, y=top + 24,
                          text=gb.kind_label(e['kind']), size=12.0,
                          style='italic', serif=True))
            y = top + 40 + ROW - 16
        else:
            p.append(Prim('line', 'thread', x=spine_x, y=y - ROW,
                          x2=spine_x, y2=y))

        # A row cites the verse where this person begets the next — which is
        # the NEXT edge's reference. The last row has no next edge, so it
        # looks for one of its own children instead: Noah's chip read
        # "Genesis 5:28" (Lamech begetting him) when 5:32 is the verse that
        # has Noah doing the begetting.
        nxt = edges[i + 1] if i + 1 < len(edges) else None
        own = nxt['ref'] if nxt else _own_ref(e['child'], e['ref'])
        _person_row(e['child'],
                    gb.ref_label(own),
                    _ref_payload(own),
                    major=e['child'] in (c['leaf'], 'david', 'abraham'),
                    gloss=_gloss(e['child']),
                    mother=e['mother'])
        band_rows.append((y, y, e['child'], i))
        y += ROW + extra[0]
        i += 1

    if c['register']:
        _register_bands(p, h, band_rows, edges, width, measure, c['root'],
                        rail_x)

    plate = Plate(width, y - ROW + PAD + 16, p, h,
                  title=_(c['title']), subtitle=_(c['subtitle']))
    plate.alt = _alt_for_chain(edges, _(c['title']))
    return plate


def _own_ref(pid: str, fallback: gb.Ref) -> gb.Ref:
    """A verse in which this person is the one acting, **in this book**.

    Never leaves the passage the chart is drawn from. Taking any child edge
    when the book had none put "Matthew 1:2" on the last row of a Genesis 11
    chart and "Matthew 1:6" on the last row of Ruth 4 — the first edge the
    table happened to hold for Abraham and for David. A chart whose whole
    claim is that every line cites the passage in front of you cannot end by
    citing a different book; the verse that begot him is the honest answer
    when this book never shows him begetting anyone.
    """
    for e in gb.children_of(pid):
        if e['ref']['book'] == fallback['book']:
            return e['ref']
    return fallback


def _gloss(pid: str) -> str:
    """The line under a name: what it means, or why the person matters.

    Meaning first — it is the shorter of the two and the one a reader can use
    immediately. Curated per person; most people have neither and get a bare
    name, which is correct: a gloss on every row is a wall."""
    doc = gb.document()
    p = doc['people'].get(pid)
    if not p:
        return ''
    if p['meaning']:
        return _(p['meaning'])
    return _(p['note']) if p['note'] else ''


def _ref_payload(ref: gb.Ref) -> str:
    return '%s|%d|%d' % (ref['book'], ref['chapter'], ref['verse'])


def _payload_text(text: str) -> str:
    r = gb.parse_ref(text)
    return _ref_payload(r) if r else ''


#: Every string this run had to cut short. Bounded by the number of distinct
#: captions the table holds, a few hundred at most, which is why a module-level
#: set is safe in a long-running app that never reads it.
#: A trimmed caption is silent loss —
#: it stays inside its box, so the overflow audit passes and the reader is the
#: one who finds out. What makes it actionable is the comparison: a string the
#: English fits and a translation does not is a string whose budget was set by
#: the one language nobody had to think about. `tools/gen_genealogy.py` reads
#: this after each language and reports the difference.
_trimmed: set[str] = set()


def _wrap(text: str, avail: float, size: float, measure: Measure,
          max_lines: int = 2) -> list[str]:
    """Break a caption over at most `max_lines`, ellipsizing only the last.

    One line was the whole vocabulary here, and it cost the ends of sentences:
    "The line breaks its own grammar at her: Jesus is bor…" needs 611px and the
    Matthew chart has 365. A caption is prose; prose wraps. Names, numbers and
    chips stay on one line, which is why this takes a limit rather than being
    the default everywhere.
    """
    if avail <= 0:
        _trimmed.add(text)
        return []
    if measure(text, size, 'normal') <= avail:
        return [text]
    words, lines, cur = text.split(' '), [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if cur and measure(trial, size, 'normal') > avail:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
        else:
            cur = trial
    if len(lines) < max_lines:
        lines.append(cur)
        return lines
    # Whatever is left over goes back onto the last line and is cut there.
    rest = text[len(' '.join(lines)):].strip()
    lines[-1] = _ellipsize((lines[-1] + ' ' + rest).strip(), avail, size,
                           measure)
    return lines


#: What joins the names in a collapsed run's preview.
NAME_SEP = ' · '


def _ellipsize_names(names: list[str], avail: float, size: float,
                     measure: Measure) -> str:
    """Join names to fit, dropping whole names — never half of one.

    `_ellipsize` trims by character, which is right for a sentence and wrong
    for this. A chart whose whole subject is who was called what shipped
    "Naasson" as `Naasso…`, "Cosam" as `Cosa…` and "Noah" as `N…`; in Spanish
    `Josafa…`, in Russian `Авраа…`. Two thirds of the previews on the Matthew,
    Luke and side-by-side charts ended mid-name, in every language and at
    every width. A reader cannot tell a trimmed name from a misspelt one, and
    on these charts that is the one thing they must be able to tell.

    So the ellipsis stands where a name would be, not inside one. At least
    one name is always kept: a preview reading only `…` says nothing that the
    count above it has not already said.
    """
    if not names:
        return ''
    text = NAME_SEP.join(names)
    if avail <= 0:
        _trimmed.add(text)
        return ''
    if measure(text, size, 'normal') <= avail:
        return text
    _trimmed.add(text)
    keep = 1
    for n in range(len(names) - 1, 0, -1):
        if measure(NAME_SEP.join(names[:n]) + NAME_SEP + '…', size,
                   'normal') <= avail:
            keep = n
            break
    return NAME_SEP.join(names[:keep]) + NAME_SEP + '…'


def _ellipsize(text: str, avail: float, size: float, measure: Measure) -> str:
    """Trim to fit, with an ellipsis.

    A widget whose minimum nobody set collapses, and a string in a fixed
    container overflows; this is the second case, and it is why the layout
    takes a measure function at all.

    A budget of zero or less means nothing fits, and the honest answer is to
    draw nothing. Returning the string untouched — which this did — is how a
    caption ended up four hundred pixels off the right edge of its own plate
    the moment the surrounding labels got wider. Every overflow the test suite
    found in the wide-measure pass traced back to this one line."""
    if avail <= 0:
        _trimmed.add(text)
        return ''
    if measure(text, size, 'normal') <= avail:
        return text
    _trimmed.add(text)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + '…', size, 'normal') <= avail:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip(' ·') + '…'


# ── E · the register overlay ───────────────────────────────────────────────

def register_sets(root: str, edges: list[gb.Edge]) -> list[tuple[str, int]]:
    """Matthew's three fourteens, counted the way he counts them.

    Counted over the NAMES Matthew writes, not the rows this chart happens to
    draw: the spine folds plain runs and telescopes two edges, so a count of
    drawn rows reported nine, three and four for a list whose own author says
    fourteen, fourteen and fourteen.

    Mary is excluded. She reaches Jesus through `husband` and `born_of`, which
    is Matthew breaking his own grammar rather than adding a generation, and
    counting her would quietly fix the very discrepancy this band exists to
    show."""
    names = [root] + [e['child'] for e in edges
                      if e['kind'] in ('son', 'descends')]
    leaf_edges = [e for e in edges if e['kind'] == 'born_of']
    if leaf_edges:
        names.append(leaf_edges[-1]['child'])
    out: list[tuple[str, int]] = []
    start = 0
    for marker in ('david', 'jeconiah'):
        if marker in names:
            i = names.index(marker)
            out.append((marker, i - start + 1))
            start = i + 1
    out.append(('', len(names) - start))
    return out


#: What Matthew claims for each set (Matt 1:17).
REGISTER_CLAIM = 14

#: The rail's three band labels. Module-level because the spine has to
#: reserve room for them before `_register_bands` draws them, and a copy of
#: the list in each place is a copy that drifts.
#:
#: `N_`, not a marker of our own: xgettext is told `--keyword=N_` and knows
#: nothing about any other name. A layout-local `N_ID` marked these three for
#: a tool that never looked, so `_(labels[i])` resolved a msgid the catalogue
#: had never heard of and Matthew's three bands stayed in English on a
#: Spanish plate.
REGISTER_LABELS = [N_('Abraham to David'), N_('David to the exile'),
                   N_('The exile to the Christ')]


def _register_bands(p: list[Prim], h: list[Hit],
                    rows: list[tuple[float, float, str, int]],
                    edges: list[gb.Edge], width: float,
                    measure: Measure, root: str, rail_x: float) -> None:
    """Matthew's own three fourteens, drawn as a rail beside his list.

    Only Matthew counts himself (Matt 1:17), so this is a mode of the spine
    rather than a structure of its own. The third band is where it earns its
    place: Matthew asserts fourteen and the names between Jeconiah and Joseph
    come to thirteen. The band prints the count it actually has and marks the
    shortfall; it does not renumber to make the claim come out."""
    sets = register_sets(root, edges)
    by_pid = {pid: y for (y, _y2, pid, _i) in rows}
    labels = REGISTER_LABELS
    top = rows[0][0] if rows else 0.0
    bottom = rows[-1][0] if rows else 0.0
    edgesy = [top]
    for marker, _n in sets[:-1]:
        edgesy.append(by_pid.get(marker, bottom))
    edgesy.append(bottom)

    for i, (_marker, n) in enumerate(sets[:3]):
        y0, y1 = edgesy[i], edgesy[i + 1]
        short = n != REGISTER_CLAIM
        p.append(Prim('band', 'omit' if short else 'band%d' % (i + 1),
                      x=rail_x, y=y0 - 14, w=5,
                      h=max(10.0, y1 - y0 + 20), r=2.5))
        p.append(Prim('text', 'muted', x=rail_x - 10, y=y0 + 2,
                      text=_(labels[i]), size=10.5, anchor='end',
                      weight='semibold'))
        p.append(Prim('text', 'omit' if short else 'muted', x=rail_x - 10,
                      y=y0 + 18,
                      text=(_('%(n)d written, %(claim)d claimed')
                            % {'n': n, 'claim': REGISTER_CLAIM}) if short
                      else ngettext('%d name', '%d names', n) % n,
                      size=10.5, anchor='end'))


# ── B · the household ──────────────────────────────────────────────────────

def household(cid: str, measure: Measure = estimate,
              width: float = 760) -> Plate:
    """Structure B. Children grouped under their mothers.

    Father-only, this is a list of twelve names. With the mothers it is the
    reason the tribes are grouped as they are for the rest of the Bible, so
    the mother band is the structure and not an ornament. The band colours are
    the highlighter palette — *content* colours under the app's two-accent
    law, the same standing a highlight has, so they add no chrome accent."""
    c = gb.chart(cid)
    if c is None:
        return Plate(width, 0)
    book = gb.passage_book(c['passage'])
    kids = [e for e in gb.children_of(c['root']) if e['ref']['book'] == book]

    # Group in first-appearance order; the text's own order is the answer to
    # "which mother comes first", and re-sorting it would be an edit.
    order: list[str] = []
    groups: dict[str, list[gb.Edge]] = {}
    for e in kids:
        m = e['mother'] or ''
        if m not in groups:
            order.append(m)
            groups[m] = []
        groups[m].append(e)

    # Columns sized to their widest member, so a long translated name widens
    # its own column instead of running into the next one.
    def _note(pid: str) -> str:
        rec = gb.document()['people'].get(pid)
        return _(rec['note']) if rec and rec['note'] else ''

    col_w: list[float] = []
    for m in order:
        widest = measure(gb.person_name(m) if m else _('no mother named'),
                         14.5, 'semibold')
        for e in groups[m]:
            widest = max(widest, measure(gb.person_name(e['child']), 14.5,
                                         'normal'))
        # The mother's note sets a floor, not the width: it is the longest
        # string in the column and letting it drive the layout would give
        # Leah four times Zilpah's width for a caption.
        widest = max(widest, measure(gb.ref_label(groups[m][0]['ref']),
                                     11.0, 'normal') + 20)
        col_w.append(widest + 28)
    total = sum(col_w)
    # Sized before anything is placed, because the columns are what the plate
    # is: squeezing four of them into a narrow pane put Reuben's verse chip on
    # top of Simeon's. The plate takes the width its own columns need and the
    # reader paints it down.
    width = max(width, total + 2 * PAD)
    avail = width - 2 * PAD
    col_w = [w + (avail - total) / len(col_w) for w in col_w]

    p: list[Prim] = []
    h: list[Hit] = []

    root_name = gb.person_name(c['root'])
    cx = width / 2
    p.append(Prim('text', 'ink', x=cx, y=PAD + 14, text=root_name,
                  size=16.5, weight='bold', anchor='middle'))
    rw = measure(root_name, 16.5, 'bold')
    h.append(Hit(cx - rw / 2, PAD, rw, 22, 'person', c['root'], root_name))
    # "also Israel" — one person, two names, which is the trap this table
    # keys on ids to avoid.
    root = gb.document()['people'].get(c['root'])
    also = root['also'] if root else []
    if also:
        p.append(Prim('text', 'muted', x=cx, y=PAD + 30,
                      text=_('also %s') % C_person(also[0]),
                      size=12.0, style='italic', anchor='middle', serif=True))

    bus_y = PAD + 52
    p.append(Prim('line', 'muted', x=cx, y=PAD + 36, x2=cx, y2=bus_y))

    x0: float = PAD

    # The horizontal bus, drawn between the first and last column centres —
    # without it the drop lines hang in the air under Jacob, connected to
    # nothing, which is what the first render actually showed.
    mids = []
    xx = x0
    for w in col_w:
        mids.append(xx + w / 2)
        xx += w
    p.append(Prim('line', 'muted', x=mids[0], y=bus_y, x2=mids[-1], y2=bus_y))

    # How far the chips and the sons drop so a wrapped mother's note has
    # room. Taken across all four columns, not per column: chips at four
    # different heights would read as a broken figure, and the cost of the
    # uniform drop is a little air under the short notes.
    def _note_lines(gi: int, m: str) -> list[str]:
        return _wrap(_note(m), col_w[gi] - 28, 11.5, measure) if m else []

    drop = 17 * max([len(_note_lines(gi, m)) for gi, m in enumerate(order)]
                    + [1]) - 17

    x = x0
    for gi, m in enumerate(order):
        w = col_w[gi]
        mid = mids[gi]
        p.append(Prim('line', 'muted', x=mid, y=bus_y, x2=mid, y2=bus_y + 18))
        role = 'band%d' % (gi % 4 + 1)
        p.append(Prim('rect', role, x=x, y=bus_y + 22, w=w - 28, h=4, r=2))
        label = gb.person_name(m) if m else _('no mother named')
        p.append(Prim('text', 'ink', x=x, y=bus_y + 46, text=label,
                      size=14.5, weight='semibold'))
        if m:
            mw = measure(label, 14.5, 'semibold')
            h.append(Hit(x, bus_y + 32, mw, 20, 'person', m, label))
            for n, line in enumerate(_note_lines(gi, m)):
                p.append(Prim('text', 'muted', x=x, y=bus_y + 62 + n * 17,
                              text=line, size=11.5))
        # ONE chip per group, not one per child. Every child in a group is
        # named by the same verse, so a chip on each row repeated the same
        # citation down the column — and, at the width Leah's column got,
        # printed it straight through her sons' names.
        _chip(p, h, x, bus_y + 72 + drop, gb.ref_label(groups[m][0]['ref']),
              'link', measure, _ref_payload(groups[m][0]['ref']))

        yy = bus_y + 118 + drop
        for e in groups[m]:
            nm = gb.person_name(e['child'])
            thread = e['child'] == 'judah'      # the line the rest hangs on
            if thread:
                p.append(Prim('rect', 'thread-wash', x=x - 8, y=yy - 16,
                              w=max(measure(nm, 14.5, 'semibold') + 24, 88),
                              h=22, r=6))
            p.append(Prim('text', 'ink' if thread else 'ink-soft', x=x, y=yy,
                          text=nm, size=14.5,
                          weight='semibold' if thread else 'normal',
                          serif=True))
            nw = measure(nm, 14.5, 'normal')
            h.append(Hit(x, yy - 16, max(nw, 40), 22, 'person', e['child'], nm))
            if thread:
                # The covenant thread leaves this figure through Judah; the
                # gold says the two structures are one system.
                dx = x + max(measure(nm, 14.5, 'semibold') + 24, 88) - 12
                p.append(Prim('dot', 'thread', x=dx, y=yy - 5, r=4.5))
                p.append(Prim('line', 'thread', x=dx, y=yy - 5, x2=dx,
                              y2=yy + 44))
                # Measured to the plate edge, not to Leah's column: the
                # label hangs a row below her sixth son, where the other
                # three columns have long run out, and `w - 40` cut it to
                # "the line contin…" in English at any ordinary pane width.
                room = width - PAD - (dx + 10)
                p.append(Prim('text', 'thread', x=dx + 10, y=yy + 46,
                              text=_ellipsize(_('the line continues here'),
                                              room, 11.5, measure),
                              size=11.5, weight='semibold'))
                h.append(Hit(dx - 6, yy - 12, room, 60, 'chart',
                             gb.chart_containing('judah', 'Matthew'),
                             _('the line continues here')))
            yy += 26
        x += w

    bottom = (bus_y + 118 + drop
              + max(len(g) for g in groups.values()) * 26 + 24)
    p.append(Prim('line', 'rule', x=PAD, y=bottom, x2=width - PAD, y2=bottom))
    foot = _('Grouping and order from %s') % _(c['passage'])
    p.append(Prim('text', 'muted', x=PAD, y=bottom + 18, text=foot, size=11.5))

    plate = Plate(width, bottom + 36, p, h,
                  title=_(c['title']), subtitle=_(c['subtitle']))
    lines = [_(c['title'])]
    for m in order:
        who = ', '.join(gb.person_name(e['child']) for e in groups[m])
        lines.append('%s: %s' % (gb.person_name(m) if m else _('no mother named'),
                                 who))
    plate.alt = '\n'.join(lines)
    return plate


# ── C · the lifespan field ─────────────────────────────────────────────────

def lifespan(cid: str, measure: Measure = estimate, width: float = 760,
             tradition: str = '') -> Plate:
    """Structure C. One bar per life on a shared axis of years from Adam.

    The only structure here that shows something a list physically cannot:
    who was alive at the same time as whom. Every figure is arithmetic on the
    verses — the chart computes the years rather than carrying a chronology
    from anywhere else, and it names the tradition it computed them under,
    because the Masoretic, Septuagint and Samaritan numbers give a genuinely
    different chart rather than a rounding difference."""
    c = gb.chart(cid)
    if c is None:
        return Plate(width, 0)
    trad = tradition or c['tradition']
    rows = gb.lifespans(trad)
    p: list[Prim] = []
    h: list[Hit] = []

    # Tradition chips first: no year on this plate without its source named.
    x: float = PAD
    y = PAD
    for key, label, have in gb.traditions():
        cw = measure(label, 11.5, 'semibold') + 26
        p.append(Prim('chip', 'chip-on' if key == trad else
                      ('chip-off' if have else 'chip-dead'),
                      x=x, y=y, w=cw, h=22, r=11, text=label, size=11.5,
                      weight='semibold'))
        if have:
            h.append(Hit(x, y, cw, 22, 'tradition', key, label))
        x += cw + 8
    if not all(a for _k, _l, a in gb.traditions()):
        # Beside the chips when they leave room for it, on its own line when
        # they do not. Three chips reading «Масоретский текст», «Септуагинта»
        # and «Самаритянское Пятикнижие» leave 104px of a 238px note, and the
        # note explains what the greyed chip means — cutting it to «серым:»
        # would leave the reader with the question and none of the answer.
        # (`_ellipsize` returns the string untouched for a non-positive
        # budget, which once put this note 400px off the right edge.)
        hint = _('greyed: no such text installed')
        room = width - x - PAD - 4
        if measure(hint, 11.5, 'normal') <= room:
            p.append(Prim('text', 'muted', x=x + 4, y=y + 15, text=hint,
                          size=11.5, style='italic', serif=True))
        else:
            y += 24
            p.append(Prim('text', 'muted', x=PAD, y=y + 12,
                          text=_ellipsize(hint, width - 2 * PAD, 11.5,
                                          measure),
                          size=11.5, style='italic', serif=True))

    if not rows:
        return Plate(width, y + 60, p, h, title=_(c['title']))

    # Compute years-from-Adam by walking the begat ages in chain order.
    order = [ls['person'] for ls in rows]
    born: dict[str, int] = {}
    acc = 0
    for ls in rows:
        born[ls['person']] = acc
        acc += ls['begat']
    span = max(born[ls['person']] + ls['total'] for ls in rows)
    span = int(span * 1.02)

    gutter = max(measure(gb.person_name(pid), 12.5, 'normal')
                 for pid in order) + 16
    x0 = PAD + gutter
    x1 = width - PAD
    scale = (x1 - x0) / span

    top = y + 40
    row_h = 24
    bottom = top + len(rows) * row_h

    p.append(Prim('line', 'rule', x=x0, y=top - 8, x2=x0, y2=bottom))
    p.append(Prim('line', 'rule', x=x0, y=bottom, x2=x1, y2=bottom))
    step = 500
    v = 0
    while v <= span:
        gx = x0 + v * scale
        if v:
            p.append(Prim('line', 'rule-soft', x=gx, y=top - 8, x2=gx, y2=bottom))
        p.append(Prim('text', 'muted', x=gx, y=bottom + 16,
                      text=(_('AM %d') % v) if v == 0 else str(v),
                      size=10.5, anchor='middle'))
        v += step

    # The flood, where the text puts it: Noah's 600th year (Gen 7:6).
    flood = None
    if 'noah' in born:
        flood = born['noah'] + 600
        fx = x0 + flood * scale
        p.append(Prim('line', 'omit', x=fx, y=top - 14, x2=fx, y2=bottom,
                      dash=(4, 4)))
        # The flood line sits near the right edge by construction — it is late
        # in the reckoning — so its label goes on whichever side has room.
        head = _('the flood · AM %d') % flood
        cite = gb.ref_label({'book': 'Genesis', 'chapter': 7, 'verse': 6})
        need = max(measure(head, 11.5, 'semibold'), measure(cite, 11.0, 'normal'))
        if fx + 6 + need <= width - PAD:
            lx, anchor = fx + 6, 'start'
        else:
            lx, anchor = fx - 6, 'end'
        p.append(Prim('text', 'omit', x=lx, y=top - 2, text=head, size=11.5,
                      weight='semibold', anchor=anchor))
        p.append(Prim('text', 'omit', x=lx, y=top + 12, text=cite,
                      size=11.0, style='italic', serif=True, anchor=anchor))

    thread: list[tuple[float, float]] = []
    for i, ls in enumerate(rows):
        pid = ls['person']
        ry = top + i * row_h
        b, d = born[pid], born[pid] + ls['total']
        bx, dx = x0 + b * scale, x0 + d * scale
        nm = gb.person_name(pid)
        p.append(Prim('text', 'ink-soft', x=x0 - 10, y=ry + 11, text=nm,
                      size=12.5, anchor='end'))
        nw = measure(nm, 12.5, 'normal')
        h.append(Hit(x0 - 10 - nw, ry, nw, row_h, 'person', pid, nm))
        # Enoch does not die; the bar must not end like the others.
        taken = ls['death_ref'] is None or ls['total'] == 365 and pid == 'enoch'
        p.append(Prim('rect', 'hatch-life' if taken else 'life',
                      x=bx, y=ry + 3, w=max(2.0, dx - bx), h=13, r=3))
        h.append(Hit(bx, ry, max(2.0, dx - bx), row_h, 'person', pid, nm))
        gx = x0 + (b + ls['begat']) * scale
        thread.append((gx, ry + 9.5))
        if flood is not None and d == flood:
            # Put the callout on whichever side of the bar it fits. At the
            # flood line there are barely a hundred pixels of plate left, and
            # the first render clipped this label mid-word.
            note = _('dies in the flood year')
            nwid = measure(note, 11.5, 'semibold')
            if dx + 32 + nwid <= width - PAD:
                p.append(Prim('line', 'omit', x=dx, y=ry + 9,
                              x2=dx + 26, y2=ry + 9))
                p.append(Prim('text', 'omit', x=dx + 32, y=ry + 6, text=note,
                              size=11.5, weight='semibold'))
            else:
                p.append(Prim('text', 'omit', x=dx - 10, y=ry + 6, text=note,
                              size=11.5, weight='semibold', anchor='end'))

    p.append(Prim('poly', 'thread', points=thread))
    for (gx, gy) in thread:
        p.append(Prim('dot', 'thread', x=gx, y=gy, r=3.2))

    plate = Plate(width, bottom + 40, p, h,
                  title=_(c['title']), subtitle=_(c['subtitle']))
    lines = [_(c['title']),
             _('Reckoned under the %s.') % dict(
                 (k, l) for k, l, _a in gb.traditions())[trad]]
    for ls in rows:
        lines.append(_('%(who)s: born AM %(b)d, lived %(t)d years, '
                       'died AM %(d)d (%(ref)s)') % {
            'who': gb.person_name(ls['person']), 'b': born[ls['person']],
            't': ls['total'], 'd': born[ls['person']] + ls['total'],
            'ref': gb.ref_label(ls['ref'])})
    plate.alt = '\n'.join(lines)
    return plate


# ── D · the two witnesses ──────────────────────────────────────────────────

def _tie_row(p: list[Prim], h: list[Hit], lx: float, rx: float, width: float,
             y: float, pid: str, lseq: list[str], rseq: list[str],
             ln: int, rn: int, measure: Measure,
             ledges: list[gb.Edge], redges: list[gb.Edge],
             left_c: gb.Chart, right_c: gb.Chart) -> float:
    """One row where both witnesses name the same person.

    The row also carries what each writer says *about* how he got there, and
    that is where the honest work is: at Shealtiel the two name different
    fathers, and at Jesus neither of them names a father at all — Matthew has
    him born of Mary and Luke has him a son "as was supposed". A row that
    printed "one man, two fathers" under Jesus would be stating something
    neither Gospel says."""
    p.append(Prim('line', 'agree', x=lx, y=y, x2=rx, y2=y))
    for x in (lx, rx):
        p.append(Prim('dot', 'thread', x=x, y=y, r=DOT_R))
    nm = gb.person_name(pid)
    nw = measure(nm, 15.0, 'bold')
    p.append(Prim('text', 'ink', x=width / 2, y=y - 8, text=nm,
                  size=15.0, weight='bold', anchor='middle'))
    h.append(Hit(width / 2 - nw / 2, y - 24, nw, 20, 'person', pid, nm))

    def _step(edges: list[gb.Edge]) -> tuple[str, str]:
        for e in edges:
            if e['child'] == pid:
                return e['parent'], e['kind']
        return '', ''

    lp, lk = _step(ledges)
    rp, rk = _step(redges)
    if lp and rp and (lp != rp or lk != rk):
        qualified = lk != 'son' or rk != 'son'
        headline = (_('each names a different step') if qualified
                    else _('one man, two fathers'))
        # Relation on one line, man on the next. Concatenated — "son of" plus
        # a bare name — Russian came out ungrammatical: «сын Иехония» needs
        # the genitive «Иехонии», and no format string can decline a name
        # supplied at run time. Stacked, each part stands in its own case in
        # every language. It also halves the widest label on the plate, which
        # was "son, as was supposed, of Joseph" and is wider in translation.
        sides = [(lx, gb.kind_label(lk), gb.person_name(lp)),
                 (rx, gb.kind_label(rk), gb.person_name(rp))]
        # Clear the tie-line: at +18 the label sat ON the rule and was struck
        # through by it.
        for x, kind, who in sides:
            p.append(Prim('text', 'omit', x=x, y=y + 24, text=kind,
                          size=11.0, anchor='middle'))
            p.append(Prim('text', 'omit', x=x, y=y + 40, text=who,
                          size=11.5, anchor='middle', weight='semibold'))
        # The centre note goes on its own line when the side labels are wide
        # enough to reach it.
        widest = max(max(measure(kind, 11.0, 'normal'),
                         measure(who, 11.5, 'semibold'))
                     for _x, kind, who in sides)
        centre_w = measure(headline, 11.0, 'semibold')
        if centre_w / 2 + widest / 2 + 16 < (rx - lx) / 2:
            p.append(Prim('text', 'omit', x=width / 2, y=y + 32,
                          text=headline, size=11.0, anchor='middle',
                          weight='semibold'))
            return y + 72
        p.append(Prim('text', 'omit', x=width / 2, y=y + 58, text=headline,
                      size=11.0, anchor='middle', weight='semibold'))
        return y + 92
    p.append(Prim('text', 'agree', x=width / 2, y=y + 20,
                  text=_('both agree'), size=11.5, anchor='middle',
                  weight='semibold'))
    return y + 44


def _rail(p: list[Prim], x: float, y0: float, y1: float,
          role: str = 'muted') -> None:
    """A vertical rail down a column, broken around whatever it would cross.

    The two rails on the side-by-side chart were appended last and drawn as
    single lines, so they were painted straight through the middle of every
    label centred on their column: `Jech|onias`, `Ne|ri`, `Mar|y`, `Jos|eph`,
    «Иехо|ния». Dark mode made it worse — the rail is lighter than the paper
    there, so it read as a scratch across the word.

    Reordering alone would not fix it. A 1.4px rule under a name still runs
    through the name; a printed chart breaks the rule instead, which is what
    this does. Every text centred on this column, and every band sitting on
    it, punches a gap in the rail, and the segments between are what gets
    drawn.

    Called after the rows are laid out, because only then is it known what
    the rail has to miss.
    """
    stops: list[tuple[float, float]] = []
    for q in p:
        if q.kind == 'text' and q.anchor == 'middle' and abs(q.x - x) <= 24:
            # A layout is drawn with its top at `y - size`; 3px of air on
            # each side keeps the rail off the ascenders and descenders.
            stops.append((q.y - q.size - 3, q.y + 3))
        elif q.kind in ('band', 'rect') and q.x - 2 <= x <= q.x + q.w + 2:
            stops.append((q.y - 2, q.y + q.h + 2))
    at = y0
    for lo, hi in sorted(stops):
        if hi <= at or lo >= y1:
            continue
        if lo - at > 2:
            p.append(Prim('line', role, x=x, y=at, x2=x, y2=min(lo, y1)))
        at = max(at, hi)
    if y1 - at > 2:
        p.append(Prim('line', role, x=x, y=at, x2=x, y2=y1))


def witnesses(cid: str, measure: Measure = estimate,
              width: float = 700) -> Plate:
    """Structure D. Two lists of one descent, tied where they agree.

    Built for one job. Both sides are shown as their own writers give them and
    neither is corrected; where they part, the chart says they part and stops.
    The classical explanations are attached to the chart as readings and are
    rendered *below* the drawing, attributed — never on it.

    One honest cost is written into the plate itself: Luke's list runs upward
    in the text, from Jesus back to Adam, so aligning the two columns reverses
    one of them. Every chart that compares these two has done this; this one
    says so."""
    c = gb.chart(cid)
    if c is None:
        return Plate(width, 0)
    left_c, right_c = gb.chart(c['left']), gb.chart(c['right'])
    if left_c is None or right_c is None:
        return Plate(width, 0)

    lb, rb = gb.passage_book(left_c['passage']), gb.passage_book(right_c['passage'])
    ledges = gb.chain(left_c['root'], left_c['leaf'], lb)
    redges = gb.chain(right_c['root'], right_c['leaf'], rb)
    lseq = [ledges[0]['parent']] + [e['child'] for e in ledges] if ledges else []
    rseq = [redges[0]['parent']] + [e['child'] for e in redges] if redges else []
    # Luke is written Jesus-first; both sequences are put in descent order so
    # the columns can be aligned at all. This is the reversal named above.
    shared = [pid for pid in lseq if pid in set(rseq)]

    # The two columns sit at fixed fractions of the width, so everything on
    # this plate is centred on a point that moves when the plate narrows —
    # and the column labels then run into the note between them. At 700 the
    # Spanish «20 nombres más» and «ningún nombre en común» overlapped by
    # eleven pixels. The plate takes the width its own labels need instead.
    # The one row with no fallback: a "n further names" count on each side and
    # the note between them share a line. (The tie rows' headline has one —
    # it drops to its own line when the side labels reach it — so it does not
    # bind here.) A column label is centred at 0.28 of the width and the note
    # at 0.5, so the air between them is 0.22 of the width less half of each.
    counted = measure(ngettext('%d further name', '%d further names', 88)
                      % 88, 13.5, 'normal')
    middle = max(measure(_('no name in common'), 11.5, 'semibold'),
                 measure(_('%d shared') % 88, 11.5, 'semibold'))
    # Nothing centred on a column may reach the plate edge either.
    wide = max([measure(gb.person_name(pid), 15.0, 'bold')
                for pid in set(lseq) | set(rseq)]
               + [measure(_(left_c['passage']), 14.0, 'bold'),
                  measure(_(right_c['passage']), 14.0, 'bold'), counted])
    width = max(width, (counted + middle + 32) / 0.44,
                (wide / 2 + PAD) / 0.28)

    p: list[Prim] = []
    h: list[Hit] = []
    lx, rx = width * 0.28, width * 0.72
    y: float = PAD + 6

    head_extra = 0.0
    for x, ch, note in ((lx, left_c, ''),
                        (rx, right_c, _('reads upward in the text; '
                                        'inverted here to align'))):
        p.append(Prim('text', 'ink', x=x, y=y, text=_(ch['passage']),
                      size=14.0, weight='bold', anchor='middle'))
        if note:
            # Centred on the right column, so its room is twice the distance
            # to the plate edge — and it wraps, because it is a sentence and
            # was coming out as "inverted here t…" in English before any
            # translation touched it.
            room = 2 * (width - PAD - x)
            note_rows = _wrap(note, room, 11.5, measure)
            for n, line in enumerate(note_rows):
                p.append(Prim('text', 'omit', x=x, y=y + 16 + n * 15,
                              text=line, size=11.5, anchor='middle'))
            head_extra = 15 * (len(note_rows) - 1)
    y += 34 + head_extra
    p.append(Prim('line', 'rule', x=PAD, y=y, x2=width - PAD, y2=y))
    y += 22

    # Walk the two sequences together. A tied row at each shared name, a
    # compressed "n further names" where they diverge — and a single band
    # where they agree for a long stretch, because fourteen consecutive rows
    # all reading "both agree" is not a comparison, it is wallpaper.
    li = ri = 0
    rows_top = y
    k = 0
    while k < len(shared):
        pid = shared[k]
        ln, rn = lseq.index(pid, li), rseq.index(pid, ri)
        gap_l, gap_r = ln - li, rn - ri
        if gap_l or gap_r:
            for x, gap in ((lx, gap_l), (rx, gap_r)):
                if gap:
                    p.append(Prim('text', 'muted', x=x, y=y + 4,
                                  text=ngettext('%d further name',
                                                '%d further names', gap) % gap,
                                  size=13.5, style='italic', anchor='middle',
                                  serif=True))
            if gap_l and gap_r:
                common = set(lseq[li:ln]) & set(rseq[ri:rn])
                p.append(Prim('text', 'omit' if not common else 'muted',
                              x=width / 2, y=y + 4,
                              text=(_('no name in common') if not common
                                    else _('%d shared') % len(common)),
                              size=11.5, anchor='middle', weight='semibold'))
            y += 34

        # How far does an unbroken agreement run from here?
        run = k
        while (run + 1 < len(shared)
               and lseq.index(shared[run + 1], ln) == lseq.index(shared[run], ln) + 1
               and rseq.index(shared[run + 1], rn) == rseq.index(shared[run], rn) + 1):
            run += 1

        y = _tie_row(p, h, lx, rx, width, y, pid, lseq, rseq,
                     lseq.index(pid, li), rseq.index(pid, ri), measure,
                     ledges, redges, left_c, right_c)
        if run - k >= 3:
            last = shared[run]
            n = run - k - 1
            p.append(Prim('band', 'agree', x=lx - 3, y=y - 24, w=6,
                          h=46, r=3))
            p.append(Prim('band', 'agree', x=rx - 3, y=y - 24, w=6,
                          h=46, r=3))
            p.append(Prim('text', 'agree', x=width / 2, y=y - 2,
                          text=ngettext('%d more name in common',
                                        '%d more names in common', n) % n,
                          size=12.5, anchor='middle', weight='semibold'))
            p.append(Prim('text', 'muted', x=width / 2, y=y + 14,
                          text=_ellipsize_names(
                              [gb.person_name(s0)
                               for s0 in shared[k + 1:run]],
                              (rx - lx) - 24, 11.5, measure),
                          size=11.5, anchor='middle', style='italic',
                          serif=True))
            y += 52
            li = lseq.index(last, li) + 1
            ri = rseq.index(last, ri) + 1
            y = _tie_row(p, h, lx, rx, width, y, last, lseq, rseq,
                         lseq.index(last, 0), rseq.index(last, 0), measure,
                         ledges, redges, left_c, right_c)
            k = run + 1
            continue
        li, ri = lseq.index(pid, li) + 1, rseq.index(pid, ri) + 1
        k += 1

    _rail(p, lx, rows_top - 8, y - 30)
    _rail(p, rx, rows_top - 8, y - 30)

    plate = Plate(width, y + 12, p, h,
                  title=_(c['title']), subtitle=_(c['subtitle']))
    plate.alt = '\n'.join([
        _(c['title']),
        _('%(a)s and %(b)s trace the same descent and agree at %(n)d names: '
          '%(who)s. Everywhere else they differ, and this chart does not '
          'resolve the difference.') % {
              'a': _(left_c['passage']), 'b': _(right_c['passage']),
              'n': len(shared),
              'who': ', '.join(gb.person_name(s) for s in shared)}])
    return plate


# ── entry point ────────────────────────────────────────────────────────────

def build(cid: str, measure: Measure = estimate, width: float = 760,
          expanded: set[int] | None = None, tradition: str = '') -> Plate:
    """The plate for a chart, whichever structure it declares."""
    c = gb.chart(cid)
    if c is None:
        return Plate(width, 0)
    if c['structure'] == 'household':
        return household(cid, measure, width)
    if c['structure'] == 'lifespan':
        return lifespan(cid, measure, width, tradition)
    if c['structure'] == 'witnesses':
        return witnesses(cid, measure, width)
    return spine(cid, measure, width, expanded)
