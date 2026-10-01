# Extracts witness references into witnesses.json. The large sources are not in
# the repository; to rebuild, put them in src/ first:
#   oc.txt — `pdftotext -layout` of An Orthodox Creed (1679),
#       https://baptiststudiesonline.com/wp-content/uploads/2007/02/orthodox-creed.pdf
#   westminster_larger_catechism.json, westminster_confession_of_faith.json —
#       from https://github.com/NonlinearFruit/Creeds.json (the 1648/1647 proofs)
#   leo_refs.json — Leo's Tome (newadvent.org/fathers/3604028.htm), kept in src/.
#   cyril_refs.json, philaret_refs.json — the references printed in Cyril's
#       Catechetical Lectures 3, 6-18 (newadvent.org/fathers/3101*.htm) and in
#       Philaret's Longer Catechism, "On the First Article" … "Twelfth"
#       (pravoslavieto.com), kept in src/.
#
#   {source: {section: [[book, ch, v1, v2], ...]}}
# Sources: Cyril (lecture), Philaret (article), OC = An Orthodox Creed 1679 (article),
# WLC = Westminster Larger Catechism 1648 (question), WCF = Westminster Confession 1647 ("ch.sec").
import json, re
import os
S = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src') + '/'
FULL = ["Genesis","Exodus","Leviticus","Numbers","Deuteronomy","Joshua","Judges","Ruth","1 Samuel","2 Samuel","1 Kings","2 Kings","1 Chronicles","2 Chronicles","Ezra","Nehemiah","Esther","Job","Psalms","Proverbs","Ecclesiastes","Song of Solomon","Isaiah","Jeremiah","Lamentations","Ezekiel","Daniel","Hosea","Joel","Amos","Obadiah","Jonah","Micah","Nahum","Habakkuk","Zephaniah","Haggai","Zechariah","Malachi","Matthew","Mark","Luke","John","Acts","Romans","1 Corinthians","2 Corinthians","Galatians","Ephesians","Philippians","Colossians","1 Thessalonians","2 Thessalonians","1 Timothy","2 Timothy","Titus","Philemon","Hebrews","James","1 Peter","2 Peter","1 John","2 John","3 John","Jude","Revelation"]
OSIS = ["Gen","Exod","Lev","Num","Deut","Josh","Judg","Ruth","1Sam","2Sam","1Kgs","2Kgs","1Chr","2Chr","Ezra","Neh","Esth","Job","Ps","Prov","Eccl","Song","Isa","Jer","Lam","Ezek","Dan","Hos","Joel","Amos","Obad","Jonah","Mic","Nah","Hab","Zeph","Hag","Zech","Mal","Matt","Mark","Luke","John","Acts","Rom","1Cor","2Cor","Gal","Eph","Phil","Col","1Thess","2Thess","1Tim","2Tim","Titus","Phlm","Heb","Jas","1Pet","2Pet","1John","2John","3John","Jude","Rev"]
O2F = dict(zip(OSIS, FULL))

def osis_spans(refs):
    out = []
    for r in refs:
        for part in r.split(','):
            m = re.match(r'(\w+)\.(\d+)(?:\.(\d+))?(?:-(\w+)\.(\d+)(?:\.(\d+))?)?$', part.strip())
            if not m or m.group(1) not in O2F: continue
            b, c = O2F[m.group(1)], int(m.group(2))
            v1 = int(m.group(3) or 1); v2 = v1
            if m.group(4):
                if int(m.group(5)) == c: v2 = int(m.group(6) or 200)
                else: v2 = 200
            elif not m.group(3): v2 = 200
            out.append([b, c, v1, v2])
    return out

W = {}
# Westminster Larger Catechism, by question
wlc = json.load(open(S + 'westminster_larger_catechism.json'))
W['WLC'] = {str(q['Number']): osis_spans([r for p in q.get('Proofs', []) for r in p['References']]) for q in wlc['Data']}
# Westminster Confession, by chapter.section
wcf = json.load(open(S + 'westminster_confession_of_faith.json'))
W['WCF'] = {f"{ch['Chapter']}.{s['Section']}": osis_spans([r for p in s.get('Proofs', []) for r in p['References']]) for ch in wcf['Data'] for s in ch['Sections']}

# An Orthodox Creed (1679): references inside each article's span (footnotes + quoted verses).
ABBR = {"Gen":"Genesis","Ex":"Exodus","Exod":"Exodus","Lev":"Leviticus","Numb":"Numbers","Num":"Numbers","Deut":"Deuteronomy","Josh":"Joshua","Judg":"Judges","Ruth":"Ruth","Sam":"Samuel","Kings":"Kings","Chron":"Chronicles","Neh":"Nehemiah","Job":"Job","Psal":"Psalms","Ps":"Psalms","Psalm":"Psalms","Prov":"Proverbs","Eccl":"Ecclesiastes","Eccles":"Ecclesiastes","Cant":"Song of Solomon","Isa":"Isaiah","Esa":"Isaiah","Jer":"Jeremiah","Lam":"Lamentations","Ezek":"Ezekiel","Dan":"Daniel","Hos":"Hosea","Joel":"Joel","Amos":"Amos","Mic":"Micah","Hab":"Habakkuk","Zeph":"Zephaniah","Hag":"Haggai","Zech":"Zechariah","Zach":"Zechariah","Mal":"Malachi","Mat":"Matthew","Matt":"Matthew","Mar":"Mark","Mark":"Mark","Luk":"Luke","Luke":"Luke","John":"John","Joh":"John","Act":"Acts","Acts":"Acts","Rom":"Romans","Cor":"Corinthians","Gal":"Galatians","Eph":"Ephesians","Ephes":"Ephesians","Phil":"Philippians","Col":"Colossians","Coloss":"Colossians","Thes":"Thessalonians","Thess":"Thessalonians","Tim":"Timothy","Tit":"Titus","Titus":"Titus","Heb":"Hebrews","Jam":"James","James":"James","Pet":"Peter","Jude":"Jude","Rev":"Revelation"}
NUMBERED = {"Samuel","Kings","Chronicles","Corinthians","Thessalonians","Timothy","Peter","John"}
t = open(S + 'oc.txt').read()
lines = t.split('\n')
# Footnote definitions: a line holding only a number, then the reference line(s).
foot, is_foot = [], set()
for i, l in enumerate(lines):
    if re.fullmatch(r'\s+\d{1,3}\s*', l) and i + 1 < len(lines) and lines[i + 1].startswith('          '):
        n = int(l.strip()); body = []
        j = i + 1
        while j < len(lines) and lines[j].startswith('          ') and not re.fullmatch(r'\s+\d{1,3}\s*', lines[j]):
            body.append(lines[j]); is_foot.add(j); j += 1
        is_foot.add(i); foot.append((i, n, ' '.join(body)))
