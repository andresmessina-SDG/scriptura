"""genealogy_bridge.py — the bundled "Book of Generations" module.

A curated table of biblical descent, shipped *inside* the app the way the
archaeology gallery is (not a download-on-demand pack). Every edge carries the
verse it comes from, so any line the app draws can be checked against the text
the reader has open.

Three things read this module:

  * `genealogy_reader` — the standalone pane, a document of drawn charts.
  * `genealogy_layout` — turns a chart id into geometry, for both the live
    widget and the static SVG plates (`tools/gen_genealogy.py`).
  * `pane` — `marker_verses()` for the per-verse markers, and
    `fragment_for()` for the compact answer inside the double-click peek.

**On translation.** Everything a reader sees here is a msgid. Person names go
through a `person` gettext context, because several are also book names (Ruth,
Judges) and one word cannot be both without the two translations fighting.
Verse references are rebuilt from a canonical English book name at display
time via `i18n.book_label`, which is the app's existing dual-role key — so
citations localise for free and the stored key never moves.

The msgids live in a TOML file, which xgettext cannot read. `tools/
gen_genealogy_strings.py` mirrors them into `genealogy_strings.py` (which IS
in POTFILES.in); `tests/test_genealogy_i18n.py` fails when the two drift.
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from typing import TypedDict

from i18n import _, C_, N_, book_label

_log = logging.getLogger('scriptura.genealogy')

#: Internal key; the display name is curated and translated.
MODULE_KEY = 'BookOfGenerations'
DISPLAY_NAME = N_('The Book of Generations')

_HERE = os.path.dirname(os.path.abspath(__file__))
# Co-located with the python modules in dev and in the meson install tree,
# same arrangement as archaeology_bridge and styles.py.
_DATA_DIR = os.path.join(_HERE, 'data', 'genealogy')
_DOC_FILE = os.path.join(_DATA_DIR, 'genealogy.toml')

#: Edge kinds, and what each means for a drawing.
#:
#:   son       — "A begat B", drawn solid.
#:   descends  — B descends from A with generations left out by the writer.
#:               Drawn dashed, and NEVER expandable: the names are not in this
#:               list. `omits` counts them, `cross` cites who does name them.
#:   born_of   — Matthew's own break of his grammar at Matt 1:16.
#:   husband   — a marriage, not a descent. Drawn sideways, never down.
#:   supposed  — Luke 3:23's "as was supposed". Drawn with the qualifier.
#:   of_god    — Luke 3:38's last step. A claim, not a link; drawn as a
#:               terminus so it cannot read as one more father.
DESCENT_KINDS = ('son', 'descends', 'born_of', 'supposed')
KIND_LABELS = {
    'son': N_('son of'),
    'descends': N_('descended from'),
    'born_of': N_('born of'),
    'husband': N_('husband of'),
    'supposed': N_('son, as was supposed, of'),
    'of_god': N_('of God'),
}


class Ref(TypedDict):
    book: str
    chapter: int
    verse: int


class Person(TypedDict):
    id: str
    name: str          # msgid, canonical English surface form
    meaning: str
    note: str
    also: list[str]    # other surface forms the same person is called


class Edge(TypedDict):
    parent: str
    child: str
    ref: Ref
    kind: str
    omits: int
    cross: str
    mother: str
    note: str


class Reading(TypedDict):
    chart: str
    title: str
    body: str
    attribution: str
    caveat: str


class Lifespan(TypedDict):
    person: str
    tradition: str
    begat: int         # age when the next in line was born
    total: int         # years lived
    ref: Ref
    death_ref: Ref | None


class Chart(TypedDict):
    id: str
    structure: str     # spine | household | lifespan | witnesses
    title: str
    subtitle: str
    intro: str
    passage: str
    passage_b: str
    root: str
    leaf: str
    register: bool
    tradition: str
    companion: str
    left: str
    right: str


class Document(TypedDict):
    title: str
    subtitle: str
    body: str
    people: dict[str, Person]
    edges: list[Edge]
    charts: list[Chart]
    readings: list[Reading]
    lifespans: list[Lifespan]


_doc: Document | None = None

#: `Genesis 5:3` / `1 Chronicles 3:11-12` → book, chapter, verse. The book name
#: keeps its English spelling as the key (window.BOOKS is the canonical list);
#: only `ref_label` translates it.
_REF_RE = re.compile(r'^(.+?)\s+(\d+):(\d+)(?:-\d+)?$')


def parse_ref(text: str) -> Ref | None:
    m = _REF_RE.match(text.strip())
    if not m:
        _log.warning('unparsable reference %r', text)
        return None
    return {'book': m.group(1), 'chapter': int(m.group(2)),
            'verse': int(m.group(3))}


def ref_label(ref: Ref) -> str:
    """`Genesis 5:3` in the reader's language.

    Only the book name is translated; the numerals are the same everywhere the
    app runs, and `book_label` is the same dual-role key the rest of the app
    already localises through."""
    return '%s %d:%d' % (book_label(ref['book']), ref['chapter'], ref['verse'])


def cross_label(text: str) -> str:
    """`1 Chronicles 3:11–12` in the reader's language, range and all.

    `ref_label` speaks a parsed `Ref`, which holds one verse, so putting a
    cross-citation through it silently dropped the second half of every range
    — and putting the raw string on the chart left "1 Chronicles" in English
    beside a chip that said "Mateo". Only the book name is translated; the
    rest is the curator's own text, including whichever dash they typed.
    """
    m = re.match(r'^(.+?)(\s+\d.*)$', text.strip())
    if not m:
        return book_label(text.strip())
    return book_label(m.group(1)) + m.group(2)


def is_genealogy_module(name: str) -> bool:
    return name == MODULE_KEY


def module_names() -> list[str]:
    """The bundled module key, if its data file is present."""
    return [MODULE_KEY] if os.path.exists(_DOC_FILE) else []


def display_name(name: str = '') -> str:
    return _(DISPLAY_NAME)


def person_name(pid: str) -> str:
    """The reader's-language name for a person.

    A `person` context, because several of these are also book names — Ruth
    the woman and Ruth the book need different words in Spanish
    (`Rut` either way) but not in every language, and one msgid could not
    carry both roles safely."""
    p = document()['people'].get(pid)
    return C_('person', p['name']) if p else pid


def kind_label(kind: str) -> str:
    return _(KIND_LABELS.get(kind, KIND_LABELS['son']))


def document() -> Document:
    """The parsed table, cached after first load."""
    global _doc
    if _doc is not None:
        return _doc

    with open(_DOC_FILE, 'rb') as f:
        raw = tomllib.load(f)

    people: dict[str, Person] = {}
    for p in raw.get('person', []):
        people[p['id']] = {
            'id': p['id'], 'name': p['name'],
            'meaning': p.get('meaning', ''), 'note': p.get('note', ''),
            'also': list(p.get('also', [])),
        }

    edges: list[Edge] = []
    for e in raw.get('edge', []):
        ref = parse_ref(e['ref'])
        if ref is None:
            continue
        for end in ('parent', 'child'):
            if e[end] not in people:
                _log.warning('edge %s references unknown person %r',
                             e['ref'], e[end])
        edges.append({
            'parent': e['parent'], 'child': e['child'], 'ref': ref,
            'kind': e.get('kind', 'son'), 'omits': int(e.get('omits', 0)),
            'cross': e.get('cross', ''), 'mother': e.get('mother', ''),
            'note': e.get('note', ''),
        })

    charts: list[Chart] = [{
        'id': c['id'], 'structure': c['structure'], 'title': c['title'],
        'subtitle': c.get('subtitle', ''), 'intro': c.get('intro', ''),
        'passage': c.get('passage', ''), 'passage_b': c.get('passage_b', ''),
        'root': c.get('root', ''), 'leaf': c.get('leaf', ''),
        'register': bool(c.get('register', False)),
        'tradition': c.get('tradition', 'mt'),
        'companion': c.get('companion', ''),
        'left': c.get('left', ''), 'right': c.get('right', ''),
    } for c in raw.get('chart', [])]

    readings: list[Reading] = [{
        'chart': r['chart'], 'title': r['title'], 'body': r['body'],
        'attribution': r.get('attribution', ''), 'caveat': r.get('caveat', ''),
    } for r in raw.get('reading', [])]

    lifespans: list[Lifespan] = []
    for ls in raw.get('lifespan', []):
        ref = parse_ref(ls['ref'])
        if ref is None:
            continue
        death = parse_ref(ls['death_ref']) if ls.get('death_ref') else None
        lifespans.append({
            'person': ls['person'], 'tradition': ls.get('tradition', 'mt'),
            'begat': int(ls['begat']), 'total': int(ls['total']),
            'ref': ref, 'death_ref': death,
        })

    meta = raw.get('meta', {})
    _doc = {
        'title': meta.get('title', DISPLAY_NAME),
        'subtitle': meta.get('subtitle', ''),
        'body': meta.get('body', '').strip(),
        'people': people, 'edges': edges, 'charts': charts,
        'readings': readings, 'lifespans': lifespans,
    }
    return _doc


# ── indexes ────────────────────────────────────────────────────────────────

_by_parent: dict[str, list[Edge]] | None = None
_by_child: dict[str, list[Edge]] | None = None
_by_surface: dict[str, list[str]] | None = None
_verse_index: dict[tuple[str, int, int], list[str]] | None = None


def _build_indexes() -> None:
    global _by_parent, _by_child, _by_surface, _verse_index
    doc = document()
    parents: dict[str, list[Edge]] = {}
    children: dict[str, list[Edge]] = {}
    verses: dict[tuple[str, int, int], list[str]] = {}
    for e in doc['edges']:
        parents.setdefault(e['parent'], []).append(e)
        children.setdefault(e['child'], []).append(e)
        key = (e['ref']['book'], e['ref']['chapter'], e['ref']['verse'])
        bucket = verses.setdefault(key, [])
        # A verse names both ends of the edge it states, plus any mother the
        # verse attaches ("Salmon begat Booz of Rachab" names three people).
        for pid in (e['parent'], e['child'], e['mother']):
            if pid and pid not in bucket:
                bucket.append(pid)

    # Surface form → the people who bear it, folded for lookup. Deliberately
    # many-to-many: "Jacob" is the patriarch AND the father of Joseph in
    # Matt 1:15, and picking one silently is the bug this index exists to
    # avoid. Callers disambiguate on the verse.
    surface: dict[str, list[str]] = {}
    for pid, p in doc['people'].items():
        for form in [p['name'], *p['also']]:
            surface.setdefault(_fold(form), []).append(pid)

    _by_parent, _by_child, _by_surface, _verse_index = \
        parents, children, surface, verses


def _fold(word: str) -> str:
    """Lookup key for a surface name: case- and accent-insensitive.

    Spanish writes `Judá` and `JUDÁ`, and the Spanish dictionary build already
    paid for a split accent that lost 826 occurrences of exactly this word —
    so the fold is NFD-based rather than a lowercase() that leaves the accent
    attached to whichever codepoint the source happened to use."""
    import unicodedata
    n = unicodedata.normalize('NFD', word.strip().lower())
    return ''.join(c for c in n if not unicodedata.combining(c))


def parents_of(pid: str) -> list[Edge]:
    if _by_child is None:
        _build_indexes()
    assert _by_child is not None
    return [e for e in _by_child.get(pid, []) if e['kind'] != 'husband']


def children_of(pid: str) -> list[Edge]:
    if _by_parent is None:
        _build_indexes()
    assert _by_parent is not None
    return [e for e in _by_parent.get(pid, []) if e['kind'] != 'husband']


def verses_with_people(book: str, chapter: int) -> set[int]:
    """Verse numbers in this chapter that the curated table draws a line from.

    Mirrors `archaeology_bridge.verses_with_artifacts` exactly, so the pane's
    marker pipeline treats the two the same way. Per the design note: the
    marker goes on the VERSE, never on each name — in Genesis 5 or Matthew 1
    a mark per name marks every line, which is noise."""
    if _verse_index is None:
        _build_indexes()
    assert _verse_index is not None
    return {v for (b, c, v) in _verse_index if b == book and c == chapter}


#: More markers than this in one chapter and they stop being a cue. An
#: absolute cap, not a share of the chapter: Genesis 5 puts a reference in ten
#: of its thirty-two verses, which is only 31% and still one mark every third
#: line. What makes a marker read as a marker is that it is rare on the page,
#: not that it is rare relative to the chapter's length.
_MARKER_MAX = 3


def marker_verses(book: str, chapter: int) -> set[int]:
    """Which verses actually get a marker drawn beside them.

    In most of the Bible a genealogy reference is rare and a small mark beside
    the verse reads as a quiet cue, exactly like the artifact marker. In a
    genealogy chapter it is the opposite: Matthew 1 would carry fifteen of
    them and Genesis 5 ten, one on nearly every line, which marks nothing.

    So a dense chapter gets a single marker on its first qualifying verse —
    one chapter-level way in, rather than a mark per name. This is the same
    conclusion the design reached for the names themselves."""
    hits = verses_with_people(book, chapter)
    if len(hits) > _MARKER_MAX:
        return {min(hits)}
    return hits


def people_in_verse(book: str, chapter: int, verse: int) -> list[str]:
    """Everyone the curated table draws from this one verse."""
    if _verse_index is None:
        _build_indexes()
    assert _verse_index is not None
    return list(_verse_index.get((book, chapter, verse), []))


def resolve(surface: str, book: str = '', chapter: int = 0,
            verse: int = 0) -> list[str]:
    """Who is meant by this word here — best candidates first.

    One name covers many people, so the verse does the disambiguating: a
    candidate that the table actually draws from THIS verse wins over one that
    merely shares the spelling. When the verse settles nothing, every
    candidate comes back and the caller offers the choice. Never silently
    picks a Zechariah."""
    if _by_surface is None:
        _build_indexes()
    assert _by_surface is not None
    candidates = list(_by_surface.get(_fold(surface), []))
    if not candidates:
        return []
    if not book:
        return candidates
    here = set(people_in_verse(book, chapter, verse))
    if not here:
        # Nothing from this exact verse; widen to the chapter before giving up,
        # which is what a reader means by "this Jacob" in a genealogy chapter.
        here = {pid for v in verses_with_people(book, chapter)
                for pid in people_in_verse(book, chapter, v)}
    return sorted(candidates, key=lambda pid: pid not in here)


# ── the double-click peek fragment ─────────────────────────────────────────

class Fragment(TypedDict):
    id: str
    name: str
    meaning: str
    note: str
    parents: list[tuple[str, str, str]]    # (id, name, ref label)
    mother: tuple[str, str] | None         # (id, name)
    children: list[tuple[str, str, str]]
    ambiguous: list[tuple[str, str]]       # other people with this name
    chart: str                             # chart id to open in full


def fragment_for(surface: str, book: str = '', chapter: int = 0,
                 verse: int = 0) -> Fragment | None:
    """The compact answer for the double-click peek: parents, the person,
    children — the question "who were their parents and offspring", answered
    in place.

    Deliberately text, not a drawing. The peek is a 260–360px popover with the
    body capped between 140 and 320px; a chart does not fit in that and would
    change the popover's natural height, which is what keeps the arrow from
    flipping to the wrong edge of the word."""
    hits = resolve(surface, book, chapter, verse)
    if not hits:
        return None
    pid = hits[0]
    doc = document()
    p = doc['people'].get(pid)
    if p is None:
        return None

    def _rows(edges: list[Edge], end: str) -> list[tuple[str, str, str]]:
        # One row per PERSON, not per edge. Boaz is Salmon's son in Ruth 4,
        # Matthew 1 and Luke 3; three rows saying "Salmon" would fill the peek
        # with the same answer three times. The citations gather onto the one
        # row instead, and the reading book leads so the verse the reader is
        # looking at is the first one offered.
        order: list[str] = []
        refs: dict[str, list[str]] = {}
        for e in edges:
            other = e[end]                      # type: ignore[literal-required]
            if other not in refs:
                order.append(other)
                refs[other] = []
            label = ref_label(e['ref'])
            if label not in refs[other]:
                if book and e['ref']['book'] == book:
                    refs[other].insert(0, label)
                else:
                    refs[other].append(label)
        return [(o, person_name(o), ' · '.join(refs[o])) for o in order]

    parents = _rows(parents_of(pid), 'parent')
    mother = None
    for e in parents_of(pid):
        if e['mother']:
            mother = (e['mother'], person_name(e['mother']))
            break
    children = _rows(children_of(pid), 'child')

    return {
        'id': pid,
        'name': person_name(pid),
        'meaning': _(p['meaning']) if p['meaning'] else '',
        'note': _(p['note']) if p['note'] else '',
        'parents': parents, 'mother': mother, 'children': children,
        'ambiguous': [(o, person_name(o)) for o in hits[1:]],
        'chart': chart_containing(pid, book),
    }


_chart_people: dict[str, set[str]] | None = None


def chart_people(cid: str) -> set[str]:
    """Everyone actually drawn on this chart.

    Membership, not book-matching. Judah is cited from Genesis and so is the
    Adam-to-Noah chain, but Judah is not on it — a chart offered on the
    strength of a shared book name sends the reader to a drawing their person
    does not appear in."""
    global _chart_people
    if _chart_people is None:
        built: dict[str, set[str]] = {}
        for c in document()['charts']:
            who: set[str] = set()
            book = passage_book(c['passage'])
            if c['structure'] == 'household':
                who.add(c['root'])
                for e in children_of(c['root']):
                    if e['ref']['book'] != book:
                        continue
                    who.add(e['child'])
                    if e['mother']:
                        who.add(e['mother'])
            elif c['structure'] == 'lifespan':
                who = {ls['person'] for ls in document()['lifespans']}
            elif c['structure'] == 'witnesses':
                # The two sides are the charts it compares. `built` fills in
                # declaration order, so a witnesses chart that named a chart
                # declared after it comes back empty rather than wrong — and
                # never re-enters this function, which is what a recursive
                # lookup here did.
                for side in (c['left'], c['right']):
                    who |= built.get(side, set())
            else:
                for e in chain(c['root'], c['leaf'], book):
                    who.add(e['parent'])
                    who.add(e['child'])
                    if e['mother']:
                        who.add(e['mother'])
            built[c['id']] = who
        _chart_people = built
    return _chart_people.get(cid, set())


def chart_containing(pid: str, book: str = '') -> str:
    """The chart that best shows this person.

    `book` is the book the reader is currently in, and it wins: Boaz stands in
    Ruth 4, Matthew 1 and Luke 3, and a reader who double-clicked him in
    Matthew means Matthew. Empty when nothing draws them — the peek then shows
    the fragment with no link out, rather than a link to a chart the person
    does not appear on."""
    usable = [c for c in document()['charts']
              if c['structure'] != 'lifespan' and pid in chart_people(c['id'])]
    if not usable:
        return ''

    def rank(c: Chart) -> tuple[int, int]:
        return (0 if book and passage_book(c['passage']) == book else 1,
                0 if c['structure'] == 'spine' else 1)

    return sorted(usable, key=rank)[0]['id']


# ── charts ─────────────────────────────────────────────────────────────────

def charts() -> list[Chart]:
    return document()['charts']


def chart(cid: str) -> Chart | None:
    for c in document()['charts']:
        if c['id'] == cid:
            return c
    return None


def readings_for(cid: str) -> list[Reading]:
    return [r for r in document()['readings'] if r['chart'] == cid]


def passage_book(chart_id_or_ref: str) -> str:
    """The canonical English book name a chart's passage names.

    `Matthew 1:1–17` → `Matthew`; `Genesis 5` → `Genesis`. Charts cite a
    range, and only the book half is needed to keep a walk inside one
    witness."""
    text = chart_id_or_ref.split('–')[0].split('-')[0].strip()
    m = re.match(r'^(.+?)\s+\d+', text)
    return m.group(1) if m else text


def chain(root: str, leaf: str, book: str = '') -> list[Edge]:
    """The edges from `root` to `leaf`, in reading order.

    `book` pins the walk to one witness and is what the charts pass. Without
    it a walk from Abraham finds BOTH Matthew's forty steps and Luke's
    fifty-six, and returns whichever it tried first — which is how this
    function first answered a request for Matthew's genealogy with Luke's.

    Every edge kind is walkable, including the ones that are not begettings:
    Matthew's own line ends `Jacob → Joseph → (husband of) Mary → (of whom
    was born) Jesus`, and a walker that only followed "begat" would stop one
    short of the person the genealogy exists to reach. The kinds come back on
    the edges so the drawing can tell them apart."""
    if _by_parent is None:
        _build_indexes()
    assert _by_parent is not None

    def out(pid: str) -> list[Edge]:
        es = _by_parent.get(pid, []) if _by_parent else []
        if book:
            es = [e for e in es if e['ref']['book'] == book]
        # Descent before marriage, so a lateral step is only ever taken when
        # it is the only way on.
        return sorted(es, key=lambda e: e['kind'] == 'husband')

    # Depth-first with an explicit stack: the graph is small and a genealogy
    # can fork (Noah has three sons; only one continues the line).
    stack: list[tuple[str, list[Edge], set[str]]] = [(root, [], {root})]
    while stack:
        cur, path, seen = stack.pop()
        if cur == leaf:
            return path
        for e in reversed(out(cur)):
            if e['child'] in seen:
                continue
            stack.append((e['child'], path + [e], seen | {e['child']}))
    return []


def lifespans(tradition: str = 'mt') -> list[Lifespan]:
    return [ls for ls in document()['lifespans']
            if ls['tradition'] == tradition]


def traditions() -> list[tuple[str, str, bool]]:
    """`(key, label, available)` for the textual traditions of the Genesis 5
    and 11 numbers.

    The Masoretic figures are read off the Hebrew the app ships. The
    Septuagint and Samaritan Pentateuch give genuinely different numbers — a
    different chart, not a rounding — and the app has no such text installed,
    so they are offered and marked unavailable rather than filled in from
    somewhere unciteable. The rule that no year appears without its tradition
    named cuts both ways: an unnamed source is not a source."""
    have = {ls['tradition'] for ls in document()['lifespans']}
    return [('mt', _('Masoretic Text'), 'mt' in have),
            ('lxx', _('Septuagint'), 'lxx' in have),
            ('sam', _('Samaritan Pentateuch'), 'sam' in have)]


def info() -> dict[str, str]:
    """Metadata for the module picker's info page."""
    doc = document()
    return {
        'description': _('The genealogies of Scripture, drawn: who descends '
                         'from whom, what the names mean, and a route back '
                         'to the passage each line comes from.'),
        'type': _('{people} people, {charts} charts').format(
            people=len(doc['people']),
            charts=sum(1 for c in doc['charts'])),
        'license': _('Curated from the biblical text; public domain'),
        'about': _('Every line carries the verse it is drawn from. Where a '
                   'genealogy leaves generations out, the gap is drawn as a '
                   'gap; where two writers disagree, both are shown and '
                   'neither is silently corrected.'),
    }
