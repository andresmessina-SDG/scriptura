#!/usr/bin/env python3
"""Turn the 1890 *Diccionario de la Santa Biblia* into curated dictionary entries.

Why this exists: the Spanish Wiktionary module built by build_spanish_dict.py
is a general dictionary, and on the words a Bible reader double-clicks it
answers as one — `circuncisión` gets a surgical description, `gracia` gets
"predisposición a favorecer o proteger a alguien". This work answers the same
two words with "signo de consagración á Dios, y de purificación" and "el
gratuito é inmerecido amor y favor que Dios se digna tener y ejercer hacia el
pecador". It supplies the register; Wiktionary keeps the long tail of the
language.

The source is W. W. Rand, *Diccionario de la Santa Biblia, para uso general en
el Estudio de las Escrituras*, Sociedad Americana de Tratados (American Tract
Society), Nueva York, 1890 — 838 pages, scanned by the Internet Archive.

On the licence, which is the whole reason this source and not another: the
Spanish text was itself published in 1890, so it is not a modern translation
of a public-domain original — the trap that puts most Spanish editions of old
English works out of reach. Its own term expired long ago, the Library of
Congress records no known restrictions, no translator is named, and Rand died
in 1909.

Three things about the scan decide the shape of this importer:

  * **Running heads look exactly like headwords.** Each page carries its
    alphabetical range alone on a line — a bare "FE" sits above the page about
    the Pharisees. Accepting it would invent an entry for `fe` and give it
    somebody else's text. A headword is therefore only recognised when prose
    follows it *on the same line*.
  * **Hyphenation travels in the text.** The OCR keeps the printer's
    end-of-line breaks as "¬", so `prepucio` arrives as `pre¬\npucio`.
  * **Sentences cannot be split on ". "** — the entries are dense with
    references (`Gén. 17:10-12`, `1 Mac. 2:42`), and every abbreviation ends
    in a period. Splitting naively truncates a definition mid-citation.

Usage:
    tools/import_rand1890.py --source rand1890.txt --out overrides.toml \
        [--caps rv1909-capitalised.json] [--report]

Writes a TOML that build_spanish_dict.py reads with --overrides. The file is
generated, not hand-written: it belongs beside the scan, not in the repo.
"""

import argparse
import json
import re
import sys
import unicodedata

SOURCE = ('Rand, W. W., «Diccionario de la Santa Biblia», Sociedad Americana '
          'de Tratados, Nueva York, 1890 — dominio público')
LABEL = 'Diccionario de la Santa Biblia, 1890'
ELLIPSIS = '\u2026'

# How much of an entry the peek shows. The full entries run to a median of
# ~480 characters and a tail past 2,500; a definition is the first sentence or
# two, and the rest is history and geography the popover has no room for.
LEAD_CHARS = 420
MIN_BODY = 40

# These entries very often open on a gloss or an etymology before they
# define anything — "CIRCUNCISIÓN, una incisión al rededor, porque en este
# rito se cortaba el prepucio." is the whole first sentence, and the sentence
# after it ("Era signo de consagración á Dios, y de purificación") is the one
# the reader wanted. So a lead keeps taking sentences until it has this much,
# rather than stopping at the first full stop it can.
MIN_MEANING = 150

