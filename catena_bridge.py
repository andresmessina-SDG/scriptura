"""catena_bridge.py — read access to the Historical Commentaries pack.

The pack is a single SQLite file (built by tools/build_catena_pack.py,
downloaded on demand from Module Manager) with one denormalised `quotes`
table keyed by verse, plus a `pack_meta` key/value table. Unlike
ebible_bridge there is exactly one "module" here, so a single module key
stands in for it rather than a prefix scheme.

Verse keys are encoded as `chapter * 1_000_000 + verse`; a verse's
commentary is every row whose [loc_start, loc_end] span contains it, so
passage-level entries (e.g. the John 7:53-8:11 pericope) surface on each
verse they cover.
"""

import gzip
import logging
import os
import shutil
import sqlite3
import threading
import urllib.request
from typing import Callable, TypedDict

import paths

_log = logging.getLogger('scriptura.catena')

# The single pane-picker module name this bridge contributes.
MODULE_KEY = 'Historical Commentaries'

# The downloadable pack, hosted as a gzipped SQLite on Codeberg Releases.
# Replace the tag once the release is published.
PACK_URL = ('https://codeberg.org/andresmessina/scriptura/releases/'
            'download/catena-pack-v1/catena.db.gz')

# Mirrors the build script's sentinel for "date unknown".
_UNKNOWN_YEAR = 9999


class CatenaEntry(TypedDict):
    author: str
    author_suffix: str | None
    year: int | None
    era: str
    source_title: str | None
    source_url: str | None
    wiki_url: str | None
    text: str


# ── connection (thread-local, read-only) ───────────────────────────────────────

# The pack is read-only at runtime (only built offline / removed wholesale),
# so each thread keeps its own read connection. _generation is bumped by
# install/remove so cached connections to a replaced or deleted file are
# reopened rather than reused.
_conn_local = threading.local()
_generation = 0
_gen_lock = threading.Lock()


def _db() -> sqlite3.Connection | None:
    """Thread-local read-only connection, or None when no pack is installed."""
    path = paths.catena_db_path()
    if not os.path.exists(path):
        return None
    with _gen_lock:
        gen = _generation
    conn = getattr(_conn_local, 'conn', None)
    if conn is not None and getattr(_conn_local, 'gen', -1) == gen:
        return conn
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except sqlite3.Error:
        _log.exception('could not open catena pack at %s', path)
        return None
    _conn_local.conn = conn
    _conn_local.gen = gen
    return conn


def _reset() -> None:
    """Invalidate cached connections (call after install / remove)."""
    global _generation
    with _gen_lock:
        _generation += 1


# ── public API ──────────────────────────────────────────────────────────────

def is_catena_module(name: str) -> bool:
    return name == MODULE_KEY


def display_name(name: str) -> str:
    return MODULE_KEY


def is_installed() -> bool:
    conn = _db()
    if conn is None:
        return False
    try:
        return conn.execute('SELECT 1 FROM quotes LIMIT 1').fetchone() is not None
    except sqlite3.Error:
        return False


def module_names() -> list[str]:
    """The pane-picker module key, present only when a pack is installed."""
    return [MODULE_KEY] if is_installed() else []


def pack_info() -> dict[str, str]:
    """pack_meta as a flat dict (version, build date, quote count, …)."""
    conn = _db()
    if conn is None:
        return {}
    try:
        return dict(conn.execute('SELECT key, value FROM pack_meta').fetchall())
    except sqlite3.Error:
        return {}


def _encode(chapter: int, verse: int) -> int:
    return chapter * 1_000_000 + verse


def lookup(book: str, chapter: int, verse: int) -> list[CatenaEntry]:
    """Commentary entries on a verse, oldest first (unknown dates last)."""
    conn = _db()
    if conn is None:
        return []
    key = _encode(chapter, verse)
    try:
        rows = conn.execute(
            'SELECT author, author_suffix, year, era, source_title, '
            'source_url, wiki_url, text FROM quotes '
            'WHERE book = ? AND loc_start <= ? AND loc_end >= ? '
            'ORDER BY (year IS NULL OR year = ?), year, author',
            (book, key, key, _UNKNOWN_YEAR)).fetchall()
    except sqlite3.Error:
        _log.exception('catena lookup failed for %s %s:%s', book, chapter, verse)
        return []
    return [
        CatenaEntry(
            author=r[0], author_suffix=r[1], year=r[2], era=r[3],
            source_title=r[4], source_url=r[5], wiki_url=r[6], text=r[7])
        for r in rows
    ]


def download_and_install(on_progress: Callable[[int, int], None] | None = None,
                         url: str | None = None) -> None:
    """Download the gzipped pack, decompress it into place, and reset.

    Synchronous — call from a background thread. `on_progress(done, total)`
    reports downloaded bytes (total is 0 if the server sends no length).
    Writes through temp files and renames atomically, so an interrupted
    download never leaves a half-written pack in service.
    """
    url = url or PACK_URL
    dest = paths.catena_db_path()
    tmp_gz = dest + '.gz.part'
    tmp_db = dest + '.part'
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            total = int(resp.headers.get('Content-Length') or 0)
            done = 0
            with open(tmp_gz, 'wb') as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
        with gzip.open(tmp_gz, 'rb') as gz, open(tmp_db, 'wb') as out:
            shutil.copyfileobj(gz, out)
        os.replace(tmp_db, dest)
    finally:
        for p in (tmp_gz, tmp_db):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
    _reset()


def remove_pack() -> None:
    """Delete the installed pack and invalidate cached connections."""
    path = paths.catena_db_path()
    for p in (path, path + '-wal', path + '-shm'):
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            _log.exception('could not remove %s', p)
    _reset()
