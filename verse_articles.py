"""The dictionary articles that cite a verse.

Built on this machine from the dictionaries the reader has installed: every
entry is walked once and every verse it cites is noted, so the
cross-reference bar can offer "what the dictionaries say about this verse".
Easton's marks its references the OSIS way (`<ref osisRef="Bible:1Sam.25.3">`),
the Russian Bible dictionary as `<reference osisRef="RusCARST:Ps.50.9">` (in
that Bible's own numbering, moved here to the KJV's), Smith's the ThML way
(`<scripRef passage="1sa 25:14">`); a work with none of them adds nothing.

Not every dictionary belongs on the bar. Two tests, both measured:

* **A Bible reference work.** Easton's cites Scripture in 97% of its
  entries, Smith's 87%, the French and Russian Bible dictionaries 77% and
  92%; Webster's 1913 in 2%, quoting the KJV to show a word's sense. A work
  is kept when at least a quarter of its entries cite a verse. Webster's
  still answers the double-clicked word; it does not answer "what do the
  dictionaries say about this verse".
* **In a language the reader reads**: the language of the Bible open in the
  pane, then the interface's. A dictionary installed in another language
  would only lengthen the row. Kept ones are ordered by that same rank.

The walk takes seconds for a large work, so the result is kept in the cache
folder, keyed on each module's data files; installing, updating or removing
a dictionary rebuilds it on the next ask. Always asked from a worker thread.
"""
from __future__ import annotations

import html
import logging
import os
import pickle
import re
import threading
from array import array

import Sword

import open_data
import paths
import sword_bridge

_log = logging.getLogger(__name__)

CACHE_FILE = 'verse-articles.pickle'
_FORMAT = 8
# A work counts as a Bible reference work when this share of its entries
# cites a verse.
BIBLE_WORK_SHARE = 0.25
# A cited range longer than this is about a whole book or psalm, not its
# verses: only its first verse is noted. A story is shorter: Tyndale's
# Abigail cites 1 Sm 25:2-42, and a cap of 40 lost her at 25:3.
_RANGE_CAP = 80

_lock = threading.Lock()
#: (signature, the index (see _build), {module: (entries, entries citing a verse)})
_index: tuple | None = None

_OSIS_REF_SHOWN = re.compile(
    r'<ref(?:erence)?\b[^>]*?osisRef="([^"]+)"[^>]*>(.*?)</ref(?:erence)?>', re.S)
_WORK_PREFIX = re.compile(r'(^|-)([^:\s-]+):')
_CHAPTER_ONLY = re.compile(r'^([1-3]?[A-Za-z]+)\.(\d+)$')
_v11n_cache = {}


def _work_v11n(work):
    """The versification a cited work numbers its verses in, or None for
    the KJV's own. From the work's .conf: the installed one, else the copy
    the module catalogue keeps."""
    if not work or work == 'Bible':
        return None
    if work not in _v11n_cache:
        v11n = ''
        with sword_bridge._lock:      # the shared manager: asked off the UI thread
            installed = sword_bridge.mgr().getModule(work) is not None
        if installed:
            v11n = sword_bridge._module_v11n(work) or ''
        else:
            pattern = os.path.join(sword_bridge._SWORD_PATH, 'InstallMgr', '*',
                                   'mods.d', work.lower() + '.conf')
            import glob
            for conf in glob.glob(pattern):
                try:
                    with open(conf, encoding='utf-8', errors='replace') as f:
                        m = re.search(r'^Versification=(\S+)', f.read(), re.M)
                except OSError:
                    continue
                if m:
                    v11n = m.group(1)
                    break
        _v11n_cache[work] = v11n if v11n not in ('', 'KJV', 'KJVA') else None
    return _v11n_cache[work]


def _to_app(v11n, ref):
    """A reference in `v11n` numbering → the KJV's, unchanged if the
    tables cannot place it."""
    if v11n is None:
        return ref
    mapped = sword_bridge._map_ref_reverse(v11n, *ref)
    other = _BORROWED_TABLES.get(v11n)
    if other and (sword_bridge._v11n_verse_max(v11n, ref[0], ref[1])
                  == sword_bridge._v11n_verse_max(other, ref[0], ref[1])):
        # SWORD defines SynodalProt with the Synodal psalter (Ps 9 of 39
        # verses) but ships no real tables for it: its answers come back
        # unmoved or clamped (Ps 118:119 → 118:29), so the Russian
        # dictionary's "Ps 50:9" for hyssop missed KJV 51:7. Wherever its
        # chapter has the Synodal's shape, the Synodal tables place it.
        mapped = sword_bridge._map_ref_reverse(other, *ref)
    if mapped and mapped[2] == 0:
        # A psalm title: the KJV prints it above verse 1.
        mapped = (mapped[0], mapped[1], 1)
    return mapped or ref