# Words ending in a period that do NOT end a sentence. Mostly the Scripture
# abbreviations this dictionary cites on nearly every line.
_ABBREV = {
    'gén', 'gen', 'éx', 'ex', 'lev', 'núm', 'num', 'deut', 'jos', 'juec',
    'rut', 'sam', 'rey', 'crón', 'cron', 'esd', 'neh', 'est', 'job', 'sal',
    'prov', 'ecl', 'cant', 'isa', 'jer', 'lam', 'ezeq', 'dan', 'ose', 'joel',
    'amós', 'amos', 'abd', 'jon', 'miq', 'nah', 'hab', 'sof', 'hag', 'zac',
    'mal', 'mat', 'mar', 'luc', 'juan', 'hech', 'rom', 'cor', 'gál', 'gal',
    'ef', 'fil', 'col', 'tes', 'tim', 'tito', 'filem', 'heb', 'sant', 'ped',
    'jud', 'apoc', 'mac', 'ecli', 'sab', 'bar', 'tob', 'jdt',
    # Six more the printer uses that the first pass missed, worth 103 leads
    # between them: `Jue.` alone ended 41 of them, cutting "Jue. 4:17" to a
    # bare "Jue." `comp.` is compárese, which introduces a citation rather
    # than closing a thought.
    'jue', 'comp', 'efes', 'cró', 'cro', 'esdr', 'eccl',
    # The printer is inconsistent: Sal./Salm./Salmos, Isa./Isai./Isaias all
    # appear, and a period after any of them closed a "sentence" that was
    # really a citation — "el de género humano, como raza, Gén. 6:12; Salm."
    'salm', 'salmo', 'salmos', 'isai', 'isaias', 'exod', 'levit', 'deuter',
    'jueces', 'reyes', 'cronicas', 'cron', 'proverbios', 'eclesiastes',
    'ezequiel', 'daniel', 'oseas', 'joel', 'amos', 'abdias', 'jonas',
    'miqueas', 'nahum', 'habacuc', 'sofonias', 'hageo', 'zacarias',
    'malaquias', 'mateo', 'marcos', 'lucas', 'hechos', 'romanos',
    'corintios', 'galatas', 'efesios', 'filipenses', 'colosenses',
    'tesalonicenses', 'timoteo', 'filemon', 'hebreos', 'santiago', 'pedro',
    'judas', 'apocalipsis', 'genesis', 'exodo', 'levitico', 'numeros',
    'deuteronomio', 'josue', 'samuel', 'esdras', 'nehemias', 'ester',
    'cantares', 'jeremias', 'lamentaciones', 'macabeos',
    'cap', 'caps', 'vers', 'vs', 'v', 'etc', 'ver', 'véase', 'vease',
    'pág', 'pag', 'núms', 'nums', 'art', 'fig', 'sig', 'sigs',
    'a', 'd', 'j', 'c', 'sr', 'sra', 'dr', 'st', 'sto', 'sta', 'ap',
    'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x', 'xi', 'xii',
}

_RUNNING_HEAD = re.compile(r'^\s*(DICCIONARIO\b.*|[0-9IVXLC]+)\s*$')

#: A page break prints four things in a row: the page number, the left running
#: head, the book title and the right running head — "59 / ART / DICCIONARIO
#: DE LA BIBLIA. / ASA". Only the number and the title match above. The two
#: three-letter heads reach `parse` as all-caps blocks, where they read as
#: plate captions and end the entry: that is how ARREPENTIMIENTO — a word the
#: New Testament turns on — kept nothing but "un cambio de". They are told
#: from a caption by company, not by shape: a caption stands on its own page,
#: a running head stands beside the page number.
_SIDE_HEAD = re.compile(r'^\s*[A-ZÁÉÍÓÚÜÑ]{2,4}\s*$')

#: How far a running head sits from the page number it belongs to.
_FURNITURE_SPAN = 4

# A headword: capitals at the start of a line, then punctuation, then text on
# the SAME line. The "same line" is the whole guard against running heads —
# a page header sits alone ("FE" above the page about the Pharisees), and an
# entry never does. An earlier version demanded the text after the punctuation
# start lowercase, which was a safer-looking guard that silently dropped every
# entry opening on a capital: DIOS, PACTO, CARNE, PALABRA, a third of the book.
#
# Compound headwords join with a connector the printer sets in lower case —
# "VERBO ó PALABRA", "MAR DE GALILEA" — so the connectors are matched in
# either case.
_CONNECT = r'(?:[ÓOÉEYA]|Ó|DE|DEL|LA|EL|LOS|LAS|ó|o|y|de|del|la|el|los|las|á|a)'
_HEAD = re.compile(
    r'^([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\'\-]*'
    r'(?:[ ]' + _CONNECT + r'?[ ]?[A-ZÁÉÍÓÚÜÑ\'\-]+)*)'
    r'\s*[,.;:]\s+(\S.{5,})$')

