#!/usr/bin/env python3
"""Build data/renderings/{es,ru}.tsv: how a Bible in the reader's language
renders each Strong's number.

A Spanish or Russian reader gets the English Strong's entry and, under it,
one line naming a Bible and the words it uses for that word:
"Reina-Valera 1909: amor, caridad". It is not a definition — no open Spanish
or Russian lexicon exists (CONTENT_I18N_RESEARCH.md §2) — it is the usage
list Strong's own entries end with, counted from a tagged Bible.

    tools/build_renderings.py --rv1909 DIR --rlob DIR

  --rv1909  the unzipped USFM of eBible's Reina-Valera 1909, Strong's-tagged,
            Public Domain: https://ebible.org/Scriptures/spaRV1909_usfm.zip
  --rlob    the unzipped Door43 ru_gl/ru_rlob, aligned, CC BY-SA 4.0:
            https://git.door43.org/ru_gl/ru_rlob/archive/master.zip

Russian needs `pymorphy3` (MIT) to fold case forms to their dictionary form,
at build time only; the app reads the TSV and never imports it.
"""
import argparse
import collections
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'renderings')

#: At most this many renderings per number, and each must carry at least this
#: share of the number's occurrences — a word the Bible used once in two
#: hundred is noise beside the ones it uses.
MOST = 3
SHARE = 0.08

#: Words that ride along inside an aligned span but are not the rendering:
#: articles, prepositions, conjunctions, possessives. Only stripped from the
#: EDGES of a span of two or more words, so "de tal manera" keeps its inner
#: words, and a one-word span is kept whole: "el" IS how the Reina-Valera
#: renders the Greek article, and "мой" how the Russian renders "my".
STOP = {
    'es': {'el', 'la', 'los', 'las', 'lo', 'un', 'una', 'unos', 'unas',
           'de', 'del', 'a', 'á', 'al', 'en', 'y', 'e', 'o', 'por', 'para',
           'con', 'sin', 'su', 'sus', 'mi', 'mis', 'tu', 'tus', 'que', 'se'},
    'ru': {'и', 'а', 'но', 'в', 'во', 'на', 'с', 'со', 'к', 'ко', 'по', 'о',
           'об', 'от', 'до', 'из', 'у', 'за', 'для', 'при', 'не', 'же',
           'свой', 'мой', 'твой', 'его', 'её', 'ее', 'их', 'наш', 'ваш'},
}

_STRONG = re.compile(r'([GH])0*(\d+)')


def strong_key(raw):
    """'G0746' / 'strong:H0430' / 'G37540' (UGNT's five digits) → 'G746'."""
    m = _STRONG.search(raw)
    if not m:
        return None
    letter, digits = m.group(1), m.group(2)
    n = int(digits)
    if letter == 'G' and len(m.group(0)) - 1 == 5 and n % 10 == 0:
        n //= 10
    return f'{letter}{n}'


def stop_in(lang):
    """The test for a function word: membership in STOP."""
    return lambda word: word.lower() in STOP[lang]


def clean(words, is_stop):
    """A span's words → the rendering, edges stripped of function words."""
    toks = [re.sub(r'[^\w\-’]', '', w) for w in words]
    toks = [t for t in toks if t]
    if len(toks) == 1:
        return toks[0]
    while toks and is_stop(toks[0]):
        toks.pop(0)
    while toks and is_stop(toks[-1]):
        toks.pop()
    return ' '.join(toks)


#: Between two words, any of these means the second opens a sentence, a verse
#: or a paragraph — where every word has a capital, name or not.
_OPENS = re.compile(r'[.!?¿¡]|\\[vcpq]\b|\\q\d')


def _initial(between):
    return bool(_OPENS.search(between))


def parse_rv1909(text):
    """Yield (strong, words, opens_sentence) from eBible USFM:
    \\w words|strong="G0746"\\w*. Footnotes are dropped first; their \\w
    markers are not the verse."""
    text = re.sub(r'\\f .*?\\f\*', '', text, flags=re.S)
    last = 0
    for m in re.finditer(r'\\\+?w ([^|\\]+)\|([^\\]*)\\\+?w\*', text):
        initial = last == 0 or _initial(text[last:m.start()])
        last = m.end()
        st = re.search(r'strong="([^"]+)"', m.group(2))
        if not st:
            continue
        for raw in re.split(r'[,\s]+', st.group(1)):
            key = strong_key(raw)
            if key:
                yield key, m.group(1).split(), initial


def parse_aligned(text):
    """Yield (strong, words, opens_sentence) from Door43 aligned USFM.
    Alignments nest — two Greek words to one Russian phrase open two
    \\zaln-s before the words — so every word credits every alignment open
    around it."""
    stack, spans, last = [], [], 0
    for m in re.finditer(r'\\zaln-s \|([^\\]*)\\\*|\\zaln-e\\\*|\\w ([^|\\]+)\|', text):
        if m.group(1) is not None:
            s = re.search(r'x-strong="([^"]+)"', m.group(1))
            stack.append([strong_key(s.group(1)) if s else None, [], None])
        elif m.group(2) is not None:
            initial = last == 0 or _initial(
                re.sub(r'\\zaln-[se][^*]*\*|\\w\*|\|[^\\]*', '', text[last:m.start()]))
            last = m.end()
            for entry in stack:
                if entry[2] is None:
                    entry[2] = initial
                entry[1].append(m.group(2))
        elif stack:
            spans.append(stack.pop())
    for key, words, initial in spans:
        if key and words:
            yield key, words, bool(initial)