#: Versifications SWORD has no mapping tables for, and the one whose tables
#: fit them chapter by chapter where their shapes agree.
_BORROWED_TABLES = {'SynodalProt': 'Synodal'}
_SCRIP_REF = re.compile(r'<scripRef([^>]*)>(.*?)</scripRef>', re.S)
_PASSAGE = re.compile(r'passage="([^"]+)"')


def _modules():
    """The dictionaries to index: the ones the word peek searches, less
    Thompson's topics, which the bar already shows as their own set."""
    return [name for name, _desc in sword_bridge.installed_dict_modules()
            if name.upper() != 'TCR']


def _signature(names):
    """What the index was built from: each module's data files, by size
    and time."""
    sig = []
    for name in sorted(names):
        folder = sword_bridge.module_data_path(name)
        files = []
        try:
            for f in sorted(os.listdir(folder)):
                st = os.stat(os.path.join(folder, f))
                files.append((f, st.st_size, int(st.st_mtime)))
        except OSError:
            pass
        sig.append((name, tuple(files)))
    return (_FORMAT, tuple(sig))


def cited_verses(raw):
    """Every (book, chapter, verse) one entry's markup cites, in order,
    without repeats."""
    out = []
    seen = set()

    def add(ref):
        if ref not in seen:
            seen.add(ref)
            out.append(ref)

    # A bare continuation — "1 Chr. 2:50, 52; 4:1, 2" — is coded wrong in
    # Easton's module: 807 of its 5,774 carry Genesis (Gen.4.1 for "4:1")
    # instead of the book before them. The printed text is right, so a
    # bare one is read from it, in the book and chapter of the last named.
    # Book and chapter stay in the cited work's numbering until each verse
    # is added, so a bare one after them is moved the same way.
    book = chapter = None
    v11n = None
    for value, shown in _OSIS_REF_SHOWN.findall(raw):
        shown = sword_bridge.plain_text(shown).strip()
        bare = re.fullmatch(r'(?:(\d+):)?(\d+)(?:\s*[-–]\s*(\d+))?[.;,]?', shown)
        if bare and book:
            if bare.group(1):
                chapter = int(bare.group(1))
            v1 = int(bare.group(2))
            v2 = int(bare.group(3) or v1)
            span = range(v1, v2 + 1) if 0 <= v2 - v1 < _RANGE_CAP else [v1]
            for v in span:
                add(_to_app(v11n, (book, chapter, v)))
            continue
        first = None
        for one in value.split():
            work = _WORK_PREFIX.match(one)
            one = _WORK_PREFIX.sub(r'\1', one)
            ref_v11n = _work_v11n(work.group(2)) if work else None
            whole = _CHAPTER_ONLY.match(one)
            if whole:
                name = open_data._OSIS_BOOKS.get(whole.group(1))
                refs = [(name, int(whole.group(2)), 1)] if name else []
            else:
                vids = open_data._osis_to_vids(one)
                refs = [open_data._parse_vid(vid)
                        for vid in (vids[:1] if len(vids) > _RANGE_CAP else vids)]
            for ref in refs:
                if ref:
                    if first is None:
                        first, v11n = ref, ref_v11n
                    add(_to_app(ref_v11n, ref))
        if first:
            book, chapter = first[0], first[1]
    for attrs, inner in _SCRIP_REF.findall(raw):
        m = _PASSAGE.search(attrs)
        text = html.unescape(m.group(1) if m else sword_bridge.plain_text(inner))
        refs = sword_bridge._parse_cross_ref_text(text)
        # The parser spells a range out verse by verse; keep it to its start
        # when it runs long, as above.
        run = []
        for r in refs + [None]:
            if run and (r is None or r[:2] != run[-1][:2] or r[2] != run[-1][2] + 1):
                for x in run[:1] if len(run) > _RANGE_CAP else run:
                    add(x[:3])
                run = []
            if r is not None:
                run.append(r)
    return out


