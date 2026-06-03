"""archaeology_bridge.py — the bundled "Scripture in Stone" module.

A small, curated archaeology gallery shipped *inside* the app (unlike the
download-on-demand catena / imagery packs): a TOML document of artifacts in
biblical sequence, each mapped to the verse(s) it touches. Read as a document
in a pane; the reader turns the verse refs into links that drive the Bible
pane. See content.py for the dispatch wiring and archaeology_reader.py for the
view.
"""

from __future__ import annotations

import logging
import os
import tomllib
from typing import TypedDict, cast

_log = logging.getLogger('scriptura.archaeology')

# Single bundled module. The key is internal; the display name is curated.
MODULE_KEY = 'ScriptureInStone'
DISPLAY_NAME = 'Scripture in Stone'

_HERE = os.path.dirname(os.path.abspath(__file__))
# Co-located with the python modules in both dev and the meson install
# (data/ ships to pkgdatadir alongside the code), same as styles.py.
_DATA_DIR = os.path.join(_HERE, 'data', 'archaeology')
_DOC_FILE = os.path.join(_DATA_DIR, 'scripture_in_stone.toml')


class Ref(TypedDict):
    book: str
    chapter: int
    verse: int
    label: str


class Detail(TypedDict):
    image: str
    source: str
    caption: str


class RelatedRef(TypedDict):
    image: str
    title: str


class Entry(TypedDict):
    image: str
    source: str
    title: str
    place: str
    date: str
    holding: str
    provenance: str
    credit: str
    caption: str
    lat: float | None
    lon: float | None
    refs: list[Ref]
    details: list[Detail]
    related: list[RelatedRef]


class Chapter(TypedDict):
    id: str
    title: str
    entries: list[Entry]


class Term(TypedDict):
    term: str
    definition: str


class Reading(TypedDict):
    title: str
    note: str


class Document(TypedDict):
    title: str
    subtitle: str
    body: str
    chapters: list[Chapter]
    terms: list[Term]
    reading: list[Reading]


_doc: Document | None = None


def is_archaeology_module(name: str) -> bool:
    return name == MODULE_KEY


def module_names() -> list[str]:
    """The bundled module key, if its data file is present."""
    return [MODULE_KEY] if os.path.exists(_DOC_FILE) else []


def display_name(name: str) -> str:
    return DISPLAY_NAME


def image_path(filename: str) -> str:
    """Absolute path to a bundled artifact image."""
    return os.path.join(_DATA_DIR, 'images', filename)


def map_path() -> str:
    """The bundled biblical-world base map (NASA Blue Marble, equirectangular,
    cropped to lon 11–50°E / lat 24–43°N — the bounds the reader projects with)."""
    return os.path.join(_DATA_DIR, 'map', 'biblical_world.jpg')


def document() -> Document:
    """The parsed gallery: intro + chapters (in declared order), each with its
    entries (in declared order). Cached after first load."""
    global _doc
    if _doc is not None:
        return _doc

    with open(_DOC_FILE, 'rb') as f:
        raw = tomllib.load(f)

    intro = raw.get('intro', {})
    # Preserve declared chapter order; bucket entries into their chapter.
    chapters: list[Chapter] = [
        {'id': c['id'], 'title': c['title'], 'entries': []}
        for c in raw.get('chapter', [])
    ]
    by_id = {c['id']: c for c in chapters}
    raw_related: dict[str, list[str]] = {}
    for e in raw.get('entry', []):
        chap = by_id.get(e['chapter'])
        if chap is None:
            _log.warning('entry %r references unknown chapter %r',
                         e.get('title'), e.get('chapter'))
            continue
        refs: list[Ref] = [
            {'book': r['book'], 'chapter': r['chapter'], 'verse': r['verse'],
             'label': f'{r["book"]} {r["chapter"]}:{r["verse"]}'}
            for r in e.get('refs', [])
        ]
        chap['entries'].append({
            'image': e['image'], 'source': e.get('source', ''),
            'title': e['title'], 'place': e.get('place', ''),
            'date': e.get('date', ''), 'holding': e.get('holding', ''),
            'provenance': e.get('provenance', ''),
            'credit': e.get('credit', ''), 'caption': e.get('caption', ''),
            'lat': e.get('lat'), 'lon': e.get('lon'),
            'refs': refs, 'details': [], 'related': [],
        })
        raw_related[e['image']] = list(e.get('related', []))

    # Attach detail closeups to their parent entry (matched by image filename).
    by_image = {en['image']: en for c in chapters for en in c['entries']}
    for d in raw.get('detail', []):
        parent = by_image.get(d.get('parent', ''))
        if parent is None:
            _log.warning('detail references unknown parent %r', d.get('parent'))
            continue
        parent['details'].append({
            'image': d['image'], 'source': d.get('source', ''),
            'caption': d.get('caption', ''),
        })

    # Resolve cross-links ("see also") to {image, title} once all entries exist.
    for image, others in raw_related.items():
        entry = by_image.get(image)
        if entry is None:
            continue
        for other in others:
            tgt = by_image.get(other)
            if tgt is not None:
                entry['related'].append({'image': other, 'title': tgt['title']})

    _doc = {
        'title': intro.get('title', DISPLAY_NAME),
        'subtitle': intro.get('subtitle', ''),
        'body': intro.get('body', '').strip(),
        'chapters': chapters,
        'terms': [{'term': t['term'], 'definition': t['definition']}
                  for t in raw.get('term', [])],
        'reading': [{'title': r['title'], 'note': r.get('note', '')}
                    for r in raw.get('reading', [])],
    }
    return _doc


_verse_index: dict[tuple[str, int, int], Entry] | None = None


def _index() -> dict[tuple[str, int, int], Entry]:
    """(book, chapter, verse) → the artifact entry that references it, for the
    Bible pane's per-verse 'related artifact' markers. Cached."""
    global _verse_index
    if _verse_index is None:
        idx: dict[tuple[str, int, int], Entry] = {}
        for chap in document()['chapters']:
            for entry in chap['entries']:
                for r in entry['refs']:
                    idx.setdefault((r['book'], r['chapter'], r['verse']), entry)
        _verse_index = idx
    return _verse_index


def verses_with_artifacts(book: str, chapter: int) -> set[int]:
    """The verse numbers in this chapter that a gallery artifact references."""
    return {v for (b, c, v) in _index() if b == book and c == chapter}


def info() -> dict[str, str]:
    """Metadata for the module picker's info page."""
    doc = document()
    n = sum(len(c['entries']) for c in doc['chapters'])
    return {
        'description': 'Artifacts of the biblical world — inscriptions, '
                       'monuments, and objects that touch the people, places, '
                       'and events named in Scripture, in historical sequence.',
        'type': f'{n} artifacts',
        'license': 'Public-domain objects; photographs CC BY-SA (per-item credit)',
        'about': 'A curated, measured gallery: each artifact links to the '
                 'passage it attests. Forgeries and disputed objects are '
                 'excluded; genuine scholarly doubt is noted.',
    }
