import io
import logging
import os
import re
import shutil
import sqlite3
import tarfile
import threading
import zipfile
from collections import OrderedDict
import Sword

import search_query

_sword_log = logging.getLogger('scriptura.sword')
_search_log = logging.getLogger('scriptura.search')

# InstallMgr shadow dirs are named with a 14-digit timestamp (e.g.
# 20081216195754); both the newest-dir lookup and the prune below match on it.
_TS_DIR_RE = re.compile(r'^\d{14}$')

_mgr = None
# RLock allows reentry: callers like load_chapter hold _lock and then call mgr().
_lock = threading.RLock()

_warm_thread = None


def start_warm():
    """Pay SWORD's one-time versification/locale init (~150 ms — the cost
    of the *first* VerseKey construction; later ones are free) on a
    background thread so it overlaps window construction. The C call runs
    without the GIL (measured), so the main thread keeps building UI.
    Call wait_warm() before the first main-thread SWORD use."""
    global _warm_thread

    def _warm():
        with _lock:
            try:
                Sword.VerseKey().setText('Genesis 1:1')
            except Exception:
                pass

    _warm_thread = threading.Thread(target=_warm, daemon=True)
    _warm_thread.start()


def wait_warm():
    if _warm_thread is not None:
        _warm_thread.join()


# Chapter render cache. OrderedDict + cap = LRU eviction so a long reading
# session that touches the whole canon doesn't grow memory unboundedly.
# 200 chapters × ~50 KB ≈ 10 MB worst case; comfortably above any normal
# session's working set.
_CHAPTER_CACHE_CAP = 200
_cache = OrderedDict()
# Footnotes for the same chapters: {verse: [(marker_index, type, body)]}.
# Filled by the same render pass and evicted in lockstep with _cache
# (every insert goes through _cache_chapter, which writes both).
_notes_cache = OrderedDict()
# Strong's lookup cache — same shape, smaller cap. A typical chapter
# references 30–50 unique Strong's numbers; 500 covers many chapters of
# recent activity before evicting.
_STRONGS_CACHE_CAP = 500
_strongs_cache = OrderedDict()


def _cache_chapter(key, value, notes):
    """Insert a chapter render + its footnotes with LRU eviction (the two
    caches stay in lockstep). Caller holds _lock."""
    _cache[key] = value
    _cache.move_to_end(key)
    _notes_cache[key] = notes
    _notes_cache.move_to_end(key)
    if len(_cache) > _CHAPTER_CACHE_CAP:
        _cache.popitem(last=False)
        _notes_cache.popitem(last=False)


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

FTS_INDEX_DIR = os.path.expanduser('~/.sword/fts5_indexes')
MAX_SEARCH_RESULTS = 5000  # cap result count so a common word can't flood the UI
# Bump when the index schema/tokenizer changes so stale indexes rebuild.
# v2: chapters of versification-mapped modules (Vulg/Synodal psalters…)
# are stored under app-space (KJV) numbers, matching how navigation
# addresses them since the cross-versification mapping landed.
_FTS_INDEX_VERSION = 2


def _get_index_path(module_name):
    # One SQLite/FTS5 file per module. Module names are filename-safe in
    # practice (KJVA, StrongsGreek…); guard against a stray separator anyway.
    safe = module_name.replace(os.sep, '_').replace('/', '_')
    return os.path.join(FTS_INDEX_DIR, safe + '.db')


def _index_is_valid(idx_path):
    """True if a built, current-version FTS5 index exists at idx_path."""
    if not os.path.exists(idx_path):
        return False
    try:
        conn = sqlite3.connect(idx_path)
        try:
            ver = conn.execute('PRAGMA user_version').fetchone()[0]
            conn.execute('SELECT 1 FROM verses LIMIT 1')  # table present?
        finally:
            conn.close()
        return ver == _FTS_INDEX_VERSION
    except Exception:
        return False

