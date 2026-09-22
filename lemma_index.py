"""Original-language search over the interlinear databases.

Answers "where does this Greek or Hebrew word occur" from the TAGNT /
TAHOT word tables `interlinear_data` already installs — every row of
which carries a disambiguated Strong's number, a lemma and a morphology
code. The reader's own translation supplies the verse text; this module
supplies only the references.

**No index is built, and none is needed.** Measured on the shipped
databases (141,720 Greek rows, 305,577 Hebrew): a full scan for one
Strong's number costs 12 ms on the Greek table and 22 ms on the Hebrew.
An index on `strongs` takes those to 0.1 ms and costs 7.4 MB on the
Hebrew file alone — a bad trade for work that already runs on a worker
thread, and it would mean a schema bump and a rebuild for every user who
has the databases installed. The searches here are scans on purpose.

Scope: the two interlinear databases cover the Hebrew OT and the Greek
NT. A verse outside them (the deuterocanon, and the Aramaic stretches
TAHOT marks but does not separate) simply has no rows, so a filter never
matches there. That is the data's own boundary, not a defect to paper
over.

Book names come out in the app's canonical English spelling, ready to
join against anything keyed the way `sword_bridge._ALL_BOOKS` is; the
ordering helper below is the OT-then-NT order those two tables define
between them, so this module needs no SWORD import to sort its answers.
"""

import re
import sqlite3
import unicodedata
from typing import NamedTuple, Optional

import interlinear_data

# Canonical order, straight from the two source tables: TAHOT's books are
# listed OT-canonical and TAGNT's NT-canonical, so their concatenation is
# the reading order the result lists want.
_BOOK_ORDER = {
    book: i for i, book in enumerate(
        list(interlinear_data._HEBREW_BOOKS.values())
        + list(interlinear_data._GREEK_BOOKS.values()))
}

_STRONGS_RE = re.compile(r'^([GH])0*(\d+)', re.IGNORECASE)


class Sense(NamedTuple):
    """What a filter set turned out to be about — the header a concordance
    prints over its column. Named `occurrences`, not `count`: a
    NamedTuple field called `count` shadows `tuple.count`, and the number
    really is occurrences rather than verses — a verse using the word
    twice is two."""
    strongs: str
    lemma: str
    translit: str
    gloss: str
    occurrences: int


def normalise_strongs(value: str) -> str:
    """'g0026' / 'G26' / '26' → 'G26'.

    The databases store the zero-stripped form (`interlinear_data
    ._norm_strongs`), the app's module markup zero-pads to four digits,
    and a reader typing by hand does neither consistently. Every
    comparison goes through here. A bare number keeps no prefix, so it
    can never match — callers wanting a guess should not guess.
    """
    m = _STRONGS_RE.match((value or '').strip())
    if not m:
        return (value or '').strip().upper()
    return m.group(1).upper() + m.group(2)


def _norm_lemma(value: str) -> str:
    """NFC, stripped — the form the parser stores. TAGNT ships decomposed
    Greek and `parse_line` normalises at build time, so a lemma typed or
    pasted from anywhere else has to be folded the same way or an
    identical-looking string will not compare equal."""
    return unicodedata.normalize('NFC', (value or '').strip())


def is_available() -> bool:
    """Whether either interlinear database is installed. False means an
    original-language query has nothing to search and callers should say
    so rather than return an empty result that reads as 'no occurrences'."""
    return bool(interlinear_data.module_names())


def _where(filters) -> Optional[tuple[str, list]]:
    """Translate `search_query.Filter`s into a WHERE clause over `words`.

    Returns None when a filter cannot be satisfied at all, which is not
    the same as matching nothing: an unparseable Strong's number means the
    caller should report a bad query, and a `None` here says so.

    Matching rules, each chosen for what the column actually holds:
      * `strong` — the primary number OR any number in the affix chain,
        so a compound word answers to both its parts. Word-bounded
        against `strongs_all` so G26 never matches G260.
      * `lemma`  — exact, NFC-folded. Lemmas are dictionary forms; a
        substring match on them returns a different word.
      * `morph`  — case-sensitive substring, because the codes are chains
        (`HR/Vqcc`) whose case carries meaning (`Ncmsc` is not `NCMSC`),
        and a reader asking for `V-AAM` wants `V-AAM-2S` and `V-AAM-3P`.
    """
    # A query of nothing but exclusions defines no result set — the same
    # rule `search_query.build_match` applies to text, and for the same
    # reason. Measured before the rule was added: `-morph:N-NSF` alone
    # returned 31,170 verses, the whole Bible minus its feminine
    # nominative nouns, which is not a search anybody typed.
    if not any(not f.negate for f in filters):
        return None
    clauses = []
    params: list = []
    for f in filters:
        if f.field == 'strong':
            num = normalise_strongs(f.value)
            if not _STRONGS_RE.match(num):
                return None
            # strongs_all is space-joined, so pad the haystack and the
            # needle with spaces to get a whole-token match out of LIKE.
            expr = ("(strongs = ? OR instr(' ' || strongs_all || ' ', ?) > 0)")
            args = [num, f' {num} ']
        elif f.field == 'lemma':
            expr = 'lemma = ?'
            args = [_norm_lemma(f.value)]
        elif f.field == 'morph':
            expr = 'instr(morph, ?) > 0'
            args = [f.value.strip()]
        else:
            continue
        clauses.append(f'NOT {expr}' if f.negate else expr)
        params.extend(args)
    if not clauses:
        return None
    return ' AND '.join(clauses), params


