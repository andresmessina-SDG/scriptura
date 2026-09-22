"""Tests for lemma_index.py and the original-language half of the search
grammar — searching by the Greek or Hebrew word under the translation.

The fixtures build tiny word tables by hand rather than leaning on an
installed interlinear database: CI has neither, and the rows that matter
here (a compound's affix chain, a homonym sharing one spelling, a word
the reading stream leaves out) are exactly the ones a real corpus makes
hard to isolate.
"""

import sqlite3

import pytest

import interlinear_data as idata
import lemma_index as li
import search_query as sq


_COLUMNS = '''CREATE TABLE words (
    book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
    pos INTEGER NOT NULL, wtype TEXT NOT NULL, in_stream INTEGER NOT NULL,
    surface TEXT NOT NULL, translit TEXT NOT NULL, gloss TEXT NOT NULL,
    strongs TEXT NOT NULL, strongs_all TEXT NOT NULL,
    strongs_ext TEXT NOT NULL, morph TEXT NOT NULL, lemma TEXT NOT NULL,
    lemma_gloss TEXT NOT NULL, editions TEXT NOT NULL,
    variant TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (book, chapter, verse, pos)) WITHOUT ROWID'''


def _word(book, chapter, verse, pos, surface, strongs, lemma, morph,
          gloss='love', translit='agapē', strongs_all=None, in_stream=1):
    return (book, chapter, verse, pos, 'N', in_stream, surface, translit,
            gloss, strongs, strongs_all or strongs, strongs, morph, lemma,
            gloss, '', '', '')


def _build(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(_COLUMNS)
    conn.executemany(
        'INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        rows)
    conn.commit()
    conn.close()


@pytest.fixture
def greek(tmp_path, monkeypatch):
    """A four-verse Greek table: ἀγάπη twice, ἀγαπάω once as an imperative,
    one word the reading stream omits, and one compound whose affix chain
    carries a second Strong's number."""
    db = tmp_path / 'greek.sqlite'
    _build(db, [
        _word('Matthew', 24, 12, 1, 'ἀγάπη', 'G26', 'ἀγάπη', 'N-NSF'),
        _word('John', 15, 12, 1, 'ἀγαπᾶτε', 'G25', 'ἀγαπάω', 'V-PAM-2P',
              gloss='love', translit='agapate'),
        _word('John', 15, 12, 2, 'ἀγάπην', 'G26', 'ἀγάπη', 'N-ASF',
              translit='agapēn'),
        # in_stream 0: a TR/Byz-only reading the interlinear does not show.
        _word('John', 15, 13, 1, 'ἀγάπην', 'G26', 'ἀγάπη', 'N-ASF',
              translit='agapēn', in_stream=0),
        # A compound: primary G1473, with G2532 in the affix chain.
        _word('Romans', 7, 25, 1, 'ἐγὼ', 'G1473', 'ἐγώ', 'P-1NS',
              gloss='I', translit='egō', strongs_all='G1473 G2532'),
        # Near neighbour, to catch a prefix match that ignores boundaries.
        _word('Romans', 7, 25, 2, 'x', 'G260', 'ἅμα', 'ADV',
              gloss='together', translit='hama'),
    ])
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK, str(db))
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW,
                        str(tmp_path / 'absent.sqlite'))
    monkeypatch.setattr(idata, '_migrated', set())
    return db


@pytest.fixture
def hebrew(tmp_path, monkeypatch):
    """One Hebrew spelling covering three different words — the homonym
    trap, taken from the real corpus (חֶ֫סֶד is H2617 'kindness' 245×,
    H2617 'shame' 2×, and the name H2618 'Hesed' once)."""
    db = tmp_path / 'hebrew.sqlite'
    _build(db, [
        _word('Genesis', 19, 19, 1, 'חַסְדְּ', 'H2617', 'חֶסֶד', 'HNcmsc',
              gloss='kindness', translit='chesed'),
        _word('Psalms', 23, 6, 1, 'חֶסֶד', 'H2617', 'חֶסֶד', 'HNcmsa',
              gloss='kindness', translit='chesed'),
        _word('Leviticus', 20, 17, 1, 'חֶסֶד', 'H2617', 'חֶסֶד', 'HNcmsa',
              gloss='shame', translit='chesed'),
        _word('1 Chronicles', 4, 20, 1, 'חֶסֶד', 'H2618', 'חֶסֶד', 'HNpm',
              gloss='Hesed', translit='chesed'),
    ])
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW, str(db))
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK,
                        str(tmp_path / 'absent.sqlite'))
    monkeypatch.setattr(idata, '_migrated', set())
    return db


