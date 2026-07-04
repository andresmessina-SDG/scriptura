"""
ebible_bridge.py — eBible.org translation download, USFM parsing, SQLite storage.
Exposes the same load_chapter() shape as sword_bridge for transparent pane integration.
"""

import logging
import re
import csv
import io
import os
import sqlite3
import threading
import zipfile

import paths
import search_query

_log = logging.getLogger('scriptura.ebible')

# Database and catalog now live under XDG dirs. paths.* migrates the
# legacy in-tree copies on first call.
_DB  = paths.ebible_db_path()
_CAT = paths.ebible_catalog_path()

CATALOG_URL = 'https://ebible.org/Scriptures/translations.csv'
_USFM_URL   = 'https://ebible.org/Scriptures/{id}_usfm.zip'

PREFIX = 'eBible: '

# ── USFM book-code → canonical name ──────────────────────────────────────────

_BOOK = {
    'GEN':'Genesis','EXO':'Exodus','LEV':'Leviticus','NUM':'Numbers',
    'DEU':'Deuteronomy','JOS':'Joshua','JDG':'Judges','RUT':'Ruth',
    '1SA':'1 Samuel','2SA':'2 Samuel','1KI':'1 Kings','2KI':'2 Kings',
    '1CH':'1 Chronicles','2CH':'2 Chronicles','EZR':'Ezra','NEH':'Nehemiah',
    'EST':'Esther','JOB':'Job','PSA':'Psalms','PRO':'Proverbs',
    'ECC':'Ecclesiastes','SNG':'Song of Solomon','ISA':'Isaiah',
    'JER':'Jeremiah','LAM':'Lamentations','EZK':'Ezekiel','DAN':'Daniel',
    'HOS':'Hosea','JOL':'Joel','AMO':'Amos','OBA':'Obadiah',
    'JON':'Jonah','MIC':'Micah','NAM':'Nahum','HAB':'Habakkuk',
    'ZEP':'Zephaniah','HAG':'Haggai','ZEC':'Zechariah','MAL':'Malachi',
    'MAT':'Matthew','MRK':'Mark','LUK':'Luke','JHN':'John',
    'ACT':'Acts','ROM':'Romans','1CO':'1 Corinthians','2CO':'2 Corinthians',
    'GAL':'Galatians','EPH':'Ephesians','PHP':'Philippians','COL':'Colossians',
    '1TH':'1 Thessalonians','2TH':'2 Thessalonians','1TI':'1 Timothy',
    '2TI':'2 Timothy','TIT':'Titus','PHM':'Philemon','HEB':'Hebrews',
    'JAS':'James','1PE':'1 Peter','2PE':'2 Peter','1JN':'1 John',
    '2JN':'2 John','3JN':'3 John','JUD':'Jude','REV':'Revelation',
    # alternate codes found in some eBible distributions
    'JOE':'Joel','EZE':'Ezekiel','NAH':'Nahum','ZEF':'Zephaniah',
    'SONG':'Song of Solomon',
}

# ── SQLite helpers ────────────────────────────────────────────────────────────

_conn_local = threading.local()


