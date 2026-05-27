import io
import logging
import os
import re
import shutil
import tarfile
import threading
import urllib.request
import zipfile
from collections import OrderedDict
import Sword

_sword_log = logging.getLogger('scriptura.sword')
_search_log = logging.getLogger('scriptura.search')

# Whoosh is only imported on first search/index — saves ~50 ms on cold
# start for the common case where the user never searches. The lazy
# helpers `_whoosh_*` below cache the imported names and the bible
# schema so repeated calls are dict-lookup-cheap.
_whoosh_imports = None
_bible_schema_cached = None


def _whoosh_load():
    """Import Whoosh on demand and return the names we use."""
    global _whoosh_imports
    if _whoosh_imports is None:
        from whoosh.index import create_in, open_dir, exists_in
        from whoosh.qparser import QueryParser
        _whoosh_imports = {
            'create_in': create_in,
            'open_dir': open_dir,
            'exists_in': exists_in,
            'QueryParser': QueryParser,
        }
    return _whoosh_imports


def _bible_schema():
    """Lazy-construct the Whoosh schema we index Bibles into."""
    global _bible_schema_cached
    if _bible_schema_cached is None:
        from whoosh.fields import Schema, ID, TEXT, NUMERIC
        from whoosh.analysis import StemmingAnalyzer
        _bible_schema_cached = Schema(
            module=ID(stored=True),
            book=ID(stored=True),
            chapter=NUMERIC(stored=True),
            verse=NUMERIC(stored=True),
            content=TEXT(stored=True, analyzer=StemmingAnalyzer()),
        )
    return _bible_schema_cached

_mgr = None
# RLock allows reentry: callers like load_chapter hold _lock and then call mgr().
_lock = threading.RLock()
# Chapter render cache. OrderedDict + cap = LRU eviction so a long reading
# session that touches the whole canon doesn't grow memory unboundedly.
# 200 chapters × ~50 KB ≈ 10 MB worst case; comfortably above any normal
# session's working set.
_CHAPTER_CACHE_CAP = 200
_cache = OrderedDict()
# Strong's lookup cache — same shape, smaller cap. A typical chapter
# references 30–50 unique Strong's numbers; 500 covers many chapters of
# recent activity before evicting.
_STRONGS_CACHE_CAP = 500
_strongs_cache = OrderedDict()


def _cache_chapter(key, value):
    """Insert a chapter render with LRU eviction. Caller holds _lock."""
    _cache[key] = value
    _cache.move_to_end(key)
    if len(_cache) > _CHAPTER_CACHE_CAP:
        _cache.popitem(last=False)


def _cache_strong(strong_num, value):
    """Insert a Strong's lookup with LRU eviction. Caller holds _lock."""
    _strongs_cache[strong_num] = value
    _strongs_cache.move_to_end(strong_num)
    if len(_strongs_cache) > _STRONGS_CACHE_CAP:
        _strongs_cache.popitem(last=False)

_indexing_threads = {} # To keep track of indexing processes per module
# Separate lock for _indexing_threads dict ops only — never held during join().
# Keeping it distinct from _lock avoids deadlocks (indexer threads acquire _lock
# inside load_chapter; if we held _lock here, the indexer couldn't make progress).
_indexing_lock = threading.Lock()

WHOOSH_INDEX_DIR = os.path.expanduser('~/.sword/whoosh_indexes')
MAX_SEARCH_RESULTS = 5000 # Limit the number of Whoosh results to prevent performance issues with common words

def _get_index_path(module_name):
    return os.path.join(WHOOSH_INDEX_DIR, module_name)

def _build_module_index(module_name, on_progress=None):
    """Build a fresh Whoosh index for module_name. Always starts clean.

    `on_progress(book_idx, total_books, book_name)` is invoked on the
    indexing thread once per book; the receiver should marshal to the
    main loop itself (via GLib.idle_add). Indexing a full Bible against
    SWORD typically takes 5-15s; per-book ticks give the UI something
    concrete to display while the work runs."""
    idx_path = _get_index_path(module_name)
    shutil.rmtree(idx_path, ignore_errors=True)
    os.makedirs(idx_path, exist_ok=True)

    w = _whoosh_load()
    ix = w['create_in'](idx_path, _bible_schema())
    writer = ix.writer()

    try:
        total_books = len(_ALL_BOOKS)
        for i, book in enumerate(_ALL_BOOKS, start=1):
            if on_progress:
                try:
                    on_progress(i, total_books, book)
                except Exception:
                    pass
            for ch in range(1, chapter_count(book) + 1):
                for v_num, html in load_chapter(module_name, book, ch):
                    plain_text = re.sub(r'<[^>]+>', '', str(html))
                    writer.add_document(module=module_name, book=book,
                                        chapter=ch, verse=v_num, content=plain_text)
        writer.commit()
    except Exception as e:
        # Without cancel(), Whoosh leaves a MAIN_WRITELOCK file that blocks
        # all future searches against this module until manual cleanup.
        _search_log.exception('index build failed for %r', module_name)
        try:
            writer.cancel()
        except Exception:
            pass
        return False
    finally:
        try:
            ix.close()
        except Exception:
            pass
    return True



class _NullSWMgr:
    """Stand-in when Sword.SWMgr() fails — keeps the app usable so module
    manager and settings still work; all module lookups return empty."""
    def getModule(self, *_args, **_kwargs):
        return None
    def getModules(self):
        return {}


_null_mgr = _NullSWMgr()


def mgr():
    global _mgr
    # Always acquire the lock — _reset() can null _mgr concurrently.
    # RLock allows callers already holding _lock to reenter safely.
    with _lock:
        if _mgr is None:
            try:
                _mgr = Sword.SWMgr()
            except Exception as e:
                # Bad/missing ~/.sword or malformed conf — don't crash the app.
                # Return a no-op stub so all `mgr().getModule(name)` callers
                # get None (which they already handle). Don't cache the stub —
                # we want to retry on next call after the user fixes their setup.
                _sword_log.exception('SWMgr init failed')
                return _null_mgr
        return _mgr


def _reset():
    global _mgr
    with _lock:
        _mgr = None
        _cache.clear()
        _strongs_cache.clear()
    with _indexing_lock:
        _indexing_threads.clear()



def module_names():
    return sorted(str(k) for k in mgr().getModules().keys())


def has_any_module():
    """Cheap check: does the user appear to have any SWORD module
    installed? Reads `~/.sword/mods.d/*.conf` directly. Used by the
    welcome-vs-main startup decision so we don't pay the first
    `SWMgr()` cost just to discover whether to show the welcome
    window. The first real SWORD call (a chapter render in
    `BiblePane`) does the authoritative SWMgr() init."""
    mods_dir = os.path.expanduser('~/.sword/mods.d')
    try:
        for name in os.listdir(mods_dir):
            if name.endswith('.conf'):
                return True
    except OSError:
        pass
    return False


def module_language(module_name):
    """Return the 2/3-letter language code for a module ('en', 'grc',
    'heb', …) or '' if the module/config can't be read."""
    try:
        mod = mgr().getModule(module_name)
        if mod is None:
            return ''
        return str(mod.getConfigEntry('Lang') or '').strip().lower()
    except Exception:
        return ''


def module_info(module_name):
    """Return a dict of human-readable metadata for the Module Info popover.
    Missing fields come back as ''."""
    info = {'name': module_name, 'description': '', 'version': '',
            'copyright': '', 'license': '', 'about': '', 'language': '',
            'type': ''}
    try:
        mod = mgr().getModule(module_name)
        if mod is None:
            return info
        info['description'] = str(mod.getConfigEntry('Description') or '')
        info['version']     = str(mod.getConfigEntry('Version') or '')
        info['copyright']   = str(mod.getConfigEntry('Copyright') or '')
        info['license']     = str(mod.getConfigEntry('DistributionLicense')
                                  or mod.getConfigEntry('License') or '')
        info['about']       = str(mod.getConfigEntry('About') or '')
        info['language']    = str(mod.getConfigEntry('Lang') or '').strip().lower()
        info['type']        = str(mod.getType() or '')
    except Exception:
        pass
    return info


def chapter_count(book):
    try:
        vk = Sword.VerseKey()
        vk.setText(f'{book} 1:1')
        return vk.getChapterMax()
    except Exception:
        # Bad book name (typo, deuterocanon outside KJV v11n) — return 1 so
        # callers don't crash. The whole nav/search/index chain depends on this.
        return 1


