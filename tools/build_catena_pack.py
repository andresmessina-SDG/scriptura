#!/usr/bin/env python3
"""Build Scriptura's Historical Commentaries pack from a checkout of
HistoricalChristianFaith/Commentaries-Database.

Each top-level folder in that repo is a "father" (a person such as
Augustine, or a source such as the book of Acts quoting an OT verse) with
a `metadata.toml` giving its `default_year` and `wiki` link. Inside are
verse-keyed files named `<Book> <chapter>_<verse>[-<verse>|-<ch>_<verse>].toml`,
each holding one or more `[[commentary]]` entries.

We keep only public-domain authors — those whose year is before the U.S.
public-domain cutoff (default 1928) — because the upstream LICENSE's
public-domain dedication explicitly does NOT cover the modern fair-use
excerpts, and we redistribute this as a bundled pack. Apocryphal books
the app can't navigate to are dropped. The output is a compact SQLite
file with one denormalised `quotes` table plus a `pack_meta` table.

Usage:
    build_catena_pack.py <commentaries-db-dir> <output.db> [--cutoff YEAR]
"""

import argparse
import os
import re
import sqlite3
import subprocess
import tomllib
from datetime import timezone, datetime

# Canonical book names the app navigates by (Protestant 66).
CANON = {
    'Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy', 'Joshua',
    'Judges', 'Ruth', '1 Samuel', '2 Samuel', '1 Kings', '2 Kings',
    '1 Chronicles', '2 Chronicles', 'Ezra', 'Nehemiah', 'Esther', 'Job',
    'Psalms', 'Proverbs', 'Ecclesiastes', 'Song of Solomon', 'Isaiah',
    'Jeremiah', 'Lamentations', 'Ezekiel', 'Daniel', 'Hosea', 'Joel',
    'Amos', 'Obadiah', 'Jonah', 'Micah', 'Nahum', 'Habakkuk', 'Zephaniah',
    'Haggai', 'Zechariah', 'Malachi', 'Matthew', 'Mark', 'Luke', 'John',
    'Acts', 'Romans', '1 Corinthians', '2 Corinthians', 'Galatians',
    'Ephesians', 'Philippians', 'Colossians', '1 Thessalonians',
    '2 Thessalonians', '1 Timothy', '2 Timothy', 'Titus', 'Philemon',
    'Hebrews', 'James', '1 Peter', '2 Peter', '1 John', '2 John', '3 John',
    'Jude', 'Revelation',
}

# HCF book spellings that differ from the app's canonical names.
ALIASES = {
    'Psalm': 'Psalms',
    '1 Pet': '1 Peter',
    '2 Pet': '2 Peter',
}

UNKNOWN_YEAR = 9999  # upstream sentinel for "date unknown"

# The father_category taxonomy the upstream metadata now carries, in the order
# the reader lays the "traditions" out (Scripture-adjacent, then the father
# traditions roughly chronologically, then councils/liturgies/pseudonymous).
# A father whose metadata omits the field falls back to UNCATEGORIZED.
CATEGORY_ORDER = [
    'Second Temple Judaism',
    'Canonical Scriptures',
    'Apocrypha, Pseudepigrapha & Early Documents',
    'Early Fathers (Pre-Nicaea)',
    'Eastern & Byzantine Theology',
    'Syriac & Oriental Theology',
    'Western & Medieval Theology',
    'Reformation & Modern',
    'Councils & Canons',
    'Liturgies & Hymns',
    'Pseudonymous Works',
]
UNCATEGORIZED = 'Uncategorized'

# Curated attribution corrections applied at build time (upstream not yet
# fixed). The 52 "Theodore Stratelates" entries are exegetical fragments on
# Isaiah and John; the martyr-general of that name wrote nothing — they are
# the fragments of Theodore of Heraclea (d. c. 355), the Eastern exegete.
AUTHOR_CORRECTIONS = {
    'Theodore Stratelates': {
        'author': 'Theodore of Heraclea',
        'year': 355,
        'category': 'Eastern & Byzantine Theology',
    },
}

# Words kept lowercase when title-casing an ALL-CAPS source title.
_TITLE_SMALL_WORDS = {'a', 'an', 'and', 'at', 'by', 'for', 'from', 'in',
                      'of', 'on', 'or', 'the', 'to', 'with'}

# A location is `ch_v` followed by any number of `-[ch_]v` segments: a single
# verse, a range, a cross-chapter range, or a father's multi-verse block a
# curator wrote as a list ("20_23-24-26"). `_SEG_RE` reads one segment.
_FN_RE = re.compile(r'^(?P<book>.+?) (?P<loc>\d+_\d+(?:-(?:\d+_)?\d+)*)\.toml$')
_SEG_RE = re.compile(r'^(?:(?P<ch>\d+)_)?(?P<v>\d+)$')