def _build_module_index(module_name, on_progress=None):
    """Build a fresh FTS5 index for module_name into a per-module SQLite file.

    `on_progress(book_idx, total_books, book_name)` is invoked on the
    indexing thread once per book; the receiver should marshal to the
    main loop itself (via GLib.idle_add). Indexing a full Bible against
    SWORD typically takes 5-15s (dominated by SWORD's per-verse render);
    per-book ticks give the UI something concrete to display.

    Built into a sibling .tmp and atomically renamed, so a killed build
    leaves the previous index (or nothing) rather than a half-built file."""
    idx_path = _get_index_path(module_name)
    os.makedirs(FTS_INDEX_DIR, exist_ok=True)
    tmp_path = idx_path + '.tmp'
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = None
    try:
        conn = sqlite3.connect(tmp_path)
        # Metadata columns UNINDEXED (stored, not searched); content indexed.
        # unicode61 gives word-boundary, case/diacritic-folded matching, shared
        # with the eBible backend via the search_query grammar.
        conn.execute("CREATE VIRTUAL TABLE verses USING fts5("
                     "book UNINDEXED, chapter UNINDEXED, verse UNINDEXED, "
                     "content, tokenize='unicode61')")
        conn.execute(f'PRAGMA user_version = {_FTS_INDEX_VERSION}')
        total_books = len(_ALL_BOOKS)
        for i, book in enumerate(_ALL_BOOKS, start=1):
            if on_progress:
                try:
                    on_progress(i, total_books, book)
                except Exception:
                    pass
            # App-space iteration bounds: for versification-mapped books
            # chapter_count returns the KJV count and load_chapter
            # translates each chapter, so index rows carry the same
            # app-space numbers navigation uses. Unmapped books keep the
            # module's own count (a KJV-keyed count would under- or
            # over-iterate RusSynodal/Wycliffe).
            book_rows = []
            for ch in range(1, chapter_count(book, module_name) + 1):
                for v_num, html in load_chapter(module_name, book, ch):
                    plain_text = re.sub(r'<[^>]+>', '', str(html))
                    book_rows.append((book, ch, v_num, plain_text))
            # Insert in canonical order so rowid order == verse order, which is
            # the result ordering the UI relies on (no relevance re-sort).
            if book_rows:
                conn.executemany(
                    'INSERT INTO verses(book, chapter, verse, content) '
                    'VALUES (?, ?, ?, ?)', book_rows)
        conn.commit()
        conn.close()
        conn = None
        os.replace(tmp_path, idx_path)
        return True
    except Exception:
        _search_log.exception('index build failed for %r', module_name)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False



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
            except Exception:
                # Bad/missing ~/.sword or malformed conf — don't crash the app.
                # Return a no-op stub so all `mgr().getModule(name)` callers
                # get None (which they already handle). Don't cache the stub —
                # we want to retry on next call after the user fixes their setup.
                _sword_log.exception('SWMgr init failed')
                return _null_mgr
            # Footnote bodies are moved into entry attributes at render
            # time by SWORD's footnote filters (read back by
            # chapter_footnotes); inline all that remains is an empty
            # <note swordFootnote="N"/> anchor, which the pane either
            # turns into a marker or strips. Without this option the
            # filters drop the notes entirely.
            _mgr.setGlobalOption('Footnotes', 'On')
        return _mgr


def _reset():
    global _mgr
    with _lock:
        _mgr = None
        _cache.clear()
        _notes_cache.clear()
        _strongs_cache.clear()
        _book_maps.clear()
    with _indexing_lock:
        _indexing_threads.clear()



def module_names():
    return sorted(str(k) for k in mgr().getModules().keys())


def has_any_module():
    """Cheap check: does the user appear to have any SWORD module
    installed? Reads the standard `mods.d/*.conf` locations directly —
    the per-user dir and the system-wide one (distro packages, or
    installmgr run as root, install to /usr/share/sword; SWMgr reads
    both). Used by the welcome-vs-main startup decision so we don't pay
    the first `SWMgr()` cost just to discover whether to show the
    welcome window. The first real SWORD call (a chapter render in
    `BiblePane`) does the authoritative SWMgr() init."""
    for mods_dir in (os.path.expanduser('~/.sword/mods.d'),
                     '/usr/share/sword/mods.d'):
        try:
            for name in os.listdir(mods_dir):
                if name.endswith('.conf'):
                    return True
        except OSError:
            continue
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


def _verse_key(module_name=None):
    """A VerseKey, switched to module_name's versification when given.
    The default (KJV) key is right for window-level navigation, which is
    pinned to the 66-book Protestant canon; per-module work (indexing)
    must use the module's own system or chapter/verse maxima drift on
    modules like RusSynodal (Synodal) or Wycliffe (Vulg)."""
    vk = Sword.VerseKey()
    if module_name:
        try:
            mod = mgr().getModule(module_name)
            v11n = mod.getConfigEntry('Versification') if mod else None
            if v11n:
                vk.setVersificationSystem(v11n)
        except Exception:
            pass  # unknown system → fall back to default
    return vk


