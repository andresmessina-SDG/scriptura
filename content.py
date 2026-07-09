"""content.py — routing facade over the content bridges.

"Which bridge owns this module key" lives here so the pane and Module
Manager call content.X(name) instead of repeating the
catena / eBible / SWORD branch in a half-dozen places. Adding a content
source (e.g. a future imagery pack) means teaching this one module about
it rather than hunting down every dispatch site.

Note: display_name routing already lives in sword_bridge.display_name
(which delegates eBible keys and the catena / imagery feature packs to
their bridges), so it is intentionally not duplicated here.
"""

from typing import TypedDict, cast

import sword_bridge
import ebible_bridge
import catena_bridge
import imagery_bridge
import archaeology_bridge
import interlinear_data
from i18n import _

# Pane-readable SWORD module types (Bibles, commentaries, browsable books).
# Lexicons / dictionaries / morphology modules are reached through other
# surfaces (lexicon panel, dict popup), not read as a pane.
_SWORD_READABLE_TYPES = ('Biblical Texts', 'Commentaries', 'Generic Books')


def readable_module_names() -> list[str]:
    """Every module key suitable for a pane's module picker, across all
    sources."""
    keep: list[str] = []
    for name in sword_bridge.module_names():
        if sword_bridge.is_internal_use(name):
            continue
        if sword_bridge.module_type(name) in _SWORD_READABLE_TYPES \
                or sword_bridge.is_devotional_module(name):
            keep.append(name)
    return (keep + cast(list[str], ebible_bridge.module_names())
            + catena_bridge.module_names() + imagery_bridge.module_names()
            + archaeology_bridge.module_names()
            + interlinear_data.module_names())


def kind(name: str) -> str:
    """Coarse content category for the module picker's tabs.

    One of: 'bible', 'commentary', 'imagery', 'books'. SWORD generic books
    and devotionals both fold into 'books'; everything verse-keyed that
    isn't a commentary is a 'bible'."""
    if catena_bridge.is_catena_module(name):
        return 'commentary'
    if imagery_bridge.is_imagery_module(name):
        return 'imagery'
    if archaeology_bridge.is_archaeology_module(name):
        return 'books'
    if interlinear_data.is_interlinear_module(name):
        return 'bible'
    if ebible_bridge.is_ebible_module(name):
        return 'bible'
    mtype = sword_bridge.module_type(name)
    if mtype == 'Commentaries':
        return 'commentary'
    if mtype == 'Generic Books' or sword_bridge.is_devotional_module(name):
        return 'books'
    return 'bible'


def is_text_bible(name: str) -> bool:
    """A 'bible'-kind module that actually carries readable verse text in a
    SWORD/eBible backend. The interlinear is bible-kind for picker grouping
    but has neither a searchable text stream nor a TextView render path —
    callers wanting a Bible to search or to read (All-Bibles search, the
    window's default-Bible pick) filter through here."""
    return (kind(name) == 'bible'
            and not interlinear_data.is_interlinear_module(name))


def has_footnotes(name: str) -> bool:
    """Whether the module can surface translator footnotes in a reading
    pane — drives the header f* toggle's sensitivity. Only verse-keyed
    render paths run the marker pipeline, so a genbook/devotional conf
    declaring a footnote filter still counts as False here."""
    if ebible_bridge.is_ebible_module(name):
        return bool(ebible_bridge.module_has_footnotes(name))
    if interlinear_data.is_interlinear_module(name):
        return False   # glosses are inline; no translator-footnote stream
    if kind(name) not in ('bible', 'commentary'):
        return False
    return bool(sword_bridge.module_has_footnotes(name))


def feature_card(name: str) -> dict | None:
    """Hero-row presentation for the marquee packs, or None for plain
    modules. The picker renders these with a leading icon and a one-line
    tagline beneath the (curated) title; ordinary modules get a plain row."""
    if catena_bridge.is_catena_module(name):
        return {'icon': 'scriptura-commentary-symbolic',
                'tagline': _('Fathers, medievals & reformers — per verse')}
    if imagery_bridge.is_imagery_module(name):
        return {'icon': 'scriptura-imagery-symbolic',
                'tagline': _('Engravings, maps & place photos')}
    if archaeology_bridge.is_archaeology_module(name):
        return {'icon': 'scriptura-artifact-symbolic',
                'tagline': _('Artifacts of the biblical world')}
    if interlinear_data.is_interlinear_module(name):
        return {'icon': 'font-x-generic-symbolic',
                'tagline': _('Greek with gloss & parsing, word by word')}
    return None


