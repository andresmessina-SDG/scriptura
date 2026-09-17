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


# ── The apparatus: what other editions read ──────────────────────────────────
# Real rows. John 1:18 is the famous substitution (θεός / υἱός); Luke 2:14 the
# minor one (εὐδοκίας / εὐδοκία); Matthew 6:13#27 the last word of the
# doxology, whose note carries the whole added text.
ROW_SUBSTITUTION = (
    'Jhn.1.18#07=N(K)O\tθεὸς (theos)\tGod\tG2316=N-NSM-T\tθεός=God\t'
    'NA28+NA27+SBL+WH+Treg\tυἱός (T=huios) son - G5207=N-NSM in: Tyn+TR+Byz'
    '\t\tdios\tGod\t#07\tG2316_b\tG5207\tv υἱός  (<i>huios</i>) \'son\' '
    'occurs in traditional manuscripts (Tyn+TR+Byz) instead of θεὸς  '
    '(<i>theos</i>) \'God\' in older manuscripts (NA28+NA27+SBL+WH+Treg)\t\t\t')
ROW_MINOR = (
    'Luk.2.14#11=N(k)O\tεὐδοκίας.¶ (eudokias)\tof good-will.\tG2107=N-GSF\t'
    'εὐδοκία=goodwill\tNA28+NA27+Tyn+SBL+WH+Treg\tεὐδοκία (t=eudokia) good '
    'will - G2107=N-NSF in: TR+Byz\t\tde pensar bien de\tgoodwill\t#11\tG2107'
    '\t\t\t\t\t')
ROW_ADDED_LAST = (
    'Mat.6.13#27=KO\tἀμήν. (amēn)\tAmen.\tG0281=INJ-HEB\tἀμήν=amen\tTR+Byz\t\t'
    '\tamén\tamen\t#27\tG0281\t\t^ ὅτι   σοῦ    ἐστιν    ἡ    βασιλεία   '
    '(<i>hoti sou estin hē basileia</i>)\t\t\t')
ROW_MULTIWORD_VARIANT = (
    'Mat.5.12#09=N(K)O\tτοῖς (tois)\tin the\tG3588=T-DPM\tὁ=the/this/who\t'
    'NA28+NA27+SBL+WH+Treg\tἐν τοῖς οὐρανοῖς (T=en tois ouranois) in the '
    'heavens - G1722=PREP + G3588=T-DPM + G3772=N-DPM in: TR+Byz\t\t\t\t#09'
    '\tG3588\t\t\t\t\t')


def test_the_other_reading_and_the_note_are_kept():
    row = idata.parse_line(ROW_SUBSTITUTION)
    assert row is not None
    assert row.variant == 'υἱός (T=huios) son - G5207=N-NSM in: Tyn+TR+Byz'
    assert row.note == ("v υἱός (huios) 'son' occurs in traditional manuscripts "
                        "(Tyn+TR+Byz) instead of θεὸς (theos) 'God' in older "
                        'manuscripts (NA28+NA27+SBL+WH+Treg)')


def test_a_row_without_variants_keeps_them_empty():
    row = idata.parse_line(ROW_SIMPLE)
    assert row is not None
    assert row.variant == '' and row.note == ''


def test_hebrew_rows_carry_no_apparatus():
    row = idata.parse_line_hebrew(HEB_ROW_VERB)
    assert row is not None
    assert row.variant == '' and row.note == ''


