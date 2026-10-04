#!/usr/bin/env python3
"""Build the Scriptura website into docs/, which GitHub Pages serves.

    python3 tools/build-site.py                  # the pages, from site/
    python3 tools/build-site.py --data SWORD_DIR # also re-read the passages
    python3 tools/build-site.py --assets         # also re-cut fonts and icons
    python3 tools/build-site.py --demos SWORD_DIR # also rebuild the live demos' data

The pages come from `site/page.html`, the words from `site/strings/*.toml`
and the live reading pane's text from `site/data/*.json`. The version and
the three starting libraries come from the app itself (`_version`,
`welcome.bundles_for`), so the site cannot drift from what installs.

`--data` reads John 1:1-5 and the entries a click opens through the app's
own lookups (`sword_bridge.lookup_dict_entry`, `word_links.key_for`), from a
SWORD library holding KJVA, BSB, SpaRV1909, RusOpenBible, StrongsGreek,
Wikcionario and RussianBibleWords, and from the eBible store for the two
eBible texts. Only open texts: every one is public domain or CC BY / BY-SA,
and the colophon credits each.

`--demos` builds what the working demos read: one verse in the open English
Bibles of the Family (YLT, ASV, ACV, KJVA, Webster, BSB and BBE from the
SWORD library, the LSV from the eBible store) for Read the difference; John
1:1 and Genesis 1:1 from the app's interlinear store; the Family's own
layout; four public-domain paintings from the imagery pack; and the
cross-reference map from OpenBible. Licensed Bibles appear only by name and
place on the Line, as in the app, never by their text.

Nothing here runs when the site is served; the output is plain files.
"""
import argparse
import html
import json
import os
import re
import shutil
import struct
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
DOCS = os.path.join(ROOT, 'docs')
BASE_URL = 'https://andresmessina-sdg.github.io/scriptura/'
LANGS = ('en', 'es', 'ru')
PASSAGE = ('John', 1, range(1, 6))

# The pane's two texts and the dictionary a click opens, per language.
# `left` is Strong's-tagged and clickable; `right` is plain.
TEXTS = {
    'en': {'left': ('sword', 'KJVA'), 'right': ('sword', 'BSB'),
           'lookup': 'strongs'},
    'es': {'left': ('sword', 'SpaRV1909'), 'right': ('ebible', 'spabes'),
           'lookup': 'Wikcionario'},
    'ru': {'left': ('sword', 'RusOpenBible'), 'right': ('ebible', 'russyn'),
           'lookup': 'RussianBibleWords'},
}


# ── the passage data (--data) ─────────────────────────────────────────────
_W = re.compile(r'<w\b([^>]*)>(.*?)</w>', re.S)
_STRONG = re.compile(r'strong:([GH])0*(\d+)', re.I)


def _plain(markup):
    return html.unescape(re.sub(r'<[^>]+>', '', markup))


def _clean(raw):
    """A verse's markup without its notes and headings, which are not text."""
    return re.sub(r'<(note|title)\b.*?</\1>', '', raw, flags=re.S)


def _tokens(raw):
    """[text, strongs-or-None] runs for one verse of OSIS markup."""
    raw = _clean(raw)
    out, pos = [], 0
    for m in _W.finditer(raw):
        if m.start() > pos:
            out.append([_plain(raw[pos:m.start()]), None])
        nums = ['%s%s' % (a.upper(), b) for a, b in _STRONG.findall(m.group(1))]
        # "the Word" carries the article's number beside the noun's; the
        # noun is the word a reader means to look up.
        nums = [n for n in nums if n != 'G3588'] or nums
        out.append([_plain(m.group(2)), nums[-1] if nums else None])
        pos = m.end()
    if pos < len(raw):
        out.append([_plain(raw[pos:]), None])
    return [t for t in out if t[0]]


def _strongs_entry(mgr, number):
    """Strong's Greek entry as {g, t, p, d, u}, or None when unreadable."""
    if not number.startswith('G'):
        return None
    mod = mgr.getModule('StrongsGreek')
    mod.setKeyText(number[1:].zfill(5))
    text = mod.stripText().strip()
    # G3739 in the CrossWire module carries a stray Chinese fragment; an
    # entry we cannot parse cleanly is left out rather than shown broken.
    if re.search(r'[\u3000-\u9fff]', text):
        return None
    m = re.match(r'\d+\.\s+(\S+)\s+\S+\s+(\S+)\s+\{([^}]*)\}\s*(.*)', text, re.S)
    if not m:
        return None
    greek, translit, pron, rest = m.groups()
    rest = re.sub(r'\s*see GREEK for \d+', '', rest).strip()
    defn, _sep, uses = rest.partition(':--')
    return {'g': greek, 't': translit, 'p': pron,
            'd': defn.strip().rstrip(';'), 'u': uses.strip().rstrip('.')}


def _article(markup, limit=900):
    """A dictionary article as paragraphs, cut at a paragraph near `limit`."""
    paras = [_plain(p).strip() for p in re.split(r'<br\s*/?>', markup)]
    paras = [p for p in paras if p]
    out, size = [], 0
    for p in paras:
        if out and size + len(p) > limit:
            out.append('…')
            break
        out.append(p)
        size += len(p)
    return out


def _ebible_verses(path, translation):
    import sqlite3
    con = sqlite3.connect(path)
    rows = con.execute(
        'SELECT verse, text FROM verses WHERE translation=? AND book=? '
        'AND chapter=? AND verse BETWEEN ? AND ? ORDER BY verse',
        (translation, PASSAGE[0], PASSAGE[1], PASSAGE[2][0], PASSAGE[2][-1]))
    return [t for _v, t in rows]


