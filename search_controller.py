"""Shared search execution for the window panel and the per-pane bar.

Owns the parts both surfaces used to duplicate: backend dispatch, background
threading, stale-result (generation) guarding, truncation parsing, and the
multi-module "all Bibles" union. Each UI keeps its own widgets and row
rendering — it hands a search closure to `SearchRunner.run` and renders in
the `on_done` callback.
"""

import threading

from gi.repository import GLib

import sword_bridge
import ebible_bridge
import content

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
    truncation sentinel)."""
    if ebible_bridge.is_ebible_module(module):
        return ebible_bridge.search_module(
            module, query, case_sensitive=case_sensitive)
    return sword_bridge.search_module(
        module, query,
        on_indexing_start=on_indexing_start,
        on_indexing_progress=on_indexing_progress,
        on_indexing_done=on_indexing_done,
        case_sensitive=case_sensitive)


def split_truncation(results):
    """Strip the backend's truncation sentinel row (empty book name); return
    (rows, truncated)."""
    truncated = bool(results and results[-1][0] == '')
    return (list(results[:-1]) if truncated else list(results)), truncated


def bible_modules():
    """Every Bible-type module key (excludes commentaries, devotionals,
    generic books, and the interlinear pseudo-module, which has no FTS
    backend) — the set 'All Bibles' searches over."""
    return [m for m in content.readable_module_names()
            if content.is_text_bible(m)]


def search_all_bibles(query, case_sensitive, on_indexing_start=None,
                      on_indexing_progress=None, on_indexing_done=None):
    """Union of unique verse references across every installed Bible — the
    'I don't remember which translation' case. One row per (book, chapter,
    verse), snippet taken from the first translation that matched, returned in
    canonical order. Truncation sentinel appended when capped."""
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

    Each `run` bumps a generation token; a result whose token is no longer
    current has been superseded by a newer search and is dropped — so fast
    typing / re-runs never let an older search overwrite a newer one."""

    def __init__(self):
        self._gen = 0

    def run(self, search_fn, on_done):
        """`search_fn()` runs on a worker thread and returns raw backend rows.
        `on_done(rows, truncated)` runs on the main loop, only if this run is
        still the most recent."""
        self._gen += 1
        gen = self._gen

        def work():
            try:
                results = search_fn()
            except Exception:
                results = []
            GLib.idle_add(self._deliver, gen, results, on_done)

        threading.Thread(target=work, daemon=True).start()

    def _deliver(self, gen, results, on_done):
        if gen != self._gen:
            return GLib.SOURCE_REMOVE
        rows, truncated = split_truncation(results)
        on_done(rows, truncated)
        return GLib.SOURCE_REMOVE
