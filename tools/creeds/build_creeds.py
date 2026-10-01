"""Build data/creeds/creeds.json — The Creeds — and check it.

Run from the repository root:  python3 tools/creeds/build_creeds.py

The links are chosen by hand in apostles_data.py, nicene_data.py and
athanasian_data.py. This script adds what a machine can add and checks what a
machine can check, and exits non-zero when any check fails:

  * the phrases of each creed rebuild the 1662 Prayer Book text exactly;
  * every reference has KJV text (`diatheke -b KJV`);
  * every "same words" link shares a word with the creed in its original
    language: a lemma of the Greek New Testament (Scriptura's interlinear,
    TAGNT) for the Nicene, a stem of the Latin Vulgate for the others;
  * a Greek same-words link never sits in a chapter the Greek numbers
    differently from the KJV (2 Corinthians 13, Romans 16 …);
  * a word marked "not in the Bible" is absent from the whole Vulgate;
  * foretold links are Old Testament; disputed lines carry a note.

Witness marks come from witnesses.json (see witnesses.py for its sources).

Needs, on the machine that runs it: the SWORD Python bindings with the KJV
and Vulgate modules installed, and Scriptura's Greek interlinear
(interlinear_greek.sqlite in the app's open_data directory).
"""
import json, os, re, sqlite3, subprocess, sys, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__)) + '/'
sys.path.insert(0, HERE)
import nicene_data, apostles_data, athanasian_data
import quotes as Q
import Sword

OPEN = os.environ.get('SCRIPTURA_OPEN_DATA',
                      os.path.expanduser('~/.local/share/bible-reader/open_data')) + '/'
OUT = os.path.join(HERE, '..', '..', 'data', 'creeds', 'creeds.json')
BOOKS = [("Genesis",50),("Exodus",40),("Leviticus",27),("Numbers",36),("Deuteronomy",34),("Joshua",24),("Judges",21),("Ruth",4),("1 Samuel",31),("2 Samuel",24),("1 Kings",22),("2 Kings",25),("1 Chronicles",29),("2 Chronicles",36),("Ezra",10),("Nehemiah",13),("Esther",10),("Job",42),("Psalms",150),("Proverbs",31),("Ecclesiastes",12),("Song of Solomon",8),("Isaiah",66),("Jeremiah",52),("Lamentations",5),("Ezekiel",48),("Daniel",12),("Hosea",14),("Joel",3),("Amos",9),("Obadiah",1),("Jonah",4),("Micah",7),("Nahum",3),("Habakkuk",3),("Zephaniah",3),("Haggai",2),("Zechariah",14),("Malachi",4),("Matthew",28),("Mark",16),("Luke",24),("John",21),("Acts",28),("Romans",16),("1 Corinthians",16),("2 Corinthians",13),("Galatians",6),("Ephesians",6),("Philippians",4),("Colossians",4),("1 Thessalonians",5),("2 Thessalonians",3),("1 Timothy",6),("2 Timothy",4),("Titus",3),("Philemon",1),("Hebrews",13),("James",5),("1 Peter",5),("2 Peter",3),("1 John",5),("2 John",1),("3 John",1),("Jude",1),("Revelation",22)]
OFF = {}; o = 0
for b, c in BOOKS: OFF[b] = o; o += c
TOTAL, NT0 = o, OFF["Matthew"]
AUTHOR = {"Genesis":"Moses","Exodus":"Moses","Deuteronomy":"Moses","Job":"Job","Proverbs":"Solomon","Isaiah":"Isaiah","Jeremiah":"Jeremiah","Daniel":"Daniel","Micah":"Micah","Jonah":"Jonah","Hosea":"Hosea","Joel":"Joel","Ezekiel":"Ezekiel","2 Samuel":"Nathan","1 Kings":"Solomon","Matthew":"Matthew","Mark":"Mark","Luke":"Luke","John":"John","Acts":"Luke","Romans":"Paul","1 Corinthians":"Paul","2 Corinthians":"Paul","Galatians":"Paul","Ephesians":"Paul","Philippians":"Paul","Colossians":"Paul","1 Thessalonians":"Paul","1 Timothy":"Paul","2 Timothy":"Paul","Titus":"Paul","Hebrews":"the writer of Hebrews","James":"James","1 Peter":"Peter","2 Peter":"Peter","1 John":"John","2 John":"John","Jude":"Jude","Revelation":"John"}
def author(b, c):
    if b == "Psalms": return "David" if c in (2, 16, 22, 68, 110, 139) else "Moses" if c == 90 else "the Psalms"
    return AUTHOR.get(b, b)