def verse_count(book, chapter):
    try:
        vk = Sword.VerseKey()
        vk.setText(f'{book} {chapter}:1')
        return vk.getVerseMax()
    except Exception:
        return 1


def load_chapter(module_name, book, chapter):
    key = (module_name, book, chapter)
    # Cache check inside the lock — _reset() can clear _cache concurrently,
    # which would race with a bare `if key in _cache` / `_cache[key]` read.
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)  # mark as recently used
            return _cache[key]

        mod = mgr().getModule(module_name)
        if mod is None:
            return []

        try:
            vk = Sword.VerseKey()
            # Use the module's own versification, not the default KJV — modules
            # like RusSynodal (Synodal), MorphGNT (NRSV) or Wycliffe (Vulg)
            # have different verse counts (e.g. Synodal Psalms have an extra
            # verse), so a KJV key would truncate or overshoot the chapter.
            v11n = mod.getConfigEntry('Versification')
            if v11n:
                try:
                    vk.setVersificationSystem(v11n)
                except Exception:
                    pass  # unknown system → fall back to default
            vk.setText(f'{book} {chapter}:1')
            verse_max = vk.getVerseMax()
        except Exception as e:
            _sword_log.exception('load_chapter VerseKey failed for %s %s', book, chapter)
            return []

        results = []
        for v in range(1, verse_max + 1):
            try:
                vk.setVerse(v)
                mod.setKey(vk)
                results.append((v, mod.renderText()))
            except Exception:
                continue

        _cache_chapter(key, results)
        return results


def module_type(module_name):
    """Return the SWORD type string for a module: 'Biblical Texts', 'Commentaries', etc."""
    mod = mgr().getModule(module_name)
    return str(mod.getType()) if mod else None


def is_devotional_module(module_name):
    """Return True if the module is a Daily Devotional (checks Category/Feature config)."""
    mod = mgr().getModule(module_name)
    if mod is None:
        return False
    cat  = str(mod.getConfigEntry('Category') or '').strip()
    feat = str(mod.getConfigEntry('Feature')  or '').strip()
    return cat == 'Daily Devotional' or feat == 'DailyDevotion'


def installed_devotional_modules():
    """Return names of installed Daily Devotional modules."""
    return [n for n in module_names() if is_devotional_module(n)]


# Modules used internally by the app for lookups, not as user-facing
# reading material. Hidden from pane / search / compare dropdowns
# because they register as Biblical Texts but their primary purpose is
# morphology lookup via the lexicon panel (see lookup_morph_for_strong
# and lookup_morph_for_strong_heb).
INTERNAL_USE_MODULES = frozenset({
    'MorphGNT',  # Greek NT morphology
    'OSHB',      # Open Scriptures Hebrew Bible — Hebrew morphology
})


def is_internal_use(module_name):
    return module_name in INTERNAL_USE_MODULES


# Curated human-friendly labels for popular CrossWire modules. The
# SWORD `Name=` (e.g. "MHCC") is what the library uses internally; the
# labels below are what users see in module pickers, the search target
# dropdown, and the Compare Translations dialog. Modules not in this
# map fall back to their short name. The Module Manager intentionally
# keeps short names — users browsing the catalog match against
# CrossWire's own pages which use the canonical short names.
DISPLAY_NAMES = {
    # Bibles
    'KJV':           'King James Version',
    'KJVA':          'King James (with Apocrypha)',
    'ASV':           'American Standard Version',
    'WEB':           'World English Bible',
    'WEBA':          'World English Bible (with Apocrypha)',
    'LEB':           'Lexham English Bible',
    'NET':           'NET Bible',
    'YLT':           "Young's Literal Translation",
    'Darby':         'Darby Translation',
    'Geneva1599':    'Geneva Bible (1599)',
    'Bishops':       "Bishops' Bible (1568)",
    'BBE':           'Bible in Basic English',
    'DRC':           'Douay-Rheims (Challoner)',
    'Webster':       "Webster's Revision",
    'KJV2006':       'King James Version (2006)',
    'EMTV':          "English Majority Text",
    'BSB':           'Berean Standard Bible',
    'NHEB':          'New Heart English Bible',
    'MKJV':          'Modern King James Version',
    'LITV':          "Green's Literal Translation",
    'AKJV':          'American King James Version',
    'UKJV':          'Updated King James Version',
    'RNKJV':         'Restored Name King James Version',
    'KJVPCE':        'King James (Pure Cambridge Edition)',
    'RWebster':      'Revised Webster Version',
    'ACV':           'A Conservative Version',
    'ALT':           'Analytical-Literal Translation',
    'Jubilee2000':   'Jubilee Bible 2000',
    'ISV':           'International Standard Version',
    'GodsWord':      "God's Word Translation",
    'OEB':           'Open English Bible',
    'CPDV':          'Catholic Public Domain Version',
    'Common':        'Common Edition New Testament',
    'Weymouth':      'Weymouth New Testament',
    'Rotherham':     "Rotherham's Emphasized Bible",
    'Diaglott':      'Emphatic Diaglott',
    'Twenty':        'Twentieth Century New Testament',
    'Montgomery':    'Montgomery New Testament',
    'Tyndale':       'Tyndale New Testament (1526)',
    'Wycliffe':      'Wycliffe Bible (1395)',
    'Murdock':       'Murdock Peshitta New Testament',
    'Etheridge':     'Etheridge Peshitta New Testament',
    'JPS':           'Jewish Publication Society Tanakh (1917)',
    'Leeser':        'Leeser Tanakh (1853)',
    'Vulgate':       'Latin Vulgate',
    'VulgClementine': 'Clementine Vulgate',
    'Luther':        'Luther Bible (German)',
    'GerSch':        'Schlachter Bible (1951)',
    'GerElb1871':    'Elberfelder Bible (1871)',
    'ItaDio':        'Diodati Bible (1649)',
    'ItaRive':       'Riveduta Bible (1927)',
    'SpaRV1909':     'Reina-Valera (1909)',
    'RusSynodal':    'Russian Synodal Bible',
    # Commentaries
    'MHC':           'Matthew Henry (Complete)',
    'MHCC':          'Matthew Henry (Concise)',
    'TSK':           'Treasury of Scripture Knowledge',
    'Clarke':        "Adam Clarke's Commentary",
    'Barnes':        "Barnes' Notes",
    'Wesley':        "Wesley's Notes",
    'JFB':           'Jamieson-Fausset-Brown',
    'Gill':          "Gill's Exposition",
    'Scofield':      'Scofield Reference Notes',
    'RWP':           "Robertson's Word Pictures",
    'Family':        'Family Bible Notes',
    'GerNeueBruns':  'Brunswick Commentary',
    'CalvinCommentaries': "Calvin's Commentaries",
    # Devotionals
    'SME':           'Spurgeon — Morning & Evening',
    'Spurgeon':      "Spurgeon's Morning & Evening",
    'Chambers':      'My Utmost for His Highest',
    'DailyTSK':      'Daily TSK',
    # Greek / Hebrew sources
    'TR':            'Textus Receptus',
    'SBLGNT':        'SBL Greek New Testament',
    'WHNU':          'Westcott-Hort / Nestle-Aland',
    'Byz':           'Byzantine Majority Text',
    'LXX':           'Septuagint',
    'ABP':           'Apostolic Bible Polyglot',
    'WLC':           'Westminster Leningrad Codex',
    'OSHB':          'Open Scriptures Hebrew Bible',
    'Aleppo':        'Aleppo Codex',
    'MorphGNT':      'Morphological Greek New Testament',
    'Tisch':         'Tischendorf Greek New Testament',
    'Nestle1904':    'Nestle Greek New Testament (1904)',
    'Antoniades':    'Antoniades Patriarchal Greek NT',
    'Elzevir':       'Elzevir Textus Receptus (1624)',
    # Lexicons + dictionaries
    'StrongsHebrew': "Strong's Hebrew Dictionary",
    'StrongsGreek':  "Strong's Greek Dictionary",
    'Easton':        "Easton's Bible Dictionary",
    'Smith':         "Smith's Bible Dictionary",
    'ISBE':          'ISBE Encyclopedia',
    'Nave':          "Nave's Topical Bible",
    'Webster1913':   "Webster's 1913 Dictionary",
    'Torrey':        "Torrey's New Topical Textbook",
    'Hitchcock':     "Hitchcock's Bible Names Dictionary",
}


