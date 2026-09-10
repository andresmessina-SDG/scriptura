"""Tests for search_query.py — the shared FTS5 query-grammar translator.

Two kinds of check:
  1. The MATCH expression has the intended shape.
  2. Every expression actually parses + runs against a real FTS5 table —
     the robustness contract: no user input may raise an FTS5 syntax error.
"""

import sqlite3

import pytest

import search_query as sq


# ── Shape of the generated MATCH expression ─────────────────────────────────

def test_single_word():
    assert sq.build_match('God') == '"God"'


def test_implicit_and():
    assert sq.build_match('living water') == '"living" AND "water"'


def test_quoted_phrase():
    assert sq.build_match('"living water"') == '"living water"'


def test_or_operator():
    assert sq.build_match('bread OR wine') == '"bread" OR "wine"'


def test_exclude():
    assert sq.build_match('faith -works') == '("faith") NOT ("works")'


def test_prefix_word():
    assert sq.build_match('baptiz*') == '"baptiz"*'


def test_prefix_phrase():
    assert sq.build_match('"living wat"*') == '"living wat"*'


def test_only_exclusions_is_none():
    assert sq.build_match('-foo') is None
    assert sq.build_match('-foo -bar') is None


def test_empty_is_none():
    assert sq.build_match('') is None
    assert sq.build_match('    ') is None
    assert sq.build_match(None) is None


def test_embedded_quote_is_escaped():
    # A stray double-quote must be doubled, not break the literal.
    assert sq.build_match('he said "hi') == '"he" AND "said" AND "hi"'


# ── plain_terms (case-filter / highlight source) ────────────────────────────

def test_plain_terms_splits_phrases():
    assert sq.plain_terms('"living water" God') == ['living', 'water', 'God']


def test_plain_terms_drops_exclusions():
    assert sq.plain_terms('faith -works') == ['faith']


def test_plain_terms_strips_prefix_star():
    assert sq.plain_terms('baptiz*') == ['baptiz']


# ── Robustness: nothing the user types may raise an FTS5 error ───────────────

@pytest.fixture
def fts():
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize='unicode61')")
    conn.executemany('INSERT INTO t(content) VALUES (?)', [
        ('For God so loved the world',),
        ('In the beginning God created the heavens',),
        ('The Lord is my shepherd I shall not want',),
        ('living water springs up',),
    ])
    conn.commit()
    return conn


_HOSTILE = [
    'God', 'living water', '"living water"', 'bread OR wine', 'faith -works',
    'baptiz*', '', '   ', '"', '""', '"""', ')(', 'a AND OR NOT b',
    '* * *', '-', '- -', 'God )', '( God', 'NEAR(a b)', "O'Brien",
    'מַ"לְאַךְ', 'Ἰησοῦς*', '100%', '[Lord]', 'a*b*c', '"unclosed',
]


@pytest.mark.parametrize('q', _HOSTILE)
def test_no_input_raises_fts_error(fts, q):
    expr = sq.build_match(q)
    if expr is None:
        return
    # Must execute without sqlite3.OperationalError ("fts5: syntax error").
    fts.execute('SELECT rowid FROM t WHERE t MATCH ?', (expr,)).fetchall()


# ── End-to-end semantics against real FTS5 ──────────────────────────────────

def test_phrase_vs_loose_and(fts):
    # "living water" (phrase) matches; the loose AND of the two words also
    # matches the same row here, but the phrase must not match a row with the
    # words apart.
    fts.execute('INSERT INTO t(content) VALUES (?)',
                ('water of living hope',))
    fts.commit()
    phrase = fts.execute('SELECT count(*) FROM t WHERE t MATCH ?',
                         (sq.build_match('"living water"'),)).fetchone()[0]
    loose = fts.execute('SELECT count(*) FROM t WHERE t MATCH ?',
                        (sq.build_match('living water'),)).fetchone()[0]
    assert phrase == 1          # only the adjacent "living water" row
    assert loose == 2           # both rows containing both words


def test_word_boundary_not_substring(fts):
    # The core eBible fix: a word query must not match inside another word.
    fts.execute('INSERT INTO t(content) VALUES (?)', ('a clever person',))
    fts.commit()
    rows = fts.execute('SELECT content FROM t WHERE t MATCH ?',
                       (sq.build_match('lever'),)).fetchall()
    assert rows == []           # "lever" must NOT match "clever"


# ── The case-sensitive post-filter ───────────────────────────────────────────
#
# Both backends run it over the matched text, because FTS5's unicode61
# tokenizer folds case at index time. It has to honour the connectors: reading
# `Jesus OR Christ` as `Jesus AND Christ` threw away 959 of the KJV's 1,217
# hits, every one of them cased exactly as the reader asked.

def test_case_groups_splits_at_or():
    assert sq.case_groups('bread OR wine') == [['bread'], ['wine']]
    assert sq.case_groups('living water') == [['living', 'water']]
    assert sq.case_groups('"living water"') == [['living', 'water']]


def test_case_groups_binds_and_tighter_than_or():
    """Measured against SQLite, not assumed: FTS5 reads `a OR b AND c` as
    `a OR (b AND c)`, so the groups must too."""
    assert sq.case_groups('God OR LORD saith') == \
        [['God'], ['LORD', 'saith']]


def test_case_groups_ignores_exclusions():
    """FTS5 has already dropped the excluded verses; re-testing them here
    would only reject on case."""
    assert sq.case_groups('faith -Works') == [['faith']]


def test_an_or_query_keeps_either_side():
    assert sq.case_matches('Jesus OR Christ',
                                     'the Christ of God') is True
    assert sq.case_matches('Jesus OR Christ',
                                     'Jesus wept') is True
    assert sq.case_matches('Jesus OR Christ',
                                     'the LORD of hosts') is False


def test_an_and_query_still_needs_every_word():
    assert sq.case_matches('Jesus Christ', 'Jesus Christ') is True
    assert sq.case_matches('Jesus Christ', 'the Christ') is False


def test_the_case_must_match():
    assert sq.case_matches('LORD', 'the LORD said') is True
    assert sq.case_matches('LORD', 'the Lord said') is False


def test_a_query_with_no_positive_term_filters_nothing():
    assert sq.case_matches('', 'anything') is True
    assert sq.case_matches('-works', 'anything') is True