@pytest.mark.parametrize('raw, expect', [
    ('υἱός (T=huios) son - G5207=N-NSM in: Tyn+TR+Byz',
     idata.Reading('υἱός', 'huios', 'son', 'Tyn+TR+Byz', False)),
    ('εὐδοκία (t=eudokia) good will - G2107=N-NSF in: TR+Byz',
     idata.Reading('εὐδοκία', 'eudokia', 'good will', 'TR+Byz', True)),
    ('ἐν τοῖς οὐρανοῖς (T=en tois ouranois) in the heavens - G1722=PREP + '
     'G3588=T-DPM + G3772=N-DPM in: TR+Byz',
     idata.Reading('ἐν τοῖς οὐρανοῖς', 'en tois ouranois', 'in the heavens',
                   'TR+Byz', False)),
    ('τὰ ἴδια (T=ta idia) <the> own - G3588=T-APN + G2398=A-APN in: Tyn+SBL',
     idata.Reading('τὰ ἴδια', 'ta idia', '<the> own', 'Tyn+SBL', False)),
    ('', None), ('garbage', None),
])
def test_the_other_reading_is_parsed(raw, expect):
    assert idata.parse_reading(raw) == expect


@pytest.mark.parametrize('raw, expect', [
    ('NA28+NA27+Tyn+SBL+WH+Treg+TR+Byz',
     ['NA28', 'NA27', 'Tyn', 'SBL', 'WH', 'Treg', 'TR', 'Byz']),
    ('Treg+TR»1+Byz«2', ['Treg', 'TR', 'Byz']),     # order markers dropped
    ('Byz+TR', ['TR', 'Byz']),                         # canonical order
    ('TR+Byz+KJV+P66', ['TR', 'Byz', 'KJV', 'P66']),  # the rest keep theirs
    ('', []),
])
def test_edition_lists_are_canonical(raw, expect):
    assert idata.editions_of(raw) == expect


def _vw(surface, editions, in_stream, wtype='NKO', variant='', note=''):
    return idata.VariantWord(1, 1, surface, 'gloss', editions, in_stream,
                             wtype, variant, note)


def test_a_word_every_edition_carries_has_no_apparatus():
    assert idata.apparatus(_vw('θεὸς', 'NA28+NA27+Tyn+SBL+WH+Treg+TR+Byz',
                               True)) == idata.Apparatus('', '', '')


def test_a_word_the_critical_text_leaves_out_names_who_has_it():
    ap = idata.apparatus(_vw('ὁ', 'Tyn+TR+Byz', False, 'ko'))
    assert ap.editions == 'Tyn TR Byz'
    assert ap.reading == ''
    assert ap.note == 'In Tyn, TR and Byz; not in the Nestle-Aland text.'


def test_a_word_the_received_text_lacks_names_who_lacks_it():
    ap = idata.apparatus(_vw('εὐδοκίας', 'NA28+NA27+Tyn+SBL+WH+Treg', True))
    assert ap.editions == '− TR Byz'
    assert ap.note == 'Not in TR or Byz.'


def test_a_substitution_names_the_other_reading():
    ap = idata.apparatus(_vw(
        'θεὸς', 'NA28+NA27+SBL+WH+Treg', True, 'N(K)O',
        'υἱός (T=huios) son - G5207=N-NSM in: Tyn+TR+Byz',
        "v υἱός (huios) 'son' occurs in traditional manuscripts (Tyn+TR+Byz) "
        "instead of θεὸς (theos) 'God' in older manuscripts (NA28+NA27+SBL+WH+Treg)"))
    assert ap.editions == '− Tyn TR Byz'
    assert ap.reading == 'Tyn TR Byz: υἱός “son”'
    # The source's own note outranks the generated sentence.
    assert ap.note.startswith("υἱός (huios) 'son' occurs in traditional")


def test_a_minor_reading_is_still_shown():
    """TAGNT calls εὐδοκία 'too minor to affect the translation'; the
    genitive and the nominative are the two readings of Luke 2:14 every
    Christmas sermon argues about, so it is shown all the same."""
    ap = idata.apparatus(_vw(
        'εὐδοκίας', 'NA28+NA27+Tyn+SBL+WH+Treg', True, 'N(k)O',
        'εὐδοκία (t=eudokia) good will - G2107=N-NSF in: TR+Byz'))
    assert ap.reading == 'TR Byz: εὐδοκία “good will”'
    assert ap.note == 'TR and Byz read εὐδοκία “good will”.'


