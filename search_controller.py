"""Shared search execution for the window panel and the per-pane bar.

Owns the parts both surfaces used to duplicate: backend dispatch, background
threading, stale-result (generation) guarding, truncation parsing, and the
multi-module "all Bibles" union. Each UI keeps its own widgets and row
rendering — it hands a search closure to `SearchRunner.run` and renders in
the `on_done` callback.
"""

import re

import sword_bridge
import ebible_bridge
import content
import lemma_index
import search_query
import tasks

# Sentinel module key for "search every installed Bible" (the window picker's
# first row). Chosen so it can't collide with a real module name.
ALL_BIBLES = '\x00all-bibles'

# Canonical book order for sorting the cross-module union.
_BOOK_ORDER = {b: i for i, b in enumerate(sword_bridge._ALL_BOOKS)}


def search_backend(module, query, case_sensitive,
                   on_indexing_start=None, on_indexing_progress=None,
                   on_indexing_done=None):
    """Run one module's search via its owning backend. Blocking — call from a
    worker thread. Returns the backend's raw rows (possibly with a trailing
    truncation sentinel).

    A query carrying `strong:` / `lemma:` / `morph:` is answered by the
    interlinear databases instead: no FTS index knows what Greek word
    stands under an English verse, so those terms are resolved to
    references first and the chosen translation supplies the text."""
    filters, rest = search_query.split_filters(query)
    if filters:
        return search_original(module, filters, rest, case_sensitive)
    return _text_backend(module, query, case_sensitive,
                         on_indexing_start, on_indexing_progress,
                         on_indexing_done)


def _text_backend(module, query, case_sensitive,
                  on_indexing_start=None, on_indexing_progress=None,
                  on_indexing_done=None):
    """The text half of a search — the FTS path, unchanged."""
    if ebible_bridge.is_ebible_module(module):
        return ebible_bridge.search_module(
            module, query, case_sensitive=case_sensitive)
    return sword_bridge.search_module(
        module, query,
        on_indexing_start=on_indexing_start,
        on_indexing_progress=on_indexing_progress,
        on_indexing_done=on_indexing_done,
        case_sensitive=case_sensitive)


def search_original(module, filters, rest, case_sensitive):
    """Verses whose original-language word matches `filters`, rendered in
    `module`. Blocking — call from a worker thread.

    `rest` is whatever plain text the query also carried, and the two are
    an INTERSECTION: `strong:G26 charity` asks for the verses whose Greek
    has ἀγάπη *and* whose translation says charity, which is how a reader
    finds out where one word was rendered two ways. The text half runs
    through its ordinary backend, so Match case keeps meaning what it
    means.

    Returns the same (book, chapter, verse, text) rows every other
    backend returns, with the same truncation sentinel — so the panel,
    the pane bar, the book chart and F3 stepping need to know nothing
    about this path.
    """
    refs = lemma_index.refs(filters)
    refs, truncated = _narrow(
        refs, rest, lambda q: _text_backend(module, q, case_sensitive))
    truncated = truncated or len(refs) > sword_bridge.MAX_SEARCH_RESULTS
    if len(refs) > sword_bridge.MAX_SEARCH_RESULTS:
        refs = refs[:sword_bridge.MAX_SEARCH_RESULTS]
    out = _texts_for(module, refs)
    if truncated:
        out.append(('', 0, 0, ''))
    return out


def _narrow(refs, rest, run_text):   # -> (refs, inexact)
    """Narrow `refs` by whatever plain text the query also carried.

    Two moves, and the second is why this is not one line. A positive
    term INTERSECTS — `strong:G26 love` is the verses with ἀγάπη that
    also say love. An exclusion SUBTRACTS — `strong:G26 -love` is the
    same verses minus those, which is where a reader finds the 26 places
    the King James says charity, dear or beloved instead.

    The text grammar refuses a query that is only exclusions, because FTS
    has no set to subtract from. Here there is one: the filters made it.
    So the exclusions are run as a positive query and removed, rather than
    handed over as `-love` and silently dropped (which returned all 104
    verses, the opposite of the ask) or handed over whole (which returned
    none of them).

    The text backend caps itself at MAX_SEARCH_RESULTS, so a term that
    matches more verses than that comes back short. Intersecting with a
    short set only drops rows, which the truncation note already covers;
    SUBTRACTING a short set leaves rows in that should have gone. Either
    way the caller is told the answer is inexact rather than left to
    present it as complete.
    """
    if not rest.strip():
        return refs, False
    inexact = False
    if search_query.build_match(rest) is not None:
        rows, cut = split_truncation(run_text(rest))
        inexact = inexact or cut
        keep = {(b, c, v) for b, c, v, _t in rows}
        refs = [r for r in refs if r in keep]
    drop_query = search_query.exclusions(rest)
    if drop_query:
        rows, cut = split_truncation(run_text(drop_query))
        inexact = inexact or cut
        drop = {(b, c, v) for b, c, v, _t in rows}
        refs = [r for r in refs if r not in drop]
    return refs, inexact


