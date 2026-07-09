"""Interlinear Greek NT data layer (TAGNT).

Downloads the Translators Amalgamated Greek NT from STEPBible's repository
(Tyndale House Cambridge, CC BY 4.0) and parses it into a local SQLite
database, one row per word: surface form, transliteration, context-sensitive
English gloss, disambiguated Strong's, Robinson morphology, lemma and lexical
gloss, plus the edition markers (NA/TR/Byz…) for a future collation surface.

The default rendered stream is the NA28-equivalent text: rows whose
type marker contains N/n. TR/Byz-only words (K/O types) are stored but
not rendered, so a later apparatus can surface them without re-downloading.

STEPBible asks that the data be fetched from their repository rather than
re-hosted, so installation streams from raw.githubusercontent.com — the
same at-install pattern as the OpenBible downloads in open_data.py.
"""
import os
import re
import sqlite3
import unicodedata
import urllib.request
from typing import Callable, NamedTuple, Optional

import paths
from i18n import _

# Module global so tests can monkeypatch the DB location (never env vars —
# paths bind at import).
_DB_FILE = os.path.join(paths.open_data_dir(), 'interlinear_greek.sqlite')

_URLS = [
    'https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/'
    'Translators%20Amalgamated%20OT%2BNT/'
    'TAGNT%20Mat-Jhn%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20'
    'STEPBible.org%20CC-BY.txt',
    'https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/'
    'Translators%20Amalgamated%20OT%2BNT/'
    'TAGNT%20Act-Rev%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20'
    'STEPBible.org%20CC-BY.txt',
]

# Pseudo-module identity, mirroring catena_bridge/imagery_bridge so the
# module picker, pane dispatch, and settings all treat it as a module name.
MODULE_NAME = 'InterlinearGreek'

ATTRIBUTION = 'STEPBible / Tyndale House Cambridge · CC BY 4.0'

_BOOK_CODES = {
    'Mat': 'Matthew', 'Mrk': 'Mark', 'Luk': 'Luke', 'Jhn': 'John',
    'Act': 'Acts', 'Rom': 'Romans', '1Co': '1 Corinthians',
    '2Co': '2 Corinthians', 'Gal': 'Galatians', 'Eph': 'Ephesians',
    'Php': 'Philippians', 'Col': 'Colossians', '1Th': '1 Thessalonians',
    '2Th': '2 Thessalonians', '1Ti': '1 Timothy', '2Ti': '2 Timothy',
    'Tit': 'Titus', 'Phm': 'Philemon', 'Heb': 'Hebrews', 'Jas': 'James',
    '1Pe': '1 Peter', '2Pe': '2 Peter', '1Jn': '1 John', '2Jn': '2 John',
    '3Jn': '3 John', 'Jud': 'Jude', 'Rev': 'Revelation',
}


class Word(NamedTuple):
    verse: int
    pos: int
    surface: str
    translit: str
    gloss: str
    strongs: str        # normalized primary Strong's, e.g. 'G1080'
    strongs_all: str    # space-joined normalized list (compounds: 'G1473 G2532')
    morph: str          # Robinson code(s), space-joined for compounds
    lemma: str
    lemma_gloss: str


class ParsedRow(NamedTuple):
    book: str
    chapter: int
    verse: int
    pos: int
    wtype: str
    surface: str
    translit: str
    gloss: str
    strongs: str
    strongs_all: str
    strongs_ext: str
    morph: str
    lemma: str
    lemma_gloss: str
    editions: str


_REF_RE = re.compile(r'^([0-9A-Za-z]{2,3})\.(\d+)\.(\d+)#(\d+)=(\S+)$')
_SURFACE_RE = re.compile(r'^(.*?)\s*\(([^)]*)\)\s*$')


def _norm_strongs(ext: str) -> str:
    """'G0011' / 'G2424G' → the app's plain form ('G11' / 'G2424'):
    letter + digits with leading zeros stripped, disambiguation suffix
    dropped — the key shape lookup_strong/lookup_dodson expect."""
    m = re.match(r'^([GH])0*(\d+)', ext.strip(), re.IGNORECASE)
    if not m:
        return ext.strip().upper()
    return m.group(1).upper() + m.group(2)


