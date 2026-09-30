#!/usr/bin/env python3
"""Build data/place_names/{es,ru}.tsv: each Bible place under the name a
Spanish or Russian Bible gives it, and its modern site's name in that language.

    tools/build_place_names.py --inputs DIR --review DIR

DIR holds, unzipped where zipped:

  ancient.jsonl  OpenBible's places and the verses that name them (CC BY 4.0):
      https://raw.githubusercontent.com/openbibleinfo/Bible-Geocoding-Data/main/data/ancient.jsonl
  modern.jsonl   OpenBible's modern sites, with their Wikidata items:
      https://raw.githubusercontent.com/openbibleinfo/Bible-Geocoding-Data/main/data/modern.jsonl
  rv1909/        eBible's Reina-Valera 1909 USFM, Strong's-tagged, Public Domain:
      https://ebible.org/Scriptures/spaRV1909_usfm.zip
  russyn/        eBible's Russian Synodal USFM, Public Domain:
      https://ebible.org/Scriptures/russyn_usfm.zip
  rlob/          Door43 ru_gl/ru_rlob, aligned, CC BY-SA 4.0 — only a guide to
      which Synodal word is the name; no rlob word reaches the table:
      https://git.door43.org/ru_gl/ru_rlob/archive/master.zip
  wikidata_modern.json  en/es/ru labels of the modern sites' Wikidata items
      (CC0); fetched and written there when missing.

It also reads the installed interlinear databases (TAHOT/TAGNT), which tie a
place's English name to the Hebrew or Greek word in each of its verses.

The name is the Bible's own. Spanish: the words the Reina-Valera 1909 tags
with that Hebrew or Greek word, as printed, and they must stand in the verse.
Russian: the word in the Synodal text of the same verse that the Russian
Literal Open Bible's rendering points to, folded to the nominative, and the
folded form must itself stand somewhere in the Synodal text. A name that fails
a check, or that the verses disagree on, goes to the review list, never into
the table; the app keeps the English name for it.

The modern name is the Wikidata label of the site OpenBible names, used only
when that item's English label is the name OpenBible gives the site; else the
app keeps the English.

Russian needs `pymorphy3` (MIT) at build time only.
"""
import argparse
import collections
import difflib
import glob
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ebible_bridge import _BOOK  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'place_names')
RENDERINGS = os.path.join(ROOT, 'data', 'renderings')
INTERLINEAR = os.path.expanduser('~/.local/share/bible-reader/open_data')

#: The top form must carry this share of the verses that gave one.
AGREE = 0.6

#: A one-word Spanish name must spell at least this much like the English
#: (difflib ratio, accents dropped). Below it the tag sat on a neighbour
#: ("Hadid" → "Ono"), or the Bible translated the name ("Cush" →
#: "Etiopía"): both go to review.
LIKE = 0.5

#: English words that are not part of what a name means.
EN_STOP = {'of', 'the', 'a', 'an', 'and'}

#: Spanish words allowed inside a name and stripped from its edges.
ES_STOP = {'el', 'la', 'los', 'las', 'lo', 'de', 'del', 'a', 'á', 'al', 'en',
           'y', 'e', 'o', 'u'}

_STRONG = re.compile(r'([GH])0*(\d+)')


def strong_key(raw):
    """'H01035' / 'G2542' / 'G45160' (UGNT's five digits) → 'H1035' /
    'G2542' / 'G4516'."""
    m = _STRONG.search(raw)
    if not m:
        return None
    n = int(m.group(2))
    if m.group(1) == 'G' and len(m.group(0)) - 1 == 5 and n % 10 == 0:
        n //= 10
    return f'{m.group(1)}{n}'


def key(text):
    return re.sub(r'[^a-z]', '', text.lower())


def display(name):
    """OpenBible's 'Aphek 2' → 'Aphek', as the app shows it."""
    return re.sub(r'\s+\d+$', '', name)


