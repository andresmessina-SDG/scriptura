#!/usr/bin/env python3
"""Build Scriptura's Bible Imagery pack (dev-only; not shipped in the Flatpak).

The pack is a directory holding `imagery.sqlite` (the catalog the app's
`imagery_bridge` reads) plus an `images/` tree, optionally tarred to
`imagery.tar.gz` for hosting on a Codeberg release.

Verse ranges use the same encoding as the catena pack — a location is
`chapter * 1_000_000 + verse`, and a row covers `[loc_start, loc_end]` — so a
plate spanning several verses (or chapters) surfaces on every verse it covers.

Each illustration *source* is driven by a small mapping table that pairs the
source's ordered plates with scripture references. The first source wired up is
Schnorr von Carolsfeld's *Die Bibel in Bildern* (1860): its Wikimedia Commons
files are named `Schnorr von Carolsfeld Bibel in Bildern 1860 NNN.png`, numbered
in Bible order, and each plate carries a chapter:verse reference in the source —
so the mapping in `tools/schnorr_plates.toml` is a transcription, not a guess.

Usage:
    build_imagery_pack.py OUTDIR [--source schnorr] [--limit N]
                          [--width 1500] [--no-fetch] [--tar]
"""

import argparse
import os
import sqlite3
import tarfile
import tomllib
import urllib.parse
import urllib.request
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_UA = ('ScripturaImageryBuilder/1.0 '
       '(https://codeberg.org/andresmessina/scriptura)')

_SCHEMA = """
CREATE TABLE imagery (
    id INTEGER PRIMARY KEY, kind TEXT, tradition TEXT, title TEXT,
    caption TEXT, book TEXT, loc_start INTEGER, loc_end INTEGER,
    passage_label TEXT, file_path TEXT, file_size INTEGER, source TEXT,
    source_url TEXT, license TEXT, attribution TEXT, artist TEXT,
    year INTEGER, iconclass TEXT);
CREATE INDEX idx_imagery_verse ON imagery (book, loc_start);
CREATE TABLE places (
    place_id TEXT PRIMARY KEY, ancient_name TEXT, modern_name TEXT,
    latitude REAL, longitude REAL, confidence INTEGER, photo_path TEXT);
CREATE TABLE place_verses (place_id TEXT, book TEXT, chapter INTEGER, verse INTEGER);
CREATE INDEX idx_place_verses ON place_verses (book, chapter, verse);
CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def encode(chapter, verse):
    return chapter * 1_000_000 + verse


def commons_filepath_url(filename, width):
    """Special:FilePath returns a width-scaled copy of a Commons file."""
    quoted = urllib.parse.quote(filename)
    return (f'https://commons.wikimedia.org/wiki/Special:FilePath/{quoted}'
            f'?width={width}')


def fetch(url, dest):
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with open(dest, 'wb') as f:
        f.write(data)
    return len(data)


# ── Schnorr von Carolsfeld, "Die Bibel in Bildern" (1860) ───────────────────

def ingest_schnorr(conn, images_dir, width, limit, fetch_images):
    with open(os.path.join(_HERE, 'schnorr_plates.toml'), 'rb') as f:
        plates = tomllib.load(f)['plate']
    if limit:
        plates = plates[:limit]
    rows = 0
    for p in plates:
        num = p['n']
        commons = f'Schnorr von Carolsfeld Bibel in Bildern 1860 {num:03d}.png'
        rel = f'images/schnorr_{num:03d}.png'
        size = None
        if fetch_images:
            dest = os.path.join(images_dir, f'schnorr_{num:03d}.png')
            try:
                size = fetch(commons_filepath_url(commons, width), dest)
            except Exception as e:  # noqa: BLE001 — report and skip one plate
                print(f'  ! plate {num:03d} fetch failed: {e}')
                continue
        v = p['verse']
        v_end = p.get('verse_end', v)
        ch_end = p.get('chapter_end', p['chapter'])
        conn.execute(
            'INSERT INTO imagery (kind, tradition, title, caption, book, '
            'loc_start, loc_end, passage_label, file_path, file_size, source, '
            'source_url, license, attribution, artist, year, iconclass) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('illustration', 'engraving', p['title'], None, p['book'],
             encode(p['chapter'], v), encode(ch_end, v_end),
             p.get('passage_label'), rel, size, 'schnorr_1860',
             'https://commons.wikimedia.org/wiki/Die_Bibel_in_Bildern', 'PD',
             'Julius Schnorr von Carolsfeld, Die Bibel in Bildern (1860)',
             'Julius Schnorr von Carolsfeld', 1860, None))
        rows += 1
        print(f'  + plate {num:03d}  {p["book"]} {p["chapter"]}:{v}  {p["title"]}')
    return rows


_SOURCES = {'schnorr': ingest_schnorr}


def main():
    ap = argparse.ArgumentParser(description='Build the Bible Imagery pack.')
    ap.add_argument('outdir', help='staging directory for imagery.sqlite + images/')
    ap.add_argument('--source', action='append', choices=sorted(_SOURCES),
                    help='source(s) to ingest (default: all)')
    ap.add_argument('--limit', type=int, default=0,
                    help='cap plates per source (for quick test builds)')
    ap.add_argument('--width', type=int, default=1500, help='thumbnail width px')
    ap.add_argument('--no-fetch', action='store_true',
                    help='write catalog rows only; skip downloading images')
    ap.add_argument('--tar', action='store_true',
                    help='also write <outdir>/../imagery.tar.gz')
    args = ap.parse_args()

    images_dir = os.path.join(args.outdir, 'images')
    os.makedirs(images_dir, exist_ok=True)
    db_path = os.path.join(args.outdir, 'imagery.sqlite')
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    sources = args.source or sorted(_SOURCES)
    total = 0
    for name in sources:
        print(f'== {name} ==')
        total += _SOURCES[name](conn, images_dir, args.width, args.limit,
                                not args.no_fetch)

    conn.executemany('INSERT INTO pack_meta VALUES (?,?)', [
        ('schema', '1'),
        ('built', date.today().isoformat()),
        ('image_count', str(total)),
        ('sources', ','.join(sources)),
    ])
    conn.commit()
    conn.close()
    print(f'wrote {db_path} ({total} images)')

    if args.tar:
        tar_path = os.path.join(os.path.dirname(os.path.abspath(args.outdir)),
                                'imagery.tar.gz')
        with tarfile.open(tar_path, 'w:gz') as tar:
            tar.add(db_path, arcname='imagery.sqlite')
            tar.add(images_dir, arcname='images')
        print(f'wrote {tar_path}')


if __name__ == '__main__':
    main()
