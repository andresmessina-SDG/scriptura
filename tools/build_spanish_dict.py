#!/usr/bin/env python3
"""Build a Spanish dictionary as a SWORD module, from the Spanish Wiktionary.

Why this exists: there is no Spanish Bible dictionary. All 168 dictionary
modules CrossWire and its friends distribute are English, French, Russian or
Portuguese, and the app teaches double-clicking a word as one of its three
launch hints — a gesture that, for a reader of the Spanish Bibles, did
nothing at all. Wiktionary is a general dictionary rather than a Bible one,
and it is the only route that exists.

The source is Kaikki's machine-readable extract of es.wiktionary.org
(Wiktextract), which parses the wikitext into JSON so this script does not
have to. Two things about that data decide the shape of this build:

  * Spanish is inflected and the app's `_dict_candidates` de-inflection is
    English (-ies/-ing/-ed), so it cannot reach `amar` from `amaréis`.
    Wiktionary solves this for us: it carries a separate page for every
    conjugated form, 643,081 of the 854,082 records here.
  * Those form pages say "Primera persona del singular de amar" and stop —
    the definition lives on the lemma's page. A reader who double-clicks a
    verb wants the meaning, not a redirect, so each form entry is resolved
    against its lemma through the structured `form_of` field and carries the
    lemma's own first gloss.

Entries are emitted with <b>, <i> and <br /> only: the peek renders them
through `pane._html_to_markup`, which keeps the first two, turns <br> into a
newline, and strips every other tag while keeping its content. The break has
to be a tag rather than a newline because imp2ld joins the lines of an IMP
entry — a body written with \n arrives as one unbroken wall of text.

Usage:
    tools/build_spanish_dict.py --source es-lemmas.jsonl --out DIR [--limit N]

Writes DIR/Wikcionario.zip — a SWORD module the Module Manager can install
and `lookup_dict_word` can read, with no application change.
"""

import argparse
import json
import tomllib
import unicodedata
import os
import re
import shutil
import subprocess
import sys
import zipfile

MODULE = 'Wikcionario'
SOURCE_URL = ('https://kaikki.org/eswiktionary/Espa%C3%B1ol/'
              'kaikki.org-dictionary-Espa%C3%B1ol.jsonl')

# Caps. A dictionary that lists every regional sense of every word is not
# more useful in a peek popover than one that lists the first several — and
# the uncapped text runs to 83 MB before compression. Measured over the
# vocabulary of Romans, six senses put a fifth of all entries past the height
# the popover can show, so the reader met a scrollbar rather than an answer.
MAX_SENSES_PER_POS = 3
MAX_POS_PER_WORD = 4
MAX_GLOSS_CHARS = 200
MAX_LEMMA_GLOSS_CHARS = 160

#: How a rendered inflected-form block starts. Wiktextract titles every
#: form page "Forma verbal", "Forma adjetiva y de participio", "Forma
#: sustantiva femenina" — 701,662 records whose one shared mark is that word.
_FORM_BLOCK = '<b>Forma '

# Closed-class words. 15% of the distinct vocabulary of a chapter is
# articles, prepositions, pronouns and conjunctions, and Wiktionary answers
# them at length in eighteenth-century lexicographer's prose — `pues` opens
# "Partícula que sirve en la oración de nota de quien se resuelve alguna
# cosa". Nobody double-clicks a conjunction hoping for that, and the peek's
# own "no entry" message is both shorter and more honest. Only inflected
# forms of the auxiliaries are listed: `ser` and `poder` are dropped as verb
# forms but kept as nouns, so the infinitives stay out of this list.
_STOPWORDS = set("""
    el la los las lo un una unos unas al del
    de a en y e o u ni que qué porque pues mas pero sino aunque como cómo
    cuando cuándo donde dónde cual cuál cuyo cuya cuyos cuyas quien quién
    si no se le les me te nos os su sus mi mis mí tu tus tú ti yo él ella
    ello ellos ellas nosotros nosotras vosotros vosotras usted ustedes
    conmigo contigo consigo
    es son era eran eres soy fue fui fueron sea seas sean siendo sido
    ha he has han había habían hay hubo haya hayan habiendo habido
    está están estaba estaban esté estén
    para por con sin sobre entre desde hasta hacia tras ante bajo durante
    mediante según contra so
    más menos muy tan tanto tanta tantos tantas todo toda todos todas
    otro otra otros otras mismo misma mismos mismas cada ambos ambas
    ya aun aún también tampoco antes después entonces así aquí allí ahí
    allá acá luego siempre nunca jamás sí
    este esta estos estas ese esa esos esas aquel aquella aquellos aquellas
    esto eso aquello aqueste aquesta aquel
""".split())

