"""harmony.py — The Harmony of the Gospels, the bundled module.

Robertson's harmony (1922, after Broadus) sets the sections, their order and
their places; the Eusebian canons (INTF) pair passages by what they say. The
data is built and checked by `tools/harmony/build_harmony.py` into
`data/harmony/harmony.json`; this module reads it for the pane page
(`harmony_view`).

Each link has a kind: `same_event` the accounts of one event (Robertson's
section), `same_words` said elsewhere (a Eusebian row outside the section),
`look_alike` a similar event (Robertson's "similar incidents"). References
are KJV-numbered, as the reading view's are.

The section titles and notes are Robertson's, in English; the page's chrome
is translated. No commentary: the page shows the harmony, not a teacher's
reading of it.
"""

from __future__ import annotations

import functools
import html
import json
import logging
import os
import re
from typing import cast

from i18n import N_, _, book_label, ngettext

_log = logging.getLogger('scriptura.harmony')

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_FILE = os.path.join(_HERE, 'data', 'harmony', 'harmony.json')

#: The bundled "module" a pane opens to show the harmony.
MODULE_KEY = 'GospelHarmony'
DISPLAY_NAME = N_('The Harmony of the Gospels')

#: Canonical order, never reshuffled: position names the Gospel.
GOSPELS = ('Matt', 'Mark', 'Luke', 'John')
#: The data's book codes → the app's book names.
BOOK = {'Matt': 'Matthew', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John',
        '1Cor': '1 Corinthians', 'Acts': 'Acts'}

KIND_NAMES = {
    'same_event': N_('Same event'),
    'same_words': N_('Said elsewhere'),
    'look_alike': N_('Similar event'),
    'only_here': N_('Only here'),
}

#: Eusebius's ten tables: which Gospels each pairs.
CANON_GOSPELS = {'I': ('Matt', 'Mark', 'Luke', 'John'),
                 'II': ('Matt', 'Mark', 'Luke'), 'III': ('Matt', 'Luke', 'John'),
                 'IV': ('Matt', 'Mark', 'John'), 'V': ('Matt', 'Luke'),
                 'VI': ('Matt', 'Mark'), 'VII': ('Matt', 'John'),
                 'VIII': ('Mark', 'Luke'), 'IX': ('Luke', 'John'), 'X': ()}

#: Greek function words left out of the shared-words underline: the
#: article, conjunctions, pronouns, prepositions, particles, "be", "say".
STOP = frozenset((
    'G3588 G2532 G1161 G846 G1722 G1519 G1063 G3756 G3361 G3754 G2443 G1510 '
    'G3739 G5037 G235 G1537 G1909 G4314 G575 G1223 G2596 G3326 G5613 G1437 '
    'G5101 G5100 G2228 G3767 G3778 G1565 G1473 G4771 G2249 G5210 G4012 G5259 '
    'G3844 G1487 G3704 G1360 G3825 G3779 G2193 G3752 G3753 G5119 G1492 G2036 '
    'G3004 G2064').split())


@functools.cache
def data() -> dict:
    try:
        with open(_DATA_FILE, encoding='utf-8') as f:
            return cast(dict, json.load(f))
    except (OSError, ValueError) as e:
        _log.warning('Harmony data unreadable: %s', e)
        return {}


def is_harmony_module(name: str) -> bool:
    return name == MODULE_KEY


def module_names() -> list[str]:
    """The bundled module key, if its data file is present."""
    return [MODULE_KEY] if os.path.exists(_DATA_FILE) else []


def display_name(name: str = '') -> str:
    return _(DISPLAY_NAME)


def info() -> dict[str, str]:
    """Metadata for the module picker's info page."""
    n = len(data().get('sections', []))
    return {
        'description': _('The four Gospels side by side: A. T. Robertson’s '
                         'harmony (1922), with the canon tables of Eusebius.'),
        'type': ngettext('{n} section', '{n} sections', n).format(n=n),
        'language': 'en',
    }


# ── sections ─────────────────────────────────────────────────────────────

@functools.cache
def _by_id() -> dict[str, dict]:
    return {s['id']: s for s in data().get('sections', [])}


def section_ids() -> list[str]:
    return [s['id'] for s in data().get('sections', [])]


