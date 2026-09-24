"""bible_family.py — the data behind The Bible Family Tree.

`data/bible_family/translations.toml` holds every English Bible: its descent,
its sources, and where it sits on the Line, the one track that runs from word
for word (0) to free (1, The Message). This module reads the file and answers
the one question the app asks of it so far: where does an installed module sit
on that track?

A Bible's place comes from the best evidence the file holds for it, in order:

  band      published charts place it; the median of their range.
  measured  Scriptura measured it against the Hebrew and Greek glosses.
  class     only its makers' own description ("formal", "functional" …);
            the middle of that zone, drawn as a bracket, not a point.

A Bible with none of these (or a module the file does not know, such as every
non-English Bible) has no place, and callers keep it out of the ordering.
"""

from __future__ import annotations

import functools
import logging
import os
import tomllib
from typing import NamedTuple

import ebible_bridge
from i18n import _, N_

_log = logging.getLogger('scriptura.bible_family')

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_FILE = os.path.join(_HERE, 'data', 'bible_family', 'translations.toml')

#: What old thee/thou English costs on the measure: the KJV measures 0.34,
#: the KJVs with modern words 0.29–0.30. Taken off every `archaic` Bible's
#: measured figure (decided 2026-09-24).
ARCHAIC_PENALTY = 0.05

#: The four zones of the Line, by upper bound.
ZONES = (
    (0.33, N_('Word for word')),
    (0.66, N_('Between')),
    (0.90, N_('Thought for thought')),
    (float('inf'), N_('Free')),
)

#: A self-described class covers a whole zone. An expanded translation (the
#: Amplified) keeps the source's every sense, so it sits with the literal ones.
_CLASS_SPANS = {
    'formal': (0.0, 0.33),
    'expanded': (0.0, 0.33),
    'intermediate': (0.33, 0.66),
    'functional': (0.66, 0.90),
    'paraphrase': (0.90, 1.0),
}


class Place(NamedTuple):
    kind: str       # 'band' | 'measured' | 'class'
    value: float    # the point to sort by; may pass 1.0 (the free end)
    low: float
    high: float


@functools.cache
def _by_module() -> dict[str, dict]:
    try:
        with open(_DATA_FILE, 'rb') as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        _log.warning('Bible family data unreadable: %s', e)
        return {}
    return {mod: node for node in data.get('node', [])
            for mod in node.get('installable', [])}


def place(module: str) -> Place | None:
    """Where `module` sits on the Line, or None when nothing places it.

    `module` is the app's key: a SWORD name, or an eBible id behind
    `ebible_bridge.PREFIX`. The data file holds bare ids for both."""
    node = _by_module().get(module.removeprefix(ebible_bridge.PREFIX))
    if node is None:
        return None
    sp = node.get('spectrum', {})
    if 'band' in sp:
        low, median, high = sp['band']
        return Place('band', median, low, high)
    if 'measured' in sp:
        v = sp['measured']
        if node.get('archaic'):
            v -= ARCHAIC_PENALTY
        return Place('measured', v, v, v)
    span = _CLASS_SPANS.get(sp.get('class', ''))
    if span is not None:
        return Place('class', (span[0] + span[1]) / 2, *span)
    return None


def zone_label(value: float) -> str:
    """The translated name of the zone `value` falls in."""
    return _(next(name for bound, name in ZONES if value < bound))


def order_by_line(modules: list[str]) -> list[str]:
    """Placed modules from word for word to free, then the rest as given."""
    placed = [(p.value, m) for m in modules if (p := place(m)) is not None]
    placed.sort(key=lambda pm: pm[0])
    rest = [m for m in modules if place(m) is None]
    return [m for _v, m in placed] + rest