def language(name: str) -> str:
    """ISO language code for a module key (''/unknown when unavailable)."""
    if catena_bridge.is_catena_module(name):
        return 'en'
    if imagery_bridge.is_imagery_module(name):
        return 'en'
    if archaeology_bridge.is_archaeology_module(name):
        return 'en'
    if interlinear_data.is_interlinear_module(name):
        return 'grc'
    if ebible_bridge.is_ebible_module(name):
        return cast(str, ebible_bridge.module_language(name))
    return cast(str, sword_bridge.module_language(name))


def info(name: str) -> dict:
    """Metadata dict for the picker info page: description, language,
    version, type, copyright, license, about (any subset)."""
    if catena_bridge.is_catena_module(name):
        meta = catena_bridge.pack_info()
        return {
            'description': _('Patristic, medieval, and Reformation commentary '
                             'keyed to each verse — the church reading '
                             'Scripture across the centuries.'),
            'version': meta.get('built', ''),
            'type': _('{n} quotations').format(n=meta.get('quote_count', '?')),
            'license': _('Public domain (compiled from public-domain sources)'),
            'about': _('Compiled from the HistoricalChristianFaith '
                       'Commentaries Database.'),
        }
    if imagery_bridge.is_imagery_module(name):
        meta = imagery_bridge.pack_info()
        return {
            'description': _('Public-domain illustrations, historical maps, and '
                             'photographs of the places named in Scripture, '
                             'shown beside the verse you are reading.'),
            'version': meta.get('built', ''),
            'type': _('{n} images').format(n=meta.get('image_count', '?')),
            'license': _('Public domain & Creative Commons (per-item credits)'),
            'about': _('Engravings (Doré, Schnorr, Merian), historical maps, and '
                       'place photography from public-domain and openly-licensed '
                       'sources.'),
        }
    if archaeology_bridge.is_archaeology_module(name):
        return archaeology_bridge.info()
    if interlinear_data.is_interlinear_module(name):
        return {
            'description': _('The Greek New Testament word by word — each '
                             'word with its English gloss, parsing, '
                             'transliteration, and Strong’s number.'),
            'type': _('Interlinear'),
            'license': 'CC BY 4.0',
            'about': _('Translators Amalgamated Greek NT (TAGNT), created '
                       'by STEPBible at Tyndale House Cambridge. Follows '
                       'the Nestle-Aland word stream; variant words from '
                       'other editions are preserved in the data.'),
        }
    if ebible_bridge.is_ebible_module(name):
        return cast(dict, ebible_bridge.module_info(name))
    return cast(dict, sword_bridge.module_info(name))


def can_remove(name: str) -> bool:
    """Whether this module can be deleted from disk through the app.

    eBible translations and the catena pack are always removable; system
    SWORD modules under /usr/share are read-only. Does NOT enforce the
    'keep at least one module' rule — that's the caller's concern since it
    depends on what else a pane has."""
    if catena_bridge.is_catena_module(name):
        return True
    if imagery_bridge.is_imagery_module(name):
        return True
    if archaeology_bridge.is_archaeology_module(name):
        return False  # bundled inside the app; not user-removable
    if interlinear_data.is_interlinear_module(name):
        return True
    if ebible_bridge.is_ebible_module(name):
        return True
    return cast(bool, sword_bridge.can_remove_module(name))


def remove(name: str) -> None:
    """Delete a module from disk, routed to its owning bridge."""
    if catena_bridge.is_catena_module(name):
        catena_bridge.remove_pack()
    elif imagery_bridge.is_imagery_module(name):
        imagery_bridge.remove_pack()
    elif interlinear_data.is_interlinear_module(name):
        interlinear_data.remove()
    elif ebible_bridge.is_ebible_module(name):
        ebible_bridge.remove_module(name)
    else:
        sword_bridge.remove_module(name)


