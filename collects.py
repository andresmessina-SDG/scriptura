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


def collect_for(key: str, lang: str = 'en') -> tuple[str, str] | None:
    """(text, source_line) for a church_year designation key
    ("anglican:trinity7"), or None when the pack has nothing for it.

    `lang` is the language the reader is looking at. A tradition may carry
    its texts in more than one, in a sub-table named by the code; English is
    the source language and lives at the top level. The whole triple — text,
    kind and source line — moves together, because a troparion in Church
    Slavonic is not "The Troparion · Hapgood's Service Book, 1906".

    Falling back per key rather than per language: a translated section may
    cover fewer days than the English one, and a reader is better served by
    the English collect on a day their own section is missing than by
    silence. Aliases come from the tradition, not the section — they are
    calendar rubrics, the same in any language.
    """
    tradition, _, sub = key.partition(':')
    data = _pack().get(tradition)
    if not data or not sub:
        return None
    sub = data.get('aliases', {}).get(sub, sub)
    section = data.get(lang)
    if isinstance(section, dict) and section.get('texts', {}).get(sub):
        return (section['texts'][sub],
                f'{section["kind"]} · {section["source"]}')
    text = data.get('texts', {}).get(sub)
    if not text:
        return None
    return text, f'{data["kind"]} · {data["source"]}'
