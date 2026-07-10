"""lexicon_panel module helpers: zero-padding-agnostic Strong's matching.

Module markup zero-pads to four digits (strong:G0746) while interlinear
clicks pass the plain form (G746) — the word-study scan and its bold
highlighting must match across both."""
from lexicon_panel import _make_verse_markup, _norm_strong, _scan_pattern

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