# Reference texts: the 1662 wording each creed's phrases must rebuild exactly.
# 1662 words whose sense has moved, glossed from Webster's 1913 Revised
# Unabridged Dictionary (public domain; the SWORD module Webster1913), in
# the sense the creed uses: (word as shown, pattern, meaning).
OLD_WORDS = [
    ("quick", r"\bquick\b", "living"),
    ("Holy Ghost", r"\bHoly Ghost\b", "the Holy Spirit; “ghost” is the old word for spirit"),
    ("confounding", r"\bconfounding\b", "mixing together, so they cannot be told apart"),
    ("incomprehensible", r"\bincomprehensibles?\b", "not held within any limits"),
    ("Godhead", r"\bGodhead\b", "divine nature"),
    ("verity", r"\bverity\b", "truth"),
    ("afore", r"\bafore\b", "before"),
    ("reasonable", r"\breasonable\b", "having reason"),
    ("as touching", r"\bas touching\b", "concerning; with respect to"),
    ("Manhood", r"\bManhood\b", "being human"),
    ("conversion", r"\bconversion\b", "change from one state to another"),
]

REF_EN = {
 "nicene": "I believe in one God the Father Almighty, Maker of heaven and earth, And of all things visible and invisible: And in one Lord Jesus Christ, the only-begotten Son of God, Begotten of his Father before all worlds, God of God, Light of Light, Very God of very God, Begotten, not made, Being of one substance with the Father, By whom all things were made; Who for us men, and for our salvation came down from heaven, And was incarnate by the Holy Ghost of the Virgin Mary, And was made man, And was crucified also for us under Pontius Pilate. He suffered and was buried, And the third day he rose again according to the Scriptures, And ascended into heaven, And sitteth on the right hand of the Father. And he shall come again with glory to judge both the quick and the dead: Whose kingdom shall have no end. And I believe in the Holy Ghost, The Lord and giver of life, Who proceedeth from the Father and the Son, Who with the Father and the Son together is worshipped and glorified, Who spake by the Prophets. And I believe one Catholick and Apostolick Church. I acknowledge one Baptism for the remission of sins. And I look for the Resurrection of the dead, And the life of the world to come. Amen.",
 "apostles": "I believe in God the Father Almighty, Maker of heaven and earth: And in Jesus Christ his only Son our Lord, Who was conceived by the Holy Ghost, Born of the Virgin Mary, Suffered under Pontius Pilate, Was crucified, dead, and buried: He descended into hell; The third day he rose again from the dead; He ascended into heaven, And sitteth on the right hand of God the Father Almighty; From thence he shall come to judge the quick and the dead. I believe in the Holy Ghost; The holy Catholick Church; The Communion of Saints; The Forgiveness of sins; The Resurrection of the body, And the Life everlasting. Amen.",
}

def norm_gr(s):
    s = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in s if not unicodedata.combining(c)).replace('ς', 'σ').strip()
ASSIM = [("ads", "ass"), ("adt", "att"), ("inm", "imm"), ("inr", "irr"), ("conp", "comp"), ("conl", "coll"),
         ("adc", "acc"), ("adf", "aff"), ("adp", "app"), ("conm", "comm")]
def norm_la(w):
    w = w.lower().replace('æ', 'ae').replace('œ', 'oe').replace('j', 'i').replace('v', 'u')
    w = re.sub(r'[^a-z]', '', w).replace('ae', 'e').replace('oe', 'e')
    for a, b in ASSIM:
        if w.startswith(a): w = b + w[len(a):]
    return w
def stem_hit(word, stems):
    w = norm_la(word)
    return any(w.startswith(s) or (len(s) >= 5 and s in w) for s in stems)