def _query(filters, columns: str, rendered_only: bool = True):
    """Run one SELECT against every installed database and chain the rows.

    `rendered_only` keeps the answer to the text the interlinear actually
    displays. A word the reading stream omits — a TR/Byz-only Greek
    reading, a Hebrew insertion row — is real data but it is not in the
    verse the reader has open, so counting it would make the concordance
    disagree with the page.
    """
    where = _where(filters)
    if where is None:
        return
    clause, params = where
    if rendered_only:
        clause = f'({clause}) AND in_stream = 1'
    for name in interlinear_data.module_names():
        conn = sqlite3.connect(interlinear_data._DB_FILES[name])
        try:
            interlinear_data._migrate(conn, name)
            yield from conn.execute(
                f'SELECT {columns} FROM words WHERE {clause}', params)
        finally:
            conn.close()


def refs(filters) -> list[tuple[str, int, int]]:
    """The distinct verses a filter set matches, in canonical order.

    This is the concordance's spine and the search panel's join key: the
    references come from the interlinear data, the text from whichever
    translation the reader has chosen."""
    seen = set()
    out = []
    for book, chapter, verse in _query(filters, 'book, chapter, verse'):
        key = (book, chapter, verse)
        if key not in seen:
            seen.add(key)
            out.append(key)
    out.sort(key=lambda r: (_BOOK_ORDER.get(r[0], 999), r[1], r[2]))
    return out


def describe(filters) -> Optional[Sense]:
    """The word a filter set is about, for the header over its results.

    Answers from the matches themselves rather than from a lexicon, so the
    header always describes the rows actually shown — a morphology-only
    query ("every aorist imperative") has no single word and correctly
    reports a blank lemma. Each field goes blank where the matches
    disagree, so the header never asserts a word the result set does not
    support.

    The transliteration is taken only from a word standing in its lexical
    form, never from the commonest match: for `strong:G26 -morph:N-NSF`
    that would have printed the accusative `agapēn` beside the nominative
    lemma ἀγάπη. Blank is better than plausible and wrong.
    """
    rows = list(_query(
        filters, 'strongs, lemma, translit, lemma_gloss, surface'))
    if not rows:
        return None
    strongs = _agreed(r[0] for r in rows)
    lemma = _agreed(r[1] for r in rows)
    gloss = _agreed(r[3] for r in rows) if lemma else ''
    translit = ''
    if lemma:
        lexical = [r[2] for r in rows if _norm_lemma(r[4]) == lemma]
        translit = _agreed(lexical) if lexical else ''
    return Sense(strongs, lemma, translit, gloss, len(rows))


def _agreed(values) -> str:
    """The one value every row carries, or '' when they differ."""
    seen = set(values)
    return seen.pop() if len(seen) == 1 else ''


def senses(filters) -> list[Sense]:
    """The distinct words a filter set gathered, commonest first.

    A lemma search is not a word search, and the data says so plainly:
    the 248 Hebrew rows spelled חֶ֫סֶד are H2617 "kindness" (245), its
    homonym H2617 "shame" (2), and the proper name H2618 "Hesed" (1).
    A surface that printed one header over all three would teach
    something false, so it asks this and offers the choice — the same
    rule the genealogy charts follow for a name that covers several
    people. `describe` stays the single-sense answer for a header.
    """
    tally: dict[tuple[str, str, str], int] = {}
    translits: dict[tuple[str, str, str], str] = {}
    for strongs, lemma, translit, gloss, surface in _query(
            filters, 'strongs, lemma, translit, lemma_gloss, surface'):
        key = (strongs, lemma, gloss)
        tally[key] = tally.get(key, 0) + 1
        if key not in translits and _norm_lemma(surface) == _norm_lemma(lemma):
            translits[key] = translit
    out = [Sense(s, le, translits.get((s, le, g), ''), g, n)
           for (s, le, g), n in tally.items()]
    # Commonest first, then by number and gloss: two senses with the same
    # count must not swap places between runs, or a surface offering the
    # choice reorders itself under the reader.
    out.sort(key=lambda s: (-s.occurrences, s.strongs, s.gloss))
    return out
