"""imagery_bridge.py — read access to the Bible Imagery pack.

The pack is a directory (downloaded on demand from Module Manager and
extracted into `paths.imagery_dir()`) containing a single SQLite catalog
`imagery.sqlite` plus an `images/` tree. Mirrors `catena_bridge` for
connection management and `ebible_bridge` for the verse-query shape.

Two content families feed the pane's two tabs:

  * **Art** — illustrations/paintings/icons/glass, located by an encoded
    verse *range* so a plate spanning several verses (or chapters) surfaces
    on every verse it covers.
  * **Where** — maps (same range model) plus the *places* named in the
    exact verse (from the `places` / `place_verses` tables).

Verse range encoding mirrors catena: a location is `chapter * 1_000_000 +
verse`, and a row covers `[loc_start, loc_end]`. This single-key encoding
handles cross-chapter ranges correctly — separate chapter/verse columns
do not (Acts 13:1–14:28 would wrongly exclude 13:40). `passage_label`
carries the human-readable scope for display.
"""

import logging
import os
import shutil
import sqlite3
import tarfile
import threading
import urllib.error
import urllib.request
from typing import Callable, TypedDict

import paths

_log = logging.getLogger('scriptura.imagery')

# The single pane-picker module name this bridge contributes.
MODULE_KEY = 'Bible Imagery'

# The downloadable pack (tar.gz so stdlib `tarfile` handles it — no zstd
# dependency). Hosted on Codeberg Releases; replace the tag once published.
PACK_URL = ('https://codeberg.org/andresmessina/scriptura/releases/'
            'download/imagery-pack-v1/imagery.tar.gz')

# Illustration kinds shown in the "Art" tab; 'map' goes to "Where".
_ART_KINDS = ('illustration', 'painting', 'icon', 'glass')

# House-style-first ordering: the antique-cohesive engraving sorts first so a
# reader defaulting to one tradition lands on it; lower rank = shown first.
_TRADITION_RANK = {
    'engraving': 0,
    'old_master': 1,
    'byzantine_icon': 2,
    'illumination': 3,
    'stained_glass': 4,
    'watercolor': 5,
    'photo': 6,
    'cartography': 7,
}


class ImageryItem(TypedDict):
    kind: str
    tradition: str
    title: str
    caption: str | None
    passage_label: str | None
    path: str | None          # absolute path on disk, or None if missing
    source: str
    source_url: str | None
    license: str
    attribution: str | None
    artist: str | None
    year: int | None


class Place(TypedDict):
    place_id: str
    ancient_name: str
    modern_name: str | None
    confidence: int | None
    path: str | None          # absolute photo path, or None
    caption: str | None       # 'aerial panorama of ruins at Tel …'
    credit: str | None        # photographer / author
    license: str | None       # human-readable, e.g. 'CC BY-SA 4.0'
    source_url: str | None    # Commons file page


# ── connection (thread-local, read-only) ───────────────────────────────────────

# The catalog is read-only at runtime (built offline / installed wholesale),
# so each thread keeps its own read connection. _generation is bumped by
# install/remove so cached connections to a replaced or deleted file reopen.
_conn_local = threading.local()
_generation = 0
_gen_lock = threading.Lock()


def _db() -> sqlite3.Connection | None:
    """Thread-local read-only connection, or None when no pack is installed."""
    path = paths.imagery_db_path()
    if not os.path.exists(path):
        return None
    with _gen_lock:
        gen = _generation
    conn: sqlite3.Connection | None = getattr(_conn_local, 'conn', None)
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
        _log.exception('could not open imagery pack at %s', path)
        return None
    _conn_local.conn = conn
    _conn_local.gen = gen
    return conn


def _reset() -> None:
    """Invalidate cached connections (call after install / remove)."""
    global _generation
    with _gen_lock:
        _generation += 1


def _abs(rel: str | None) -> str | None:
    """Resolve a stored relative file path to an absolute one (None if absent)."""
    if not rel:
        return None
    return os.path.join(paths.imagery_dir(), rel)


# ── public predicate / metadata API ────────────────────────────────────────────

def is_imagery_module(name: str) -> bool:
    return name == MODULE_KEY


