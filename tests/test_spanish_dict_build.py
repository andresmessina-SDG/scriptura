"""Tests for build_spanish_dict.py's curation rules — the closed-class
stoplist, the sense filters, and the hand-curated override layer. Loaded by
path because the build tool lives under tools/, off the test import path."""

import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'build_spanish_dict',
    os.path.join(os.path.dirname(__file__), '..', 'tools',
                 'build_spanish_dict.py'))
assert _SPEC is not None and _SPEC.loader is not None  # by-path load must resolve
bsd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bsd)


def _rec(word, glosses, pos='noun', **sense_extra):
    return {'word': word, 'pos': pos, 'pos_title': 'Sustantivo',
            'senses': [dict({'glosses': [g]}, **sense_extra) for g in glosses]}


# ── Sense filters ───────────────────────────────────────────────────────────


def test_a_sense_that_cites_a_numbered_sibling_is_dropped():
    """"conformidad con la justicia₁" points at a numbered list the peek does
    not show, so alone it defines the word as itself."""
    out = bsd.render_record(
        _rec('justicia', ['Por extensión, conformidad con la justicia₁.',
                          'Cualidad moral que impulsa a dar a cada cual.']), {})
    assert 'justicia₁' not in out
    assert 'Cualidad moral' in out


def test_coarse_senses_are_dropped():
    rec = _rec('x', ['Sentido corriente.'])
    rec['senses'].append({'glosses': ['Sentido grosero.'], 'tags': ['vulgar']})
    out = bsd.render_record(rec, {})
    assert 'corriente' in out and 'grosero' not in out


def test_senses_are_capped_at_three():
    out = bsd.render_record(
        _rec('x', [f'Sentido {n}.' for n in range(1, 7)]), {})
    assert 'Sentido 3.' in out and 'Sentido 4.' not in out


def test_the_cap_counts_kept_senses_not_source_senses():
    """Filtering used to happen after the slice, so three dropped senses at
    the top left an entry with nothing in it."""
    glosses = ['Cita la acepción x₁.'] * 3 + ['Sentido real.']
    out = bsd.render_record(_rec('x', glosses), {})
    assert 'Sentido real.' in out


def test_a_gloss_does_not_end_on_two_full_stops():
    assert bsd._clean('Se pospone a la primera palabra..') == \
        'Se pospone a la primera palabra.'


# ── The closed-class stoplist ───────────────────────────────────────────────


def test_function_words_get_no_entry(tmp_path):
    src = tmp_path / 'in.jsonl'
    src.write_text(
        '\n'.join(__import__('json').dumps(r) for r in [
            _rec('pues', ['Partícula que sirve en la oración de nota de.'],
                 pos='conj'),
            _rec('gracia', ['Predisposición a favorecer a alguien.']),
        ]), encoding='utf-8')
    entries = bsd.build_entries(str(src), {})
    assert 'GRACIA' in entries
    assert 'PUES' not in entries


def test_no_de_accented_alias_lands_on_a_stopword(tmp_path):
    """`más` de-accents to `mas`, which the Reina-Valera uses on nearly every
    page to mean "but". Aliasing would answer it with "more"."""
    entries = {'MÁS': {'más': ['<b>Adverbio</b>Mayor cantidad.']}}
    out = tmp_path / 'x.imp'
    count, aliases = bsd.write_imp(entries, str(out))
    body = out.read_text(encoding='utf-8')
    assert '$$$MÁS' in body
    assert '$$$MAS' not in body and aliases == 0


def test_de_accented_aliases_still_made_for_ordinary_words(tmp_path):
    """The stoplist must not switch aliasing off in general: the RV1909
    writes `carcel` where the dictionary has `cárcel`."""
    entries = {'CÁRCEL': {'cárcel': ['<b>Sustantivo</b>Prisión.']}}
    out = tmp_path / 'x.imp'
    _count, aliases = bsd.write_imp(entries, str(out))
    assert aliases == 1
    assert '$$$CARCEL' in out.read_text(encoding='utf-8')


# ── The curated override layer ──────────────────────────────────────────────


def _write(tmp_path, text):
    p = tmp_path / 'ov.toml'
    p.write_text(text, encoding='utf-8')
    return str(p)


def test_an_override_without_a_source_fails_the_build(tmp_path):
    """A Bible dictionary is a doctrinal document; an entry nobody can trace
    is one nobody can ship."""
    path = _write(tmp_path, '[fe]\nsenses = ["La convicción de lo que no se ve."]\n')
    with pytest.raises(SystemExit, match='source'):
        bsd.read_overrides(path)


def test_an_override_without_senses_fails_the_build(tmp_path):
    path = _write(tmp_path, '[fe]\nsenses = []\nsource = "X"\n')
    with pytest.raises(SystemExit, match='senses'):
        bsd.read_overrides(path)


def test_an_override_renders_like_any_other_entry(tmp_path):
    path = _write(tmp_path, '[fe]\npos = "Sustantivo femenino"\n'
                            'senses = ["Primera.", "Segunda."]\n'
                            'source = "Obra, 1900, dominio público"\n')
    body = bsd.read_overrides(path)['fe']
    assert body.startswith('<b>Sustantivo femenino</b>')
    assert '1. Primera.' in body and '2. Segunda.' in body


def test_a_single_sense_override_is_not_numbered(tmp_path):
    path = _write(tmp_path, '[fe]\nsenses = ["Sólo una."]\nsource = "X"\n')
    assert '1.' not in bsd.read_overrides(path)['fe']