def _cross_refs(path, book_osis, chapter, verse, limit=6):
    """The passages OpenBible links to one verse, most-voted first, as
    (book, chapter, verse) of each target's first verse."""
    import csv
    sys.path.insert(0, ROOT)
    import open_data
    # A link may be filed under a range ("John.1.1-John.1.2"), as the app
    # reads it: match every verse the range covers.
    key = open_data._vid(open_data._OSIS_BOOKS[book_osis], chapter, verse)
    rows = []
    with open(path, encoding='utf-8') as fh:
        reader = csv.reader(fh, delimiter='\t')
        next(reader)
        for row in reader:
            if (len(row) >= 3 and row[0].startswith(book_osis + '.')
                    and key in (open_data._osis_to_vids(row[0]) or ())):
                target = open_data._osis_first_tuple(row[1])
                if target:
                    rows.append((int(row[2]), target))
    rows.sort(key=lambda r: -r[0])
    return [target for _votes, target in rows[:limit]]


def _voices(path, book, chapter, verse, limit=4):
    """The church's quotations on one verse: the narrowest passages first,
    one per author, then set in date order."""
    import sqlite3
    con = sqlite3.connect(path)
    loc = chapter * 1_000_000 + verse
    rows = con.execute(
        'SELECT author, year, source_title, text, loc_end - loc_start AS span '
        'FROM quotes WHERE book=? AND loc_start<=? AND loc_end>=? '
        'AND condemned=0 AND author NOT IN (SELECT DISTINCT book FROM quotes) '
        'ORDER BY span, year', (book, loc, loc)).fetchall()
    # A reading written to explain the verse comes before one met in passing;
    # a work that reports what heretics taught is not the church's reading.
    def genre(title):
        if re.search(r'Gospel of John|on John|Joan|Catena Aurea', title):
            return 0            # written on this Gospel
        if re.search(r'Commentar|Homil|Tractate|Sermon|Exposition', title):
            return 1            # written to explain Scripture
        return 2
    rows = sorted(rows, key=lambda r: (genre(r[2] or ''), r[4], r[1] or 0))
    picked, seen = [], set()
    for author, year, source, text, _span in rows:
        if author in seen or not text or 'Refutation of All Heresies' in (source or ''):
            continue
        seen.add(author)
        picked.append((year or 0, author, source or '', _excerpt(text)))
        if len(picked) == limit:
            break
    return sorted(picked)


def _excerpt(text, limit=420):
    """The opening of a quotation, cut at a sentence near `limit`."""
    text = re.sub(r'\s+', ' ', text).strip()
    # Catena Aurea opens many extracts on its own citation, "(Hom. v. in Joan.)".
    text = re.sub(r'^\([^)]{1,60}\)\s*', '', text)
    # ...and cites its sources in passing, "(Prov. 16. Vulg.)": the editor's
    # references, not the father's words.
    text = re.sub(r'\s*\((?=[^)]*(?:\d|\bc\.|\b[ivxl]+\.))[^()]{1,40}\)', '', text)
    if len(text) <= limit:
        return text
    cut = max(text.rfind('. ', 0, limit), text.rfind('? ', 0, limit),
              text.rfind('; ', 0, limit))
    return text[:cut + 1 if cut > limit // 2 else limit].rstrip() + ' …'


def _dodson(path):
    """Strong's number -> Dodson's brief gloss (public domain)."""
    import csv
    out = {}
    with open(path, encoding='utf-8') as fh:
        for row in csv.DictReader(fh, delimiter='\t'):
            num = (row.get("Strong's") or '').strip().lstrip('0')
            gloss = (row.get('English Definition (brief)') or '').strip()
            if num and gloss:
                out['G' + num] = gloss
    return out


def build_data(sword_dir, ebible_db, open_dir, catena_db):
    os.environ['SWORD_PATH'] = sword_dir
    sys.path.insert(0, ROOT)
    import Sword
    import sword_bridge
    import word_links
    import i18n
    mgr = Sword.SWMgr(sword_dir)
    book, chapter, verses = PASSAGE
    glosses = _dodson(os.path.join(open_dir, 'dodson.csv'))
    xref_file = os.path.join(open_dir, 'cross_references.txt')
    for lang, spec in TEXTS.items():
        i18n.install_language(lang)

        def verse_raw(module, v, where=None):
            mod = mgr.getModule(module)
            if mod is None:
                sys.exit(f'{module} is not in {sword_dir}')
            b, c = where or (book, chapter)
            mod.setKey(Sword.VerseKey(f'{b} {c}:{v}'))
            return mod.getRawEntry()

        def verse_text(b, c, v):
            """A cross-reference's verse in this page's Bible, or in its
            companion when the first lacks the book."""
            text = _plain(_clean(verse_raw(spec['left'][1], v, (b, c)))).strip()
            if not text and spec['right'][0] == 'ebible':
                import sqlite3
                row = sqlite3.connect(ebible_db).execute(
                    'SELECT text FROM verses WHERE translation=? AND book=? '
                    'AND chapter=? AND verse=?',
                    (spec['right'][1], b, c, v)).fetchone()
                text = row[0] if row else ''
            text = re.sub(r'\s+', ' ', text)
            # RV1909 sets a book's first word in capitals ("EN el principio").
            return re.sub(r'^(\w)(\w+)\b', lambda m: m.group(1) + m.group(2).lower()
                          if m.group(2).isupper() else m.group(0), text)

        left = [_tokens(verse_raw(spec['left'][1], v)) for v in verses]
        kind, name = spec['right']
        right = ([_plain(_clean(verse_raw(name, v))).strip() for v in verses]
                 if kind == 'sword' else _ebible_verses(ebible_db, name))
        entries, lookup = {}, spec['lookup']
        for v, toks in zip(verses, left):
            for tok in toks:
                word, number = tok
                # A one-letter word ("у", "a") shares its number with the
                # noun beside it; a click there would open the noun.
                if not number or len(re.sub(r'\W', '', word)) < 2:
                    tok[1] = None
                    continue
                if lookup == 'strongs':
                    key = number
                    if key not in entries:
                        entries[key] = _strongs_entry(mgr, number)
                else:
                    if lookup == 'RussianBibleWords':
                        key = word_links.key_for(lookup, book, chapter, v,
                                                 [number])
                        found = sword_bridge.lookup_dict_entry(lookup, key)[0] if key else ''
                    else:
                        found, exact = sword_bridge.lookup_dict_entry(lookup, word)
                        key = word.lower() if exact else None
                        found = found if exact else ''
                    if not key or not found:
                        tok[1] = None
                        continue
                    if key not in entries:
                        head = _strongs_entry(mgr, number) or {}
                        paras = _article(found)
                        # The Russian articles open on their own title.
                        if paras and paras[0].upper() == key.upper():
                            paras = paras[1:]
                        entries[key] = {'g': head.get('g', ''),
                                        't': head.get('t', ''),
                                        'n': number, 'h': key.upper()
                                        if lookup == 'RussianBibleWords'
                                        else word, 'a': paras}
                if entries.get(key) is None:
                    tok[1] = None
                else:
                    tok[1] = key
        entries = {k: e for k, e in entries.items() if e}
        for key, e in entries.items():
            gloss = glosses.get(e.get('n') or key)
            if gloss:
                e['b'] = gloss
        xrefs = []
        for v in verses:
            refs = []
            for b, c, rv in _cross_refs(xref_file, 'John', chapter, v):
                text = verse_text(b, c, rv)
                if text:
                    refs.append({'r': f'{i18n.book_label(b)} {c}:{rv}',
                                 't': text})
            xrefs.append(refs)
        voices = [[{'a': a, 'y': (i18n._('c. {year} AD').format(year=y) if y > 0
                                  else i18n._('c. {year} BC').format(year=-y)
                                  if y < 0 else ''),
                    's': s, 't': q}
                   for y, a, s, q in _voices(catena_db, book, chapter, v)]
                  for v in verses]
        path = os.path.join(SITE, 'data', f'{lang}.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'left': left, 'right': right, 'entries': entries,
                       'lookup': lookup, 'xrefs': xrefs, 'voices': voices,
                       'ref': f'{i18n.book_label(book)} {chapter}'},
                      fh, ensure_ascii=False, indent=1)
            fh.write('\n')
        print(f'{lang}: {len(entries)} entries, '
              f'{sum(map(len, xrefs))} cross-references, '
              f'{sum(map(len, voices))} quotations')
    i18n.install_language(None)