#: A roman numeral or a digit heads a numbered sub-sense inside an entry
#: ("III. Ciudad en las montañas de Judá"), not an entry of its own.
_NOT_A_HEADWORD = re.compile(r'^[IVXLC0-9]+$')

#: The printer sets the rest of a headword in capitals too — "FILIPENSES,
#: EPÍSTOLA Á LOS. En ésta elogia Pablo…", "ÍDOLO, IDOLATRÍA. La palabra…".
#: `_HEAD` stops at the first comma, so the tail stays at the front of the
#: body and becomes the whole lead: the entry for Philippians read "EPÍSTOLA
#: Á LOS." and nothing else.
_HEAD_TAIL = re.compile(r"^(?:[ÓO]\s+)?[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ'\- ]{2,}\.\s+(?=\S)")

_XREF = re.compile(r'^V[ée]ase\s+(?:á\s+)?([^.,;]+)', re.IGNORECASE)

#: An entry for a name several people share opens with the etymology and then
#: numbers them: "ABÍAS, el Señor es mi padre, I., segundo hijo de Samuel".
#: On the page the numeral is a heading; run into a line of prose it reads as
#: a stray letter dropped between two clauses. The lookbehind is what keeps a
#: regnal numeral out — "Jeroboam II." follows a name, a sub-sense marker
#: follows punctuation, and all 140 regnal numerals in the book obey that.
_FIRST_SUBSENSE = re.compile(r'(?:^|(?<=[,.;] ))I\.,?\s+')

#: The second and later markers, which the period split leaves standing alone.
_NEXT_SUBSENSE = re.compile(r'^\s*(?:I{1,3}|IV|VI{0,3}|IX|XI{0,2}|X)\.,?\s*$')


def _strip_accents(word):
    return ''.join(c for c in unicodedata.normalize('NFD', word.lower())
                   if unicodedata.category(c) != 'Mn')