def chapter_count(book, module_name=None):
    try:
        # A mapped book is addressed in app-space chapters everywhere
        # (load_chapter translates), so the app-space count governs.
        if module_name and _chapter_map(module_name, book):
            module_name = None
        vk = _verse_key(module_name)
        vk.setText(f'{book} 1:1')
        return vk.getChapterMax()
    except Exception:
        # Bad book name (typo, deuterocanon outside KJV v11n) — return 1 so
        # callers don't crash. The whole nav/search/index chain depends on this.
        return 1


def verse_count(book, chapter, module_name=None):
    try:
        if module_name:
            mapped = mapped_chapter(module_name, book, chapter)
            if mapped:
                book, chapter = mapped
        vk = _verse_key(module_name)
        vk.setText(f'{book} {chapter}:1')
        return vk.getVerseMax()
    except Exception:
        return 1


# ── Cross-versification mapping ──────────────────────────────────────────────
#
# App-space references — window navigation, pane-to-pane sync, bookmarks,
# TSK cross-refs, annotation keys — live in the default KJV-shaped
# book/chapter/verse space. A module keyed to another versification
# (Vulg, Synodal, LXX, …) numbers the same text differently, most
# famously the Greek/Latin psalter sitting one psalm behind the
# Hebrew/KJV numbering for most of the book; addressing such a module
# with app-space numbers lands on the wrong psalm. VerseKey.positionFrom
# applies the engine's av11n mapping tables between systems.
#
# Mapping is adopted per (module, book): each app chapter is anchored to
# the module chapter holding its FIRST verse. Where the systems merge
# chapters (KJV Ps 9+10 are one Vulgate psalm) two app chapters share a
# module chapter and both show the whole merged psalm — the right text
# unit either way. Where they split one (KJV Ps 116 spans Vulgate
# 114+115) the anchor renders the module chapter containing the opening
# verses; the split-off tail is only reachable through the neighbouring
# app chapter when the tables allow. Systems the engine has no mapping
# tables for come back as the identity and the book keeps today's
# module-space behavior wholesale. Verse numbers inside a mapped chapter
# stay the module's own (a Vulgate psalter shows its printed numbering,
# including title-verses — KJV Ps 9:1 is Vulgate Ps 9:2).

_book_maps = {}  # (module_name, book) → {app_chapter: (m_book, m_chapter)} | None


def _module_v11n(module_name):
    """The module's versification system, or None when it matches the
    app space (KJV, or its KJVA superset — identical for the 66 books)."""
    try:
        mod = mgr().getModule(module_name)
        v11n = str(mod.getConfigEntry('Versification') or '') if mod else ''
        return v11n if v11n not in ('', 'KJV', 'KJVA') else None
    except Exception:
        return None


def _map_ref(book, chapter, verse, to_v11n):
    """One app-space (KJV) reference → (book, chapter, verse) in
    `to_v11n`, or None. Guards against VerseKey's silent clamping of
    unparseable input by round-tripping the source key first."""
    try:
        src = Sword.VerseKey()
        src.setText(f'{book} {chapter}:{verse}')
        if (str(src.getBookName()).lower() != book.lower()
                or src.getChapter() != chapter or src.getVerse() != verse):
            return None
        dst = Sword.VerseKey()
        dst.setVersificationSystem(to_v11n)
        dst.positionFrom(src)
        return str(dst.getBookName()), dst.getChapter(), dst.getVerse()
    except Exception:
        return None


def _compute_book_map(book, v11n):
    """{app_chapter: (module_book, module_chapter)} anchoring every KJV
    chapter of `book` by its first verse, or None when any chapter fails
    to map or the whole map is the identity (no tables → nothing to do)."""
    src = Sword.VerseKey()
    src.setText(f'{book} 1:1')
    if str(src.getBookName()).lower() != book.lower():
        return None
    out = {}
    identity = True
    for ch in range(1, src.getChapterMax() + 1):
        first = _map_ref(book, ch, 1, v11n)
        if first is None:
            return None
        out[ch] = first[:2]
        if first[:2] != (book, ch):
            identity = False
    return None if identity else out


def _chapter_map(module_name, book):
    """The (cached) per-book chapter map for a module, or None. Cached
    entries are dropped by _reset() alongside the chapter cache."""
    v11n = _module_v11n(module_name)
    if v11n is None:
        return None
    key = (module_name, book)
    if key not in _book_maps:
        try:
            _book_maps[key] = _compute_book_map(book, v11n)
        except Exception:
            _book_maps[key] = None
    return _book_maps[key]