# ── the working demos (--demos) ───────────────────────────────────────────
# Read the difference: the open Bibles of the Family, as the app reads them.
DIFF_VERSES = (('John', 3, 16), ('Romans', 12, 2), ('Genesis', 1, 2),
               ('Philippians', 4, 6))
DIFF_BIBLES = (('YLT', 'ylt', 'sword'), ('englsv', 'lsv', 'ebible'),
               ('ASV', 'asv', 'sword'), ('ACV', 'acv', 'sword'),
               ('KJVA', 'kjv', 'sword'), ('Webster', 'webster', 'sword'),
               ('BSB', 'bsb', 'sword'), ('BBE', 'bbe', 'sword'))
# Licensed Bibles shown by name and place only, for the reader's bearings.
DIFF_OTHERS = ('nasb', 'esv', 'csb', 'niv', 'nlt', 'msg')
# Paintings that lead the art pane on their verse (imagery ids).
ART = ((419, ('Matthew', 9, 9)), (412, ('Genesis', 22, 10)),
       (425, ('Luke', 15, 20)), (423, ('John', 20, 27)))
# The map draws chapter links OpenBible's readers made at least this often.
XMAP_MIN = 8
# The words each page's own Bible sets above the interlinear.
_INTER_LINE = {'es': 'spaRV1909', 'ru': 'russyn'}
# RV1909 tags ἦν with Strong's old number; the interlinear uses the new.
_STRONGS_ALIAS = {'G2258': 'G1510'}


def _ebible_row(con, translation, book, chapter, verse):
    row = con.execute('SELECT text, markup FROM verses WHERE translation=? AND '
                      'book=? AND chapter=? AND verse=?',
                      (translation, book, chapter, verse)).fetchone()
    return (row[0], row[1] or '') if row else ('', '')


def _one_line(text):
    return re.sub(r'\s+', ' ', text.replace('¶', '')).strip()


def _xmap(open_dir):
    """Every chapter link with XMAP_MIN or more references, as packed
    (from, to, weight) triples, and each book's totals."""
    import base64
    import collections
    import csv
    import struct
    import open_data
    books = [b for b in open_data._OSIS_BOOKS if b != 'Revelation']
    alias = {'Revelation': 'Rev'}
    last = collections.Counter()
    pairs, out, linked, total = collections.Counter(), collections.Counter(), \
        collections.defaultdict(set), 0
    with open(os.path.join(open_dir, 'cross_references.txt'), encoding='utf-8') as fh:
        next(fh)
        for row in csv.reader(fh, delimiter='\t'):
            a, b = row[0].split('-')[0].split('.'), row[1].split('-')[0].split('.')
            a[0], b[0] = alias.get(a[0], a[0]), alias.get(b[0], b[0])
            if a[0] not in books or b[0] not in books:
                continue
            ia, ib = books.index(a[0]), books.index(b[0])
            last[ia] = max(last[ia], int(a[1]))
            last[ib] = max(last[ib], int(b[1]))
            if int(row[2]) <= 0:
                continue
            total += 1
            out[ia] += 1
            if ia != ib:
                linked[ia].add(ib)
            pa, pb = (ia, int(a[1])), (ib, int(b[1]))
            if pa != pb:
                pairs[tuple(sorted([pa, pb]))] += 1
    chapters = [last[i] for i in range(66)]
    start = [sum(chapters[:i]) for i in range(66)]
    keep = sorted(((start[a[0]] + a[1] - 1, start[b[0]] + b[1] - 1, min(n, 255))
                   for (a, b), n in pairs.items() if n >= XMAP_MIN),
                  key=lambda t: (t[2], t[0], t[1]))   # faint first, strong on top
    raw = b''.join(struct.pack('<HHB', *t) for t in keep)
    return books, {'total': total, 'chapters': chapters,
                   'refs': [out[i] for i in range(66)],
                   'linked': [len(linked[i]) for i in range(66)],
                   'arcs': base64.b64encode(raw).decode()}