def _walk(name):
    """([((key, nth), cited verses, references made)] for every entry that
    cites a verse, the number of entries walked)."""
    entries = []
    with sword_bridge._lock:
        # A manager of its own: a walk run to the end leaves the module's
        # key in an error state that the next lookup would inherit.
        manager = Sword.SWMgr()   # held: the module dies with it
        mod = manager.getModule(name)
        if mod is None:
            return entries, 0
        mod.setPosition(Sword.SW_POSITION(1))
        # Keys can repeat — Smith's has two entries under "AB" and two
        # under "ABEL" — so the walk runs to the module's own end, and each
        # entry is named by its key and which of the same-named it is.
        times = {}
        walked = 0
        while walked < 200_000:
            if sword_bridge._walk_ended(mod.popError()):
                break
            key = str(mod.getKeyText())
            nth = times.get(key, 0)
            times[key] = nth + 1
            raw = str(mod.getRawEntry())
            if 'osisRef' in raw or 'scripRef' in raw:
                entries.append(((key, nth), raw))
            walked += 1
            mod.increment()
            if walked % 2000 == 0:
                # The module and its manager are this walk's own, but the
                # lock is everyone's: Webster's alone takes 5 s, and the page
                # cannot render while it is held. Let go between batches.
                sword_bridge._lock.release()
                sword_bridge._lock.acquire()
    return [(key, cited_verses(raw), _citations(raw))
            for key, raw in entries], walked


def _citations(raw):
    """How many references an entry makes: a range is one, however long."""
    return len(_OSIS_REF_SHOWN.findall(raw)) + len(_SCRIP_REF.findall(raw))


def _build(names):
    """(index, stats). The index is compact — it holds 148,000 links to
    15,000 articles, and as tuples it took 21 MB: each article is named
    once in a table, and each verse keeps an array of article numbers.

        {'articles': [(module, key, nth), ...],
         'verses': {verse number: array of article numbers}}
    """
    articles, number, verses, stats = [], {}, {}, {}
    for name in names:
        try:
            walked, total = _walk(name)
        except Exception:
            _log.exception('could not index %s', name)
            continue
        stats[name] = (total, sum(1 for _key, refs, _n in walked if refs))
        # An article that makes few references is about them; one making
        # hundreds mentions them in passing. The narrow ones go first.
        # Counted by reference, not verse: a story cited as one range is
        # one citation.
        for (key, nth), refs, _n in sorted(walked, key=lambda e: e[2]):
            art = (name, key, nth)
            if art not in number:
                number[art] = len(articles)
                articles.append(art)
            for ref in refs:
                vid = _verse_number(*ref)
                if vid is not None:
                    verses.setdefault(vid, array('I')).append(number[art])
    return {'articles': articles, 'verses': verses}, stats


def _verse_number(book, chapter, verse):
    i = open_data._BOOK_IDX.get(book)
    return None if i is None else i * 1_000_000 + chapter * 1000 + verse


def _cache_path():
    return os.path.join(paths.cache_dir(), CACHE_FILE)


def _write(entry):
    try:
        tmp = _cache_path() + f'.{os.getpid()}.tmp'
        with open(tmp, 'wb') as f:
            pickle.dump(entry, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, _cache_path())
    except OSError:
        _log.exception('could not keep the verse-article index')


#: (signature, cache file, its mtime) last found not to match: an out-of-date
#: cache is not unpickled again on every verse click (24 ms each) while the
#: reader has not yet chosen Dictionaries to rebuild it.
_stale = None


def _read(sig):
    global _stale
    try:
        mtime = os.stat(_cache_path()).st_mtime_ns
    except OSError:
        return None
    if _stale == (sig, _cache_path(), mtime):
        return None
    try:
        with open(_cache_path(), 'rb') as f:
            cached = pickle.load(f)
        if cached[0] == sig:
            return cached
    except Exception:
        pass
    _stale = (sig, _cache_path(), mtime)
    return None


