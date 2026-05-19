import csv
import io
import os
import shutil
import zipfile

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

_BOOKS = [
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
_BOOK_IDX = {b: i + 1 for i, b in enumerate(_BOOKS)}


def _vid(book, chapter, verse):
    return f'{_BOOK_IDX[book]:02d}{chapter:03d}{verse:03d}'


def _parse_vid(vid):
    try:
        b = int(vid[:2]) - 1
        c = int(vid[2:5])
        v = int(vid[5:8])
        if 0 <= b < len(_BOOKS):
            return _BOOKS[b], c, v
    except (ValueError, IndexError):
        pass
    return None


# OpenBible files use OSIS-style references like "Gen.1.1" or
# "Exod.20.1-Exod.20.26", not the 8-digit numeric vids used internally.
# Kept local rather than imported from sword_bridge to avoid a circular import.
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
    '2John': '2 John', '3John': '3 John', 'Jude': 'Jude', 'Revelation': 'Revelation',
    'Rev': 'Revelation',
}


def _parse_osis_one(s):
    """Parse a single OSIS verse like 'Gen.1.1' → ('Genesis', 1, 1) or None."""
    parts = s.split('.')
    if len(parts) != 3:
        return None
    book = _OSIS_BOOKS.get(parts[0])
    if not book:
        return None
    try:
        return (book, int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _osis_to_vids(s):
    """Convert 'Gen.1.1' or 'Exod.20.1-Exod.20.26' to a list of vids.
    Cross-chapter ranges are clipped to the start verse (rare; OpenBible
    usually keeps ranges within a chapter). Cross-book ranges likewise."""
    s = s.strip()
    if '-' in s:
        a, b = s.split('-', 1)
        ta = _parse_osis_one(a)
        tb = _parse_osis_one(b)
        if not ta:
            return []
        if not tb or ta[0] != tb[0] or ta[1] != tb[1]:
            return [_vid(*ta)]
        return [_vid(ta[0], ta[1], v) for v in range(ta[2], tb[2] + 1)]
    t = _parse_osis_one(s)
    return [_vid(*t)] if t else []


def _osis_first_tuple(s):
    """First (book, chapter, verse) of an OSIS string (range or single)."""
    s = s.strip()
    if '-' in s:
        s = s.split('-', 1)[0]
    return _parse_osis_one(s)


# ── Cross-references ──────────────────────────────────────────────────────────

_xref = None


def _load_xref():
    global _xref
    if _xref is not None:
        return
    path = os.path.join(_DIR, 'cross_references.txt')
    if not os.path.exists(path):
        _xref = {}
        return
    data = {}
    with open(path, encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)
        for row in reader:
            if len(row) < 2:
                continue
            # Columns: From Verse (OSIS) | To Verse (OSIS, maybe a range) | Votes
            from_vids = _osis_to_vids(row[0])
            to_tuple  = _osis_first_tuple(row[1])
            if not from_vids or not to_tuple:
                continue
            for fv in from_vids:
                data.setdefault(fv, []).append(to_tuple)
    _xref = data


def get_cross_refs(book, chapter, verse):
    """[(book, chapter, verse, label), ...] or None if not downloaded."""
    _load_xref()
    if not _xref:
        return None
    refs = _xref.get(_vid(book, chapter, verse), [])
    return [(b, c, v, f'{b} {c}:{v}') for b, c, v in refs]


def has_cross_refs():
    return os.path.exists(os.path.join(_DIR, 'cross_references.txt'))


# ── Topics ────────────────────────────────────────────────────────────────────

_topics = None


def _load_topics():
    global _topics
    if _topics is not None:
        return
    path = os.path.join(_DIR, 'topic-scores.txt')
    if not os.path.exists(path):
        _topics = {}
        return
    raw = {}
    with open(path, encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)
        for row in reader:
            if len(row) < 3:
                continue
            # Columns: Topic | OSIS reference (often a range) | Quality Score
            topic = row[0].strip()
            osis  = row[1].strip()
            try:
                votes = int(row[2])
            except ValueError:
                votes = 0
            for vid in _osis_to_vids(osis):
                raw.setdefault(vid, []).append((votes, topic))
    _topics = {
        vid: [t for _, t in sorted(items, reverse=True)]
        for vid, items in raw.items()
    }


def get_topics(book, chapter, verse):
    """[topic, ...] sorted by relevance (top 10), or [] if not downloaded."""
    _load_topics()
    vid = _vid(book, chapter, verse)
    return (_topics or {}).get(vid, [])[:10]


def has_topics():
    return os.path.exists(os.path.join(_DIR, 'topic-scores.txt'))


# ── Dodson Greek Lexicon ──────────────────────────────────────────────────────

_dodson = None


def _norm_strongs(s):
    s = s.strip().upper()
    if len(s) < 2:
        return s
    return s[0] + (s[1:].lstrip('0') or '0')


def _load_dodson():
    global _dodson
    if _dodson is not None:
        return
    path = os.path.join(_DIR, 'dodson.csv')
    if not os.path.exists(path):
        _dodson = {}
        return
    data = {}
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            strongs = (row.get("Strong's") or row.get('strongs') or
                       row.get('Strongs') or '').strip()
            defn = (row.get('English Definition (longer)') or
                    row.get('English Definition (brief)') or
                    row.get('kjv_def') or row.get('definition') or '').strip()
            if strongs and defn:
                data[_norm_strongs(strongs)] = defn
    _dodson = data


def lookup_dodson(strong_num):
    """Dodson definition for a Greek Strong's number, or None."""
    _load_dodson()
    if not _dodson:
        return None
    return _dodson.get(_norm_strongs(strong_num))


def has_dodson():
    return os.path.exists(os.path.join(_DIR, 'dodson.csv'))


# ── Source registry + download ────────────────────────────────────────────────

_SOURCES = {
    'cross_references': {
        'label': 'OpenBible Cross-References',
        'description': '340,000 cross-references — 5× more than TSK',
        'url': 'https://a.openbible.info/data/cross-references.zip',
        'is_zip': True,
        'dest': 'cross_references.txt',
    },
    'topics': {
        'label': 'OpenBible Topics',
        'description': '700+ topical tags for every verse',
        'url': 'https://a.openbible.info/data/topic-scores.zip',
        'is_zip': True,
        'dest': 'topic-scores.txt',
    },
    'dodson': {
        'label': 'Dodson Greek Lexicon',
        'description': 'Readable NT Greek definitions keyed to Strong\'s numbers',
        'url': 'https://raw.githubusercontent.com/biblicalhumanities/Dodson-Greek-Lexicon/master/dodson.csv',
        'is_zip': False,
        'dest': 'dodson.csv',
    },
}


def get_sources():
    return [
        {**v, 'id': k,
         'installed': os.path.exists(os.path.join(_DIR, v['dest']))}
        for k, v in _SOURCES.items()
    ]


def invalidate(source_id):
    global _xref, _topics, _dodson
    if source_id == 'cross_references':
        _xref = None
    elif source_id == 'topics':
        _topics = None
    elif source_id == 'dodson':
        _dodson = None


def download_source(source_id, on_progress=None):
    """Download and install a data source. Raises on failure.

    `on_progress(bytes_done, total_bytes)` is invoked periodically while
    bytes are streaming in; `total_bytes` may be 0 if the server doesn't
    send a Content-Length header. The callback runs on whatever thread
    invoked download_source — callers wanting to update UI should marshal
    via GLib.idle_add."""
    import urllib.request
    src = _SOURCES[source_id]
    os.makedirs(_DIR, exist_ok=True)
    dest = os.path.join(_DIR, src['dest'])

    chunk_size = 64 * 1024

    def _stream(resp, sink):
        total = 0
        try:
            total = int(resp.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            total = 0
        done = 0
        while True:
            buf = resp.read(chunk_size)
            if not buf:
                break
            sink.write(buf)
            done += len(buf)
            if on_progress:
                try:
                    on_progress(done, total)
                except Exception:
                    pass

    if src['is_zip']:
        # ZIPs need to be fully buffered before extraction.
        buf = io.BytesIO()
        with urllib.request.urlopen(src['url'], timeout=60) as resp:
            _stream(resp, buf)
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            target = next(
                (n for n in names if os.path.basename(n).lower() == src['dest'].lower()),
                names[0]
            )
            with zf.open(target) as zf_in, open(dest, 'wb') as f_out:
                f_out.write(zf_in.read())
    else:
        # urlretrieve has no timeout — a hung server would freeze the app forever.
        # Use urlopen(timeout=) explicitly.
        with urllib.request.urlopen(src['url'], timeout=60) as resp, \
             open(dest, 'wb') as f_out:
            _stream(resp, f_out)

    invalidate(source_id)


def remove_source(source_id):
    path = os.path.join(_DIR, _SOURCES[source_id]['dest'])
    if os.path.exists(path):
        os.remove(path)
    invalidate(source_id)
