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
import json
import os
import re
import sqlite3
import tarfile
import tomllib
import zipfile
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
    latitude REAL, longitude REAL, confidence INTEGER, photo_path TEXT,
    photo_caption TEXT, photo_credit TEXT, photo_license TEXT,
    photo_source_url TEXT);
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


# Protestant 66 in canonical order — index = OpenBible `sort` book number (BB).
# Names must match the app's book names exactly (so place_verses keys line up).
CANON66 = [
    'Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy', 'Joshua',
    'Judges', 'Ruth', '1 Samuel', '2 Samuel', '1 Kings', '2 Kings',
    '1 Chronicles', '2 Chronicles', 'Ezra', 'Nehemiah', 'Esther', 'Job',
    'Psalms', 'Proverbs', 'Ecclesiastes', 'Song of Solomon', 'Isaiah',
    'Jeremiah', 'Lamentations', 'Ezekiel', 'Daniel', 'Hosea', 'Joel', 'Amos',
    'Obadiah', 'Jonah', 'Micah', 'Nahum', 'Habakkuk', 'Zephaniah', 'Haggai',
    'Zechariah', 'Malachi', 'Matthew', 'Mark', 'Luke', 'John', 'Acts',
    'Romans', '1 Corinthians', '2 Corinthians', 'Galatians', 'Ephesians',
    'Philippians', 'Colossians', '1 Thessalonians', '2 Thessalonians',
    '1 Timothy', '2 Timothy', 'Titus', 'Philemon', 'Hebrews', 'James',
    '1 Peter', '2 Peter', '1 John', '2 John', '3 John', 'Jude', 'Revelation',
]


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


# ── OpenBible.info geocoding — places named in each verse ───────────────────

# Pinned to the default branch; switch to a pinned commit SHA for fully
# reproducible builds. CC BY 4.0.
_OPENBIBLE_ANCIENT = ('https://raw.githubusercontent.com/openbibleinfo/'
                      'Bible-Geocoding-Data/main/data/ancient.jsonl')
# Photo metadata for the places: a curated Commons image per modern site
# (real photographs, plus Copernicus Sentinel satellite tiles as fallback).
_OPENBIBLE_IMAGE = ('https://raw.githubusercontent.com/openbibleinfo/'
                    'Bible-Geocoding-Data/main/data/image.jsonl')
# 512x512 thumbnail for every location (real photographs and Copernicus
# Sentinel satellite tiles alike). 184 MB, fetched once at build time; only
# the per-place tiles we extract ship. This is OpenBible's purpose-built
# per-location image set — one clean download, no Commons rate-limiting.
_OPENBIBLE_THUMBS_ZIP = 'https://a.openbible.info/geo/thumbnails.zip'

# image.jsonl license codes -> human-readable, for the attribution line.
_LICENSE_LABEL = {
    'PD': 'Public domain', 'CC-Zero': 'CC0', 'sentinel': 'Copernicus Sentinel',
    'attribution': 'Attribution', 'GFDL': 'GFDL', 'GPL': 'GPL', 'FAL': 'FAL',
    'OGL-1.0': 'OGL 1.0',
}


def _license_label(code):
    if code in _LICENSE_LABEL:
        return _LICENSE_LABEL[code]
    # 'CC-BY-SA-4.0' -> 'CC BY-SA 4.0'; 'CC-BY-3.0' -> 'CC BY 3.0'.
    m = re.match(r'CC-BY(-SA)?-([\d.]+)', code)
    if m:
        return f'CC BY{m.group(1) or ""} {m.group(2)}'
    return code


def _strip_tags(text):
    """Drop OpenBible's inline <modern>/<ancient> markup from a caption."""
    return re.sub(r'<[^>]+>', '', text or '').strip()


def _pick_photo(massoc, img_by_modern):
    """Best image across a place's modern associations: real photographs
    (highest-confidence modern first, 'color' preferred) before satellite."""
    mids = sorted(massoc, key=lambda k: massoc[k].get('score', 0) or 0,
                  reverse=True)
    real, sat = [], []
    for mid in mids:
        for im in img_by_modern.get(mid, []):
            (sat if im['license'] == 'sentinel' else real).append((mid, im))
    pool = real or sat
    if not pool:
        return None
    pool.sort(key=lambda mi: 0 if mi[1].get('color') == 'color' else 1)
    return pool[0]   # (modern_id, image_record)


