"""Interlinear data layer — TAGNT (Greek NT) and TAHOT (Hebrew OT).

Downloads STEPBible's Translators Amalgamated texts (Tyndale House
Cambridge, CC BY 4.0) and parses them into local SQLite databases, one
row per word: surface form, transliteration, context-sensitive English
gloss, disambiguated Strong's, morphology (Robinson / OSHM), lemma and
lexical gloss.

Greek: the rendered stream is the NA28-equivalent text (type markers
containing N/n); TR/Byz-only words are stored but not rendered, with the
edition markers kept for a future collation surface.

Hebrew: the rendered stream is Leningrad plus Qere readings plus the
verses Leningrad omits but the KJV-shaped app-space carries (type L/Q/R;
X-typed insertion rows are stored but not rendered). TAHOT references
are already English-first (`Psa.56.7(56.8)`), so no versification
mapping is needed. Surface forms arrive morpheme-slashed with
backslash-escaped punctuation and parashah markers — cleaned at parse.

STEPBible asks that the data be fetched from their repository rather
than re-hosted, so installation streams from raw.githubusercontent.com —
the same at-install pattern as the OpenBible downloads in open_data.py.
"""
import os
import re
import sqlite3
import unicodedata
import urllib.request
import zlib
from typing import Callable, NamedTuple, Optional

import paths
from i18n import _

_BASE = ('https://raw.githubusercontent.com/STEPBible/STEPBible-Data/'
         'master/Translators%20Amalgamated%20OT%2BNT/')

GREEK = 'InterlinearGreek'
HEBREW = 'InterlinearHebrew'

ATTRIBUTION = 'STEPBible / Tyndale House Cambridge · CC BY 4.0'

_GREEK_BOOKS = {
    'Mat': 'Matthew', 'Mrk': 'Mark', 'Luk': 'Luke', 'Jhn': 'John',
    'Act': 'Acts', 'Rom': 'Romans', '1Co': '1 Corinthians',
    '2Co': '2 Corinthians', 'Gal': 'Galatians', 'Eph': 'Ephesians',
    'Php': 'Philippians', 'Col': 'Colossians', '1Th': '1 Thessalonians',
    '2Th': '2 Thessalonians', '1Ti': '1 Timothy', '2Ti': '2 Timothy',
    'Tit': 'Titus', 'Phm': 'Philemon', 'Heb': 'Hebrews', 'Jas': 'James',
    '1Pe': '1 Peter', '2Pe': '2 Peter', '1Jn': '1 John', '2Jn': '2 John',
    '3Jn': '3 John', 'Jud': 'Jude', 'Rev': 'Revelation',
}

_HEBREW_BOOKS = {
    'Gen': 'Genesis', 'Exo': 'Exodus', 'Lev': 'Leviticus',
    'Num': 'Numbers', 'Deu': 'Deuteronomy', 'Jos': 'Joshua',
    'Jdg': 'Judges', 'Rut': 'Ruth', '1Sa': '1 Samuel', '2Sa': '2 Samuel',
    '1Ki': '1 Kings', '2Ki': '2 Kings', '1Ch': '1 Chronicles',
    '2Ch': '2 Chronicles', 'Ezr': 'Ezra', 'Neh': 'Nehemiah',
    'Est': 'Esther', 'Job': 'Job', 'Psa': 'Psalms', 'Pro': 'Proverbs',
    'Ecc': 'Ecclesiastes', 'Sng': 'Song of Solomon', 'Isa': 'Isaiah',
    'Jer': 'Jeremiah', 'Lam': 'Lamentations', 'Ezk': 'Ezekiel',
    'Dan': 'Daniel', 'Hos': 'Hosea', 'Jol': 'Joel', 'Amo': 'Amos',
    'Oba': 'Obadiah', 'Jon': 'Jonah', 'Mic': 'Micah', 'Nam': 'Nahum',
    'Hab': 'Habakkuk', 'Zep': 'Zephaniah', 'Hag': 'Haggai',
    'Zec': 'Zechariah', 'Mal': 'Malachi',
}


class Word(NamedTuple):
    verse: int
    pos: int
    surface: str
    translit: str
    gloss: str
    strongs: str        # normalized primary Strong's, e.g. 'G1080' / 'H7225'
    strongs_all: str    # space-joined normalized list (compounds/affix chains)
    morph: str          # Robinson code(s) / OSHM chain
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
    rendered: bool


