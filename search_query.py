"""Translate a user search string into a safe SQLite FTS5 MATCH expression.

Both search backends (eBible SQLite and the SWORD FTS5 index) share this
grammar so the *same query means the same thing* on every module — the
divergence the old Whoosh/LIKE split produced is gone.

Supported grammar (deliberately small and predictable):

    plain words            implicit AND        →  living water
    "quoted phrase"        adjacent, in order  →  "living water"
    OR  (bare, uppercase)  alternation         →  bread OR wine
    -word / -"phrase"      exclude (NOT)        →  faith -works
    trailing *             prefix match         →  baptiz*
    strong: / lemma: /     the Greek or Hebrew   →  strong:G26 charity
    morph:                 word under the verse

The last three are not FTS terms at all — `split_filters` lifts them out
for the interlinear databases to answer, and the caller intersects the two
result sets. Everything below concerns the text half.

Robustness contract: every term is emitted as a double-quoted FTS5 string
literal, so arbitrary user input (stray quotes, punctuation, operator words,
LIKE/GLOB metacharacters) can NEVER produce an FTS5 syntax error. Worst case
a term tokenizes to nothing and is dropped.

FTS5 tokenization (unicode61) lowercases and folds diacritics, so a MATCH is
inherently case-insensitive; callers wanting case-sensitive results run the
plain terms (see `plain_terms`) as a post-filter over the matched text.
"""

import re
from typing import NamedTuple

# A token is: an optional leading '-', then either a "quoted phrase" or a bare
# run of non-space characters, with an optional trailing '*' for prefix match.
_TOKEN_RE = re.compile(r'-?"[^"]*"\*?|-?\S+')


def _fts_quote(value):
    """Wrap a raw string as an FTS5 string literal (doubling embedded quotes).
    A multi-word value becomes a phrase; a single word, a bare term."""
    return '"' + value.replace('"', '""') + '"'


def _parse(query):
    """Tokenize `query` into (positives, negatives, connectors).

    positives/negatives are lists of (fts_literal, plain_text). connectors[i]
    is the boolean joining positives[i] to positives[i-1] ('AND' or 'OR')."""
    positives = []
    negatives = []
    connectors = []
    next_conn = 'AND'
    for raw in _TOKEN_RE.findall(query):
        neg = raw.startswith('-')
        body = raw[1:] if neg else raw
        if not body:
            continue
        # Bare uppercase OR between two terms switches the next connector.
        if body == 'OR' and not neg:
            if positives:
                next_conn = 'OR'
            continue
        prefix = False
        if body.startswith('"'):
            # "quoted phrase" with optional trailing * (prefix on last token).
            if body.endswith('"*'):
                prefix = True
                inner = body[1:-2]
            else:
                inner = body[1:-1] if body.endswith('"') else body[1:]
        else:
            if body.endswith('*'):
                prefix = True
                inner = body[:-1]
            else:
                inner = body
        inner = inner.strip()
        if not inner:
            continue
        fts = _fts_quote(inner) + ('*' if prefix else '')
        if neg:
            negatives.append((fts, inner))
        else:
            positives.append((fts, inner))
            connectors.append(next_conn if len(positives) > 1 else 'AND')
            next_conn = 'AND'
    return positives, negatives, connectors


def build_match(query):
    """Return an FTS5 MATCH expression for `query`, or None if it has no
    usable positive term (empty, whitespace, or only exclusions — neither of
    which defines a result set)."""
    positives, negatives, connectors = _parse(query or '')
    if not positives:
        return None
    parts = []
    for i, (fts, _plain) in enumerate(positives):
        if i > 0:
            parts.append(connectors[i])
        parts.append(fts)
    expr = ' '.join(parts)
    if negatives:
        expr = f'({expr}) NOT ({" OR ".join(n for n, _ in negatives)})'
    return expr


def case_groups(query):
    """The positive terms grouped the way FTS5 evaluates them: a list of
    AND-groups joined by OR. `bread OR wine water` → [['bread'],
    ['wine', 'water']].

    Measured against SQLite rather than assumed: FTS5 binds AND tighter than
    OR, so `a OR b AND c` matches `a` alone and `b c` together, not `(a OR b)
    AND c`.
    """
    # Filter terms first: `strong:G26` is not a word anybody's verse
    # contains, and leaving it in made `case_matches` refuse every row
    # (an AND group of ['strong:G26', 'Charity'] matches no text) and the
    # pane highlight hunt for the literal string in the chapter.
    positives, _neg, connectors = _parse(split_filters(query)[1])
    groups = []
    for i, (_fts, plain) in enumerate(positives):
        words = [w for w in plain.split() if w]
        if not words:
            continue
        if not groups or connectors[i] == 'OR':
            groups.append(list(words))
        else:
            groups[-1].extend(words)
    return groups


