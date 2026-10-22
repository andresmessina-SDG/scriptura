"""Build harmony.json: Robertson's sections, the Eusebian canons, and typed
links between Gospel passages. Fails on any check it cannot account for.

Sources (all public domain, in src/):
  robertson.txt  A. T. Robertson, A Harmony of the Gospels (1922), Gutenberg #36264
  sword/         INTF Eusebian_vs + Eusebian_num (CrossWire), read with diatheke

Run from the repository root, then annotate with the Greek measure:
  python3 -I tools/harmony/build_harmony.py
  python3 -I tools/harmony/greek_agreement.py --annotate
src/ is not kept in the repository; tools/harmony/fetch_sources.py fills it.
"""
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
ROOT = os.path.join(HERE, '..', '..')
OUT = os.path.join(ROOT, 'data', 'harmony', 'harmony.json')
sys.path.insert(0, ROOT)
from sword_bridge import load_chapter, plain_text, verse_count  # noqa: E402  (KJV)

GOSPELS = ('Matt', 'Mark', 'Luke', 'John')
SWORD_NAME = {'Matt': 'Matthew', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John'}
CHAPTERS = {'Matt': 28, 'Mark': 16, 'Luke': 24, 'John': 21}
ROBERTSON_BOOK = {'Mark': 'Mark', 'Matt.': 'Matt', 'Luke': 'Luke', 'John': 'John',
                  '1 Cor.': '1Cor', 'Acts': 'Acts'}
BOOK_RE = r'(Mark|Matt\.|Luke|John|1 Cor\.|Acts)'

errors, warnings = [], []


def kjv_count(book, ch):
    return verse_count(SWORD_NAME[book], ch, 'KJV') if book in SWORD_NAME else 999


def verses_of(span):
    """Every (book, ch, v) in a span, by KJV counts."""
    book, (c, v), (c2, v2) = span['book'], span['start'], span['end']
    out = []
    while (c, v) <= (c2, v2):
        out.append((book, c, v))
        v += 1
        if v > kjv_count(book, c):
            c, v = c + 1, 1
    return out


def parse_refs(text, where):
    """'Mark 1:9-11; Matt. 3:13-17; Luke 3:21-23.' -> spans. Robertson's forms:
    whole chapters (Matt. 5-7), carried book and chapter (Luke 3:19-20; 4:14,
    Mark 14:26, 32-42), cross-chapter ranges (John 2:23-3:21)."""
    spans, book, chap = [], None, None
    for piece in re.split(r'[;,]', text.strip().rstrip('.')):
        p = piece.strip()
        m = re.match(BOOK_RE + r'\s+(.*)', p)
        if m:
            book, p, chap = ROBERTSON_BOOK[m.group(1)], m.group(2).strip(), None
        if not p:
            continue
        if book is None:
            errors.append(f'{where}: reference with no book: {piece!r}')
            continue
        whole = re.fullmatch(r'(\d+)(?:-(\d+))?', p)
        if whole and chap is None:
            c1, c2 = int(whole.group(1)), int(whole.group(2) or whole.group(1))
            spans.append({'book': book, 'start': [c1, 1], 'end': [c2, kjv_count(book, c2)]})
            continue
        m = re.fullmatch(r'(?:(\d+):)?(\d+)(?:-(?:(\d+):)?(\d+))?', p)
        if not m or (m.group(1) is None and chap is None):
            errors.append(f'{where}: cannot read {piece!r}')
            continue
        c1 = int(m.group(1)) if m.group(1) else chap
        v1 = int(m.group(2))
        c2 = int(m.group(3)) if m.group(3) else c1
        v2 = int(m.group(4)) if m.group(4) else v1
        chap = c2
        span = {'book': book, 'start': [c1, v1], 'end': [c2, v2]}
        if book in GOSPELS:
            for c, v in ((c1, v1), (c2, v2)):
                if not 1 <= c <= CHAPTERS[book] or not 1 <= v <= kjv_count(book, c):
                    errors.append(f'{where}: {book} {c}:{v} is not a KJV verse')
            if (c1, v1) > (c2, v2):
                errors.append(f'{where}: backwards range {piece!r}')
        spans.append(span)
    return spans


def ref_label(span):
    (c, v), (c2, v2) = span['start'], span['end']
    tail = f'{c}:{v}' if (c, v) == (c2, v2) else (
        f'{c}:{v}-{v2}' if c == c2 else f'{c}:{v}-{c2}:{v2}')
    return f"{span['book']} {tail}"


# ── Robertson: the chief divisions ─────────────────────────────────────────

lines = open(os.path.join(SRC, 'robertson.txt'), encoding='utf-8').read().splitlines()
div_start = next(i for i, l in enumerate(lines)
                 if l.strip() == 'ANALYTICAL OUTLINE OF THE HARMONY' and i > 200)
div_end = next(i for i, l in enumerate(lines)
               if l.strip() == 'TABLE FOR FINDING ANY PASSAGE IN THE HARMONY' and i > div_start)


def indent(s):
    return len(s) - len(s.lstrip())


parts, groups, sections = [], [], []
cur_part = cur_group = cur_sec = None
title_item = None          # the item whose title is still being read
pending_refs = None        # ref text still waiting for its closing period
for raw in lines[div_start + 1:div_end]:
    s = raw.strip()
    if not s or s == '_Eight Groups in the Period_' or s.startswith('_') and 'Groups' in s:
        continue
    if pending_refs is not None:
        pending_refs['text'] += ' ' + s
        if s.endswith('.'):
            pending_refs = None
        continue
    if s.startswith('PART '):
        m = re.match(r'PART ([IVX]+): (.*)', s)
        cur_part = {'n': m.group(1), 'title': m.group(2), 'sections': []}
        parts.append(cur_part)
        cur_group = cur_sec = None
        title_item = (cur_part, indent(raw))
        continue
    m = re.match(r'SECTIONS (\d+)-(\d+)$', s)
    if m:
        cur_part['range'] = [int(m.group(1)), int(m.group(2))]
        title_item = None
        continue
    m = re.match(r'Sections (\d+)-(\d+)\.$', s)
    if m:
        groups[-1]['range'] = [int(m.group(1)), int(m.group(2))]
        title_item = None
        continue
    m = re.match(r'Sect\. (\d+)([ab]?): (.*)', s)
    if m:
        cur_sec = {'id': m.group(1) + m.group(2), 'num': int(m.group(1)),
                   'title': m.group(3), 'part': cur_part['n'], 'refs_text': '',
                   'subparts': []}
        sections.append(cur_sec)
        cur_part['sections'].append(cur_sec['id'])
        title_item = (cur_sec, indent(raw))
        continue
    if re.match(BOOK_RE + r' \d', s):
        target = title_item[0] if title_item else None
        if target is None or (target is not cur_sec and target not in cur_sec['subparts']):
            errors.append(f"§{cur_sec['id']}: reference line with no title {s!r}")
            continue
        target['refs_text'] = s
        if not s.endswith('.'):
            pending_refs = {'text': s}
            target['refs_text'] = pending_refs  # finished below
        title_item = None
        continue
    # A title line: a continuation, a part-VII group, or a sub-part.
    if title_item and indent(raw) > title_item[1] and (
            'depth' not in title_item[0] or not re.match(r'(\(|_)', s)):
        title_item[0]['title'] += ' ' + s
        continue
    if cur_sec is None and cur_part is not None and re.match(r'\(\d+\) ', s):
        g = {'part': cur_part['n'], 'title': re.sub(r'^\(\d+\) ', '', s)}
        groups.append(g)
        title_item = (g, indent(raw))
        continue
    if cur_sec is not None:
        sp = {'title': s.strip('_'), 'depth': indent(raw)}
        cur_sec['subparts'].append(sp)
        title_item = (sp, indent(raw))
        continue
    errors.append(f'unplaced line in divisions: {s!r}')

# Part VII groups come before their sections in the list; attach by range.
for sec in sections:
    for g in groups:
        if g['range'][0] <= sec['num'] <= g['range'][1]:
            sec['group'] = groups.index(g)


def finish_refs(item, where):
    t = item.get('refs_text', '')
    if isinstance(t, dict):
        t = t['text']
    item['refs_text'] = t
    item['refs'] = parse_refs(t, where) if t else []


for sec in sections:
    finish_refs(sec, f"§{sec['id']}")
    depths = sorted({sp['depth'] for sp in sec['subparts']})
    for sp in sec['subparts']:
        finish_refs(sp, f"§{sec['id']} {sp['title'][:30]}")
        sp['depth'] = depths.index(sp['depth'])
        sp['title'] = re.sub(r'\s+', ' ', sp['title']).strip()
    sec['title'] = re.sub(r'\s+', ' ', sec['title']).strip()
    sec['gospels'] = [b for b in GOSPELS if any(r['book'] == b for r in sec['refs'])]
    if not sec['refs']:
        errors.append(f"§{sec['id']}: no references")

# Numbering: 1..184, with 128 split into a and b.
ids = [s['id'] for s in sections]
expected = [str(n) for n in range(1, 128)] + ['128a', '128b'] + [str(n) for n in range(129, 185)]
if ids != expected:
    errors.append(f'section numbering differs from 1..184 (+128a/b): '
                  f'{sorted(set(ids) ^ set(expected))}')
for p in parts:
    if 'range' in p:
        nums = [int(re.match(r'\d+', i).group()) for i in p['sections']]
        if (min(nums), max(nums)) != tuple(p['range']):
            errors.append(f"PART {p['n']}: says sections {p['range']}, holds {min(nums)}-{max(nums)}")

# ── Robertson: the body headers (setting line) ─────────────────────────────

body_from = div_end
setting, summary, compare, body_title = {}, {}, {}, {}
i = body_from
while i < len(lines):
    m = re.match(r'Sect\. (\d+[ab]?)\. (.*)', lines[i])
    if m and m.group(1) not in body_title:
        sid, title = m.group(1), m.group(2).strip()
        j = i + 1
        while lines[j].strip():
            title += ' ' + lines[j].strip()
            j += 1
        body_title[sid] = re.sub(r'\[[a-z]\]', '', title).strip()
        # Paragraphs between the title and the text: an italic summary, a
        # "(Compare Sect. N)" note, the place and the time.
        paras, cur = [], []
        while j < len(lines):
            s = lines[j].strip()
            if '|' in s or re.match(BOOK_RE + r' \d', s) or s.startswith('[Footnote') \
                    or re.match(r'\d+ ', s) or s.startswith('Sect. '):
                break
            if s:
                cur.append(s)
            elif cur:
                paras.append(' '.join(cur))
                cur = []
            j += 1
        if cur:
            paras.append(' '.join(cur))
        for para in paras:
            para = re.sub(r'\[[a-z]\]', '', para).strip()
            if para.startswith('_'):
                summary.setdefault(sid, []).append(para.strip('_ '))
            elif re.match(r'\((Compare|Comp\.|Cf\.)', para):
                compare[sid] = para.strip('() ')
            else:
                setting.setdefault(sid, []).append(para)
        i = j
        continue
    i += 1
missing_body = [s['id'] for s in sections if s['id'] not in body_title]
if missing_body:
    errors.append(f'sections with no body header: {missing_body}')


def norm(t):
    return re.sub(r'[^A-Z0-9]', '', t.upper())


for sec in sections:
    sec['setting'] = setting.get(sec['id'], [])
    if sec['id'] in summary:
        sec['summary'] = summary[sec['id']]
    if sec['id'] in compare:
        sec['compare'] = compare[sec['id']]
    if sec['id'] in body_title and norm(body_title[sec['id']]) != norm(sec['title']):
        warnings.append(f"§{sec['id']} title differs in body: {sec['title']!r} / {body_title[sec['id']]!r}")

# ── Robertson: verse -> sections, from the divisions and from the finding table ─

div_map = defaultdict(set)
for sec in sections:
    for span in sec['refs']:
        if span['book'] in GOSPELS:
            for v in verses_of(span):
                div_map[v].add(sec['id'])

ft_start = next(i for i, l in enumerate(lines) if l.strip() == 'TABLE FOR FINDING ANY PASSAGE IN THE HARMONY'
                and i > div_end - 1)
ft_end = next(i for i, l in enumerate(lines) if l.startswith('Sect. 1. ') and i > ft_start)
find_map = defaultdict(set)
book = None
for raw in lines[ft_start:ft_end]:
    s = raw.strip()
    if s in ('MARK', 'MATTHEW', 'LUKE', 'JOHN'):
        book = {'MARK': 'Mark', 'MATTHEW': 'Matt', 'LUKE': 'Luke', 'JOHN': 'John'}[s]
        continue
    if book is None or '|' not in s or s.startswith('Chap') or s.startswith('-'):
        continue
    for half in s.split('||'):
        cells = [c.strip() for c in half.split('|')]
        if len(cells) != 3 or not cells[0]:
            continue
        ch, vs, sid = cells
        if vs == '...':      # whole chapters: '24, 25 | ... | 139'
            ch, vs = ch.split(',')[0].strip(), ''
            ref = f'{book if book != "Matt" else "Matt."} ' + cells[0].replace(',', '-').replace(' ', '')
            for span in parse_refs(ref, f'finding table {book} {cells[0]}'):
                for v in verses_of(span):
                    find_map[v].add(sid)
            continue
        for span in parse_refs(f'{book if book != "Matt" else "Matt."} {ch}:{vs}', f'finding table {book} {ch}:{vs}'):
            for v in verses_of(span):
                find_map[v].add(sid)

all_verses = [(b, c, v) for b in GOSPELS for c in range(1, CHAPTERS[b] + 1)
              for v in range(1, kjv_count(b, c) + 1)]
# Verses the Revised Version leaves out; Robertson has no section for them.
RV_OMITS = {('Mark', 11, 26): '131', ('Matt', 17, 21): '87'}
# Matt 8:1 sits only in a sub-part of §54 (7:13-8:1), not in the section's own line.
SUBPART_ONLY = {('Matt', 8, 1): '54'}
for v in all_verses:
    if v in RV_OMITS or v in SUBPART_ONLY:
        continue
    if not div_map[v]:
        errors.append(f'{v} is in no Robertson section')
    if div_map[v] != find_map[v] and find_map[v]:
        warnings.append(f'{v}: divisions say {sorted(div_map[v])}, finding table {sorted(find_map[v])}')
    if not find_map[v] and div_map[v]:
        warnings.append(f'{v}: not in the finding table (divisions: {sorted(div_map[v])})')
for v, sid in {**RV_OMITS, **SUBPART_ONLY}.items():
    if div_map[v]:
        errors.append(f'{v} was listed as having no section, but is in {sorted(div_map[v])}')

# ── Robertson: similar incidents and repeated sayings ──────────────────────

sim_at = [i for i, l in enumerate(lines) if l.strip() == 'SIMILAR INCIDENTS AND CHIEF REPEATED SAYINGS'][-1]
similar = []
text = []
for raw in lines[sim_at + 1:]:
    if raw.startswith('In general the Later Judean'):
        break
    if raw.strip():
        text.append(raw.strip())
    elif text:
        entry = ' '.join(text)
        text = []
        m = re.match(r'(.*?): Sects?\. (.*)\.$', entry)
        if not m:
            errors.append(f'similar list: cannot read {entry!r}')
            continue
        secs = []
        for piece in re.split(r',|\band\b', m.group(2)):
            p = piece.strip()
            if not p:
                continue
            r = re.fullmatch(r'(\d+)(?: \(([a-z])\))?(?:-(\d+))?', p)
            if not r:
                errors.append(f'similar list {m.group(1)!r}: cannot read {p!r}')
                continue
            a, b = int(r.group(1)), int(r.group(3) or r.group(1))
            for n in range(a, b + 1):
                if n == 128 and a == b:
                    # A bare "128" (Lament Over Jerusalem) is 128b, where Luke 19:41-44 is.
                    secs.append('128b')
                    continue
                for sid in (str(n),) if str(n) in ids else (f'{n}a', f'{n}b'):
                    if sid in ids:
                        secs.append(sid + (f' ({r.group(2)})' if r.group(2) else ''))
        similar.append({'title': m.group(1), 'sections': secs})
if text:
    errors.append(f'similar list: trailing text {text!r}')

# Kind of each group. Robertson names the groups but not their kind; each kind
# below rests on his own words where he gives them (checked against the text
# below), on Scripture, or on the stated rule.
#   incident = an act or event that happened more than once (dashed)
#   saying   = the same words in another setting: said again, or placed
#              elsewhere by an evangelist (fine)
#   theme    = a subject running through many sections, or one word shared
#              by different sayings (no stroke)
R = 'robertson'
SIMILAR_KIND = {
    'Calling Disciples': ('incident', R, 'had already become disciples of Jesus at Bethany beyond Jordan'),
    'Cleansing the Temple': ('incident', R, 'there is no inherent difficulty in the repetition of such an act'),
    'Owning Jesus as Messiah': ('theme', 'rule', None),
    'Rejection at Nazareth': ('incident', R, 'There is no sufficient occasion to identify this visit to Nazareth with that described by Luke.'),
    'Miraculous Draught of Fishes': ('incident', 'rule', None),
    'Parables of Mustard Seed and Leaven': ('saying', 'rule', None),
    'The Tours of Galilee': ('theme', 'rule', None),
    'Healings on the Sabbath': ('theme', 'rule', None),
    'The Lists of the Twelve': ('saying', R, 'Matthew postpones giving the names of the Twelve till they are sent out to preach in Galilee'),
    "Courtier's Son and Centurion's Servant": ('incident', 'scripture', 'John 4:46 a nobleman and his son at Cana; Luke 7:2 a centurion and his servant at Capernaum'),
    'The Model Prayer': ('saying', R, 'JESUS AGAIN GIVES A MODEL OF PRAYER'),
    'The Anointing of Christ': ('incident', R, 'This anointing in Galilee must be distinct from the anointing at Bethany, near Jerusalem, more than a year later.'),
    'The Blasphemous Accusation': ('incident', R, 'should be repeated a year or so afterward in Judea or Perea, and that Jesus should make substantially the same argument in reply'),
    'Groups of Parables': ('theme', 'rule', None),
    'Sending the Twelve and Sending the Seventy': ('incident', 'scripture', 'Luke 10:1 "the Lord appointed other seventy also"'),
    'Feeding the Five Thousand and the Four Thousand': ('incident', R, 'Mark and Matthew likewise report Jesus as referring to both incidents (Mark 8:19-20 = Matt. 16:9-10).'),
    'Tests of Discipleship': ('saying', 'rule', None),
    'Jesus Foretelling His Death': ('theme', 'rule', None),
    'The Twelve Contending for Supremacy': ('incident', 'scripture', 'Luke 22:24 "And there was also a strife among them"'),
    'Attacking Jesus in Jerusalem': ('theme', 'rule', None),
    'Foretelling the Second Coming': ('theme', 'rule', None),
    'Divorce': ('saying', 'rule', None),
    'Like Children': ('saying', 'rule', None),
    'Rewards of Service': ('saying', 'rule', None),
    'Worldly Anxieties': ('saying', R, 'Jesus often repeated his sayings on other occasions as all teachers do and ought to do.'),
    'The Ninety and Nine': ('saying', 'rule', None),
    'Baptism of Death': ('saying', 'rule', None),
    'The Pounds and the Talents': ('saying', R, 'The similar parable of the Talents was given several days later.'),
    'The Agony of Christ': ('incident', 'rule', None),
    'Denouncing the Scribes and Pharisees': ('saying', 'rule', None),
    'Lament Over Jerusalem': ('saying', 'rule', None),
    'About a Sword': ('theme', 'rule', None),   # three different sayings that share a word
    'The Three Commissions': ('saying', R, "Of our Lord's final commissions to the apostles and others (Luke 24:33), this is the first."),
}
flat = re.sub(r'\s+', ' ', '\n'.join(lines))
# What each kind means, in Robertson's words where he gives them.
KINDS = {
    'same_event': {'stroke': 'solid', 'label': 'Same event'},
    'same_words': {'stroke': 'fine', 'label': 'Said elsewhere',
                   'quote': 'Some of these were real doublets, spoken by Jesus more than once. '
                            'Others may be grouped by Luke in a different place. '
                            'We have no way to decide the problem.'},
    'look_alike': {'stroke': 'dashed', 'label': 'Similar event',
                   'quote': "Similar miracles were often wrought in the Master's work and similar "
                            'sayings were frequently repeated on similar or different occasions.'},
    'only_here': {'stroke': 'hollow', 'label': 'Only here'},
}
for k, v in KINDS.items():
    if 'quote' in v and v['quote'] not in flat:
        errors.append(f'kind {k}: quotation not found in Robertson')
for title, (kind, basis, words) in SIMILAR_KIND.items():
    if basis == R and re.sub(r'\s+', ' ', words) not in flat:
        errors.append(f'similar {title!r}: quotation not found in Robertson: {words!r}')
for g in similar:
    kind, basis, words = SIMILAR_KIND.get(g['title'], (None, None, None))
    g.update(kind=kind, basis=basis)
    if words:
        g['quote' if basis == R else 'cite'] = words
    if g['kind'] is None:
        errors.append(f"similar group with no kind: {g['title']!r}")
if set(SIMILAR_KIND) - {g['title'] for g in similar}:
    errors.append(f'kinds for missing groups: {set(SIMILAR_KIND) - {g["title"] for g in similar}}')

# ── Eusebius: the INTF modules ─────────────────────────────────────────────

SWORD = os.path.join(SRC, 'sword')
env = dict(os.environ, SWORD_PATH=SWORD)
CANON = {'I': 'Matt Mark Luke John', 'II': 'Matt Mark Luke', 'III': 'Matt Luke John',
         'IV': 'Matt Mark John', 'V': 'Matt Luke', 'VI': 'Matt Mark', 'VII': 'Matt John',
         'VIII': 'Mark Luke', 'IX': 'Luke John', 'X': None}
EB = {'1': 'Matt', '2': 'Mark', '3': 'Luke', '4': 'John'}

CACHE = os.path.join(SRC, 'eusebian_num.json')   # diatheke is slow; delete to re-read
eus = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
for b in ('' if eus else '1234'):
    n = 1
    while True:
        out = subprocess.run(['diatheke', '-b', 'Eusebian_num', '-k', f'{b}.{n}'],
                             capture_output=True, text=True, env=env).stdout
        m = re.search(r'<EusebianNumber id="([\d.]+)" table="([^"]*)" osisRef="([^"]*)" assocates="([^"]*)"', out)
        if not m or m.group(1) != f'{b}.{n}':
            break
        eus[m.group(1)] = {'id': m.group(1), 'gospel': EB[b], 'table': m.group(2),
                           'osis': m.group(3), 'assoc': m.group(4).split()}
        n += 1
json.dump(eus, open(CACHE, 'w'), indent=0)
counts = Counter(e['gospel'] for e in eus.values())
if counts != Counter({'Matt': 355, 'Mark': 233, 'Luke': 342, 'John': 232}):
    errors.append(f'Eusebian section counts: {dict(counts)}')


def parse_osis(ref, where):
    """'Matt.1.1-16', 'Mark.1.7b-8', 'John.7.45-8.19a' -> span with half-verse marks."""
    one = re.fullmatch(r'(Matt|Mark|Luke|John)\.(\d+)\.(\d+)([a-e])-([a-eA-E])', ref)
    if one:
        warnings.append(f'{where}: read {ref!r} as parts {one.group(4)}-{one.group(5).lower()} of one verse')
        c, v = int(one.group(2)), int(one.group(3))
        return {'book': one.group(1), 'start': [c, v], 'end': [c, v],
                'start_part': one.group(4), 'end_part': one.group(5).lower()}
    m = re.fullmatch(r'(Matt|Mark|Luke|John)\.(\d+)\.(\d+)([a-e]?)(?:-(?:(?:\w+\.)?(\d+)\.)?(\d+)([a-e]?))?', ref)
    if not m:
        errors.append(f'{where}: cannot read osisRef {ref!r}')
        return None
    b, c1, v1, p1 = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    c2 = int(m.group(5)) if m.group(5) else c1
    v2 = int(m.group(6)) if m.group(6) else v1
    p2 = m.group(7) if m.group(6) else p1
    span = {'book': b, 'start': [c1, v1], 'end': [c2, v2]}
    if p1:
        span['start_part'] = p1
    if p2:
        span['end_part'] = p2
    return span


# Per verse, from Eusebian_vs, against the ranges.
vs_map = {}
CODE = {v: k for k, v in SWORD_NAME.items()}
ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']
for b in GOSPELS:
    last = CHAPTERS[b]
    out = subprocess.run(['diatheke', '-b', 'Eusebian_vs', '-k',
                          f'{SWORD_NAME[b]} 1:1-{last}:{kjv_count(b, last)}'],
                         capture_output=True, text=True, env=env).stdout
    for m in re.finditer(r'^(\w+) (\d+):(\d+): ([\d.]+)', out, re.M):
        if CODE.get(m.group(1)) != b:
            errors.append(f'Eusebian_vs read for {b} returned {m.group(0)!r}')
            continue
        n = m.group(4)
        head, tail = n.split('.')
        if int(head) > 4:
            # Two entries are written section.table ('144.2'), not gospel.section.
            fixed = f'{GOSPELS.index(b) + 1}.{head}'
            if fixed not in eus or eus[fixed]['table'] != ROMAN[int(tail) - 1]:
                errors.append(f'Eusebian_vs {b} {m.group(2)}:{m.group(3)} = {n}: cannot repair')
            else:
                warnings.append(f'Eusebian_vs {b} {m.group(2)}:{m.group(3)} = {n}: read as {fixed} '
                                f'(section.table, table {ROMAN[int(tail) - 1]})')
                n = fixed
        vs_map[(b, int(m.group(2)), int(m.group(3)))] = n
for e in eus.values():
    if not e['osis']:
        vv = sorted((c, v) for (b, c, v), n in vs_map.items() if n == e['id'])
        if not vv:
            errors.append(f"Eusebius {e['id']}: no range and no verses")
            e['span'] = None
            continue
        e['span'] = {'book': e['gospel'], 'start': list(vv[0]), 'end': list(vv[-1]),
                     'from_verse_module': True}
        warnings.append(f"Eusebius {e['id']}: empty range; took {e['gospel']} "
                        f"{vv[0][0]}:{vv[0][1]}-{vv[-1][0]}:{vv[-1][1]} from Eusebian_vs")
        continue
    e['span'] = parse_osis(e['osis'], f"Eusebius {e['id']}")
    ag = {EB[a.split('.')[0]] for a in e['assoc']} | {e['gospel']}
    if e['table'] == 'X':
        if e['assoc']:
            errors.append(f"Eusebius {e['id']}: table X with parallels {e['assoc']}")
    elif e['table'] in CANON:
        if ag != set(CANON[e['table']].split()):
            errors.append(f"Eusebius {e['id']}: table {e['table']} but Gospels {sorted(ag)}")
    else:
        warnings.append(f"Eusebius {e['id']}: table {e['table']!r} is not one of the ten "
                        f"(Gospels {sorted(ag)}; parallels {e['assoc']})")
    for a in e['assoc']:
        if a not in eus:
            errors.append(f"Eusebius {e['id']}: parallel {a} does not exist")
        elif e['id'] not in eus[a]['assoc']:
            warnings.append(f"Eusebius {e['id']} lists {a}, which does not list it back")

# Ranges should run through each Gospel in order, without gaps (half-verses join).
for b in GOSPELS:
    seq = sorted((e for e in eus.values() if e['gospel'] == b and e['span']),
                 key=lambda e: int(e['id'].split('.')[1]))
    for prev, nxt in zip(seq, seq[1:]):
        (pc, pv), (nc, nv) = prev['span']['end'], nxt['span']['start']
        if prev['span'].get('end_part') and (pc, pv) == (nc, nv):
            continue
        follows = (nc, nv) == (pc, pv + 1) or (nv == 1 and nc == pc + 1 and pv == kjv_count(b, pc))
        if not follows:
            warnings.append(f"Eusebius {prev['id']} ends {pc}:{pv}, {nxt['id']} starts {nc}:{nv}")

range_map = defaultdict(set)
for e in eus.values():
    for v in verses_of(e['span']) if e['span'] else ():
        range_map[v].add(e['id'])
no_number, no_table = [], []
for v in all_verses:
    n = vs_map.get(v)
    if n is None:
        no_number.append(v)
    elif n not in eus:
        no_table.append((v, n))
    elif n not in range_map[v]:
        warnings.append(f'Eusebian_vs gives {v} section {n}; the ranges give {sorted(range_map[v])}')
# Known: the longer ending of Mark is numbered 234-241 in Eusebian_vs, with no table entry.
LONGER_ENDING = {('Mark', 16, v) for v in range(9, 21)}
if {v for v, _ in no_table} != LONGER_ENDING:
    errors.append(f'verses numbered with no table entry: {no_table}')
for v in no_number:
    warnings.append(f'{v}: no Eusebian number (KJV verse absent from the critical text?)')

if errors:   # the links below need clean spans
    for e in errors:
        print('ERROR:', e)
    sys.exit(1)

# ── Links ──────────────────────────────────────────────────────────────────


def secs_of(span):
    found = set()
    for v in verses_of(span):
        found |= div_map.get(v, set())
        if v in RV_OMITS:
            found.add(RV_OMITS[v])
        if v in SUBPART_ONLY:
            found.add(SUBPART_ONLY[v])
    return found


links = []
# 1. Same event: each Robertson section in two or more Gospels.
for sec in sections:
    if len(sec['gospels']) >= 2:
        links.append({'kind': 'same_event', 'section': sec['id'],
                      'passages': [r for r in sec['refs'] if r['book'] in GOSPELS],
                      'witnesses': ['robertson']})

# 2. Eusebius's parallels, one pair at a time, each against Robertson.
pairs_seen = set()
for e in eus.values():
    for a_id in e['assoc']:
        if eus[a_id]['gospel'] != e['gospel']:
            pairs_seen.add(tuple(sorted((e['id'], a_id), key=lambda i: (i.split('.')[0], int(i.split('.')[1])))))
rows = pairs_seen
incident_pairs = defaultdict(set)   # section -> sections Robertson calls look-alike events
saying_pairs = defaultdict(set)     # section -> sections holding the same words elsewhere
for g in similar:
    plain = [s.split()[0] for s in g['sections']]
    target = {'incident': incident_pairs, 'saying': saying_pairs}.get(g['kind'])
    for x in plain:
        for y in plain:
            if target is not None and x != y:
                target[x].add(y)
by_kind = Counter()
event_links = {l['section']: l for l in links}
for a_id, b_id in sorted(pairs_seen):
    sa, sb = secs_of(eus[a_id]['span']), secs_of(eus[b_id]['span'])
    shared = sa & sb
    if shared:
        for sid in shared:
            if sid in event_links and 'eusebius' not in event_links[sid]['witnesses']:
                event_links[sid]['witnesses'].append('eusebius')
        by_kind['eusebius agrees: same event'] += 1
        continue
    cross = {(x, y) for x in sa for y in sb}
    link = {'passages': [eus[a_id]['span'], eus[b_id]['span']], 'eusebius': [a_id, b_id],
            'robertson_sections': [sorted(sa), sorted(sb)], 'witnesses': ['eusebius']}
    if any(y in incident_pairs[x] for x, y in cross):
        link['kind'] = 'look_alike'
        link['note'] = 'eusebius_pairs'   # Eusebius sets them side by side; Robertson counts two events
    else:
        link['kind'] = 'same_words'
        if any(y in saying_pairs[x] for x, y in cross):
            link['witnesses'].append('robertson')
    links.append(link)
    by_kind[link['kind']] += 1

# 3. Robertson's look-alike events and repeated sayings, between whole sections.
for g in similar:
    if g['kind'] == 'theme':
        continue
    links.append({'kind': 'look_alike' if g['kind'] == 'incident' else 'same_words',
                  'robertson_group': g['title'], 'sections': g['sections'],
                  'witnesses': ['robertson']})

# 4. Only here.
only_here = {
    'robertson': [s['id'] for s in sections if len(s['gospels']) == 1],
    'eusebius_x': [e['id'] for e in eus.values() if e['table'] == 'X'],
}

# ── Report and write ───────────────────────────────────────────────────────

for w in warnings:
    print('warning:', w)
for e in errors:
    print('ERROR:', e)
print(f'\nRobertson: {len(parts)} parts, {len(groups)} groups, {len(sections)} sections, '
      f"{sum(len(s['subparts']) for s in sections)} sub-parts, "
      f"{sum(1 for s in sections if s['setting'])} with a setting line, "
      f'{len(similar)} similar groups ({dict(Counter(g["kind"] for g in similar))})')
print(f'Eusebius: {len(eus)} sections, {len(rows)} pairs of parallels, '
      f"{len(only_here['eusebius_x'])} in canon X")
print('Rows against Robertson:', dict(by_kind))
print('Links:', dict(Counter(l['kind'] for l in links)))
print(f'{len(warnings)} warnings, {len(errors)} errors')
if errors:
    sys.exit(1)

for sec in sections:
    for k in ('refs_text', 'num'):
        sec.pop(k, None)
    for sp in sec['subparts']:
        sp.pop('refs_text', None)
# ── Headings in sentence case ──────────────────────────────────────────────
# Robertson's capitals are a print convention. A word keeps its capital when
# the KJV Gospels only ever write it with one, plus names the KJV lacks.
case = {}
for b in GOSPELS:
    for c in range(1, CHAPTERS[b] + 1):
        for _v, h in load_chapter('KJV', SWORD_NAME[b], c):
            for w in re.findall(r"[A-Za-z][a-z']+", plain_text(h)):
                case[w.lower()] = case.get(w.lower(), True) and w[0].isupper()
PROPER = {k for k, up in case.items() if up} | {
    'twelve', 'seventy', 'baptist', 'messiah', 'sanhedrin', 'jewish', 'perea', 'perean',
    'antipas', 'galilean', 'judean', 'khersa', 'magadan', 'dalmanutha', 'phoenicia',
    'hermon', 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
    'saturday', 'sabbath', 'passover', 'paschal', 'logos', 'christ', 'lord',
    # Spelt otherwise in the KJV (Elias, Cesarea) or not in the Gospels.
    'luke', 'gospels', 'roman', 'elijah', 'elizabeth', 'caesar', 'caesarea',
    'bartimaeus', 'zacchaeus', 'gerasene', 'julias', 'machaerus', 'syro',
    'phoenician', 'via', 'dolorosa', 'magnificat', 'kedron', 'mount'}
if not case:
    errors.append('KJV not readable: headings left in capitals')


#: Titles a lower-case word cannot tell apart from common use: "the father"
#: is God in one heading and John Mark's in another.
TITLES = (('sermon on the Mount', 'Sermon on the Mount'),
          ('as the word (Logos)', 'as the Word (Logos)'),
          ('about the father', 'about the Father'),
          ('son of man', 'Son of man'))


def sentence(title):
    def cap(w):
        return re.sub(r'[a-z]', lambda m: m.group().upper(), w, count=1)

    def core(w):
        return re.sub(r"[^a-z']", '', w).split("'")[0]

    out = []
    for i, w in enumerate(title.lower().split(' ')):
        if i == 0 or (out and out[-1].endswith('.')):
            w = cap(w)
        # Each part of a joined name: Syro-Phoenician.
        w = '-'.join(cap(p) if core(p) in PROPER
                     or (core(p) == 'mark' and out and out[-1] == 'John') else p
                     for p in w.split('-'))
        out.append(w)
    out = ' '.join(out)
    for low, cap in TITLES:
        out = out.replace(low, cap)
    return out


for s in sections:
    s['heading'] = sentence(s['title'])
    s['setting'] = [sentence(x) if x.isupper() else x for x in s['setting']]
for p in parts:
    p['heading'] = sentence(p['title'])

# ── The opening's quotations, checked word for word ───────────────────────
OPENING = [
    ('irenaeus', 'Irenaeus, Against Heresies III.11.8 (ANF 1)',
     'it is fitting that she should have four pillars … the Word … has given us '
     'the Gospel under four aspects, but bound together by one Spirit.'),
    ('carpianus', 'Eusebius, Letter to Carpianus (tr. Mark DelCogliano)',
     'in order that you may be able to know where each evangelist wrote passages '
     'in which they were led by love of truth to speak about the same things'),
]


def checked(src, cite, text):
    path = os.path.join(SRC, 'texts', src + '.txt')
    if not os.path.exists(path):
        warnings.append(f'{src}: not fetched, quotation unchecked')
        return {'cite': cite, 'text': text}
    body = ' '.join(open(path, encoding='utf-8').read().split())
    body = re.sub(r'(?<=[a-z]) \d{1,2}(?= [a-z])', '', body)   # footnote marks
    at = 0
    for piece in text.split('…'):
        piece = ' '.join(piece.split()).strip(' ,;')
        i = body.find(piece, at)
        if i < 0:
            errors.append(f'{src}: quotation not found: {piece[:60]}…')
            break
        at = i + len(piece)
    return {'cite': cite, 'text': text}


opening = [checked(*q) for q in OPENING]

data = {
    'schema': 1,
    'sources': {
        'robertson': 'A. T. Robertson, A Harmony of the Gospels for Students of the Life of '
                     'Christ (1922), after Broadus; Project Gutenberg #36264; public domain',
        'eusebius': 'Eusebian canons, INTF via CrossWire modules Eusebian_vs / Eusebian_num; '
                    'public domain',
    },
    'versification': 'KJV',
    'opening': opening,
    'kinds': KINDS,
    'parts': parts, 'groups': groups, 'sections': sections, 'similar': similar,
    'eusebius': sorted(eus.values(), key=lambda e: (e['id'].split('.')[0], int(e['id'].split('.')[1]))),
    'links': links, 'only_here': only_here,
    'no_section': {f'{b} {c}:{v}': {'attach_to': s, 'why': 'not in the Revised Version Robertson printed'}
                   for (b, c, v), s in RV_OMITS.items()},
}
for e in data['eusebius']:
    e.pop('osis', None)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
print('wrote', os.path.relpath(OUT))
