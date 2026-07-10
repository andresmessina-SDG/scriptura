"""Scholar's Greek lexicon pack — TBESG (Abbott-Smith) + full LSJ.

Downloads STEPBible's formatted lexicons (Tyndale House Cambridge,
CC BY 4.0) into one local SQLite database:

- TBESG, the Translators Brief lexicon of Extended Strongs for Greek —
  Abbott-Smith's Manual Greek Lexicon of the New Testament, the standard
  "brief but scholarly" NT lexicon, keyed to Strong's numbers. Replaces
  Strong's 1890 definitions as the primary Greek entry when installed.
- TFLSJ, the full Liddell-Scott-Jones formatted by Tyndale House — the
  deep layer, one click away from the brief entry. Only the canonical
  0–5624 file is fetched: the "extra" file holds STEPBible-extended
  G6000+ ids (LXX-only words) that no NT click can produce.

Entries are stored as shipped; conversion to the lexicon panel's
HTML dialect (<b>/<i> survive, newlines are literal, everything else
is stripped by the panel) happens at lookup: <BR/> becomes a newline
and LSJ's citation tooltips (<a title="…">refs</a>) are inlined as
dimmed bracketed text — the citations are the scholarly point of LSJ,
and a hover-only surface would lose them.

Fetched from STEPBible's repository at install time (they ask that the
data not be re-hosted), gzip-negotiated like the interlinear downloads.
"""
import os
import re
import sqlite3
import unicodedata
import urllib.request
import zlib
from typing import Callable, Optional

import paths

_BASE = ('https://raw.githubusercontent.com/STEPBible/STEPBible-Data/'
         'master/Lexicons/')

_URLS = {
    'tbesg': (_BASE + 'TBESG%20-%20Translators%20Brief%20lexicon%20of%20'
              'Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20'
              'CC%20BY.txt'),
    'tflsj': (_BASE + 'TFLSJ%20%200-5624%20-%20Translators%20Formatted%20'
              'full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20'
              'CC%20BY.txt'),
}

# Tests monkeypatch this (never env vars — paths bind at import).
_DB_FILE = os.path.join(paths.open_data_dir(), 'greek_lexicon.sqlite')

ATTRIBUTION = 'STEPBible / Tyndale House Cambridge · CC BY 4.0'

_ENTRY_RE = re.compile(r'^G0*(\d+)$')


def is_installed() -> bool:
    return os.path.exists(_DB_FILE)


def parse_entry(line: str) -> Optional[tuple[str, str, str, str, str, str]]:
    """One lexicon data line → (strongs, lemma, translit, pos, gloss,
    entry_html), or None for headers/comments. Both files share the
    8-field shape; ids are normalized to the app's plain form (G26).
    Pure — unit-tested against real rows."""
    fields = unicodedata.normalize('NFC', line.rstrip('\n')).split('\t')
    if len(fields) != 8:
        return None
    m = _ENTRY_RE.match(fields[0])
    if not m:
        return None
    entry = fields[7].strip()
    if not entry:
        return None
    return ('G' + m.group(1), fields[3].strip(), fields[4].strip(),
            fields[5].strip(), fields[6].strip(), entry)