def content_words(name):
    """The words of an English name that carry meaning: 'Valley of Aijalon'
    → ['Valley', 'Aijalon']. A hyphen joins one word: 'Abel-meholah'."""
    return [w for w in re.sub(r'’s\b', '', name).split()
            if w.lower() not in EN_STOP]


def matches(word, lemma_gloss):
    """Does an interlinear token's lemma gloss name this English word?
    'Salt( Sea)' names Salt; 'Beth-lehem' names Bethlehem; 'Jabesh' names
    part of Jabesh-gilead. 'Jebusite' does not name Jebus."""
    w, g = key(word), key(lemma_gloss)
    if not w or not g:
        return False
    first = key(re.split(r'[\s(;]', lemma_gloss.strip())[0])
    return g == w or first == w or (len(g) > 3 and w.startswith(g))


# ── USFM ────────────────────────────────────────────────────────────────────

def usfm_verses(paths):
    """{(BOOK, chapter, verse): the verse's USFM}."""
    out = {}
    for path in paths:
        text = open(path, encoding='utf-8').read()
        code = re.search(r'\\id (\w+)', text).group(1)
        for cm in re.finditer(r'\\c (\d+)(.*?)(?=\\c \d+|\Z)', text, re.S):
            for vm in re.finditer(r'\\v (\d+)\S*(.*?)(?=\\v \d+|\Z)', cm.group(2), re.S):
                out[(code, int(cm.group(1)), int(vm.group(1)))] = vm.group(2)
    return out


def rv1909_items(usfm):
    """A verse → [(words, {strong}, text before the item)]."""
    usfm = re.sub(r'\\f .*?\\f\*', '', usfm, flags=re.S)
    out, last = [], 0
    for m in re.finditer(r'\\\+?w ([^|\\]+)\|([^\\]*)\\\+?w\*', usfm):
        st = re.search(r'strong="([^"]+)"', m.group(2))
        keys = {strong_key(x) for x in re.split(r'[,\s]+', st.group(1))} if st else set()
        out.append((m.group(1).split(), keys - {None}, usfm[last:m.start()]))
        last = m.end()
    return out


def plain(usfm):
    """A verse's words with the markup gone."""
    usfm = re.sub(r'\\f .*?\\f\*', '', usfm, flags=re.S)
    usfm = re.sub(r'\|[^\\]*\\\+?w\*', '', usfm)
    usfm = re.sub(r'\\\+?\w+\*?', ' ', usfm)
    return ' '.join(usfm.split())


def aligned_words(usfm):
    """Door43 aligned USFM → {strong: [words]} for one verse."""
    out = collections.defaultdict(list)
    stack = []
    for m in re.finditer(r'\\zaln-s \|([^\\]*)\\\*|\\zaln-e\\\*|\\w ([^|\\]+)\|', usfm):
        if m.group(1) is not None:
            s = re.search(r'x-strong="([^"]+)"', m.group(1))
            stack.append(strong_key(s.group(1)) if s else None)
        elif m.group(2) is not None:
            for k in stack:
                if k:
                    out[k].append(m.group(2))
        elif stack:
            stack.pop()
    return out


def read_renderings(lang):
    """data/renderings/{lang}.tsv → {strong: {one-word rendering}}. Longer
    renderings carry the words around the word ("desde Havila") and would
    let them into a name."""
    table = {}
    with open(os.path.join(RENDERINGS, f'{lang}.tsv'), encoding='utf-8') as f:
        for line in f:
            if not line.startswith('#'):
                k, words = line.rstrip('\n').split('\t')
                table[k] = {r for r in words.split(' | ') if ' ' not in r}
    return table


# ── Which Hebrew or Greek words the name is ─────────────────────────────────

def refs(place):
    """A place's verses as (BOOK, chapter, verse)."""
    out = []
    for v in place.get('verses') or []:
        code, cv = v['usx'].split()
        c, vv = cv.split(':')
        out.append((code, int(c), int(vv)))
    return out