def parse_line(line: str) -> Optional[ParsedRow]:
    """One TAGNT data line → ParsedRow, or None for headers/comments/blank
    lines. Pure — unit-tested against real rows."""
    # The shipped files carry decomposed (NFD) Greek; the app's SWORD texts
    # and lexicon keys are NFC — normalize once at parse time.
    fields = unicodedata.normalize('NFC', line.rstrip('\n')).split('\t')
    if len(fields) < 6:
        return None
    m = _REF_RE.match(fields[0].strip())
    if not m:
        return None
    code, chapter, verse, pos, wtype = m.groups()
    book = _BOOK_CODES.get(code)
    if book is None:
        return None

    sm = _SURFACE_RE.match(fields[1].strip())
    if sm:
        surface, translit = sm.group(1), sm.group(2)
    else:
        surface, translit = fields[1].strip(), ''
    # TAGNT embeds paragraph/line markers in surface forms (Ἰακώβ.¶) —
    # layout metadata, not text; [brackets] are text-critical and kept.
    surface = surface.replace('¶', '').replace('¬', '').strip()

    gloss = fields[2].strip()

    # Grammar: 'G1080=V-AAI-3S' or compounds 'G1473=P-1NS + G2532=CONJ'.
    exts, morphs = [], []
    for pair in fields[3].split(' + '):
        left, _sep, right = pair.strip().partition('=')
        if left:
            exts.append(left.strip())
            morphs.append(right.strip())
    strongs_all = ' '.join(_norm_strongs(e) for e in exts)
    strongs = strongs_all.split(' ')[0] if strongs_all else ''

    # Lemma: 'γεννάω=to beget'; spelling variants list the forms
    # comma-separated ('Δαυείδ, Δαυίδ, Δαβίδ=David') — keep the first.
    lemma_field, _sep, lemma_gloss = fields[4].partition('=')
    lemma = lemma_field.split(',')[0].strip()

    return ParsedRow(
        book=book, chapter=int(chapter), verse=int(verse), pos=int(pos),
        wtype=wtype, surface=surface, translit=translit, gloss=gloss,
        strongs=strongs, strongs_all=strongs_all,
        strongs_ext=' '.join(exts), morph=' '.join(m for m in morphs if m),
        lemma=lemma, lemma_gloss=lemma_gloss.strip(),
        editions=fields[5].strip(),
    )


def in_na_stream(wtype: str) -> bool:
    """Whether a type marker (NKO, N(k)O, K, ko…) places the word in the
    NA-equivalent text — any N, parenthesised or not, upper or lower."""
    return 'n' in wtype.lower()


# ── Installation ──────────────────────────────────────────────────────────────

def is_installed() -> bool:
    return os.path.exists(_DB_FILE)


def is_interlinear_module(name: str) -> bool:
    return name == MODULE_NAME


def module_names() -> list[str]:
    return [MODULE_NAME] if is_installed() else []


def display_name(name: str) -> str:
    return _('Interlinear — Greek NT')