def _f(query):
    filters, _rest = sq.split_filters(query)
    return filters


# ── The grammar ─────────────────────────────────────────────────────────────

def test_filters_are_lifted_out_of_the_query():
    filters, rest = sq.split_filters('strong:G26 charity')
    assert filters == [sq.Filter('strong', 'G26', False)]
    assert rest == 'charity'


def test_a_bare_strongs_number_stays_a_text_search():
    """`G26` is a word a reader may be looking for; only the prefix asks
    the interlinear. The grammar promises to be predictable."""
    filters, rest = sq.split_filters('G26 love')
    assert filters == []
    assert rest == 'G26 love'


def test_every_field_and_negation_parses():
    filters, rest = sq.split_filters('lemma:ἀγάπη -morph:N-NSF water')
    assert filters == [sq.Filter('lemma', 'ἀγάπη', False),
                       sq.Filter('morph', 'N-NSF', True)]
    assert rest == 'water'


def test_a_half_typed_filter_is_dropped_not_matched():
    """`strong:` with nothing after it must not become 'every word'."""
    assert sq.split_filters('strong: love') == ([], 'love')


def test_a_quoted_value_loses_its_quotes():
    assert sq.split_filters('lemma:"ἀγάπη"')[0] == [
        sq.Filter('lemma', 'ἀγάπη', False)]


def test_the_field_prefix_is_case_insensitive():
    assert sq.split_filters('Strong:G26')[0] == [
        sq.Filter('strong', 'G26', False)]


def test_a_filtered_query_still_builds_a_match_for_the_rest():
    _filters, rest = sq.split_filters('strong:G26 charity')
    assert sq.build_match(rest) == '"charity"'


# ── Strong's matching ───────────────────────────────────────────────────────

def test_padding_and_case_do_not_matter(greek):
    for written in ('G26', 'G0026', 'g26', 'g0026'):
        assert li.refs(_f(f'strong:{written}')) == [
            ('Matthew', 24, 12), ('John', 15, 12)]


def test_a_strongs_number_does_not_match_its_longer_neighbour(greek):
    """G26 must never gather G260 — the bug the lexicon panel's own
    scan pattern carries a negative lookahead for."""
    assert ('Romans', 7, 25) not in li.refs(_f('strong:G26'))
    assert li.refs(_f('strong:G260')) == [('Romans', 7, 25)]


def test_a_compound_answers_to_every_number_in_its_chain(greek):
    """ἐγὼ is stored as G1473 with G2532 in strongs_all; asking for either
    must find it, or a search for καί silently misses the words that
    absorbed it."""
    assert li.refs(_f('strong:G1473')) == [('Romans', 7, 25)]
    assert li.refs(_f('strong:G2532')) == [('Romans', 7, 25)]


def test_an_unparseable_number_matches_nothing_rather_than_everything(greek):
    assert li.refs(_f('strong:banana')) == []
    assert li.describe(_f('strong:banana')) is None


# ── Lemma and morphology ────────────────────────────────────────────────────

def test_lemma_matches_the_dictionary_form_exactly(greek):
    assert li.refs(_f('lemma:ἀγάπη')) == [('Matthew', 24, 12),
                                          ('John', 15, 12)]
    assert li.refs(_f('lemma:ἀγαπάω')) == [('John', 15, 12)]