# Wiktionary keeps redirect-ish and construction pages that are noise in a
# reading peek.
_SKIP_POS = {'character', 'suffix', 'prefix', 'infix', 'romanization'}

# imp2ld joins an entry's lines, so breaks travel as tags.
BR = '<br />'
PARA = '<br /><br />'


def _clean(text):
    """Wikitext leftovers Wiktextract passes through, and markup we must not
    emit: the peek escapes the entry, so a stray < would be shown literally."""
    text = re.sub(r'\s+', ' ', str(text)).strip()
    text = text.replace('<', '‹').replace('>', '›')
    # Wiktionary glosses sometimes carry their own terminal stop and pick up
    # another from the sentence they were cut from.
    text = re.sub(r'\.\.+$', '.', text)
    return text


#: Wiktionary cross-references a word's other senses with a subscript
#: numeral — "conformidad con la justicia₁". Lifted out of its numbered list
#: the reference points at nothing, so the sense reads as a definition of
#: itself. 2,205 senses carry one.
_BACKREF = re.compile(r'[\u2080-\u2089]')


def _truncate(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut + '…'


def read_lemma_glosses(path, limit=None):
    """word -> its first real (non-form-of) gloss, for resolving form pages.

    Keyed by word alone rather than by (word, pos): `form_of` names a word,
    and the lemma of a verb form is always a verb, so the collision risk is
    a noun sharing the spelling — in which case its gloss is still the more
    useful thing to show beside the conjugation.
    """
    lemmas = {}
    for n, line in enumerate(open(path, encoding='utf-8')):
        if limit and n >= limit:
            break
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        word = rec.get('word')
        if not word or word in lemmas:
            continue
        for sense in rec.get('senses') or []:
            if 'form-of' in (sense.get('tags') or []):
                continue
            glosses = sense.get('glosses') or []
            if glosses:
                lemmas[word] = _truncate(_clean(glosses[0]),
                                         MAX_LEMMA_GLOSS_CHARS)
                break
    return lemmas


def render_record(rec, lemmas):
    """One part-of-speech block for a word, or '' if it carries nothing."""
    lines = []
    for sense in rec.get('senses') or []:
        if len(lines) >= MAX_SENSES_PER_POS:
            break
        glosses = sense.get('glosses') or []
        if not glosses:
            continue
        if _BACKREF.search(glosses[0]):
            continue                    # cites a sense we are not showing
        if {'vulgar', 'obscene', 'offensive'} & set(sense.get('tags') or []):
            continue
        body = _truncate(_clean(glosses[0]), MAX_GLOSS_CHARS)
        if 'form-of' in (sense.get('tags') or []):
            # Resolve the redirect, and lead with the meaning. A reader who
            # double-clicks `amaréis` wants to know what `amar` means; that
            # it is the second person plural future is the smaller half of
            # the answer, so it follows in italics instead of standing where
            # the definition should be. Several form_of targets are common
            # (amigar / amigarse) — the first that has a gloss wins.
            meaning = ''
            for target in sense.get('form_of') or []:
                gloss = lemmas.get(target.get('word'))
                if gloss:
                    meaning = f"<b>{_clean(target['word'])}</b>: {gloss}"
                    break
            if not meaning:
                lines.append(body)          # no lemma gloss: the form is all
                continue
            # One lemma, several of its forms on the same page: say what the
            # lemma means once, then list the forms under it.
            if meaning not in lines:
                lines.append(meaning)
            lines.append(f'<i>{body}</i>')
        else:
            lines.append(body)
    if not lines:
        return ''
    # Number only when there is more than one sense to tell apart.
    if len(lines) > 1 and not any(l.startswith(('<i>', '<b>'))
                                  for l in lines):
        lines = [f'{i}. {l}' for i, l in enumerate(lines, 1)]
    title = _clean(rec.get('pos_title') or rec.get('pos') or '')
    head = f'<b>{title}</b>{BR}' if title else ''
    return head + BR.join(lines)


def build_entries(path, lemmas, limit=None):
    """upcased key -> {spelling: [blocks]}.

    Grouped by the UPCASED word, not the word, because a SWORD lexicon key is
    case-insensitive: `luz` and `Luz` are one key. Keyed by the spelling this
    silently dropped one of every colliding pair — 1.1% of entries, among them
    Aarón — and the survivor was whichever the index happened to land on, so
    `luz` answered with "nombre de pila de mujer" instead of light.
    """
    entries = {}
    for n, line in enumerate(open(path, encoding='utf-8')):
        if limit and n >= limit:
            break
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        word = rec.get('word')
        if not word or rec.get('pos') in _SKIP_POS:
            continue
        if word.lower() in _STOPWORDS:
            continue
        # Keys are the lookup surface, and a double-click selects one word.
        # A proverb ("a abril, deséale por lluvioso y témele por vil") can
        # never be reached, so 10,681 of them were indexed for nobody.
        if not word.strip() or len(word) > 60 or any(c.isspace() for c in word):
            continue
        block = render_record(rec, lemmas)
        if not block:
            continue
        spellings = entries.setdefault(word.upper(), {})
        blocks = spellings.setdefault(word, [])
        if len(blocks) < MAX_POS_PER_WORD and block not in blocks:
            blocks.append(block)
    return entries


#: Wiktionary lists an interjection before the word's other readings, which
#: put "Expresa asombro, sorpresa o extrañeza" above the plural of `cielo` on
#: the second word of Genesis 1:1. An interjection is a whole utterance, and
#: a word double-clicked inside a sentence is by definition not one — so it
#: goes last wherever the key has another reading, and stays put where it is
#: the only one (`oh`, `ah`, `ea`, which is what Scripture means by them).
_INTERJECTION = '<b>Interjección'


def _reading_order(blocks):
    """`blocks` with any interjection last, otherwise untouched.

    The sort is stable, so a curated entry — which carries no part-of-speech
    label at all — keeps the lead it was given.
    """
    return sorted(blocks, key=lambda b: b.startswith(_INTERJECTION))


def render_entry(spellings, prefers_capital=()):
    """The body for one key. When a key holds more than one spelling the
    blocks are labelled with theirs, since the peek's headword shows what the
    reader clicked and cannot tell them apart. Lowercase first: a word met
    mid-sentence is far more often the common noun than the given name."""
    # Which spelling leads is decided by the Reina-Valera's own usage, not by
    # a guess about words in general. `moisés` led with "cuna portátil hecha
    # con mimbre" — a wicker carrycot — in a Bible that writes Moisés 758
    # times mid-sentence and moisés none; `dios` led with the polytheistic
    # common noun at 64 occurrences against Dios at 3,936.
    key = next(iter(spellings)).lower()
    capital_first = key in prefers_capital
    order = sorted(spellings,
                   key=lambda w: (w[:1].isupper() != capital_first, w))
    if len(order) == 1:
        return PARA.join(_reading_order(spellings[order[0]]))
    out = []
    for word in order:
        for block in _reading_order(spellings[word]):
            if block.startswith('<b>'):
                block = block.replace('<b>', f'<b>{_clean(word)} · ', 1)
            else:
                block = f'<b>{_clean(word)}</b>{BR}{block}'
            out.append(block)
    return PARA.join(out)


def _strip_accents(word):
    return ''.join(c for c in unicodedata.normalize('NFD', word)
                   if unicodedata.category(c) != 'Mn')


def write_imp(entries, path, prefers_capital=()):
    """IMP, sorted by the upcased key. SWORD searches a lexicon by binary
    search over its index and imp2ld does not sort for you — Easton's own
    changelog records two releases spent fixing out-of-order entries.

    Every accented key also gets a de-accented alias where that spelling is
    not already taken. The app's lookup can drop an accent the text has and
    the dictionary lacks (`dió` → `dio`) but cannot invent one the text lacks
    and the dictionary has, and the Reina-Valera 1909 writes `carcel` for
    `cárcel`. Only this side of it can be fixed here, so it is.
    """
    bodies = {key: render_entry(spellings, prefers_capital)
              for key, spellings in entries.items()}
    aliases = 0
    for key in list(bodies):
        plain = _strip_accents(key)
        # Never alias into a word we deliberately hold no entry for: `más`
        # would otherwise answer for `mas`, which the Reina-Valera uses on
        # nearly every page to mean "but".
        if plain.lower() in _STOPWORDS:
            continue
        if plain != key and plain not in bodies:
            bodies[plain] = bodies[key]
            aliases += 1
    with open(path, 'w', encoding='utf-8') as fh:
        for key in sorted(bodies, key=lambda k: k.encode('utf-8')):
            fh.write(f'$$${key}\n')
            fh.write(bodies[key])
            fh.write('\n')
    return len(bodies), aliases


CONF = """[{module}]
Description=Wikcionario — diccionario general en español
DataPath=./modules/lexdict/zld/{lower}/{lower}
ModDrv=zLD
SourceType=OSIS
Encoding=UTF-8
CompressType=ZIP
BlockCount=30
Lang=es
Version=1.0
About=Diccionario de la lengua española derivado del Wikcionario \\
(es.wiktionary.org) mediante la extracción de Kaikki/Wiktextract, con \\
entradas bíblicas tomadas del «Diccionario de la Santa Biblia» de W. W. \\
Rand (Sociedad Americana de Tratados, Nueva York, 1890). \\par\\par \\
Las entradas generales definen las palabras del idioma, incluidas las \\
formas verbales conjugadas; las entradas bíblicas llevan su propia \\
atribución y conservan la ortografía de 1890. \\par\\par \\
El texto del Wikcionario está disponible bajo la licencia Creative Commons \\
Atribución-CompartirIgual 4.0; véase https://es.wiktionary.org para la lista \\
de autores. El «Diccionario de la Santa Biblia» de 1890 es de dominio \\
público.
DistributionLicense=Creative Commons: BY-SA 4.0
TextSource={source}
LCSH=Spanish language--Dictionaries.
"""


def read_overrides(path):
    """Hand-curated entries that replace Wiktionary's for a word.

    Wiktionary is a general dictionary, and on the words a Bible reader
    actually double-clicks it answers as one: `circuncisión` gets a surgical
    description, `hombre` opens on "mamífero primate dotado de inteligencia".
    Two mechanical repairs were tried and both damaged the words that matter
    most — scoring senses by how much of their wording Scripture itself uses
    picks "persona con un talento extraordinario" for `dios`, and promoting
    Wiktionary's own religion tag replaces the Hebrews 11:1 sense of `fe`
    with "sistema de creencias de una religión". So the quality goes here
    instead, one word at a time, from a named source.

    Every entry must carry `source`: this file mixes licences with the
    CC BY-SA text around it, and an entry nobody can trace is one nobody can
    ship. Entries are rendered exactly like Wiktionary's, so an override is
    indistinguishable to the reader except in being right.
    """
    if not path:
        return {}
    with open(path, 'rb') as fh:
        raw = tomllib.load(fh)
    out = {}
    for word, entry in raw.items():
        senses = entry.get('senses') or []
        if not senses:
            raise SystemExit(f'override for {word!r} has no senses')
        if not entry.get('source'):
            raise SystemExit(f'override for {word!r} has no source')
        title = _clean(entry.get('pos') or '')
        lines = [_clean(g) for g in senses]
        if len(lines) > 1:
            lines = [f'{i}. {l}' for i, l in enumerate(lines, 1)]
        head = f'<b>{title}</b>{BR}' if title else ''
        # A reader meeting "fué" and "Jesu-Cristo" deserves to know they are
        # reading 1890, not a modern gloss that has aged badly.
        label = _clean(entry.get('label') or '')
        tail = f'{BR}<i>{label}</i>' if label else ''
        out[word] = head + BR.join(lines) + tail
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, help='Kaikki JSONL extract')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--limit', type=int, help='read only N lines (for trials)')
    ap.add_argument('--overrides', action='append', default=[],
                    help='TOML of curated entries; repeatable, last wins')
    ap.add_argument('--bible-caps',
                    help='JSON list of words Scripture writes capitalised')
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    stage = os.path.join(out, 'stage')
    lower = MODULE.lower()
    data_dir = os.path.join(stage, 'modules', 'lexdict', 'zld', lower)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, 'mods.d'), exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    print('pass 1: lemma glosses…', flush=True)
    lemmas = read_lemma_glosses(args.source, args.limit)
    print(f'  {len(lemmas):,} lemmas with a definition', flush=True)

    print('pass 2: entries…', flush=True)
    entries = build_entries(args.source, lemmas, args.limit)

    overrides = {}
    for path in args.overrides:
        overrides.update(read_overrides(path))
    kept_forms = 0
    for word, body in overrides.items():
        # A curated entry replaces Wiktionary's *definitions* — that is the
        # whole point, and leaving them beside it would put the surgical
        # account of `circuncisión` under the one we chose instead.
        #
        # Its *inflections* are a different thing and must survive. `vino` is
        # wine in this dictionary and "he came" on 682 lines of the
        # Reina-Valera; `sal` is salt and "go out"; `haya` is a tree and a
        # form of haber. Dropping those would answer a question the reader
        # did not ask and hide the one they did.
        blocks = [b for b in entries.get(word.upper(), {}).get(word, [])
                  if b.startswith(_FORM_BLOCK)]
        kept_forms += len(blocks)
        entries[word.upper()] = {word: [body] + blocks}
    if overrides:
        print(f'  {len(overrides):,} curated entries applied '
              f'({kept_forms:,} inflection blocks kept under them)', flush=True)
    imp = os.path.join(out, f'{lower}.imp')
    prefers_capital = set()
    if args.bible_caps:
        with open(args.bible_caps, encoding='utf-8') as fh:
            prefers_capital = {w.lower() for w in json.load(fh)}
        print(f'  {len(prefers_capital):,} words lead with their capital form',
              flush=True)
    count, aliases = write_imp(entries, imp, prefers_capital)
    print(f'  {count:,} keys ({aliases:,} de-accented aliases), '
          f'IMP {os.path.getsize(imp) / 1e6:.1f} MB', flush=True)

    print('imp2ld…', flush=True)
    subprocess.run(['imp2ld', imp, '-z', 'z', '-o',
                    os.path.join(data_dir, lower)],
                   check=True, stdout=subprocess.DEVNULL)

    conf_path = os.path.join(stage, 'mods.d', f'{lower}.conf')
    with open(conf_path, 'w', encoding='utf-8') as fh:
        fh.write(CONF.format(module=MODULE, lower=lower, source=SOURCE_URL))

    zip_path = os.path.join(out, f'{MODULE}.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(stage):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, stage))
    data_bytes = sum(os.path.getsize(os.path.join(data_dir, f))
                     for f in os.listdir(data_dir))
    print(f'module {data_bytes / 1e6:.1f} MB, '
          f'zip {os.path.getsize(zip_path) / 1e6:.1f} MB -> {zip_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