def mapped_chapter(module_name, book, chapter):
    """App-space chapter → the module-v11n (book, chapter) holding that
    text, or None when the module is app-keyed or the book is unmapped."""
    m = _chapter_map(module_name, book)
    return m.get(chapter) if m else None


def map_target_verse(module_name, book, chapter, verse):
    """App-space verse → the verse number to target inside the chapter a
    pane rendered for app-space (book, chapter). Falls back to `verse`
    whenever mapping doesn't apply cleanly."""
    if verse is None:
        return verse
    v11n = _module_v11n(module_name)
    if v11n is None:
        return verse
    mapped = mapped_chapter(module_name, book, chapter)
    if mapped is None:
        return verse
    ref = _map_ref(book, chapter, verse, v11n)
    if ref is not None and ref[:2] == mapped:
        return ref[2]
    return verse


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

        # The caller addresses in app-space (KJV) numbers; translate into
        # the module's own numbering where a safe per-book map exists
        # (Greek/Latin psalter offset). The cache key above deliberately
        # stays app-space.
        mapped = mapped_chapter(module_name, book, chapter)
        if mapped:
            book, chapter = mapped

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
        except Exception:
            _sword_log.exception('load_chapter VerseKey failed for %s %s', book, chapter)
            return []

        results = []
        notes = {}
        for v in range(1, verse_max + 1):
            try:
                vk.setVerse(v)
                mod.setKey(vk)
                results.append((v, mod.renderText()))
            except Exception:
                continue
            v_notes = _collect_footnotes(mod)
            if v_notes:
                notes[v] = v_notes

        _cache_chapter(key, results, notes)
        return results


def _collect_footnotes(mod):
    """[(marker_index, type, body_html)] for the verse just rendered.

    Must run right after renderText(): the footnote filters move each
    note's body out of the text into the module's entry attributes, and
    the next setKey/render replaces the map. marker_index matches the
    swordFootnote="N" attribute on the inline anchor."""
    out = []
    try:
        ea = mod.getEntryAttributesMap()
        for k1 in ea.keys():
            if str(k1) != 'Footnote':
                continue
            fmap = ea[k1]
            for k2 in fmap.keys():
                note = fmap[k2]
                # AttributeValueMap has no .get(); walk the keys.
                fields = {str(k3): str(note[k3]) for k3 in note.keys()}
                body = fields.get('body', '').strip()
                if body:
                    out.append((str(k2), fields.get('type', ''), body))
    except Exception:
        _sword_log.exception('footnote attribute read failed')
    out.sort(key=lambda t: int(t[0]) if t[0].isdigit() else 0)
    return out


def chapter_footnotes(module_name, book, chapter):
    """{verse: [(marker_index, type, body_html), ...]} for a chapter.

    Populated by the same render pass as load_chapter — a cache hit here
    is free, a miss renders (and caches) the chapter."""
    key = (module_name, book, chapter)
    with _lock:
        if key in _notes_cache:
            _notes_cache.move_to_end(key)
            return _notes_cache[key]
    load_chapter(module_name, book, chapter)
    with _lock:
        return _notes_cache.get(key, {})


def module_type(module_name):
    """Return the SWORD type string for a module: 'Biblical Texts', 'Commentaries', etc."""
    mod = mgr().getModule(module_name)
    return str(mod.getType()) if mod else None