def download_and_build(
        on_progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Stream both TAGNT files and build the SQLite database. Raises on
    failure. on_progress(bytes_done, bytes_total) follows the open_data
    contract (total may be 0); rows are parsed as bytes stream in, so the
    byte scale tracks the whole build except the final count-check/commit.
    Atomic: builds to a .tmp sibling, os.replace."""
    os.makedirs(os.path.dirname(_DB_FILE), exist_ok=True)
    tmp = _DB_FILE + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    try:
        conn.execute('''
            CREATE TABLE words (
                book TEXT NOT NULL, chapter INTEGER NOT NULL,
                verse INTEGER NOT NULL, pos INTEGER NOT NULL,
                wtype TEXT NOT NULL, in_na INTEGER NOT NULL,
                surface TEXT NOT NULL, translit TEXT NOT NULL,
                gloss TEXT NOT NULL,
                strongs TEXT NOT NULL, strongs_all TEXT NOT NULL,
                strongs_ext TEXT NOT NULL, morph TEXT NOT NULL,
                lemma TEXT NOT NULL, lemma_gloss TEXT NOT NULL,
                editions TEXT NOT NULL,
                PRIMARY KEY (book, chapter, verse, pos)
            ) WITHOUT ROWID''')

        done_bytes = 0
        # The HEAD pre-flight only serves progress scaling — skip both
        # round trips when nobody is listening.
        totals = _content_lengths() if on_progress else []
        total_bytes = sum(totals) if totals and all(totals) else 0
        batch: list[tuple[object, ...]] = []
        for url in _URLS:
            with urllib.request.urlopen(url, timeout=60) as resp:
                buf = b''
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    done_bytes += len(chunk)
                    buf += chunk
                    *lines, buf = buf.split(b'\n')
                    for raw in lines:
                        row = parse_line(raw.decode('utf-8', 'replace'))
                        if row is not None:
                            batch.append((
                                row.book, row.chapter, row.verse, row.pos,
                                row.wtype, int(in_na_stream(row.wtype)),
                                row.surface, row.translit, row.gloss,
                                row.strongs, row.strongs_all, row.strongs_ext,
                                row.morph, row.lemma, row.lemma_gloss,
                                row.editions))
                    if len(batch) >= 2000:
                        conn.executemany(
                            'INSERT OR REPLACE INTO words VALUES '
                            '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', batch)
                        batch.clear()
                    if on_progress:
                        try:
                            on_progress(done_bytes, total_bytes)
                        except Exception:
                            pass
                row = parse_line(buf.decode('utf-8', 'replace'))
                if row is not None:
                    batch.append((
                        row.book, row.chapter, row.verse, row.pos,
                        row.wtype, int(in_na_stream(row.wtype)),
                        row.surface, row.translit, row.gloss,
                        row.strongs, row.strongs_all, row.strongs_ext,
                        row.morph, row.lemma, row.lemma_gloss, row.editions))
        if batch:
            conn.executemany(
                'INSERT OR REPLACE INTO words VALUES '
                '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', batch)
        # Guard against a truncated or wrong-file download building an
        # empty shell that is_installed() would then report as ready.
        count = conn.execute('SELECT COUNT(*) FROM words').fetchone()[0]
        if count < 100000:
            raise ValueError(
                f'TAGNT parse produced only {count} words; refusing install')
        conn.commit()
    except BaseException:
        conn.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    conn.close()
    os.replace(tmp, _DB_FILE)


def _content_lengths() -> list[int]:
    """Content-Length of each source file (0 where the server omits it) —
    lets the two-file download report one continuous progress scale."""
    sizes = []
    for url in _URLS:
        try:
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=15) as resp:
                sizes.append(int(resp.headers.get('Content-Length') or 0))
        except Exception:
            sizes.append(0)
    return sizes


def remove() -> None:
    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)


# ── Queries ───────────────────────────────────────────────────────────────────
# A fresh connection per query: chapter loads are rare (navigation-paced)
# and callers run on pane worker threads, so per-call connections avoid
# cross-thread sharing entirely.

_migrated = False


def _migrate(conn: sqlite3.Connection) -> None:
    """One-shot cleanup of databases built before parse_line stripped
    TAGNT's ¶/¬ layout markers from surface forms — saves an existing
    install the 29 MB re-download. Gated on a cheap probe so clean
    databases pay one indexed-scan LIMIT 1 per process."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    dirty = conn.execute(
        "SELECT 1 FROM words WHERE surface LIKE '%¶%' "
        "OR surface LIKE '%¬%' LIMIT 1").fetchone()
    if dirty:
        conn.execute(
            "UPDATE words SET surface = TRIM(REPLACE(REPLACE("
            "surface, '¶', ''), '¬', '')) "
            "WHERE surface LIKE '%¶%' OR surface LIKE '%¬%'")
        conn.commit()


def load_chapter(book: str, chapter: int) -> list[Word]:
    """The NA-stream words of one chapter, in canonical word order."""
    if not is_installed():
        return []
    conn = sqlite3.connect(_DB_FILE)
    _migrate(conn)
    try:
        rows = conn.execute(
            'SELECT verse, pos, surface, translit, gloss, strongs, '
            'strongs_all, morph, lemma, lemma_gloss FROM words '
            'WHERE book=? AND chapter=? AND in_na=1 ORDER BY verse, pos',
            (book, chapter)).fetchall()
    finally:
        conn.close()
    return [Word(*r) for r in rows]


def chapter_count(book: str) -> int:
    """Highest chapter present for a book (0 when absent) — keeps the
    interlinear's navigation self-contained rather than assuming the
    KJV shape."""
    if not is_installed():
        return 0
    conn = sqlite3.connect(_DB_FILE)
    try:
        row = conn.execute(
            'SELECT MAX(chapter) FROM words WHERE book=?', (book,)).fetchone()
    finally:
        conn.close()
    return int(row[0] or 0)