def build_demos(sword_dir, ebible_db, open_dir, imagery_dir):
    import importlib
    import sqlite3
    os.environ['SWORD_PATH'] = sword_dir
    sys.path.insert(0, ROOT)
    import Sword
    import bible_family
    import open_data
    import sword_bridge
    mgr = Sword.SWMgr(sword_dir)
    eb = sqlite3.connect(ebible_db)

    def sword_text(module, ref):
        mod = mgr.getModule(module)
        if mod is None:
            sys.exit(f'{module} is not in {sword_dir}')
        mod.setKey(Sword.VerseKey(ref))
        return _one_line(_plain(_clean(mod.getRawEntry())))

    # Read the difference, from word for word to free on the app's own Line.
    bibles = []
    for module, nid, kind in DIFF_BIBLES:
        node = bible_family.node(nid)
        texts = [sword_text(module, f'{b} {c}:{v}') if kind == 'sword'
                 else _one_line(_ebible_row(eb, module, b, c, v)[0])
                 for b, c, v in DIFF_VERSES]
        assert all(texts), module
        bibles.append({'abbr': node.get('abbr') or module, 'name': node['name'],
                       'year': node['year'],
                       'at': round(bible_family.place_of(node).value, 2), 't': texts})
    bibles.sort(key=lambda b: b['at'])
    others = [{'abbr': bible_family.node(i)['abbr'], 'name': bible_family.node(i)['name'],
               'at': round(bible_family.place_of(bible_family.node(i)).value, 2)}
              for i in DIFF_OTHERS]

    # The interlinear: John 1:1 and Genesis 1:1, with the app's parsing.
    inter = {}
    for key, db, book, decode in (
            ('nt', 'interlinear_greek.sqlite', 'John',
             lambda m: '  +  '.join(filter(None, (sword_bridge.decode_robinson(
                 'robinson:' + c) for c in m.split())))),
            ('ot', 'interlinear_hebrew.sqlite', 'Genesis',
             lambda m: '  +  '.join(filter(None, (sword_bridge.decode_hebrew_morph(
                 'oshm:' + (s if i == 0 or s.startswith('H') else 'H' + s))
                 for i, s in enumerate(m.split('/'))))))):
        rows = sqlite3.connect(os.path.join(open_dir, db)).execute(
            'SELECT surface, translit, gloss, strongs, morph FROM words WHERE '
            'book=? AND chapter=1 AND verse=1 AND in_stream=1 ORDER BY pos',
            (book,)).fetchall()
        mod = mgr.getModule('KJVA')
        mod.setKey(Sword.VerseKey(f'{book} 1:1'))
        entry = {'ref': f'{book} 1:1', 'kjv': _tokens(mod.getRawEntry()),
                 'words': [{'s': s, 't': t, 'g': g, 'n': n, 'p': decode(m)}
                           for s, t, g, n, m in rows]}
        for lang, translation in _INTER_LINE.items():
            text, markup = _ebible_row(eb, translation, book, 1, 1)
            if '<w ' in markup:
                line = [[w, _STRONGS_ALIAS.get(n, n)] for w, n in _tokens(markup)]
            else:
                line = [[_one_line(text), None]]
            entry[lang] = {'line': line}
        inter[key] = entry

    # The Family, as family_layout draws it, with its notes in each language.
    import family_layout
    pos = {'family': family_layout.positions('family'),
           'line': family_layout.positions('line')}
    root = bible_family.family_data().get('root', {})
    nodes = []
    for nid in bible_family.family_members():
        n = bible_family.node(nid)
        place = bible_family.place_of(n)
        nodes.append({'id': nid, 'abbr': n.get('abbr') or n['name'], 'name': n['name'],
                      'year': n['year'], 'yl': n.get('year_label') or str(n['year']),
                      'note': n.get('note', ''),
                      'at': round(place.value, 2) if place else None,
                      'root': nid in root,
                      'xy': [round(v, 1) for v in pos['family'][nid]],
                      'xyl': [round(v, 1) for v in pos['line'][nid]]})
    nodes.sort(key=lambda n: n['year'])
    notes, ui, zones = {}, {}, {}
    for lang in LANGS:
        with _InLanguage(lang) as i18n:
            importlib.reload(bible_family)
            importlib.reload(family_layout)
            notes[lang] = [[n.y, n.text] for n in family_layout.notes()]
            ui[lang] = [i18n._(t) for t in (
                'By family', 'By literalness', 'Mark differences', 'Old Testament',
                'New Testament', 'Word for word', 'Free', 'Exit reading mode',
                'Presentation', 'Exit presentation', 'Copy')]
            zones[lang] = [bible_family.zone_label(v) for v in (0.1, 0.5, 0.8, 0.95)]
    family = {'nodes': nodes, 'notes': notes,
              'edges': [{'f': e.parent, 't': e.child, 'k': e.kind}
                        for e in family_layout.edges()],
              'ticks': [[y, round(family_layout.year_y(y), 1)]
                        for y in (1611, 1700, 1800, 1900, 1950, 2000, 2025)],
              'w': family_layout.WIDTH,
              'lanes': [family_layout.LANE_LEFT, family_layout.LANE_RIGHT,
                        family_layout.NOTE_LEFT, family_layout.NOT_PLACED_X,
                        family_layout.AXIS_TOP]}
    family['h'] = round(max(max(n['xy'][1], n['xyl'][1]) for n in nodes) + 60)

    # Art for the passage: each painting, at a size a band shows, and its
    # verse in each page's Bible.
    from PIL import Image
    art_dir = os.path.join(DOCS, 'assets', 'art')
    os.makedirs(art_dir, exist_ok=True)
    img_db = sqlite3.connect(os.path.join(imagery_dir, 'imagery.sqlite'))
    art = []
    for iid, (b, c, v) in ART:
        title, artist, year, path, lic = img_db.execute(
            'SELECT title, artist, year, file_path, license FROM imagery WHERE id=?',
            (iid,)).fetchone()
        assert lic == 'PD', (iid, lic)
        im = Image.open(os.path.join(imagery_dir, path)).convert('RGB')
        im.thumbnail((1100, 1100))
        name = f'art{iid}.webp'
        im.save(os.path.join(art_dir, name), quality=80)
        art.append({'ref': [b, c, v], 'title': title, 'artist': artist, 'year': year,
                    'img': name, 'w': im.width, 'h': im.height,
                    't': {lang: _one_line(_ebible_row(eb, tr, b, c, v)[0])
                          for lang, tr in (('en', 'eng-kjv2006'), ('es', 'spaRV1909'),
                                           ('ru', 'russyn'))}})

    # The map, and the book names in each language from the app's catalogues.
    books, xmap = _xmap(open_dir)
    xmap['names'] = {}
    for lang in LANGS:
        with _InLanguage(lang) as i18n:
            xmap['names'][lang] = [i18n._(open_data._OSIS_BOOKS[b]) for b in books]

    for name, data in (('demos', {'diff': {'refs': [f'{b} {c}:{v}' for b, c, v in DIFF_VERSES],
                                            'bibles': bibles, 'others': others},
                                   'inter': inter, 'family': family, 'art': art,
                                   'ui': ui, 'zones': zones}),
                       ('xmap', xmap)):
        with open(os.path.join(SITE, 'data', f'{name}.json'), 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.write('\n')
    print(f'demos: {len(bibles)} Bibles, {len(nodes)} in the Family, {len(art)} paintings; '
          f'map: {xmap["total"]} cross-references, {len(xmap["arcs"]) * 3 // 4 // 5} arcs')


# ── fonts and icons (--assets) ────────────────────────────────────────────
LATIN = ('U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+2013-2014,'
         'U+2018-201E,U+2022,U+2026,U+2039-203A,U+00B7,U+2009,U+2192')
GREEK = 'U+0370-03FF,U+1F00-1FFF,U+0300-036F'
CYRILLIC = 'U+0400-045F,U+0490-0491,U+2116'
FONTS = [
    # (source, output, ranges, pinned axes or None)
    ('AdwaitaSans-Regular.ttf', 'sans-latin', LATIN, None),
    ('AdwaitaSans-Regular.ttf', 'sans-cyrillic', CYRILLIC, None),
    ('Newsreader[opsz,wght].ttf', 'prose', LATIN, None),
    # Italic sets only transliterations, which are plain Latin letters.
    ('Newsreader-Italic[opsz,wght].ttf', 'prose-italic', 'U+0020-007E',
     {'opsz': 18, 'wght': 400}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-latin', LATIN + ',' + GREEK,
     {'wdth': 100, 'wght': 400}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-cyrillic', CYRILLIC,
     {'wdth': 100, 'wght': 400}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-medium-latin', LATIN,
     {'wdth': 100, 'wght': 600}),
    ('NotoSerif[wdth,wght].ttf', 'scripture-medium-cyrillic', CYRILLIC,
     {'wdth': 100, 'wght': 600}),
    # The wordmark's seven letters: the S is the icon's own initial.
    ('EBGaramond[wght].ttf', 'wordmark', 'U+0061,U+0063,U+0069,U+0070,U+0072,U+0074,U+0075',
     {'wght': 500}),
    # The margins' alphabet: the twenty-two letters, no final forms.
    ('NotoSerifHebrew[wdth,wght].ttf', 'hebrew', ','.join(
        'U+%04X' % c for c in range(0x05D0, 0x05EB)
        if c not in (0x05DA, 0x05DD, 0x05DF, 0x05E3, 0x05E5)),
     {'wdth': 100, 'wght': 400}),
    # The interlinear's Hebrew, pointed and accented: the whole block.
    ('NotoSerifHebrew[wdth,wght].ttf', 'hebrew-text', 'U+0020,U+0591-05F4,U+FB1D-FB4F',
     {'wdth': 100, 'wght': 400}),
]
# Phone-sized crops of two screenshots: the part that matters, at a size a
# phone can read. (left, top, right, bottom) in the 1366 x 733 shot.
PHONE_CROPS = {'voices': (696, 84, 1366, 733), 'writing': (600, 250, 1200, 690)}


def build_assets():
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    out = os.path.join(DOCS, 'assets', 'fonts')
    os.makedirs(out, exist_ok=True)
    for src, name, ranges, pin in FONTS:
        font = TTFont(os.path.join(ROOT, 'data', 'fonts', src), lazy=False)
        if pin:
            font = instancer.instantiateVariableFont(font, pin)
        opts = subset.Options()
        opts.flavor = 'woff2'
        opts.layout_features = ['*']
        # Keep every name record: the OFL asks that the copyright and the
        # licence travel with the font, and they live in records 0, 13, 14.
        opts.name_IDs = ['*']
        opts.name_languages = ['*']
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=subset.parse_unicodes(ranges))
        sub.subset(font)
        subset.save_font(font, os.path.join(out, name + '.woff2'), opts)
    # The icon is a PNG inside the app's SVG; cut the sizes a browser asks for.
    import base64
    import io
    from PIL import Image
    svg = open(os.path.join(ROOT, 'data', 'icons', 'hicolor', 'scalable', 'apps',
                            'io.github.andresmessina_SDG.Scriptura.svg')).read()
    png = base64.b64decode(re.search(r'base64,([^"]+)', svg).group(1))
    icon = Image.open(io.BytesIO(png)).convert('RGBA')
    for size in (32, 64, 180):
        icon.resize((size, size), Image.LANCZOS).save(
            os.path.join(DOCS, 'assets', f'icon-{size}.png'), optimize=True)
    # Browsers ask for /favicon.ico whatever the page names.
    icon.resize((32, 32), Image.LANCZOS).save(
        os.path.join(DOCS, 'favicon.ico'), sizes=[(16, 16), (32, 32)])
    # One notice for the folder: each face's own copyright line, then the
    # licence they share.
    notices = []
    for src in sorted({f[0] for f in FONTS}):
        name = TTFont(os.path.join(ROOT, 'data', 'fonts', src))['name']
        notices.append(f'{src}: {name.getDebugName(0)}')
    with open(os.path.join(ROOT, 'data', 'fonts', 'AdwaitaSans-OFL.txt'),
              encoding='utf-8') as fh:
        licence = fh.read()
    licence = licence[licence.index('This Font Software is licensed'):]
    with open(os.path.join(out, 'LICENSE.txt'), 'w', encoding='utf-8') as fh:
        fh.write('The fonts in this folder are subsets of these faces, each\n'
                 'under the SIL Open Font License 1.1:\n\n'
                 + '\n'.join(notices) + '\n\n' + licence)
    stale = os.path.join(out, 'OFL.txt')
    if os.path.exists(stale):
        os.remove(stale)
    for lang in LANGS:
        for name, box in PHONE_CROPS.items():
            for dark in ('', '-dark'):
                img = os.path.join(DOCS, 'assets', 'img', lang, name + dark + '.webp')
                Image.open(img).crop(box).save(
                    os.path.join(DOCS, 'assets', 'img', lang, f'{name}-phone{dark}.webp'),
                    quality=86, method=6)