def ingest_openbible(conn, images_dir, width, limit, fetch_images):
    """Populate places + place_verses from OpenBible's ancient.jsonl, then
    attach a Commons site photo per place from image.jsonl.

    Each place's verse references carry a `sort` key encoded BBCCCVVV, where BB
    is the canonical Protestant book number — so we map straight to CANON66
    without parsing OSIS abbreviations. Confidence = the best modern
    association's score (OpenBible's 0-1000) normalised to 0-100.

    Photos: image.jsonl keys images by *modern* place id, so we pick the best
    image across a place's modern associations (real photographs preferred over
    Copernicus Sentinel satellite tiles) and fetch a width-scaled copy. The
    photo is CC/PD — credit + license are stored and shown on the place card.
    """
    req = urllib.request.Request(_OPENBIBLE_ANCIENT, headers={'User-Agent': _UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        lines = resp.read().decode('utf-8').splitlines()
    if limit:
        lines = lines[:limit]

    to_photo = []   # (place_id, modern_associations) for the photo phase
    places = links = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        pid = obj['id']
        ancient = obj.get('friendly_id') or pid
        modern = score = lat = lon = None
        massoc = obj.get('modern_associations') or {}
        if massoc:
            best = max(massoc.values(), key=lambda m: m.get('score', 0) or 0)
            modern = best.get('name')
            s = best.get('score')
            if s is not None:
                score = max(0, min(100, round(s / 10)))   # 0-1000 -> 0-100
            to_photo.append((pid, massoc))
        for r in obj.get('resolutions') or []:
            ll = r.get('lonlat')
            if ll:
                try:
                    lo, la = ll.split(',')[:2]
                    lon, lat = float(lo), float(la)
                except ValueError:
                    pass
                break
        conn.execute('INSERT OR REPLACE INTO places '
                     'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (pid, ancient, modern, lat, lon, score,
                      None, None, None, None, None))
        places += 1
        seen = set()
        for v in obj.get('verses') or []:
            srt = v.get('sort')
            if not srt or len(srt) != 8:
                continue
            try:
                bb, ccc, vvv = int(srt[:2]), int(srt[2:5]), int(srt[5:8])
            except ValueError:
                continue
            if not 1 <= bb <= 66:
                continue
            key = (bb, ccc, vvv)
            if key in seen:
                continue
            seen.add(key)
            conn.execute('INSERT INTO place_verses VALUES (?,?,?,?)',
                         (pid, CANON66[bb - 1], ccc, vvv))
            links += 1
    print(f'  + {places} places, {links} place-verse links')

    if fetch_images:
        _attach_place_photos(conn, images_dir, to_photo)
    return 0   # adds places, not imagery-table rows


def _attach_place_photos(conn, images_dir, to_photo):
    """Attach one 512px site thumbnail per place from OpenBible's
    thumbnails.zip (downloaded once) and UPDATE its row. The zip carries a
    thumbnail for every location — real photographs and Copernicus Sentinel
    satellite tiles alike — so a single download covers every place with no
    Commons rate-limiting. _pick_photo still prefers a real photograph over a
    satellite tile; a place keeps its name-only card if it has no thumbnail."""
    req = urllib.request.Request(_OPENBIBLE_IMAGE, headers={'User-Agent': _UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        img_lines = resp.read().decode('utf-8').splitlines()
    img_by_modern = {}
    for line in img_lines:
        if not line.strip():
            continue
        im = json.loads(line)
        for mid in (im.get('thumbnails') or {}):
            img_by_modern.setdefault(mid, []).append(im)

    # The zip lives in outdir (sibling of images/), so it is never swept into
    # the shipped tar — only the per-place tiles we extract are.
    zip_path = os.path.join(os.path.dirname(images_dir), '_thumbnails.zip')
    if not os.path.exists(zip_path):
        print('    fetching OpenBible thumbnails.zip (184 MB)…')
        fetch(_OPENBIBLE_THUMBS_ZIP, zip_path)
    thumbs = zipfile.ZipFile(zip_path)
    members = set(thumbs.namelist())

    got = sat = miss = 0
    total = len(to_photo)
    for i, (pid, massoc) in enumerate(to_photo, 1):
        pick = _pick_photo(massoc, img_by_modern)
        if not pick:
            miss += 1
            continue
        mid, im = pick
        member = (im.get('thumbnails') or {}).get(mid, {}).get('file')
        if not member or member not in members:
            miss += 1
            continue
        rel = f'images/place_{pid}.jpg'
        with thumbs.open(member) as src, \
                open(os.path.join(images_dir, f'place_{pid}.jpg'), 'wb') as out:
            out.write(src.read())
        caption = _strip_tags((im.get('descriptions') or {}).get(mid, ''))
        conn.execute(
            'UPDATE places SET photo_path=?, photo_caption=?, photo_credit=?, '
            'photo_license=?, photo_source_url=? WHERE place_id=?',
            (rel, caption or None, im.get('credit') or im.get('author'),
             _license_label(im['license']), im.get('url'), pid))
        if im['license'] == 'sentinel':
            sat += 1
        else:
            got += 1
        if i % 200 == 0:
            conn.commit()
            print(f'    …{i}/{total} photos')
    thumbs.close()
    conn.commit()
    print(f'  + photos: {got} real, {sat} satellite, {miss} none')


# ── Hurlbut's Bible Atlas (1882) — antique maps from Project Gutenberg ──────

_GUTENBERG_IMG = 'https://www.gutenberg.org/files/41140/41140-h/images/{}'


def _fetch_gutenberg_map(img, dest):
    """Fetch a Hurlbut map image, preferring the hi-res `-big` variant."""
    for suffix in ('-big.jpg', '.jpg'):
        try:
            return fetch(_GUTENBERG_IMG.format(img + suffix), dest)
        except Exception:
            continue
    raise RuntimeError(f'no image for {img}')


def ingest_hurlbut(conn, images_dir, width, limit, fetch_images):
    """Insert Hurlbut maps from tools/hurlbut_maps.toml. A map covering several
    books gets one imagery row per range (same image file), so it surfaces on
    each book it depicts."""
    with open(os.path.join(_HERE, 'hurlbut_maps.toml'), 'rb') as f:
        maps = tomllib.load(f)['map']
    if limit:
        maps = maps[:limit]
    rows = 0
    for m in maps:
        img = m['img']
        rel = f'images/hurlbut_{img}.jpg'
        size = None
        if fetch_images:
            try:
                size = _fetch_gutenberg_map(
                    img, os.path.join(images_dir, f'hurlbut_{img}.jpg'))
            except Exception as e:  # noqa: BLE001
                print(f'  ! map {img} fetch failed: {e}')
                continue
        for rng in m['ranges']:
            ce = rng.get('chapter_end', rng['chapter'])
            ve = rng.get('verse_end', rng['verse'])
            conn.execute(
                'INSERT INTO imagery (kind, tradition, title, caption, book, '
                'loc_start, loc_end, passage_label, file_path, file_size, '
                'source, source_url, license, attribution, artist, year, '
                'iconclass) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('map', 'cartography', m['title'], None, rng['book'],
                 encode(rng['chapter'], rng['verse']), encode(ce, ve),
                 m.get('passage_label'), rel, size, 'hurlbut_1882',
                 'https://www.gutenberg.org/ebooks/41140', 'PD',
                 'Jesse L. Hurlbut, Bible Atlas (1882)', None, 1882, None))
            rows += 1
        print(f'  + map {img}  {m["title"]}  ({len(m["ranges"])} range(s))')
    return rows


# ── Modern vector maps (Wikimedia SVGs) ─────────────────────────────────────

def ingest_modern(conn, images_dir, width, limit, fetch_images):
    """Insert modern SVG maps from tools/modern_maps.toml. Fetches the raw SVG
    (Special:FilePath without a width param returns the original vector file,
    which renders crisply via the rsvg loader). tradition='modern_map'."""
    with open(os.path.join(_HERE, 'modern_maps.toml'), 'rb') as f:
        maps = tomllib.load(f)['map']
    if limit:
        maps = maps[:limit]
    rows = 0
    for m in maps:
        slug = m['slug']
        rel = f'images/modern_{slug}.svg'
        size = None
        if fetch_images:
            url = ('https://commons.wikimedia.org/wiki/Special:FilePath/'
                   + urllib.parse.quote(m['file']))
            try:
                size = fetch(url, os.path.join(images_dir, f'modern_{slug}.svg'))
            except Exception as e:  # noqa: BLE001
                print(f'  ! modern {slug} fetch failed: {e}')
                continue
        file_url = ('https://commons.wikimedia.org/wiki/File:'
                    + m['file'].replace(' ', '_'))
        for rng in m['ranges']:
            ce = rng.get('chapter_end', rng['chapter'])
            ve = rng.get('verse_end', rng['verse'])
            conn.execute(
                'INSERT INTO imagery (kind, tradition, title, caption, book, '
                'loc_start, loc_end, passage_label, file_path, file_size, '
                'source, source_url, license, attribution, artist, year, '
                'iconclass) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('map', 'modern_map', m['title'], None, rng['book'],
                 encode(rng['chapter'], rng['verse']), encode(ce, ve),
                 m.get('passage_label'), rel, size, 'wikimedia_svg', file_url,
                 m.get('license', 'PD'), m.get('attribution'), None, None, None))
            rows += 1
        print(f'  + modern {slug}  {m["title"]}')
    return rows


_SOURCES = {'schnorr': ingest_schnorr, 'openbible': ingest_openbible,
            'hurlbut': ingest_hurlbut, 'modern': ingest_modern}


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

    img_n = conn.execute('SELECT COUNT(*) FROM imagery').fetchone()[0]
    place_n = conn.execute('SELECT COUNT(*) FROM places').fetchone()[0]
    conn.executemany('INSERT INTO pack_meta VALUES (?,?)', [
        ('schema', '1'),
        ('built', date.today().isoformat()),
        ('image_count', str(img_n)),
        ('place_count', str(place_n)),
        ('sources', ','.join(sources)),
    ])
    conn.commit()
    conn.close()
    print(f'wrote {db_path} ({img_n} images, {place_n} places, {total} new this run)')

    if args.tar:
        tar_path = os.path.join(os.path.dirname(os.path.abspath(args.outdir)),
                                'imagery.tar.gz')
        with tarfile.open(tar_path, 'w:gz') as tar:
            tar.add(db_path, arcname='imagery.sqlite')
            tar.add(images_dir, arcname='images')
        print(f'wrote {tar_path}')


if __name__ == '__main__':
    main()