def section(sid: str) -> dict | None:
    return _by_id().get(sid)


def part_of(sid: str) -> dict | None:
    s = section(sid)
    return next((p for p in data().get('parts', [])
                 if s is not None and p['n'] == s['part']), None)


def gospel_spans(sid: str) -> dict[str, list[dict]]:
    """The section's passages per Gospel, in canonical order."""
    s = section(sid) or {}
    out: dict[str, list[dict]] = {}
    for b in GOSPELS:
        spans = [r for r in s.get('refs', []) if r['book'] == b]
        if spans:
            out[b] = spans
    return out


def other_spans(sid: str) -> list[dict]:
    """Passages outside the Gospels Robertson sets beside it (1 Cor 15, Acts 1)."""
    return [r for r in (section(sid) or {}).get('refs', [])
            if r['book'] not in GOSPELS]


def _key(span: dict, end: bool = False) -> tuple[int, int]:
    c, v = span['end' if end else 'start']
    return c, v


def overlaps(a: dict, b: dict) -> bool:
    return (a['book'] == b['book'] and _key(a) <= _key(b, True)
            and _key(b) <= _key(a, True))


def section_for_verse(book: str, chapter: int, verse: int) -> str | None:
    """The section a Gospel verse (app book name) falls in: the first in
    Robertson's order whose passages hold it, or the one a verse he left
    out is attached to."""
    code = next((c for c, name in BOOK.items() if name == book), None)
    if code not in GOSPELS:
        return None
    here = {'book': code, 'start': [chapter, verse], 'end': [chapter, verse]}
    for s in data().get('sections', []):
        if any(overlaps(r, here) for r in s['refs']):
            return str(s['id'])
    loose = data().get('no_section', {}).get(f'{code} {chapter}:{verse}')
    return loose['attach_to'] if loose else None


# ── references ───────────────────────────────────────────────────────────

def ref_text(span: dict, with_book: bool = True) -> str:
    """'Matthew 14:13–21', in the reader's language; a half verse keeps its
    letter, as Eusebius divides them ('Mark 1:7b–8')."""
    (c, v), (c2, v2) = span['start'], span['end']
    a = f"{c}:{v}{span.get('start_part', '')}"
    if (c, v) == (c2, v2) and span.get('start_part') == span.get('end_part'):
        tail = a
    elif c == c2:
        tail = f"{a}–{v2}{span.get('end_part', '')}"
    else:
        tail = f"{a}–{c2}:{v2}{span.get('end_part', '')}"
    return f"{book_label(BOOK[span['book']])} {tail}" if with_book else tail


def verses_of(span: dict) -> list[tuple[str, int, int]]:
    """Every (app book, chapter, verse) in a span, by KJV counts (the
    default versification)."""
    from sword_bridge import verse_count
    book = BOOK[span['book']]
    (c, v), (c2, v2) = span['start'], span['end']
    out = []
    while (c, v) <= (c2, v2):
        out.append((book, c, v))
        v += 1
        if v > verse_count(book, c):
            c, v = c + 1, 1
    return out


# ── Eusebius ─────────────────────────────────────────────────────────────

@functools.cache
def _eusebius() -> dict[str, dict]:
    return {e['id']: e for e in data().get('eusebius', [])}


def _eus_order(eid: str) -> tuple[int, int]:
    g, n = eid.split('.')
    return int(g), int(n)


def eusebian_sections(sid: str) -> list[str]:
    """Eusebius's sections that overlap this Robertson section."""
    spans = [r for rs in gospel_spans(sid).values() for r in rs]
    return sorted((e['id'] for e in _eusebius().values()
                   if any(overlaps(e['span'], r) for r in spans)),
                  key=_eus_order)


def canon(table: str) -> str:
    """The table as read: the INTF file's one 'I.IV' pairs all four Gospels,
    so it is Canon I."""
    return 'I' if table == 'I.IV' else table


def canons(sid: str) -> list[str]:
    """The tables this section's Eusebian sections stand in, I to X."""
    found = {canon(_eusebius()[e]['table']) for e in eusebian_sections(sid)}
    return [t for t in CANON_GOSPELS if t in found]


