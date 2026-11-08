#!/usr/bin/env python3
"""Build the Tyndale Open Study Notes as a SWORD commentary module.

Source: Tyndale House Publishers' own release, tyndale_open-studynotes.zip
from https://tyndaleopenresources.com, CC BY-SA 4.0. Pass the unzipped
"Tyndale Open Study Notes" folder.

The notes were written for the New Living Translation: each comment opens
on the NLT's words for the verse, and on 400 random notes only 30% of
those words stand word for word in the KJV verse. The module says so in
its name and its About, so a reader on another Bible knows why a phrase
may not be on the page.

Each verse's entry gathers every piece that begins there, widest first:
the book's summary and introduction (at its first verse), then theme notes
and profiles, then section notes, then the verse's own note. A piece on a
verse the KJV numbers differently (the NLT's 3 John 15 is the KJV's 14)
goes to the last verse the KJV has before it.

Written as OSIS the commentary pane already shows: <hi type="bold"> for
headings and the reference each note leads with, <hi type="italic">,
paragraphs split by <div type="x-p"/>, verse links as
<reference osisRef="Bible:…">, which the pane makes clickable.

Usage:  python3 tools/build_tyndale_notes.py --src DIR --out DIR
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from build_tyndale_dict import _BOOK_FIX, _BREF, _ITEM_LINK, _exists, osis_refs  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import open_data  # noqa: E402

MODULE = 'TyndaleSN'

# Pieces in the order they stand at a verse, and the file each comes from.
_KINDS = (('BookIntroSummaries', 0), ('BookIntros', 1), ('ThemeNotes', 2),
          ('Profiles', 3), ('StudyNotes', 4))
_ITEM = re.compile(r'<item ([^>]*)>(.*?)</item>', re.S)


def _bold(t):
    return f'<hi type="bold">{t}</hi>'


def _inline(text, bad_refs):
    def ref(m):
        refs = osis_refs(m.group(1))
        if not refs or not all(map(_exists, refs)):
            bad_refs.append(m.group(1))
            return m.group(2)
        # A chapter alone ("Ps.23") becomes its first verse, which the
        # pane's link can open.
        refs = [r if r.count('.') >= 2 else f'{r}.1' for r in refs]
        return ('<reference osisRef="'
                + ' '.join(f'Bible:{r}' for r in refs) + f'">{m.group(2)}</reference>')
    text = _BREF.sub(ref, text)
    text = _ITEM_LINK.sub(r'\1', text)
    # The quoted words and the verse label are bold, and Tyndale splits
    # them into sibling spans where the divine name or a small capital
    # falls inside ("<excerpt-divine-name>Lord</…><excerpt> God</…>"):
    # every part goes bold, the small capitals as capitals, or "LORD God"
    # loses its bold on LORD.
    text = re.sub(r'<span class="sn-(?:excerpt|ref)-(?:divine-name|sc)">(.*?)</span>',
                  lambda m: _bold(m.group(1).upper()), text, flags=re.S)
    text = re.sub(r'<span class="sn-excerpt-roman">(.*?)</span>',
                  lambda m: _bold(m.group(1)), text, flags=re.S)
    # Small capitals stand for capitals: LORD, NLT, the "B" of "BC".
    text = re.sub(r'<span class="[^"]*(?:-sc|^sc|divine-name)[^"]*">(.*?)</span>',
                  lambda m: m.group(1).upper(), text, flags=re.S)
    text = re.sub(r'<span class="(?:sc|sn-sc|sc-ital|bold-sc)">(.*?)</span>',
                  lambda m: m.group(1).upper(), text, flags=re.S)
    # The verse a note is on, and the Bible words it explains, lead it.
    text = re.sub(r'<span class="(?:sn-ref|sn-excerpt|bold|intro-h2)">(.*?)</span>',
                  lambda m: _bold(m.group(1)), text, flags=re.S)
    text = re.sub(r'<span class="(?:ital|ital-bold|divine-name-ital)">(.*?)</span>',
                  r'<hi type="italic">\1</hi>', text, flags=re.S)
    text = re.sub(r'<span class="[^"]*">(.*?)</span>', r'\1', text, flags=re.S)
    text = re.sub(r'<(?!/?(?:hi|reference)\b)[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def render(body, bad_refs):
    out = []
    for cls, inner in re.findall(r'<p(?: class="([^"]*)")?[^>]*>(.*?)</p>', body, re.S):
        text = _inline(inner, bad_refs)
        if not text:
            continue
        if cls.endswith(('-title', '-h1', '-h2')):
            text = _bold(text)
        out.append(text)
    return '<div type="x-p"/>'.join(out)


def _letters(markup):
    return len(re.sub(r'\W', '', re.sub(r'<[^>]+>', ' ', html.unescape(markup))))


def _place(ref):
    """'Gen.1.1-2.3' → ('Genesis', 1, 1) in the KJV, or None."""
    first = re.sub(r'-.*', '', ref.strip())
    code, _, rest = first.partition('.')
    t = open_data._parse_osis_one(f'{_BOOK_FIX.get(code, code)}.{rest}')
    if not t:
        return None
    book, chapter, verse = t
    while verse > 1 and not _exists(f'{open_data_osis(book)}.{chapter}.{verse}'):
        verse -= 1
    return book, chapter, verse


_OSIS_OF = {v: k for k, v in open_data._OSIS_BOOKS.items() if k != 'Rev'}
_OSIS_OF['Revelation'] = 'Rev'


def open_data_osis(book):
    return _OSIS_OF[book]


def _span(ref):
    """How many verses a piece covers, roughly: wider pieces stand first."""
    vids = open_data._osis_to_vids(re.sub(r'(\d+)\.(\d+)-(\d+)\.(\d+)',
                                          r'\1.\2-\1.\4', ref))
    a, _, b = ref.partition('-')
    ta = open_data._parse_osis_one(a)
    if b and ta:
        parts = b.split('.')
        tb = (open_data._parse_osis_one(b) if len(parts) == 3
              else (ta[0], int(parts[0]), int(parts[1])) if len(parts) == 2
              else (ta[0], ta[1], int(parts[0])))
        if tb:
            return (tb[1] - ta[1]) * 1000 + (tb[2] - ta[2])
    return len(vids)


def load(src):
    """{(book, ch, v): [(order, -span, markup)]}, and the build's report."""
    at, bad_refs, short, unplaced = {}, [], [], []
    for kind, order in _KINDS:
        text = open(os.path.join(src, f'{kind}.xml'), encoding='utf-8').read()
        for attrs, inner in _ITEM.findall(text):
            ref = re.search(r'<refs>([^<]+)</refs>', inner)
            body = re.search(r'<body>(.*?)</body>', inner, re.S)
            if not ref or not body:
                continue
            ref = ref.group(1).strip()
            markup = render(body.group(1), bad_refs)
            if _letters(markup) < _letters(body.group(1)):
                short.append((kind, ref))
            where = _place(ref)
            if where is None:
                unplaced.append((kind, ref))
                continue
            at.setdefault(where, []).append((order, -_span(ref), markup))
    return at, {'bad_refs': bad_refs, 'short': short, 'unplaced': unplaced}


