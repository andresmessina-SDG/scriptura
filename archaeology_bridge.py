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
from typing import TypedDict

import i18n
from i18n import _, N_

_log = logging.getLogger('scriptura.archaeology')

# Single bundled module. The key is internal; the display name is curated.
MODULE_KEY = 'ScriptureInStone'
DISPLAY_NAME = N_('Scripture in Stone')

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
    #: The same date as curated, untranslated. `date` is prose a reader sees
    #: — «XIV век до н. э.» — and the timeline places an artifact by reading
    #: the era token out of it, which only the English has.
    date_key: str
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
    intro: str
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
#: The language `_doc` was built in. Every string in it has been through
#: `_()` already, so a document cached under one language is wrong under
#: the next — and the header picker rebuilds the window inside one run.
_doc_lang: str | None = None


def is_archaeology_module(name: str) -> bool:
    return name == MODULE_KEY


def module_names() -> list[str]:
    """The bundled module key, if its data file is present."""
    return [MODULE_KEY] if os.path.exists(_DOC_FILE) else []


def display_name(name: str) -> str:
    return _(DISPLAY_NAME)


def image_path(filename: str) -> str:
    """Absolute path to a bundled artifact image."""
    return os.path.join(_DATA_DIR, 'images', filename)


def map_path() -> str:
    """The bundled biblical-world base map (NASA Blue Marble, equirectangular,
    cropped to lon 11–50°E / lat 24–43°N — the bounds the reader projects with)."""
    return os.path.join(_DATA_DIR, 'map', 'biblical_world.jpg')


def _t(text: str) -> str:
    """Translate a curated field, leaving an empty one empty.

    `_('')` returns the catalogue's own header — the whole PO metadata block —
    which is what a bare `_()` on an optional field would put on the page.
    Stripped first, because the mirror the translators work from is stripped:
    the gallery's opening body ends in a newline the TOML's own syntax adds,
    and an id off by that one character finds nothing.
    """
    return _(text.strip()) if text.strip() else text


def document() -> Document:
    """The parsed gallery: intro + chapters (in declared order), each with its
    entries (in declared order). Cached after first load."""
    global _doc, _doc_lang
    lang = i18n.current_language()
    if _doc is not None and _doc_lang == lang:
        return _doc

    with open(_DOC_FILE, 'rb') as f:
        raw = tomllib.load(f)

    intro = raw.get('intro', {})
    # Preserve declared chapter order; bucket entries into their chapter.
    chapters: list[Chapter] = [
        {'id': c['id'], 'title': _(c['title']), 'intro': _t(c.get('intro', '')),
         'entries': []}
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
        # The book stays English — it is the key the Bible pane is driven
        # with — and only the chip's label is localized, through the one
        # function that translates book names anywhere in the app. Written
        # out in full, the chips read "Joshua 10:1" under a Russian UI.
        refs: list[Ref] = [
            {'book': r['book'], 'chapter': r['chapter'], 'verse': r['verse'],
             'label': f'{i18n.book_label(r["book"])} '
                      f'{r["chapter"]}:{r["verse"]}'}
            for r in e.get('refs', [])
        ]
        # `credit` is not translated: the licences these photographs carry
        # ask us to reproduce the attribution as given.
        chap['entries'].append({
            'image': e['image'], 'source': e.get('source', ''),
            'title': _(e['title']), 'place': _t(e.get('place', '')),
            'date': _t(e.get('date', '')), 'date_key': e.get('date', ''),
            'holding': _t(e.get('holding', '')),
            'provenance': _t(e.get('provenance', '')),
            'credit': e.get('credit', ''),
            'caption': _t(e.get('caption', '')),
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
            'caption': _t(d.get('caption', '')),
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

    # A reading's `title` is a bibliography — "Amihai Mazar, Archaeology of
    # the Land of the Bible" is what a reader would type into a library
    # catalogue — so it stays as printed; the note under it is prose.
    _doc = {
        'title': _(intro.get('title', DISPLAY_NAME)),
        'subtitle': _t(intro.get('subtitle', '')),
        'body': _t(intro.get('body', '').strip()),
        'chapters': chapters,
        'terms': [{'term': _(t['term']), 'definition': _(t['definition'])}
                  for t in raw.get('term', [])],
        'reading': [{'title': r['title'], 'note': _t(r.get('note', ''))}
                    for r in raw.get('reading', [])],
    }
    _doc_lang = lang
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
        'description': _('Artifacts of the biblical world — inscriptions, '
                         'monuments, and objects that touch the people, places, '
                         'and events named in Scripture, in historical sequence.'),
        'type': _('{n} artifacts').format(n=n),
        'license': _('Public-domain objects; photographs CC BY-SA (per-item credit)'),
        'about': _('A curated, measured gallery: each artifact links to the '
                   'passage it attests. Forgeries and disputed objects are '
                   'excluded; genuine scholarly doubt is noted.'),
    }