def case_matches(query, text):
    """Whether `text` carries the query's positive terms in the case they were
    typed — the post-filter both backends run for "Match case".

    Honours the connectors, which is the whole reason it is not a bare
    `all(word in text)`: that read `Jesus OR Christ` as `Jesus AND Christ` and
    threw away 959 of the KJV's 1,217 hits, every one of them cased exactly as
    asked. A query with no usable positive term filters nothing.
    """
    groups = case_groups(query)
    if not groups:
        return True
    body = text or ''
    return any(all(word in body for word in group) for group in groups)


def plain_terms(query):
    """Positive search words in original case, phrases split into their words.

    Used for case-sensitive post-filtering and match highlighting, so the
    highlight reflects exactly what the query asked for — which is why the
    original-language terms come out first. They are not words in any
    verse, and highlighting `strong:G26` in a chapter finds nothing while
    claiming to."""
    positives, _neg, _conn = _parse(split_filters(query)[1])
    words = []
    for _fts, plain in positives:
        words.extend(w for w in plain.split() if w)
    return words


# ── Original-language filters ────────────────────────────────────────────────
#
# A query may carry `strong:`, `lemma:` or `morph:` terms, which no FTS index
# can answer: they ask about the Greek or Hebrew word under the translation,
# and that data lives in the interlinear databases, not in the verse text.
# `split_filters` lifts them out so the rest of the query stays ordinary text
# — `strong:G26 charity` means "verses whose Greek carries G26 AND whose
# translation says charity", which is an intersection of two result sets, not
# one MATCH expression.
#
# The prefix is required. A bare `G26` stays a text search, because a reader
# looking for the letter-number is not asking about Strong's, and silently
# reinterpreting it would make the grammar unpredictable — the one thing this
# module's docstring promises it is not.

FILTER_FIELDS = ('strong', 'lemma', 'morph')

_FILTER_RE = re.compile(
    r'^(-?)(' + '|'.join(FILTER_FIELDS) + r')\s*:\s*(.*)$', re.IGNORECASE)


class Filter(NamedTuple):
    """One original-language term. `field` is a FILTER_FIELDS member,
    `value` the text after the colon (quotes stripped), `negate` whether
    it was written with a leading '-'."""
    field: str
    value: str
    negate: bool


def exclusions(query):
    """The query's exclusion terms rewritten as a positive query.

    `-works` → `works`. Needed because an FTS backend cannot answer
    "everything except works" — it has no result set to subtract from —
    but a caller that already HAS one can: an original-language filter
    defines the verses, and `strong:G26 -love` means those verses minus
    the ones whose text says love. Returns '' when the query excludes
    nothing.

    Several exclusions join with **OR**, matching what `build_match`
    already emits for its own `NOT (a OR b)` clause: `-love -charity`
    means "neither", so the set to subtract is every verse carrying
    either. Joining them the default way instead made it an AND — the
    verses carrying BOTH, which on the KJV is almost none, so
    `strong:G26 -love -charity` subtracted nothing and answered with all
    104 verses rather than 2.
    """
    _pos, negatives, _conn = _parse(query or '')
    terms = [plain if ' ' not in plain else f'"{plain}"'
             for _fts, plain in negatives]
    return ' OR '.join(terms)


def split_filters(query):
    """Pull the original-language terms out of `query`.

    Returns (filters, rest) — `rest` is the query with those tokens
    removed, ready for `build_match` and the case post-filter, and is ''
    when the query was nothing but filters. A filter with an empty value
    (`strong:`, a half-typed query) is dropped rather than matching
    everything."""
    filters = []
    kept = []
    for raw in _TOKEN_RE.findall(query or ''):
        m = _FILTER_RE.match(raw)
        if not m:
            kept.append(raw)
            continue
        value = m.group(3).strip()
        if value.startswith('"') and value.endswith('"') and len(value) > 1:
            value = value[1:-1]
        value = value.strip()
        if not value:
            continue
        filters.append(Filter(m.group(2).lower(), value, bool(m.group(1))))
    return filters, ' '.join(kept)
