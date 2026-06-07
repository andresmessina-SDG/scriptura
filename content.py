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

from typing import cast

import sword_bridge
import ebible_bridge
import catena_bridge
import imagery_bridge
import archaeology_bridge

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
            + archaeology_bridge.module_names())


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
    if ebible_bridge.is_ebible_module(name):
        return 'bible'
    mtype = sword_bridge.module_type(name)
    if mtype == 'Commentaries':
        return 'commentary'
    if mtype == 'Generic Books' or sword_bridge.is_devotional_module(name):
        return 'books'
    return 'bible'


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
    return None


def language(name: str) -> str:
    """ISO language code for a module key (''/unknown when unavailable)."""
    if catena_bridge.is_catena_module(name):
        return 'en'
    if imagery_bridge.is_imagery_module(name):
        return 'en'
    if archaeology_bridge.is_archaeology_module(name):
        return 'en'
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
    if ebible_bridge.is_ebible_module(name):
        return True
    return cast(bool, sword_bridge.can_remove_module(name))


def remove(name: str) -> None:
    """Delete a module from disk, routed to its owning bridge."""
    if catena_bridge.is_catena_module(name):
        catena_bridge.remove_pack()
    elif imagery_bridge.is_imagery_module(name):
        imagery_bridge.remove_pack()
    elif ebible_bridge.is_ebible_module(name):
        ebible_bridge.remove_module(name)
    else:
        sword_bridge.remove_module(name)