def display_name(name: str) -> str:
    # Curated feature name shown in the UI. MODULE_KEY ('Bible Imagery')
    # remains the on-disk identity used everywhere else.
    return _('Scripture in Art')


def is_installed() -> bool:
    conn = _db()
    if conn is None:
        return False
    try:
        return conn.execute('SELECT 1 FROM imagery LIMIT 1').fetchone() is not None
    except sqlite3.Error:
        return False


def module_names() -> list[str]:
    """The pane-picker module key, present only when a pack is installed."""
    return [MODULE_KEY] if is_installed() else []


def pack_info() -> dict[str, str]:
    """pack_meta as a flat dict (version, build date, counts, …)."""
    conn = _db()
    if conn is None:
        return {}
    try:
        return dict(conn.execute('SELECT key, value FROM pack_meta').fetchall())
    except sqlite3.Error:
        return {}


def _encode(chapter: int, verse: int) -> int:
    return chapter * 1_000_000 + verse


# ── verse → content queries ─────────────────────────────────────────────────

def _item(row: sqlite3.Row | tuple) -> ImageryItem:
    return ImageryItem(
        kind=row[0], tradition=row[1], title=row[2], caption=row[3],
        passage_label=row[4], path=_abs(row[5]), source=row[6],
        source_url=row[7], license=row[8], attribution=row[9],
        artist=row[10], year=row[11])


_ITEM_COLS = ('kind, tradition, title, caption, passage_label, file_path, '
              'source, source_url, license, attribution, artist, year')


def art_for(book: str, chapter: int, verse: int) -> list[ImageryItem]:
    """Illustrations covering a verse, house-tradition first then by year.

    Ordered so a reader showing one tradition by default lands on the
    antique-cohesive engraving; the rest follow for the "other traditions"
    expansion."""
    conn = _db()
    if conn is None:
        return []
    key = _encode(chapter, verse)
    placeholders = ','.join('?' for _ in _ART_KINDS)
    try:
        rows = conn.execute(
            f'SELECT {_ITEM_COLS} FROM imagery '
            f'WHERE book = ? AND kind IN ({placeholders}) '
            f'AND loc_start <= ? AND loc_end >= ?',
            (book, *_ART_KINDS, key, key)).fetchall()
    except sqlite3.Error:
        _log.exception('imagery art lookup failed for %s %s:%s',
                       book, chapter, verse)
        return []
    items = [_item(r) for r in rows]
    items.sort(key=lambda it: (_TRADITION_RANK.get(it['tradition'], 99),
                               it['year'] if it['year'] is not None else 99999,
                               it['title']))
    return items


def maps_for(book: str, chapter: int, verse: int) -> list[ImageryItem]:
    """Maps whose passage range covers a verse (oldest first)."""
    conn = _db()
    if conn is None:
        return []
    key = _encode(chapter, verse)
    try:
        rows = conn.execute(
            f'SELECT {_ITEM_COLS} FROM imagery '
            f"WHERE book = ? AND kind = 'map' "
            f'AND loc_start <= ? AND loc_end >= ? '
            f'ORDER BY (year IS NULL), year, title',
            (book, key, key)).fetchall()
    except sqlite3.Error:
        _log.exception('imagery map lookup failed for %s %s:%s',
                       book, chapter, verse)
        return []
    return [_item(r) for r in rows]


def places_for(book: str, chapter: int, verse: int) -> list[Place]:
    """Places named in the exact verse, most-confident first."""
    conn = _db()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            'SELECT p.place_id, p.ancient_name, p.modern_name, p.confidence, '
            'p.photo_path, p.photo_caption, p.photo_credit, p.photo_license, '
            'p.photo_source_url FROM places p '
            'JOIN place_verses v ON v.place_id = p.place_id '
            'WHERE v.book = ? AND v.chapter = ? AND v.verse = ? '
            'ORDER BY (p.confidence IS NULL), p.confidence DESC, p.ancient_name',
            (book, chapter, verse)).fetchall()
    except sqlite3.Error:
        _log.exception('imagery place lookup failed for %s %s:%s',
                       book, chapter, verse)
        return []
    return [
        Place(place_id=r[0], ancient_name=r[1], modern_name=r[2],
              confidence=r[3], path=_abs(r[4]), caption=r[5], credit=r[6],
              license=r[7], source_url=r[8])
        for r in rows
    ]