# ── the pages ─────────────────────────────────────────────────────────────
_LOCALE = None


def _catalogues():
    """po/ compiled into a scratch folder, once per run.

    The library cards are translated by the app's own catalogues. A source
    checkout's locale/ is whatever `tools/build-locale.py` last wrote, and
    may be behind po/; the site is built from po/ as it stands."""
    global _LOCALE
    if _LOCALE is None:
        import atexit
        import subprocess
        import tempfile
        _LOCALE = tempfile.mkdtemp(prefix='scriptura-site-locale-')
        atexit.register(shutil.rmtree, _LOCALE, True)
        for code in LANGS[1:]:
            d = os.path.join(_LOCALE, code, 'LC_MESSAGES')
            os.makedirs(d)
            subprocess.run(['msgfmt', '-o', os.path.join(d, 'scriptura.mo'),
                            os.path.join(ROOT, 'po', f'{code}.po')], check=True)
    return _LOCALE


class _InLanguage:
    """The app's catalogues answering in `lang` for the length of a block.

    The library cards, the release notes and the dates are all the app's own
    words, translated by its own catalogues, compiled fresh from po/."""

    def __init__(self, lang):
        self.lang = lang

    def __enter__(self):
        sys.path.insert(0, ROOT)
        import i18n
        self.i18n = i18n
        self.before = os.environ.get('LANGUAGE')
        self.saved = i18n.localedir
        locale = _catalogues()
        i18n.localedir = lambda: locale
        i18n.install_language(self.lang)
        return i18n

    def __exit__(self, *_exc):
        # Put the caller's language back: a test run shares this process.
        self.i18n.localedir = self.saved
        self.i18n.install_language(self.before)


