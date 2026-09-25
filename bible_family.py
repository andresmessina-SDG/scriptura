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
import re
import tomllib
import unicodedata
from urllib.parse import quote
from typing import NamedTuple

import ebible_bridge
from i18n import _, N_, ngettext

_log = logging.getLogger('scriptura.bible_family')

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_FILE = os.path.join(_HERE, 'data', 'bible_family', 'translations.toml')

#: The bundled "module" a pane opens to show The Bible Family Tree, the way
#: it opens The Book of Generations.
MODULE_KEY = 'BibleFamilyTree'
DISPLAY_NAME = N_('The Bible Family Tree')

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
def _data() -> dict:
    try:
        with open(_DATA_FILE, 'rb') as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        _log.warning('Bible family data unreadable: %s', e)
        return {}


@functools.cache
def _by_id() -> dict[str, dict]:
    return {n['id']: n for n in _data().get('node', [])}


@functools.cache
def _by_module() -> dict[str, dict]:
    return {mod: node for node in _data().get('node', [])
            for mod in node.get('installable', [])}


def node(node_id: str) -> dict | None:
    """One Bible's record from the data file, by its id."""
    return _by_id().get(node_id)


def node_for_module(module: str) -> dict | None:
    """The Bible an installed module is a text of, or None.

    `module` is the app's key: a SWORD name, or an eBible id behind
    `ebible_bridge.PREFIX`. The data file holds bare ids for both."""
    return _by_module().get(module.removeprefix(ebible_bridge.PREFIX))


def installed_module(node_id: str, installed: list[str]) -> str | None:
    """The first of `installed` (app keys) that is a text of this Bible."""
    return next((m for m in installed
                 if (n := node_for_module(m)) is not None
                 and n['id'] == node_id), None)


def place_of(record: dict) -> Place | None:
    """Where a Bible's record sits on the Line, or None."""
    sp = record.get('spectrum', {})
    if 'band' in sp:
        low, median, high = sp['band']
        return Place('band', median, low, high)
    if 'measured' in sp:
        v = sp['measured']
        if record.get('archaic'):
            v -= ARCHAIC_PENALTY
        return Place('measured', v, v, v)
    span = _CLASS_SPANS.get(sp.get('class', ''))
    if span is not None:
        return Place('class', (span[0] + span[1]) / 2, *span)
    return None


def place(module: str) -> Place | None:
    """Where the installed `module` sits on the Line, or None."""
    record = node_for_module(module)
    return place_of(record) if record is not None else None


def zone_label(value: float) -> str:
    """The translated name of the zone `value` falls in."""
    return _(next(name for bound, name in ZONES if value < bound))


def order_by_line(modules: list[str]) -> list[str]:
    """Placed modules from word for word to free, then the rest as given."""
    placed = [(p.value, m) for m in modules if (p := place(m)) is not None]
    placed.sort(key=lambda pm: pm[0])
    rest = [m for m in modules if place(m) is None]
    return [m for _v, m in placed] + rest


# ── descent ───────────────────────────────────────────────────────────────
#
# Edge kinds: 'rev' a revision of, 'para' reworded from (an English Bible,
# §9d), 'drew' drew on — a secondary debt, never the main line.

def _edges() -> list[dict]:
    edges: list[dict] = _data().get('edge', [])
    return edges


def descent(node_id: str) -> list[tuple[dict, str | None]]:
    """The main line back to the root: [(this Bible, None), (its parent,
    'rev' | 'para'), …]. Where a Bible has two parents (Matthew's Bible,
    the NIV 2011) the first in the file is the main line; the other is
    listed by `drew_on`."""
    path: list[tuple[dict, str | None]] = []
    seen = set()
    cur, rel = node(node_id), None
    while cur is not None and cur['id'] not in seen:
        seen.add(cur['id'])
        path.append((cur, rel))
        up = next((e for e in _edges()
                   if e['to'] == cur['id'] and e['type'] != 'drew'), None)
        cur, rel = (node(up['from']), up['type']) if up else (None, None)
    return path


def drew_on(node_id: str) -> list[dict]:
    """Every other Bible this one owes something to: its 'drew on' debts,
    and any second parent the main line passed over."""
    main = descent(node_id)
    parent = main[1][0]['id'] if len(main) > 1 else None
    return [n for e in _edges()
            if e['to'] == node_id and e['from'] != parent
            and (n := node(e['from'])) is not None]