def _texts_for(module, refs):
    """Fill app-space references with `module`'s own verse text.

    One chapter load per chapter, not per verse — a common word touches
    hundreds of verses and `content.load_chapter` is the expensive call.
    Goes through `content`, never `sword_bridge`, because an eBible
    translation is a Bible the reader may well have chosen (the World
    English Bible ships in the English welcome bundle) and the SWORD
    function answers [] for it without raising.

    A verse the module does not carry is dropped rather than shown empty:
    the interlinear covers the Hebrew OT and the Greek NT, and a New
    Testament module has nothing to say about Genesis.
    """
    out = []
    by_chapter = {}
    for book, chapter, verse in refs:
        by_chapter.setdefault((book, chapter), []).append(verse)
    for (book, chapter), verses in by_chapter.items():
        try:
            loaded = {v: html for v, html
                      in content.load_chapter(module, book, chapter)}
        except Exception:
            continue
        for verse in verses:
            # The rendered chapter numbers verses the MODULE's way; the
            # reference is app-space. On a mapped psalter those differ,
            # and looking the app number straight up would quietly return
            # the neighbouring verse.
            target = sword_bridge.map_target_verse(module, book, chapter,
                                                   verse)
            html = loaded.get(target)
            if html is None:
                continue
            text = re.sub(r'<[^>]+>', '', str(html)).strip()
            if text:
                out.append((book, chapter, verse, text))
    out.sort(key=lambda r: (_BOOK_ORDER.get(r[0], 999), r[1], r[2]))
    return out


def split_truncation(results):
    """Strip the backend's truncation sentinel row (empty book name); return
    (rows, truncated)."""
    truncated = bool(results and results[-1][0] == '')
    return (list(results[:-1]) if truncated else list(results)), truncated


def bible_modules():
    """Every Bible-type module key (excludes commentaries, devotionals,
    generic books, and the interlinear pseudo-module, which has no FTS
    backend) — the set 'All Bibles' searches over."""
    return content.text_bible_names()


def search_all_bibles(query, case_sensitive, on_indexing_start=None,
                      on_indexing_progress=None, on_indexing_done=None):
    """Union of unique verse references across every installed Bible — the
    'I don't remember which translation' case. One row per (book, chapter,
    verse), snippet taken from the first translation that matched, returned in
    canonical order. Truncation sentinel appended when capped."""
    filters, rest = search_query.split_filters(query)
    if filters:
        return _all_bibles_original(filters, rest, case_sensitive)
    seen = set()
    out = []
    truncated = False
    for module in bible_modules():
        rows, t = split_truncation(search_backend(
            module, query, case_sensitive,
            on_indexing_start=on_indexing_start,
            on_indexing_progress=on_indexing_progress,
            on_indexing_done=on_indexing_done))
        truncated = truncated or t
        for book, ch, v, text in rows:
            key = (book, ch, v)
            if key not in seen:
                seen.add(key)
                out.append((book, ch, v, text))
    out.sort(key=lambda r: (_BOOK_ORDER.get(r[0], 999), r[1], r[2]))
    if len(out) > sword_bridge.MAX_SEARCH_RESULTS:
        out = out[:sword_bridge.MAX_SEARCH_RESULTS]
        truncated = True
    if truncated:
        out.append(('', 0, 0, ''))
    return out


class SearchRunner:
    """Runs a search closure on a background thread with stale-result guarding.

    A thin per-surface facade over the shared `tasks` runner: each instance
    is one task key, so a surface's re-run supersedes only its own earlier
    search — fast typing / re-runs never let an older search overwrite a
    newer one, and surfaces never cancel each other's."""

    def __init__(self):
        self._key = f'search:{id(self)}'

    def run(self, search_fn, on_done):
        """`search_fn()` runs on a worker thread and returns raw backend rows.
        `on_done(rows, truncated)` runs on the main loop, only if this run is
        still the most recent."""
        def apply(results):
            rows, truncated = split_truncation(results)
            on_done(rows, truncated)

        # A raised search delivers as empty results, so the surface always
        # leaves its "Searching…" state.
        tasks.submit(self._key, lambda _task: search_fn(), apply,
                     on_error=lambda _exc: apply([]))


def _all_bibles_original(filters, rest, case_sensitive):
    """'All Bibles' for an original-language query.

    The references do not depend on the translation — the Greek behind
    John 3:16 is the same whichever English is on the page — so the
    interlinear is asked once rather than once per installed Bible, and
    each verse takes its text from the first module that carries it. The
    text half, when the query has one, still has to run per module: that
    IS the translation-dependent part, and a word rendered "charity" in
    one Bible and "love" in another should match in both.
    """
    def across_all(query):
        rows = []
        cut = False
        for module in bible_modules():
            got, t = split_truncation(
                _text_backend(module, query, case_sensitive))
            rows.extend(got)
            cut = cut or t
        return (rows + [('', 0, 0, '')]) if cut else rows

    refs = lemma_index.refs(filters)
    refs, truncated = _narrow(refs, rest, across_all)
    truncated = truncated or len(refs) > sword_bridge.MAX_SEARCH_RESULTS
    if len(refs) > sword_bridge.MAX_SEARCH_RESULTS:
        refs = refs[:sword_bridge.MAX_SEARCH_RESULTS]
    found = {}
    for module in bible_modules():
        missing = [r for r in refs if r not in found]
        if not missing:
            break
        for book, chapter, verse, text in _texts_for(module, missing):
            found[(book, chapter, verse)] = text
    out = [(b, c, v, found[(b, c, v)]) for (b, c, v) in refs
           if (b, c, v) in found]
    if truncated:
        out.append(('', 0, 0, ''))
    return out