_REF_RE = re.compile(
    r'^([0-9A-Za-z]{2,3})\.(\d+)\.(\d+)(?:\([0-9.]+\))?#(\d+)=(\S+)$')
_SURFACE_RE = re.compile(r'^(.*?)\s*\(([^)]*)\)\s*$')


def _norm_strongs(ext: str) -> str:
    """'G0011' / 'G2424G' / 'H7225G' → the app's plain form ('G11' /
    'G2424' / 'H7225'): letter + digits with leading zeros stripped,
    disambiguation suffix dropped — the key shape lookup_strong expects."""
    m = re.match(r'^([GH])0*(\d+)', ext.strip(), re.IGNORECASE)
    if not m:
        return ext.strip().upper()
    return m.group(1).upper() + m.group(2)


def in_na_stream(wtype: str) -> bool:
    """Whether a Greek type marker (NKO, N(k)O, K, ko…) places the word
    in the NA-equivalent text — any N, parenthesised or not, any case."""
    return 'n' in wtype.lower()


def parse_line(line: str) -> Optional[ParsedRow]:
    """One TAGNT (Greek) data line → ParsedRow, or None for headers/
    comments/blank lines. Pure — unit-tested against real rows."""
    # The shipped files carry decomposed (NFD) Greek; the app's SWORD texts
    # and lexicon keys are NFC — normalize once at parse time.
    fields = unicodedata.normalize('NFC', line.rstrip('\n')).split('\t')
    if len(fields) < 6:
        return None
    m = _REF_RE.match(fields[0].strip())
    if not m:
        return None
    code, chapter, verse, pos, wtype = m.groups()
    book = _GREEK_BOOKS.get(code)
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
        editions=fields[5].strip(), rendered=in_na_stream(wtype),
    )


_BRACED_RE = re.compile(r'\{(H\d+[A-Za-z]?)\}')
_HSTRONG_RE = re.compile(r'H\d+')
# Lemma breakdown, braced content word: {H7225G=רֵאשִׁית=: beginning»first:…}
_HEB_LEMMA_RE = re.compile(r'\{H\d+[A-Za-z]?=([^=]*)=([^}]*)\}')


def parse_line_hebrew(line: str) -> Optional[ParsedRow]:
    """One TAHOT (Hebrew) data line → ParsedRow, or None. Pure.

    Surface forms are morpheme-slashed (בְּ/רֵאשִׁ֖ית) with
    backslash-escaped trailing punctuation and parashah markers
    (צֽוּר\\׃\\ \\פ) — joined and cleaned here. The strongs chain marks
    the content word in braces ({H7225G}); H9xxx affix pseudo-numbers
    (prefixes/suffixes) are kept in strongs_ext but excluded from the
    clickable strongs_all (no lexicon carries them)."""
    fields = unicodedata.normalize('NFC', line.rstrip('\n')).split('\t')
    if len(fields) < 12:
        return None
    m = _REF_RE.match(fields[0].strip())
    if not m:
        return None
    code, chapter, verse, pos, wtype = m.groups()
    book = _HEBREW_BOOKS.get(code)
    if book is None:
        return None

    surface = fields[1].replace('\\', '').replace('/', '').strip()
    # Parashah layout markers (petuchah פ / setumah ס) trail the last word
    # of a paragraph after a space — layout, not text; sof pasuq is kept.
    surface = re.sub(r'\s+[פס]$', '', surface).strip()

    translit = fields[2].replace('/', '').strip()
    gloss = ' '.join(fields[3].replace('/', ' ').split())

    chain = fields[4].strip()
    braced = _BRACED_RE.findall(chain)
    strongs = _norm_strongs(braced[0]) if braced else ''
    # Clickable numbers: real Strong's only — H9xxx are STEPBible affix
    # codes with no lexicon entries.
    all_norm = []
    for tok in _HSTRONG_RE.findall(chain):
        n = _norm_strongs(tok)
        if int(n[1:]) < 9000 and n not in all_norm:
            all_norm.append(n)
    strongs_all = ' '.join(all_norm)
    if not strongs and strongs_all:
        strongs = strongs_all.split(' ')[0]

    morph = fields[5].strip()

    lemma, lemma_gloss = '', ''
    lm = _HEB_LEMMA_RE.search(fields[11])
    if lm:
        lemma = lm.group(1).strip()
        # Gloss tail like ': beginning»first:1_beginning' — take the text
        # before the »-alternatives, minus the leading punctuation.
        lemma_gloss = lm.group(2).split('»')[0].lstrip(':').strip()

    return ParsedRow(
        book=book, chapter=int(chapter), verse=int(verse), pos=int(pos),
        wtype=wtype, surface=surface, translit=translit, gloss=gloss,
        strongs=strongs, strongs_all=strongs_all, strongs_ext=chain,
        morph=morph, lemma=lemma, lemma_gloss=lemma_gloss,
        editions='', rendered=not wtype.startswith('X'),
    )