def _bundles(lang):
    """The welcome screen's starting libraries, in `lang`, from the app."""
    with _InLanguage(lang) as i18n:
        import welcome
        return [{'title': i18n._(b['title']), 'summary': b['summary'],
                 'mb': b['mb'], 'recommended': b['recommended']}
                for b in welcome.bundles_for(lang)]


def _releases(lang):
    """The store listing's release notes, newest first, in `lang` where the
    catalogue has them. Each release says whether it was translated."""
    import datetime
    import glob
    import xml.etree.ElementTree as ET
    path = glob.glob(os.path.join(ROOT, 'data', '*.metainfo.xml.in'))[0]
    out = []
    with _InLanguage(lang) as i18n:
        for rel in ET.parse(path).getroot().iter('release'):
            desc = rel.find('description')
            if desc is None:
                continue
            texts = []
            for el in desc:
                if el.tag == 'p':
                    texts.append(' '.join((el.text or '').split()))
                elif el.tag == 'ul':
                    texts += [' '.join((li.text or '').split())
                              for li in el.findall('li')]
            # Each line carries whether the catalogue had it, so a release
            # translated only in part marks its English lines as English.
            said = [(i18n._(t), lang == 'en' or i18n._(t) != t) for t in texts]
            lead = desc[0].tag == 'p'
            out.append({
                'version': rel.get('version'),
                'date': i18n.format_date(datetime.date.fromisoformat(rel.get('date'))),
                'iso': rel.get('date'),
                'summary': said[0] if lead else ('', True),
                'items': said[1:] if lead else said,
                'translated': any(ok for _t, ok in said),
            })
    return out


def _template(name):
    """A page template with its `{{> part}}` includes filled in."""
    with open(os.path.join(SITE, name), encoding='utf-8') as fh:
        text = fh.read()

    def include(m):
        with open(os.path.join(SITE, 'parts', m.group(1) + '.html'),
                  encoding='utf-8') as fh:
            return fh.read().rstrip('\n')
    return re.sub(r'\{\{> ([a-z_]+)\}\}', include, text)


def _fill(template, values):
    def sub(m):
        key = m.group(1)
        if key not in values:
            raise KeyError(f'no value for {{{{{key}}}}}')
        return str(values[key])
    return re.sub(r'\{\{([a-z0-9_.]+)\}\}', sub, template)


# Each page, and the folder it is served from beneath a language's own.
PAGES = {'home': ('page.html', ''), 'news': ('news.html', 'whats-new/')}
NAMES = (('en', 'English'), ('es', 'Español'), ('ru', 'Русский'))


def _prefix(code):
    return '' if code == 'en' else code + '/'


