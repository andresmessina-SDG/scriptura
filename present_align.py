"""Pure reference alignment for presentation, with injected verse mappings.

Project each module's rendered keys into app space before joining the streams.
Keep the original lines so neither many-to-one mappings nor numbered psalm
titles lose text, and the view can still print each translation's own numbers.
"""
from __future__ import annotations
from collections.abc import Callable, Iterable
from typing import NamedTuple


class Projection(NamedTuple):
    verses: list[tuple[int, str]]
    parts: dict[int, list[tuple[int, str]]]
    source_to_app: dict[int, int]
    aliases: dict[int, int]


def project(verses: list[tuple[int, str]],
            to_app: Callable[[int], int],
            to_module: Callable[[int], int],
            app_verses: Iterable[int] | None = None) -> Projection:
    """Re-key rendered lines by equivalent app verse without dropping a line.

    SWORD maps some numbered psalm titles to verse 1 as well as the first
    body verse. The forward mapping identifies the body: leading lines before
    that round-trip anchor belong to the preface (app verse 0). Other
    many-to-one mappings remain together, in source order, on one slide row.
    """
    mapped = [(to_app(v), v, str(html)) for v, html in verses]
    indexes = {v: i for i, (_app, v, _html) in enumerate(mapped)}
    represented = {app for app, _v, _html in mapped if app > 0}
    # Some tables reverse-map a first body verse to 0 even though their forward
    # mapping addresses it correctly (e.g. Synodal Psalm 23). Prefer that known
    # positive reference to treating the body as a superscription.
    targets = {app: to_module(app) for app in (
        app_verses if app_verses is not None else
        range(1, max((max(app, v) for app, v, _h in mapped), default=0) + 1))}
    for app, key in targets.items():
        if app not in represented and key in indexes:
            i = indexes[key]
            old, v, html = mapped[i]
            if old <= 0:
                mapped[i] = (app, v, html)
                represented.add(app)
    first_body = next((i for i, (app, v, _h) in enumerate(mapped)
                       if app > 0 and targets.get(app) == v), None)
    if first_body is not None and mapped[first_body][0] == 1:
        for i in range(first_body):
            app, v, html = mapped[i]
            if app in (0, 1):
                mapped[i] = (0, v, html)
    parts: dict[int, list[tuple[int, str]]] = {}
    source_to_app = {}
    for app, v, html in mapped:
        parts.setdefault(app, []).append((v, html))
        source_to_app[v] = app
    combined = [(app, '<br/>'.join(h for _v, h in parts[app]))
                for app in sorted(parts)]
    # A forward alias is only needed when no source line already carries that
    # reference. This keeps a contradictory forward table from stealing a real
    # verse (Vulgate Psalm 16:11), but records a genuine combined verse such as
    # Synodal Psalm 13's last line, which holds KJV verses 5 and 6.
    aliases = {app: source_to_app[key] for app, key in targets.items()
               if app not in parts and key in source_to_app
               and source_to_app[key] > 0}
    return Projection(combined, parts, source_to_app, aliases)


def coalesce(*projections: Projection) -> tuple[Projection, ...]:
    """Put many-to-one equivalents from either translation on the same row."""
    parents: dict[int, int] = {}

    def root(verse: int) -> int:
        while verse in parents:
            verse = parents[verse]
        return verse

    for projection in projections:
        for app, equivalent in projection.aliases.items():
            a, b = root(app), root(equivalent)
            if a != b:
                parents[max(a, b)] = min(a, b)
    aliases = {app: root(app) for app in parents}
    result = []
    for projection in projections:
        parts: dict[int, list[tuple[int, str]]] = {}
        for app, lines in projection.parts.items():
            parts.setdefault(root(app), []).extend(lines)
        result.append(Projection(
            [(app, '<br/>'.join(h for _v, h in parts[app]))
             for app in sorted(parts)], parts,
            {v: root(app) for v, app in projection.source_to_app.items()}, aliases))
    return tuple(result)


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