starts = [(i, l.strip()) for i, l in enumerate(lines) if re.match(r'^\s*[IVXL]+\. Article\.?\s*$', l)]
def roman(s):
    v = {'I':1,'V':5,'X':10,'L':50}; n = 0
    for a, b in zip(s, s[1:] + ' '): n += -v[a] if b != ' ' and v[a] < v[b] else v[a]
    return n
pat = re.compile(r'(?:\b(I{1,3}|[123])\s+)?\b([A-Z][a-z]+)\.?\s+(\d+)[.:]\s*(\d+)((?:\s*,\s*\d+)*)(?:\s*[-–]\s*(\d+))?')
def refs_in(seg):
    refs = []
    for pre, bk, c, v, more, to in pat.findall(seg):
        if bk not in ABBR: continue
        name = ABBR[bk]
        if name in NUMBERED:
            num = {'I':'1','II':'2','III':'3'}.get(pre, pre)
            if num: name = f"{num} {name}"
            elif name != 'John': continue
        for x in [int(v)] + [int(y) for y in re.findall(r'\d+', more)]: refs.append([name, int(c), x, x])
        if to: refs.append([name, int(c), int(v), int(to)])
    return refs
OC = {}
for k, (i, head) in enumerate(starts):
    n = roman(head.split('.')[0])
    j = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
    body = '\n'.join(lines[x] for x in range(i, j) if x not in is_foot and 'BaptistTheology' not in lines[x] and 'Page ' not in lines[x])
    marks = {int(m) for m in re.findall(r'(?<=[A-Za-z,;:.)]) (\d{1,3})(?=[ ,;:.]|$)', body, re.M)}
    refs = refs_in(body)
    for m in sorted(marks):
        d = next((txt for li, n2, txt in foot if n2 == m and li > i), None)
        if d: refs += refs_in(d)
    OC[str(n)] = refs
W['OC'] = OC

# Cyril (by lecture) and Philaret (by article): already extracted.
PH = {"Heb.":"Hebrews","Eph.":"Ephesians","Ephes.":"Ephesians","Rom.":"Romans","1 Cor.":"1 Corinthians","2 Cor.":"2 Corinthians","1 Tim.":"1 Timothy","2 Tim.":"2 Timothy","Psalm":"Psalms","Apoc.":"Revelation","Rev.":"Revelation","Matt.":"Matthew","Coloss.":"Colossians","Col.":"Colossians","Gen.":"Genesis","Mal.":"Malachi","Zach.":"Zechariah","2 Kings":"2 Samuel","1 Kings":"1 Samuel","Gal.":"Galatians","Phil.":"Philippians","1 Pet.":"1 Peter","2 Pet.":"2 Peter","Exod.":"Exodus","Ezek.":"Ezekiel","1 Thess.":"1 Thessalonians","2 Thess.":"2 Thessalonians","1 Chron.":"1 Chronicles","Psalm":"Psalms","Songs":"Song of Solomon"}
def plain_spans(refs):
    out = []
    for r in refs:
        m = re.match(r'(.+?) (\d+):([\d,\-– ]+)$', r.strip())
        if not m: continue
        b = PH.get(m.group(1), m.group(1)); c = int(m.group(2))
        for part in re.split(r'[, ]+', m.group(3)):
            if not part: continue
            a, _, z = part.replace('–', '-').partition('-')
            try: out.append([b, c, int(a), int(z or a)])
            except ValueError: pass
    return out
W['Philaret'] = {k: plain_spans(v) for k, v in json.load(open(S + 'philaret_refs.json')).items()}
W['Cyril'] = {k: plain_spans(v) for k, v in json.load(open(S + 'cyril_refs.json')).items()}
# Leo's Tome (449): the references the NPNF edition prints, and the passages
# it quotes word for word, each found in the text; allusions are left out.
W['Leo'] = {k: plain_spans(v) for k, v in json.load(open(S + 'leo_refs.json')).items()}
bad = sorted({r[0] for src in W.values() for sec in src.values() for r in sec if r[0] not in FULL})
json.dump(W, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'witnesses.json'), 'w'))
print({k: (len(v), sum(len(x) for x in v.values())) for k, v in W.items()})
print('unknown book names:', bad)
print('OC 3:', W['OC']['3'][:12]); print('OC 17 count', len(W['OC']['17']), 'OC 38', len(W['OC'].get('38', [])))