def repair(text):
    """Undo the scan's damage, in the order the damage was done."""
    # Page furniture comes off FIRST. A page break falls between the two
    # halves of a broken word — "des-" at the foot of one page, "pués" at the
    # head of the next — with the number, the running heads and the title
    # standing between them. Joining the hyphen before clearing that away
    # welded the word to the furniture instead: "des" + "ANA", 86 words in
    # all, every one of them silently.
    raw = text.split('\n')
    numbered = [i for i, l in enumerate(raw) if _RUNNING_HEAD.match(l)]
    furniture = set(numbered)
    for i in numbered:
        for j in range(max(0, i - _FURNITURE_SPAN),
                       min(len(raw), i + _FURNITURE_SPAN + 1)):
            if _SIDE_HEAD.match(raw[j]):
                furniture.add(j)
    text = '\n'.join(re.sub(r'[ \t]+', ' ', l).strip()
                     for i, l in enumerate(raw) if i not in furniture)
    # The printer's end-of-line hyphens, kept by the OCR as ¬ or -. Most break
    # a word and must go, but a compound name that happens to land on the line
    # end keeps a hyphen that means something: joining it welded Esion-Gaber
    # into "EsionGaber" and Abel-Mizraim into "AbelMizraim", 82 names in all.
    # A Spanish word never resumes on a capital followed by lower case, so
    # that shape marks the real hyphens — and only those. Both sides capital
    # is a soft hyphen again in an all-caps line ("APÓSTO-LES").
    text = re.sub(r'(\w)[¬-]\s*\n\s*(\w\w?)',
                  lambda m: m.group(1)
                  + ('-' if m.group(1).islower() and m.group(2)[0].isupper()
                     and m.group(2)[1:].islower() else '')
                  + m.group(2), text)
    text = re.sub(r'[¬-]\s*\n\s*', '', text)
    # A handful of marks the scan invented, none of which the book prints.
    # The asterisk does two jobs: an end-of-line hyphen ("perte* / necían")
    # and the period after an abbreviation ("Isai* 14:5"). The per-cent sign
    # is the vulgar fraction — deleting it turned "3% millas al oeste" into
    # three miles, so it is restored rather than dropped. The caret and the
    # tilde are specks of ink inside a word ("es^a", "ret~ibución").
    text = re.sub(r'\*\s*\n\s*', '', text)
    text = re.sub(r'([A-Za-zÁ-úÑñ])\*(?=\s+\d)', r'\1.', text)
    text = re.sub(r'([0-9i])\s*%',
                  lambda m: ('1' if m.group(1) == 'i' else m.group(1)) + '½',
                  text)
    text = re.sub(r'[*^~|#]', '', text)
    text = re.sub(r'(?<=[A-Za-zÁ-úÑñ])\?(?=[A-Za-zÁ-úÑñ])', '', text)
    # The scan reads the printer's y as a v — "el Jordán v el Leontes", 27
    # times. Spanish has no one-letter word v. It does have the others, and
    # this book uses them: two entries discuss "la b por la m en el Hebreo"
    # and "como c antes de a", so only the v is touched.
    text = re.sub(r'(?<=[a-záéíóúñ,]) v (?=[a-záéíóúñ])', ' y ', text)
    # The scan reads the printer's ó as a six about as often as it gets it
    # right; between two lower-case words it can be nothing else.
    text = re.sub(r'(?<=[a-záéíóúñ]) 6 (?=[a-záéíóúñ])', ' ó ', text)
    # The scan doubles spaces and floats punctuation away from its word.
    text = re.sub(r' +([,.;:!?»”])', r'\1', text)
    text = re.sub(r'([«“¡¿]) +', r'\1', text)
    text = re.sub(r'(\d) *: *(\d)', r'\1:\2', text)      # "Juan 1 : 17"
    text = re.sub(r'(\d) *- *(\d)', r'\1-\2', text)
    # The printer sets an ellipsis as spaced periods ("vierte .... las
    # comunicaciones"); left alone it reads as a sentence ending in a stutter.
    text = re.sub(r' ?\.{3,} ?', ELLIPSIS + ' ', text)
    text = re.sub(r'(\d)(I{1,3}|IV|VI{0,3}|IX|XI{0,2})\.', r'\1 \2.', text)
    # The scan reads an accented capital ending a headword as a letter of its
    # own: JUDÁ comes through as "JUD  A, celebre" — and a headword with a
    # space in it is a phrase, which `keys_for` drops. That cost the article
    # on Judah, a word the Reina-Valera uses 826 times. A connector never
    # sits against a comma ("EPÍSTOLA Á LOS" is followed by more of the
    # headword), so the punctuation is what tells the two apart.
    text = re.sub(r'^([A-ZÁÉÍÓÚÜÑ]{2,}) +([AEIOU])(?= *[,.])', r'\1\2',
                  text, flags=re.M)
    # Two misreads, and they are the only ones a check of every word in the
    # curated layer against the module's own lexicon turns up. `qne` is not
    # a Spanish word, so it can be corrected anywhere; `tina` is one — a tub —
    # so it is corrected only where an article belongs, which is where the
    # scan put it: "padre de tina multitud".
    text = re.sub(r'\bqne\b', 'que', text)
    text = re.sub(r'\b(de|en|á|a) tina (?=[a-záéíóúñ])', r'\1 una ', text)
    return text


def _ends_sentence(chunk):
    """Whether a period ending `chunk` closes a sentence rather than an
    abbreviation or a verse number."""
    if chunk.rstrip().endswith(ELLIPSIS):
        return False
    tail = re.split(r'[\s(«“]', chunk.rstrip('.'))[-1]
    tail = _strip_accents(tail.strip('.,;:()«»“”'))
    if not tail or tail in _ABBREV:
        return False
    return not tail.isdigit() and len(tail) > 1