def test_a_decomposed_lemma_still_matches(greek):
    """The source ships NFD and the parser stores NFC; a lemma pasted
    from anywhere else has to be folded or it compares unequal while
    looking identical."""
    import unicodedata
    assert li.refs(_f('lemma:' + unicodedata.normalize('NFD', 'ἀγάπη'))) == [
        ('Matthew', 24, 12), ('John', 15, 12)]


def test_morphology_matches_inside_the_code(greek):
    """`V-PAM` finds `V-PAM-2P`: a reader asking for an imperative does
    not know the person and number they want."""
    assert li.refs(_f('morph:V-PAM')) == [('John', 15, 12)]
    assert li.refs(_f('morph:N-NSF')) == [('Matthew', 24, 12)]


def test_morphology_is_case_sensitive(greek):
    """OSHM codes mean different things in different cases (`Ncmsc` is
    not `NCMSC`), so folding them would merge distinct answers."""
    assert li.refs(_f('morph:v-pam')) == []


def test_filters_combine_as_an_intersection(greek):
    assert li.refs(_f('strong:G26 morph:N-ASF')) == [('John', 15, 12)]


def test_a_negated_filter_excludes(greek):
    assert li.refs(_f('strong:G26 -morph:N-NSF')) == [('John', 15, 12)]


# ── What the reading stream shows ───────────────────────────────────────────

def test_a_word_the_interlinear_does_not_show_is_not_counted(greek):
    """John 15:13 carries a TR/Byz-only ἀγάπην. It is real data and it is
    not in the verse the reader has open, so a concordance that counted
    it would disagree with the page."""
    assert ('John', 15, 13) not in li.refs(_f('strong:G26'))
    assert li.describe(_f('strong:G26')).occurrences == 2


# ── Counts and identification ───────────────────────────────────────────────

def test_describe_names_the_word_behind_a_strongs_search(greek):
    sense = li.describe(_f('strong:G26'))
    assert (sense.strongs, sense.lemma, sense.gloss) == ('G26', 'ἀγάπη',
                                                         'love')
    assert sense.occurrences == 2


def test_the_transliteration_comes_from_the_lexical_form(greek):
    """Asking for G26 without the nominative leaves only ἀγάπην, whose
    transliteration is `agapēn`. Printing that beside the lemma ἀγάπη
    would be plausible and wrong, so it is left blank."""
    assert li.describe(_f('strong:G26')).translit == 'agapē'
    assert li.describe(_f('strong:G26 -morph:N-NSF')).translit == ''


def test_a_morphology_only_search_names_no_word(greek):
    """`morph:A` gathers ἀγαπᾶτε, ἀγάπην and ἅμα — three different words,
    so there is no word to name over them."""
    sense = li.describe(_f('morph:A'))
    assert sense.lemma == '' and sense.strongs == '' and sense.gloss == ''
    assert sense.occurrences == 3


def test_one_spelling_covering_several_words_is_reported_as_several(hebrew):
    """A lemma search is not a word search. Printing one header over
    H2617 'kindness', its homonym 'shame' and the name H2618 would teach
    something false."""
    found = li.senses(_f('lemma:חֶסֶד'))
    assert [(s.strongs, s.gloss, s.occurrences) for s in found] == [
        ('H2617', 'kindness', 2), ('H2617', 'shame', 1),
        ('H2618', 'Hesed', 1)]
    header = li.describe(_f('lemma:חֶסֶד'))
    assert header.gloss == '' and header.strongs == ''


def test_results_come_back_in_canonical_order(hebrew):
    assert li.refs(_f('lemma:חֶסֶד')) == [
        ('Genesis', 19, 19), ('Leviticus', 20, 17),
        ('1 Chronicles', 4, 20), ('Psalms', 23, 6)]


# ── Availability ────────────────────────────────────────────────────────────

def test_nothing_installed_is_reported_not_answered_as_no_matches(
        tmp_path, monkeypatch):
    """An empty result from a missing database reads as 'this word never
    occurs', which is the worst thing a concordance can say."""
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK,
                        str(tmp_path / 'absent.sqlite'))
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW,
                        str(tmp_path / 'absent2.sqlite'))
    assert not li.is_available()
    assert li.refs(_f('strong:G26')) == []