def parse(ref):
    m = re.match(r'(.+) (\d+):(\d+)(?:[-–](\d+))?$', ref)
    return m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4) or m.group(3))

def kjv(ref):
    out = subprocess.run(['diatheke', '-b', 'KJV', '-f', 'plain', '-k', ref], capture_output=True, text=True).stdout
    lines = [l for l in out.strip().split('\n') if l and not l.startswith('(KJV')]
    text = re.sub(r'\s+', ' ', ' '.join(re.sub(r'^[\w ]+ \d+:\d+:\s*', '', l) for l in lines)).strip()
    # The KJV prints each epistle's closing note ("Written to the Hebrews
    # from Italy…") inside its last verse, after the Amen; it is not Scripture.
    return re.sub(r'(Amen\.) (?:Written|Unto|It was written|The (?:first|second)) .*$',
                  r'\1', text)

MGR = Sword.SWMgr(); VULG = MGR.getModule('Vulgate')
def vulgate(b, c, v):
    src = Sword.VerseKey(); src.setVersificationSystem('KJV'); src.setText(f"{b} {c}:{v}")
    k = Sword.VerseKey(); k.setVersificationSystem('Vulg'); k.positionFrom(src)
    VULG.setKey(k)
    return VULG.stripText().strip()

GDB = sqlite3.connect(OPEN + 'interlinear_greek.sqlite')
def greek(b, c, v):
    return GDB.execute("select surface, lemma, gloss from words where book=? and chapter=? and verse=? and in_stream=1 order by pos", (b, c, v)).fetchall()

# Verses per chapter in the KJV's own numbering (the Greek and Hebrew data number
# some chapters differently: 2 Corinthians 13 ends at 13 there, 14 in the KJV).
_VK = Sword.VerseKey(); _VK.setVersificationSystem('KJV')
_VC = {}
def vmax(b, c):
    if (b, c) not in _VC:
        _VK.setText(f"{b} {c}:1"); _VC[(b, c)] = _VK.getVerseMax()
    return _VC[(b, c)]
def tpos(b, c, v):
    nt = OFF[b] >= NT0
    base = OFF[b] - (NT0 if nt else 0); n = vmax(b, c)
    return (base + c - 1 + (min(v, n) - 0.5) / n) / ((TOTAL - NT0) if nt else NT0)

W = json.load(open(HERE + 'witnesses.json'))
BAD_WIT = sorted({f"{src} {sec}: {B} {C}:{A}" for src, secs in W.items() for sec, rs in secs.items() for B, C, A, Z in rs
                  if B in OFF and 1 <= C <= dict(BOOKS)[B] and A > vmax(B, C)})
WNAME = {"Cyril": "Cyril", "Philaret": "Philaret", "OC": "Orthodox Creed", "WLC": "Larger Catechism", "WCF": "Westminster"}
def cites(src, secs, b, c, v1, v2):
    for s in secs:
        for B, C, A, Z in W[src].get(s, []):
            if B == b and C == c and not (Z < v1 or A > v2): return True
    return False

# Words anywhere in the Vulgate / Greek NT, for the "not a Bible word" check.
def vulgate_words():
    # popError returns a char: '\x00' means success, and it is truthy.
    words = set(); VULG.setKeyText('Genesis 1:1')
    for _ in range(40000):
        words.update(norm_la(w) for w in VULG.stripText().split())
        VULG.increment()
        e = VULG.popError()
        if (e if isinstance(e, int) else ord(e or '\x00')): break
    return words
NT_LEMMAS = {norm_gr(l) for (l,) in GDB.execute("select distinct lemma from words")}

errors, warns = [], []

# The quotations: each piece between ellipses must stand, in order, in its
# source (fetch_texts.py; src/oc.txt for An Orthodox Creed). Spacing, quote
# marks, case and footnote numbers are set aside on both sides.
def _plain(t):
    t = t.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r' \d{1,3}(?= )', '', t)            # footnote and page numbers
    t = re.sub(r' ?— ?', '—', t)
    t = re.sub(r' (?=[,;:.?!)\]\'"])', '', t)
    return t.casefold()
