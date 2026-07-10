"""lexicon_data: TBESG/TFLSJ entry parsing, panel-dialect conversion, and
(when the raw files are present locally) a full offline build + lookups."""
import os
import urllib.request

import pytest

import lexicon_data as ldata

# Real rows (STEPBible CC BY 4.0), abridged bodies.
TBESG_ROW = (
    "G0026\tG0026 =\tG0026\tἀγάπη\tagapē\tG:N-F\tlove\t"
    " <b>ἀγάπη</b>, -ης, ἡ <BR /> [in LXX for אַהֲבָה ;] <BR /> "
    "<b>love, goodwill, esteem</b>: <ref='Jhn.13.35'>Jhn.13:35;</ref> "
    "<re><i>SYN.</i>: φιλία.</re> (AS)")
TBESG_MEANING_ROW = (
    "G0032\tG0032H = a Meaning of\tG0032G\tἄγγελος\tangelos\tG:N-M\t"
    "angel: messenger\t <b>ἄγγελος</b>, -ου, ὁ (AS)")
TFLSJ_ROW = (
    'G0026\tG0026 =\tG0026\tἀγάπη\tagapē\tG:N-F\tlove\t'
    '<b> ἀγάπ-η</b>, ἡ, <br /> <b>love,</b> '
    '[<a href="javascript:void(0)" title=" LXX.Jer.2.2, +others">'
    'LXX+2nd c.BC+</a>] <br /><Level2><b>__II</b></Level2> in <i>plural</i>, '
    '<b>love-feast</b>')


def test_parse_entry_basic():
    row = ldata.parse_entry(TBESG_ROW)
    assert row is not None
    strongs, lemma, translit, pos, gloss, entry = row
    assert strongs == 'G26'                 # normalized plain form
    assert lemma == 'ἀγάπη'
    assert translit == 'agapē'
    assert pos == 'G:N-F'
    assert gloss == 'love'
    assert entry.startswith('<b>ἀγάπη</b>')


def test_parse_entry_rejects_non_entries():
    assert ldata.parse_entry('') is None
    assert ldata.parse_entry('TBESG - Translators Brief lexicon') is None
    assert ldata.parse_entry('\t\t\t\t\t\t\t') is None


def test_to_panel_html_br_and_refs():
    out = ldata.to_panel_html(ldata.parse_entry(TBESG_ROW)[5])
    assert '<BR />' not in out and '<br />' not in out
    assert '\n' in out                       # BRs became newlines
    assert 'Jhn.13:35' in out                # ref text kept
    assert '<b>love, goodwill, esteem</b>' in out


def test_to_panel_html_inlines_lsj_citations():
    out = ldata.to_panel_html(ldata.parse_entry(TFLSJ_ROW)[5])
    assert 'javascript' not in out           # anchor gone
    assert 'LXX+2nd c.BC+' in out            # display text kept
    assert '<i>[LXX.Jer.2.2, +others]</i>' in out   # title inlined, italic
    assert 'love-feast' in out


def test_to_panel_html_indents_hierarchy_markers():
    out = ldata.to_panel_html(ldata.parse_entry(TFLSJ_ROW)[5])
    assert '__' not in out                   # markers converted…
    assert ' II' in out                 # …to an em-space indent


# ── Offline end-to-end build ─────────────────────────────────────────────────

_SCRATCH = ('/tmp/scriptura-build/'
            'scratchpad')
_RAW = {'tbesg': f'{_SCRATCH}/tbesg.txt', 'tflsj': f'{_SCRATCH}/tflsj1.txt'}


@pytest.mark.skipif(
    not all(os.path.exists(p) for p in _RAW.values()),
    reason='raw lexicon files not downloaded locally')
def test_full_build_and_lookups(tmp_path, monkeypatch):
    monkeypatch.setattr(ldata, '_DB_FILE', str(tmp_path / 'lex.sqlite'))
    monkeypatch.setattr(ldata, '_URLS', {
        k: 'file://' + urllib.request.pathname2url(p)
        for k, p in _RAW.items()})

    ldata.download_and_build()
    assert ldata.is_installed()

    brief = ldata.lookup_brief('G26')
    assert brief is not None
    assert 'ἀγάπη' in brief
    # Reading-pane clicks pass the raw zero-padded module form.
    assert ldata.lookup_brief('G0026') == brief
    assert '(AS)' in brief                   # Abbott-Smith attribution
    assert '\n' in brief

    assert ldata.has_lsj('G26')
    lsj = ldata.lookup_lsj('G26')
    assert lsj is not None and 'love' in lsj
    assert 'javascript' not in lsj

    # First-wins on duplicate ids: G32's primary row, not 'a Meaning of'.
    g32 = ldata.lookup_brief('G32')
    assert g32 is not None and 'ἄγγελος' in g32

    # Unknown / out-of-testament keys are quiet.
    assert ldata.lookup_brief('G99999') is None
    assert not ldata.has_lsj('H430')


def test_to_panel_html_isolates_hebrew_runs():
    out = ldata.to_panel_html(ldata.parse_entry(TBESG_ROW)[5])
    # Each Hebrew run wrapped in FSI…PDI so neighbouring punctuation
    # keeps the English text's left-to-right order.
    assert '⁨אַהֲבָה⁩' in out
    assert out.count('⁨') == out.count('⁩')


def test_scripture_refs():
    text = 'idea: Mat.8:8, Luk.7:7, 1Co.14:9, 19 Heb.12:19, al.'
    refs = ldata.scripture_refs(text)
    assert [(r[2], r[3], r[4]) for r in refs] == [
        ('Matthew', 8, 8), ('Luke', 7, 7),
        ('1 Corinthians', 14, 9), ('Hebrews', 12, 19)]
    start, end = refs[0][0], refs[0][1]
    assert text[start:end] == 'Mat.8:8'      # offsets index the text


def test_scripture_refs_kingdoms_and_skips():
    # LXX Kingdoms numbering: 1Ki cites 1 Samuel (31 chapters).
    assert ldata.scripture_refs('1Ki.31:10')[0][2] == '1 Samuel'
    assert ldata.scripture_refs('3Ki.17:21')[0][2] == '1 Kings'
    # Deuterocanon and dual-numbered LXX psalms stay plain.
    assert ldata.scripture_refs('Sir.1:1, Wis.2:12') == []
    assert ldata.scripture_refs('Psa.81(82):6') == []


def test_to_panel_html_restores_hebrew_list_commas():
    # STEPBible writes the comma between two Hebrew words as ' ,' glued
    # to the second word (compensating for fused RTL runs); isolation
    # restores the logical ', '.
    out = ldata.to_panel_html('for מִלָּה ,אֵמֶר, etc.')
    assert '⁩, ⁨' in out
    assert '⁩ ,⁨' not in out
