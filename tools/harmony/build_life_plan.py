"""Build life_of_christ.json: the "Life of Christ in 40 Days" reading plan.

Robertson's 185 sections, in his order, cut into 40 days of near-equal
length by verse count. A day keeps whole sections and reads every account
of each, gathered by Gospel (Matthew's part, then Mark's, Luke's, John's)
and joined where the verses run on, so a day is a few passages and not a
score of them. Each day also names its sections for the door to the
harmony page.

Run from the repository root, after build_harmony.py:
  python3 -I tools/harmony/build_life_plan.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
IN = os.path.join(ROOT, 'data', 'harmony', 'harmony.json')
OUT = os.path.join(ROOT, 'data', 'harmony', 'life_of_christ.json')
sys.path.insert(0, ROOT)
from sword_bridge import verse_count  # noqa: E402  (KJV)

DAYS = 40
#: harmony.json's book keys, in reading order, to the app's book names.
BOOKS = {'Matt': 'Matthew', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John',
         'Acts': 'Acts', '1Cor': '1 Corinthians'}


def kjv_count(book, ch):
    return verse_count(BOOKS[book], ch, 'KJV')


def verses_of(ref):
    """Every (chapter, verse) in a ref, by KJV counts."""
    (c, v), end = ref['start'], tuple(ref['end'])
    out = []
    while (c, v) <= end:
        out.append((c, v))
        v += 1
        if v > kjv_count(ref['book'], c):
            c, v = c + 1, 1
    return out


def split(weights, n):
    """Cut weights, in order, into n runs as near the mean as can be
    (least squares). Returns (start, end) index pairs."""
    pre = [0]
    for w in weights:
        pre.append(pre[-1] + w)
    mean, m = pre[-1] / n, len(weights)
    inf = float('inf')
    best = [[inf] * (m + 1) for _ in range(n + 1)]
    cut = [[0] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0
    for k in range(1, n + 1):
        for i in range(k, m + 1):
            for j in range(k - 1, i):
                c = best[k - 1][j] + (pre[i] - pre[j] - mean) ** 2
                if c < best[k][i]:
                    best[k][i], cut[k][i] = c, j
    runs, i = [], m
    for k in range(n, 0, -1):
        runs.append((cut[k][i], i))
        i = cut[k][i]
    return runs[::-1]


def passages(sections):
    """A day's sections as [book, chapter, verse, end_chapter, end_verse]
    passages, by book in reading order, joined where the verses run on."""
    seen = {}
    for s in sections:
        for r in s['refs']:
            seen.setdefault(r['book'], set()).update(verses_of(r))
    out = []
    for book in BOOKS:
        run = None
        for c, v in sorted(seen.get(book, ())):
            if run and ((c, v) == (run[3], run[4] + 1)
                        or (c == run[3] + 1 and v == 1
                            and run[4] == kjv_count(book, run[3]))):
                run[3], run[4] = c, v
                continue
            if run:
                out.append(run)
            run = [BOOKS[book], c, v, c, v]
        if run:
            out.append(run)
    return out


def main():
    with open(IN, encoding='utf-8') as f:
        sections = json.load(f)['sections']
    weights = [sum(len(verses_of(r)) for r in s['refs']) for s in sections]
    runs = split(weights, DAYS)
    days = [{'sections': [s['id'] for s in sections[a:b]],
             'passages': passages(sections[a:b])} for a, b in runs]
    loads = [sum(weights[a:b]) for a, b in runs]
    with open(OUT, 'w', encoding='utf-8') as f:
        # A day to a line, so a rebuild's diff reads day by day.
        f.write('{"source": "Robertson, A Harmony of the Gospels (1922); '
                'built by tools/harmony/build_life_plan.py",\n "days": [\n')
        f.write(',\n'.join(json.dumps(d, ensure_ascii=False) for d in days))
        f.write('\n]}\n')
    print(f'{len(days)} days, {min(loads)}–{max(loads)} verses a day, '
          f'{max(len(d["passages"]) for d in days)} passages at most')
    print('wrote', os.path.relpath(OUT, ROOT))


if __name__ == '__main__':
    main()