def tally(spans, is_stop, lemma=None):
    """{strong: Counter(rendering)}, {strong: Counter(capitalised?)} and
    {strong: spans that were nothing but function words}. `lemma` takes the
    rendering's words and gives back its dictionary form. A capital only
    counts mid-sentence: at a sentence's start it says nothing."""
    counts = collections.defaultdict(collections.Counter)
    caps = collections.defaultdict(collections.Counter)
    bare = collections.Counter()
    for key, words, initial in spans:
        r = clean(words, is_stop)
        if not r:
            bare[key] += 1
            continue
        if not initial:
            caps[key][r[:1].isupper()] += 1
        r = r.lower()
        if lemma is not None:
            r = lemma(r.split())
        counts[key][r] += 1
    return counts, caps, bare


def pick(counts, caps, bare=0):
    """The renderings worth a line, most used first; a name keeps its capital
    when the Bible capitalises it more often than not.

    A word whose spans are mostly function words and nothing else gets no
    line: what is left after them is its rare exception, which would mislead
    more than it tells."""
    total = sum(counts.values())
    if bare > total:
        return []
    keep = [(r, n) for r, n in counts.most_common()
            if n / total >= SHARE or n == total][:MOST]
    upper = caps[True] > caps[False]
    return [r[:1].upper() + r[1:] if upper else r for r, _n in keep]


def russian_stop(morph):
    """A Russian function word, judged by what it IS rather than a list of
    spellings: a list of dictionary forms missed «моего» in «отца моего». A
    preposition, conjunction or particle, a possessive, or a personal pronoun
    ("его" in «дом его») — and anything in STOP."""
    listed = stop_in('ru')

    def is_stop(word):
        if listed(word):
            return True
        p = morph.parse(word.lower())[0]
        return (p.tag.POS in ('PREP', 'CONJ', 'PRCL', 'NPRO')
                or 'Apro' in p.tag)
    return is_stop


def russian_lemma(morph):
    """words → the phrase in its dictionary form, agreement kept.

    One word folds to its lemma, but only when the analyser KNOWS the word: a
    name it has never seen gets guessed at and cut ("Яхве" → "Яхв"), so an
    unknown word stays as the Bible spells it. In a phrase the noun folds and
    the adjectives and participles follow its gender and number — folding each
    word alone gave "верный любовь" for «верной любви»."""
    def fold(words):
        parses = [morph.parse(w)[0] for w in words]
        if len(words) == 1:
            p = parses[0]
            return p.normal_form if p.is_known else words[0]
        noun = next((p for p in parses if p.tag.POS == 'NOUN' and p.is_known), None)
        if noun is None:
            return ' '.join(words)
        head = noun.inflect({'nomn'}) or noun
        out = []
        for w, p in zip(words, parses):
            if p is noun:
                out.append(head.word)
            elif p.tag.POS in ('ADJF', 'PRTF') and p.is_known:
                want = {'nomn', head.tag.number or 'sing'}
                if head.tag.number != 'plur' and head.tag.gender:
                    want.add(head.tag.gender)
                q = p.inflect(want)
                out.append(q.word if q else w)
            else:
                out.append(w)
        return ' '.join(out)
    cache = {}

    def lemma(words):
        key = tuple(words)
        if key not in cache:
            cache[key] = fold(list(words))
        return cache[key]
    return lemma


def write(path, header, table):
    with open(path, 'w', encoding='utf-8') as f:
        for line in header:
            f.write(f'# {line}\n')
        for key in sorted(table, key=lambda k: (k[0], int(k[1:]))):
            if table[key]:
                f.write(f'{key}\t{" | ".join(table[key])}\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--rv1909', required=True)
    ap.add_argument('--rlob', required=True)
    args = ap.parse_args()

    def read(pattern):
        files = sorted(glob.glob(pattern, recursive=True))
        if not files:
            sys.exit(f'no USFM under {pattern}')
        return (open(f, encoding='utf-8').read() for f in files)

    os.makedirs(OUT, exist_ok=True)

    es, es_caps, es_bare = tally((p for t in read(os.path.join(args.rv1909, '**', '*.usfm'))
                         for p in parse_rv1909(t)), stop_in('es'))
    write(os.path.join(OUT, 'es.tsv'),
          ['How the Reina-Valera 1909 renders each Strong\'s number.',
           'Source: eBible.org spaRV1909, Strong\'s-tagged. Public Domain.',
           'Built by tools/build_renderings.py. Do not edit by hand.'],
          {k: pick(c, es_caps[k], es_bare[k]) for k, c in es.items()})

    import pymorphy3
    morph = pymorphy3.MorphAnalyzer()
    lemma = russian_lemma(morph)

    ru, ru_caps, ru_bare = tally((p for t in read(os.path.join(args.rlob, '**', '*.usfm'))
                         for p in parse_aligned(t)), russian_stop(morph), lemma)
    write(os.path.join(OUT, 'ru.tsv'),
          ['How the Russian Literal Open Bible renders each Strong\'s number,',
           'words folded to their dictionary form.',
           'Source: Door43 ru_gl/ru_rlob, aligned. CC BY-SA 4.0.',
           'This file is licensed CC BY-SA 4.0.',
           'Built by tools/build_renderings.py. Do not edit by hand.'],
          {k: pick(c, ru_caps[k], ru_bare[k]) for k, c in ru.items()})
    print(f'es {len(es)} numbers, ru {len(ru)} numbers → {OUT}')


if __name__ == '__main__':
    main()