def module_has_footnotes(module_name):
    """True if the module's conf declares a footnote filter
    (GlobalOptionFilter=OSISFootnotes / ThMLFootnotes / GBFFootnotes) —
    i.e. its markup can carry translator notes at all. getConfigEntry
    returns only the FIRST of a repeated conf key (SBLGNT's first
    GlobalOptionFilter is UTF8GreekAccents), so walk the full config
    multimap instead."""
    try:
        mod = mgr().getModule(module_name)
        if mod is None:
            return False
        return any(str(k) == 'GlobalOptionFilter' and 'Footnotes' in str(v)
                   for k, v in mod.getConfigMap().items())
    except Exception:
        return False


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
    # Generic Books / Confessions
    'BaptistConfession1689': 'Baptist Confession of Faith (1689)',
    'Concord':              'Book of Concord',
    'DarkNightOfTheSoul':   'The Dark Night of the Soul',
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
    # The feature packs carry curated names of their own. Lazy imports keep
    # this bridge independent of them, mirroring the eBible branch above.
    import catena_bridge
    if catena_bridge.is_catena_module(name):
        return catena_bridge.display_name(name)
    import imagery_bridge
    if imagery_bridge.is_imagery_module(name):
        return imagery_bridge.display_name(name)
    import archaeology_bridge
    if archaeology_bridge.is_archaeology_module(name):
        return archaeology_bridge.display_name(name)
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
            except Exception:
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
            except Exception:
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
        except Exception:
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
            _sword_log.exception('SWMgr init failed in get_devotional_raw')
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
        try:
            fresh_mgr = Sword.SWMgr()
        except Exception:
            _sword_log.exception('SWMgr init failed in lookup_dict_word')
            return ''
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
            _sword_log.exception('SWMgr init failed in load_devotional')
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

    candidates = []
    for d in os.listdir(base):
        full = os.path.join(base, d)
        mods_d = os.path.join(full, 'mods.d')
        if os.path.isdir(mods_d) and _TS_DIR_RE.match(d):
            confs = [f for f in os.listdir(mods_d) if f.endswith('.conf')]
            if confs:
                candidates.append((d, full))

    if candidates:
        candidates.sort(reverse=True)  # most recent timestamp first
        return candidates[0][1]
    return None


_CROSSWIRE_HTTP = 'https://crosswire.org/ftpmirror/pub/sword/packages/rawzip'
_SWORD_PATH = os.path.expanduser('~/.sword')


def _parse_conf_lines(raw_lines):
    """Parse SWORD .conf line strings (no file I/O) → dict of fields.

    Accepts raw lines from a file or from zip bytes; folds `\\`
    continuations the same way SWORD does.
    """
    info = {}

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
            elif k == 'version':
                info['version'] = v
            elif k == 'distributionlicense':
                info['license'] = v
            elif k == 'installsize':
                info['size'] = v
            elif k == 'cipherkey':
                # Present-but-empty means the module is locked and needs a
                # key; we keep the value (possibly '') and use presence as
                # the "is encrypted" signal.
                info['cipherkey'] = v
            elif k == 'feature':
                info.setdefault('features', set()).add(v)
    return info


def _parse_conf(path):
    """Return dict of name/description/type from a SWORD .conf file."""
    try:
        # utf-8-sig strips a leading BOM that would otherwise break the
        # `[Module]` header detection on the first line.
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            raw_lines = f.readlines()
    except OSError:
        return {}
    return _parse_conf_lines(raw_lines)


# Parsed catalogue cache: (shadow_path, [module dicts sans 'installed']).
# Each Refresh writes a brand-new timestamped shadow dir, so keying on the
# path self-invalidates; the volatile 'installed' flag is stamped fresh on
# every call. Parsing 425 .conf files costs ~190 ms — was paid on every
# Module Manager open.
_catalog_cache = None


def list_available_modules():
    """Read available modules by parsing .conf files from the local shadow
    (cached per shadow dir — see _catalog_cache above)."""
    global _catalog_cache
    path = _shadow_path()
    if not path:
        raise FileNotFoundError('No module list cached yet — click Refresh first.')
    if _catalog_cache is not None and _catalog_cache[0] == path:
        installed = set(module_names())
        return [{**m, 'installed': m['name'] in installed}
                for m in _catalog_cache[1]]
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
                # The module *driver* is the authoritative signal — it
                # distinguishes texts / commentaries / dictionaries reliably,
                # whereas LCSH subject strings like "Bible--Dictionaries" trip
                # up a naive "Bible in lcsh" test (Easton, Nave, Torrey are
                # dictionaries/indexes, not Bibles). So classify by driver
                # first, then fall back to LCSH only when the driver is unknown.
                is_devotional = (
                    'DailyDevotion' in info.get('features', set())
                    or 'Devotional' in lcsh
                    or 'Daily Devotional' in info.get('description', ''))
                if drv in ('RawText', 'zText', 'OldzText', 'RawText4', 'zText4'):
                    cat = 'Biblical Texts'
                elif drv in ('RawCom', 'zCom', 'RawCom4', 'zCom4', 'RawFiles'):
                    cat = 'Commentaries'
                elif drv in ('RawLD', 'zLD', 'RawLD4', 'OldzLD'):
                    # The LD driver backs both dictionaries and the date-keyed
                    # daily devotionals — split them by the devotional signal.
                    cat = 'Daily Devotional' if is_devotional \
                        else 'Lexicons / Dictionaries'
                elif drv in ('RawGenBook', 'zGenBook'):
                    cat = 'Generic Books'
                elif 'Commentary' in lcsh:
                    cat = 'Commentaries'
                elif 'Lexicon' in lcsh or 'Dictionary' in lcsh:
                    cat = 'Lexicons / Dictionaries'
                elif is_devotional:
                    cat = 'Daily Devotional'
                elif 'Bible' in lcsh:
                    cat = 'Biblical Texts'
                else:
                    cat = 'Generic Books'

            # Standardize common spellings of the Bible-text category, without
            # catching "Bible Dictionary"-style categories.
            if cat in ('Bible', 'Bibles', 'Bible Texts', 'Biblical Text'):
                cat = 'Biblical Texts'

            result.append({
                'name': name,
                'description': info.get('description', ''),
                'type': cat,
                'lang': info.get('lang', ''),
                'features': info.get('features', set()),
                'license': info.get('license', ''),
                'size': info.get('size', ''),
            })
    result.sort(key=lambda m: m['name'].lower())
    _catalog_cache = (path, result)
    return [{**m, 'installed': m['name'] in installed} for m in result]


