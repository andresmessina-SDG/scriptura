"""content.py — routing facade over the content bridges.

"Which bridge owns this module key" lives here so the pane and Module
Manager call content.X(name) instead of repeating the
catena / eBible / SWORD branch in a half-dozen places. Adding a content
source (e.g. a future imagery pack) means teaching this one module about
it rather than hunting down every dispatch site.

The routing is a REGISTRY, not an if/elif ladder re-typed per function.
`_TYPES` lists one `_ContentType` descriptor per source — its membership
predicate plus every routed answer (kind, footnote capability, feature
card, language, info, removability) as a function of the module key. The
public functions below are one-line lookups over it, so a new source is
one entry rather than an edit to seven functions in lockstep. (This is
Step 0 of STRUCTURAL_ANALYSIS.md's T3 — the keystone the pane's future
content-strategy will resolve against the same table.)

Note: display_name routing already lives in sword_bridge.display_name
(which delegates eBible keys and the catena / imagery feature packs to
their bridges), so it is intentionally not duplicated here.
"""

from typing import Callable, TypedDict, cast

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


# ── The content-type registry ────────────────────────────────────────────────
# Per-source answers that don't reduce to a one-liner: the two feature packs'
# info blocks and the SWORD catch-all's kind/footnote logic. Kept as named
# functions so the descriptor list below stays a table.

def _catena_info(name: str) -> dict:
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


def _imagery_info(name: str) -> dict:
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


def _interlinear_info(name: str) -> dict:
    if interlinear_data.is_hebrew(name):
        return {
            'description': _('The Hebrew Old Testament word by word — '
                             'each word with its English gloss, parsing, '
                             'transliteration, and Strong’s number.'),
            'type': _('Interlinear'),
            'license': 'CC BY 4.0',
            'about': _('Translators Amalgamated Hebrew OT (TAHOT), '
                       'created by STEPBible at Tyndale House Cambridge '
                       'from the Leningrad Codex, with Qere readings '
                       'and English-first verse numbering.'),
        }
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


def _sword_kind(name: str) -> str:
    mtype = sword_bridge.module_type(name)
    if mtype == 'Commentaries':
        return 'commentary'
    if mtype == 'Generic Books' or sword_bridge.is_devotional_module(name):
        return 'books'
    return 'bible'


def _sword_has_footnotes(name: str) -> bool:
    # Only verse-keyed render paths (Bibles, commentaries) run the marker
    # pipeline, so a genbook / devotional conf declaring a footnote filter
    # still counts as False.
    if _sword_kind(name) not in ('bible', 'commentary'):
        return False
    return bool(sword_bridge.module_has_footnotes(name))


class _ContentType:
    """One content source and every routing answer for the keys it owns.

    Each answer is a function of the module key, so answers that vary by key
    (an eBible's language, an interlinear's testament) live in one place.
    Trivial answers get a small default; `remove` defaults to the SWORD
    remover (the path the old ladder's `else` took for the packless types)."""

    def __init__(
        self, key: str, is_member: Callable[[str], bool],
        kind: Callable[[str], str], info: Callable[[str], dict], *,
        feature_card: Callable[[str], dict | None] = lambda name: None,
        language: Callable[[str], str] = lambda name: 'en',
        has_footnotes: Callable[[str], bool] = lambda name: False,
        can_remove: Callable[[str], bool] = lambda name: False,
        remove: Callable[[str], None] | None = None,
    ) -> None:
        self.key = key
        self.is_member = is_member
        self.kind = kind
        self.info = info
        self.feature_card = feature_card
        self.language = language
        self.has_footnotes = has_footnotes
        self.can_remove = can_remove
        # Default resolves sword_bridge.remove_module at call time (not by
        # reference now), so it tracks a monkeypatch and stays the ladder's
        # old `else` path for the packless types.
        self.remove: Callable[[str], None] = (
            remove or (lambda name: sword_bridge.remove_module(name)))