def strongs_for(place, tokens):
    """Each content word of the name → the Strong's number its verses vote
    for, as [(strong, whole)]. `tokens(ref)` gives [(strong, lemma_gloss)]
    for a verse. A one-word name matches on the whole name; a longer one word
    by word, and the name counts only when every word found a number."""
    name = display(place['friendly_id'])
    words = content_words(name)
    if len(words) <= 1:
        found = vote(place, tokens, [name])
        # 'Jabesh-gilead' is two Hebrew words; the first alone names only
        # part of it, so its parts are tried as words of their own.
        if found and '-' in name and not found[0][1]:
            return vote(place, tokens, name.split('-')) or found
        return found
    return vote(place, tokens, words)


def vote(place, tokens, words):
    """[(strong, whole)] — whole when the token's gloss is the entire word
    rather than a part of it — or [] when a word found no number."""
    votes = {w: collections.Counter() for w in words}
    whole = set()
    for ref in refs(place):
        for strong, gloss in tokens(ref):
            for w in words:
                if matches(w, gloss):
                    votes[w][strong] += 1
                    if key(gloss) == key(w):
                        whole.add(strong)
    if not all(votes.values()):
        return []
    top = dict.fromkeys(votes[w].most_common(1)[0][0] for w in words)
    return [(k, k in whole) for k in top]


# ── Spanish ─────────────────────────────────────────────────────────────────

#: Between two words, any of these means the second opens a sentence, where
#: every word has a capital, name or not.
_OPENS = re.compile(r'[.!?¿¡:;]')


def spanish_in_verse(items, wanted, rendered):
    """The Reina-Valera's name in one verse, and whether it is printed as a
    name: the shortest run of tagged items that holds every wanted number,
    each wanted item cut to the words the Bible uses for that number (a
    one-word rendering, or a capitalised word mid-sentence), the items
    between allowed only as function words."""
    best = None
    for i, (_w, ks, _b) in enumerate(items):
        if not ks & wanted:
            continue
        seen = set()
        for j in range(i, len(items)):
            seen |= items[j][1] & wanted
            if seen == wanted:
                if best is None or j - i < best[1] - best[0]:
                    best = (i, j)
                break
    if best is None:
        return None, False
    i, j = best
    out, named = [], False
    for n in range(i, j + 1):
        words, ks, before = items[n]
        if n > i and re.search(r'[^\W\d_]', before):
            return None, False
        hit = ks & wanted
        opens = n == 0 or bool(_OPENS.search(before))
        for w in words:
            bare = re.sub(r'[^\w\-’]', '', w)
            if not bare:
                continue
            if not hit:
                if bare.lower() not in ES_STOP:
                    return None, False
                out.append(bare)
            else:
                known = set().union(*(rendered.get(k, set()) for k in hit))
                if bare in known or (bare[:1].isupper() and not opens):
                    out.append(bare)
                    named = named or bare[:1].isupper()
                elif bare.lower() in {r.lower() for r in known}:
                    out.append(bare)
                elif out and bare.lower() in ES_STOP:
                    out.append(bare)
            opens = False
    while out and out[0].lower() in ES_STOP:
        out.pop(0)
    while out and out[-1].lower() in ES_STOP:
        out.pop()
    return ' '.join(out) or None, named


def upper_first(name):
    return name[:1].upper() + name[1:]


def stands_in(name, text):
    """Is the name in the text as words, ignoring the first letter's case?"""
    body = re.escape(name[1:])
    pattern = rf'(?<!\w)[{re.escape(name[0].upper())}{re.escape(name[0].lower())}]{body}(?!\w)'
    return re.search(pattern, text) is not None


def spanish_name(place, wanted, verses, rendered):
    """(name, None) or (best guess, why it goes to review)."""
    forms, common = collections.Counter(), collections.Counter()
    for ref in refs(place):
        usfm = verses.get(ref)
        if not usfm:
            continue
        form, named = spanish_in_verse(rv1909_items(usfm), set(wanted), rendered)
        if form and stands_in(form, plain(usfm)):
            (forms if named else common)[upper_first(form)] += 1
    if not forms and common:
        return common.most_common(1)[0][0], 'printed as a common word, not a name'
    if not forms:
        return None, 'not found in its verses'
    top, why = verdict(forms)
    english = display(place['friendly_id'])
    if not why and len(content_words(english)) == 1 and likeness(english, top) < LIKE:
        why = f'spelled unlike {english}'
    return top, why


