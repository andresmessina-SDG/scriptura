"""Pure verse-number alignment for bilingual (parallel) presentation.

No GTK: given two ``[(verse, html), …]`` chapter streams — the primary and the
secondary pane — this outer-joins them by verse number into aligned rows the
present view lays out side by side. Verse-number join is the app's reference
granularity (see sword_bridge's chapter-level versification mapping); this makes
no attempt at cross-versification verse remapping. Kept pure so it is
unit-testable headlessly, mirroring present_paging.
"""
from __future__ import annotations


def align(a: list[tuple[int, str]],
          b: list[tuple[int, str]]) -> list[tuple[int, str | None, str | None]]:
    """Outer-join two verse streams by verse number.

    Returns ``[(verse, html_a, html_b), …]`` ordered by verse number, where a
    side missing that verse is ``None``. When a verse number repeats within a
    stream (it shouldn't inside one chapter) the first occurrence wins, so a row
    is never silently dropped.
    """
    map_a: dict[int, str] = {}
    for v, h in a:
        map_a.setdefault(v, h)
    map_b: dict[int, str] = {}
    for v, h in b:
        map_b.setdefault(v, h)
    verses = sorted(set(map_a) | set(map_b))
    return [(v, map_a.get(v), map_b.get(v)) for v in verses]