# ── Module registry ───────────────────────────────────────────────────────────

def _tagnt(name: str) -> str:
    return (_BASE + 'TAGNT%20' + name +
            '%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20'
            'STEPBible.org%20CC-BY.txt')


def _tahot(name: str) -> str:
    return (_BASE + 'TAHOT%20' + name +
            '%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20'
            'STEPBible.org%20CC%20BY.txt')


_MODULES: dict[str, dict] = {
    GREEK: {
        'db': os.path.join(paths.open_data_dir(), 'interlinear_greek.sqlite'),
        'urls': [_tagnt('Mat-Jhn'), _tagnt('Act-Rev')],
        'parse': parse_line,
        'min_words': 100_000,
    },
    HEBREW: {
        'db': os.path.join(paths.open_data_dir(), 'interlinear_hebrew.sqlite'),
        'urls': [_tahot('Gen-Deu'), _tahot('Jos-Est'),
                 _tahot('Job-Sng'), _tahot('Isa-Mal')],
        'parse': parse_line_hebrew,
        'min_words': 250_000,
    },
}

# Tests monkeypatch these per-module DB paths (never env vars — paths
# bind at import).
_DB_FILES = {name: spec['db'] for name, spec in _MODULES.items()}


def is_interlinear_module(name: str) -> bool:
    return name in _MODULES


def is_hebrew(name: str) -> bool:
    return name == HEBREW


def is_installed(name: str) -> bool:
    return name in _MODULES and os.path.exists(_DB_FILES[name])


def module_names() -> list[str]:
    return [n for n in _MODULES if is_installed(n)]


def display_name(name: str) -> str:
    if name == HEBREW:
        return _('Interlinear — Hebrew OT')
    return _('Interlinear — Greek NT')


# ── Installation ──────────────────────────────────────────────────────────────