def likeness(a, b):
    def bare(s):
        s = unicodedata.normalize('NFD', s.lower())
        return re.sub(r'[^a-z]', '', s)
    return difflib.SequenceMatcher(None, bare(a), bare(b)).ratio()


def verdict(forms):
    top, n = forms.most_common(1)[0]
    if n / sum(forms.values()) < AGREE:
        return top, 'verses disagree: ' + ', '.join(f'{f} ×{c}' for f, c in forms.most_common(4))
    return top, None


# ── Russian ─────────────────────────────────────────────────────────────────

def fold_e(word):
    return word.lower().replace('ё', 'е')


def stem_of(word):
    """The part of a Russian word that its case endings leave alone."""
    w = fold_e(word)
    return w[:max(3, len(w) - 2)]


def synodal_tokens(text):
    return re.findall(r'[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*', text)


_EN_PAIRS = (('th', 'f'), ('ph', 'f'), ('sh', 's'), ('ch', 'h'), ('kh', 'h'),
             ('tz', 's'), ('ts', 's'), ('x', 'ks'), ('qu', 'kv'), ('ck', 'k'))
_EN_ONE = str.maketrans({'z': 's', 'j': 'i', 'y': 'i', 'w': 'v', 'b': 'v', 'q': 'k'})
_RU_ONE = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                   ['a', 'v', 'v', 'g', 'd', 'e', 'e', 's', 's', 'i', 'i', 'k',
                    'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f', '', 's',
                    'h', 's', 's', '', 'i', '', 'e', 'iu', 'ia']))

#: An English and a Synodal name that sound at least this alike (difflib
#: ratio over a coarse spelling of each) are taken as one. Over the names
#: the rlob guide found, 99% of right pairs reach it and 2% of random ones.
SOUND = 0.6


def sound_en(name):
    """'Beth-shemesh' → 'vetsemes': a spelling that the Synodal's Greek-born
    forms («Вефсамис») can be compared with. h drops: Hazor is «Асор»."""
    s = re.sub(r'[^a-z]', '', unicodedata.normalize('NFD', name.lower()))
    for a, b in _EN_PAIRS:
        s = s.replace(a, b)
    s = re.sub(r'c(?=[eiy])', 's', s).replace('c', 'k')
    s = s.translate(_EN_ONE).replace('h', '')
    return re.sub(r'(.)\1+', r'\1', s)


def sound_ru(word):
    s = ''.join(_RU_ONE.get(c, '') for c in word.lower())
    return re.sub(r'(.)\1+', r'\1', s)


def sounds_like(english, word):
    """The better of the word as printed and with a case ending off."""
    low = fold_e(word)
    forms = [low] + [low[:-len(e)] for e in ENDINGS if low.endswith(e) and len(low) > len(e) + 1]
    return max(difflib.SequenceMatcher(None, sound_en(english), sound_ru(f)).ratio()
               for f in forms)


def russian_in_verse(tokens, guides):
    """The Synodal words for the name in one verse: for each content word, a
    token sharing a stem with one of its guide spellings and not much longer
    («Нетофафянин» is a man from Нетофа); the tokens must sit together (at
    most one word between neighbours)."""
    at = []
    for forms in guides:
        stems = {(stem_of(g), len(g)) for g in forms if len(g) > 1}
        hits = [i for i, t in enumerate(tokens)
                if any(fold_e(t).startswith(s) and len(t) <= n + 3 for s, n in stems)]
        if not hits:
            return None
        at.append(hits)
    best = None
    for first in at[0]:
        chosen = [first]
        for hits in at[1:]:
            near = [h for h in hits if abs(h - chosen[-1]) <= 2 and h not in chosen]
            if not near:
                break
            chosen.append(near[0])
        else:
            lo, hi = min(chosen), max(chosen)
            if hi - lo <= len(chosen) and (best is None or hi - lo < best[1] - best[0]):
                best = (lo, hi)
    if best is None:
        return None
    return tokens[best[0]:best[1] + 1]