def open_subsense(body):
    """Turn the numeral that opens the first sub-sense into the sentence break
    it stands for, so "el Señor es mi padre, I., segundo hijo de Samuel" reads
    "el Señor es mi padre. Segundo hijo de Samuel"."""
    m = _FIRST_SUBSENSE.search(body)
    if not m:
        return body
    head, rest = body[:m.start()].rstrip(' ,;'), body[m.end():]
    rest = rest[:1].upper() + rest[1:]
    if not head:
        return rest
    # The etymology usually runs into the numeral without stopping, so the
    # period is added here — but 24 entries already close on one, and Judá,
    # the word this matters most for, read "Véase este nombre.. El cuarto".
    return head + (' ' if head.endswith('.') else '. ') + rest


def _close_quote(text, body):
    """Take the closing quotation mark with the sentence it belongs to.

    The book puts the period inside the quotes — «la versión inglesa de esta
    palabra es “lino fino.”» — so cutting on that period strands the opening
    mark and the lead ends in mid-quotation.
    """
    if text.count('\u201c') > text.count('\u201d') \
            and body[len(text):len(text) + 1] == '\u201d':
        text += '\u201d'
    return _drop_stray_quotes(text)


def _drop_stray_quotes(text):
    """Remove a quotation mark whose partner is not in the lead.

    Twenty-two entries keep a mark the other side of which the scan lost or
    the cut left behind — «llamada por los Persas el “pájaro-camello» reads as
    a quotation that never ends. Pairing them and dropping what is left over
    costs the marks and keeps the sentence.
    """
    if text.count('\u201c') == text.count('\u201d'):
        return text
    stray, opened = set(), []
    for i, ch in enumerate(text):
        if ch == '\u201c':
            opened.append(i)
        elif ch == '\u201d':
            if opened:
                opened.pop()
            else:
                stray.add(i)
    stray.update(opened)
    return ''.join(c for i, c in enumerate(text) if i not in stray)


def lead(body, limit=LEAD_CHARS):
    """The opening sentence or two, never cut mid-word or mid-citation.

    Running to the limit and stopping is not enough. These entries end most
    clauses on a reference, so a cut that lands on the nearest period leaves
    the reader "…contemporáneo de Eglón y de Aod, Jueces 3." — a definition
    that appears to end on a book name. When the limit arrives mid-sentence we
    fall back to the last period that genuinely closed one, and only if there
    is no such period do we cut on a word boundary and say so with an ellipsis.
    """
    body = open_subsense(body)
    pieces = re.findall(r'.+?(?:\.|$)', body)
    out, taken, safe = [], 0, None
    for piece in pieces:
        if out and taken + len(piece) > limit:
            break
        if out and _NEXT_SUBSENSE.match(piece):
            break                # person II is a different man; half of him
                                 # is worse than none
        out.append(piece)
        taken += len(piece)
        if piece.rstrip().endswith('.') and _ends_sentence(piece):
            safe = len(out)
            if taken >= MIN_MEANING:
                break
    # Falling back to the last clean sentence end is right only when that
    # sentence carries a definition. `amor` opens on a quoted verse and then
    # defines the word, and the fallback returned the quote alone — the
    # reader met 1 John 4:16 and nothing about what `amor` means.
    if safe and (safe == len(out)
                 or len(''.join(out[:safe])) >= MIN_MEANING):
        return _close_quote(''.join(out[:safe]), body).strip()
    text = ''.join(out).strip()
    cut = text[:limit].rsplit(' ', 1)[0] if len(text) > limit else text
    return cut.rstrip(' ,;:') + ELLIPSIS


def parse(path):
    """headword -> body, in the order the dictionary prints them."""
    text = repair(open(path, encoding='utf-8', errors='replace').read())
    entries, current = {}, None
    for block in text.split('\n\n'):
        block = ' '.join(l for l in block.split('\n') if l).strip()
        if not block:
            continue
        m = _HEAD.match(block)
        head = m.group(1).strip(' .,;:') if m else None
        if head and not _NOT_A_HEADWORD.match(head):
            current = head
            entries.setdefault(current, []).append(m.group(2).strip())
        elif block.isupper():
            current = None                   # a plate caption
        elif current:
            entries[current].append(block)   # a continuation paragraph
    return {k: _HEAD_TAIL.sub('', ' '.join(v).strip(), count=1)
            for k, v in entries.items()}