# ── install / remove ─────────────────────────────────────────────────────────

def _safe_extract(tar: tarfile.TarFile, dest: str) -> None:
    """Extract guarding against path traversal (`../` escapes / absolute paths)."""
    dest_abs = os.path.abspath(dest)
    for member in tar.getmembers():
        target = os.path.abspath(os.path.join(dest, member.name))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise ValueError(f'unsafe path in imagery archive: {member.name}')
    tar.extractall(dest)


def _probe(url: str) -> int | None:
    """Return the byte size of `url` if it exists, or None on 404.

    Uses a one-byte ranged GET so it works on hosts that don't allow HEAD;
    the total comes from Content-Range (`bytes 0-0/<total>`) when the server
    honours the range, else from Content-Length. Any non-404 HTTP error is
    raised — a transient failure must abort, never look like 'no more parts'.
    """
    req = urllib.request.Request(url, headers={'Range': 'bytes=0-0'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            cr = r.headers.get('Content-Range')
            if cr and '/' in cr:
                tail = cr.rsplit('/', 1)[1]
                if tail.isdigit():
                    return int(tail)
            return int(r.headers.get('Content-Length') or 0)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except urllib.error.URLError as e:
        # A missing file:// path surfaces as URLError(FileNotFoundError) —
        # treat as 'not found'; real network failures still propagate.
        if isinstance(e.reason, FileNotFoundError):
            return None
        raise


def _resolve_parts(url: str) -> list[tuple[str, int]]:
    """Resolve the pack to an ordered list of (part_url, size).

    Packs too large for a single release asset (host caps vary, e.g. 100 MB)
    are split into `<url>.000`, `<url>.001`, … which the installer downloads
    in order and concatenates. A single `<url>` is used when no `.000` part
    exists, so small packs keep working unchanged. The part count is open —
    probing stops at the first 404 — so the pack can grow without code
    changes."""
    first = _probe(f'{url}.000')
    if first is None:
        size = _probe(url)
        if size is None:
            raise FileNotFoundError(f'imagery pack not found at {url}')
        return [(url, size)]
    parts = [(f'{url}.000', first)]
    i = 1
    while True:
        size = _probe(f'{url}.{i:03d}')
        if size is None:
            break
        parts.append((f'{url}.{i:03d}', size))
        i += 1
    return parts


def download_and_install(on_progress: Callable[[int, int], None] | None = None,
                         url: str | None = None) -> None:
    """Download the .tar.gz pack, extract it into place, and reset.

    Synchronous — call from a background thread. `on_progress(done, total)`
    reports downloaded bytes (total is 0 if sizes are unknown). Large packs
    are served as ordered `.000/.001/…` parts (see _resolve_parts); they are
    streamed in sequence into one archive, so concatenation is implicit.
    Extracts into a sibling staging dir then swaps it in, so an interrupted
    download never leaves a half-written pack in service.
    """
    url = url or PACK_URL
    dest_dir = paths.imagery_dir()
    parent = os.path.dirname(dest_dir)
    staging = dest_dir + '.part'
    tmp_archive = os.path.join(parent, '.imagery.tar.gz.part')
    shutil.rmtree(staging, ignore_errors=True)
    try:
        parts = _resolve_parts(url)
        total = sum(size for _, size in parts)
        done = 0
        with open(tmp_archive, 'wb') as out:
            for part_url, _size in parts:
                with urllib.request.urlopen(part_url, timeout=120) as resp:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total)
        os.makedirs(staging, exist_ok=True)
        with tarfile.open(tmp_archive, mode='r:gz') as tar:
            _safe_extract(tar, staging)
        shutil.rmtree(dest_dir, ignore_errors=True)
        os.replace(staging, dest_dir)
    finally:
        try:
            if os.path.exists(tmp_archive):
                os.remove(tmp_archive)
        except OSError:
            pass
        shutil.rmtree(staging, ignore_errors=True)
    _reset()


def remove_pack() -> None:
    """Delete the installed pack directory and invalidate cached connections."""
    try:
        shutil.rmtree(paths.imagery_dir(), ignore_errors=True)
    except OSError:
        _log.exception('could not remove imagery pack')
    _reset()
