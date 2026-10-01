"""Check Scripture in Stone, and write the verse texts its plates show.

Run from the repository root:  python3 tools/stone/build_stone.py
                                python3 tools/stone/build_stone.py --refresh-licences

The gallery is curated by hand in data/archaeology/scripture_in_stone.toml.
This script checks what a machine can check, and exits non-zero when any
check fails:

  * every verse resolves in the KJV (the Apocrypha in the KJVA), and an
    entry's verses stand in canonical order;
  * every link of a rewritten entry (one with a `fact`) says what kind of
    link it is;
  * every photograph and detail is on disk, every place is on the map,
    every date can be placed on the timeline;
  * every quotation is word for word in its source (fetch_texts.py), each
    piece between ellipses in order;
  * what is in the page's own words stays short: a fact line, a note;
  * each photograph's licence, as Wikimedia Commons records it
    (licences.json; --refresh-licences asks Commons again), is the one its
    credit names, and none is NonCommercial or NoDerivatives.

It writes data/archaeology/verses.json: each verse's KJV text, for the plate.
"""
import json
import os
import re
import subprocess
import sys
import tomllib
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DATA = os.path.join(ROOT, 'data', 'archaeology')
TOML = os.path.join(DATA, 'scripture_in_stone.toml')
LICENCES = os.path.join(HERE, 'licences.json')
OUT = os.path.join(DATA, 'verses.json')
sys.path.insert(0, ROOT)

BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
         "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles",
         "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs", "Ecclesiastes",
         "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea",
         "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah",
         "Haggai", "Zechariah", "Malachi",
         # the KJV's Apocrypha, between the Testaments as it prints them
         "1 Esdras", "2 Esdras", "Tobit", "Judith", "Additions to Esther", "Wisdom",
         "Sirach", "Baruch", "Prayer of Azariah", "Susanna", "Bel and the Dragon",
         "Prayer of Manasseh", "1 Maccabees", "2 Maccabees",
         "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
         "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians",
         "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus",
         "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John", "3 John",
         "Jude", "Revelation"]
APOCRYPHA = set(BOOKS[BOOKS.index("1 Esdras"):BOOKS.index("Matthew")])
KINDS = {'person', 'place', 'event', 'words', 'custom'}
#: The map's plate (archaeology_bridge.map_path): lon 11–50°E, lat 24–43°N.
LON, LAT = (11, 50), (24, 43)
FACT_MAX, NOTE_MAX = 160, 120

errors, warns = [], []


def kjv(book, ch, v):
    mod = 'KJVA' if book in APOCRYPHA else 'KJV'
    out = subprocess.run(['diatheke', '-b', mod, '-f', 'plain', '-k', f'{book} {ch}:{v}'],
                         capture_output=True, text=True).stdout
    lines = [ln for ln in out.strip().split('\n') if ln.strip() and not ln.startswith(f'({mod}')]
    text = re.sub(r'\s+', ' ', ' '.join(re.sub(r'^[\w ]+ \d+:\d+:\s*', '', ln) for ln in lines)).strip()
    # an epistle's closing note in the KJV stands in its last verse, after the Amen
    return re.sub(r'(Amen\.) (?:Written|Unto|It was written|The (?:first|second)) .*$', r'\1', text)


# ── quotations (the same check as tools/creeds/build_creeds.py) ─────────────
def plain(t):
    t = unicodedata.normalize('NFC', t)
    t = t.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r' \d{1,3}(?= )', '', t)
    t = re.sub(r' ?— ?', '—', t)
    t = re.sub(r'(?<=[(\[]) ', '', t)
    t = re.sub(r' (?=[,;:.?!)\]\'"])', '', t)
    return t.casefold()


_SRC = {}
_UNCHECKED = set()


def source(name):
    if name not in _SRC:
        path = (os.path.join(ROOT, 'tools', 'creeds', 'src', 'oc.txt') if name == 'oc'
                else os.path.join(HERE, 'src', 'texts', name + '.txt'))
        _SRC[name] = plain(open(path, encoding='utf-8').read()) if os.path.exists(path) else None
    return _SRC[name]


def check_quote(q, where):
    body = source(q['source'])
    if body is None:
        _UNCHECKED.add(q['source'])
        return
    pieces = q.get('pieces') or re.split(r'…', q['text'])
    # A page set in two columns (a translation beside its original) runs
    # their lines together in the scan: each piece is then looked for
    # anywhere, not after the one before.
    in_order = not q.get('columns')
    at = 0
    for piece in pieces:
        piece = plain(piece).strip(' ,;')
        if not piece:
            continue
        i = body.find(piece, at if in_order else 0)
        if i < 0:
            errors.append(f"{where}: quotation not in {q['source']}: …{piece[:60]}…")
            return
        at = i + len(piece)
    for key in ('source', 'cite', 'text'):
        if not q.get(key):
            errors.append(f"{where}: a quotation without its {key}")


# ── licences ───────────────────────────────────────────────────────────────
def commons_title(url):
    m = re.search(r'/wiki/(File:[^?#]+)', url or '')
    return urllib.parse.unquote(m.group(1)).replace('_', ' ') if m else None