def tame_title(title):
    """An ALL-CAPS source title ("FRAGMENTS ON JOHN 12") to title case; a title
    carrying any lowercase passes through untouched. Small words stay lower,
    roman numerals and locator tokens (XII.3, 215:2) keep their shape. Formerly
    catena_reader._display_title — now baked into the pack."""
    if not title or any(c.islower() for c in title):
        return title
    words = []
    for i, w in enumerate(title.split()):
        lw = w.lower()
        if i and lw in _TITLE_SMALL_WORDS:
            words.append(lw)
        elif re.fullmatch('[IVXLCDM]+', w):
            words.append(w)
        elif any(c.isdigit() for c in w) and not w.isdigit():
            words.append(w)
        else:
            words.append(w.capitalize())
    return ' '.join(words)


def clean_source_title(title, author):
    """Display form of a source title: ALL-CAPS tamed, and a leading repeat of
    the author's name dropped ("Irenaeus Against Heresies Book 3" under an
    Irenaeus eyebrow -> "Against Heresies Book 3"). Formerly the reader's
    _display_title + _source_title, now applied at build time."""
    title = tame_title((title or '').strip())
    if author and title.lower().startswith(author.lower()):
        rest = title[len(author):].lstrip(' ,:;-–—')
        if rest:
            title = rest[0].upper() + rest[1:]
    return title or None


def clean_suffix(suffix):
    """Normalize an author suffix: strip surrounding whitespace and wrap a bare
    verse locator (" 10:23-33") in parentheses; suffixes that already carry
    their own parenthesis or prose pass through. Formerly the reader's
    _author_parts wrapping, now baked in."""
    suffix = (suffix or '').strip()
    if suffix and '(' not in suffix:
        suffix = f'({suffix})'
    return suffix or None


def encode(chapter, verse):
    """Verse key as the upstream encodes it: chapter*1e6 + verse."""
    return chapter * 1_000_000 + verse


def parse_location(loc):
    """'3_16' / '3_16-18' / '7_53-8_11' / '20_23-24-26' -> (start, end) encoded.
    The last shape is a father's multi-verse block a curator wrote as a list
    (verses 23, 24 ... 26); file it as one continuous span from the first verse
    to the last, ignoring the intermediate markers. A bare trailing verse
    inherits the start chapter; a `ch_v` segment carries its own chapter."""
    parts = loc.split('-')
    first = _SEG_RE.match(parts[0])
    last = _SEG_RE.match(parts[-1])
    if first is None or last is None or first['ch'] is None:
        return None
    start_ch = int(first['ch'])
    end_ch = int(last['ch']) if last['ch'] is not None else start_ch
    return encode(start_ch, int(first['v'])), encode(end_ch, int(last['v']))


def era_for(year):
    """Bucket a year (AD) into a study-friendly church-history era."""
    if year is None or year == UNKNOWN_YEAR:
        return 'Unknown'
    if year < 325:
        return 'Ante-Nicene'
    if year < 600:
        return 'Nicene & Post-Nicene'
    if year < 1454:
        return 'Medieval'
    if year < 1700:
        return 'Reformation'
    return 'Modern'


def read_metadata(folder):
    """Return (default_year:int|None, wiki:str, category:str, condemned:bool)
    from a father's metadata.toml."""
    path = os.path.join(folder, 'metadata.toml')
    if not os.path.isfile(path):
        return None, '', UNCATEGORIZED, False
    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None, '', UNCATEGORIZED, False
    year = data.get('default_year')
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None
    category = str(data.get('father_category') or '').strip() or UNCATEGORIZED
    condemned = bool(data.get('condemned_by_council'))
    return year, str(data.get('wiki', '') or ''), category, condemned