CONF = """[{module}]
Description=Tyndale Open Study Notes (on the New Living Translation)
DataPath=./modules/comments/zcom/{lower}/
ModDrv=zCom
BlockType=BOOK
CompressType=ZIP
SourceType=OSIS
Encoding=UTF-8
Versification=KJV
Lang=en
Version=1.0
GlobalOptionFilter=OSISFootnotes
About=Book introductions, theme notes, profiles, and verse-by-verse study \\
notes on the whole Bible.\\par\\par \\
The notes were written for the New Living Translation: a note opens on the \\
NLT's words for the verse, which another Bible may word differently.\\par\\par \\
Adapted from Tyndale Open Study Notes. The original work by Tyndale House \\
Publishers is available for free at http://www.tyndaleopenresources.com. \\
Copyright (C) 2022 by Tyndale House Publishers, licensed CC BY-SA 4.0.\\par\\par \\
Changes: each note placed at the first verse it covers, in KJV numbering \\
(a note on a verse the KJV numbers otherwise, at the verse before it); a \\
verse's notes joined, the widest first; the further-study lists kept as text.
DistributionLicense=Creative Commons: BY-SA 4.0
Copyright=Copyright (C) 2022 by Tyndale House Publishers. Licensed CC BY-SA 4.0.
TextSource=https://tyndaleopenresources.com
LCSH=Bible--Commentaries.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='the "Tyndale Open Study Notes" folder')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    at, report = load(args.src)
    pieces = sum(len(v) for v in at.values())
    print(f'{pieces} pieces at {len(at)} verses')
    print(f'unreadable verse links: {len(report["bad_refs"])} {report["bad_refs"][:8]}')
    print(f'pieces short of their source: {len(report["short"])} {report["short"][:5]}')
    print(f'pieces with no place: {len(report["unplaced"])} {report["unplaced"][:8]}')

    work = os.path.join(args.out, '_work')
    lower = MODULE.lower()
    datadir = os.path.join(work, 'modules', 'comments', 'zcom', lower)
    os.makedirs(datadir, exist_ok=True)
    os.makedirs(os.path.join(work, 'mods.d'), exist_ok=True)
    imp = os.path.join(args.out, f'{MODULE}.imp')
    order = {b: i for i, b in enumerate(open_data._BOOKS)}
    with open(imp, 'w', encoding='utf-8') as fh:
        for (book, ch, v) in sorted(at, key=lambda k: (order[k[0]], k[1], k[2])):
            parts = [m for _o, _s, m in sorted(at[(book, ch, v)])]
            fh.write(f'$$${book} {ch}:{v}\n' + '<div type="x-p"/>'.join(parts) + '\n')
    r = subprocess.run(['imp2vs', imp, '-o', datadir + '/', '-z', 'z', '-4', '-b', '4'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('imp2vs failed:', (r.stderr or r.stdout)[-400:])
        return 1
    open(os.path.join(work, 'mods.d', f'{lower}.conf'), 'w',
         encoding='utf-8').write(CONF.format(module=MODULE, lower=lower))
    zip_path = os.path.join(args.out, f'{MODULE}.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, names in os.walk(work):
            for n in names:
                p = os.path.join(root, n)
                zf.write(p, os.path.relpath(p, work))
    print(f'zip {os.path.getsize(zip_path)/1e6:.2f} MB -> {zip_path}')
    return 0 if not (report['short'] or report['unplaced']) else 2


if __name__ == '__main__':
    sys.exit(main())