def test_one_installed_database_is_enough(greek):
    assert li.is_available()


# ── The search backend ──────────────────────────────────────────────────────

class _FakeModule:
    """A one-chapter Bible, enough to check the join between references
    and verse text without a SWORD install."""

    CHAPTERS = {
        ('Matthew', 24): [(12, '<w>And</w> the <w>love</w> of many'),
                          (13, 'But he that shall endure')],
        ('John', 15): [(12, 'That ye <w>love</w> one another'),
                       (13, 'Greater love hath no man')],
        ('Romans', 7): [(25, 'I thank God')],
    }


@pytest.fixture
def backend(greek, monkeypatch):
    """The controller wired to a fake translation, so the test measures the
    join and not SWORD."""
    import content
    import search_controller as sc
    monkeypatch.setattr(
        content, 'load_chapter',
        lambda mod, book, ch: _FakeModule.CHAPTERS.get((book, ch), []))
    monkeypatch.setattr(sc.sword_bridge, 'map_target_verse',
                        lambda mod, book, ch, v: v)
    return sc


def test_a_strongs_query_returns_the_readers_own_translation(backend):
    rows, truncated = backend.split_truncation(
        backend.search_backend('AnyBible', 'strong:G26', False))
    assert not truncated
    assert rows == [('Matthew', 24, 12, 'And the love of many'),
                    ('John', 15, 12, 'That ye love one another')]


def test_text_and_word_terms_intersect(backend, monkeypatch):
    """`strong:G26 another` is the question a concordance exists to
    answer: where was this one Greek word rendered that way."""
    monkeypatch.setattr(
        backend, '_text_backend',
        lambda module, query, case, *a, **k: [
            ('John', 15, 12, 'That ye love one another')])
    rows, _t = backend.split_truncation(
        backend.search_backend('AnyBible', 'strong:G26 another', False))
    assert rows == [('John', 15, 12, 'That ye love one another')]


def test_a_verse_the_module_does_not_carry_is_dropped(backend, monkeypatch):
    """A New Testament module has nothing to say about Genesis, and an
    empty row would read as a verse with no text in it."""
    monkeypatch.setattr(
        backend.content, 'load_chapter', lambda mod, book, ch: [])
    rows, _t = backend.split_truncation(
        backend.search_backend('AnyBible', 'strong:G26', False))
    assert rows == []


def test_an_ordinary_query_still_goes_to_the_text_backend(backend,
                                                          monkeypatch):
    seen = {}

    def fake(module, query, case, *a, **k):
        seen['query'] = query
        return [('John', 3, 16, 'For God so loved')]

    monkeypatch.setattr(backend, '_text_backend', fake)
    rows, _t = backend.split_truncation(
        backend.search_backend('AnyBible', 'loved', False))
    assert seen['query'] == 'loved'
    assert rows == [('John', 3, 16, 'For God so loved')]


def test_the_truncation_sentinel_is_appended_like_every_backend(
        backend, monkeypatch):
    monkeypatch.setattr(backend.sword_bridge, 'MAX_SEARCH_RESULTS', 1)
    results = backend.search_backend('AnyBible', 'strong:G26', False)
    rows, truncated = backend.split_truncation(results)
    assert truncated and len(rows) == 1


def test_a_mapped_psalter_is_asked_for_its_own_verse_number(
        greek, monkeypatch):
    """References are app-space; a mapped module numbers its rendered
    chapter its own way. Looking the app number straight up returns the
    neighbouring verse."""
    import content
    import search_controller as sc
    asked = []
    monkeypatch.setattr(sc.sword_bridge, 'map_target_verse',
                        lambda mod, book, ch, v: v + 1)
    monkeypatch.setattr(
        content, 'load_chapter',
        lambda mod, book, ch: [(13, 'the verse one further on')])

    def note(mod, book, ch):
        asked.append((book, ch))
        return [(13, 'the verse one further on')]

    monkeypatch.setattr(content, 'load_chapter', note)
    rows, _t = sc.split_truncation(
        sc.search_backend('Mapped', 'strong:G26', False))
    assert ('Matthew', 24, 12, 'the verse one further on') in rows


