"""interlinear_data: TAGNT/TAHOT line parsing, stream typing, Strong's
normalization, and (when the raw files are present locally) full offline
build + query round-trips for both testaments."""
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

# Real TAHOT rows.
HEB_ROW_PREFIXED = (
    'Gen.1.1#01=L\tבְּ/רֵאשִׁ֖ית\tbe./re.Shit\tin/ beginning\t'
    'H9003/{H7225G}\tHR/Ncfsa\t\t\tH7225G\t\t\t'
    'H9003=ב=in/{H7225G=רֵאשִׁית=: beginning»first:1_beginning}\t\t\t\t\t')
HEB_ROW_VERB = (
    'Gen.1.1#02=L\tבָּרָ֣א\tba.Ra\'\the created\t{H1254A}\tHVqp3ms\t\t\t'
    'H1254A\t\t\t{H1254A=בָּרָא=to create}\t\t\t\t\t')
HEB_ROW_SOF_PASUQ = (
    'Gen.1.1#07=L\tהָ/אָֽרֶץ\\׃\tha./\'A.retz\tthe/ earth\t'
    'H9009/{H0776G}\\H9016\tHTd/Ncfsa\t\t\tH0776G\t\t\t'
    'H9009=ה=the/{H0776G=אֶ֫רֶץ=: country;_planet»land:2_country}\t\t\t\t\t')
HEB_ROW_QERE = (
    'Jos.2.13#09=Q(K)\tאַחְיוֹתַ֔/י\t\'a.cho.ta/i\tsisters/ my\t'
    '{H0269}/H9020\tHNcfpc/Sp1bs\tK= ... \tL= ...\tH0269\t\t\t'
    '{H0269=אָחוֹת=sister}\t\t\t\t\t')
HEB_ROW_ALT_NUMBERING = (
    'Psa.56.7(56.8)#02=L\tאֵין\t\'ein\tnot\t{H0369}\tHNcbsc\t\t\t'
    'H0369\t\t\t{H0369=אַ֫יִן=nothing}\t\t\t\t\t')
HEB_ROW_INSERTION = (
    'Psa.25.21#0501=X\tיְהוָה\tYah.weh\tYahweh\t{H3068G}\tHNpt\t\t\t'
    'H3068G\t\t\t{H3068G=יהוה=LORD»LORD@Gen.1.1-Heb}\t\t\t\t\t')


# ── Greek parser ──────────────────────────────────────────────────────────────

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
    assert row.rendered


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
    assert row.strongs == 'G2424'
    assert 'G2424G' in row.strongs_ext


def test_tr_only_row_parses_but_is_not_rendered():
    row = idata.parse_line(ROW_TR_ONLY)
    assert row is not None
    assert not row.rendered


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


# ── Hebrew parser ─────────────────────────────────────────────────────────────

def test_heb_prefixed_word():
    row = idata.parse_line_hebrew(HEB_ROW_PREFIXED)
    assert row is not None
    assert row.book == 'Genesis'
    assert (row.chapter, row.verse, row.pos) == (1, 1, 1)
    assert row.surface == 'בְּרֵאשִׁ֖ית'          # morpheme slash joined
    assert row.translit == 'be.re.Shit'
    assert row.gloss == 'in beginning'
    assert row.strongs == 'H7225'                # braced content word
    assert row.strongs_all == 'H7225'            # H9003 affix excluded
    assert row.morph == 'HR/Ncfsa'
    assert row.lemma == 'רֵאשִׁית'
    assert row.lemma_gloss == 'beginning'
    assert row.rendered


def test_heb_plain_verb():
    row = idata.parse_line_hebrew(HEB_ROW_VERB)
    assert row is not None
    assert row.surface == 'בָּרָ֣א'
    assert row.strongs == 'H1254'
    assert row.morph == 'HVqp3ms'
    assert row.lemma_gloss == 'to create'


def test_heb_sof_pasuq_kept_backslashes_stripped():
    row = idata.parse_line_hebrew(HEB_ROW_SOF_PASUQ)
    assert row is not None
    assert row.surface == 'הָאָֽרֶץ׃'             # \ gone, sof pasuq kept
    assert '\\' not in row.surface


def test_heb_parashah_marker_stripped():
    row = idata.parse_line_hebrew(
        'Num.7.89#17=L\tפְּדָה/ /צֽוּר\\׃\\ \\פ\tpe.da.Tsur\tPedahzur\t'
        '{H6301}\tHNpm\t\t\tH6301\t\t\t{H6301=פְּדָהצוּר=Pedahzur}\t\t\t\t\t')
    assert row is not None
    assert not row.surface.endswith('פ')
    assert row.surface.endswith('׃')


def test_heb_qere_row_rendered():
    row = idata.parse_line_hebrew(HEB_ROW_QERE)
    assert row is not None
    assert row.rendered                          # Qere reads in the stream
    assert row.strongs == 'H269'
    assert row.strongs_all == 'H269'             # suffix H9020 excluded