# ── Cross-source editions of the same translation ────────────────────────────
#
# The same translation often exists both as a CrossWire SWORD module and
# as an eBible.org download (differing in markup: Strong's tagging,
# footnotes, deuterocanon). The Module Manager folds such duplicates into
# one row per *work* with the editions selectable underneath. The table
# is curated, not fuzzy: the sources share no identifier, and title
# matching silently mis-pairs distinct revisions — a wrong merge is worse
# than a duplicate row. Every id below was read out of the two live
# catalogues; extending the table is one line per newly spotted pair.

class EditionWork(TypedDict):
    id: str
    title: str          # canonical display title (proper name, untranslated)
    sword: tuple[str, ...]
    ebible: tuple[str, ...]


EDITION_WORKS: list[EditionWork] = [
    {'id': 'kjv', 'title': 'King James Version',
     'sword': ('KJV', 'KJVA'), 'ebible': ('eng-kjv', 'eng-kjv2006')},
    {'id': 'asv', 'title': 'American Standard Version (1901)',
     'sword': ('ASV',), 'ebible': ('eng-asv',)},
    {'id': 'ylt', 'title': 'Young’s Literal Translation',
     'sword': ('YLT',), 'ebible': ('engylt',)},
    {'id': 'darby', 'title': 'Darby Bible',
     'sword': ('Darby',), 'ebible': ('engDBY',)},
    {'id': 'drc', 'title': 'Douay-Rheims (Challoner)',
     'sword': ('DRC',), 'ebible': ('engDRA',)},
    {'id': 'bbe', 'title': 'Bible in Basic English',
     'sword': ('BBE',), 'ebible': ('engBBE',)},
    {'id': 'geneva', 'title': 'Geneva Bible (1599)',
     'sword': ('Geneva1599',), 'ebible': ('enggnv',)},
    {'id': 'webster', 'title': 'Webster Bible',
     'sword': ('Webster',), 'ebible': ('engwebster',)},
    {'id': 'jps', 'title': 'JPS TaNaKH (1917)',
     'sword': ('JPS',), 'ebible': ('engjps',)},
    {'id': 'emtv', 'title': 'English Majority Text Version',
     'sword': ('EMTV',), 'ebible': ('engemtv',)},
    {'id': 'godsword', 'title': 'GOD’S WORD',
     'sword': ('GodsWord',), 'ebible': ('enggw',)},
    {'id': 'noyes', 'title': 'Noyes Translation (1869)',
     'sword': ('Noyes',), 'ebible': ('engnoy',)},
    {'id': 'oeb', 'title': 'Open English Bible (US)',
     'sword': ('OEB',), 'ebible': ('engoebus',)},
    {'id': 'oebcth', 'title': 'Open English Bible (Commonwealth)',
     'sword': ('OEBcth',), 'ebible': ('engoebcw',)},
    {'id': 'bsb', 'title': 'Berean Standard Bible',
     'sword': ('BSB',), 'ebible': ('engbsb',)},
    {'id': 'net', 'title': 'New English Translation (NET)',
     'sword': ('NETfree', 'NETtext'), 'ebible': ('engnet',)},
    {'id': 'tyndale', 'title': 'Tyndale Bible',
     'sword': ('Tyndale',), 'ebible': ('engtnt',)},
]

_WORK_BY_KEY: dict[tuple[str, str], str] = {}
_WORK_TITLE: dict[str, str] = {}
for _w in EDITION_WORKS:
    _WORK_TITLE[_w['id']] = _w['title']
    for _k in _w['sword']:
        _WORK_BY_KEY[('sword', _k)] = _w['id']
    for _k in _w['ebible']:
        _WORK_BY_KEY[('ebible', _k)] = _w['id']


def edition_work(source: str, key: str) -> str | None:
    """The curated work id shared by cross-source editions of one
    translation, or None when the key has no known counterpart.
    `source` is 'sword' (module key) or 'ebible' (translationId)."""
    return _WORK_BY_KEY.get((source, key))


def edition_work_title(work_id: str) -> str:
    """Canonical display title for a work id from EDITION_WORKS."""
    return _WORK_TITLE[work_id]
