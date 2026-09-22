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

**Word links.** Russian inflects and the articles are keyed on dictionary
forms, so a double-click on `спросил` or `иисуса` found nothing: the forms
alone answered 9.6% of John. With `--twl`, Door43's Translation Word Links
(`ru_twl`, CC BY-SA 4.0) go in beside the data as `links.tsv.gz`: for each
verse, which Strong's number is which article. A link names the Greek or
Hebrew word, so it is kept only where that exact word, found in the
interlinear data, carries the number; a link that places no word, or a
number two articles claim in one verse, is dropped. A wrong article is
worse than none. The app reads it through `word_links.py` for any tagged
Russian Bible.

Usage:  python3 tools/build_russian_tw_dict.py --src DIR --out DIR
            [--twl DIR --interlinear DIR]
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import os
import re
import sqlite3
import unicodedata
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


LINKS_FILE = 'links.tsv.gz'


def _plain(word: str) -> str:
    """Greek or Hebrew with every mark, joiner and point stripped, so a
    link's `OrigWords` meets the interlinear's `surface` letter for letter."""
    word = unicodedata.normalize('NFD', word)
    word = ''.join(c for c in word if not unicodedata.combining(c))
    return re.sub(r'[^\w]', '', word).lower().replace('ς', 'σ')


def _number(strong: str) -> str:
    return re.sub(r'^([GH])0*', r'\1', strong)


def build_links(twl_dir: str, interlinear_dir: str,
                key_of: dict[str, str]) -> tuple[list[tuple], dict]:
    """(book, chapter, verse, Strong's, key) for every link that places a
    word. `key_of` maps an article id (`kt/god`) to the key its body is
    stored under."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    from ebible_bridge import _BOOK
    dbs = {t: sqlite3.connect(os.path.join(interlinear_dir,
                                           f'interlinear_{t}.sqlite'))
           for t in ('greek', 'hebrew')}
    found: dict[tuple, set] = collections.defaultdict(set)
    stats = collections.Counter()
    for name in sorted(os.listdir(twl_dir)):
        m = re.match(r'twl_(\w+)\.tsv$', name)
        if not m or m.group(1) not in _BOOK:
            continue
        book = _BOOK[m.group(1)]
        testament = 'greek' if list(_BOOK).index(m.group(1)) >= 39 else 'hebrew'
        db = dbs[testament]
        with open(os.path.join(twl_dir, name), encoding='utf-8') as fh:
            for row in csv.DictReader(fh, delimiter='\t'):
                ref = re.fullmatch(r'(\d+):(\d+)', row['Reference'] or '')
                article = (row['TWLink'] or '').split('/dict/bible/')[-1]
                if ref is None or article not in key_of:
                    stats['unplaceable'] += 1
                    continue
                chapter, verse = int(ref.group(1)), int(ref.group(2))
                want = {_plain(w) for w in row['OrigWords'].split()}
                # Same verse first; then either side of it, because the
                # links count a psalm's title as verse 1 where the
                # interlinear, like the KJV, numbers it 0. Only an exact
                # word match is kept, so a neighbour cannot mislead.
                for v in (verse, verse - 1, verse + 1):
                    numbers = {_number(s) for surface, s in db.execute(
                        'SELECT surface, strongs FROM words WHERE book=? '
                        'AND chapter=? AND verse=? AND in_stream=1',
                        (book, chapter, v))
                        if _plain(surface) in want and s and s != 'G3588'}
                    if numbers:
                        for n in numbers:
                            found[(book, chapter, v, n)].add(article)
                        stats['placed' if v == verse else 'shifted'] += 1
                        break
                else:
                    stats['no word'] += 1
    rows = []
    for (book, chapter, verse, n), articles in sorted(found.items()):
        if len(articles) == 1:
            rows.append((book, chapter, verse, n, key_of[articles.pop()]))
        else:
            stats['two articles'] += 1
    return rows, stats


CONF = """[{module}]
Description=Библейский словарь — термины, имена и понятия
DataPath=./modules/lexdict/zld/{lower}/{lower}
ModDrv=zLD
SourceType=OSIS
Encoding=UTF-8
CompressType=ZIP
BlockCount=30
Lang=ru
Version=1.1
About=Словарь библейских слов: ключевые термины, имена и понятия Писания. \\
Каждая статья даёт определение или факты, замечания о переводе и номера \\
Стронга.\\par\\par \\
Источник — Translation Words проекта unfoldingWord / Door43 World Missions \\
Community, русская версия (`ru_tw`), и связи слов со стихами из Translation \\
Word Links (`ru_twl`), доступные по лицензии Creative Commons \\
«С указанием авторства — На тех же условиях» 4.0.
DistributionLicense=Creative Commons: BY-SA 4.0
Copyright=Door43 World Missions Community. Licensed CC BY-SA 4.0.
TextSource=https://git.door43.org/ru_gl/ru_tw
LCSH=Bible--Dictionaries.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='dir holding kt/ names/ other/')
    ap.add_argument('--out', required=True)
    ap.add_argument('--twl', help='dir holding ru_twl twl_*.tsv')
    ap.add_argument('--interlinear', help='dir holding interlinear_*.sqlite',
                    default=os.path.expanduser(
                        '~/.local/share/bible-reader/open_data'))
    args = ap.parse_args()

    entries: dict[str, str] = {}
    owner: dict[str, str] = {}
    heads_of: dict[str, list[str]] = {}
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
            heads_of[f'{sub}/{name[:-3]}'] = [_key(h) for h in heads]
            for h in heads:
                k = _key(h)
                if k in entries:
                    clashes += 1
                    if len(body) <= len(entries[k]):
                        continue
                entries[k] = body
                owner[k] = f'{sub}/{name[:-3]}'

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

    if args.twl:
        # An article is reached under its first heading that still holds
        # its own body: "СВЕТ", not "ОСВЕЩАТЬ", for the light article.
        key_of = {a: next(k for k in heads if owner.get(k) == a)
                  for a, heads in heads_of.items()
                  if any(owner.get(k) == a for k in heads)}
        rows, stats = build_links(args.twl, args.interlinear, key_of)
        with gzip.open(os.path.join(datadir, LINKS_FILE), 'wt',
                       encoding='utf-8') as fh:
            for row in rows:
                fh.write('\t'.join(str(x) for x in row) + '\n')
        print(f'{len(rows)} word links ({dict(stats)})')

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