def display_name(name):
    """Return the human-friendly label for any module key. SWORD modules
    map through the curated name table; eBible keys (PREFIX + id) are
    resolved to their title by ebible_bridge. The lazy import keeps this
    bridge otherwise independent of the eBible one."""
    if isinstance(name, str) and name.startswith('eBible: '):
        import ebible_bridge
        return ebible_bridge.display_name(name)
    return DISPLAY_NAMES.get(name, name)


# ── Generic Books ────────────────────────────────────────────────────────────
# Generic Books (SWORD type "Generic Books") are tree-keyed rather than
# verse-keyed. Examples: Didache, Westminster Confession, Apostolic
# Fathers, Book of Common Prayer, theological treatises. Their primary
# access pattern is "browse a table of contents, click an entry, read"
# — not chapter navigation. The bridge below exposes:
#   - is_genbook_module(name)
#   - list_genbook_entries(name) → [(path, label, depth), ...] in document order
#   - load_genbook_entry(name, path) → rendered HTML for that entry
#
# Cached per-module since walking the tree key on every popover open
# would be wasteful (the structure doesn't change at runtime).

_GENBOOK_TOC_CACHE = {}


def is_genbook_module(module_name):
    """True for SWORD type 'Generic Books'."""
    return module_type(module_name) == 'Generic Books'


def _genbook_tree_key(mod):
    """Try to get a TreeKey wrapper for a Generic Book module. The SWIG
    bindings vary across distros — getKey() may return a plain SWKey
    that's missing firstChild/nextSibling/parent. Try several known
    cast paths; return None if none work (caller falls back to a flat
    increment-based walk)."""
    # createKey() should return the right subtype for the module
    try:
        k = mod.createKey()
        if hasattr(k, 'firstChild'):
            return k
    except Exception:
        pass
    try:
        raw = mod.getKey()
    except Exception:
        return None
    if hasattr(raw, 'firstChild'):
        return raw
    # SWIG-generated static-cast helpers
    for caster_name in ('TreeKeyIdx_castTo', 'TreeKey_castTo'):
        caster = getattr(Sword, caster_name, None)
        if caster:
            try:
                tk = caster(raw)
                if hasattr(tk, 'firstChild'):
                    return tk
            except Exception:
                continue
    for cls_name in ('TreeKeyIdx', 'TreeKey'):
        cls = getattr(Sword, cls_name, None)
        if cls and hasattr(cls, 'castTo'):
            try:
                tk = cls.castTo(raw)
                if hasattr(tk, 'firstChild'):
                    return tk
            except Exception:
                continue
    return None


def list_genbook_entries(module_name, max_entries=4000):
    """Walk the Generic Book's TreeKey in document order and return a flat
    list of (path, label, depth) tuples — path is the full TreeKey string
    (e.g. '/Chapter 1/Section 2'), label is the local name to show, depth
    is the indentation level for TOC rendering.

    Cached per module. Two strategies:
      1. If we can obtain a real TreeKey wrapper (firstChild/nextSibling/
         parent), do a proper depth-first walk — gives accurate depth.
      2. Otherwise fall back to mod.increment() in document order and
         derive depth from the path's '/' separator count. Loses fidelity
         on TreeKey conventions that don't reflect depth in the path but
         works for the common case (Didache, Westminster, etc.)."""
    if module_name in _GENBOOK_TOC_CACHE:
        return _GENBOOK_TOC_CACHE[module_name]

    entries = []
    with _lock:
        mod = mgr().getModule(module_name)
        if mod is None:
            _GENBOOK_TOC_CACHE[module_name] = entries
            return entries

        # Helpers that adapt across binding variants. TreeKeyIdx's path
        # accessor is spelled `getKeyText` on some bindings and `getText`
        # on others (and short-name might be `getLocalName` or a missing
        # method entirely). Try each and fall back to str(key).
        def _path_of(k):
            for name in ('getKeyText', 'getText', 'getShortText'):
                fn = getattr(k, name, None)
                if fn is None:
                    continue
                try:
                    v = fn()
                    if v is None:
                        continue
                    return str(v)
                except Exception:
                    continue
            try:
                return str(k)
            except Exception:
                return ''

        def _label_of(k, path):
            fn = getattr(k, 'getLocalName', None)
            if fn:
                try:
                    v = fn()
                    if v:
                        return str(v)
                except Exception:
                    pass
            return path.rsplit('/', 1)[-1] or path

        tk = _genbook_tree_key(mod)
        if tk is not None:
            try:
                tk.root()

                def _depth():
                    fn = getattr(tk, 'getLevel', None)
                    if fn:
                        try:
                            return int(fn())
                        except Exception:
                            pass
                    return _path_of(tk).count('/')

                def _record():
                    path = _path_of(tk)
                    if not path or path == '/':
                        return
                    label = _label_of(tk, path)
                    entries.append((path, label, max(0, _depth() - 1)))

                if tk.firstChild():
                    while len(entries) < max_entries:
                        _record()
                        if tk.firstChild():
                            continue
                        while True:
                            if tk.nextSibling():
                                break
                            if not tk.parent():
                                _GENBOOK_TOC_CACHE[module_name] = entries
                                return entries
                            try:
                                if int(tk.getLevel()) <= 0:
                                    _GENBOOK_TOC_CACHE[module_name] = entries
                                    return entries
                            except Exception:
                                pass
            except Exception as e:
                _sword_log.exception('genbook tree walk failed for %s', module_name)
                entries = []

        if not entries:
            # Flat fallback: increment the module forward, collecting
            # paths as we go. Depth derived from '/' count in path.
            def _mod_path():
                for name in ('getKeyText', 'getKey'):
                    fn = getattr(mod, name, None)
                    if fn is None:
                        continue
                    try:
                        v = fn()
                        if v is None:
                            continue
                        # getKey() returns a key object; getKeyText
                        # returns a string. Stringify either way.
                        return str(v)
                    except Exception:
                        continue
                return ''

            try:
                try:
                    mod.setKeyText('/')
                except Exception:
                    pass
                seen = set()
                count = 0
                while count < max_entries:
                    try:
                        mod.increment()
                    except Exception:
                        break
                    try:
                        if mod.popError():
                            break
                    except Exception:
                        pass
                    path = _mod_path()
                    if not path or path == '/':
                        count += 1
                        continue
                    if path in seen:
                        # increment looped or stalled; bail rather than
                        # spin forever
                        break
                    seen.add(path)
                    label = path.rsplit('/', 1)[-1] or path
                    depth = max(0, path.count('/') - 1)
                    entries.append((path, label, depth))
                    count += 1
            except Exception as e:
                _sword_log.exception('genbook flat walk failed for %s', module_name)

    _GENBOOK_TOC_CACHE[module_name] = entries
    return entries


def load_genbook_entry(module_name, path):
    """Render the Generic Book entry at the given TreeKey path. Returns
    the rendered HTML string, or '' on failure. Uses setKeyText (which
    works on the base SWKey regardless of binding variant) instead of
    constructing a fresh TreeKey."""
    if not path:
        return ''
    with _lock:
        mod = mgr().getModule(module_name)
        if mod is None:
            return ''
        try:
            mod.setKeyText(path)
            return str(mod.renderText())
        except Exception as e:
            _sword_log.exception('genbook load failed for %s %r', module_name, path)
            return ''