#: Russian case endings, longest first: what is left when one comes off is
#: the base a name's other forms share.
ENDINGS = ('ами', 'ями', 'ою', 'ею', 'ом', 'ем', 'ой', 'ей', 'ам', 'ям',
           'ах', 'ях', 'ов', 'ев', 'а', 'я', 'у', 'ю', 'е', 'и', 'ы')
_VOWELS = set('аеёиоуыэюяй')

#: A word the name was made into: «Елласарский» (of Ellasar),
#: «Филистимлян» (Philistines).
_DERIVED = re.compile(r'(ск(ий|ая|ое|ие|ого|ой|ую|им|их|ом|ою)|[яа]н|[яа]не)$')

#: Endings only a plural name takes: «в Афинах».
_PLURAL = ('ах', 'ях', 'ами', 'ями')

#: Endings only a feminine name in -а/-я takes: «Рамою». «Раму» is no
#: sign: «к Риммону» is a masculine dative.
_FEMININE = ('ою', 'ею', 'ой')
#: Endings only a masculine name takes: «Сихемом», «Сихему» is shared.
_MASCULINE = ('ом', 'ем', 'ов', 'ев')


def name_nominative(word, names, own, english):
    """One Synodal word → (the name's nominative, sure). `names` holds the
    words the Synodal text prints with a capital — names, not «мор» for
    Moreh; `own` every word printed in the place's own verses.

    Sure when the text prints the nominative as a name, or when the place's
    own verses show an ending only one gender takes: «Мигдолом» → «Мигдол»
    though «Мигдол» is never printed, «Рамою» → «Рама». The analyser is not
    asked: its places are modern ones («Раме» → the Рам, «Мадона» in Latvia),
    and it reads «Луза» as the billiard word.

    Forms in -а/-е alone say nothing: «до Лаккума» is a masculine genitive,
    «Азека» a feminine nominative. There the English name decides — the
    Hebrew feminine ends in -ah, as Azekah and Ramah do and Lakkum does not —
    and the result is sure only if the text prints it; otherwise it is the
    best guess for review."""
    if _DERIVED.search(fold_e(word)):
        return None, False
    low = fold_e(word)
    heard = sound_en(english)
    # A last i, o or u the English name also ends with, on the same sound
    # before it, is part of the name: «Хали» is Hali, not «Хал» + -и; «в
    # Беф-Биреи» is not Beth-biri. Not an e, a y or an h: «Риме»,
    # «Вифании» and «Гиаха» are not the nominatives of Rome, Bethany, Giah.
    if low[-1] in 'иоу' and english[-1:].lower() == _RU_ONE.get(low[-1]) \
            and sound_ru(low)[-2:] == heard[-2:] and low in names:
        return low, True
    # An ending the English name also ends with is part of the name:
    # «Рекем» is Rekem, not «Рек» + -ем; «Сеном» is Shen's, so off it comes.
    endings = [e for e in ENDINGS if low.endswith(e) and len(low) - len(e) >= 2]
    cut = [e for e in endings if not (len(e) > 1 and heard.endswith(sound_ru(e)))]
    bases = [low[:-len(e)] for e in cut]
    if (low[-1] not in _VOWELS or low[-1] in 'оь') and not any(len(e) > 1 for e in cut):
        bases.insert(0, low)
    # Hebrew feminines end in -ah; a final -ah over a guttural does not make
    # one: Tappuah is «Таппуах», Giah «Гиах».
    feminine = (re.search(r'ah?$', english.lower()) is not None
                and not re.search(r'[aiou]ah$', english.lower()))
    guess = None
    for base in bases:
        forms = {t[len(base):] for t in own if t.startswith(base) and len(t) - len(base) <= 3}
        # A gender ending counts wherever the text prints the name, when it
        # agrees with the English: Ezekiel has only «от Мигдола», Numbers
        # «пред Мигдолом». Against the English it may be another name on the
        # same letters: «Ваалом» is Baal, not Baalah.
        wide = {e for e in _FEMININE + _MASCULINE if base + e in names}
        forms |= wide & set(_FEMININE if feminine else _MASCULINE)
        masc = base[-1] not in _VOWELS or base[-1] in 'оь'
        base_nom = base
        if masc and base not in names:
            # «Изрееля» → «Изреель»; «Египта» → «Египет», a vowel that
            # drops out of every form but the nominative.
            for t in (base + 'ь', base[:-1] + 'е' + base[-1], base[:-1] + 'о' + base[-1]):
                if t in names:
                    base_nom = t
                    break
        if forms & set(_PLURAL):
            plural = next((base + e for e in ('ы', 'и') if base + e in names), None)
            if plural:
                return plural, True
        fem = [base + 'я', base + 'а'] if base[-1] == 'и' else [base + 'а', base + 'я']
        if forms & set(_FEMININE):
            return next((t for t in fem if t in names), fem[0]), True
        if masc and forms & set(_MASCULINE):
            return base_nom, True
        if masc and not feminine and forms & {'', 'ь'} and base_nom in names:
            return base_nom, True
        if base[-1] == 'и':          # «Вифании» is Вифания, whatever the English
            tries = [base + 'я', base + 'й']
        else:
            tries = fem if feminine else [base_nom] if masc else [base + 'й']
        for t in tries:
            if t in names:
                return t, True
        guess = guess or tries[0]
    return guess, False