_SRC = {}
def _source(name):
    if name not in _SRC:
        path = HERE + ('src/oc.txt' if name == 'oc' else f'src/texts/{name}.txt')
        _SRC[name] = _plain(open(path, encoding='utf-8').read()) if os.path.exists(path) else None
    return _SRC[name]
_UNCHECKED = set()
def quoted(q, where):
    src, cite, text = q[:3]
    pieces = q[3] if len(q) > 3 else re.split(r'…|\.\.\.', text)
    body = _source(src)
    if body is None:
        _UNCHECKED.add(src)
    else:
        at = 0
        for piece in pieces:
            piece = _plain(piece).strip(' ,;')
            if not piece:
                continue
            i = body.find(piece, at)
            if i < 0:
                errors.append(f"{where}: quotation not in {src}: …{piece[:60]}…")
                break
            at = i + len(piece)
    return {"cite": cite, "text": text}

out = {"creeds": [], "books": [[b, OFF[b], n] for b, n in BOOKS],
       "bookspan": {b: [round((OFF[b] - (NT0 if OFF[b] >= NT0 else 0)) / ((TOTAL - NT0) if OFF[b] >= NT0 else NT0), 6),
                        round((OFF[b] + n - (NT0 if OFF[b] >= NT0 else 0)) / ((TOTAL - NT0) if OFF[b] >= NT0 else NT0), 6),
                        OFF[b] >= NT0] for b, n in BOOKS}}