_OSIS_BOOKS = {
    'Gen': 'Genesis', 'Exod': 'Exodus', 'Lev': 'Leviticus', 'Num': 'Numbers',
    'Deut': 'Deuteronomy', 'Josh': 'Joshua', 'Judg': 'Judges', 'Ruth': 'Ruth',
    '1Sam': '1 Samuel', '2Sam': '2 Samuel', '1Kgs': '1 Kings', '2Kgs': '2 Kings',
    '1Chr': '1 Chronicles', '2Chr': '2 Chronicles', 'Ezra': 'Ezra', 'Neh': 'Nehemiah',
    'Esth': 'Esther', 'Job': 'Job', 'Ps': 'Psalms', 'Prov': 'Proverbs',
    'Eccl': 'Ecclesiastes', 'Song': 'Song of Solomon', 'Isa': 'Isaiah',
    'Jer': 'Jeremiah', 'Lam': 'Lamentations', 'Ezek': 'Ezekiel', 'Dan': 'Daniel',
    'Hos': 'Hosea', 'Joel': 'Joel', 'Amos': 'Amos', 'Obad': 'Obadiah',
    'Jonah': 'Jonah', 'Mic': 'Micah', 'Nah': 'Nahum', 'Hab': 'Habakkuk',
    'Zeph': 'Zephaniah', 'Hag': 'Haggai', 'Zech': 'Zechariah', 'Mal': 'Malachi',
    'Matt': 'Matthew', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John',
    'Acts': 'Acts', 'Rom': 'Romans', '1Cor': '1 Corinthians', '2Cor': '2 Corinthians',
    'Gal': 'Galatians', 'Eph': 'Ephesians', 'Phil': 'Philippians', 'Col': 'Colossians',
    '1Thess': '1 Thessalonians', '2Thess': '2 Thessalonians', '1Tim': '1 Timothy',
    '2Tim': '2 Timothy', 'Titus': 'Titus', 'Phlm': 'Philemon', 'Heb': 'Hebrews',
    'Jas': 'James', '1Pet': '1 Peter', '2Pet': '2 Peter', '1John': '1 John',
    '2John': '2 John', '3John': '3 John', 'Jude': 'Jude', 'Rev': 'Revelation',
}


def get_devotional_raw(module_name, date_obj=None):
    """Return raw OSIS XML for a devotional entry (uses getRawEntry). Returns '' if not found."""
    from datetime import date as _date
    if date_obj is None:
        date_obj = _date.today()
    day = date_obj.day
    mon = date_obj.strftime('%b')
    fmts = [date_obj.strftime('%m.%d'),
            f'{mon} {day}', f'{mon}. {day}',
            date_obj.strftime('%m/%d'),
            f'{date_obj.month}/{day}']
    with _lock:
        # Fresh SWMgr per call: a failed setKeyText on one format corrupts the
        # module key state for subsequent attempts (same bug as lookup_dict_word).
        try:
            fresh_mgr = Sword.SWMgr()
        except Exception:
            return ''
        mod = fresh_mgr.getModule(module_name)
        if mod is None:
            return ''
        for fmt in fmts:
            try:
                mod.setKeyText(fmt)
                text = str(mod.getRawEntry()).strip()
                if len(text) > 20:
                    return text
            except Exception:
                pass
    return ''