def refresh_licences(images):
    """{image: {"licence": ..., "artist": ...}} as Commons records them now."""
    found = {}
    titles = {img: commons_title(url) for img, url in images.items()}
    want = [t for t in titles.values() if t]
    for i in range(0, len(want), 40):
        batch = '|'.join(want[i:i + 40])
        out = subprocess.run(
            ['curl', '-sS', '-m', '60', '-A', 'Scriptura licence check (build script)', '-G',
             'https://commons.wikimedia.org/w/api.php',
             '--data-urlencode', 'action=query', '--data-urlencode', 'prop=imageinfo',
             '--data-urlencode', 'iiprop=extmetadata', '--data-urlencode', 'format=json',
             '--data-urlencode', f'titles={batch}'],
            capture_output=True, text=True, check=True).stdout
        pages = json.loads(out)['query']['pages'].values()
        for p in pages:
            meta = (p.get('imageinfo') or [{}])[0].get('extmetadata', {})
            found[p['title']] = {
                'licence': meta.get('LicenseShortName', {}).get('value', ''),
                'artist': re.sub(r'<[^>]+>', '', meta.get('Artist', {}).get('value', '')).strip()}
    return {img: found.get(t, {}) for img, t in titles.items() if t}


def norm_licence(s):
    s = s.lower().replace('-', ' ').strip()
    s = re.sub(r'\s+', ' ', s)
    return {'pd': 'public domain', 'public domain mark': 'public domain'}.get(s, s)


# ── the checks ─────────────────────────────────────────────────────────────
def main():
    d = tomllib.load(open(TOML, 'rb'))
    from archaeology_reader import ArchaeologyReader
    entries, details = d.get('entry', []), d.get('detail', [])
    images = {e['image']: e.get('source', '') for e in entries}
    images.update({x['image']: x.get('source', '') for x in details})

    verses, off_map, undated = {}, [], []
    for e in entries:
        where = e['image']
        refs = e.get('refs', [])
        order = []
        for r in refs:
            b, c, v = r['book'], r['chapter'], r['verse']
            if b not in BOOKS:
                errors.append(f"{where}: unknown book {b}")
                continue
            text = kjv(b, c, v)
            if not text:
                errors.append(f"{where}: {b} {c}:{v} has no KJV text")
            verses[f"{b} {c}:{v}"] = text
            order.append((BOOKS.index(b), c, v))
            if 'fact' in e and r.get('kind') not in KINDS:
                errors.append(f"{where}: {b} {c}:{v} has no kind, or an unknown one")
        if order != sorted(order):
            errors.append(f"{where}: verses out of canonical order")
        if not os.path.exists(os.path.join(DATA, 'images', e['image'])):
            errors.append(f"{where}: image missing")
        # An object of a type ("a Herodian lamp") has no findspot, and an age
        # ("Iron Age") no year: the map and the timeline leave them out, by
        # design. Where a place or a year is given, it must land.
        if e.get('lat') is None:
            off_map.append(where)
        elif not (LON[0] <= e['lon'] <= LON[1] and LAT[0] <= e['lat'] <= LAT[1]):
            errors.append(f"{where}: off the map ({e.get('lat')}, {e.get('lon')})")
        if ArchaeologyReader._parse_year(e.get('date', '')) is None:
            undated.append(f"{where} ({e.get('date')})")
        if 'fact' in e:
            if 'caption' in e:
                errors.append(f"{where}: a fact line and a caption both")
            if len(e['fact']) > FACT_MAX:
                errors.append(f"{where}: fact line over {FACT_MAX} characters")
        for n in e.get('notes', []):
            if len(n) > NOTE_MAX:
                errors.append(f"{where}: a note over {NOTE_MAX} characters: {n[:40]}…")
        for q in e.get('quote', []):
            check_quote(q, where)
        for rel in e.get('related', []):
            if rel not in images:
                errors.append(f"{where}: see-also {rel} is no entry")
    for x in details:
        if not os.path.exists(os.path.join(DATA, 'images', x['image'])):
            errors.append(f"detail {x['image']}: image missing")
    for q in d.get('apocrypha', []):
        check_quote(q, 'apocrypha')

    # Licences: what the credit names against what Commons records.
    cache = json.load(open(LICENCES)) if os.path.exists(LICENCES) else {}
    if '--refresh-licences' in sys.argv:
        cache = refresh_licences(images)
        with open(LICENCES, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write('\n')
    for e in entries:
        lic = e.get('credit', '').rpartition('·')[2]
        rec = cache.get(e['image'], {}).get('licence')
        if rec is None:
            warns.append(f"{e['image']}: no licence on record (run --refresh-licences)")
            continue
        if re.search(r'\bNC\b|\bND\b|noncommercial|noderiv', rec, re.I):
            errors.append(f"{e['image']}: Commons records {rec}, which we cannot use")
        if norm_licence(lic) != norm_licence(rec):
            errors.append(f"{e['image']}: the credit says {lic.strip()!r}, Commons records {rec!r}")

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(verses, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    done = sum(1 for e in entries if 'fact' in e)
    print(f"entries {len(entries)}  rewritten {done}  verses {len(verses)}  "
          f"quotations {sum(len(e.get('quote', [])) for e in entries) + len(d.get('apocrypha', []))}")
    print("not on the map, by design:", ", ".join(off_map) or "none")
    print("not on the timeline, by design:", ", ".join(undated) or "none")
    for w in warns:
        print("WARN", w)
    if _UNCHECKED:
        print("WARN quotations not checked, sources missing (run fetch_texts.py):",
              ", ".join(sorted(_UNCHECKED)))
    for e in errors:
        print("FAIL", e)
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