# ── Regressions, each measured before it was fixed ──────────────────────────

def test_only_exclusions_define_no_result_set(greek):
    """The text grammar refuses a query that is only exclusions; so must
    this half. `-morph:N-NSF` alone returned 31,170 verses — the whole
    Bible minus its feminine nominative nouns."""
    assert li.refs(_f('-morph:N-NSF')) == []
    assert li.refs(_f('-strong:G26')) == []
    # A positive alongside it is a different question, and still answered.
    assert li.refs(_f('strong:G26 -morph:N-NSF')) == [('John', 15, 12)]


def test_exclusions_rewrite_as_a_positive_query():
    assert sq.exclusions('faith -works') == 'works'
    assert sq.exclusions('faith') == ''
    # OR, not AND: -love -charity means NEITHER, so the set to subtract is
    # every verse carrying either. Joined the other way, `strong:G26 -love
    # -charity` subtracted the verses carrying BOTH — almost none — and
    # answered with all 104 instead of 2.
    assert sq.exclusions('-love -charity') == 'love OR charity'
    assert sq.exclusions('-"living water"') == '"living water"'


def test_an_exclusion_subtracts_from_the_words_verses(backend, monkeypatch):
    """`strong:G26 -love` is the verses with ἀγάπη that do NOT say love —
    where a reader finds the places the King James says charity instead.
    Handing `-love` to the text backend got it dropped (all the verses
    came back); handing it over whole got none of them."""
    def text(module, query, case, *a, **k):
        assert query == 'love', f'the exclusion went over as {query!r}'
        return [('Matthew', 24, 12, 'And the love of many')]

    monkeypatch.setattr(backend, '_text_backend', text)
    rows, _t = backend.split_truncation(
        backend.search_backend('AnyBible', 'strong:G26 -love', False))
    assert [r[:3] for r in rows] == [('John', 15, 12)]


def test_a_capped_text_half_reports_the_answer_as_inexact(backend,
                                                          monkeypatch):
    """Subtracting a set the backend truncated leaves rows in that should
    have gone. The reader is told, rather than shown a short answer as a
    complete one."""
    monkeypatch.setattr(
        backend, '_text_backend',
        lambda module, query, case, *a, **k: [
            ('Matthew', 24, 12, 'x'), ('', 0, 0, '')])
    results = backend.search_backend('AnyBible', 'strong:G26 -love', False)
    _rows, truncated = backend.split_truncation(results)
    assert truncated


def test_the_text_helpers_ignore_the_filter_terms():
    """`strong:G26` is not a word in anyone's verse. Left in, it made the
    Match-case post-filter refuse every row and sent the pane highlight
    hunting for the literal string in the chapter."""
    assert sq.plain_terms('strong:G26 charity') == ['charity']
    assert sq.case_groups('strong:G26 Charity') == [['Charity']]
    assert sq.case_matches('strong:G26 Charity', 'I speak with Charity')
    assert not sq.case_matches('strong:G26 Charity', 'i speak with charity')
    # A query that is only filters post-filters nothing, rather than
    # refusing everything.
    assert sq.case_matches('strong:G26', 'any verse at all')
    # The plain grammar is untouched.
    assert sq.plain_terms('living water') == ['living', 'water']
    assert sq.case_groups('bread OR wine water') == [['bread'],
                                                     ['wine', 'water']]


def test_the_filter_prefix_does_not_swallow_ordinary_words():
    """The grammar has to stay predictable for a reader who never heard of
    Strong's numbers. Quoting escapes the prefix, which is the documented
    way out if a verse ever needs the literal text."""
    for plain in ('strongly worded', 'morphology', 'Genesis 1:1',
                  'a-strong:G26', '"strong:G26"'):
        assert sq.split_filters(plain) == ([], plain), plain
