"""Bundled liturgical texts for the Today page epigraph.

`data/collects.toml` carries the collect (or troparion) for each
church_year designation key, curated word-for-word from public-domain /
freely reproducible editions — the pack header names each tradition's
edition and the extraction provenance. With a church calendar chosen, the
day's collect takes the epigraph slot ahead of any devotional module; a
devotional answers when no calendar is chosen, and on the days a chosen
calendar cannot fill.

Each tradition's table: `kind` and `source` (composed into the foot's
source line), `aliases` (engine keys 1662-style rubrics serve with
another day's collect), and `texts` keyed by the designation sub-key.
"""

import functools
import logging
import os
import tomllib
from typing import Any

_log = logging.getLogger('scriptura.collects')

_PACK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'data', 'collects.toml')


@functools.cache
def _pack() -> dict[str, Any]:
    try:
        with open(_PACK_PATH, 'rb') as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        _log.exception('collects pack unreadable: %s', _PACK_PATH)
        return {}


def collect_for(key: str) -> tuple[str, str] | None:
    """(text, source_line) for a church_year designation key
    ("anglican:trinity7"), or None when the pack has nothing for it."""
    tradition, _, sub = key.partition(':')
    data = _pack().get(tradition)
    if not data or not sub:
        return None
    sub = data.get('aliases', {}).get(sub, sub)
    text = data.get('texts', {}).get(sub)
    if not text:
        return None
    return text, f'{data["kind"]} · {data["source"]}'