def test_heb_alt_versification_uses_english_numbers():
    row = idata.parse_line_hebrew(HEB_ROW_ALT_NUMBERING)
    assert row is not None
    assert row.book == 'Psalms'
    assert (row.chapter, row.verse) == (56, 7)   # English-first, app-space


def test_heb_insertion_row_not_rendered():
    row = idata.parse_line_hebrew(HEB_ROW_INSERTION)
    assert row is not None
    assert not row.rendered                      # X = stored, not shown


def test_heb_rejects_greek_rows():
    assert idata.parse_line_hebrew(ROW_SIMPLE) is None


# ── Offline end-to-end builds (need raw files downloaded locally) ────────────

_SCRATCH = ('/tmp/scriptura-build/'
            'scratchpad')
_GREEK_RAW = [f'{_SCRATCH}/tagnt1.txt', f'{_SCRATCH}/tagnt2.txt']
_HEBREW_RAW = [f'{_SCRATCH}/tahot{i}.txt' for i in (1, 2, 3, 4)]


def _file_urls(paths_):
    return ['file://' + urllib.request.pathname2url(p) for p in paths_]


@pytest.mark.skipif(
    not all(os.path.exists(p) for p in _GREEK_RAW),
    reason='raw TAGNT files not downloaded locally')
def test_full_greek_build_and_query(tmp_path, monkeypatch):
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK,
                        str(tmp_path / 'greek.sqlite'))
    monkeypatch.setitem(idata._MODULES[idata.GREEK], 'urls',
                        _file_urls(_GREEK_RAW))

    progress = []
    idata.download_and_build(
        idata.GREEK, on_progress=lambda d, t: progress.append((d, t)))

    assert idata.is_installed(idata.GREEK)
    assert progress and progress[-1][0] > 25_000_000

    words = idata.load_chapter(idata.GREEK, 'John', 1)
    v1 = [w for w in words if w.verse == 1]
    assert [w.surface for w in v1][:4] == ['Ἐν', 'ἀρχῇ', 'ἦν', 'ὁ']
    logos = v1[4]
    assert logos.strongs == 'G3056'
    assert logos.morph == 'N-NSM'

    conn = sqlite3.connect(idata._DB_FILES[idata.GREEK])
    n_books = conn.execute(
        'SELECT COUNT(DISTINCT book) FROM words').fetchone()[0]
    n_words = conn.execute(
        'SELECT COUNT(*) FROM words WHERE in_stream=1').fetchone()[0]
    conn.close()
    assert n_books == 27
    assert 130_000 < n_words < 140_000

    assert idata.chapter_count(idata.GREEK, 'Matthew') == 28
    assert idata.chapter_count(idata.GREEK, 'Genesis') == 0


@pytest.mark.skipif(
    not all(os.path.exists(p) for p in _HEBREW_RAW),
    reason='raw TAHOT files not downloaded locally')
def test_full_hebrew_build_and_query(tmp_path, monkeypatch):
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW,
                        str(tmp_path / 'hebrew.sqlite'))
    monkeypatch.setitem(idata._MODULES[idata.HEBREW], 'urls',
                        _file_urls(_HEBREW_RAW))

    idata.download_and_build(idata.HEBREW)
    assert idata.is_installed(idata.HEBREW)

    words = idata.load_chapter(idata.HEBREW, 'Genesis', 1)
    v1 = [w for w in words if w.verse == 1]
    assert v1[0].surface == 'בְּרֵאשִׁ֖ית'
    assert v1[0].strongs == 'H7225'
    assert v1[1].surface == 'בָּרָ֣א'
    assert len(v1) == 7

    conn = sqlite3.connect(idata._DB_FILES[idata.HEBREW])
    n_books = conn.execute(
        'SELECT COUNT(DISTINCT book) FROM words').fetchone()[0]
    n_words = conn.execute(
        'SELECT COUNT(*) FROM words WHERE in_stream=1').fetchone()[0]
    n_all = conn.execute('SELECT COUNT(*) FROM words').fetchone()[0]
    conn.close()
    assert n_books == 39
    assert 280_000 < n_words < 320_000
    assert n_all > n_words                       # X rows stored, hidden

    # Restored verses (Leningrad omits, KJV app-space carries) reachable.
    jos = idata.load_chapter(idata.HEBREW, 'Joshua', 21)
    assert any(w.verse == 36 for w in jos)

    assert idata.chapter_count(idata.HEBREW, 'Psalms') == 150
    assert idata.chapter_count(idata.HEBREW, 'Matthew') == 0

    # Bridge surface covers both testaments.
    assert idata.is_interlinear_module(idata.HEBREW)
    assert idata.is_hebrew(idata.HEBREW)
    assert not idata.is_hebrew(idata.GREEK)