def cased(new, old):
    """`new` with the capitals `old` had, part by part: «Беф-Шемеш»."""
    parts, olds = new.split('-'), old.split('-')
    olds += olds[-1:] * len(parts)
    return '-'.join(p[:1].upper() + p[1:] if o[:1].isupper() else p
                    for p, o in zip(parts, olds))


def phrase_nominative(words, morph):
    """Synodal words → the phrase in the nominative: its noun folds and the
    adjectives agree with it, «города Давидова» → «город Давидов»."""
    parses = [morph.parse(w)[0] for w in words]
    noun = next((p for p in parses if p.tag.POS == 'NOUN'), None)
    if noun is None:
        return ' '.join(words)
    head = noun.inflect({'nomn'}) or noun
    out = []
    for w, p in zip(words, parses):
        if p is noun:
            out.append(cased(head.word, w))
        elif p.tag.POS in ('ADJF', 'PRTF'):
            want = {'nomn', head.tag.number or 'sing'}
            if head.tag.number != 'plur' and head.tag.gender:
                want.add(head.tag.gender)
            q = p.inflect(want)
            out.append(cased(q.word, w) if q else w)
        else:
            out.append(w)
    return ' '.join(out)


def russian_name(place, wanted, synodal, rlob, rendered, printed, morph):
    """(name, None) or (best guess or None, why it goes to review).
    `printed` is printed_forms() of the Synodal text."""
    printed, names = printed
    english = display(place['friendly_id'])
    single = len(content_words(english)) <= 1
    forms, own = collections.Counter(), set()
    for ref in refs(place):
        usfm = synodal.get(ref)
        if not usfm:
            continue
        tokens = synodal_tokens(plain(usfm))
        own.update(fold_e(t) for t in tokens)
        aligned = aligned_words(rlob.get(ref, ''))
        guides = [aligned.get(k) or sorted(rendered.get(k, ())) for k in wanted]
        if single:
            # A name's guide is a name: rlob aligns «из» with Egypt too.
            guides = [[g for g in forms if g[:1].isupper()] for forms in guides]
        if all(guides):
            words = russian_in_verse(tokens, guides)
        elif single:
            # No rlob in this book and no rendering for the number: the
            # capitalised word that sounds most like the English name.
            scored = [(sounds_like(english, t), t) for t in tokens[1:] if t[:1].isupper()]
            best = max(scored, default=(0, None))
            words = [best[1]] if best[0] >= SOUND else None
        else:
            words = None
        if words:
            forms[tuple(words)] += 1
    if not forms:
        return None, 'no Synodal word matched'
    folded = collections.Counter()
    for words, n in forms.items():
        if len(words) == 1:
            name, sure = name_nominative(words[0], names, own, english)
            name = cased(name, words[0]) if name else None
            guess = name
            name = name if sure else None
        else:
            name = phrase_nominative(list(words), morph)
            guess = name
            name = name if fold_e(name) in printed else None
        folded[name or '?' + (guess or ' '.join(words))] += n
    top, why = verdict(folded)
    if top.startswith('?'):
        return top[1:], 'nominative not printed in the Synodal text'
    if len(wanted) == 1 and not top[:1].isupper():
        return top, 'printed as a common word, not a name'
    if not why and single and sounds_like(english, top) < SOUND:
        why = f'sounds unlike {english}'
    return upper_first(top), why