def eusebius_rows(sid: str) -> list[dict]:
    """The canon rows that touch this section, for the Eusebius lens: each
    row a Eusebian section with those it is paired with, by Gospel. Rows
    outside the section come in too: that is the lens."""
    rows, seen = [], set()
    for eid in eusebian_sections(sid):
        e = _eusebius()[eid]
        ids = frozenset([eid, *e['assoc']])
        if ids in seen:
            continue
        seen.add(ids)
        cells: dict[str, list[dict]] = {}
        for i in sorted(ids, key=_eus_order):
            x = _eusebius()[i]
            cells.setdefault(x['gospel'], []).append(x)
        rows.append({'table': canon(e['table']), 'raw_table': e['table'],
                     'ids': sorted(ids, key=_eus_order),
                     'cells': {b: cells[b] for b in GOSPELS if b in cells}})
    return rows


# ── links ────────────────────────────────────────────────────────────────

def same_event(sid: str) -> dict | None:
    return next((link for link in data().get('links', [])
                 if link['kind'] == 'same_event' and link.get('section') == sid),
                None)


@functools.cache
def _similar() -> dict[str, dict]:
    return {g['title']: g for g in data().get('similar', [])}


def other_links(sid: str) -> list[dict]:
    """Links from this section to others, one per target and kind: similar
    events first, then said elsewhere; within each, the better witnessed
    first. Eusebius's half-verse pairs to one target merge into one."""
    merged: dict[tuple[str, str], dict] = {}
    for link in data().get('links', []):
        kind = link['kind']
        if kind == 'same_event':
            continue
        if 'passages' in link:
            mine = [i for i, secs in enumerate(link['robertson_sections'])
                    if sid in secs]
            if not mine:
                continue
            for i, p in enumerate(link['passages']):
                if i in mine:
                    continue
                target = ','.join(link['robertson_sections'][i]) or ref_text(p)
                m = merged.setdefault((kind, target), _entry(kind, target))
                if not any(overlaps(p, q) for q in m['spans']):
                    m['spans'].append(p)
                m['witnesses'] |= set(link['witnesses'])
                m['shares_words'] |= link['shares_words']
        elif any(s.split()[0] == sid for s in link['sections']):
            g = _similar().get(link['robertson_group'], {})
            for other in (s.split()[0] for s in link['sections']):
                if other == sid:
                    continue
                m = merged.setdefault((kind, other), _entry(kind, other))
                m['group'] = link['robertson_group']
                m['basis'] = g.get('basis')
                m['quote'] = g.get('quote') or g.get('cite')
                if not m['spans']:
                    m['spans'] = [r for rs in gospel_spans(other).values()
                                  for r in rs]
                m['witnesses'] |= set(link['witnesses'])
                m['shares_words'] |= link['shares_words']
    out = []
    for m in merged.values():
        m['witnesses'] = [w for w in ('eusebius', 'robertson')
                          if w in m['witnesses']]
        first = m['target'].split(',')[0]
        m['section'] = first if section(first) else None
        out.append(m)
    order = {'look_alike': 0, 'same_words': 1}
    return sorted(out, key=lambda m: (order[m['kind']], -len(m['witnesses']),
                                      GOSPELS.index(m['spans'][0]['book']),
                                      _key(m['spans'][0])))


def _entry(kind: str, target: str) -> dict:
    return {'kind': kind, 'target': target, 'spans': [], 'witnesses': set(),
            'shares_words': False}


# ── facts ────────────────────────────────────────────────────────────────

#: Passages whose text is in question, and what to say: (book, start, end,
#: fact). Short facts only; the readings are the Variants chip's to show.
TEXTUAL = (
    ('Mark', (16, 9), (16, 20), N_('Eusebius’s tables end at Mark 16:8.')),
    ('John', (7, 53), (8, 11),
     N_('John 7:53–8:11 is missing from many early Greek manuscripts.')),
)


