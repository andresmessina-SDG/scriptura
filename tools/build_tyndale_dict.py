#!/usr/bin/env python3
"""Build the Tyndale Open Bible Dictionary as a SWORD dictionary module.

Source: Tyndale House Publishers' own release, TyndaleOpenBibleDictionary.zip
from https://tyndaleopenresources.com, CC BY-SA 4.0. Unzip it and pass the
folder: it holds Articles/A.xml … Z.xml, Textboxes/, Charts/, Maps/ and
Pictures/.

What goes in, and how:

* Every article, keyed on its title in capitals with the RSV/KJV asterisk
  dropped ("Aaron's Rod*" → AARON'S ROD). Titles that differ only by a
  bracketed sense — "Abel (Person)", "Abel (Place)" — share one key, ABEL,
  each part under its own heading, so a double-clicked "Abel" finds both.
* Text boxes and charts inline where the article includes them; a chart
  reads row by row. Maps and pictures are left out: the release carries
  the maps as PDFs and the pictures not at all.
* Markup the word peek renders: <p>, <b>, <i>, <h3> for a section head.
  Verse links become OSIS <reference osisRef="Bible:…">: the peek shows
  their text, and the bar's Dictionaries index reads them. The release's
  own book codes are mended to OSIS (Pr → Prov, 1Jn → 1John, Tb → Tob…).

Changes from the source, as CC BY-SA asks us to say, go in the module's
About: the asterisks dropped, same-named articles joined, pictures and
maps left out, tables flattened to rows, links to other articles kept as
plain text.

Usage:  python3 tools/build_tyndale_dict.py --src DIR --out DIR
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import zipfile

MODULE = 'TyndaleBD'

# The release's book codes that are not OSIS, mended. Everything else it
# writes is already OSIS.
_BOOK_FIX = {
    'Pr': 'Prov', 'Mt': 'Matt', 'Jos': 'Josh', 'Esther': 'Esth',
    '1Jn': '1John', '2Jn': '2John', '3Jn': '3John',
    '1Thes': '1Thess', '2Thes': '2Thess', 'Hagg': 'Hag', 'Jon': 'Jonah',
    'Tb': 'Tob', 'Ecclus': 'Sir', 'Wisd': 'Wis',
}

_ITEM = re.compile(
    r'<item typename="(\w+)"[^>]*name="([^"]+)">\s*<title>(.*?)</title>'
    r'\s*<body>(.*?)</body>\s*</item>', re.S)
_INCLUDE = re.compile(r'<include_items src="\.\./(\w+)/\w+\.xml" name="([^"]+)"\s*/>')
# A link can carry other attributes before its target
# (`<a class="apocrypha" href=…>`): half the verse links do.
_BREF = re.compile(r'<a\b[^>]*?href="\?bref=([^"]*)"[^>]*>(.*?)</a>', re.S)
_ITEM_LINK = re.compile(r'<a\b[^>]*?href="\?item=[^"]*"[^>]*>(.*?)</a>', re.S)


def osis_refs(bref):
    """'1Sam.25.2-42,45' → ['1Sam.25.2-1Sam.25.42', '1Sam.25.45'], or []
    when the link cannot be read. Shapes in the release: C.V, C.V-V,
    C.V-C.V, C.V--Book.C.V, lists of those after commas, and a verse part
    letter (25.2b) dropped."""
    bref = bref.replace('–', '-').replace(' ', '')
    m = re.match(r'^([1-4]?[A-Za-z]+)\.(\d+)(?:\.(\d+)[a-c]?)?(.*)$', bref)
    if not m:
        return []
    book = _BOOK_FIX.get(m.group(1), m.group(1))
    chapter = int(m.group(2))
    if m.group(3) is None:
        return [f'{book}.{chapter}'] if not m.group(4) else []
    refs = []
    start = f'{book}.{chapter}.{int(m.group(3))}'
    rest = m.group(4)
    # The first range's end, if any.
    end = re.match(r'^-{1,2}(?:([1-4]?[A-Za-z]+)\.)?(?:(\d+)\.)?(\d+)[a-c]?', rest)
    if end:
        e_book = _BOOK_FIX.get(end.group(1), end.group(1)) if end.group(1) else book
        e_ch = int(end.group(2)) if end.group(2) else chapter
        if e_book == book:
            chapter = e_ch
        refs.append(f'{start}-{e_book}.{e_ch}.{int(end.group(3))}')
        rest = rest[end.end():]
    else:
        refs.append(start)
    # Then ", V" or ", V-V" in the chapter last reached.
    for part in filter(None, rest.split(',')):
        pm = re.fullmatch(r'(\d+)[a-c]?(?:-(\d+)[a-c]?)?', part)
        if not pm:
            return refs
        v1 = int(pm.group(1))
        refs.append(f'{book}.{chapter}.{v1}' + (
            f'-{book}.{chapter}.{int(pm.group(2))}' if pm.group(2) else ''))
    return refs


_CANON = None


def _exists(ref):
    """Whether the first verse of an OSIS reference is in the KJV, or the
    reference is to a book outside the 66 (left for the reader to judge)."""
    global _CANON
    if _CANON is None:
        import Sword
        _CANON = Sword.VerseKey()
    first = ref.split('-')[0].split('.')
    book = first[0]
    _CANON.setText(f'{book} 1:1')
    if str(_CANON.getOSISBookName()) != book:
        return True
    chapter = int(first[1])
    verse = int(first[2]) if len(first) > 2 else 1
    _CANON.setText(f'{book} {chapter}:{verse}')
    return _CANON.getChapter() == chapter and _CANON.getVerse() == verse


def _inline(text, bad_refs):
    """One paragraph's inner markup → the peek's markup."""
    def ref(m):
        refs = osis_refs(m.group(1))
        shown = m.group(2)
        if not refs or not all(map(_exists, refs)):
            # A link to a verse no Bible has (the release's "Ps 17:98") keeps
            # its words and loses the link.
            bad_refs.append(m.group(1))
            return shown
        return ('<reference osisRef="'
                + ' '.join(f'Bible:{r}' for r in refs) + f'">{shown}</reference>')
    text = _BREF.sub(ref, text)
    text = _ITEM_LINK.sub(r'\1', text)
    text = re.sub(r'<span class="(?:ital)">(.*?)</span>', r'<i>\1</i>', text, flags=re.S)
    text = re.sub(r'<span class="bold">(.*?)</span>', r'<b>\1</b>', text, flags=re.S)
    # Small capitals stand for capitals: the divine name (LORD for YHWH),
    # Bible versions (NLT, KJV), headword tails (P + ERSON). The peek has
    # no small capitals, so they are written as capitals.
    text = re.sub(r'<span class="(?:sc|lc|divine-name)">(.*?)</span>',
                  lambda m: m.group(1).upper(), text, flags=re.S)
    # Hebrew, Greek, eras: the words, unmarked.
    text = re.sub(r'<span class="[^"]*">(.*?)</span>', r'\1', text, flags=re.S)
    text = re.sub(r'<tab\s*/>', ' ', text)
    text = re.sub(r'<(?!/?(?:i|b|reference)\b)[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def render(body, parts, bad_refs, missing, depth=0):
    """An item's <body> → the module's markup."""
    out = []
    # A body paragraph is a bare <p>; the special ones carry a class, and
    # a heading an id after it.
    for m in re.finditer(r'<p(?: class="([^"]*)")?[^>]*>(.*?)</p>|<table>(.*?)</table>|'
                         + _INCLUDE.pattern, body, re.S):
        if m.group(2) is not None:
            cls, inner = m.group(1) or '', _inline(m.group(2), bad_refs)
            if not inner or cls in ('h1', 'artfile', 'caption-head', 'caption-text'):
                continue
            if cls.startswith(('h2', 'h3', 'h4', 'box-h2')):
                out.append(f'<h3>{inner}</h3>')
            else:
                out.append(f'<p>{inner}</p>')
        elif m.group(3) is not None:
            for row in re.findall(r'<tr>(.*?)</tr>', m.group(3), re.S):
                cells = [_inline(c, bad_refs)
                         for c in re.findall(r'<td>(.*?)</td>', row, re.S)]
                cells = [c for c in cells if c]
                if cells:
                    out.append('<p>' + ' · '.join(cells) + '</p>')
        else:
            kind, name = m.group(4), m.group(5)
            if kind not in ('Textboxes', 'Charts'):
                continue                      # maps (PDF) and pictures (absent)
            # The include spells a possessive "AbrahamSBosom" where the box
            # is named "AbrahamsBosom": matched without case or punctuation.
            part = parts.get((kind, _norm(name)))
            if part is None:
                missing.append(f'{kind}/{name}')
                continue
            if depth < 2:
                out.append(f'<h3>{_inline(part[0], bad_refs)}</h3>')
                out.append(render(part[1], parts, bad_refs, missing, depth + 1))
    return ''.join(out)


def _norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _key(title):
    """'Abel (Person)' → 'ABEL'; 'Aaron’s Rod*' → 'AARON’S ROD'."""
    t = html.unescape(re.sub(r'<[^>]+>', '', title))
    t = re.sub(r'\s*\([^)]*\)\s*', ' ', t).replace('*', '')
    return re.sub(r'\s+', ' ', t).strip().upper()


def load(src):
    """([(name, title, body)] of articles, {(kind, name): (title, body)})."""
    def items(path):
        return _ITEM.findall(open(path, encoding='utf-8').read())
    articles = []
    for f in sorted(os.listdir(os.path.join(src, 'Articles'))):
        for typ, name, title, body in items(os.path.join(src, 'Articles', f)):
            if typ == 'Article':
                articles.append((name, title, body))
    parts = {}
    for kind in ('Textboxes', 'Charts'):
        for typ, name, title, body in items(os.path.join(src, kind, f'{kind}.xml')):
            parts[(kind, _norm(name))] = (title, body)
    return articles, parts


def _words(markup):
    """The letters and digits of a text: tags split "Modern ." into two words
    in the source and not in the build, so words are the wrong measure."""
    return len(re.sub(r'\W', '', re.sub(r'<[^>]+>', ' ', html.unescape(markup))))


def build_entries(articles, parts):
    """{key: markup}, and what the validator needs to see."""
    groups: dict[str, list] = {}
    for name, title, body in articles:
        groups.setdefault(_key(title), []).append((name, title, body))
    entries, bad_refs, missing, empty, short = {}, [], [], [], []
    for key, members in groups.items():
        chunks = []
        # The peek titles the entry with the word and strips that word from
        # the front of the text, so "<h3>Abel (Person)</h3>" came out as
        # "(Person)" run into the first line. A joined entry gives each part
        # only its sense, "Person", "Place"; a part with none ("Sin", beside
        # "Sin (Place)") is the main article and goes first, unheaded.
        members = sorted(members, key=lambda m: '(' in m[1])
        for name, title, body in members:
            text = render(body, parts, bad_refs, missing)
            if not text:
                empty.append(name)
                continue
            # Every word of the source must arrive, less the headword line,
            # the picture and map captions left out, and the included boxes
            # counted here on their own (so the build cannot lose text again
            # the way bare <p> paragraphs once were).
            dropped = re.sub(r'<p class="(?:h1|artfile|caption-head|caption-text)">'
                             r'.*?</p>|<include_items[^>]*/>', '', body, flags=re.S)
            if _words(text) < _words(dropped):
                short.append((name, _words(dropped), _words(text)))
            sense = re.search(r'\(([^)]*)\)', title)
            if len(members) > 1 and sense:
                shown = html.unescape(sense.group(1)).replace('*', '').strip()
                text = f'<h3>{shown}</h3>' + text
            chunks.append(text)
        if chunks:
            entries[key] = ''.join(chunks)
    return entries, {'bad_refs': bad_refs, 'missing': missing, 'empty': empty,
                     'short': short, 'groups': len(groups)}


CONF = """[{module}]
Description=Tyndale Open Bible Dictionary
DataPath=./modules/lexdict/zld/{lower}/{lower}
ModDrv=zLD
SourceType=OSIS
Encoding=UTF-8
CompressType=ZIP
BlockCount=30
Lang=en
Version=1.0
About=Articles on the people, places and terms of the Bible, on the books of \\
the Bible, and on the cultural setting and theology of Scripture.\\par\\par \\
Adapted from Tyndale Open Bible Dictionary. The original work by Tyndale \\
House Publishers is available for free at http://www.tyndaleopenresources.com. \\
Copyright (C) 2023 by Tyndale House Publishers, licensed CC BY-SA 4.0.\\par\\par \\
Changes: the asterisk marking terms not in the NLT dropped from headwords; \\
articles of the same name (as Abel, person and place) joined under one \\
headword; text boxes and charts set inside their articles, charts row by \\
row; maps and pictures left out; links to other articles kept as text.
DistributionLicense=Creative Commons: BY-SA 4.0
Copyright=Copyright (C) 2023 by Tyndale House Publishers. Licensed CC BY-SA 4.0.
TextSource=https://tyndaleopenresources.com
LCSH=Bible--Dictionaries.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='the unzipped release')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    articles, parts = load(args.src)
    entries, report = build_entries(articles, parts)
    print(f'{len(articles)} articles -> {len(entries)} keys '
          f'({report["groups"]} headwords); {len(parts)} boxes and charts')
    print(f'unreadable verse links: {len(report["bad_refs"])} '
          f'{report["bad_refs"][:10]}')
    print(f'missing includes: {report["missing"][:10]}; '
          f'empty articles: {report["empty"][:10]}; '
          f'articles short of their source: {len(report["short"])} '
          f'{report["short"][:5]}')

    work = os.path.join(args.out, '_work')
    lower = MODULE.lower()
    datadir = os.path.join(work, 'modules', 'lexdict', 'zld', lower)
    os.makedirs(datadir, exist_ok=True)
    os.makedirs(os.path.join(work, 'mods.d'), exist_ok=True)

    # imp2ld does not sort; SWORD binary-searches the index.
    imp = os.path.join(args.out, f'{MODULE}.imp')
    with open(imp, 'w', encoding='utf-8') as fh:
        for k in sorted(entries):
            fh.write(f'$$${k}\n{entries[k]}\n')
    # -P: no Strong's-number padding of keys.
    r = subprocess.run(['imp2ld', imp, '-o', os.path.join(datadir, lower),
                        '-z', 'z', '-4', '-b', '30', '-P'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('imp2ld failed:', (r.stderr or r.stdout)[-400:])
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
    return 0 if not (report['missing'] or report['empty']
                     or report['short']) else 2


if __name__ == '__main__':
    sys.exit(main())