def printed_forms(synodal):
    """({every word and two-word phrase the Synodal text prints},
    {the words it prints with a capital, not after a full stop}), folded."""
    out, names = set(), set()
    for usfm in synodal.values():
        text = plain(usfm)
        toks = [fold_e(t) for t in synodal_tokens(text)]
        out.update(toks)
        out.update(f'{a} {b}' for a, b in zip(toks, toks[1:]))
        # A verse's first word counts: lists of towns open verses. A word
        # after a full stop does not.
        for m in re.finditer(r'(?<![.!?] )(?<![.!?])\b[А-ЯЁ][а-яё]+(?:-[А-Яа-яЁё]+)*', text):
            names.add(fold_e(m.group(0)))
    return out, names


# ── Modern names ────────────────────────────────────────────────────────────

def best_modern(place):
    """The modern site the app shows for a place: the highest-scored one."""
    assoc = place.get('modern_associations') or {}
    if not assoc:
        return None, None
    mid, best = max(assoc.items(), key=lambda kv: kv[1].get('score', 0) or 0)
    return mid, best.get('name')


def site_qids(site):
    out = []
    source = site.get('coordinates_source') or {}
    if source.get('type') == 'wikidata':
        out.append(source['id'])
    out += [s['id'] for s in site.get('secondary_sources') or []
            if s.get('type') == 'wikidata' and s['id'] not in out]
    return out


def modern_label(name, qids, labels, lang):
    """The site's name in `lang`, from the first Wikidata item whose English
    label is the name OpenBible gives the site. An item for the ancient place
    carries the Bible's name, not the site's ("Abel-beth-maachah" for Tel
    Abel Beth Maacah), and its label would print the ancient name twice."""
    for q in qids:
        item = labels.get(q) or {}
        if key(item.get('en', '')) == key(name) and item.get(lang):
            return item[lang]
    return None


