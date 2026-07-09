"""interlinear_data: TAGNT line parsing, NA-stream typing, Strong's
normalization, and (when the raw files are present locally) a full
offline build + query round-trip."""
import os
import sqlite3
import urllib.request

import pytest

import interlinear_data as idata

# Real TAGNT rows (STEPBible CC BY 4.0), verbatim from the shipped files.
ROW_SIMPLE = (
    'Mat.1.1#01=NKO\tΒίβλος (Biblos)\t[The] book\tG0976=N-NSF\t'
    'βίβλος=book\tNA28+NA27+Tyn+SBL+WH+Treg+TR+Byz\t\t\tLibro\tbook\t'
    '#01\tG0976\t\t\t\t\t')
ROW_PROPER = (
    'Mat.1.1#06=NKO\tΔαυὶδ (Dauid)\tof David\tG1138=N-GSM-P\t'
    'Δαυείδ, Δαυίδ, Δαβίδ=David\tNA28+NA27+Tyn+SBL+WH+Treg+TR+Byz\t\t'
    'Tyn+WH: Δαυεὶδ ; +TR: Δαβὶδ ; \tde David\tDavid»David|David@Rut.4.17\t'
    '#06\tG1138\t\t\t\t\t')
ROW_COMPOUND = (
    'Mat.2.8#19=NKO\tκἀγὼ (kagō)\tI also\tG1473=P-1NS + G2532=CONJ\t'
    'κἀγώ=and I\tNA28+NA27+Tyn+SBL+WH+Treg+TR+Byz\t\t\tyo también\tand I\t'
    '#19\tG2504\t\t\t\t\t')
ROW_TR_ONLY = (
    'Mat.1.6#10=k\tὁ (ho)\tthe\tG3588=T-NSM\tὁ=the/this/who\tTR+Byz\t\t\t'
    'el\tthe\t#10»11:G0935\tG3588_c\t\t\t\t\t')
ROW_EXT_STRONG = (
    'Mat.1.1#03=NKO\tἸησοῦ (Iēsou)\tof Jesus\tG2424G=N-GSM-P\t'
    'Ἰησοῦς=Jesus/Joshua\tNA28+NA27+Tyn+SBL+WH+Treg+TR+Byz\t\t\t'
    'de Jesús\tJesus»Jesus|Jesus@Mat.1.1\t#03\tG2424\t\t\t\t\t')


def test_parse_simple_row():
    row = idata.parse_line(ROW_SIMPLE)
    assert row is not None
    assert row.book == 'Matthew'
    assert (row.chapter, row.verse, row.pos) == (1, 1, 1)
    assert row.surface == 'Βίβλος'
    assert row.translit == 'Biblos'
    assert row.gloss == '[The] book'
    assert row.strongs == 'G976'
    assert row.morph == 'N-NSF'
    assert row.lemma == 'βίβλος'
    assert row.lemma_gloss == 'book'
    assert row.editions.startswith('NA28+NA27')
    assert idata.in_na_stream(row.wtype)


def test_parse_variant_spellings_keep_first_lemma():
    row = idata.parse_line(ROW_PROPER)
    assert row is not None
    assert row.lemma == 'Δαυείδ'
    assert row.lemma_gloss == 'David'


def test_parse_compound_word():
    row = idata.parse_line(ROW_COMPOUND)
    assert row is not None
    assert row.strongs == 'G1473'                 # primary = first
    assert row.strongs_all == 'G1473 G2532'
    assert row.morph == 'P-1NS CONJ'


def test_extended_strongs_normalizes_to_plain():
    row = idata.parse_line(ROW_EXT_STRONG)
    assert row is not None
    assert row.strongs == 'G2424'                 # suffix dropped, zeros kept off
    assert 'G2424G' in row.strongs_ext


def test_tr_only_row_parses_but_is_not_na():
    row = idata.parse_line(ROW_TR_ONLY)
    assert row is not None
    assert not idata.in_na_stream(row.wtype)