def _common(lang, s, root, page_path, version):
    """The values every page shares: head, header, colophon, scripts."""
    esc = html.escape
    values = {f't.{k}': (v if k.endswith('_html') else esc(v))
              for k, v in s.items() if isinstance(v, str)}
    home = root + _prefix(lang)
    here = BASE_URL + _prefix(lang) + page_path
    values.update({
        'lang': lang, 'root': root, 'version': version, 'robots': '',
        'home': home or './', 'home_install': (home or './') + '#install',
        'news_href': home + PAGES['news'][1],
        'news_current': ' aria-current="page"' if page_path == PAGES['news'][1] else '',
        'version_anchor': 'v' + version.replace('.', '-'),
        'canonical': here,
        'og_image': BASE_URL + f'assets/img/{lang}/reading.jpg',
        # The faces above the fold, fetched before the stylesheet asks.
        # (Russian prose is set in the sans; its name is still Latin.)
        'font_sans': 'sans-latin',
        'font_lede': 'sans-cyrillic' if lang == 'ru' else 'prose',
        'page_title': esc(s['title']), 'page_description': esc(s['description']),
        'page_scripts': '',
    })
    values['alternates'] = '\n'.join(
        f'<link rel="alternate" hreflang="{code}" href="{BASE_URL}{_prefix(code)}{page_path}">'
        for code in LANGS) + \
        f'\n<link rel="alternate" hreflang="x-default" href="{BASE_URL}{page_path}">'
    current = ' aria-current="page"'
    values['lang_name'] = dict(NAMES)[lang]
    values['lang_menu'] = '\n'.join(
        f'<a lang="{code}" hreflang="{code}" '
        f'href="{(root + _prefix(code) + page_path) or "./"}"'
        f'{current if code == lang else ""}>{name}'
        '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7"/></svg></a>'
        for code, name in NAMES)
    values['credits'] = '\n'.join(f'<li>{c}</li>' for c in s['credits_html'])
    values['t.hero_meta'] = esc(s['hero_meta'].format(version=version))
    return values


def _strings(lang):
    with open(os.path.join(SITE, 'strings', f'{lang}.toml'), 'rb') as fh:
        return tomllib.load(fh)


def _payload(values, text, js, **extra):
    values['data_json'] = json.dumps(dict({'text': text, 'strings': js}, **extra),
                                     ensure_ascii=False,
                                     separators=(',', ':')).replace('</', '<\\/')


def render(lang, page='home'):
    sys.path.insert(0, ROOT)
    from _version import __version__ as version
    s = _strings(lang)
    template_name, page_path = PAGES[page]
    depth = (lang != 'en') + (page_path != '')
    root = '../' * depth
    values = _common(lang, s, root, page_path, version)
    esc = html.escape
    js = dict(s['js'], papers=s['papers'], copy=s['copy'])
    if page == 'news':
        values['page_title'] = esc(s['news_title'])
        values['page_description'] = esc(s['news_description'])
        releases = _releases(lang)
        note = s['news_english_note'] if not all(r['translated'] for r in releases) else ''
        values['news_note'] = f'    <p class="note">{esc(note)}</p>' if note else ''

        def english(ok, whole):
            # Mark a line English where the rest of its release is not.
            return '' if ok or not whole['translated'] else ' lang="en"'

        def release(r):
            lang_attr = '' if r['translated'] else ' lang="en"'
            items = ''.join(f'<li{english(ok, r)}>{esc(i)}</li>' for i, ok in r['items'])
            items = f'<ul class="rel-list">{items}</ul>' if items else ''
            text, ok = r['summary']
            summary = (f'<p class="rel-sum"{english(ok, r)}>{esc(text)}</p>'
                       if text else '')
            return (f'<li class="release" id="v{r["version"].replace(".", "-")}"{lang_attr}>'
                    f'<div class="rel-head"><h2>{esc(s["release_heading"].format(version=r["version"]))}</h2>'
                    f'<time datetime="{r["iso"]}">{esc(r["date"])}</time></div>'
                    f'{summary}{items}</li>')
        values['releases'] = '\n'.join(release(r) for r in releases)
        _payload(values, None, js)
        return _fill(_template(template_name), values)

    with open(os.path.join(SITE, 'data', f'{lang}.json'), encoding='utf-8') as fh:
        data = json.load(fh)
    values['rows'] = '\n'.join(
        f'<div class="row"><h3>{esc(r["title"])}</h3><p>{esc(r["text"])}</p></div>'
        for r in s['rows'])

    def size(name):
        # Read from the lossy WebP header, so the pages build without Pillow.
        with open(os.path.join(DOCS, 'assets', 'img', lang, name + '.webp'), 'rb') as fh:
            head = fh.read(30)
        assert head[12:16] == b'VP8 ', name
        w, h = struct.unpack('<HH', head[26:30])
        return w & 0x3fff, h & 0x3fff

    def band(sh):
        """A feature at a size you can read: the picture follows the paper
        (a dark one on a dark paper), and a click opens it full size. On a
        phone, a shot with a phone crop shows the crop. Sources marked
        data-dark are the ones site.js points at the paper."""
        src = f'{root}assets/img/{lang}/{sh["img"]}'
        w, h = size(sh['img'])
        phone = ''
        if sh['img'] in PHONE_CROPS:
            pw, ph = size(sh['img'] + '-phone')
            when = '(max-width: 759px)'
            phone = (f'<source data-dark data-when="{when}" '
                     f'media="{when} and (prefers-color-scheme: dark)" '
                     f'srcset="{src}-phone-dark.webp" width="{pw}" height="{ph}">'
                     f'<source media="{when}" srcset="{src}-phone.webp" '
                     f'width="{pw}" height="{ph}">')
        narrow = ' narrow' if h > w else ''
        return (
            f'<article class="band{narrow}"><button type="button" class="zoom" '
            f'aria-label="{esc(s["zoom_label"])}: {esc(sh["title"])}">'
            f'<picture>{phone}<source data-dark media="(prefers-color-scheme: dark)" '
            f'srcset="{src}-dark.webp"><img class="shot" src="{src}.webp" '
            f'width="{w}" height="{h}" alt="{esc(sh["alt"])}" loading="lazy">'
            f'</picture></button><div class="band-text"><h3>{esc(sh["title"])}</h3>'
            f'<p>{esc(sh["text"])}</p></div></article>')
    values['bands'] = '\n'.join(band(sh) for sh in s['shots'])
    values['teach_band'] = band(s['teach_shot'])
    values['teach_rows'] = '\n'.join(
        f'<div class="row"><h3>{esc(r["title"])}</h3><p>{esc(r["text"])}</p></div>'
        for r in s['teach_rows'])
    values['claims'] = '\n'.join(
        f'<div><h3>{esc(c["title"])}</h3><p>{esc(c["text"])}</p></div>'
        for c in s['claims'])
    # The window's three steps, named as its tabs are.
    values['story_steps'] = '\n'.join(
        f'      <li class="step"><span class="n" aria-hidden="true">{i}</span>'
        f'<h3>{esc(s[tab])}</h3><p>{esc(text)}</p></li>'
        for i, (tab, text) in enumerate(
            zip(('tab_entry', 'tab_xrefs', 'tab_voices'), s['story']), 1))
    with open(os.path.join(SITE, 'data', 'xmap.json'), encoding='utf-8') as fh:
        total = json.load(fh)['total']
    sep = ',' if lang == 'en' else '\u00a0'
    values['map_p'] = esc(s['map_p'].format(total=f'{total:,}'.replace(',', sep)))
    values['page_scripts'] = ''.join(
        f'\n<script src="{root}assets/{name}" defer></script>'
        for name in ('xmap-data.js', 'xmap.js', 'demos-data.js', 'demos.js'))
    values['bundles'] = '\n'.join(
        f'<div class="bundle{" rec" if b["recommended"] else ""}"><b>{esc(b["title"])}</b>'
        f'<span>{esc(b["summary"])}</span><em>'
        + (esc(s['recommended']) + ' · ' if b['recommended'] else '')
        + esc(s['about_mb'].format(n=b['mb'])) + '</em></div>'
        for b in _bundles(lang))
    _payload(values, data, js)
    return _fill(_template(template_name), values)