def resolve(entries):
    """Follow "Véase Verbo." to the entry it points at."""
    index = {_strip_accents(k): k for k in entries}
    out, followed = {}, 0
    for word, body in entries.items():
        m = _XREF.match(body)
        if m and len(body) < 60:
            target = index.get(_strip_accents(m.group(1).strip()))
            if target and target != word and not _XREF.match(entries[target]):
                out[word] = entries[target]
                followed += 1
                continue
        out[word] = body
    return out, followed


def accent_map(freq_path):
    """de-accented word -> the accented spelling Scripture uses for it.

    The 1890 printer sets headwords in capitals, and Spanish typography of the
    period leaves the accents off capitals: the page reads AARON, JESUS, ELIAS.
    Left alone the curated entry lands on the unaccented key while the general
    dictionary keeps the accented one, so a reader who clicks `Jesús` — as
    written in the Bible in front of them — gets the general entry and never
    sees this one.

    The accent is restored from the Reina-Valera's own vocabulary rather than
    from a rule, and only where Scripture is unanimous. It writes both `caña`
    and `caná`, so `CANA` is left exactly as the printer set it.
    """
    by_plain = {}
    for word, count in json.load(open(freq_path, encoding='utf-8')):
        by_plain.setdefault(_strip_accents(word), {})[word] = count
    out = {}
    for plain, spellings in by_plain.items():
        accented = {w: n for w, n in spellings.items() if w != plain}
        if len(accented) == 1:
            out[plain] = next(iter(accented))
    return out


def restore_accent(word, accents):
    """`AARON` -> `aarón`, using Scripture's spelling; unknown words unchanged."""
    if _strip_accents(word) != word.lower():
        return word                      # the printer kept the accent
    return accents.get(word.lower(), word)


def spelling_key(word):
    """A name reduced to what 1890 and 1909 spell the same way.

    The Reina-Valera of 1909 and the Rand of 1890 are nineteen years and one
    orthographic reform apart, and they disagree about the same people and
    places: Ephraim/Efraím, Josaphat/Josafat, Nephtalí/Neftalí,
    Jerusalem/Jerusalén, Esther/Ester. Every difference is one of these —
    the Greek digraphs the older spelling kept, the silent h, and the final
    m — so folding them lets a reader's click on the word in front of them
    reach the article about it.
    """
    w = _strip_accents(word.lower())
    for digraph, plain in (('ph', 'f'), ('th', 't'), ('ch', 'c')):
        w = w.replace(digraph, plain)
    w = w.replace('h', '').replace('k', 'c')
    w = re.sub(r'(.)\1+', r'\1', w)
    return w[:-1] + 'n' if w.endswith('m') else w


def bible_aliases(kept, caps, accents):
    """Extra keys so a 1909 spelling reaches its 1890 article.

    Two guards, because a fold that merges names invents answers rather than
    finding them. Only words the Reina-Valera writes capitalised are aliased,
    so the fold cannot take `tiro` or `rama` away from the common noun the
    reader more often means. And an alias must open on the same three letters
    as its article and be within two of its length, which is what separates
    `abraham` -> `Abram`, a link the article itself makes ("llamado después
    Abraham"), from `issach` -> `Isaac`, two different men.

    A spelling that folds onto two articles is dropped: there is no evidence
    here for choosing between them.
    """
    by_key = {}
    for head in kept:
        by_key.setdefault(spelling_key(head), []).append(head)
    have = {k.lower() for k in kept}
    out = {}
    for word in caps:
        if word.lower() in have:
            continue
        heads = by_key.get(spelling_key(word))
        if not heads or len(heads) > 1:
            continue
        head = heads[0]
        a, b = _strip_accents(word.lower()), _strip_accents(head.lower())
        if a[:3] != b[:3] or abs(len(a) - len(b)) > 2:
            continue
        out[headword_case(restore_accent(word, accents), {a})] = kept[head]
    return out