VW = None
for cid, mod in (("apostles", apostles_data), ("nicene", nicene_data), ("athanasian", athanasian_data)):
    C = {"id": cid, "title": mod.TITLE, "orig": mod.ORIG, "coined_en": mod.COINED_EN,
         "origin": quoted(Q.ORIGINS[cid], f"{cid} origin"),
         "sections": getattr(mod, "SECTIONS", None), "articles": []}
    for art in mod.ARTICLES:
        n = art["n"]; wit = mod.WITNESS[n]
        A = {"n": n, "phrases": [], "left_out": []}
        for ref, note in art.get("left_out", []):
            A["left_out"].append({"ref": ref, "note": note, "text": kjv(ref)})
            if not note: errors.append(f"{cid} {n}: left-out {ref} has no note")
        for pid, en, orig, keys, links, extra in art["phrases"]:
            P = {"id": pid, "en": en, "orig": orig, "links": [], **extra}
            if "quotes" in extra:
                P["quotes"] = [quoted(q, f"{cid} {pid}") for q in extra["quotes"]]
            old = [[w, m] for w, pat, m in OLD_WORDS if re.search(pat, en)]
            if old:
                P["old"] = old
            if not links: errors.append(f"{cid} {pid}: no links")
            if extra.get("disputed") and not (extra.get("note") or extra.get("quotes")): errors.append(f"{cid} {pid}: disputed without a note")
            for w in mod.COINED_EN.get(pid, []):
                if w not in en: errors.append(f"{cid} {pid}: coined English '{w}' not in the line")
            seen = set()
            keyset = {norm_gr(k) for k in keys.split()} if mod.ORIG == "grc" else [norm_la(k) for k in keys.split()]
            for link in links:
                kind, ref = link[0], link[1]; note = link[2] if len(link) > 2 else ""
                if ref in seen: errors.append(f"{cid} {pid}: {ref} twice")
                seen.add(ref)
                b, c, v1, v2 = parse(ref)
                if b not in OFF: errors.append(f"{cid} {pid}: unknown book {b}"); continue
                text = kjv(ref)
                if not text: errors.append(f"{cid} {pid}: {ref} has no KJV text")
                nt = OFF[b] >= NT0
                if kind == "f" and nt: errors.append(f"{cid} {pid}: foretold link {ref} is in the New Testament")
                L = {"kind": kind, "ref": ref, "book": b, "ch": c, "v": v1, "note": note, "text": text,
                     "author": author(b, c), "nt": nt, "tp": round(tpos(b, c, v1), 6), "witness": []}
                for src, secs in wit.items():
                    if cites(src, secs, b, c, v1, v2): L["witness"].append(WNAME[src])
                if kind == "w":
                    words, shared = [], set()
                    if mod.ORIG == "grc":
                        gmax = GDB.execute("select max(verse) from words where book=? and chapter=?", (b, c)).fetchone()[0]
                        if nt and gmax != vmax(b, c):
                            errors.append(f"{cid} {pid}: {b} {c} is numbered differently in the Greek; map {ref} first")
                        if nt:
                            for v in range(v1, v2 + 1):
                                for s, lem, gl in greek(b, c, v):
                                    hit = norm_gr(lem) in keyset
                                    if hit: shared.add(norm_gr(lem))
                                    words.append([s, 1 if hit else 0, gl])
                    else:
                        for v in range(v1, v2 + 1):
                            for w in vulgate(b, c, v).split():
                                hit = bool(keyset) and stem_hit(w, keyset)
                                if hit: shared.add(norm_la(w)[:5])
                                words.append([w, 1 if hit else 0, ""])
                    L["orig_words"] = words; L["shared"] = len(shared)
                    if shared: L["witness"].append("Word match")
                    else: errors.append(f"{cid} {pid}: same-words link {ref} shares no word")
                P["links"].append(L)
            # coined words are absent from Scripture
            for w, _g in extra.get("coined", []):
                if mod.ORIG == "grc":
                    pass  # Greek coined words were checked against TAGNT lemmas in the echo test
                else:
                    if VW is None: VW = vulgate_words()
                    st = norm_la(w)[:6]
                    if any(x.startswith(st) for x in VW): errors.append(f"{cid} {pid}: coined '{w}' is in the Vulgate")
            A["phrases"].append(P)
        C["articles"].append(A)
    # the phrases rebuild the 1662 text exactly
    if cid in REF_EN:
        got = re.sub(r'\s+', ' ', ' '.join(''.join(p["en"] for p in a["phrases"]) for a in C["articles"])).strip()
        if got != REF_EN[cid]:
            i = next((k for k, (x, y) in enumerate(zip(got, REF_EN[cid])) if x != y), min(len(got), len(REF_EN[cid])))
            errors.append(f"{cid}: phrases differ from the 1662 text at {i}: …{got[max(0,i-30):i+30]}… vs …{REF_EN[cid][max(0,i-30):i+30]}…")
    if cid == "athanasian":
        ref = open(HERE + 'src/athanasian_1662.txt').read().strip().split('\n')
        got = [p["en"] for a in C["articles"] for p in a["phrases"]]
        for k, (x, y) in enumerate(zip(got, ref), 1):
            if x != y: errors.append(f"athanasian {k}: differs from the 1662 text")
        if len(got) != len(ref): errors.append(f"athanasian: {len(got)} lines, 1662 has {len(ref)}")
    out["creeds"].append(C)

out["opening"] = {"why": [quoted(q, "opening") for q in Q.WHY],
                  "words": quoted(Q.WORDS, "opening")}

for w, pat, _m in OLD_WORDS:
    if not any(re.search(pat, p["en"]) for c in out["creeds"] for a in c["articles"] for p in a["phrases"]):
        errors.append(f"old word '{w}' is in no line")

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
    f.write('\n')
for c in out["creeds"]:
    L = [l for a in c["articles"] for p in a["phrases"] for l in p["links"]]
    hist = sum(1 for l in L if any(w != "Word match" for w in l["witness"]))
    print(f"{c['id']:11} lines {sum(len(a['phrases']) for a in c['articles']):3}  links {len(L):3}  "
          f"same words {sum(l['kind']=='w' for l in L):3}  historic witness {hist:3} ({100*hist//max(1,len(L))}%)  "
          f"books {len({l['book'] for l in L})}")
for w in warns: print("WARN", w)
if _UNCHECKED: print("WARN quotations not checked, sources missing (run fetch_texts.py):", ", ".join(sorted(_UNCHECKED)))
if BAD_WIT: print("NOTE witness references past a chapter's end (source misprints or OCR):", "; ".join(BAD_WIT))
for e in errors: print("FAIL", e)
sys.exit(1 if errors else 0)