def render_404():
    """One page for every missing address. GitHub Pages serves it at any
    depth, so its links are absolute; it is written in English and turns to
    Spanish or Russian in the browser, by the address or the reader's
    language."""
    sys.path.insert(0, ROOT)
    from _version import __version__ as version
    s = _strings('en')
    root = '/scriptura/'
    values = _common('en', s, root, '', version)
    nf = s['notfound']
    values.update({f'nf.{k}': html.escape(v) for k, v in nf.items()})
    values['nf.verse_initial'] = html.escape(nf['verse'][0])
    values['nf.verse_rest'] = html.escape(nf['verse'][1:])
    values['page_title'] = html.escape(nf['title'])
    values['robots'] = '<meta name="robots" content="noindex">'
    notfound = {}
    for lang in LANGS:
        t = _strings(lang)
        notfound[lang] = dict(t['notfound'], root=root + _prefix(lang))
    _payload(values, None, dict(s['js'], papers=s['papers'], copy=s['copy']),
             notfound=notfound)
    return _fill(_template('404.html'), values)


def demo_scripts():
    """The demos' data as two scripts: what --demos built, with the words
    each language's page says around it."""
    with open(os.path.join(SITE, 'data', 'demos.json'), encoding='utf-8') as fh:
        demos = json.load(fh)
    with open(os.path.join(SITE, 'data', 'xmap.json'), encoding='utf-8') as fh:
        xmap = json.load(fh)
    words = {lang: _strings(lang)['demo'] for lang in LANGS}
    for key in ('unfold', 'swipe', 'phonedl', 'pd', 'yl', 'artists'):
        demos[key] = {lang: words[lang][key] for lang in LANGS}
    demos['credit'] = {lang: words[lang]['credit_html'] for lang in LANGS}
    demos['arttitles'] = {}
    for lang in LANGS:
        for iid, title in words[lang]['art_titles'].items():
            demos['arttitles'].setdefault(iid, {})[lang] = title
    xmap['read'] = {lang: words[lang]['map_read'] for lang in LANGS}

    def script(var, data, what):
        return (f'// {what} Built by tools/build-site.py; do not edit.\n'
                f'window.{var}=' + json.dumps(data, ensure_ascii=False,
                                              separators=(',', ':')) + ';\n')
    return {'demos-data.js': script('DEMOS', demos, 'The working demos\' data.'),
            'xmap-data.js': script('XMAP', xmap, 'OpenBible.info cross-references (CC BY), '
                                   'chapter links with %d or more.' % XMAP_MIN)}


def build_pages(out=DOCS):
    for lang in LANGS:
        for page, (_name, page_path) in PAGES.items():
            path = os.path.join(out, _prefix(lang), page_path, 'index.html')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(render(lang, page))
    with open(os.path.join(out, '404.html'), 'w', encoding='utf-8') as fh:
        fh.write(render_404())
    os.makedirs(os.path.join(out, 'assets'), exist_ok=True)
    for f in ('site.css', 'site.js', 'demos.js', 'xmap.js', 'initial-s.svg'):
        shutil.copy(os.path.join(SITE, f), os.path.join(out, 'assets', f))
    for name, text in demo_scripts().items():
        with open(os.path.join(out, 'assets', name), 'w', encoding='utf-8') as fh:
            fh.write(text)
    with open(os.path.join(out, '.nojekyll'), 'w'):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--data', metavar='SWORD_DIR',
                    help='re-read the passages from this SWORD library')
    ap.add_argument('--ebible', default=os.path.expanduser(
        '~/.local/share/bible-reader/ebible.db'),
        help='the eBible store holding spabes and russyn')
    ap.add_argument('--open-data', default=os.path.expanduser(
        '~/.local/share/bible-reader/open_data'),
        help='the folder holding cross_references.txt and dodson.csv')
    ap.add_argument('--catena', default=os.path.expanduser(
        '~/.local/share/bible-reader/catena.db'),
        help='the Voices of the Church pack')
    ap.add_argument('--assets', action='store_true',
                    help='re-cut the fonts, icons and phone crops')
    ap.add_argument('--demos', metavar='SWORD_DIR',
                    help="rebuild the demos' data from this SWORD library")
    ap.add_argument('--imagery', default=os.path.expanduser(
        '~/.local/share/bible-reader/imagery'),
        help='the Bible Imagery pack, for the paintings')
    args = ap.parse_args()
    if args.data:
        build_data(os.path.abspath(args.data), args.ebible,
                   args.open_data, args.catena)
    if args.demos:
        build_demos(os.path.abspath(args.demos), args.ebible, args.open_data,
                    args.imagery)
    if args.assets:
        build_assets()
    build_pages()
    print('docs/ written')


if __name__ == '__main__':
    main()
