"""creeds.py — The Creeds, the bundled module.

The Apostles', Nicene and Athanasian Creeds, each line tied to the verses it
is drawn from. The data is built and checked by `tools/creeds/build_creeds.py`
into `data/creeds/creeds.json`; this module reads it for three callers:

  * `creeds_view` — the pane page (the creed as lines, threads to the Bible);
  * `pane` — `marker_verses()`, for the mark beside a verse whose words a
    creed uses;
  * `window` — `line_for_verse()`, to open the page at that line.

Each link has a kind: `w` the creed uses the verse's words, `t` the verse
teaches what the line says, `f` an Old Testament promise the line sees
fulfilled. References are KJV-numbered, as the reading view's are.

The creed text, notes and verses are English (the 1662 Prayer Book and the
KJV), with the Greek and Latin originals; the page's chrome is translated.
"""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import cast

from i18n import N_, _, ngettext

_log = logging.getLogger('scriptura.creeds')

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_FILE = os.path.join(_HERE, 'data', 'creeds', 'creeds.json')

#: The bundled "module" a pane opens to show The Creeds.
MODULE_KEY = 'TheCreeds'
DISPLAY_NAME = N_('The Creeds')

#: Tab order: the Book of Concord's, which is also shortest to longest.
CREED_IDS = ('apostles', 'nicene', 'athanasian')

TITLES = {
    'apostles': N_("The Apostles' Creed"),
    'nicene': N_('The Nicene Creed'),
    'athanasian': N_('The Athanasian Creed'),
}

#: The reading view's mark, one whole sentence per creed so each language
#: can fit the creed's name to it.
SAID_IN = {
    'apostles': N_("In the Apostles' Creed: “{line}”"),
    'nicene': N_('In the Nicene Creed: “{line}”'),
    'athanasian': N_('In the Athanasian Creed: “{line}”'),
}

#: The section headings the data names, here so the catalogues carry them:
#: the page shows them through _().
SECTION_NAMES = (N_('God the Father'), N_('God the Son'),
                 N_('God the Holy Ghost'), N_('The faith'), N_('The Trinity'),
                 N_('Christ'))

KIND_NAMES = {
    'w': N_('Same words'),
    't': N_('Same teaching'),
    'f': N_('Foretold'),
}


@functools.cache
def data() -> dict:
    try:
        with open(_DATA_FILE, encoding='utf-8') as f:
            return cast(dict, json.load(f))
    except (OSError, ValueError) as e:
        _log.warning('Creeds data unreadable: %s', e)
        return {}


def creed(creed_id: str) -> dict | None:
    for c in data().get('creeds', []):
        if c['id'] == creed_id:
            return cast(dict, c)
    return None


def phrases(creed_id: str) -> list[dict]:
    """Every line of the creed in order; each carries its article number."""
    c = creed(creed_id)
    out = []
    for a in (c or {}).get('articles', []):
        for i, p in enumerate(a['phrases']):
            out.append({**p, 'art': a['n'], 'first': i == 0})
    return out


def is_creeds_module(name: str) -> bool:
    return name == MODULE_KEY


def module_names() -> list[str]:
    """The bundled module key, if its data file is present."""
    return [MODULE_KEY] if os.path.exists(_DATA_FILE) else []


def display_name(name: str = '') -> str:
    return _(DISPLAY_NAME)


def info() -> dict[str, str]:
    """Metadata for the module picker's info page."""
    n = sum(len(p['links']) for c in data().get('creeds', [])
            for a in c['articles'] for p in a['phrases'])
    return {
        'description': _("The Apostles', Nicene and Athanasian Creeds, each "
                         'line drawn to the verses it comes from.'),
        'type': ngettext('{n} link to Scripture', '{n} links to Scripture',
                         n).format(n=n),
        'language': 'en',
    }


@functools.cache
def _same_words() -> dict[tuple[str, int], dict[int, list[tuple[str, str]]]]:
    """(book, chapter) → verse → [(creed id, line id)] for every verse whose
    words a creed uses. A range marks each verse in it."""
    out: dict[tuple[str, int], dict[int, list[tuple[str, str]]]] = {}
    for c in data().get('creeds', []):
        for a in c['articles']:
            for p in a['phrases']:
                for link in p['links']:
                    if link['kind'] != 'w':
                        continue
                    last = link['v']
                    tail = link['ref'].rsplit('-', 1)
                    if len(tail) == 2 and tail[1].isdigit():
                        last = int(tail[1])
                    for v in range(link['v'], last + 1):
                        lines = out.setdefault((link['book'], link['ch']),
                                               {}).setdefault(v, [])
                        if (c['id'], p['id']) not in lines:
                            lines.append((c['id'], p['id']))
    return out


def marker_verses(book: str, chapter: int) -> set[int]:
    """Verses in this chapter whose words a creed uses."""
    return set(_same_words().get((book, chapter), {}))


def mark_tooltip(book: str, chapter: int, verse: int) -> str:
    """What the reading view's mark says: which creed, and the line."""
    found = line_for_verse(book, chapter, verse)
    if found is None:
        return ''
    cid, pid = found
    line = next((p['en'] for p in phrases(cid) if p['id'] == pid), '')
    return _(SAID_IN[cid]).format(line=line.strip().rstrip(',;:.'))


def line_for_verse(book: str, chapter: int, verse: int,
                   prefer: str | None = None) -> tuple[str, str] | None:
    """The creed line that uses this verse's words: in the creed `prefer`
    when it has one, else the first in tab order."""
    lines = _same_words().get((book, chapter), {}).get(verse, [])
    if not lines:
        return None
    for cid, pid in lines:
        if cid == prefer:
            return cid, pid
    return min(lines, key=lambda x: CREED_IDS.index(x[0]))