def git_commit(repo_dir):
    try:
        return subprocess.run(
            ['git', '-C', repo_dir, 'rev-parse', 'HEAD'],
            capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ''


def build(src_dir, out_path, cutoff):
    conn = sqlite3.connect(out_path)
    conn.executescript("""
        DROP TABLE IF EXISTS quotes;
        DROP TABLE IF EXISTS pack_meta;
        CREATE TABLE quotes (
            book          TEXT NOT NULL,
            loc_start     INTEGER NOT NULL,
            loc_end       INTEGER NOT NULL,
            author        TEXT NOT NULL,
            author_suffix TEXT,
            year          INTEGER,
            era           TEXT,
            category      TEXT,
            condemned     INTEGER,
            source_title  TEXT,
            source_url    TEXT,
            wiki_url      TEXT,
            text          TEXT NOT NULL
        );
        CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT);
    """)

    stats = {
        'authors_kept': 0, 'authors_dropped': [], 'authors_no_year': 0,
        'quotes': 0, 'files_skipped_apocrypha': 0, 'files_bad_name': [],
        'unmatched_books': set(), 'era_counts': {}, 'category_counts': {},
        'dupes_dropped': 0, 'corrected': [],
    }
    rows = []
    seen = set()  # (book, loc_start, loc_end, author, text) — drop exact dups

    for entry in sorted(os.scandir(src_dir), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        default_year, wiki, category, condemned = read_metadata(entry.path)
        author = entry.name
        correction = AUTHOR_CORRECTIONS.get(entry.name)
        if correction:
            author = correction.get('author', author)
            default_year = correction.get('year', default_year)
            category = correction.get('category', category)
            stats['corrected'].append((entry.name, author))
        if default_year is None:
            stats['authors_no_year'] += 1
        # Public-domain gate: drop authors with a known year at/after cutoff.
        if default_year is not None and default_year != UNKNOWN_YEAR \
                and default_year >= cutoff:
            stats['authors_dropped'].append((entry.name, default_year))
            continue
        stats['authors_kept'] += 1

        for fn in os.listdir(entry.path):
            if fn == 'metadata.toml' or not fn.endswith('.toml'):
                continue
            fm = _FN_RE.match(fn)
            if not fm:
                stats['files_bad_name'].append(f'{entry.name}/{fn}')
                continue
            book = ALIASES.get(fm['book'], fm['book'])
            if book not in CANON:
                stats['files_skipped_apocrypha'] += 1
                stats['unmatched_books'].add(fm['book'])
                continue
            loc = parse_location(fm['loc'])
            if loc is None:
                stats['files_bad_name'].append(f'{entry.name}/{fn}')
                continue
            loc_start, loc_end = loc

            try:
                with open(os.path.join(entry.path, fn), 'rb') as f:
                    doc = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError):
                stats['files_bad_name'].append(f'{entry.name}/{fn}')
                continue

            for c in doc.get('commentary', []):
                text = (c.get('quote') or '').strip()
                if not text:
                    continue
                dkey = (book, loc_start, loc_end, author, text)
                if dkey in seen:          # exact duplicate — same voice, place
                    stats['dupes_dropped'] += 1
                    continue
                seen.add(dkey)
                year = c.get('time', default_year)
                try:
                    year = int(year) if year is not None else None
                except (TypeError, ValueError):
                    year = default_year
                if correction and 'year' in correction:
                    year = correction['year']   # the corrected figure's date
                era = era_for(year)
                stats['era_counts'][era] = stats['era_counts'].get(era, 0) + 1
                stats['category_counts'][category] = \
                    stats['category_counts'].get(category, 0) + 1
                rows.append((
                    book, loc_start, loc_end, author,
                    clean_suffix(c.get('append_to_author_name')),
                    year, era, category, int(condemned),
                    clean_source_title(c.get('source_title'), author),
                    c.get('source_url') or None,
                    wiki or None, text,
                ))
                stats['quotes'] += 1

    conn.executemany(
        'INSERT INTO quotes (book, loc_start, loc_end, author, author_suffix, '
        'year, era, category, condemned, source_title, source_url, wiki_url, '
        'text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    conn.execute(
        'CREATE INDEX idx_quotes_book_loc ON quotes (book, loc_start, loc_end)')

    meta = {
        'schema': '2',
        'built': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'source': 'HistoricalChristianFaith/Commentaries-Database',
        'source_commit': git_commit(src_dir),
        'pd_cutoff': str(cutoff),
        'quote_count': str(stats['quotes']),
        'grouping': 'category',
    }
    conn.executemany('INSERT INTO pack_meta (key, value) VALUES (?,?)',
                     list(meta.items()))
    conn.commit()
    conn.execute('VACUUM')
    conn.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('src_dir', help='Commentaries-Database checkout')
    ap.add_argument('out_path', help='output .db path')
    ap.add_argument('--cutoff', type=int, default=1928,
                    help='drop authors whose year is >= this (default 1928)')
    args = ap.parse_args(argv)

    if not os.path.isdir(args.src_dir):
        ap.error(f'not a directory: {args.src_dir}')

    stats = build(args.src_dir, args.out_path, args.cutoff)

    size_mb = os.path.getsize(args.out_path) / (1 << 20)
    print(f'Built {args.out_path}  ({size_mb:.1f} MB)')
    print(f'  authors kept:    {stats["authors_kept"]}')
    print(f'  authors dropped: {len(stats["authors_dropped"])} '
          f'(year >= {args.cutoff})')
    for name, yr in sorted(stats['authors_dropped'], key=lambda x: x[1]):
        print(f'      {yr}  {name}')
    print(f'  authors w/o year: {stats["authors_no_year"]}')
    print(f'  quotes:          {stats["quotes"]}')
    print(f'  exact dupes dropped: {stats["dupes_dropped"]}')
    for orig, fixed in stats['corrected']:
        print(f'  attribution fixed: {orig!r} -> {fixed!r}')
    print(f'  apocrypha files skipped: {stats["files_skipped_apocrypha"]} '
          f'({", ".join(sorted(stats["unmatched_books"]))})')
    if stats['files_bad_name']:
        print(f'  unparseable filenames: {len(stats["files_bad_name"])} '
              f'(e.g. {stats["files_bad_name"][:3]})')
    print('  per category:')
    for cat in CATEGORY_ORDER + [UNCATEGORIZED]:
        if cat in stats['category_counts']:
            print(f'      {stats["category_counts"][cat]:>7}  {cat}')


if __name__ == '__main__':
    main()
