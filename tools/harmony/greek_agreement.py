"""Greek agreement between parallel passages (research doc §14).

Thresholds were fixed in the doc (§14.0) before this was first run.
Run from the repository root:  python3 -I tools/harmony/greek_agreement.py [--annotate]
Needs the Greek interlinear installed in the app (its TAGNT lemmas).
"""
import json
import os
import math
import random
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, ROOT)
from sword_bridge import verse_count  # noqa: E402
import paths  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'harmony', 'harmony.json')
DB = os.path.join(paths.open_data_dir(), 'interlinear_greek.sqlite')
NAME = {'Matt': 'Matthew', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John'}
GOSPELS = tuple(NAME)
CHAPTERS = {'Matt': 28, 'Mark': 16, 'Luke': 24, 'John': 21}
STOP_MORPH = ('T-', 'CONJ', 'PREP', 'P-', 'R-', 'D-', 'I-', 'X-', 'F-', 'PRT', 'COND')
random.seed(1)

data = json.load(open(OUT, encoding='utf-8'))

# ── Lemmas per verse ───────────────────────────────────────────────────────
db = sqlite3.connect(DB)
stream, other = defaultdict(list), defaultdict(list)
for book, c, v, morph, lemma, ins in db.execute(
        'select book, chapter, verse, morph, lemma, in_stream from words order by book, chapter, verse, pos'):
    if morph.startswith(STOP_MORPH) or not lemma:
        continue
    lemma = unicodedata.normalize('NFC', lemma)
    if lemma == 'εἰμί':
        continue
    (stream if ins else other)[(book, c, v)].append(lemma)
fallback = set()


def lemmas(book, c, v):
    key = (NAME.get(book, book), c, v)
    if stream.get(key):
        return stream[key]
    if other.get(key):
        fallback.add(key)
        return other[key]
    return []


df = Counter()
for key in set(stream) | set(other):
    for l in set(stream.get(key) or other.get(key)):
        df[l] += 1
N = len(set(stream) | set(other))


def idf(l):
    return math.log(N / (1 + df[l]))


def kjv(book, c):
    return verse_count(NAME[book], c, 'KJV')


def verses_of(span):
    b, (c, v), (c2, v2) = span['book'], span['start'], span['end']
    out = []
    while (c, v) <= (c2, v2):
        out.append((b, c, v))
        v += 1
        if v > kjv(b, c):
            c, v = c + 1, 1
    return out


def tokens(verses):
    return [l for vv in verses for l in lemmas(*vv)]


def score(a, b):
    """idf-weighted share of the smaller passage's content lemmas found in the other."""
    ca, cb = Counter(a), Counter(b)
    shared = sum(min(ca[l], cb[l]) * idf(l) for l in ca)
    small = min(sum(n * idf(l) for l, n in ca.items()), sum(n * idf(l) for l, n in cb.items()))
    return shared / small if small else 0.0


def underline_share(a, b):
    """Share of a's content words whose lemma b also has; and the share inside
    runs of two or more lemmas that b also has in a row."""
    if not a:
        return None, None
    sb = set(b)
    bigrams_b = set(zip(b, b[1:]))
    single = sum(1 for l in a if l in sb) / len(a)
    in_run = [False] * len(a)
    for i in range(len(a) - 1):
        if (a[i], a[i + 1]) in bigrams_b:
            in_run[i] = in_run[i + 1] = True
    return single, sum(in_run) / len(a)


# ── Robertson sections: verse → section, and each section's passages ──────
sec_of = defaultdict(set)
passages = {}
for s in data['sections']:
    per = defaultdict(list)
    for r in s['refs']:
        if r['book'] in GOSPELS:
            vs = verses_of(r)
            per[r['book']] += vs
            for v in vs:
                sec_of[v].add(s['id'])
    passages[s['id']] = dict(per)

# ── Baseline ───────────────────────────────────────────────────────────────
all_verses = {b: [(b, c, v) for c in range(1, CHAPTERS[b] + 1) for v in range(1, kjv(b, c) + 1)]
              for b in GOSPELS}


def random_passage(book, length):
    vs = all_verses[book]
    i = random.randrange(0, len(vs) - length)
    return vs[i:i + length]


def baseline(lengths, draws=2000):
    out = []
    while len(out) < draws:
        la, lb = random.choice(lengths)
        ba, bb = random.sample(GOSPELS, 2)
        pa, pb = random_passage(ba, la), random_passage(bb, lb)
        if {s for v in pa for s in sec_of[v]} & {s for v in pb for s in sec_of[v]}:
            continue
        out.append(score(tokens(pa), tokens(pb)))
    return sorted(out)


def pct(xs, p):
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


# ── Q1, Q2: same-event pairs ───────────────────────────────────────────────
same_event = []
for s in data['sections']:
    per = passages[s['id']]
    books = [b for b in GOSPELS if b in per]
    for i, a in enumerate(books):
        for b in books[i + 1:]:
            same_event.append((s['id'], a, b, per[a], per[b]))
base = baseline([(len(pa), len(pb)) for _, _, _, pa, pb in same_event])
chance = pct(base, 95)
print(f'Baseline: {len(base)} random pairs; median {statistics.median(base):.3f}, '
      f'95th percentile {chance:.3f}')

rows = []
for sid, a, b, pa, pb in same_event:
    ta, tb = tokens(pa), tokens(pb)
    rows.append((score(ta, tb), sid, a, b, len(pa), len(pb), ta, tb))
above = [r for r in rows if r[0] > chance]
q1 = len(above) / len(rows)
print(f'\nQ1 same-event pairs: {len(rows)}; above chance {len(above)} ({q1:.0%}); '
      f'median score {statistics.median(r[0] for r in rows):.3f}  '
      f"-> {'PASS' if q1 >= 0.80 else 'FAIL'} (threshold 80%)")
print('  by Gospel pair:', {f'{a}-{b}': f'{statistics.median(r[0] for r in rows if (r[2], r[3]) == (a, b)):.2f}'
                            f' (n={sum(1 for r in rows if (r[2], r[3]) == (a, b))})'
                            for a in GOSPELS for b in GOSPELS if GOSPELS.index(a) < GOSPELS.index(b)
                            and any((r[2], r[3]) == (a, b) for r in rows)})
print('  below chance:')
sections = {s['id']: s for s in data['sections']}
for sc, sid, a, b, la, lb, *_ in sorted(r for r in rows if r[0] <= chance):
    print(f'    {sc:.2f}  §{sid:5} {a}-{b} ({la}/{lb} verses)  {sections[sid]["title"][:60]}')

singles, runs = [], []
for sc, sid, a, b, la, lb, ta, tb in rows:
    for x, y in ((ta, tb), (tb, ta)):
        s1, s2 = underline_share(x, y)
        if s1 is not None:
            singles.append(s1)
            runs.append(s2)
m1, m2 = statistics.median(singles), statistics.median(runs)
verdict = 'PASS (single-lemma underline)' if 0.20 <= m1 <= 0.70 else (
    'over 70%: use runs' if m1 > 0.70 else 'under 20%: no underline')
print(f'\nQ2 underline: median share of content words with a shared lemma {m1:.0%}; '
      f'in shared runs of 2+ {m2:.0%}  -> {verdict}')
print(f'  quartiles single {pct(sorted(singles), 25):.0%}-{pct(sorted(singles), 75):.0%}, '
      f'runs {pct(sorted(runs), 25):.0%}-{pct(sorted(runs), 75):.0%}')

# ── Q3: verse alignment ───────────────────────────────────────────────────
verse_base = []
while len(verse_base) < 4000:
    ba, bb = random.sample(GOSPELS, 2)
    va, vb = random.choice(all_verses[ba]), random.choice(all_verses[bb])
    if sec_of[va] & sec_of[vb]:
        continue
    verse_base.append(score(lemmas(*va), lemmas(*vb)))
verse_chance = pct(sorted(verse_base), 95)


def lis_len(seq):
    import bisect
    tails = []
    for x in seq:
        i = bisect.bisect_right(tails, x)
        tails[i:i + 1] = [x]
    return len(tails)


matched = kept = total = 0
for sc, sid, a, b, la, lb, *_ in rows:
    pa, pb = passages[sid][a], passages[sid][b]
    if len(pa) < 2 or len(pb) < 2:
        continue
    seq = []
    for va in pa:
        best = max(((score(lemmas(*va), lemmas(*vb)), j) for j, vb in enumerate(pb)), default=(0, 0))
        total += 1
        if best[0] > verse_chance:
            seq.append(best[1])
    matched += len(seq)
    kept += lis_len(seq)
q3 = kept / matched if matched else 0
print(f'\nQ3 alignment: verse chance (95th pct) {verse_chance:.3f}; {total} verses in multi-verse pairs, '
      f'{matched} ({matched / total:.0%}) have a match above chance; '
      f"{q3:.0%} of those keep their order  -> {'PASS' if q3 >= 0.85 else 'FAIL'} (threshold 85%)")

# ── Q4: the kinds ──────────────────────────────────────────────────────────
print('\nQ4 by kind (median score; share above chance):')


def report(label, scores):
    if scores:
        print(f'  {label:42} n={len(scores):4}  median {statistics.median(scores):.2f}  '
              f'above chance {sum(s > chance for s in scores) / len(scores):.0%}')


report('same event (Robertson sections)', [r[0] for r in rows])
by = defaultdict(list)
for l in data['links']:
    if 'eusebius' in l:
        p = [tokens(verses_of(sp)) for sp in l['passages']]
        by[l['kind']].append(score(*p))
report('same words, another setting (Eusebius)', by['same_words'])
report('similar event (Eusebius pairs, Robertson 2)', by['look_alike'])
for kind in ('saying', 'incident'):
    sc = []
    for g in data['similar']:
        if g['kind'] != kind:
            continue
        ids = [s.split()[0] for s in g['sections']]
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                ta = tokens([v for vs in passages[x].values() for v in vs])
                tb = tokens([v for vs in passages[y].values() for v in vs])
                sc.append(score(ta, tb))
    report(f"Robertson's {kind} groups (whole sections)", sc)
print(f'\n(verses read from other editions: {len(fallback)}: '
      f"{', '.join(f'{b} {c}:{v}' for b, c, v in sorted(fallback))})")
# Eusebius's same-words pairs: does reading whole verses (not his half-verses) explain the low share?
whole = [score(*[tokens(verses_of(sp)) for sp in l['passages']]) for l in data['links']
         if l['kind'] == 'same_words' and 'eusebius' in l
         and not any('start_part' in sp or 'end_part' in sp for sp in l['passages'])]
report('  same words, whole-verse sections only', whole)

# ── --annotate: write each link's measure into harmony.json ────────────────
if '--annotate' in sys.argv:
    def section_tokens(sid):
        return tokens([v for vs in passages[sid].values() for v in vs])

    for l in data['links']:
        if l['kind'] == 'same_event':
            per = passages[l['section']]
            books = [b for b in GOSPELS if b in per]
            l['greek_pairs'] = {f'{a}-{b}': round(score(tokens(per[a]), tokens(per[b])), 3)
                                for i, a in enumerate(books) for b in books[i + 1:]}
            l['shares_words'] = all(s > chance for s in l['greek_pairs'].values())
            continue
        if 'passages' in l:
            s = score(*[tokens(verses_of(sp)) for sp in l['passages']])
        else:
            ids = [x.split()[0] for x in l['sections']]
            s = max(score(section_tokens(a), section_tokens(b))
                    for i, a in enumerate(ids) for b in ids[i + 1:])
        l['greek'] = round(s, 3)
        l['shares_words'] = s > chance
    data['greek_measure'] = {
        'source': 'TAGNT lemmas, STEPBible / Tyndale House Cambridge · CC BY 4.0', 'chance': round(chance, 3),
        'score': 'idf-weighted share of the smaller passage\'s content lemmas found in the other',
        'chance_is': '95th percentile of 2,000 length-matched random pairs from different Gospels',
    }
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    sw = [l for l in data['links'] if l['kind'] == 'same_words']
    print(f"annotated: said elsewhere {len(sw)} links, {sum(l['shares_words'] for l in sw)} share words, "
          f"{sum(not l['shares_words'] for l in sw)} share a teaching")