def _db():
    """Return a thread-local SQLite connection. Schema initialisation
    runs once per thread on first use; subsequent calls return the cached
    connection.

    Previously this opened a fresh connection on every call (with
    PRAGMA + CREATE TABLE IF NOT EXISTS + COMMIT each time), which became
    significant overhead on hot paths like load_chapter and the module
    picker's per-keystroke language probe. Threads are bounded (the main
    GLib loop + a handful of short-lived fetch threads), and SQLite
    connections aren't safe to share across threads without external
    locking — so thread-local storage is the simplest correct shape."""
    conn = getattr(_conn_local, 'conn', None)
    if conn is not None:
        return conn
    conn = sqlite3.connect(_DB)
    # WAL mode lets concurrent readers continue while a writer (translation
    # download) is in progress; default rollback mode would raise
    # "database is locked" on read during a long INSERT batch.
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.Error:
        pass
    conn.execute('''CREATE TABLE IF NOT EXISTS verses (
        translation TEXT, book TEXT, chapter INTEGER, verse INTEGER, text TEXT,
        PRIMARY KEY (translation, book, chapter, verse))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS translations (
        id TEXT PRIMARY KEY, title TEXT, language TEXT, lang_code TEXT,
        copyright TEXT, license TEXT)''')
    # Translator footnotes (\f…\f* in the USFM source). n is the 1-based
    # per-verse index matching the <note swordFootnote="n"/> anchor left in
    # the verse text — the same anchor shape SWORD's footnote filters emit,
    # so the pane's marker pipeline serves both backends. Translations
    # imported before this table existed have no rows here (and no anchors
    # in their text); a re-download re-imports with notes.
    conn.execute('''CREATE TABLE IF NOT EXISTS notes (
        translation TEXT, book TEXT, chapter INTEGER, verse INTEGER,
        n INTEGER, type TEXT, body TEXT,
        PRIMARY KEY (translation, book, chapter, verse, n))''')
    # Full-text search index over verse text (shared FTS5 grammar with the
    # SWORD backend — see search_query). External-content: the index points
    # at `verses` instead of duplicating the text. unicode61 tokenization
    # gives word-boundary matching (no more substring over-match) and folds
    # case + diacritics, so searches match across Greek/Hebrew pointing.
    conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS verses_fts USING fts5(
        text, content='verses', content_rowid='rowid', tokenize='unicode61')''')
    # Triggers keep the index in lock-step with `verses`, so every
    # download/removal path maintains it automatically.
    conn.execute('''CREATE TRIGGER IF NOT EXISTS verses_ai AFTER INSERT ON verses BEGIN
        INSERT INTO verses_fts(rowid, text) VALUES (new.rowid, new.text);
    END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS verses_ad AFTER DELETE ON verses BEGIN
        INSERT INTO verses_fts(verses_fts, rowid, text) VALUES('delete', old.rowid, old.text);
    END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS verses_au AFTER UPDATE ON verses BEGIN
        INSERT INTO verses_fts(verses_fts, rowid, text) VALUES('delete', old.rowid, old.text);
        INSERT INTO verses_fts(rowid, text) VALUES (new.rowid, new.text);
    END''')
    # Schema version stamp. v1 = base tables; v2 = FTS index added; v3 =
    # notes table (created above — no data migration, old imports just have
    # no rows). When the layout changes, bump this and add the migration
    # steps in an `if ver < N` block so existing user DBs upgrade in place.
    ver = conn.execute('PRAGMA user_version').fetchone()[0]
    if ver < 1:
        conn.execute('PRAGMA user_version = 1')
    if ver < 2:
        # Backfill the FTS index for verses that existed before it was added.
        conn.execute("INSERT INTO verses_fts(verses_fts) VALUES('rebuild')")
        conn.execute('PRAGMA user_version = 2')
    if ver < 3:
        conn.execute('PRAGMA user_version = 3')
    conn.commit()
    _conn_local.conn = conn
    return conn

# ── Public API ────────────────────────────────────────────────────────────────

def is_ebible_module(name):
    return isinstance(name, str) and name.startswith(PREFIX)

def _tid(module_name):
    """Module key → DB translation id. The key embeds the id directly
    (PREFIX + id), so this just strips the prefix."""
    return module_name[len(PREFIX):]

def installed_translations():
    """Returns [(id, title, language, lang_code, copyright, license)]."""
    try:
        conn = _db()
        rows = conn.execute(
            'SELECT id, title, language, lang_code, copyright, license '
            'FROM translations ORDER BY title').fetchall()
        return rows
    except Exception:
        return []

def module_names():
    """Module keys for the pane dropdown: PREFIX + the stable
    translationId (the DB primary key), not the display title — two
    catalog rows can share a title, but ids are unique. The friendly
    title is resolved for display by display_name()."""
    return [f'{PREFIX}{r[0]}' for r in installed_translations()]


def display_name(module_name):
    """Friendly title for an eBible module key (PREFIX + id). When another
    installed translation shares the title, the id is appended so the two
    aren't indistinguishable in the dropdown. Falls back to the id if the
    translation isn't in the DB (e.g. read error)."""
    tid = module_name[len(PREFIX):]
    try:
        conn = _db()
        row = conn.execute(
            'SELECT title FROM translations WHERE id=?', (tid,)).fetchone()
        if not row or not row[0]:
            return tid
        title = row[0]
        shared = conn.execute(
            'SELECT COUNT(*) FROM translations WHERE title=?', (title,)
        ).fetchone()[0]
        return f'{title} ({tid})' if shared > 1 else title
    except Exception:
        return tid


def module_language(module_name):
    """Return the 2-letter language code for an eBible module, or ''."""
    try:
        tid = module_name[len(PREFIX):]
        conn = _db()
        row = conn.execute(
            'SELECT lang_code FROM translations WHERE id=?', (tid,)
        ).fetchone()
        return (row[0] or '').strip().lower() if row else ''
    except Exception:
        return ''


def module_info(module_name):
    """Same shape as sword_bridge.module_info(): description / version /
    copyright / license / about / language / type — eBible only has a
    subset, the rest come back as ''."""
    info = {'name': module_name, 'description': '', 'version': '',
            'copyright': '', 'license': '', 'about': '', 'language': '',
            'type': 'eBible translation'}
    try:
        tid = module_name[len(PREFIX):]
        conn = _db()
        row = conn.execute(
            'SELECT title, language, lang_code, copyright, license '
            'FROM translations WHERE id=?', (tid,)
        ).fetchone()
        if row:
            info['description'] = row[1] or row[0] or ''
            info['language']    = (row[2] or '').strip().lower()
            info['copyright']   = row[3] or ''
            info['license']     = row[4] or ''
    except Exception:
        pass
    return info

def installed_ids():
    try:
        conn = _db()
        rows = conn.execute('SELECT id FROM translations').fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()

def load_chapter(module_name, book, chapter):
    """Returns [(verse_num, html_text)] — same shape as sword_bridge.load_chapter()."""
    tid = _tid(module_name)
    try:
        conn = _db()
        rows = conn.execute(
            'SELECT verse, text FROM verses '
            'WHERE translation=? AND book=? AND chapter=? ORDER BY verse',
            (tid, book, chapter)).fetchall()
        return list(rows)
    except Exception:
        return []

def chapter_footnotes(module_name, book, chapter):
    """{verse: [(marker_index, type, body_html), …]} — same shape as
    sword_bridge.chapter_footnotes. marker_index is the string matching
    the swordFootnote="N" anchor in the stored verse text."""
    tid = _tid(module_name)
    try:
        conn = _db()
        rows = conn.execute(
            'SELECT verse, n, type, body FROM notes '
            'WHERE translation=? AND book=? AND chapter=? ORDER BY verse, n',
            (tid, book, chapter)).fetchall()
    except Exception:
        return {}
    out = {}
    for v, n, t, body in rows:
        out.setdefault(v, []).append((str(n), t, body))
    return out


def module_has_footnotes(module_name):
    """True if any stored note exists for this translation. Translations
    imported before notes were kept return False until re-downloaded."""
    try:
        conn = _db()
        return conn.execute(
            'SELECT 1 FROM notes WHERE translation=? LIMIT 1',
            (_tid(module_name),)).fetchone() is not None
    except Exception:
        return False


def search_module(module_name, query, case_sensitive=False, **_kwargs):
    """Full-text verse search via the FTS5 index, using the shared query
    grammar (phrase / AND / OR / exclude / prefix — see search_query).

    FTS5 (unicode61) tokenization is word-boundary and case/diacritic
    insensitive, so 'art' no longer matches 'heart' and a query matches across
    Greek/Hebrew pointing. case_sensitive=True post-filters the matched text
    for the original-case terms. Returns [(book, ch, v, text)], with a
    truncation sentinel row when the result set is capped."""
    match = search_query.build_match(query)
    if match is None:
        return []
    tid = _tid(module_name)
    try:
        conn = _db()
        rows = conn.execute(
            'SELECT v.book, v.chapter, v.verse, v.text FROM verses v '
            'WHERE v.translation=? AND v.rowid IN '
            '(SELECT rowid FROM verses_fts WHERE verses_fts MATCH ?) '
            'ORDER BY v.rowid', (tid, match)).fetchall()
        result = list(rows)
        if case_sensitive:
            terms = search_query.plain_terms(query)
            result = [r for r in result
                      if all(w in (r[3] or '') for w in terms)]
        if len(result) > 5000:
            result = result[:5000]
            result.append(('', 0, 0,
                'Showing first 5000 results — try a more specific search.'))
        return result
    except Exception:
        _log.exception('search failed')
        return []

def catalog_entries():
    """Return cached eBible catalog as list of dicts, or []."""
    if not os.path.exists(_CAT):
        return []
    try:
        with open(_CAT, newline='', encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

# These are synchronous — always call from a background thread.

def download_catalog_sync():
    """Download and cache the eBible catalog CSV. Raises on failure."""
    # Lazy: pulls in http/ssl/email (~40 ms) — only needed for downloads.
    import urllib.request
    req = urllib.request.Request(CATALOG_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    # Write through a tmp + os.replace so a killed download can't leave a
    # truncated catalog that catalog_entries() would then parse partially.
    tmp = _CAT + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, _CAT)

def download_translation_sync(tid, entry, on_status=None):
    """Download, parse, and store one translation. Raises on failure."""
    import urllib.request
    if on_status:
        on_status('download')
    url = _USFM_URL.format(id=tid)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()

    if on_status:
        on_status('parse')
    verses = {}
    notes = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if re.search(r'\.(usfm|sfm)$', name, re.IGNORECASE):
                with z.open(name) as f:
                    content = f.read().decode('utf-8', errors='replace')
                file_verses, file_notes = _parse_usfm(content)
                verses.update(file_verses)
                notes.update(file_notes)

    if on_status:
        on_status('save')
    title     = (entry.get('shortTitle') or entry.get('translationId') or tid).strip()
    language  = (entry.get('languageName') or '').strip()
    lang_code = (entry.get('languageCode') or '').strip()
    copyright_= (entry.get('copyrightStatement') or '').strip()
    license_  = (entry.get('licenseType') or '').strip()

    conn = _db()
    conn.execute('DELETE FROM verses      WHERE translation=?', (tid,))
    conn.execute('DELETE FROM notes       WHERE translation=?', (tid,))
    conn.execute('DELETE FROM translations WHERE id=?',         (tid,))
    conn.executemany(
        'INSERT OR REPLACE INTO verses VALUES (?,?,?,?,?)',
        [(tid, b, c, v, t) for (b, c, v), t in verses.items() if b])
    conn.executemany(
        'INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?)',
        [(tid, b, c, v, n, t, body)
         for (b, c, v), lst in notes.items() if b
         for n, t, body in lst])
    conn.execute('INSERT OR REPLACE INTO translations VALUES (?,?,?,?,?,?)',
                 (tid, title, language, lang_code, copyright_, license_))
    conn.commit()

def remove_translation(tid):
    conn = _db()
    conn.execute('DELETE FROM verses      WHERE translation=?', (tid,))
    conn.execute('DELETE FROM notes       WHERE translation=?', (tid,))
    conn.execute('DELETE FROM translations WHERE id=?',         (tid,))
    conn.commit()


def remove_module(module_name):
    """Remove an eBible translation by its pane module key (PREFIX + id)."""
    remove_translation(_tid(module_name))

# ── USFM parser ───────────────────────────────────────────────────────────────

# Block-level notes (span multiple lines). \f footnotes are captured into
# note bodies (see _parse_usfm); the rest are stripped: \x cross-references
# are a separate system out of scope here, \fe endnotes and \esb sidebars
# have no reading-pane surface.
_RE_FN  = re.compile(r'\\f\b(.*?)\\f\*',  re.DOTALL)
_RE_XR  = re.compile(r'\\x\b.*?\\x\*',   re.DOTALL)
_RE_EN  = re.compile(r'\\fe\b.*?\\fe\*',  re.DOTALL)
_RE_SB  = re.compile(r'\\esb\b.*?\\esbe\b', re.DOTALL)
# Placeholder a captured footnote leaves in the text until verse assembly
# renumbers it per verse and swaps in the <note swordFootnote="n"/> anchor.
_RE_NOTE_PH = re.compile(r'\[\[EBN_(\d+)\]\]')

# Line-start marker patterns
_RE_BOOK    = re.compile(r'^\\id\s+([A-Z1-9]{3})',   re.IGNORECASE)
_RE_CHAPTER = re.compile(r'^\\c\s+(\d+)')
_RE_VERSE   = re.compile(r'^\\v\s+(\d+)(?:-\d+)?\s*(.*)')
_RE_HEADING = re.compile(r'^\\(?:s\d?|ms\d?|d)\s+(.*)')
_RE_POETRY  = re.compile(r'^\\(q[cmr]?\d?|b)\s*(.*)')
_RE_PARA    = re.compile(r'^\\(?:p|m|pi\d?|mi|nb|ph\d?|pr|li\d?|pc|po)\s*(.*)')
# Markers to skip entirely (metadata, titles, references)
_RE_SKIP    = re.compile(
    r'^\\(?:ide|rem|sts|h|toc\d?|cl|mt\d?|mte\d?|imt\d?|imte?\d?'
    r'|periph|r|mr|sr|rq|va|vp|ca|cd|cp)\b')


def _apply_char(text):
    """
    Convert USFM inline character markers to SWORD-compatible HTML understood
    by pane._html_to_markup():
      \\wj...\\wj*   → <q who="Jesus">...</q>      (red letter)
      \\add...\\add* → <transChange type="added">   (italic translator addition)
      \\em/\\it      → <i>...</i>
      \\title        → <title>...</title>            (bold heading)
      everything else → plain text (markers stripped)
    """
    # Nested character markers carry a '+' right after the backslash
    # (\+wj ... \+wj*). Drop the '+' so the rules below — which match the
    # plain \wj form — handle nested markers too instead of leaking raw tags.
    text = re.sub(r'\\\+', r'\\', text)
    # Alternate / published verse-number spans
    text = re.sub(r'\\(?:va|vp|ca)\s.*?\\(?:va|vp|ca)\*', '', text, flags=re.DOTALL)
    # Words of Jesus → red letter
    text = re.sub(r'\\wj\s(.*?)\\wj\*',
                  r'<q who="Jesus">\1</q>', text, flags=re.DOTALL)
    # Translator additions → italic
    text = re.sub(r'\\add\s(.*?)\\add\*',
                  r'<transChange type="added">\1</transChange>', text, flags=re.DOTALL)
    # Emphasis / italic / bold-italic
    text = re.sub(r'\\(?:em|it|bdit)\s(.*?)\\(?:em|it|bdit)\*',
                  r'<i>\1</i>', text, flags=re.DOTALL)
    # Bold — strip markers, keep text (pane doesn't style inline bold, text survives)
    text = re.sub(r'\\bd\s(.*?)\\bd\*', r'\1', text, flags=re.DOTALL)
    # Divine name, small caps, keyword, ordinal, superscript — keep text
    text = re.sub(r'\\(?:nd|sc|k|ord|sup|fk|fl|fr|ft|fq|fqa)\s(.*?)\\(?:nd|sc|k|ord|sup|fk|fl|fr|ft|fq|fqa)\*',
                  r'\1', text, flags=re.DOTALL)
    # Strong's word attribute: \w word|strong="G1234" ...\w*  or  \w word\w*
    text = re.sub(r'\\w\s(.*?)(?:\|[^\\]*)\\w\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\w\s(.*?)\\w\*',             r'\1', text, flags=re.DOTALL)
    # Quoted book / proper name markup
    text = re.sub(r'\\(?:pn|png|addpn|qt)\s(.*?)\\(?:pn|png|addpn|qt)\*',
                  r'\1', text, flags=re.DOTALL)
    # Remove any remaining opening character markers (\marker<space>)
    text = re.sub(r'\\[a-zA-Z]+\d*\+?\s', '', text)
    # Remove any remaining closing markers (\marker*)
    text = re.sub(r'\\[a-zA-Z]+\d*\+?\*', '', text)
    # Clean whitespace: collapse runs but preserve intentional newlines (poetry)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'[ \t]*\n[ \t]*', '\n', text)
    return text.strip()


def _note_body(inner):
    """One \\f…\\f* note's internals → body HTML in the dialect
    _apply_char emits (pane._html_to_markup renders it in the peek):
    \\fr origin reference → bold, quoted/keyword text (\\fq \\fqa \\fk
    \\fl) → italic, \\ft and untagged text → plain. Footnote content
    markers are usually unpaired — each runs to the next marker — so
    this walks marker/text tokens instead of matching pairs."""
    inner = re.sub(r'\\\+', r'\\', inner)          # nested \+marker forms
    inner = re.sub(r'^\s*[^\s\\]\s+', '', inner)   # the caller ('+' = auto)
    out = []
    style = 'ft'
    for tok in re.split(r'(\\[a-z]+\d*\*?)', inner):
        if tok.startswith('\\'):
            style = 'ft' if tok.endswith('*') else tok[1:]
            continue
        text = tok.strip()
        if not text:
            continue
        if style == 'fr':
            out.append(f'<hi type="bold">{text}</hi>')
        elif style in ('fq', 'fqa', 'fk', 'fl'):
            out.append(f'<i>{text}</i>')
        else:
            out.append(text)
    return ' '.join(out)


def _parse_usfm(content):
    """
    Parse one USFM file into a pair:
      {(book, chapter, verse): html_text},
      {(book, chapter, verse): [(n, type, body_html), …]}   (footnotes)

    Output html_text is compatible with pane._html_to_markup():
      • Red-letter words in <q who="Jesus">…</q>
      • Translator additions in <transChange type="added">…</transChange>
      • Section / psalm headings in <title>…</title> prepended to first verse
      • Poetry lines indented with em-spaces and separated by newlines
      • Footnotes become <note swordFootnote="n"/> anchors (bodies in the
        second dict); cross-references and metadata fully stripped
    """
    # Strip the note types we don't keep, then capture \f footnotes into
    # per-file bodies, leaving a placeholder that verse assembly (flush)
    # renumbers per verse. Strips run first so a footnote inside a
    # stripped sidebar vanishes with it.
    for pat in (_RE_XR, _RE_EN, _RE_SB):
        content = pat.sub('', content)
    bodies = []

    def _stash(m):
        body = _note_body(m.group(1))
        if not body:
            return ''
        bodies.append(body)
        return f'[[EBN_{len(bodies) - 1}]]'

    content = _RE_FN.sub(_stash, content)

    verses  = {}
    notes   = {}
    book    = None
    chapter = None
    vnum    = None
    parts   = []          # text segments for the current verse
    heading = None        # pending section/psalm heading
    pre     = []          # text after \c but before the first \v

    def flush():
        if book and chapter is not None and vnum is not None and parts:
            raw = ' '.join(parts)
            raw = re.sub(r'[ \t]+',       ' ',  raw)   # collapse inline spaces
            raw = re.sub(r'[ \t]*\n[ \t]*', '\n', raw) # clean around newlines
            raw = _apply_char(raw)
            vnotes = []

            def _anchor(m):
                vnotes.append((len(vnotes) + 1, '', bodies[int(m.group(1))]))
                return f'<note swordFootnote="{len(vnotes)}"/>'

            raw = _RE_NOTE_PH.sub(_anchor, raw)
            if raw:
                verses[(book, chapter, vnum)] = raw
                if vnotes:
                    notes[(book, chapter, vnum)] = vnotes
        parts.clear()

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        # ── Book identifier ───────────────────────────────────────────────────
        m = _RE_BOOK.match(line)
        if m:
            flush()
            book    = _BOOK.get(m.group(1).upper())
            chapter = vnum = None
            heading = None
            pre.clear()
            continue

        # ── Chapter ───────────────────────────────────────────────────────────
        m = _RE_CHAPTER.match(line)
        if m:
            flush()
            vnum    = None
            chapter = int(m.group(1))
            pre.clear()
            continue

        # ── Section / psalm / descriptive heading ─────────────────────────────
        m = _RE_HEADING.match(line)
        if m:
            txt = m.group(1).strip()
            # Strip inline markers from heading text; a footnote in a
            # heading has no verse to attach to, so it stays dropped.
            txt = re.sub(r'\\[a-zA-Z]+\d*\+?\s?', '', txt).strip()
            txt = _RE_NOTE_PH.sub('', txt).strip()
            if txt:
                heading = txt
            continue

        # ── Metadata / reference lines to skip entirely ───────────────────────
        if _RE_SKIP.match(line):
            continue

        # ── Verse ─────────────────────────────────────────────────────────────
        m = _RE_VERSE.match(line)
        if m:
            flush()
            vnum = int(m.group(1))
            rest = m.group(2).strip()
            if heading:
                parts.append(f'<title>{heading}</title>')
                heading = None
            if pre:
                parts.extend(pre)
                pre.clear()
            if rest:
                parts.append(rest)
            continue

        # ── Poetry lines ──────────────────────────────────────────────────────
        m = _RE_POETRY.match(line)
        if m and (vnum is not None or chapter is not None):
            target = parts if vnum is not None else pre
            marker = m.group(1)
            rest   = m.group(2).strip()
            if marker == 'b':                       # stanza break
                target.append('\n')
            elif rest:
                level  = int(marker[-1]) if marker[-1:].isdigit() else 1
                indent = ' ' * level           # em-space per indent level
                target.append(f'\n{indent}{rest}')
            continue

        # ── Paragraph markers (may carry text after them) ─────────────────────
        m = _RE_PARA.match(line)
        if m:
            rest = m.group(1).strip()
            if rest:
                if vnum is not None:
                    parts.append(rest)
                elif chapter is not None:
                    pre.append(rest)
            continue

        # ── Unknown marker: try to salvage any text content ───────────────────
        if line.startswith('\\'):
            rest = re.sub(r'^\\[a-zA-Z]+\d*\s*', '', line).strip()
            if rest:
                if vnum is not None:
                    parts.append(rest)
                elif chapter is not None:
                    pre.append(rest)
            continue

        # ── Plain continuation text ───────────────────────────────────────────
        if vnum is not None:
            parts.append(line)
        elif chapter is not None:
            pre.append(line)

    flush()
    return verses, notes