def download_and_build(
        on_progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Stream both lexicon files into one SQLite database. Raises on
    failure; atomic (.tmp sibling + os.replace). Same gzip-negotiating
    stream as interlinear_data — progress counts wire bytes."""
    os.makedirs(os.path.dirname(_DB_FILE), exist_ok=True)
    tmp = _DB_FILE + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    try:
        for table in ('tbesg', 'tflsj'):
            conn.execute(f'''
                CREATE TABLE {table} (
                    strongs TEXT PRIMARY KEY,
                    lemma TEXT NOT NULL, translit TEXT NOT NULL,
                    pos TEXT NOT NULL, gloss TEXT NOT NULL,
                    entry TEXT NOT NULL
                ) WITHOUT ROWID''')

        done_bytes = 0
        totals = _content_lengths() if on_progress else []
        total_bytes = sum(totals) if totals and all(totals) else 0
        for table, url in _URLS.items():
            batch: list[tuple[str, ...]] = []
            req = urllib.request.Request(
                url, headers={'Accept-Encoding': 'gzip'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                gz = (resp.headers.get('Content-Encoding') or '') == 'gzip'
                decomp = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz \
                    else None
                buf = b''
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        if decomp is not None:
                            buf += decomp.flush()
                        break
                    done_bytes += len(chunk)
                    buf += decomp.decompress(chunk) if decomp else chunk
                    *lines, buf = buf.split(b'\n')
                    for raw in lines:
                        row = parse_entry(raw.decode('utf-8', 'replace'))
                        if row is not None:
                            batch.append(row)
                    if on_progress:
                        try:
                            on_progress(done_bytes, total_bytes)
                        except Exception:
                            pass
                row = parse_entry(buf.decode('utf-8', 'replace'))
                if row is not None:
                    batch.append(row)
            # First row per plain id wins: primary entries precede the
            # 'a Meaning of' / 'a Form of' disambiguation rows.
            conn.executemany(
                f'INSERT OR IGNORE INTO {table} VALUES (?,?,?,?,?,?)',
                batch)
        n_brief = conn.execute('SELECT COUNT(*) FROM tbesg').fetchone()[0]
        n_lsj = conn.execute('SELECT COUNT(*) FROM tflsj').fetchone()[0]
        if n_brief < 4000 or n_lsj < 4000:
            raise ValueError(
                f'lexicon parse produced {n_brief}/{n_lsj} entries; '
                'refusing install')
        conn.commit()
    except BaseException:
        conn.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    conn.close()
    os.replace(tmp, _DB_FILE)


def _content_lengths() -> list[int]:
    sizes = []
    for url in _URLS.values():
        try:
            req = urllib.request.Request(
                url, method='HEAD', headers={'Accept-Encoding': 'gzip'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                sizes.append(int(resp.headers.get('Content-Length') or 0))
        except Exception:
            sizes.append(0)
    return sizes


def remove() -> None:
    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)


# ── Conversion to the lexicon panel's dialect ─────────────────────────────────

_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_CITE_RE = re.compile(r'<a\s[^>]*title="([^"]*)"[^>]*>(.*?)</a>',
                      re.DOTALL)


_INDENT_RE = re.compile(r'^((?:\s*<[^>]+>)*\s*)_{2,}', re.MULTILINE)

# Hebrew runs inside the English prose (the '[in LXX for …]' lines).
# Without isolation, a comma between two adjacent RTL words joins their
# bidi run and the pair renders reversed with the comma on the wrong
# side; wrapping each run in FSI…PDI (zero-width) keeps the list in
# logical order while each word still shapes right-to-left.
_HEBREW_RUN_RE = re.compile(r'[\u0590-\u05FF]+')


def to_panel_html(entry: str) -> str:
    """Shipped entry HTML → the dialect lexicon_panel._html_to_markup
    speaks: literal newlines, <b>/<i> kept, LSJ citation tooltips inlined
    as bracketed italic text (the panel strips every other tag, which
    disposes of <ref>/<re>/<Level…> wrappers while keeping their text).
    STEPBible's '__' hierarchy markers (line-leading, possibly inside a
    <b>/<Level…> wrapper) become an em-space indent — the print lexicons'
    own layout for I. / 1. / (a) sense levels."""
    s = _CITE_RE.sub(lambda m: f'{m.group(2)} <i>[{m.group(1).strip()}]</i>',
                     entry)
    s = _BR_RE.sub('\n', s)
    s = _INDENT_RE.sub('\\1 ', s)
    s = _HEBREW_RUN_RE.sub('⁨\\g<0>⁩', s)
    # STEPBible pre-compensated for fused RTL runs by writing the
    # comma between two Hebrew words as ' ,' glued to the SECOND
    # word; with each run isolated, restore the logical ', '.
    s = s.replace('⁩ ,⁨', '⁩, ⁨')
    return s.strip()


# ── Scripture references in rendered entry text ──────────────────────────────

# Abbott-Smith's visible-text abbreviations → app book names. Only books
# in the app's canon appear; deuterocanonical citations (Sir, Wis, 1-4Ma,
# Tob, Jdth, Bar, 1Es) resolve to nothing and stay plain text. 1Ki–4Ki
# follow the LXX Kingdoms numbering — confirmed empirically: TBESG cites
# 1Ki.31 (1 Samuel has 31 chapters, 1 Kings only 22).
_REF_BOOKS = {
    'Gen': 'Genesis', 'Exo': 'Exodus', 'Lev': 'Leviticus',
    'Num': 'Numbers', 'Deu': 'Deuteronomy', 'Jos': 'Joshua',
    'Jdg': 'Judges', 'Rut': 'Ruth',
    '1Ki': '1 Samuel', '2Ki': '2 Samuel',
    '3Ki': '1 Kings', '4Ki': '2 Kings',
    '1Ch': '1 Chronicles', '2Ch': '2 Chronicles',
    'Ezr': 'Ezra', 'Neh': 'Nehemiah', 'Est': 'Esther', 'Job': 'Job',
    'Psa': 'Psalms', 'Pro': 'Proverbs', 'Ecc': 'Ecclesiastes',
    'Sng': 'Song of Solomon', 'Isa': 'Isaiah', 'Jer': 'Jeremiah',
    'Lam': 'Lamentations', 'Eze': 'Ezekiel', 'Dan': 'Daniel',
    'Hos': 'Hosea', 'Jol': 'Joel', 'Amo': 'Amos', 'Oba': 'Obadiah',
    'Jon': 'Jonah', 'Mic': 'Micah', 'Nam': 'Nahum', 'Hab': 'Habakkuk',
    'Zep': 'Zephaniah', 'Hag': 'Haggai', 'Zec': 'Zechariah',
    'Mal': 'Malachi',
    'Mat': 'Matthew', 'Mrk': 'Mark', 'Luk': 'Luke', 'Jhn': 'John',
    'Act': 'Acts', 'Rom': 'Romans',
    '1Co': '1 Corinthians', '2Co': '2 Corinthians',
    '1Cor': '1 Corinthians', '2Cor': '2 Corinthians',
    'Gal': 'Galatians', 'Eph': 'Ephesians', 'Php': 'Philippians',
    'Col': 'Colossians',
    '1Th': '1 Thessalonians', '2Th': '2 Thessalonians',
    '1Ti': '1 Timothy', '2Ti': '2 Timothy', 'Tit': 'Titus',
    'Phm': 'Philemon', 'Heb': 'Hebrews', 'Jas': 'James',
    '1Pe': '1 Peter', '2Pe': '2 Peter',
    '1Jn': '1 John', '2Jn': '2 John', '3Jn': '3 John',
    '1Jo': '1 John', '2Jo': '2 John', '3Jo': '3 John',
    'Jud': 'Jude', 'Rev': 'Revelation',
}

# Book.C:V with the colon directly after the chapter — this deliberately
# skips the dual-numbered LXX psalm forms ('Psa.81(82):6'), whose target
# numbering the app can't pick reliably.
_SCRIPTURE_REF_RE = re.compile(r'\b(\d?[A-Z][a-z]{1,3})\.(\d+):(\d+)')


def scripture_refs(text: str) -> list[tuple[int, int, str, int, int]]:
    """(start, end, app_book, chapter, verse) for every clickable
    scripture reference in rendered definition text. Pure — offsets
    index the text as passed (the panel's buffer contents)."""
    out = []
    for m in _SCRIPTURE_REF_RE.finditer(text):
        book = _REF_BOOKS.get(m.group(1))
        if book:
            out.append((m.start(), m.end(), book,
                        int(m.group(2)), int(m.group(3))))
    return out


# ── Lookups ───────────────────────────────────────────────────────────────────
# Fresh connection per call (click-paced; callers run on worker threads).

def _norm_key(strongs: str) -> str:
    """Callers pass both normalized ('G26') and raw zero-padded module
    forms ('G0026') — fold to the stored key shape."""
    m = re.match(r'^([GH])0*(\d+)', (strongs or '').strip(), re.IGNORECASE)
    if not m:
        return (strongs or '').strip().upper()
    return m.group(1).upper() + m.group(2)


def _lookup(table: str, strongs: str) -> Optional[str]:
    if not is_installed():
        return None
    conn = sqlite3.connect(_DB_FILE)
    try:
        row = conn.execute(
            f'SELECT entry FROM {table} WHERE strongs = ?',
            (_norm_key(strongs),)).fetchone()
    finally:
        conn.close()
    return to_panel_html(row[0]) if row else None


def lookup_brief(strongs: str) -> Optional[str]:
    """Abbott-Smith entry in panel dialect, or None."""
    return _lookup('tbesg', strongs)


def lookup_lsj(strongs: str) -> Optional[str]:
    """Full LSJ entry in panel dialect, or None."""
    return _lookup('tflsj', strongs)


def _has(table: str, strongs: str) -> bool:
    if not is_installed():
        return False
    conn = sqlite3.connect(_DB_FILE)
    try:
        row = conn.execute(
            f'SELECT 1 FROM {table} WHERE strongs = ?',
            (_norm_key(strongs),)).fetchone()
    finally:
        conn.close()
    return row is not None


def has_brief(strongs: str) -> bool:
    """Cheap existence probe (indexed point query) — tells the panel the
    shown definition is the pack's Abbott-Smith entry (the lookup
    preference order guarantees it when the pack carries the word)."""
    return _has('tbesg', strongs)


def has_lsj(strongs: str) -> bool:
    """Cheap existence probe — drives the panel's 'Full LSJ entry'
    affordance without fetching the (large) entry."""
    return _has('tflsj', strongs)