def download_and_build(
        name: str,
        on_progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Stream a module's source files and build its SQLite database.
    Raises on failure. on_progress(bytes_done, bytes_total) follows the
    open_data contract (total may be 0); rows are parsed as bytes stream
    in, so the byte scale tracks the whole build except the final
    count-check/commit. Atomic: builds to a .tmp sibling, os.replace."""
    spec = _MODULES[name]
    db_file = _DB_FILES[name]
    parse = spec['parse']
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    tmp = db_file + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    try:
        conn.execute('''
            CREATE TABLE words (
                book TEXT NOT NULL, chapter INTEGER NOT NULL,
                verse INTEGER NOT NULL, pos INTEGER NOT NULL,
                wtype TEXT NOT NULL, in_stream INTEGER NOT NULL,
                surface TEXT NOT NULL, translit TEXT NOT NULL,
                gloss TEXT NOT NULL,
                strongs TEXT NOT NULL, strongs_all TEXT NOT NULL,
                strongs_ext TEXT NOT NULL, morph TEXT NOT NULL,
                lemma TEXT NOT NULL, lemma_gloss TEXT NOT NULL,
                editions TEXT NOT NULL,
                PRIMARY KEY (book, chapter, verse, pos)
            ) WITHOUT ROWID''')

        done_bytes = 0
        # The HEAD pre-flight only serves progress scaling — skip the
        # round trips when nobody is listening.
        totals = _content_lengths(spec['urls']) if on_progress else []
        total_bytes = sum(totals) if totals and all(totals) else 0
        batch: list[tuple[object, ...]] = []

        def push(row: ParsedRow) -> None:
            batch.append((
                row.book, row.chapter, row.verse, row.pos,
                row.wtype, int(row.rendered),
                row.surface, row.translit, row.gloss,
                row.strongs, row.strongs_all, row.strongs_ext,
                row.morph, row.lemma, row.lemma_gloss, row.editions))

        for url in spec['urls']:
            # Ask for gzip: the raw text compresses ~5× (the Hebrew set is
            # 70 MB plain, ~14 MB on the wire), and GitHub's CDN honours it.
            # urllib doesn't negotiate encodings itself, so decompress the
            # stream by hand; file:// test URLs have no Content-Encoding
            # and pass through untouched.
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
                    done_bytes += len(chunk)   # wire bytes — matches totals
                    buf += decomp.decompress(chunk) if decomp else chunk
                    *lines, buf = buf.split(b'\n')
                    for raw in lines:
                        row = parse(raw.decode('utf-8', 'replace'))
                        if row is not None:
                            push(row)
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
                row = parse(buf.decode('utf-8', 'replace'))
                if row is not None:
                    push(row)
        if batch:
            conn.executemany(
                'INSERT OR REPLACE INTO words VALUES '
                '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', batch)
        # Guard against a truncated or wrong-file download building an
        # empty shell that is_installed() would then report as ready.
        count = conn.execute('SELECT COUNT(*) FROM words').fetchone()[0]
        if count < spec['min_words']:
            raise ValueError(
                f'{name} parse produced only {count} words; refusing install')
        conn.commit()
    except BaseException:
        conn.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    conn.close()
    os.replace(tmp, db_file)


def _content_lengths(urls: list[str]) -> list[int]:
    """Content-Length of each source file (0 where the server omits it) —
    lets a multi-file download report one continuous progress scale.
    Asks for gzip like the download itself, so the totals match the wire
    bytes the progress counter accumulates."""
    sizes = []
    for url in urls:
        try:
            req = urllib.request.Request(
                url, method='HEAD', headers={'Accept-Encoding': 'gzip'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                sizes.append(int(resp.headers.get('Content-Length') or 0))
        except Exception:
            sizes.append(0)
    return sizes


def remove(name: str) -> None:
    if name in _DB_FILES and os.path.exists(_DB_FILES[name]):
        os.remove(_DB_FILES[name])


# ── Queries ───────────────────────────────────────────────────────────────────
# A fresh connection per query: chapter loads are rare (navigation-paced)
# and callers run on pane worker threads, so per-call connections avoid
# cross-thread sharing entirely.

_migrated = False


def _migrate(conn: sqlite3.Connection, name: str) -> None:
    """One-shot cleanup of Greek databases built before parse_line
    stripped TAGNT's ¶/¬ layout markers and before the column rename —
    saves an existing install the 29 MB re-download. Gated on cheap
    probes so clean databases pay a LIMIT-1 scan per process."""
    global _migrated
    if _migrated or name != GREEK:
        return
    _migrated = True
    cols = [r[1] for r in conn.execute('PRAGMA table_info(words)')]
    if 'in_na' in cols:
        conn.execute('ALTER TABLE words RENAME COLUMN in_na TO in_stream')
        conn.commit()
    dirty = conn.execute(
        "SELECT 1 FROM words WHERE surface LIKE '%¶%' "
        "OR surface LIKE '%¬%' LIMIT 1").fetchone()
    if dirty:
        conn.execute(
            "UPDATE words SET surface = TRIM(REPLACE(REPLACE("
            "surface, '¶', ''), '¬', '')) "
            "WHERE surface LIKE '%¶%' OR surface LIKE '%¬%'")
        conn.commit()


def load_chapter(name: str, book: str, chapter: int) -> list[Word]:
    """The rendered-stream words of one chapter, in canonical order."""
    if not is_installed(name):
        return []
    conn = sqlite3.connect(_DB_FILES[name])
    try:
        _migrate(conn, name)
        rows = conn.execute(
            'SELECT verse, pos, surface, translit, gloss, strongs, '
            'strongs_all, morph, lemma, lemma_gloss FROM words '
            'WHERE book=? AND chapter=? AND in_stream=1 '
            'ORDER BY verse, pos',
            (book, chapter)).fetchall()
    finally:
        conn.close()
    return [Word(*r) for r in rows]


def chapter_count(name: str, book: str) -> int:
    """Highest chapter present for a book (0 when absent) — keeps the
    interlinear's navigation self-contained rather than assuming the
    KJV shape."""
    if not is_installed(name):
        return 0
    conn = sqlite3.connect(_DB_FILES[name])
    try:
        row = conn.execute(
            'SELECT MAX(chapter) FROM words WHERE book=?', (book,)).fetchone()
    finally:
        conn.close()
    return int(row[0] or 0)