def descendants(node_id: str) -> list[dict]:
    """The Bibles that revise, reword or draw on this one."""
    return [n for e in _edges()
            if e['from'] == node_id and (n := node(e['to'])) is not None]


def neighbours(node_id: str) -> tuple[dict | None, dict | None]:
    """The nearest Bibles either side on the Line that published charts
    place — the ones a reader is likely to know. (None, None) when this
    Bible has no point of its own: no place, or only its makers' word for
    a whole zone, whose middle is not a position to stand next to."""
    me = node(node_id)
    here = place_of(me) if me else None
    if here is None or here.kind == 'class':
        return None, None
    charted = [(p.value, n) for n in _data().get('node', [])
               if n['id'] != node_id and (p := place_of(n)) is not None
               and p.kind == 'band']
    below = [pn for pn in charted if pn[0] <= here.value]
    above = [pn for pn in charted if pn[0] > here.value]
    return (max(below, key=lambda pn: pn[0])[1] if below else None,
            min(above, key=lambda pn: pn[0])[1] if above else None)


# ── words for the Card ────────────────────────────────────────────────────

BASE_TEXTS = {
    'MT': N_('the Masoretic Text (Hebrew)'),
    'LXX': N_('the Septuagint (Greek)'),
    'VUL': N_('the Latin Vulgate'),
    'TR': N_('the Textus Receptus (Greek)'),
    'MAJ': N_('the Majority or Byzantine text (Greek)'),
    'CT': N_('the critical text (Nestle-Aland and UBS Greek)'),
    'ENG': N_('an earlier English Bible, reworded'),
    'SPA': N_('a Spanish Bible'),
    'MIX': N_('an eclectic text, chosen reading by reading'),
    'SYR': N_('the Syriac Peshitta'),
}

TRADITIONS = {
    'protestant': N_('Protestant'), 'catholic': N_('Catholic'),
    'catholic-era': N_('Before the Reformation'),
    'orthodox': N_('Eastern Orthodox'), 'jewish': N_('Jewish'),
    'messianic': N_('Messianic Jewish'), 'ecumenical': N_('Ecumenical'),
    'baptist': N_('Baptist'), 'lutheran': N_('Lutheran'),
    'anglican': N_('Anglican'), 'brethren': N_('Brethren'),
    'unitarian': N_('Unitarian'), 'charismatic': N_('Charismatic'),
    'other': N_('Other traditions'),
}

SCOPES = {
    'bible': N_('Whole Bible'), 'nt': N_('New Testament'),
    'ot': N_('Old Testament'), 'partial': N_('Part of the Bible'),
}

CONFIDENCE = {
    'checked': N_('Two sources agree on these facts.'),
    'reference': N_('These facts rest on one standard source.'),
    'disputed': N_('Sources disagree on some of these facts.'),
}

_WIKI = 'https://en.wikipedia.org/wiki/'
_CROSSWIRE = 'https://www.crosswire.org/sword/modules/ModInfo.jsp?modName='


def source(key: str) -> tuple[str, str | None]:
    """A citation key as (label, URL or None). Labels are English, like the
    facts they stand behind."""
    named = _data().get('source', {})
    if key in named:
        text = named[key]
        url, _sep, rest = text.partition(' ')
        if url.startswith('http'):
            if url.startswith(_WIKI):
                title = url[len(_WIKI):].replace('_', ' ')
                return f'Wikipedia: {title}', url
            host = url.split('/')[2].removeprefix('www.')
            return host, url
        return text.split(' — ')[0], None
    kind, _sep, arg = key.partition(':')
    if kind == 'wp':
        title = _data().get('wikipedia', {}).get(arg)
        if title:
            return (f'Wikipedia: {title}',
                    _WIKI + quote(title.replace(' ', '_'), safe="'(),_"))
        return f'Wikipedia ({arg})', None
    if kind == 'conf':
        return f'CrossWire: {arg}', _CROSSWIRE + arg
    if kind == 'bg':
        return f'Bible Gateway: {arg}', None
    if kind == 'br':
        return f'bible-researcher.com ({arg})', None
    return key, None


# ── the pane's module ─────────────────────────────────────────────────────

def is_family_module(name: str) -> bool:
    return name == MODULE_KEY


def module_names() -> list[str]:
    """The bundled module key, if its data file is present."""
    return [MODULE_KEY] if os.path.exists(_DATA_FILE) else []


