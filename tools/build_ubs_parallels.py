#!/usr/bin/env python3
"""Build data/parallels/ubs.tsv from the UBS Parallel Passages database.

UBS numbers its Old Testament verses by the Hebrew text and its New
Testament by the Greek. The app reads in English (KJV) numbering, so each
verse is moved through STEPBible's TVTMS table, which pairs the KJV column
with the Hebrew and Greek ones verse by verse. A verse the table does not
list keeps its number.

Inputs (both CC BY / CC BY-SA, see data/parallels/NOTICE):
  ParallelPassages.xml  github.com/ubsicap/ubs-open-license, "parallel passages"
  TVTMS ... CC BY.txt   github.com/STEPBible/STEPBible-Data, Versification/

Output: one passage per line; tab-separated members; each member is the
space-separated list of its English verses in OSIS ("Mark.10.7 Mark.10.8").

Usage: build_ubs_parallels.py PARALLELS_XML TVTMS_TXT [OUT_TSV]
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

# USFM code → OSIS book, the 66 books UBS covers.
_OSIS = {
    'GEN': 'Gen', 'EXO': 'Exod', 'LEV': 'Lev', 'NUM': 'Num', 'DEU': 'Deut',
    'JOS': 'Josh', 'JDG': 'Judg', 'RUT': 'Ruth', '1SA': '1Sam', '2SA': '2Sam',
    '1KI': '1Kgs', '2KI': '2Kgs', '1CH': '1Chr', '2CH': '2Chr', 'EZR': 'Ezra',
    'NEH': 'Neh', 'EST': 'Esth', 'JOB': 'Job', 'PSA': 'Ps', 'PRO': 'Prov',
    'ECC': 'Eccl', 'SNG': 'Song', 'ISA': 'Isa', 'JER': 'Jer', 'LAM': 'Lam',
    'EZK': 'Ezek', 'DAN': 'Dan', 'HOS': 'Hos', 'JOL': 'Joel', 'AMO': 'Amos',
    'OBA': 'Obad', 'JON': 'Jonah', 'MIC': 'Mic', 'NAM': 'Nah', 'HAB': 'Hab',
    'ZEP': 'Zeph', 'HAG': 'Hag', 'ZEC': 'Zech', 'MAL': 'Mal',
    'MAT': 'Matt', 'MRK': 'Mark', 'LUK': 'Luke', 'JHN': 'John', 'ACT': 'Acts',
    'ROM': 'Rom', '1CO': '1Cor', '2CO': '2Cor', 'GAL': 'Gal', 'EPH': 'Eph',
    'PHP': 'Phil', 'COL': 'Col', '1TH': '1Thess', '2TH': '2Thess',
    '1TI': '1Tim', '2TI': '2Tim', 'TIT': 'Titus', 'PHM': 'Phlm', 'HEB': 'Heb',
    'JAS': 'Jas', '1PE': '1Pet', '2PE': '2Pet', '1JN': '1John', '2JN': '2John',
    '3JN': '3John', 'JUD': 'Jude', 'REV': 'Rev',
}

# A TVTMS cell: "Psa.51:3", "Mal.3:19-21", "Num.16:36-17:2", with an
# optional leading "*" and trailing subverse marks ("a", ".2") we drop.
_CELL = re.compile(
    r'^\*?([1-3]?[A-Za-z]{2,3})\.(\d+):(\d+)[a-z]?(?:\.\d+)?'
    r'(?:-(?:(\d+):)?(\d+)[a-z]?(?:\.\d+)?)?$')


def _cell_verses(cell, max_verse):
    """The verses one TVTMS cell names, as (USFM, chapter, verse), or []."""
    m = _CELL.match(cell.strip())
    if not m:
        return []
    book = m.group(1).upper()
    c1, v1 = int(m.group(2)), int(m.group(3))
    if m.group(5) is None:
        return [(book, c1, v1)]
    c2 = int(m.group(4)) if m.group(4) else c1
    v2 = int(m.group(5))
    out = []
    c, v = c1, v1
    while (c, v) <= (c2, v2) and len(out) < 400:
        out.append((book, c, v))
        v += 1
        if c < c2 and v > max_verse.get((book, c), 999):
            c, v = c + 1, 1
    return out


def load_tvtms(path):
    """{'HEB'|'GRK': {(USFM, ch, v): (USFM, ch, v) in KJV}} for every
    verse whose number differs. Reads the condensed section only."""
    lines = open(path, encoding='utf-8-sig').read().split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('#DataStart(Condensed)'))
    end = next(i for i, l in enumerate(lines) if l.startswith('#DataEnd(Condensed)'))
    rows = [l.split('\t') for l in lines[start + 1:end]]

    # Last verse of each chapter, from the cells themselves, so a range
    # that crosses a chapter ("Num.16:36-17:2") knows where to turn.
    max_verse = {}
    for r in rows:
        for cell in r[1:]:
            m = _CELL.match(cell.strip())
            if m:
                key = (m.group(1).upper(), int(m.group(2)))
                last = int(m.group(5)) if m.group(5) and not m.group(4) else int(m.group(3))
                max_verse[key] = max(max_verse.get(key, 0), last)

    maps = {'HEB': {}, 'GRK': {}}
    cols = None
    for r in rows:
        head = r[0].strip()
        if head.startswith('$') or head == 'BIBLES':
            names = [c.strip() for c in r]
            kjv = next((i for i, n in enumerate(names) if n.startswith('English KJV')), None)
            heb = next((i for i, n in enumerate(names) if n == 'Hebrew'), None)
            grk = next((i for i, n in enumerate(names)
                        if n in ('Greek', 'Greek+NRSV')), None)
            cols = (kjv, heb, grk) if kjv is not None else None
            continue
        if not cols or not head or head.startswith(('TEST', "'", '#')):
            continue
        kjv_i = cols[0]
        if kjv_i >= len(r):
            continue
        kjv_vs = _cell_verses(r[kjv_i], max_verse)
        title = re.match(r'^\*?([1-3]?[A-Za-z]{2,3})\.(\d+):Title$', r[kjv_i].strip())
        if title:
            # A psalm title: Hebrew counts it as verse 1 (or 1-2); the KJV
            # prints it above verse 1, which is where a link should land.
            kjv_vs = [(title.group(1).upper(), int(title.group(2)), 1)]
        if not kjv_vs:
            continue
        for lang, i in (('HEB', cols[1]), ('GRK', cols[2])):
            if i is None or i >= len(r):
                continue
            src_vs = _cell_verses(r[i], max_verse)
            if not src_vs:
                continue
            if len(src_vs) == len(kjv_vs):
                pairs = zip(src_vs, kjv_vs)
            elif len(kjv_vs) == 1:
                pairs = ((s, kjv_vs[0]) for s in src_vs)
            elif len(src_vs) == 1:
                pairs = [(src_vs[0], kjv_vs[0])]
            else:
                continue
            for s, k in pairs:
                if s != k:
                    maps[lang].setdefault(s, k)
    return maps


_REF = re.compile(r'^([1-3A-Z]{3}) (\d+):(.+)$')


def _ubs_verses(text):
    """'MRK 10:7-8' / 'LUK 6:27-28,35' → [(USFM, ch, v), ...]."""
    m = _REF.match(text.strip())
    if not m:
        raise ValueError(f'unreadable reference {text!r}')
    book, ch = m.group(1), int(m.group(2))
    out = []
    for part in m.group(3).split(','):
        a, _, b = part.partition('-')
        out.extend((book, ch, v) for v in range(int(a), int(b or a) + 1))
    return out


def build(xml_path, tvtms_path):
    maps = load_tvtms(tvtms_path)
    passages = []
    seen = set()
    moved = 0
    for p in ET.parse(xml_path).getroot().iter('Passage'):
        members = []
        for v in p.iter('Verse'):
            lang = 'HEB' if 'HEB' in v.attrib else 'GRK'
            verses = []
            for ref in _ubs_verses(v.text):
                eng = maps[lang].get(ref, ref)
                moved += eng != ref
                verses.append(f'{_OSIS[eng[0]]}.{eng[1]}.{eng[2]}')
            members.append(' '.join(verses))
        key = tuple(members)
        if len(members) > 1 and key not in seen:
            seen.add(key)
            passages.append(members)
    return passages, moved


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    out = argv[3] if len(argv) > 3 else os.path.join(
        os.path.dirname(__file__), '..', 'data', 'parallels', 'ubs.tsv')
    passages, moved = build(argv[1], argv[2])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        for members in passages:
            f.write('\t'.join(members) + '\n')
    print(f'{len(passages)} passages, {moved} verses renumbered → {out}')


if __name__ == '__main__':
    main(sys.argv)
