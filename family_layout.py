"""family_layout.py — where the Family view puts each Bible.

Pure geometry, no GTK, so it can be tested alone and later write the print
plate from the same numbers the screen uses (like genealogy_layout).

The drawing has its own units: WIDTH across, time running DOWN the page.
Before 1611 the Bibles sit in a small tree above the time axis, placed by
hand in the data like a map label, since nothing can be measured there.
From 1611 each line of descent has a lane, and each Bible sits in its lane at
its year. Lanes run left to right by their Bibles' average place on the Line,
so the "by literalness" arrangement (step 5) moves them as little as it can.

Time is lumpy: one Bible for 270 years, then a flood after 1950. The axis is
compressed where little happened and the drawing says so.
"""

from __future__ import annotations

from typing import NamedTuple

import bible_family

WIDTH = 1180
AXIS_TOP = 440          # y of 1611, where the time axis begins
LANE_LEFT = 120
LANE_RIGHT = 830
NOTE_LEFT = 924         # the margin notes' column
NOTE_WIDTH = WIDTH - NOTE_LEFT - 16      # 240
LAST_YEAR = 2025

#: Year marks on the axis; the century ones are drawn solid.
TICKS = (1611, 1700, 1800, 1880, 1900, 1925, 1950, 1975, 2000, 2025)


def year_y(year: float) -> float:
    """The y of a year. Three rates: slow to 1880, faster to 1950, fastest
    after, where most of the Bibles are."""
    if year <= 1880:
        return AXIS_TOP + (year - 1611) * 0.55
    if year <= 1950:
        return AXIS_TOP + 148 + (year - 1880) * 3
    return AXIS_TOP + 148 + 210 + (year - 1950) * 13


HEIGHT = year_y(LAST_YEAR) + 60


class Lane(NamedTuple):
    name: str
    x: float
    members: tuple[str, ...]


class Edge(NamedTuple):
    parent: str
    child: str
    kind: str           # 'rev' | 'para' | 'drew'


class Note(NamedTuple):
    y: float
    text: str


def lanes() -> list[Lane]:
    """The lanes, ordered by their Bibles' average place on the Line."""
    members = set(bible_family.family_members())

    def mean_place(ids):
        vals = [p.value for i in ids
                if (r := bible_family.node(i)) is not None
                and (p := bible_family.place_of(r)) is not None]
        return sum(vals) / len(vals) if vals else 0.5

    raw = [(lane['name'], tuple(i for i in lane['members'] if i in members))
           for lane in bible_family.family_data().get('lane', [])]
    raw = [(n, ids) for n, ids in raw if ids]
    raw.sort(key=lambda ni: mean_place(ni[1]))
    step = (LANE_RIGHT - LANE_LEFT) / max(1, len(raw) - 1)
    return [Lane(n, LANE_LEFT + i * step, ids)
            for i, (n, ids) in enumerate(raw)]


#: Where a Bible with no place on the Line stands in the "by literalness"
#: arrangement: its own column, past the free end.
NOT_PLACED_X = 880.0

#: A Bible placed as another: the 1611 KJV is placed on the 1769 text, the
#: one readers have (the data's own note on it).
PLACED_AS = {'kjv1611': 'kjv'}


def line_x(value: float) -> float:
    """The x of a place on the Line, across the lanes' width. A Bible past
    the free end is pinned there (decided 7b)."""
    return LANE_LEFT + min(max(value, 0.0), 1.0) * (LANE_RIGHT - LANE_LEFT)


def spot(nid: str):
    """A Family Bible's place on the Line, or None: the root has none."""
    if nid in bible_family.family_data().get('root', {}):
        return None
    record = bible_family.node(PLACED_AS.get(nid, nid))
    return bible_family.place_of(record) if record is not None else None


def positions(arrangement: str = 'family') -> dict[str, tuple[float, float]]:
    """Every Family Bible's (x, y). The root keeps its spot before 1611 in
    both arrangements. After it, 'family' puts each Bible in its lane;
    'line' slides it sideways to its place on the Line (time stays put),
    and a Bible with no place to the column past the free end."""
    root = bible_family.family_data().get('root', {})
    out: dict[str, tuple[float, float]] = {
        i: (float(x), float(y)) for i, (x, y) in root.items()}
    for lane in lanes():
        for i in lane.members:
            if i in out:
                continue
            record = bible_family.node(i)
            assert record is not None       # members come from the data
            y = year_y(record['year'])
            if arrangement == 'line':
                here = spot(i)
                out[i] = (line_x(here.value) if here else NOT_PLACED_X, y)
            else:
                out[i] = (lane.x, y)
    return out


def edges() -> list[Edge]:
    """The lines of descent between Family Bibles."""
    members = set(bible_family.family_members())
    return [Edge(e['from'], e['to'], e['type'])
            for e in bible_family._edges()
            if e['from'] in members and e['to'] in members]


def edge_curve(a: tuple[float, float], b: tuple[float, float]):
    """A curve from parent to child that leaves the parent straight down,
    so a long diagonal (the ASV to the Living Bible, 1901 to 1971) can be
    followed by eye. Returns the four Bézier points."""
    if abs(b[1] - a[1]) < 30:
        # Two Bibles on one row (Coverdale and Matthew's): a straight line
        # would run through the first one's label like a strike-through,
        # so the curve dips below the row and comes back up.
        dip = max(a[1], b[1]) + 34
        return (a, (a[0], dip), (b[0], dip), b)
    mid = (a[1] + b[1]) / 2
    return (a, (a[0], mid), (b[0], mid), b)


def notes() -> list[Note]:
    return [Note(year_y(n['year']), n['text'])
            for n in bible_family.family_data().get('note', [])]


def label_left(x: float, root: bool = False) -> bool:
    """Labels near the right edge run leftward, clear of the notes. The
    root's never do: nothing sits beside them, and Douay–Rheims's ran back
    into the Geneva Bible's."""
    return x > 700 and not root
