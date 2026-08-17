"""lexicon_panel module helpers: zero-padding-agnostic Strong's matching.

Module markup zero-pads to four digits (strong:G0746) while interlinear
clicks pass the plain form (G746) — the word-study scan and its bold
highlighting must match across both."""
from lexicon_panel import (_extract_segments, _make_verse_markup, _norm_strong,
                           _scan_pattern)

VERSE = ('<w lemma="strong:G1722" morph="robinson:PREP">Ἐν</w> '
         '<w lemma="strong:G0746" morph="robinson:N-DSF">ἀρχῇ</w> '
         '<w lemma="strong:G1510" morph="robinson:V-IAI-3S">ἦν</w>')


def test_norm_strong():
    assert _norm_strong('G0746') == 'G746'
    assert _norm_strong('g746') == 'G746'
    assert _norm_strong('G3056') == 'G3056'
    assert _norm_strong('H0430') == 'H430'


def test_scan_pattern_padding_agnostic():
    for query in ('G746', 'G0746'):
        assert _scan_pattern(query).search(VERSE)
    # The lookahead still rejects longer numbers sharing a prefix.
    assert not _scan_pattern('G74').search(VERSE)
    assert not _scan_pattern('G7460').search(VERSE)


def test_make_verse_markup_bolds_across_padding():
    for query in ('G746', 'G0746'):
        out = _make_verse_markup(VERSE, query)
        assert '<b>ἀρχῇ</b>' in out
        assert '<b>Ἐν</b>' not in out


# ── The capitalised prefix ───────────────────────────────────────────────────

SPA_VERSE = ('<w savlm="Strong:H7225">EN el principio</w> '
             '<w savlm="Strong:H1254">crió</w> '
             '<w savlm="Strong:H0430">Dios</w>')


def test_extract_segments_reads_the_capitalised_prefix():
    """SpaRV1909 writes savlm="Strong:H7225" on nearly every word, and the
    lowercase strong: only inside its rare multi-number tags. Matching case
    sensitively found 15 of 36 verses in John 3 and none in Genesis 1 — a
    fully tagged Bible whose word study was dead."""
    segments = _extract_segments(SPA_VERSE)
    assert [s for _t, s, _m in segments if s] == [['H7225'], ['H1254'], ['H0430']]


def test_make_verse_markup_bolds_a_capitalised_tag():
    out = _make_verse_markup(SPA_VERSE, 'H430')
    assert '<b>Dios</b>' in out
    assert '<b>crió</b>' not in out


def test_the_two_extractors_agree():
    """pane._extract_segments and this module's copy are the same parser
    written twice. Any fix to one that misses the other splits word study
    in the reading pane from word study in the panel."""
    import pane
    assert pane._extract_segments(SPA_VERSE) == _extract_segments(SPA_VERSE)
    assert pane._extract_segments(VERSE) == _extract_segments(VERSE)