def _build_in_child():
    """Build in a process of its own and leave the result in the cache.

    Walking the dictionaries reads every entry's text: in the app's own
    process that left about 50 MB behind after the build, which Python
    keeps until the app closes. A child returns all of it when it exits,
    and holds no lock the page needs while it works."""
    import subprocess
    import sys
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), '--build'],
                           capture_output=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        _log.exception('the index build did not run')
        return False
    if r.returncode != 0:
        _log.warning('the index build failed: %s', r.stderr[-400:])
    return r.returncode == 0


def _load(build=True):
    """(index, stats), building them if need be; with `build` False, None
    when they would have to be built."""
    global _index
    names = _modules()
    sig = _signature(names)
    # A first build holds the lock for seconds; a question that may not
    # build must not wait behind it, or every set on the bar would.
    if not _lock.acquire(blocking=build):
        return None
    try:
        if _index is not None and _index[0] == sig:
            return _index[1:]
        cached = _read(sig)
        if cached is None and build and _build_in_child():
            cached = _read(sig)
        if cached is not None:
            _index = cached
            return cached[1:]
        if not build:
            return None
        # The child could not build (or a dictionary changed meanwhile):
        # build here instead.
        _index = (sig, *_build(names))
        _write(_index)
        return _index[1:]
    finally:
        _lock.release()


def _language_rank(langs):
    """{module: rank} for the dictionaries in a language the reader reads;
    `langs` is in order of preference, the open Bible's first."""
    import content
    order = [l for i, l in enumerate(langs) if l and l not in langs[:i]]
    rank = {}
    for name in _modules():
        lang = content.language_code(name)
        if lang in order:
            rank[name] = order.index(lang)
    return rank


def _is_bible_work(stats, name):
    total, citing = stats.get(name, (0, 0))
    return total > 0 and citing / total >= BIBLE_WORK_SHARE


def works(langs):
    """The dictionaries the bar draws on, best first: Bible reference works
    in a language the reader reads. Before the index exists, every
    dictionary in such a language counts, so asking never builds it."""
    rank = _language_rank(langs)
    loaded = _load(build=False)
    names = [n for n in rank if loaded is None or _is_bible_work(loaded[1], n)]
    return sorted(names, key=lambda n: (rank[n], n.lower()))


def articles_for(book, chapter, verse, langs):
    """[(module, key, nth), ...] for the articles that cite this verse
    (app-space numbering) in the dictionaries `works(langs)` keeps: by
    their rank, then narrowest first within each. `nth` tells same-named
    entries apart: 0 for the first under that key."""
    index, stats = _load()
    keep = [n for n in works(langs) if _is_bible_work(stats, n)]
    order = {name: i for i, name in enumerate(keep)}
    vid = _verse_number(book, chapter, verse)
    articles = index['articles']
    found = [articles[i] for i in index['verses'].get(vid, ())]
    return sorted((a for a in found if a[0] in order), key=lambda a: order[a[0]])


def article_text(name, key, nth=0):
    """The raw text of one entry, the `nth` of those filed under `key`."""
    with sword_bridge._lock:
        # Fresh, as lookup_dict_entry does: a failed set spoils the
        # shared module's key for every later lookup.
        manager = Sword.SWMgr()   # held: the module dies with it
        mod = manager.getModule(name)
        if mod is None:
            return ''
        # The key reads back empty until the entry has been read once, so
        # read first and check after; a key it does not hold lands on a
        # neighbour, which the check turns away.
        mod.setKeyText(key)
        raw = str(mod.getRawEntry())
        want = key.strip()
        if str(mod.getKeyText()).strip() != want:
            return ''
        # Under a repeated key the set lands on any one of them: step back
        # to the first, then forward to the nth.
        for _ in range(50):
            mod.decrement()
            if sword_bridge._walk_ended(mod.popError()):
                mod.setPosition(Sword.SW_POSITION(1))
                mod.getRawEntry()
                break
            mod.getRawEntry()
            if str(mod.getKeyText()).strip() != want:
                mod.increment()
                break
        raw = str(mod.getRawEntry())
        for _ in range(nth):
            mod.increment()
            if sword_bridge._walk_ended(mod.popError()):
                return ''
            raw = str(mod.getRawEntry())
        if str(mod.getKeyText()).strip() != want:
            return ''
        return raw


if __name__ == '__main__':
    # The child `_build_in_child` starts: build, keep, exit.
    import sys
    if sys.argv[1:] == ['--build']:
        names = _modules()
        _write((_signature(names), *_build(names)))
        sys.exit(0)