def fetch_labels(qids, path):
    labels = {}
    qids = sorted(set(qids))
    for i in range(0, len(qids), 50):
        url = 'https://www.wikidata.org/w/api.php?' + urllib.parse.urlencode({
            'action': 'wbgetentities', 'ids': '|'.join(qids[i:i + 50]),
            'props': 'labels', 'languages': 'en|es|ru', 'format': 'json'})
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Scriptura-build (https://github.com/andresmessina-SDG/scriptura)'})
        with urllib.request.urlopen(req, timeout=60) as r:
            for q, item in json.load(r)['entities'].items():
                labels[q] = {lang: v['value'] for lang, v in (item.get('labels') or {}).items()}
        time.sleep(0.3)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(labels, f, ensure_ascii=False, indent=0)
    return labels


# ── Output ──────────────────────────────────────────────────────────────────

def write(path, header, rows):
    with open(path, 'w', encoding='utf-8') as f:
        for line in header:
            f.write(f'# {line}\n')
        for row in sorted(rows):
            f.write('\t'.join(c or '' for c in row) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--inputs', required=True)
    ap.add_argument('--review', required=True)
    ap.add_argument('--interlinear', default=INTERLINEAR)
    args = ap.parse_args()
    src = args.inputs

    def usfm(sub):
        files = sorted(glob.glob(os.path.join(src, sub, '**', '*.usfm'), recursive=True))
        if not files:
            sys.exit(f'no USFM under {os.path.join(src, sub)}')
        return usfm_verses(files)

    places = [json.loads(line) for line in open(os.path.join(src, 'ancient.jsonl'))]
    sites = {s['id']: s for s in map(json.loads, open(os.path.join(src, 'modern.jsonl')))}
    labels_path = os.path.join(src, 'wikidata_modern.json')
    if os.path.exists(labels_path):
        labels = json.load(open(labels_path, encoding='utf-8'))
    else:
        labels = fetch_labels([q for s in sites.values() for q in site_qids(s)], labels_path)

    dbs = [sqlite3.connect(os.path.join(args.interlinear, f'interlinear_{t}.sqlite'))
           for t in ('hebrew', 'greek')]

    def tokens(ref):
        book = _BOOK.get(ref[0])
        out = []
        for db in dbs:
            for s, g in db.execute('SELECT strongs, lemma_gloss FROM words '
                                   'WHERE book=? AND chapter=? AND verse=?',
                                   (book, ref[1], ref[2])):
                k = strong_key(s)
                if k:
                    out.append((k, g))
        return out

    rv1909, synodal, rlob = usfm('rv1909'), usfm('russyn'), usfm('rlob')
    es_rendered, ru_rendered = read_renderings('es'), read_renderings('ru')

    import pymorphy3
    morph = pymorphy3.MorphAnalyzer()
    printed = printed_forms(synodal)

    tables = {'es': [], 'ru': []}
    review = []
    for place in places:
        pid, name = place['id'], display(place['friendly_id'])
        wanted = [k for k, _whole in strongs_for(place, tokens)] if place.get('verses') else []
        mid, modern = best_modern(place)
        qids = site_qids(sites.get(mid, {}))
        for lang in ('es', 'ru'):
            if not wanted:
                bible, why = None, 'no Hebrew or Greek word found for the name'
            elif lang == 'es':
                bible, why = spanish_name(place, wanted, rv1909, es_rendered)
            else:
                bible, why = russian_name(place, wanted, synodal, rlob,
                                          ru_rendered, printed, morph)
            if why and place.get('verses'):
                review.append((lang, pid, name, bible or '', why))
                bible = None
            site = modern_label(modern, qids, labels, lang) if modern else None
            if bible or site:
                tables[lang].append((pid, bible, site))

    os.makedirs(OUT, exist_ok=True)
    common = ['Columns: OpenBible place id, the Bible\'s name, the modern site\'s name.',
              'An empty column means the app keeps the English.',
              'Places: OpenBible Bible Geocoding Data, CC BY 4.0.',
              'Modern names: Wikidata labels, CC0.',
              'Built by tools/build_place_names.py. Do not edit by hand.']
    write(os.path.join(OUT, 'es.tsv'),
          ['Bible places as the Reina-Valera 1909 names them (Public Domain).'] + common,
          tables['es'])
    write(os.path.join(OUT, 'ru.tsv'),
          ['Bible places as the Russian Synodal Bible names them (Public Domain),',
           'the word found with the Russian Literal Open Bible\'s alignment (CC BY-SA 4.0).'] + common,
          tables['ru'])
    os.makedirs(args.review, exist_ok=True)
    write(os.path.join(args.review, 'place_names_review.tsv'),
          ['lang, place id, English name, best guess, why it is not in the table'],
          review)
    for lang in ('es', 'ru'):
        rows = tables[lang]
        print(f'{lang}: {sum(1 for r in rows if r[1])} Bible names, '
              f'{sum(1 for r in rows if r[2])} modern names, '
              f'{sum(1 for r in review if r[0] == lang)} to review')


if __name__ == '__main__':
    main()