# Order: the specific sources first (their predicates are disjoint), then the
# SWORD catch-all last — its predicate is always True.
_TYPES: list[_ContentType] = [
    _ContentType(
        'catena', catena_bridge.is_catena_module,
        kind=lambda name: 'commentary', info=_catena_info,
        feature_card=lambda name: {
            'icon': 'scriptura-commentary-symbolic',
            'tagline': _('Fathers, medievals & reformers — per verse')},
        can_remove=lambda name: True,
        remove=lambda name: catena_bridge.remove_pack()),
    _ContentType(
        'imagery', imagery_bridge.is_imagery_module,
        kind=lambda name: 'imagery', info=_imagery_info,
        feature_card=lambda name: {
            'icon': 'scriptura-imagery-symbolic',
            'tagline': _('Engravings, maps & place photos')},
        can_remove=lambda name: True,
        remove=lambda name: imagery_bridge.remove_pack()),
    _ContentType(
        'archaeology', archaeology_bridge.is_archaeology_module,
        kind=lambda name: 'books',
        info=lambda name: cast(dict, archaeology_bridge.info()),
        feature_card=lambda name: {
            'icon': 'scriptura-artifact-symbolic',
            'tagline': _('Artifacts of the biblical world')}),
        # bundled inside the app: can_remove False, and remove never reached.
    _ContentType(
        'interlinear', interlinear_data.is_interlinear_module,
        kind=lambda name: 'bible', info=_interlinear_info,
        feature_card=lambda name: {
            'icon': 'font-x-generic-symbolic',
            'tagline': (_('Hebrew with gloss & parsing, word by word')
                        if interlinear_data.is_hebrew(name) else
                        _('Greek with gloss & parsing, word by word'))},
        language=lambda name: (
            'hbo' if interlinear_data.is_hebrew(name) else 'grc'),
        can_remove=lambda name: True,
        remove=lambda name: interlinear_data.remove(name)),
    _ContentType(
        'ebible', ebible_bridge.is_ebible_module,
        kind=lambda name: 'bible',
        info=lambda name: cast(dict, ebible_bridge.module_info(name)),
        language=lambda name: cast(str, ebible_bridge.module_language(name)),
        has_footnotes=lambda name: bool(
            ebible_bridge.module_has_footnotes(name)),
        can_remove=lambda name: True,
        remove=lambda name: ebible_bridge.remove_module(name)),
    _ContentType(
        'sword', lambda name: True,          # catch-all — keep last
        kind=_sword_kind,
        info=lambda name: cast(dict, sword_bridge.module_info(name)),
        language=lambda name: cast(str, sword_bridge.module_language(name)),
        has_footnotes=_sword_has_footnotes,
        can_remove=lambda name: cast(
            bool, sword_bridge.can_remove_module(name))),
]


def _type_for(name: str) -> _ContentType:
    """The descriptor owning this key. The SWORD catch-all always matches, so
    the loop cannot fall through."""
    for ct in _TYPES:
        if ct.is_member(name):
            return ct
    return _TYPES[-1]


def kind(name: str) -> str:
    """Coarse content category for the module picker's tabs.

    One of: 'bible', 'commentary', 'imagery', 'books'. SWORD generic books
    and devotionals both fold into 'books'; everything verse-keyed that
    isn't a commentary is a 'bible'."""
    return _type_for(name).kind(name)


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
    return _type_for(name).has_footnotes(name)


def feature_card(name: str) -> dict | None:
    """Hero-row presentation for the marquee packs, or None for plain
    modules. The picker renders these with a leading icon and a one-line
    tagline beneath the (curated) title; ordinary modules get a plain row."""
    return _type_for(name).feature_card(name)


def language(name: str) -> str:
    """ISO language code for a module key (''/unknown when unavailable)."""
    return _type_for(name).language(name)


def info(name: str) -> dict:
    """Metadata dict for the picker info page: description, language,
    version, type, copyright, license, about (any subset)."""
    return _type_for(name).info(name)


def can_remove(name: str) -> bool:
    """Whether this module can be deleted from disk through the app.

    eBible translations and the catena pack are always removable; system
    SWORD modules under /usr/share are read-only. Does NOT enforce the
    'keep at least one module' rule — that's the caller's concern since it
    depends on what else a pane has."""
    return _type_for(name).can_remove(name)


def remove(name: str) -> None:
    """Delete a module from disk, routed to its owning bridge."""
    _type_for(name).remove(name)


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
