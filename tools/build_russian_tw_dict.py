#!/usr/bin/env python3
"""Build a Russian Bible dictionary from Door43's Translation Words (`ru_tw`).

Why this exists. Russian had no dictionary of any kind — CrossWire's 426
modules hold ten Russian ones and not a single general dictionary, so
double-clicking a word, one of the three gestures onboarding teaches, answered
a Russian reader with «Словари не установлены». `ru_tw` is 1,018 curated
articles on biblical terms, names and concepts, CC BY-SA 4.0, so unlike the
Spanish case nothing has to be mined out of Wiktionary: the prose is already
written and already about the Bible.

Entries carry <b>, <i> and <br /> only. The peek renders them through
`pane._html_to_markup`, which keeps those and strips every other tag while
keeping its content — a `<reference osisRef=…>` would survive as plain text
but never become a link, because that only happens on the commentary path.
The break must be a tag: imp2ld joins an entry's lines, so a body written with
newlines arrives as one wall of text.

Usage:  python3 tools/build_russian_tw_dict.py --src DIR --out DIR
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import zipfile

MODULE = 'RussianBibleWords'
BR = '<br />'
PARA = '<br /><br />'

#: Sections worth carrying into a peek 360px wide. The reference lists
#: ("Ссылки на библейский текст", "Примеры из Библейских историй") are dozens
#: of citations that cannot be clicked here, so they would be pure ballast.
_KEEP = ('Определение', 'Факты', 'Варианты перевода', 'Данные о слове')

_TITLE = re.compile(r'^#\s+(.+?)\s*$', re.M)
_H2 = re.compile(r'^##\s+(.+?):?\s*$', re.M)
_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_STRONG = re.compile(r'\b([GH])(\d+)\b')


def normalise_strong(letter: str, digits: str) -> str:
    """`G21430` -> `G2143`, `H0087` -> `H87`.

    Door43 writes NT numbers as five digits with a sub-index and OT numbers
    zero-padded; a SWORD Strong's lexicon is keyed on neither. Same rule as
    tools/build_russian_open_bible.py, and wrong here means the numbers print
    and the lexicon finds none of them.
    """
    if letter == 'G' and len(digits) == 5:
        digits = digits[:4]
    return f'{letter}{int(digits)}'


def _clean(text: str) -> str:
    text = _LINK.sub(r'\1', text)                 # keep a link's words
    text = re.sub(r'rc://[^\s)]+', '', text)
    text = re.sub(r'[*_`]', '', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


def render(md: str) -> tuple[list[str], str]:
    """(headwords, entry body) for one article."""
    m = _TITLE.search(md)
    if not m:
        return [], ''
    heads = [h.strip() for h in m.group(1).split(',') if h.strip()]

    out: list[str] = []
    marks = list(_H2.finditer(md))
    for i, sec in enumerate(marks):
        name = sec.group(1).strip().rstrip(':')
        if not any(name.startswith(k) for k in _KEEP):
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        body = md[sec.end():end]
        lines = []
        for raw in body.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            bullet = raw.startswith(('*', '-'))
            txt = _clean(raw.lstrip('*- '))
            if not txt:
                continue
            if 'Номера Стронга' in txt:
                nums = ', '.join(normalise_strong(a, b)
                                 for a, b in _STRONG.findall(txt))
                txt = f'Номера Стронга: {nums}' if nums else ''
                if not txt:
                    continue
            lines.append(('• ' + txt) if bullet else txt)
        if lines:
            out.append(f'<b>{name}</b>{BR}' + BR.join(lines))
    return heads, PARA.join(out)


def _key(word: str) -> str:
    return word.upper().strip()


CONF = """[{module}]
Description=Библейский словарь — термины, имена и понятия
DataPath=./modules/lexdict/zld/{lower}/{lower}
ModDrv=zLD
SourceType=OSIS
Encoding=UTF-8
CompressType=ZIP
BlockCount=30
Lang=ru
Version=1.0
About=Словарь библейских слов: ключевые термины, имена и понятия Писания. \\
Каждая статья даёт определение или факты, замечания о переводе и номера \\
Стронга.\\par\\par \\
Источник — Translation Words проекта unfoldingWord / Door43 World Missions \\
Community, русская версия (`ru_tw`), доступная по лицензии Creative Commons \\
«С указанием авторства — На тех же условиях» 4.0.
DistributionLicense=Creative Commons: BY-SA 4.0
Copyright=Door43 World Missions Community. Licensed CC BY-SA 4.0.
TextSource=https://git.door43.org/Door43-Catalog/ru_tw
LCSH=Bible--Dictionaries.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='dir holding kt/ names/ other/')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    entries: dict[str, str] = {}
    articles = clashes = 0
    for sub in ('kt', 'names', 'other'):
        d = os.path.join(args.src, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith('.md'):
                continue
            heads, body = render(open(os.path.join(d, name),
                                     encoding='utf-8').read())
            if not heads or not body:
                continue
            articles += 1
            for h in heads:
                k = _key(h)
                if k in entries:
                    clashes += 1
                    if len(body) <= len(entries[k]):
                        continue
                entries[k] = body

    # Ё/Е bridge, the Russian counterpart of the Spanish accent alias: printed
    # Russian very often writes `е` where the dictionary form has `ё`, and a
    # lookup cannot invent a diaeresis the page does not carry.
    aliases = 0
    for k in list(entries):
        plain = k.replace('Ё', 'Е')
        if plain != k and plain not in entries:
            entries[plain] = entries[k]
            aliases += 1

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, '_work')
    lower = MODULE.lower()
    datadir = os.path.join(work, 'modules', 'lexdict', 'zld', lower)
    os.makedirs(datadir, exist_ok=True)
    os.makedirs(os.path.join(work, 'mods.d'), exist_ok=True)

    # imp2ld does not sort; SWORD binary-searches the index. Easton's own
    # changelog records two releases spent fixing out-of-order entries.
    imp = os.path.join(work, f'{MODULE}.imp')
    with open(imp, 'w', encoding='utf-8') as fh:
        for k in sorted(entries):
            fh.write(f'$$${k}\n{entries[k]}\n')
    print(f'{articles} articles -> {len(entries)} keys '
          f'({aliases} ё/е aliases, {clashes} headword clashes)')

    # `-P` matters: without it imp2ld pads keys that look like Strong's
    # numbers, and this dictionary is keyed on Russian words, not numbers.
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
                if p == imp:
                    continue
                zf.write(p, os.path.relpath(p, work))
    print(f'zip {os.path.getsize(zip_path)/1e6:.2f} MB -> {zip_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