def catalog_timestamp():
    """When the cached CrossWire catalogue was downloaded, or None.

    The catalogue lives in a 14-digit timestamp-named shadow dir (see
    `_shadow_path`), so the directory name is the download time."""
    from datetime import datetime
    path = _shadow_path()
    if not path:
        return None
    try:
        return datetime.strptime(os.path.basename(path), '%Y%m%d%H%M%S')
    except ValueError:
        return None


_CROSSWIRE_CATALOG = 'https://crosswire.org/ftpmirror/pub/sword/raw/mods.d.tar.gz'


def refresh_source():
    """Download the CrossWire module catalogue and store in a new shadow dir."""
    # Lazy: pulls in http/ssl/email (~40 ms) — only needed for downloads.
    import urllib.request
    from datetime import datetime
    url = _CROSSWIRE_CATALOG
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()

    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    base = os.path.expanduser('~/.sword/InstallMgr')
    mods_d = os.path.join(base, ts, 'mods.d')
    os.makedirs(mods_d, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        for member in tar.getmembers():
            if member.name.endswith('.conf') and not member.isdir():
                member.name = os.path.basename(member.name)
                tar.extract(member, mods_d)

    # Prune superseded shadow dirs — every refresh creates a fresh
    # timestamp dir and _shadow_path only ever reads the newest, so old
    # ones would otherwise accumulate a few MB of .conf trees forever.
    for d in os.listdir(base):
        if d != ts and _TS_DIR_RE.match(d):
            shutil.rmtree(os.path.join(base, d), ignore_errors=True)


def install_module(module_name):
    """Download module zip from CrossWire and extract into ~/.sword/."""
    import urllib.request
    url = f'{_CROSSWIRE_HTTP}/{module_name}.zip'
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Extract member-by-member through _safe_extract (rather than
        # extractall) so the network path enforces the same path-escape
        # guard as the local sideload path.
        for member in zf.infolist():
            if member.is_dir():
                continue
            _safe_extract(zf, member, _SWORD_PATH)
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

    # Delete the associated FTS5 search index (a single .db file).
    idx_path = _get_index_path(module_name)
    if os.path.exists(idx_path):
        try:
            os.remove(idx_path)
        except OSError:
            pass

    _reset()


# ── Module sideload (import from local .zip) ───────────────────────────────────

def _category_from_info(info):
    """Friendly category label for a parsed .conf (preview display)."""
    cat = info.get('category', '')
    if cat:
        return 'Biblical Texts' if ('Bible' in cat and 'Texts' not in cat) else cat
    lcsh = info.get('lcsh', '')
    drv = info.get('moddrv', '')
    if 'Bible' in lcsh:
        return 'Commentaries' if 'Commentary' in lcsh else 'Biblical Texts'
    if 'Lexicon' in lcsh or 'Dictionary' in lcsh:
        return 'Lexicons / Dictionaries'
    if drv in ('RawText', 'zText', 'OldzText'):
        return 'Biblical Texts'
    if drv in ('RawCom', 'zCom'):
        return 'Commentaries'
    if drv in ('RawLD', 'RawLD4', 'zLD'):
        return 'Lexicons / Dictionaries'
    if 'Daily Devotional' in info.get('description', ''):
        return 'Daily Devotional'
    return 'Generic Books'


def _zip_conf_members(infos):
    """Yield ZipInfo entries that are SWORD module confs (mods.d/*.conf)."""
    for i in infos:
        if i.is_dir():
            continue
        if 'mods.d' in i.filename.split('/') and i.filename.lower().endswith('.conf'):
            yield i


def cmp_version(a, b):
    """Compare two SWORD version strings. Returns -1, 0, or 1.

    Compares dotted numeric components (1.10 > 1.9); falls back to a
    plain string compare when a component isn't numeric.
    """
    def parts(v):
        out = []
        for chunk in str(v).split('.'):
            out.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
        return out
    pa, pb = parts(a), parts(b)
    if pa == pb:
        return 0
    return -1 if pa < pb else 1


def installed_version(module_name):
    """Return the Version= of an installed module, or '' if unknown."""
    conf = os.path.join(_SWORD_PATH, 'mods.d', f'{module_name.lower()}.conf')
    if not os.path.exists(conf):
        return ''
    return _parse_conf(conf).get('version', '')


def can_remove_module(module_name):
    """True if the module lives in the user's ~/.sword and can be deleted.

    System modules (in /usr/share/sword) are read-only — `remove_module`
    refuses them — so the UI shouldn't offer removal for those.
    """
    return os.path.exists(
        os.path.join(_SWORD_PATH, 'mods.d', f'{module_name.lower()}.conf'))


def is_encrypted_module(module_name):
    """True if the installed module's conf declares a CipherKey line.

    Used to gate the wrong-cipher-key detection so non-encrypted modules
    (and valid non-Latin scripts) are never flagged.
    """
    for base in (_SWORD_PATH, '/usr/share/sword'):
        conf = os.path.join(base, 'mods.d', f'{module_name.lower()}.conf')
        if os.path.exists(conf):
            return 'cipherkey' in _parse_conf(conf)
    return False


def chapter_in_index(module_name, book, chapter):
    """True if any verse in the chapter physically exists in the module's
    index, independent of whether it decrypts.

    Lets the wrong-cipher-key check tell two empty-render cases apart: a
    compressed encrypted module with a bad key fails to decompress and
    returns nothing even though the data is there (index says yes), versus
    a genuine coverage gap (index says no).
    """
    with _lock:
        mod = mgr().getModule(module_name)
        if mod is None:
            return False
        mapped = mapped_chapter(module_name, book, chapter)
        if mapped:
            book, chapter = mapped
        try:
            vk = Sword.VerseKey()
            v11n = mod.getConfigEntry('Versification')
            if v11n:
                try:
                    vk.setVersificationSystem(v11n)
                except Exception:
                    pass
            vk.setText(f'{book} {chapter}:1')
            verse_max = vk.getVerseMax()
        except Exception:
            return False
        for v in range(1, verse_max + 1):
            try:
                vk.setVerse(v)
                if mod.hasEntry(vk):
                    return True
            except Exception:
                continue
    return False


def inspect_module_zip(zip_bytes):
    """Inspect a SWORD module .zip held in memory — no disk writes.

    Returns one dict per detected module:
      {name, description, type, lang, version, size, locked,
       installed, installed_version}
    Raises ValueError if the file is not a SWORD module zip.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError('That file is not a valid .zip archive.')

    installed = {n.lower() for n in module_names()}
    results = []
    with zf:
        infos = zf.infolist()
        conf_members = list(_zip_conf_members(infos))
        if not conf_members:
            raise ValueError(
                "This doesn't look like a SWORD module "
                '(no mods.d/*.conf inside).')
        for cm in conf_members:
            text = zf.read(cm.filename).decode('utf-8-sig', errors='replace')
            info = _parse_conf_lines(text.splitlines())
            name = info.get('name')
            if not name:
                continue
            datapath = info.get('datapath', '').lstrip('./').rstrip('/')
            size = 0
            if datapath:
                for i in infos:
                    if i.is_dir():
                        continue
                    p = i.filename.lstrip('./')
                    if p == datapath or p.startswith(datapath + '/'):
                        size += i.file_size
            is_installed = name.lower() in installed
            results.append({
                'name': name,
                'description': info.get('description', ''),
                'type': _category_from_info(info),
                'lang': info.get('lang', ''),
                'version': info.get('version', ''),
                'size': size,
                'locked': 'cipherkey' in info and not info.get('cipherkey'),
                'installed': is_installed,
                'installed_version': installed_version(name) if is_installed else None,
            })
    return results


def _safe_extract(zf, member, dest):
    """Extract one zip member under dest, refusing paths that escape it."""
    target = os.path.realpath(os.path.join(dest, member.filename))
    root = os.path.realpath(dest)
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f'Unsafe path in zip: {member.filename}')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with zf.open(member) as src, open(target, 'wb') as out:
        shutil.copyfileobj(src, out)


def _write_cipher_key(module_name, key):
    """Write/replace the CipherKey= line in an installed module's conf."""
    conf = os.path.join(_SWORD_PATH, 'mods.d', f'{module_name.lower()}.conf')
    if not os.path.exists(conf):
        return
    with open(conf, encoding='utf-8-sig', errors='replace') as f:
        lines = f.readlines()
    out = []
    found = False
    for ln in lines:
        if ln.strip().lower().startswith('cipherkey'):
            out.append(f'CipherKey={key}\n')
            found = True
        else:
            out.append(ln)
    if not found:
        if out and not out[-1].endswith('\n'):
            out[-1] += '\n'
        out.append(f'CipherKey={key}\n')
    with open(conf, 'w', encoding='utf-8') as f:
        f.writelines(out)


def install_module_from_zip(zip_bytes, names, cipher_keys=None):
    """Extract the named modules from an in-memory SWORD zip into ~/.sword.

    `names` selects which detected modules to install (a multi-module zip
    may carry more than the user wants). `cipher_keys` is an optional
    {name: key} map written into each installed conf after extraction.
    Validation happens before any file is written, so a bad zip leaves no
    partial state.
    """
    cipher_keys = cipher_keys or {}
    wanted = set(names)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = zf.infolist()
        for cm in _zip_conf_members(infos):
            info = _parse_conf_lines(
                zf.read(cm.filename).decode('utf-8-sig', errors='replace').splitlines())
            name = info.get('name')
            if name not in wanted:
                continue
            _safe_extract(zf, cm, _SWORD_PATH)
            datapath = info.get('datapath', '').lstrip('./').rstrip('/')
            if datapath:
                for i in infos:
                    if i.is_dir():
                        continue
                    p = i.filename.lstrip('./')
                    if p == datapath or p.startswith(datapath + '/'):
                        _safe_extract(zf, i, _SWORD_PATH)
            key = cipher_keys.get(name)
            if key:
                _write_cipher_key(name, key)
    _reset()


def set_cipher_key(module_name, key):
    """Set/replace the CipherKey of an already-installed module, then reset
    caches so the next chapter load decrypts with the new key."""
    _write_cipher_key(module_name, key)
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
    """Search a module via its FTS5 index, using the shared query grammar
    (phrase / AND / OR / exclude / prefix — see search_query). Builds the
    index on first use (or after a schema-version bump). Returns
    [(book, chapter, verse, plain_text)], with a truncation sentinel row
    when capped.
    """
    match = search_query.build_match(query)
    if match is None:
        return []

    idx_path = _get_index_path(module_name)

    if not _index_is_valid(idx_path):
        # Atomic check-and-spawn: two concurrent searches must not both build
        # the same index. Hold _indexing_lock only for the dict op, never
        # during the long-running join below.
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

        if not _index_is_valid(idx_path):
            return []

    # Perform search. chapter/verse are stored as FTS5 text columns, so CAST
    # them back to int — the navigation chain (chapter_count/clamp) does
    # integer comparisons. Fetch one past the cap to detect truncation.
    try:
        conn = sqlite3.connect(idx_path)
        try:
            rows = conn.execute(
                'SELECT book, CAST(chapter AS INTEGER), CAST(verse AS INTEGER), '
                'content FROM verses WHERE verses MATCH ? ORDER BY rowid '
                'LIMIT ?', (match, MAX_SEARCH_RESULTS + 1)).fetchall()
        finally:
            conn.close()
    except Exception:
        _search_log.exception('FTS5 search error')
        return []

    truncated = len(rows) > MAX_SEARCH_RESULTS
    formatted = [(b, c, v, content) for (b, c, v, content) in rows[:MAX_SEARCH_RESULTS]]
    # FTS5 (unicode61) folds case at index time, so MATCH is case-insensitive.
    # For a case-sensitive match we post-filter the stored verbatim content
    # for the original-case terms (shared with the eBible backend).
    if case_sensitive:
        cs_words = search_query.plain_terms(query)
        formatted = [r for r in formatted
                     if all(w in (r[3] or '') for w in cs_words)]
    if truncated:
        # Sentinel row the panel detects and replaces with its own translated
        # message, so this backend stays English-free.
        formatted.append(('', 0, 0, ''))
    return formatted


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
