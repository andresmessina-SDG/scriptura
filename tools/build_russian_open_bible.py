#!/usr/bin/env python3
"""Build a SWORD module from the Russian Open Bible (Door43 `ru_rob`).

Why this exists. Russian had no modern Bible the app could ship: NRT is
personal-use-only, and Biblica's CC BY-SA Open programme covers Ukrainian,
Serbian, Polish, Czech and a dozen others but pointedly not Russian. `ru_rob`
is the way out — a community revision of the public-domain 1876 Synodal,
released CC BY-SA 4.0, complete in 66 books, and word-aligned to the
unfoldingWord Greek/Hebrew.

The alignment is the point. Its `\\zaln-s` milestones carry `x-strong`,
`x-lemma` and `x-morph` for every word, so a careless USFM strip would throw
away the only Strong's-tagged modern Russian text in existence — the exact
loss `_parse_usfm` used to inflict on eBible. Everything here is arranged so
that data survives into OSIS `<w lemma="strong:...">`.

Usage:  python3 tools/build_russian_open_bible.py --src DIR --out DIR
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import zipfile

MODULE = 'RusOpenBible'

#: USFM book id -> (OSIS id, Russian title). Synodal titles, since the module
#: is Russian and SWORD shows the conf/OSIS names in some surfaces.
BOOKS = [
    ('GEN', 'Gen'), ('EXO', 'Exod'), ('LEV', 'Lev'), ('NUM', 'Num'),
    ('DEU', 'Deut'), ('JOS', 'Josh'), ('JDG', 'Judg'), ('RUT', 'Ruth'),
    ('1SA', '1Sam'), ('2SA', '2Sam'), ('1KI', '1Kgs'), ('2KI', '2Kgs'),
    ('1CH', '1Chr'), ('2CH', '2Chr'), ('EZR', 'Ezra'), ('NEH', 'Neh'),
    ('EST', 'Esth'), ('JOB', 'Job'), ('PSA', 'Ps'), ('PRO', 'Prov'),
    ('ECC', 'Eccl'), ('SNG', 'Song'), ('ISA', 'Isa'), ('JER', 'Jer'),
    ('LAM', 'Lam'), ('EZK', 'Ezek'), ('DAN', 'Dan'), ('HOS', 'Hos'),
    ('JOL', 'Joel'), ('AMO', 'Amos'), ('OBA', 'Obad'), ('JON', 'Jonah'),
    ('MIC', 'Mic'), ('NAM', 'Nah'), ('HAB', 'Hab'), ('ZEP', 'Zeph'),
    ('HAG', 'Hag'), ('ZEC', 'Zech'), ('MAL', 'Mal'),
    ('MAT', 'Matt'), ('MRK', 'Mark'), ('LUK', 'Luke'), ('JHN', 'John'),
    ('ACT', 'Acts'), ('ROM', 'Rom'), ('1CO', '1Cor'), ('2CO', '2Cor'),
    ('GAL', 'Gal'), ('EPH', 'Eph'), ('PHP', 'Phil'), ('COL', 'Col'),
    ('1TH', '1Thess'), ('2TH', '2Thess'), ('1TI', '1Tim'), ('2TI', '2Tim'),
    ('TIT', 'Titus'), ('PHM', 'Phlm'), ('HEB', 'Heb'), ('JAS', 'Jas'),
    ('1PE', '1Pet'), ('2PE', '2Pet'), ('1JN', '1John'), ('2JN', '2John'),
    ('3JN', '3John'), ('JUD', 'Jude'), ('REV', 'Rev'),
]

# ── Strong's normalisation ────────────────────────────────────────────────
# The two testaments are numbered differently in the source and BOTH differ
# from what a SWORD Strong's lexicon is keyed on. Getting this wrong costs
# nothing at build time and everything at read time: the numbers render, the
# lexicon finds none of them, and the failure looks like a missing module.
#
#   NT  G15100  -> five digits, the fifth a sub-index  -> G1510
#   OT  H0430   -> four digits, zero-padded            -> H430
#       H1254a  -> homograph letter, no SWORD entry    -> H1254
#       c:d:H0776 -> Hebrew prefix particles           -> H776
_PREFIX = re.compile(r'^(?:[a-z]:)+')


def normalise_strong(raw: str) -> str | None:
    s = _PREFIX.sub('', raw.strip())
    m = re.match(r'^([GH])(\d+)([a-z]?)$', s)
    if not m:
        return None
    letter, digits, _homograph = m.groups()
    if letter == 'G' and len(digits) == 5:
        digits = digits[:4]
    n = int(digits)
    return f'{letter}{n}' if n else None


def _esc(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


_ZALN_S = re.compile(r'\\zaln-s\s*\|([^\\]*)\\\*')
_W = re.compile(r'\\w\s+([^|\\]*?)(?:\|[^\\]*?)?\\w\*')


def render_verse(chunk: str) -> str:
    """USFM3 verse body -> OSIS, keeping the alignment's Strong's numbers.

    `\\zaln-s` opens a span that may hold several `\\w` words and may nest
    (one Greek word aligned to a Russian phrase, or two Greek words to one).
    Only the INNERMOST open alignment applies to a word — an outer `ὁ` must
    not stamp its number onto the noun inside it — so the milestones are
    walked with a stack rather than matched pairwise.
    """
    out: list[str] = []
    stack: list[tuple[str | None, str | None]] = []
    i = 0
    while i < len(chunk):
        if chunk.startswith('\\zaln-s', i):
            m = _ZALN_S.match(chunk, i)
            if m:
                attrs = m.group(1)
                sm = re.search(r'x-strong="([^"]*)"', attrs)
                mm = re.search(r'x-morph="([^"]*)"', attrs)
                stack.append((normalise_strong(sm.group(1)) if sm else None,
                              mm.group(1) if mm else None))
                i = m.end()
                continue
        if chunk.startswith('\\zaln-e\\*', i):
            if stack:
                stack.pop()
            i += len('\\zaln-e\\*')
            continue
        if chunk.startswith('\\w', i):
            m = _W.match(chunk, i)
            if m:
                word = _esc(m.group(1))
                strong, morph = stack[-1] if stack else (None, None)
                if strong:
                    attr = f' lemma="strong:{strong}"'
                    if morph:
                        attr += f' morph="{_esc(morph)}"'
                    out.append(f'<w{attr}>{word}</w>')
                else:
                    out.append(word)
                i = m.end()
                continue
        if chunk.startswith('\\', i):
            m = re.match(r'\\\+?[a-z0-9-]+\*?', chunk[i:])
            if m:
                i += m.end()
                continue
        out.append(_esc(chunk[i]))
        i += 1
    text = ''.join(out)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


_C = re.compile(r'\\c\s+(\d+)')
# A verse marker may name a RANGE — `\\v 56-57`, four of them in this source.
# Matching only the first number leaves the rest of the marker sitting in the
# verse body, and the module ships «-57 чтобы научить вас…». The range is
# consumed here and the text filed under its first verse, which is what
# osis2mod expects; the second number is simply absent, as it is in any module
# whose translator merged two verses.
_V = re.compile(r'\\v\s+(\d+[a-z]?)(?:\s*[-–]\s*\d+[a-z]?)?')


def book_to_osis(usfm: str, osis_id: str) -> str:
    body = [f'<div type="book" osisID="{osis_id}">']
    chapters = list(_C.finditer(usfm))
    for n, cm in enumerate(chapters):
        ch = int(cm.group(1))
        end = chapters[n + 1].start() if n + 1 < len(chapters) else len(usfm)
        body.append(f'<chapter osisID="{osis_id}.{ch}">')
        seg = usfm[cm.end():end]
        verses = list(_V.finditer(seg))
        for k, vm in enumerate(verses):
            v = vm.group(1)
            vend = verses[k + 1].start() if k + 1 < len(verses) else len(seg)
            text = render_verse(seg[vm.end():vend])
            if not text:
                continue
            body.append(f'<verse osisID="{osis_id}.{ch}.{v}">{text}</verse>')
        body.append('</chapter>')
    body.append('</div>')
    return '\n'.join(body)


CONF = '''[{mod}]
DataPath=./modules/texts/ztext/rusopenbible/
ModDrv=zText
BlockType=BOOK
CompressType=ZIP
SourceType=OSIS
Encoding=UTF-8
Lang=ru
Versification=Synodal
GlobalOptionFilter=OSISStrongs
GlobalOptionFilter=OSISMorph
Feature=StrongsNumbers
Description=Русский открытый перевод (Russian Open Bible)
About=Russian Open Bible — современный русский перевод общественного \\
проекта Door43. Он восходит к Синодальному переводу 1876 года, но переписан \\
на нынешнем языке. В 23 книгах из 66 — среди них Евангелия, Деяния, \\
большинство посланий Павла, Бытие и Исход — каждое слово выровнено по \\
греческому и еврейскому тексту unfoldingWord и несёт номер Стронга, лемму и \\
морфологический разбор.\\par\\par\\
Russian Open Bible: a modern Russian text from the Door43 community. It \\
descends from the public-domain 1876 Synodal Bible but is rewritten in \\
present-day Russian. In 23 of its 66 books — the Gospels, Acts, most of \\
Paul, Genesis and Exodus among them — every word is aligned to the \\
unfoldingWord Greek and Hebrew and carries a Strong's number, lemma and \\
morphological parse.
TextSource=https://git.door43.org/Door43-Catalog/ru_rob
DistributionLicense=Creative Commons: BY-SA 4.0
Copyright=Door43 World Missions Community. Licensed CC BY-SA 4.0.
Version={version}
MinimumVersion=1.8.900
Category=Biblical Texts
LCSH=Bible. Russian.
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='directory of ru_rob .usfm files')
    ap.add_argument('--out', required=True)
    ap.add_argument('--version', default='1.0')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, '_work')
    datadir = os.path.join(work, 'modules', 'texts', 'ztext', 'rusopenbible')
    os.makedirs(datadir, exist_ok=True)
    os.makedirs(os.path.join(work, 'mods.d'), exist_ok=True)

    files = {f.split('-', 1)[1].replace('.usfm', '').upper(): f
             for f in os.listdir(args.src) if f.lower().endswith('.usfm')}

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">',
             f'<osisText osisIDWork="{MODULE}" osisRefWork="bible" xml:lang="ru">',
             f'<header><work osisWork="{MODULE}">'
             f'<title>Russian Open Bible</title>'
             f'<identifier type="OSIS">Bible.{MODULE}</identifier>'
             f'<rights>CC BY-SA 4.0</rights></work></header>']
    missing, strongs_total = [], 0
    for usfm_id, osis_id in BOOKS:
        f = files.get(usfm_id)
        if not f:
            missing.append(usfm_id)
            continue
        raw = open(os.path.join(args.src, f), encoding='utf-8').read()
        xml = book_to_osis(raw, osis_id)
        strongs_total += xml.count('lemma="strong:')
        parts.append(xml)
    parts.append('</osisText></osis>')
    osis_path = os.path.join(work, f'{MODULE}.osis.xml')
    open(osis_path, 'w', encoding='utf-8').write('\n'.join(parts))
    print(f'OSIS: {os.path.getsize(osis_path)/1e6:.1f} MB, '
          f'{strongs_total:,} Strong\'s tags, missing books: {missing or "none"}')

    r = subprocess.run(['osis2mod', datadir, osis_path,
                        '-v', 'Synodal', '-z', 'z', '-b', '4'],
                       capture_output=True, text=True)
    tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
    print('osis2mod:', r.returncode, '|', ' / '.join(tail))
    if r.returncode != 0:
        return 1

    open(os.path.join(work, 'mods.d', 'rusopenbible.conf'), 'w',
         encoding='utf-8').write(CONF.format(mod=MODULE, version=args.version))

    zip_path = os.path.join(args.out, f'{MODULE}.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, names in os.walk(work):
            for n in names:
                p = os.path.join(root, n)
                if p == osis_path:
                    continue
                zf.write(p, os.path.relpath(p, work))
    print(f'zip {os.path.getsize(zip_path)/1e6:.1f} MB -> {zip_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