@pytest.mark.parametrize('marker,expected', [
    ('NKO', True), ('N(k)O', True), ('no', True), ('n', True),
    ('NK(o)', True), ('K', False), ('ko', False), ('O', False),
    ('K(O)', False),
])
def test_na_stream_markers(marker, expected):
    assert idata.in_na_stream(marker) is expected


def test_non_data_lines_return_none():
    assert idata.parse_line('') is None
    assert idata.parse_line('# Mat.1.2\tἈβραὰμ\tἐγέννησεν') is None
    assert idata.parse_line('Summary of words included\tfoo\tbar') is None
    assert idata.parse_line(
        '\t==========\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t') is None


def test_paragraph_markers_stripped_from_surface():
    # TAGNT embeds ¶ layout markers in surface forms (Ἰακώβ.¶).
    row = idata.parse_line(
        'Mat.1.2#09=NKO\tἸακώβ.¶ (Iakōb)\tJacob\tG2384=N-ASM-P\t'
        'Ἰακώβ=Jacob\tNA28+NA27\t\t\tJacob\tJacob\t#09\tG2384\t\t\t\t\t')
    assert row is not None
    assert row.surface == 'Ἰακώβ.'


def test_norm_strongs():
    assert idata._norm_strongs('G0011') == 'G11'
    assert idata._norm_strongs('G2424G') == 'G2424'
    assert idata._norm_strongs('H0430') == 'H430'
    assert idata._norm_strongs('G3588') == 'G3588'


# ── Offline end-to-end build (needs the raw files downloaded locally) ────────

_LOCAL_RAW = [
    os.path.expandvars(
        '/tmp/scriptura-build/'
        'scratchpad/tagnt1.txt'),
    os.path.expandvars(
        '/tmp/scriptura-build/'
        'scratchpad/tagnt2.txt'),
]


@pytest.mark.skipif(
    not all(os.path.exists(p) for p in _LOCAL_RAW),
    reason='raw TAGNT files not downloaded locally')
def test_full_build_and_query(tmp_path, monkeypatch):
    monkeypatch.setattr(idata, '_DB_FILE', str(tmp_path / 'inter.sqlite'))
    monkeypatch.setattr(
        idata, '_URLS',
        ['file://' + urllib.request.pathname2url(p) for p in _LOCAL_RAW])

    progress = []
    idata.download_and_build(on_progress=lambda d, t: progress.append((d, t)))

    assert idata.is_installed()
    assert progress and progress[-1][0] > 25_000_000  # both files streamed

    # John 1:1 — the canonical smoke verse.
    words = idata.load_chapter('John', 1)
    v1 = [w for w in words if w.verse == 1]
    assert [w.surface for w in v1][:4] == ['Ἐν', 'ἀρχῇ', 'ἦν', 'ὁ']
    logos = v1[4]
    assert logos.surface.startswith('λόγος')
    assert logos.strongs == 'G3056'
    assert logos.morph == 'N-NSM'
    assert logos.gloss != ''
    assert logos.translit != ''

    # Whole-canon shape: all 27 books present, plausible word count.
    conn = sqlite3.connect(idata._DB_FILE)
    n_books = conn.execute(
        'SELECT COUNT(DISTINCT book) FROM words').fetchone()[0]
    n_words = conn.execute(
        'SELECT COUNT(*) FROM words WHERE in_na=1').fetchone()[0]
    n_all = conn.execute('SELECT COUNT(*) FROM words').fetchone()[0]
    conn.close()
    assert n_books == 27
    assert 130_000 < n_words < 140_000     # NA-stream words
    assert n_all > n_words                 # TR/Byz-only rows stored too

    assert idata.chapter_count('Matthew') == 28
    assert idata.chapter_count('Jude') == 1
    assert idata.chapter_count('Genesis') == 0

    # Bridge surface
    assert idata.module_names() == [idata.MODULE_NAME]
    assert idata.is_interlinear_module(idata.MODULE_NAME)
    assert not idata.is_interlinear_module('KJV')