def facts(sid: str) -> list[tuple[str, tuple[str, int, int] | None]]:
    """One-line facts about the section's text: (fact, the verse whose
    readings the interlinear can show, or None)."""
    out: list[tuple[str, tuple[str, int, int] | None]] = []
    spans = [r for rs in gospel_spans(sid).values() for r in rs]
    for book, a, z, fact in TEXTUAL:
        q = {'book': book, 'start': list(a), 'end': list(z)}
        mine = [r for r in spans if overlaps(q, r)]
        if mine:
            # The first verse in question that this section holds.
            c, v = max(a, min(_key(r) for r in mine))
            out.append((_(fact), (BOOK[book], c, v)))
    for ref, loose in sorted(data().get('no_section', {}).items()):
        if loose['attach_to'] == sid:
            code, cv = ref.split()
            c, v = (int(x) for x in cv.split(':'))
            out.append((_('{ref} is not in the Revised Version Robertson '
                          'printed.').format(
                ref=ref_text({'book': code, 'start': [c, v], 'end': [c, v]})),
                (BOOK[code], c, v)))
    if any(_eusebius()[e]['table'] == 'I.IV' for e in eusebian_sections(sid)):
        out.append((_('The INTF tables give one section here the canon '
                      '“I.IV”, which is not one of Eusebius’s ten; its '
                      'parallels are in all four Gospels, so it is shown '
                      'as Canon I.'), None))
    return out


# ── the pillars ──────────────────────────────────────────────────────────

@functools.cache
def _gospel_index() -> dict[str, tuple[dict[int, int], int]]:
    """Per Gospel: verses before each chapter, and the whole count."""
    from sword_bridge import verse_count
    chapters = {'Matt': 28, 'Mark': 16, 'Luke': 24, 'John': 21}
    out = {}
    for b in GOSPELS:
        before, n = {}, 0
        for c in range(1, chapters[b] + 1):
            before[c] = n
            n += verse_count(BOOK[b], c)
        out[b] = (before, n)
    return out


def place(span: dict) -> tuple[float, float]:
    """Where a passage falls in its Gospel, 0 at the first verse to 1 past
    the last: the pillar's top and foot."""
    before, total = _gospel_index()[span['book']]
    (c, v), (c2, v2) = span['start'], span['end']
    return (before[c] + v - 1) / total, (before[c2] + v2) / total


# ── the words ────────────────────────────────────────────────────────────

_W = re.compile(r'<w\s([^>]*?)(?:/>|>(.*?)</w>)', re.DOTALL)
_STRONG = re.compile(r'strong:G0*(\d+)', re.IGNORECASE)
_DROP = re.compile(r'<note\b.*?</note>|<title\b.*?</title>', re.DOTALL)


def words(markup: str) -> list[tuple[str, frozenset[str]]]:
    """A verse as [(text, Greek Strong's numbers)] in reading order; text
    between tagged words carries none."""
    s = _DROP.sub('', str(markup))
    out: list[tuple[str, frozenset[str]]] = []
    pos = 0

    def plain(raw):
        return html.unescape(re.sub(r'<[^>]+>', '', raw))

    for m in _W.finditer(s):
        if m.start() > pos:
            out.append((plain(s[pos:m.start()]), frozenset()))
        pos = m.end()
        if m.group(2) is None:
            continue           # a Greek word the translation leaves unsaid
        nums = frozenset(f'G{int(n)}' for n in _STRONG.findall(m.group(1)))
        out.append((plain(m.group(2)), nums))
    if pos < len(s):
        out.append((plain(s[pos:]), frozenset()))
    return [(t, n) for t, n in out if t]


def passage(module: str, span: dict) -> list[tuple[int, int, list]]:
    """[(chapter, verse, words)] for a span in `module`, by KJV numbers.
    Safe off the UI thread."""
    import content
    import sword_bridge
    out = []
    chapters: dict[int, dict] = {}
    for book, c, v in verses_of(span):
        if c not in chapters:
            chapters[c] = dict(content.load_chapter(module, book, c))
        want = sword_bridge.map_target_verse(module, book, c, v)
        out.append((c, v, words(chapters[c].get(want, ''))))
    return out


def shared_numbers(columns: list[list[tuple[int, int, list]]]) -> list[set[str]]:
    """Per column, the Strong's numbers another column also uses, function
    words left out: what the underline marks."""
    used = [{n for _c, _v, ws in col for _t, nums in ws for n in nums} - STOP
            for col in columns]
    return [set().union(*(used[j] for j in range(len(columns)) if j != i))
            & used[i] for i in range(len(columns))]