def test_no_overrides_file_is_not_an_error():
    assert bsd.read_overrides(None) == {}


# ── Which spelling leads ────────────────────────────────────────────────────


def test_a_name_scripture_capitalises_leads_with_its_proper_noun():
    """`moisés` led with "Cuna portátil hecha con mimbre" — a wicker carrycot
    — in a Bible that writes Moisés 758 times mid-sentence and moisés none."""
    spellings = {'moisés': ['<b>Sustantivo</b>Cuna portátil de mimbre.'],
                 'Moisés': ['<b>Sustantivo propio</b>Profeta hebreo.']}
    out = bsd.render_entry(spellings, prefers_capital={'moisés'})
    assert out.index('Profeta hebreo') < out.index('mimbre')


def test_an_ordinary_word_still_leads_with_its_common_noun():
    spellings = {'hombre': ['<b>Sustantivo</b>Individuo de la especie.'],
                 'Hombre': ['<b>Sustantivo propio</b>Apellido.']}
    out = bsd.render_entry(spellings, prefers_capital={'moisés'})
    assert out.index('Individuo') < out.index('Apellido')


def test_both_spellings_stay_labelled_either_way():
    """The peek's title shows what was clicked and cannot tell the two apart,
    so each block keeps its own spelling."""
    spellings = {'dios': ['<b>Sustantivo</b>Entidad sobrenatural.'],
                 'Dios': ['<b>Sustantivo propio</b>El Ser Supremo.']}
    out = bsd.render_entry(spellings, prefers_capital={'dios'})
    assert 'dios · ' in out and 'Dios · ' in out


def test_a_single_spelling_needs_no_label():
    out = bsd.render_entry({'gracia': ['<b>Sustantivo</b>Favor.']})
    assert '·' not in out


def test_an_override_carrying_a_label_says_where_it_came_from(tmp_path):
    """A reader meeting "fué" and "Jesu-Cristo" deserves to know they are
    reading 1890, not a modern gloss that has aged badly."""
    path = _write(tmp_path, '[gracia]\nsenses = ["Favor inmerecido."]\n'
                            'label = "Diccionario de la Santa Biblia, 1890"\n'
                            'source = "Rand 1890, dominio público"\n')
    body = bsd.read_overrides(path)['gracia']
    assert body.endswith('<i>Diccionario de la Santa Biblia, 1890</i>')


def test_an_override_without_a_label_gets_no_trailing_line(tmp_path):
    path = _write(tmp_path, '[gracia]\nsenses = ["Favor."]\nsource = "X"\n')
    assert '<i>' not in bsd.read_overrides(path)['gracia']


# ── What an override replaces, and what it must not ─────────────────────────


def test_an_override_replaces_the_general_definition():
    """The surgical account of `circuncisión` is exactly what the curated
    entry exists to displace."""
    entries = {'CIRCUNCISIÓN': {'circuncisión':
                                ['<b>Sustantivo femenino</b>Operación de cirugía.']}}
    entries['CIRCUNCISIÓN'] = {'circuncisión': ['<b>curada</b>Signo del pacto.']
                               + [b for b in entries['CIRCUNCISIÓN']['circuncisión']
                                  if b.startswith(bsd._FORM_BLOCK)]}
    body = bsd.render_entry(entries['CIRCUNCISIÓN'])
    assert 'cirugía' not in body and 'Signo del pacto' in body


def test_a_form_block_is_recognised_by_its_title():
    assert '<b>Forma verbal</b>x'.startswith(bsd._FORM_BLOCK)
    assert '<b>Forma adjetiva y de participio</b>x'.startswith(bsd._FORM_BLOCK)
    assert not '<b>Sustantivo masculino</b>x'.startswith(bsd._FORM_BLOCK)


def test_an_inflection_survives_under_a_curated_entry():
    """`vino` is wine in the 1890 dictionary and "he came" on 682 lines of the
    Reina-Valera. Dropping the inflection answers a question nobody asked."""
    wiki = ['<b>Sustantivo masculino</b>Bebida alcohólica de uva.',
            '<b>Forma verbal</b><b>venir</b>: Trasladarse de allá para acá.']
    kept = [b for b in wiki if b.startswith(bsd._FORM_BLOCK)]
    body = bsd.render_entry({'vino': ['<b>curada</b>El vino de la Escritura.']
                             + kept})
    assert 'venir' in body and 'Bebida alcohólica' not in body


def test_an_interjection_yields_to_the_reading_the_sentence_means():
    """Wiktionary lists the interjection first, which put "Expresa asombro,
    sorpresa o extrañeza" above the plural of `cielo` on the second word of
    Genesis 1:1. 369 keys led with one, `oye`, `venga` and `salve` among
    them."""
    blocks = ['<b>Interjección</b><br />Expresa asombro.',
              '<b>Forma sustantiva masculina</b><br />cielo: parte del cielo.']
    assert bsd._reading_order(blocks)[0].startswith(
        '<b>Forma sustantiva masculina')


def test_a_word_that_is_only_an_interjection_keeps_it():
    """`oh`, `ah`, `ea` have no other reading, and an interjection is exactly
    what Scripture means by them."""
    blocks = ['<b>Interjección</b><br />Expresa asombro.']
    assert bsd._reading_order(blocks) == blocks


def test_a_curated_entry_keeps_the_lead_it_was_given():
    """It carries no part-of-speech label, and the sort must not read that as
    a reason to move it."""
    blocks = ['El Dios eterno, creador de todas las cosas.',
              '<b>Interjección</b><br />Expresa asombro.']
    assert bsd._reading_order(blocks) == blocks