def parse_osis_ref(osis_ref):
    """Parse 'Bible:Eph.1.3' or 'Eph.1.3' → ('Ephesians', 1, 3), or None
    on failure. Ranges like 'Rom.11.1-Rom.11.5' collapse to the start
    verse, which is enough for cross-pane navigation — the user can
    page forward from there."""
    ref = osis_ref.strip()
    if ref.startswith('Bible:'):
        ref = ref[6:]
    # Clip any range / list to the first reference. SWORD encodes
    # range endpoints with '-' and grouped references with space.
    for sep in ('-', ' ', ','):
        if sep in ref:
            ref = ref.split(sep, 1)[0]
            break
    parts = ref.split('.')
    if len(parts) < 3:
        return None
    book = _OSIS_BOOKS.get(parts[0])
    if not book:
        return None
    try:
        return (book, int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def parse_devotional_refs(raw_osis):
    """Return (book, chapter, verse) from the first osisRef in raw_osis, or None."""
    m = re.search(r'<reference[^>]+osisRef="([^"]+)"', raw_osis)
    if not m:
        return None
    return parse_osis_ref(m.group(1))


_DICT_SKIP = frozenset([
    'strongshebrew', 'strongsgreek', 'morphgnt', 'oshb', 'tsk',
])


def installed_dict_modules():
    """Return [(name, description)] for installed English dictionary/encyclopedia modules."""
    result = []
    for name in module_names():
        if name.lower() in _DICT_SKIP:
            continue
        if is_devotional_module(name):
            continue
        mod = mgr().getModule(name)
        if mod is None:
            continue
        t = str(mod.getType() or '')
        if 'Lexicon' not in t and 'Dict' not in t:
            continue
        lang = str(mod.getConfigEntry('Lang') or '').strip().lower()
        if lang and lang not in ('en', 'eng', 'english'):
            continue
        desc = str(mod.getConfigEntry('Description') or name)
        result.append((name, desc))
    return result


def _dict_candidates(word):
    """Return lookup key variants: exact case forms first, then de-inflected singular forms."""
    w = word.lower()
    exact = []
    seen = set()
    for v in [word, word.upper(), word.capitalize(), word.lower(), word.title()]:
        if v not in seen:
            exact.append(v)
            seen.add(v)

    stems = []
    if w.endswith('ies') and len(w) > 4:
        stems.append(w[:-3] + 'y')       # prophecies → prophecy
    if w.endswith('ves') and len(w) > 4:
        stems.append(w[:-3] + 'f')       # loaves → loaf
    if w.endswith('es') and len(w) > 4:
        stems.append(w[:-2])             # churches → church
    if w.endswith('s') and len(w) > 3 and not w.endswith('ss'):
        stems.append(w[:-1])             # sins → sin
    if w.endswith('ing') and len(w) > 5:
        stems.append(w[:-3])             # praying → pray
        stems.append(w[:-3] + 'e')       # loving → love
    if w.endswith('ed') and len(w) > 4:
        stems.append(w[:-2])             # prayed → pray
        stems.append(w[:-1])             # loved → love

    extra = []
    for s in stems:
        for v in [s.capitalize(), s.upper(), s]:
            if v not in seen:
                extra.append(v)
                seen.add(v)
    return exact + extra


def lookup_dict_word(module_name, word):
    """Look up word in a SWORD dictionary module. Returns raw HTML or '' on miss."""
    with _lock:
        # Fresh SWMgr per call: a failed setKeyText corrupts the module's key
        # state and prevents subsequent lookups in the same module object.
        fresh_mgr = Sword.SWMgr()
        mod = fresh_mgr.getModule(module_name)
        if mod is None:
            return ''
        for variant in _dict_candidates(word):
            try:
                mod.setKeyText(variant)
                actual = str(mod.getKeyText()).strip()
                # getRawEntry() called unconditionally: it clears SWORD's internal
                # error state after a failed setKeyText, allowing subsequent variants
                # (e.g. 'CHRIST' after 'Christ' fails) to reposition correctly.
                text = str(mod.getRawEntry()).strip()
                if actual.lower() == variant.lower() and text:
                    return text
            except Exception:
                pass
    return ''


def load_devotional(module_name, date_obj=None):
    """Load a devotional entry for date_obj (today if None). Returns HTML string."""
    from datetime import date as _date
    if date_obj is None:
        date_obj = _date.today()
    day = date_obj.day
    mon = date_obj.strftime('%b')
    fmts = [date_obj.strftime('%m.%d'),        # "05.09" — SME / OSIS style
            f'{mon} {day}', f'{mon}. {day}',   # "May 9", "May. 9"
            date_obj.strftime('%m/%d'),         # "05/09"
            f'{date_obj.month}/{day}']         # "5/9"
    with _lock:
        # Fresh SWMgr per call: see get_devotional_raw for the same bug.
        try:
            fresh_mgr = Sword.SWMgr()
        except Exception:
            return ''
        mod = fresh_mgr.getModule(module_name)
        if mod is None:
            return ''
        for fmt in fmts:
            try:
                mod.setKeyText(fmt)
                text = str(mod.renderText()).strip()
                if len(text) > 20:
                    return text
            except Exception:
                pass
    return ''


# ── Module manager ────────────────────────────────────────────────────────────

def _shadow_path():
    """Find the locally cached CrossWire module list directory.

    SWORD stores the remote catalogue in a timestamp-named subdirectory
    of ~/.sword/InstallMgr/ (e.g. 20081216195754/) rather than the
    RemoteSources/CrossWire/ path used by older versions.
    """
    base = os.path.expanduser('~/.sword/InstallMgr')
    if not os.path.isdir(base):
        return None

    timestamp_re = re.compile(r'^\d{14}$')
    candidates = []
    for d in os.listdir(base):
        full = os.path.join(base, d)
        mods_d = os.path.join(full, 'mods.d')
        if os.path.isdir(mods_d) and timestamp_re.match(d):
            confs = [f for f in os.listdir(mods_d) if f.endswith('.conf')]
            if confs:
                candidates.append((d, full))

    if candidates:
        candidates.sort(reverse=True)  # most recent timestamp first
        return candidates[0][1]
    return None


_CROSSWIRE_HTTP = 'https://crosswire.org/ftpmirror/pub/sword/packages/rawzip'
_SWORD_PATH = os.path.expanduser('~/.sword')


def _parse_conf(path):
    """Return dict of name/description/type from a SWORD .conf file."""
    info = {}
    try:
        # utf-8-sig strips a leading BOM that would otherwise break the
        # `[Module]` header detection on the first line.
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            raw_lines = f.readlines()
    except OSError:
        return info

    # SWORD .conf permits `\` at end of line for continuation — join them up.
    lines = []
    pending = ''
    for raw in raw_lines:
        s = raw.rstrip('\n').rstrip('\r')
        if s.endswith('\\'):
            pending += s[:-1]
            continue
        if pending:
            s = pending + s
            pending = ''
        lines.append(s)
    if pending:
        lines.append(pending)

    for line in lines:
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            info['name'] = line[1:-1]
        elif '=' in line:
            key, _, val = line.partition('=')
            k = key.strip().lower()
            v = val.strip()
            if k == 'description':
                info['description'] = v
            elif k == 'category':
                info['category'] = v
            elif k == 'lcsh':
                info['lcsh'] = v
            elif k == 'moddrv':
                info['moddrv'] = v
            elif k == 'datapath':
                info['datapath'] = v
            elif k == 'lang':
                info['lang'] = v
            elif k == 'feature':
                info.setdefault('features', set()).add(v)
    return info


def list_available_modules():
    """Read available modules by parsing .conf files from the local shadow."""
    path = _shadow_path()
    if not path:
        raise FileNotFoundError('No module list cached yet — click Refresh first.')
    mods_d = os.path.join(path, 'mods.d')
    installed = set(module_names())
    result = []
    for filename in os.listdir(mods_d):
        if not filename.endswith('.conf'):
            continue
        info = _parse_conf(os.path.join(mods_d, filename))
        name = info.get('name')
        if name:
            # Infer category if missing
            cat = info.get('category', '')
            lcsh = info.get('lcsh', '')
            drv = info.get('moddrv', '')

            if not cat:
                if 'Bible' in lcsh:
                    if 'Commentary' in lcsh:
                        cat = 'Commentaries'
                    else:
                        cat = 'Biblical Texts'
                elif 'Lexicon' in lcsh or 'Dictionary' in lcsh:
                    cat = 'Lexicons / Dictionaries'
                elif drv in ('RawText', 'zText', 'OldzText'):
                    cat = 'Biblical Texts'
                elif drv in ('RawCom', 'zCom'):
                    cat = 'Commentaries'
                elif drv in ('RawLD', 'zLD'):
                    cat = 'Lexicons / Dictionaries'
                elif 'Daily Devotional' in info.get('description', ''):
                    cat = 'Daily Devotional'
                else:
                    cat = 'Generic Books'

            # Standardize common category names
            if 'Bible' in cat and 'Texts' not in cat:
                cat = 'Biblical Texts'

            result.append({
                'name': name,
                'description': info.get('description', ''),
                'type': cat,
                'lang': info.get('lang', ''),
                'features': info.get('features', set()),
                'installed': name in installed,
            })
    return sorted(result, key=lambda m: m['name'].lower())


_CROSSWIRE_CATALOG = 'https://crosswire.org/ftpmirror/pub/sword/raw/mods.d.tar.gz'


def refresh_source():
    """Download the CrossWire module catalogue and store in a new shadow dir."""
    from datetime import datetime
    url = _CROSSWIRE_CATALOG
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()

    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    mods_d = os.path.expanduser(f'~/.sword/InstallMgr/{ts}/mods.d')
    os.makedirs(mods_d, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        for member in tar.getmembers():
            if member.name.endswith('.conf') and not member.isdir():
                member.name = os.path.basename(member.name)
                tar.extract(member, mods_d)


def install_module(module_name):
    """Download module zip from CrossWire and extract into ~/.sword/."""
    url = f'{_CROSSWIRE_HTTP}/{module_name}.zip'
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(_SWORD_PATH)
    _reset()


def remove_module(module_name):
    """Delete module conf and data files from ~/.sword/."""
    conf = os.path.join(_SWORD_PATH, 'mods.d', f'{module_name.lower()}.conf')
    if not os.path.exists(conf):
        # Check if it's a system-installed module we can't touch
        sys_conf = os.path.join('/usr/share/sword/mods.d', f'{module_name.lower()}.conf')
        if os.path.exists(sys_conf):
            raise RuntimeError(f'{module_name} is a system-installed module and cannot be removed here.')
        raise RuntimeError(f'Module conf not found: {conf}')
    info = _parse_conf(conf)
    data_path = info.get('datapath', '').lstrip('./')
    if data_path:
        full = os.path.join(_SWORD_PATH, data_path)
        if os.path.isdir(full):
            shutil.rmtree(full)
    os.remove(conf)
    
    # Delete the associated Whoosh index
    idx_path = _get_index_path(module_name)
    if os.path.exists(idx_path):
        shutil.rmtree(idx_path)
    
    _reset()


_ALL_BOOKS = [
    'Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy',
    'Joshua', 'Judges', 'Ruth', '1 Samuel', '2 Samuel',
    '1 Kings', '2 Kings', '1 Chronicles', '2 Chronicles',
    'Ezra', 'Nehemiah', 'Esther', 'Job', 'Psalms', 'Proverbs',
    'Ecclesiastes', 'Song of Solomon', 'Isaiah', 'Jeremiah',
    'Lamentations', 'Ezekiel', 'Daniel', 'Hosea', 'Joel', 'Amos',
    'Obadiah', 'Jonah', 'Micah', 'Nahum', 'Habakkuk', 'Zephaniah',
    'Haggai', 'Zechariah', 'Malachi',
    'Matthew', 'Mark', 'Luke', 'John', 'Acts', 'Romans',
    '1 Corinthians', '2 Corinthians', 'Galatians', 'Ephesians',
    'Philippians', 'Colossians', '1 Thessalonians', '2 Thessalonians',
    '1 Timothy', '2 Timothy', 'Titus', 'Philemon', 'Hebrews',
    'James', '1 Peter', '2 Peter', '1 John', '2 John', '3 John',
    'Jude', 'Revelation',
]





def search_module(module_name, query, on_indexing_start=None,
                  on_indexing_done=None, on_indexing_progress=None,
                  case_sensitive=False):
    """
    Search a module using Whoosh. Builds index if it doesn't exist or is outdated.
    Returns [(book, chapter, verse, plain_text)]
    """
    query_stripped = query.strip()
    if not query_stripped:
        return []

    idx_path = _get_index_path(module_name)
    w = _whoosh_load()

    # Check if index exists and is valid
    index_exists = w['exists_in'](idx_path)
    index_needs_rebuild = False
    if index_exists:
        try:
            ix = w['open_dir'](idx_path)
            if ix.schema != _bible_schema(): # Schema changed, need rebuild
                ix.close()
                index_needs_rebuild = True
            else:
                ix.close()
        except Exception: # Index corrupt, need rebuild
            index_needs_rebuild = True
            
    if not index_exists or index_needs_rebuild:
        # Atomic check-and-spawn: two concurrent searches must not both
        # rmtree+create_in the same index dir. Hold _indexing_lock only for the
        # dict op, never during the long-running join below.
        started_here = False
        with _indexing_lock:
            existing = _indexing_threads.get(module_name)
            if existing is None or not existing.is_alive():
                thread = threading.Thread(
                    target=_build_module_index,
                    args=(module_name,),
                    kwargs={'on_progress': on_indexing_progress},
                    daemon=True
                )
                _indexing_threads[module_name] = thread
                started_here = True
            else:
                thread = existing

        if started_here:
            if on_indexing_start:
                on_indexing_start()
            thread.start()

        # Wait for the indexing thread to complete — lock released during join.
        thread.join()

        with _indexing_lock:
            # Only remove if it's still our thread (a later search may have
            # spawned a fresh one after we noticed this one finished).
            if _indexing_threads.get(module_name) is thread:
                _indexing_threads.pop(module_name, None)

        if on_indexing_done:
            on_indexing_done()

        if not w['exists_in'](idx_path):
            return []

    # Perform search
    try:
        ix = w['open_dir'](idx_path)
        with ix.searcher() as searcher:
            parser = w['QueryParser']("content", ix.schema)
            parsed_query = parser.parse(query_stripped)
            results = searcher.search(parsed_query, limit=MAX_SEARCH_RESULTS)
            formatted = [(h['book'], h['chapter'], h['verse'], h['content'])
                         for h in results]
            truncated = None
            if len(results) == MAX_SEARCH_RESULTS:
                truncated = ('', 0, 0,
                    f'Showing first {MAX_SEARCH_RESULTS} results — try a more specific search.')
            # Whoosh's StandardAnalyzer lowercases at index time, so the
            # query is always case-insensitive. For a case-sensitive match
            # we post-filter the result content (which is stored verbatim)
            # for the original-case query string.
            if case_sensitive and query_stripped:
                cs_words = query_stripped.split()
                formatted = [r for r in formatted
                             if all(w in (r[3] or '') for w in cs_words)]
            if truncated is not None:
                formatted.append(truncated)
            return formatted
    except Exception as e:
        _search_log.exception('Whoosh error')
        return []


_CROSS_REF_ABBREVS = {
    # OT
    'ge': 'Genesis', 'gen': 'Genesis',
    'ex': 'Exodus', 'exo': 'Exodus', 'exod': 'Exodus',
    'le': 'Leviticus', 'lev': 'Leviticus',
    'nu': 'Numbers', 'num': 'Numbers',
    'de': 'Deuteronomy', 'deu': 'Deuteronomy', 'deut': 'Deuteronomy',
    'jos': 'Joshua', 'josh': 'Joshua',
    'jud': 'Judges', 'judg': 'Judges', 'jg': 'Judges',
    'ru': 'Ruth', 'rut': 'Ruth',
    '1sa': '1 Samuel', '1sam': '1 Samuel',
    '2sa': '2 Samuel', '2sam': '2 Samuel',
    '1ki': '1 Kings', '1kin': '1 Kings', '1kgs': '1 Kings',
    '2ki': '2 Kings', '2kin': '2 Kings', '2kgs': '2 Kings',
    '1ch': '1 Chronicles', '1chr': '1 Chronicles', '1chron': '1 Chronicles',
    '2ch': '2 Chronicles', '2chr': '2 Chronicles', '2chron': '2 Chronicles',
    'ezr': 'Ezra',
    'ne': 'Nehemiah', 'neh': 'Nehemiah',
    'es': 'Esther', 'est': 'Esther', 'esth': 'Esther',
    'job': 'Job',
    'ps': 'Psalms', 'psa': 'Psalms', 'pss': 'Psalms',
    'pr': 'Proverbs', 'pro': 'Proverbs', 'prov': 'Proverbs',
    'ec': 'Ecclesiastes', 'ecc': 'Ecclesiastes', 'eccl': 'Ecclesiastes',
    'so': 'Song of Solomon', 'sos': 'Song of Solomon', 'sg': 'Song of Solomon',
    'song': 'Song of Solomon', 'sol': 'Song of Solomon',
    'isa': 'Isaiah', 'is': 'Isaiah',
    'jer': 'Jeremiah',
    'la': 'Lamentations', 'lam': 'Lamentations',
    'eze': 'Ezekiel', 'ezek': 'Ezekiel',
    'da': 'Daniel', 'dan': 'Daniel',
    'ho': 'Hosea', 'hos': 'Hosea',
    'joe': 'Joel', 'jl': 'Joel',
    'am': 'Amos', 'amo': 'Amos',
    'ob': 'Obadiah', 'oba': 'Obadiah',
    'jon': 'Jonah',
    'mic': 'Micah',
    'na': 'Nahum', 'nah': 'Nahum',
    'hab': 'Habakkuk',
    'zep': 'Zephaniah', 'zeph': 'Zephaniah',
    'hag': 'Haggai',
    'zec': 'Zechariah', 'zech': 'Zechariah',
    'mal': 'Malachi',
    # NT
    'mt': 'Matthew', 'mat': 'Matthew', 'matt': 'Matthew',
    'mr': 'Mark', 'mar': 'Mark', 'mk': 'Mark',
    'lu': 'Luke', 'luk': 'Luke', 'lk': 'Luke',
    'joh': 'John', 'jn': 'John',
    'ac': 'Acts', 'act': 'Acts',
    'ro': 'Romans', 'rom': 'Romans',
    '1co': '1 Corinthians', '1cor': '1 Corinthians',
    '2co': '2 Corinthians', '2cor': '2 Corinthians',
    'ga': 'Galatians', 'gal': 'Galatians',
    'eph': 'Ephesians',
    'php': 'Philippians', 'phi': 'Philippians', 'phil': 'Philippians',
    'col': 'Colossians',
    '1th': '1 Thessalonians', '1the': '1 Thessalonians', '1thes': '1 Thessalonians',
    '2th': '2 Thessalonians', '2the': '2 Thessalonians', '2thes': '2 Thessalonians',
    '1ti': '1 Timothy', '1tim': '1 Timothy',
    '2ti': '2 Timothy', '2tim': '2 Timothy',
    'tit': 'Titus',
    'phm': 'Philemon', 'phlm': 'Philemon',
    'heb': 'Hebrews',
    'jas': 'James', 'jam': 'James',
    '1pe': '1 Peter', '1pet': '1 Peter',
    '2pe': '2 Peter', '2pet': '2 Peter',
    '1jo': '1 John', '1jn': '1 John',
    '2jo': '2 John', '2jn': '2 John',
    '3jo': '3 John', '3jn': '3 John',
    'jude': 'Jude',
    're': 'Revelation', 'rev': 'Revelation',
}


def _parse_cross_ref_text(text):
    """Parse TSK-style text (e.g. 'Ge 1:2; Ps 33:6; 136:5; 1Jn 5:7-8') into
    a list of (book, chapter, verse, label) tuples."""
    refs = []
    current_book = None
    current_chapter = None
    current_abbrev = None

    def _emit_tail(tail, book, chapter, abbrev, start_v):
        """Parse a reference tail for ranges ('-8'/'–8') and comma extras (', 5, 8')."""
        # Hyphen/en-dash range immediately after the main verse: '-8' → emit v+1..8
        range_m = re.match(r'^\s*[-–]\s*(\d+)', tail)
        if range_m:
            try:
                end_v = int(range_m.group(1))
                # Cap to prevent runaway emit on e.g. "Ps 119:1-176"
                for vv in range(start_v + 1, min(end_v + 1, start_v + 200)):
                    refs.append((book, chapter, vv, f'{abbrev} {chapter}:{vv}'))
            except ValueError:
                pass
            tail = tail[range_m.end():]
        # Additional verses: ", 5, 8" (the (?!:) lookahead avoids consuming chapter starts)
        for extra in re.findall(r',\s*(\d+)(?!:)', tail):
            refs.append((book, chapter, int(extra), f'{abbrev} {chapter}:{extra}'))

    for seg in re.split(r';', text):
        seg = seg.strip().strip('.')
        if not seg:
            continue

        # Full reference: "Ge 1:1", "1Co 3:16", "Song 1:1"
        m = re.match(r'^((?:\d\s*)?[A-Za-z]+\.?)\s+(\d+):(\d+)(.*)', seg)
        if m:
            raw = m.group(1).rstrip('.')
            key = raw.replace(' ', '').lower()
            book_full = _CROSS_REF_ABBREVS.get(key)
            if book_full:
                current_book = book_full
                current_chapter = int(m.group(2))
                current_abbrev = raw
                v = int(m.group(3))
                refs.append((book_full, current_chapter, v,
                             f'{raw} {current_chapter}:{v}'))
                _emit_tail(m.group(4), book_full, current_chapter, raw, v)
            continue

        if not current_book:
            continue

        # Same-book new chapter: "136:5"
        m2 = re.match(r'^(\d+):(\d+)(.*)', seg)
        if m2:
            current_chapter = int(m2.group(1))
            v = int(m2.group(2))
            refs.append((current_book, current_chapter, v,
                         f'{current_abbrev} {current_chapter}:{v}'))
            _emit_tail(m2.group(3), current_book, current_chapter, current_abbrev, v)
            continue

        # Bare verse numbers: same book and chapter
        for v_str in re.findall(r'\b(\d+)\b', seg):
            refs.append((current_book, current_chapter, int(v_str),
                         f'{current_abbrev} {current_chapter}:{v_str}'))

    return refs


def get_cross_refs(book, chapter, verse):
    """Return [(book, chapter, verse, label), ...]. Uses OpenBible if downloaded, else TSK."""
    import open_data
    ob = open_data.get_cross_refs(book, chapter, verse)
    if ob is not None:
        return ob

    # Fall back to TSK
    installed = module_names()
    tsk_mod = next((m for m in installed if m.upper() == 'TSK'), None)
    if not tsk_mod:
        return None

    with _lock:
        mod = mgr().getModule(tsk_mod)
        if mod is None:
            return None
        vk = Sword.VerseKey()
        vk.setText(f'{book} {chapter}:{verse}')
        mod.setKey(vk)
        raw = str(mod.renderText())

    plain = re.sub(r'<[^>]+>', ' ', raw)
    plain = re.sub(r'\s+', ' ', plain).strip()
    return _parse_cross_ref_text(plain)


_HEB_POS = {
    'A': 'Adjective', 'C': 'Conjunction', 'D': 'Adverb', 'N': 'Noun',
    'P': 'Pronoun', 'R': 'Preposition', 'S': 'Suffix', 'T': 'Particle', 'V': 'Verb',
}
_HEB_VERB_STEM = {
    'q': 'Qal', 'N': 'Niphal', 'p': 'Piel', 'P': 'Pual',
    'h': 'Hiphil', 'H': 'Hophal', 't': 'Hitpael', 'o': 'Polel',
    'O': 'Polal', 'r': 'Hithpolel', 'm': 'Poel', 'M': 'Poal',
    'k': 'Palel', 'K': 'Pulal', 'Q': 'Qal passive', 'l': 'Pilpel',
    'L': 'Polpal', 'f': 'Hithpalpel', 'D': 'Nithpael', 'j': 'Pealal',
    'i': 'Pilel', 'u': 'Hothpaal', 'c': 'Tiphil', 'v': 'Shaphel',
}
_HEB_VERB_ASPECT = {
    'p': 'Perfect', 'i': 'Imperfect', 'h': 'Cohortative', 'j': 'Jussive',
    'v': 'Vav-consecutive', 'w': 'Waw-consecutive',
    'r': 'Imperative', 'c': 'Infinitive Construct', 'a': 'Infinitive Absolute',
    's': 'Active Participle', 'S': 'Passive Participle',
}
_HEB_PERSON       = {'1': '1st Person', '2': '2nd Person', '3': '3rd Person'}
_HEB_GENDER       = {'m': 'Masculine', 'f': 'Feminine', 'c': 'Common', 'b': 'Both'}
_HEB_NUMBER       = {'s': 'Singular', 'p': 'Plural', 'd': 'Dual'}
_HEB_STATE        = {'a': 'Absolute', 'c': 'Construct', 'd': 'Determined'}
_HEB_NOUN_TYPE    = {'c': '', 'p': 'Proper'}
_HEB_ADJ_TYPE     = {'a': '', 'c': 'Cardinal', 'g': 'Gentilic', 'o': 'Ordinal'}
_HEB_PRON_TYPE    = {
    'd': 'Demonstrative', 'f': 'Reflexive', 'i': 'Interrogative',
    'p': 'Personal', 'r': 'Relative', 'x': 'Indefinite',
}
_HEB_PARTICLE_TYPE = {
    'a': 'Affirmation', 'd': 'Definite Article', 'e': 'Exhortation',
    'f': 'Negative', 'i': 'Interrogative', 'j': 'Interjection',
    'm': 'Demonstrative', 'n': 'Negative', 'o': 'Object Marker',
}


def _decode_one_heb(morph):
    code = morph
    for prefix in ('oshm:', 'WLC:'):
        if morph.startswith(prefix):
            code = morph[len(prefix):]
            break
    code = re.sub(r'^[HA][^/]*/', '', code)   # strip H/A + prefix letters + /
    if code and code[0] in 'HA' and '/' not in code:
        code = code[1:]                         # bare H/A with no slash (no prefix word)
    if not code:
        return None
    pos = code[0]
    rest = code[1:]
    pos_name = _HEB_POS.get(pos)
    if not pos_name:
        return None
    tokens = [pos_name]
    if pos == 'V':
        stem = rest[0:1]; aspect = rest[1:2]
        person = rest[2:3]; gender = rest[3:4]; number = rest[4:5]
        if stem:   tokens.append(_HEB_VERB_STEM.get(stem, stem))
        if aspect: tokens.append(_HEB_VERB_ASPECT.get(aspect, aspect))
        if person: tokens.append(_HEB_PERSON.get(person, ''))
        if gender: tokens.append(_HEB_GENDER.get(gender, ''))
        if number: tokens.append(_HEB_NUMBER.get(number, ''))
    elif pos == 'N':
        idx = 0
        if rest and rest[0] in 'cp':
            ntype = _HEB_NOUN_TYPE.get(rest[0], '')
            if ntype: tokens.append(ntype)
            idx = 1
        gender = rest[idx:idx+1]; number = rest[idx+1:idx+2]; state = rest[idx+2:idx+3]
        if gender: tokens.append(_HEB_GENDER.get(gender, ''))
        if number: tokens.append(_HEB_NUMBER.get(number, ''))
        if state:  tokens.append(_HEB_STATE.get(state, ''))
    elif pos == 'A':
        idx = 0
        if rest and rest[0] in 'acgo':
            atype = _HEB_ADJ_TYPE.get(rest[0], '')
            if atype: tokens.append(atype)
            idx = 1
        gender = rest[idx:idx+1]; number = rest[idx+1:idx+2]; state = rest[idx+2:idx+3]
        if gender: tokens.append(_HEB_GENDER.get(gender, ''))
        if number: tokens.append(_HEB_NUMBER.get(number, ''))
        if state:  tokens.append(_HEB_STATE.get(state, ''))
    elif pos == 'P':
        idx = 0
        if rest and rest[0] in 'dfipqrx':
            tokens.append(_HEB_PRON_TYPE.get(rest[0], rest[0]))
            idx = 1
        person = rest[idx:idx+1]; gender = rest[idx+1:idx+2]; number = rest[idx+2:idx+3]
        if person: tokens.append(_HEB_PERSON.get(person, ''))
        if gender: tokens.append(_HEB_GENDER.get(gender, ''))
        if number: tokens.append(_HEB_NUMBER.get(number, ''))
    elif pos == 'S':
        person = rest[0:1]; gender = rest[1:2]; number = rest[2:3]
        if person: tokens.append(_HEB_PERSON.get(person, ''))
        if gender: tokens.append(_HEB_GENDER.get(gender, ''))
        if number: tokens.append(_HEB_NUMBER.get(number, ''))
    elif pos == 'T':
        ttype = rest[0:1]
        if ttype: tokens.append(_HEB_PARTICLE_TYPE.get(ttype, ttype))
    elif pos == 'R':
        if rest and rest[0] == 'd':
            tokens.append('Definite Article')
    return ' · '.join(t for t in tokens if t) or None


def decode_hebrew_morph(morph):
    if not morph:
        return None
    parts = [_decode_one_heb(p) for p in morph.split()]
    parts = [p for p in parts if p]
    return ' + '.join(parts) or None


def lookup_morph_for_strong_heb(book, chapter, verse, strong_num):
    def _norm(s):
        return s[0].upper() + (s[1:].lstrip('0') or '0')
    with _lock:
        mod = mgr().getModule('OSHB')
        if not mod:
            return None
        try:
            vk = Sword.VerseKey(f'{book} {chapter}:{verse}')
            mod.setKey(vk)
            raw = str(mod.getRawEntry())
        except Exception:
            return None
    target = _norm(strong_num)
    for m in re.finditer(r'<w\s([^>]*)>', raw):
        attrs = m.group(1)
        lemma_m = re.search(r'lemma="([^"]*)"', attrs, re.IGNORECASE)
        if not lemma_m:
            continue
        strongs = re.findall(r'[Ss]trong:([GHgh]\d+)', lemma_m.group(1))
        normed = [_norm(s) for s in strongs]
        if target not in normed:
            continue
        morph_m = re.search(r'morph="([^"]*)"', attrs)
        if not morph_m:
            continue
        parts = morph_m.group(1).split()
        idx = normed.index(target)
        return parts[idx] if idx < len(parts) else (parts[0] if parts else None)
    return None


_ROB_POS = {
    'N': 'Noun', 'V': 'Verb', 'ADJ': 'Adjective', 'A': 'Adjective',
    'ADV': 'Adverb', 'CONJ': 'Conjunction', 'PREP': 'Preposition',
    'PRT': 'Particle', 'PRT-N': 'Negative Particle', 'INJ': 'Interjection',
    'COND': 'Conditional', 'T': 'Article', 'P': 'Personal Pronoun',
    'R': 'Relative Pronoun', 'C': 'Reciprocal Pronoun',
    'D': 'Demonstrative Pronoun', 'K': 'Correlative Pronoun',
    'I': 'Interrogative Pronoun', 'X': 'Indefinite Pronoun',
    'Q': 'Correlative/Interrogative Pronoun', 'F': 'Reflexive Pronoun',
    'S': 'Possessive Pronoun',
}
_ROB_TENSE = {
    'P': 'Present', 'I': 'Imperfect', 'F': 'Future', '2F': '2nd Future',
    'A': 'Aorist', '2A': '2nd Aorist', 'R': 'Perfect', '2R': '2nd Perfect',
    'L': 'Pluperfect', '2L': '2nd Pluperfect', 'FP': 'Future Perfect',
}
_ROB_VOICE = {
    'A': 'Active', 'M': 'Middle', 'P': 'Passive', 'D': 'Middle Deponent',
    'O': 'Passive Deponent', 'N': 'Middle/Passive Deponent', 'E': 'Middle or Passive',
}
_ROB_MOOD   = {'I': 'Indicative', 'S': 'Subjunctive', 'O': 'Optative',
               'M': 'Imperative', 'N': 'Infinitive', 'P': 'Participle'}
_ROB_CASE   = {'N': 'Nominative', 'G': 'Genitive', 'D': 'Dative',
               'A': 'Accusative', 'V': 'Vocative'}
_ROB_NUMBER = {'S': 'Singular', 'P': 'Plural'}
_ROB_GENDER = {'M': 'Masculine', 'F': 'Feminine', 'N': 'Neuter'}
_ROB_PERSON = {'1': '1st', '2': '2nd', '3': '3rd'}


def decode_robinson(morph):
    """Decode a robinson:XXX morph tag to a readable string, e.g. 'Verb · Aorist · Active · Indicative · 3rd Person · Singular'."""
    if not morph or 'robinson:' not in morph:
        return None
    code   = morph.split('robinson:')[-1].strip()
    parts  = code.split('-')
    pos_raw, fields = parts[0], parts[1:]

    tokens = [_ROB_POS.get(pos_raw, pos_raw)]

    if pos_raw == 'V' and fields:
        raw = fields[0]
        t_key = next((p for p in ('2A', '2F', '2R', '2L', 'FP') if raw.startswith(p)), None)
        if t_key:
            tail = raw[len(t_key):]
        else:
            t_key = raw[:1]
            tail  = raw[1:]
        v_key  = tail[:1]
        mo_key = tail[1:2]

        if t_key:  tokens.append(_ROB_TENSE.get(t_key, t_key))
        if v_key:  tokens.append(_ROB_VOICE.get(v_key, v_key))
        if mo_key: tokens.append(_ROB_MOOD.get(mo_key, mo_key))

        if len(fields) > 1:
            extra = fields[1]
            if mo_key == 'P' and len(extra) >= 3:
                tokens.append(_ROB_CASE.get(extra[0], extra[0]))
                tokens.append(_ROB_NUMBER.get(extra[1], extra[1]))
                tokens.append(_ROB_GENDER.get(extra[2], extra[2]))
            elif len(extra) >= 2:
                tokens.append(_ROB_PERSON.get(extra[0], extra[0]) + ' Person')
                tokens.append(_ROB_NUMBER.get(extra[1], extra[1]))
    elif fields:
        cng = fields[0]
        if len(cng) >= 1: tokens.append(_ROB_CASE.get(cng[0], cng[0]))
        if len(cng) >= 2: tokens.append(_ROB_NUMBER.get(cng[1], cng[1]))
        if len(cng) >= 3: tokens.append(_ROB_GENDER.get(cng[2], cng[2]))

    return ' · '.join(t for t in tokens if t) or None


def lookup_morph_for_strong(book, chapter, verse, strong_num):
    """Return the robinson:XXX morph string for a Strong's word in a verse via MorphGNT."""
    with _lock:
        mod = mgr().getModule('MorphGNT')
        if not mod:
            return None
        try:
            vk = Sword.VerseKey(f'{book} {chapter}:{verse}')
            mod.setKey(vk)
            raw = str(mod.getRawEntry())
        except Exception:
            return None
    target = strong_num.upper()
    for m in re.finditer(r'<w\s([^>]*)>', raw):
        attrs = m.group(1)
        # A single <w> tag can carry multiple Strong's (KJV-style markup
        # for collapsed Greek phrases — see _extract_segments). Use
        # findall + membership rather than search + ==, otherwise a
        # match for the SECOND Strong's would be silently missed.
        nums = [n.upper() for n in re.findall(r'strong:([GH]\d+)', attrs)]
        if target in nums:
            mm = re.search(r'morph="([^"]*)"', attrs)
            if mm:
                return mm.group(1)
    return None


def count_strong_occurrences(module_name, strong_num, book=None):
    """Count verses containing strong_num in book (whole Bible if None)."""
    books = [book] if book else _ALL_BOOKS
    # Negative-lookahead anchor — `strong:G65` must not be followed by
    # another digit. Without it, G65 matches G650 / G651 / G652 / etc.
    # and the count balloons with unrelated verses.
    pattern = re.compile(rf'strong:{re.escape(strong_num)}(?!\d)', re.IGNORECASE)
    count = 0
    for b in books:
        for ch in range(1, chapter_count(b) + 1):
            for _, html in load_chapter(module_name, b, ch):
                if pattern.search(str(html)):
                    count += 1
    return count


def lookup_strong(strong_num):
    """Look up a Strong's definition. strong_num is like 'G3056' or 'H1234'."""
    if not strong_num or len(strong_num) < 2:
        return None

    with _lock:
        if strong_num in _strongs_cache:
            _strongs_cache.move_to_end(strong_num)  # mark as recently used
            return _strongs_cache[strong_num]

    # For Greek words, try Dodson first (cleaner definitions).
    # open_data.lookup_dodson does its own file I/O; don't hold _lock for it.
    import open_data
    letter = strong_num[0].upper()
    if letter == 'G':
        dodson = open_data.lookup_dodson(strong_num)
        if dodson:
            with _lock:
                _cache_strong(strong_num, dodson)
            return dodson

    installed = module_names()
    mod_name = None
    if letter == 'G':
        mod_name = next((m for m in installed if 'Strongs' in m and 'Greek' in m), None)
    elif letter == 'H':
        mod_name = next((m for m in installed if 'Strongs' in m and 'Hebrew' in m), None)

    if not mod_name:
        return None

    with _lock:
        mod = mgr().getModule(mod_name)
        if mod is None:
            return None

        num_bare = strong_num[1:].lstrip('0') or '0'
        # Try multiple key formats: 03056, 3056, etc.
        for key in [num_bare.zfill(5), num_bare.zfill(4), num_bare]:
            try:
                mod.setKeyText(key)
                actual = str(mod.getKeyText())
                text = str(mod.getRawEntry()).strip()
            except Exception:
                continue
            if actual.lstrip('0') == num_bare and text:
                _cache_strong(strong_num, text)
                return text

        # Deliberately NOT caching misses. Previously this stored
        # None to skip future lookups, but it also blocked retries
        # after the user installed a Strong's module that didn't
        # exist when the first click happened. Cost of a re-lookup
        # is a single SWORD module probe (~5 ms) — small enough that
        # always-retrying is the right trade-off.
        return None