def test_a_supplied_word_in_the_other_reading_loses_its_brackets():
    ap = idata.apparatus(_vw(
        'ἴδια', 'NA28+NA27+WH', True, 'N(K)O',
        'τὰ ἴδια (T=ta idia) <the> own - G3588=T-APN + G2398=A-APN in: Tyn+TR+Byz'))
    assert ap.reading == 'Tyn TR Byz: τὰ ἴδια “the own”'
    assert ap.note == 'Tyn, TR and Byz read τὰ ἴδια “the own”.'


def test_an_added_run_note_is_not_repeated_as_prose():
    """A `^` note lists the added words themselves, which the cells already
    show in place; the generated sentence says who adds them instead."""
    ap = idata.apparatus(_vw('ἀμήν.', 'TR+Byz', False, 'KO', '',
                             '^ ὅτι σοῦ ἐστιν ἡ βασιλεία (hoti sou estin)'))
    assert ap.note == 'In TR and Byz; not in the Nestle-Aland text.'


def test_an_old_database_gains_the_columns_and_asks_for_a_rebuild(
        tmp_path, monkeypatch):
    """A database built before the apparatus columns still answers every
    query (the columns arrive empty), and the Module Manager is told a
    rebuild would fill them."""
    db = tmp_path / 'greek.sqlite'
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE words (
        book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
        pos INTEGER NOT NULL, wtype TEXT NOT NULL, in_stream INTEGER NOT NULL,
        surface TEXT NOT NULL, translit TEXT NOT NULL, gloss TEXT NOT NULL,
        strongs TEXT NOT NULL, strongs_all TEXT NOT NULL,
        strongs_ext TEXT NOT NULL, morph TEXT NOT NULL, lemma TEXT NOT NULL,
        lemma_gloss TEXT NOT NULL, editions TEXT NOT NULL,
        PRIMARY KEY (book, chapter, verse, pos)) WITHOUT ROWID''')
    conn.execute('INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 ('John', 1, 18, 7, 'N(K)O', 1, 'θεὸς', 'theos', 'God',
                  'G2316', 'G2316', 'G2316', 'N-NSM-T', 'θεός', 'God',
                  'NA28+NA27+SBL+WH+Treg'))
    conn.commit()
    conn.close()
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK, str(db))
    monkeypatch.setattr(idata, '_migrated', set())
    assert idata.needs_rebuild(idata.GREEK)
    words = idata.chapter_variants(idata.GREEK, 'John', 1)
    assert words[0].variant == '' and words[0].note == ''
    assert idata.apparatus(words[0]).editions == '− Tyn TR Byz'
    full = idata.load_chapter_full(idata.GREEK, 'John', 1)
    assert full[0].surface == 'θεὸς' and full[0].in_stream
    assert idata.needs_rebuild(idata.GREEK)     # a migration is not a rebuild


def test_a_fresh_build_carries_the_apparatus(tmp_path, monkeypatch):
    """Built from real rows: the columns are filled and the version stamped,
    so needs_rebuild is False. The out-of-stream word is in the full load
    and not in the reading stream."""
    raw = tmp_path / 'tagnt.txt'
    raw.write_text('\n'.join([ROW_SIMPLE, ROW_SUBSTITUTION, ROW_MINOR,
                              ROW_ADDED_LAST, ROW_TR_ONLY]) + '\n',
                   encoding='utf-8')
    monkeypatch.setitem(idata._DB_FILES, idata.GREEK,
                        str(tmp_path / 'greek.sqlite'))
    monkeypatch.setitem(idata._MODULES[idata.GREEK], 'urls', _file_urls([str(raw)]))
    monkeypatch.setitem(idata._MODULES[idata.GREEK], 'min_words', 1)
    monkeypatch.setattr(idata, '_migrated', set())
    idata.download_and_build(idata.GREEK)
    assert not idata.needs_rebuild(idata.GREEK)
    john = idata.chapter_variants(idata.GREEK, 'John', 1)
    assert john[0].variant.startswith('υἱός') and john[0].note.startswith('v ')
    matt = idata.load_chapter_full(idata.GREEK, 'Matthew', 1)
    assert [(w.surface, w.in_stream) for w in matt] == [('Βίβλος', True), ('ὁ', False)]
    assert [w.surface for w in idata.load_chapter(idata.GREEK, 'Matthew', 1)] == ['Βίβλος']


# ── Qere / Ketiv ─────────────────────────────────────────────────────────────
# Real TAHOT rows. Joshua 2:13 reads "sisters" (Qere) over the written
# "sister"; Nehemiah 2:13 carries two variants, the Ketiv second.
HEB_ROW_QERE_REAL = (
    "Jos.2.13#09=Q(K)\tאַחְיוֹתַ֔/י\t'a.cho.ta/i\tsisters/ my\t{H0269}/H9020\t"
    "HNcfpc/Sp1bs\tK= 'a.cho.ta/i (אַחוֹתַ/י) \"sister/ my\" "
    "(H0269/H9020=HNcfsc/Sp1bs)\tL= אַחְוֹתַ֔/י ¦ ;\tH0269\t\t\t"
    "{H0269=אָחוֹת=sister}/H9020=Ps1c=my\t\t\t\t\t")
HEB_ROW_TWO_VARIANTS = (
    "Neh.2.13#17=Q(K)\tהֵ֣ם\\׀/ /פְּרוּצִ֔ים\them/ /fe.ru.tzim\tthey/ /[were] "
    "broken down\t{H1992}\\H9015/ /{H6555}\tHPp3mp//Vqsmpa\tB= he/m.fe.ru.tzim "
    "(הֵ֣/מפְּרוּצִ֔ים) \"<the>/ [had been] broken down\" (H9009/{H6555}=HTd/Pp3mp)"
    " ¦ K= ha/me.for.va.tzim (הַ/מְפֹרוָצִים) \"<the>/ [had been] broken down\" "
    "(H9009/H6555=HTd/Pp3mp)\tL= הֵ֣מ\\׀//פְּרוּצִ֔ים\tH1992, H6555\t\t\t"
    "{H1992=הֵ֫מָּה=they(masc.)}\\H9015=׀=separate/ /{H6555=פָּרַץ=to break through}"
    "\t\t\t\t\t")


def test_a_hebrew_row_keeps_its_variants_column():
    row = idata.parse_line_hebrew(HEB_ROW_QERE_REAL)
    assert row is not None
    assert row.variant.startswith("K= 'a.cho.ta/i (אַחוֹתַ/י)")
    assert row.note == ''


def test_hebrew_variant_entries_are_parsed():
    assert idata.parse_hebrew_variants(
        "K= 'a.cho.ta/i (אַחוֹתַ/י) \"sister/ my\" (H0269/H9020=HNcfsc/Sp1bs)"
    ) == [idata.HebrewReading('K', 'אַחוֹתַי', "'a.cho.tai", 'sister my')]
    two = idata.parse_hebrew_variants(
        idata.parse_line_hebrew(HEB_ROW_TWO_VARIANTS).variant)
    assert [r.source for r in two] == ['B', 'K']
    assert two[1] == idata.HebrewReading(
        'K', 'הַמְפֹרוָצִים', 'hame.for.va.tzim', '<the> [had been] broken down')
    assert idata.parse_hebrew_variants('') == []
    assert idata.parse_hebrew_variants('garbage') == []


def test_the_ketiv_is_read_off_a_qere_word():
    w = idata.Word(13, 9, 'אַחְיוֹתַי', "'a.cho.tai", 'sisters my', 'H269', 'H269',
                   'HNcfpc/Sp1bs', 'אָחוֹת', 'sister', True, 'Q(K)', '',
                   "K= 'a.cho.ta/i (אַחוֹתַ/י) \"sister/ my\" (H0269/H9020=HNcfsc/Sp1bs)")
    k = idata.ketiv(w)
    assert k is not None
    assert (k.written, k.gloss, k.minor) == ('אַחוֹתַי', 'sister my', False)
    assert idata.ketiv_note(w, k) == (
        'Written (Ketiv) אַחוֹתַי “sister my”; read (Qere) אַחְיוֹתַי “sisters my”.')


def test_a_minor_ketiv_is_marked_and_a_plain_word_has_none():
    minor = idata.Word(3, 8, 'וְלוֹ', 've.Lo', 'and to him', 'H3808', '', 'HC/R/Sp3ms',
                       '', '', True, 'Q(k)', '',
                       'K= ve.lo (וְלֹא) "and not" (H9002/H3808=HC/Tn)')
    k = idata.ketiv(minor)
    assert k is not None and k.minor and k.written == 'וְלֹא'
    plain = idata.Word(1, 1, 'בְּרֵאשִׁית', '', 'in beginning', 'H7225', '', '', '', '',
                       True, 'L', '', '')
    assert idata.ketiv(plain) is None
    # A Qere whose Ketiv differs only in spelling carries no K entry.
    assert idata.ketiv(plain._replace(wtype='Q(K)')) is None


def test_an_old_hebrew_database_gains_the_column_and_asks_for_a_rebuild(
        tmp_path, monkeypatch):
    db = tmp_path / 'hebrew.sqlite'
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE words (
        book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
        pos INTEGER NOT NULL, wtype TEXT NOT NULL, in_stream INTEGER NOT NULL,
        surface TEXT NOT NULL, translit TEXT NOT NULL, gloss TEXT NOT NULL,
        strongs TEXT NOT NULL, strongs_all TEXT NOT NULL,
        strongs_ext TEXT NOT NULL, morph TEXT NOT NULL, lemma TEXT NOT NULL,
        lemma_gloss TEXT NOT NULL, editions TEXT NOT NULL,
        PRIMARY KEY (book, chapter, verse, pos)) WITHOUT ROWID''')
    conn.execute('INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 ('Joshua', 2, 13, 9, 'Q(K)', 1, 'אַחְיוֹתַי', "'a.cho.tai",
                  'sisters my', 'H269', 'H269', '{H0269}/H9020', 'HNcfpc/Sp1bs',
                  'אָחוֹת', 'sister', ''))
    conn.commit()
    conn.close()
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW, str(db))
    monkeypatch.setattr(idata, '_migrated', set())
    assert idata.needs_rebuild(idata.HEBREW)
    words = idata.load_chapter_full(idata.HEBREW, 'Joshua', 2)
    assert words[0].wtype == 'Q(K)' and words[0].variant == ''
    assert idata.ketiv(words[0]) is None
    assert idata.needs_rebuild(idata.HEBREW)


def test_a_fresh_hebrew_build_carries_the_ketiv(tmp_path, monkeypatch):
    raw = tmp_path / 'tahot.txt'
    raw.write_text('\n'.join([HEB_ROW_PREFIXED, HEB_ROW_QERE_REAL]) + '\n',
                   encoding='utf-8')
    monkeypatch.setitem(idata._DB_FILES, idata.HEBREW,
                        str(tmp_path / 'hebrew.sqlite'))
    monkeypatch.setitem(idata._MODULES[idata.HEBREW], 'urls', _file_urls([str(raw)]))
    monkeypatch.setitem(idata._MODULES[idata.HEBREW], 'min_words', 1)
    monkeypatch.setattr(idata, '_migrated', set())
    idata.download_and_build(idata.HEBREW)
    assert not idata.needs_rebuild(idata.HEBREW)
    josh = idata.load_chapter_full(idata.HEBREW, 'Joshua', 2)
    assert idata.ketiv(josh[0]).written == 'אַחוֹתַי'