def display_name(name: str = '') -> str:
    return _(DISPLAY_NAME)


def info() -> dict[str, str]:
    """Metadata for the module picker's info page."""
    n = sum(1 for r in _data().get('node', [])
            if r.get('kind', 'translation') == 'translation')
    return {
        'description': _('Every English Bible on one line from word for word '
                         'to free, and the family each one comes from.'),
        'type': ngettext('{n} English Bible', '{n} English Bibles',
                         n).format(n=n),
        'language': 'en',
    }


# ── filters for the Line ──────────────────────────────────────────────────
#
# Seven tradition chips (decided 2026-09-24). The data keeps the finer tag
# for the Card; the chip is the family it belongs to. Historic Protestant
# is kept apart from Pentecostal and Charismatic, at his asking; the
# Restoration Movement and Wycliffe count as Protestant, his rulings.

TRADITION_CHIPS = (
    ('protestant', N_('Protestant')),
    ('pentecostal', N_('Pentecostal & Charismatic')),
    ('catholic', N_('Catholic')),
    ('orthodox', N_('Eastern Orthodox')),
    ('ecumenical', N_('Ecumenical')),
    ('jewish', N_('Jewish & Messianic')),
    ('other', N_('Other groups')),
)

_CHIP_OF_TRADITION = {
    'protestant': 'protestant', 'baptist': 'protestant',
    'lutheran': 'protestant', 'anglican': 'protestant',
    'brethren': 'protestant', 'catholic-era': 'protestant',
    'charismatic': 'pentecostal',
    'catholic': 'catholic', 'orthodox': 'orthodox',
    'ecumenical': 'ecumenical',
    'jewish': 'jewish', 'messianic': 'jewish',
    'unitarian': 'other', 'other': 'other',
}


def tradition_chip(record: dict) -> str:
    """The tradition chip a Bible is filtered under."""
    return _CHIP_OF_TRADITION[record['tradition']]


#: Eras by first year, and the label each shows.
ERAS = (
    (0, 1610, N_('Before 1611')),
    (1611, 1899, N_('1611–1899')),
    (1900, 1969, N_('1900–1969')),
    (1970, 9999, N_('1970 on')),
)


def _fold(text: str) -> str:
    """Lower case, no accents, punctuation as spaces: 'Douay–Rheims'
    and 'douay rheims' fold alike."""
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^\w]+', ' ', text).split())


def matches(record: dict, query: str) -> bool:
    """Whether every word of `query` is in the Bible's name, abbreviation,
    year or one of its editions ('nasb 1995', 'douay', 'kjv 1611')."""
    words = _fold(query).split()
    if not words:
        return True
    hay = ' '.join(_fold(str(part)) for part in (
        record.get('name', ''), record.get('abbr', ''),
        record.get('year', ''), record.get('year_label', ''),
        *record.get('editions', [])))
    return all(word in hay for word in words)


def era(record: dict) -> int:
    """The index into ERAS of the era a Bible belongs to."""
    return next(i for i, (lo, hi, _label) in enumerate(ERAS)
                if lo <= record['year'] <= hi)


def translations() -> list[dict]:
    """Every English Bible in the data, in file order (no source texts)."""
    return [r for r in _data().get('node', [])
            if r.get('kind', 'translation') == 'translation']


# ── the Family view ───────────────────────────────────────────────────────

def family_members() -> list[str]:
    """The Bibles the Family draws: every Bible read today or needed as a
    landmark, and every Bible they revise or reword, back to the root. A
    rule, not a list: change who is read and the Family follows. 'Drew on'
    debts do not pull a Bible in; they are secondary (§5.3)."""
    seeds = [r['id'] for r in translations()
             if r.get('read') or r.get('landmark')]
    members = set(seeds)
    stack = list(seeds)
    while stack:
        here = stack.pop()
        for e in _edges():
            if (e['to'] == here and e['type'] in ('rev', 'para')
                    and e['from'] not in members):
                members.add(e['from'])
                stack.append(e['from'])
    return sorted(members, key=lambda i: (_by_id()[i]['year'], i))


def family_data() -> dict:
    """The Family view's hand-set parts: lanes, the pre-1611 root, notes."""
    fam: dict = _data().get('family', {})
    return fam


def why_in_family(record: dict) -> str:
    """Why a Bible is in the Family, in the data's own (English) words."""
    return record.get('read') or record.get('landmark') or ''
