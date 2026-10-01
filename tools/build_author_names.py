#!/usr/bin/env python3
"""Build data/author_names/{es,ru}.tsv: the name a Spanish or Russian reader
knows each Voices of the Church author by.

    tools/build_author_names.py --catena PATH/catena.db [--cache FILE]

Every author in the pack carries the English Wikipedia page the pack took
them from. The name here is the Spanish or Russian label of that page's
Wikidata item (CC0), so a Father reads as his own language's reference works
name him: Agustín de Hipona, Иоанн Златоуст. An author whose item has no label
in a language is left out of that file, and the app keeps the English.

The suffixes name a second author in a short form ("as quoted by Aquinas"):
such a form is given the label of the one pack author whose name it is (in
any case), ends with, or begins as "FORM of …", and is left out when that is
not exactly one.

The fetched labels are cached (--cache, in the temp dir by default) so a
rebuild needs no network.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'author_names')
LANGS = ('es', 'ru')
WIKIPEDIA = 'https://en.wikipedia.org/w/api.php'
WIKIDATA = 'https://www.wikidata.org/w/api.php'
AGENT = 'Scriptura build tool (https://github.com/andresmessina-SDG/scriptura)'

#: Authors whose Wikidata item is labelled in English by another spelling or
#: title of the same person, read and kept by hand. Any other item whose
#: English label shares no word with the pack's name is taken to be the wrong
#: page (one pack link lands on a web-server index, another on a book) and
#: its labels are not used.
SAME_PERSON = {
    'Adamnán of Iona',              # Adomnán
    'Callistus I of Rome',          # Callixtus I
    'Leo the Great',                # Leo I
    'Oresiesis-Heru-sa Ast',        # Orsisius
    'Shenoute the Archimandrite',   # Shenute
    'Theodorus of Tabennese',       # Theodoros of Tabenna
}

#: Labels read by hand on 2026-10-01 and kept out: each is the wrong language,
#: names someone else as well, or drops what tells two authors apart.
REJECT = {
    'Council of Carthage of 411': {'es'},      # plural, and no year
    'Council of Carthage of 419': {'es'},
    'Lateran Council of 649': {'es', 'ru'},    # no year: there are several
    'Epiphanius Scholasticus': {'es'},         # Greek spelling
    'Haimo of Auxerre': {'es'},                # French
    'Nicholas of Gorran': {'es'},              # not Spanish
    'Peter Olivi': {'es'},                     # Latin
    'Phileas of Thmuis': {'es'},               # English, and two martyrs
    'Primasius of Hadrumetum': {'es'},         # drops the see
    'Papias the Lexicographer': {'es'},        # reads as Papias of Hierapolis
    'Pseudo-Cyprian': {'es'},                  # French
    'Pseudo-Macarius': {'es'},                 # French
    'Theophanes of Nicaea': {'ru'},            # both Graptoi brothers
    'Venerable Barsanuphius and John the Prophet': {'es', 'ru'},  # no John
    'Lucifer of Cagliari': {'ru'},             # "Saint Lucifer"
    'Heracleon': {'ru'},                       # carries "(philosopher)"
}

#: The suffix forms the app translates; the name is group 1.
SUFFIX = re.compile(r'^\(as quoted by ([^,()]+?)(?:, AD \d+)?\)$')


def _title(url):
    path = urllib.parse.urlparse(url).path
    return urllib.parse.unquote(path.rsplit('/wiki/', 1)[-1]).replace('_', ' ')


def _get(url, params):
    req = urllib.request.Request(f'{url}?{urllib.parse.urlencode(params)}',
                                 headers={'User-Agent': AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _fetch(titles):
    """enwiki title → {lang: label}. Wikipedia resolves the title, redirects
    and all, to its Wikidata item; Wikidata's own title lookup misses pages
    the pack names by a redirect ("Pope Clement I")."""
    item = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = _get(WIKIPEDIA, {
            'action': 'query', 'titles': '|'.join(batch), 'redirects': 1,
            'prop': 'pageprops', 'ppprop': 'wikibase_item', 'format': 'json'})
        q = data.get('query', {})
        hops = {n['from']: n['to'] for n in
                q.get('normalized', []) + q.get('redirects', [])}
        by_title = {p['title']: p.get('pageprops', {}).get('wikibase_item')
                    for p in q.get('pages', {}).values()}
        for t in batch:
            seen = t
            while seen in hops:
                seen = hops[seen]
            if by_title.get(seen):
                item[t] = by_title[seen]
    labels = {}
    ids = sorted(set(item.values()))
    for i in range(0, len(ids), 50):
        data = _get(WIKIDATA, {
            'action': 'wbgetentities', 'ids': '|'.join(ids[i:i + 50]),
            'props': 'labels', 'languages': '|'.join(('en',) + LANGS),
            'format': 'json'})
        for qid, ent in data.get('entities', {}).items():
            labels[qid] = {k: v['value']
                           for k, v in ent.get('labels', {}).items()}
    return {t: labels.get(q, {}) for t, q in item.items()}


def _clean(label):
    """No soft hyphens (one Russian label is full of them), and a capital
    to begin: a label opens the byline."""
    label = label.replace('\u00ad', '')
    return label[:1].upper() + label[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catena', required=True)
    ap.add_argument('--cache', default=os.path.join(
        tempfile.gettempdir(), 'scriptura-author-labels.json'))
    args = ap.parse_args()

    conn = sqlite3.connect(f'file:{args.catena}?mode=ro', uri=True)
    authors = dict(conn.execute(
        "SELECT author, MIN(wiki_url) FROM quotes "
        "WHERE wiki_url IS NOT NULL AND wiki_url != '' GROUP BY author"))
    suffixes = [s for (s,) in conn.execute(
        'SELECT DISTINCT author_suffix FROM quotes '
        'WHERE author_suffix IS NOT NULL')]

    if os.path.exists(args.cache):
        with open(args.cache, encoding='utf-8') as f:
            labels = json.load(f)
    else:
        labels = _fetch(sorted({_title(u) for u in authors.values()}))
        with open(args.cache, 'w', encoding='utf-8') as f:
            json.dump(labels, f, ensure_ascii=False, indent=1)

    def words(text):
        return set(re.findall(r'[a-z]{4,}', text.lower()))

    # A Bible book quoted as a voice is named by the app's own book names.
    sys.path.insert(0, ROOT)
    import sword_bridge
    books = set(sword_bridge._ALL_BOOKS) | set(sword_bridge.DEUTEROCANON)
    names = {}
    for a, u in authors.items():
        if a in books:
            continue
        lab = labels.get(_title(u), {})
        if lab and a not in SAME_PERSON and not words(a) & words(lab.get('en', '')):
            print(f'{a}: page labelled {lab.get("en")!r}, not used',
                  file=sys.stderr)
            lab = {}
        # A pseudonymous author linked to the real one's page would be
        # labelled as the real one: Pseudo-Athanasius as Athanasius.
        if a.startswith('Pseudo-'):
            lab = {k: v for k, v in lab.items()
                   if k == 'en' or re.search('seudo|севдо', v, re.I)}
        lab = {k: _clean(v) for k, v in lab.items()
               if k not in REJECT.get(a, ())}
        names[a] = lab
    short = set()
    for s in suffixes:
        m = SUFFIX.match(s)
        if m and m.group(1) not in names:
            short.add(m.group(1))
    for form in sorted(short):
        f = form.lower()
        whose = [a for a in names if a.lower() == f
                 or a.lower().endswith(' ' + f) or a.lower().startswith(f + ' of ')]
        if len(whose) == 1:
            names[form] = names[whose[0]]
        else:
            print(f'suffix name {form!r}: {len(whose)} matches, kept English',
                  file=sys.stderr)

    os.makedirs(OUT, exist_ok=True)
    for lang in LANGS:
        rows = sorted((a, lab[lang]) for a, lab in names.items()
                      if lab.get(lang) and lab[lang] != a)
        missing = sorted(a for a, lab in names.items() if not lab.get(lang))
        with open(os.path.join(OUT, f'{lang}.tsv'), 'w', encoding='utf-8') as f:
            f.write(f'# Voices of the Church authors in {lang}: the Wikidata '
                    'label (CC0) of each one\'s\n# Wikipedia page. Built by '
                    'tools/build_author_names.py; do not edit.\n')
            for a, lab in rows:
                f.write(f'{a}\t{lab}\n')
        print(f'{lang}: {len(rows)} names, {len(missing)} kept English',
              file=sys.stderr)
        for a in missing:
            print(f'  {lang} no label: {a}', file=sys.stderr)


if __name__ == '__main__':
    main()
