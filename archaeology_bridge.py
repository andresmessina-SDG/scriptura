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


class Entry(TypedDict):
    image: str
    title: str
    place: str
    date: str
    holding: str
    credit: str
    caption: str
    refs: list[Ref]


class Chapter(TypedDict):
    id: str
    title: str
    entries: list[Entry]


class Document(TypedDict):
    title: str
    subtitle: str
    body: str
    chapters: list[Chapter]


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
            'image': e['image'], 'title': e['title'], 'place': e.get('place', ''),
            'date': e.get('date', ''), 'holding': e.get('holding', ''),
            'credit': e.get('credit', ''), 'caption': e.get('caption', ''),
            'refs': refs,
        })

    _doc = {
        'title': intro.get('title', DISPLAY_NAME),
        'subtitle': intro.get('subtitle', ''),
        'body': intro.get('body', '').strip(),
        'chapters': chapters,
    }
    return _doc


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