def keys_for(word):
    """The lookup keys one printed headword should become.

    A double-click selects a single word, so a headword that is a phrase can
    never be reached — the same rule the Wiktionary build applies to the
    10,681 proverbs it used to index. Three shapes appear:

      * "ABEL - BETH - MAACA" — the printer's spaced hyphens; one word really.
      * "DIANA ó ÁRTEMIS" — two names for one thing. Both are worth a key, so
        this yields two entries sharing a body.
      * "CENA DEL SEÑOR", "ARCA DE NOÉ" — descriptive phrases. Dropped: the
        first word alone would either duplicate a real entry or, worse, hand
        "cabeza" the article on Cabeza de Baal.
    """
    word = re.sub(r'\s*-\s*', '-', word.strip())
    if ' ' not in word:
        return [word]
    parts = re.split(r'\s+[óÓoO]\s+', word)
    if len(parts) == 2 and all(p and ' ' not in p for p in parts):
        return parts
    return []


def headword_case(word, caps):
    """`GRACIA` -> `gracia`, but `MOISÉS` -> `Moisés`.

    Decided by how the Reina-Valera writes the word mid-sentence, the same
    evidence build_spanish_dict.py uses to order a key's blocks — not by a
    guess about which words are names.
    """
    parts = word.split()
    if _strip_accents(word) in caps or any(_strip_accents(p) in caps
                                           for p in parts):
        return ' '.join(p.capitalize() if p not in ('DE', 'DEL', 'LA', 'EL',
                                                    'LOS', 'LAS', 'Y', 'Ó')
                        else p.lower() for p in parts)
    return word.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, help='the OCR text')
    ap.add_argument('--out', required=True, help='TOML to write')
    ap.add_argument('--caps', help='rv1909-capitalised.json, for headword case')
    ap.add_argument('--accents', help='rv1909-freq.json, to restore the '
                                      'accents the printer left off capitals')
    ap.add_argument('--report', action='store_true', help='print QA counts')
    args = ap.parse_args()

    caps, caps_raw = set(), []
    if args.caps:
        caps_raw = json.load(open(args.caps))
        caps = {_strip_accents(w) for w in caps_raw}
    accents = accent_map(args.accents) if args.accents else {}

    raw = parse(args.source)
    entries, followed = resolve(raw)

    kept, dropped = {}, 0
    for word, body in entries.items():
        keys = [k for k in keys_for(word) if len(k) > 1]
        if not keys or len(body) < MIN_BODY:
            dropped += 1
            continue
        text = lead(body)
        if len(text) < MIN_BODY:
            dropped += 1
            continue
        for key in keys:
            cased = headword_case(restore_accent(key, accents), caps)
            kept.setdefault(cased, text)      # first printing of a key wins

    aliases = bible_aliases(kept, caps_raw, accents) if caps_raw else {}
    kept.update(aliases)

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('# GENERATED by tools/import_rand1890.py — do not edit.\n'
                 f'# {SOURCE}\n\n')
        for word in sorted(kept):
            body = kept[word].replace('\\', '').replace('"', '\\"')
            fh.write(f'[{json.dumps(word, ensure_ascii=False)}]\n')
            fh.write(f'senses = ["{body}"]\n')
            fh.write(f'label = "{LABEL}"\n')
            fh.write(f'source = "{SOURCE}"\n\n')

    print(f'{len(kept):,} entries -> {args.out}')
    if args.report:
        repaired = sum(1 for w in kept if _strip_accents(w) != w.lower())
        print(f'  headwords carrying an accent: {repaired}')
        print(f'  cross-references followed: {followed}')
        print(f'  1909 spellings aliased onto 1890 articles: {len(aliases)}')
        print(f'  dropped as too short or malformed: {dropped}')
        lens = sorted(len(v) for v in kept.values())
        print(f'  lead length: median {lens[len(lens)//2]}, '
              f'max {lens[-1]}, over {LEAD_CHARS}: '
              f'{sum(1 for l in lens if l > LEAD_CHARS)}')
        bad = [w for w, v in kept.items()
               if not _ends_sentence(v) and not v.endswith('…')]
        print(f'  leads ending mid-citation: {len(bad)} {bad[:6]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
