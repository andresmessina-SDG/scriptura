"""Tests for import_rand1890.py — the scan repairs and headword rules that
turn the 1890 *Diccionario de la Santa Biblia* into curated entries. Loaded by
path because the tool lives under tools/, off the test import path."""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    'import_rand1890',
    os.path.join(os.path.dirname(__file__), '..', 'tools',
                 'import_rand1890.py'))
assert _SPEC is not None and _SPEC.loader is not None  # by-path load must resolve
imp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(imp)


# ── Repairing the scan ──────────────────────────────────────────────────────


def test_the_printers_hyphen_is_rejoined():
    assert 'prepucio' in imp.repair('se  cortaba  el  pre¬\npucio.')


def test_a_running_head_becomes_a_break_not_text():
    """A page header sits alone above the page — "FE" over the page about the
    Pharisees. Left in, it becomes an entry for `fe` holding somebody else's
    article."""
    out = imp.repair('DICCIONARIO DE LA BIBLIA.\nFE\ntexto')
    assert 'DICCIONARIO' not in out


def test_verse_references_lose_their_floating_punctuation():
    assert 'Juan 1:17' in imp.repair('Juan  1 : 17')


def test_the_printers_spaced_ellipsis_becomes_one_character():
    assert '....' not in imp.repair('uno que derrama ó vierte .... las')


# ── Finding headwords ───────────────────────────────────────────────────────


def _entries(text, tmp_path):
    p = tmp_path / 'scan.txt'
    p.write_text(text, encoding='utf-8')
    return imp.parse(str(p))


def test_an_entry_opening_on_a_capital_is_still_an_entry(tmp_path):
    """The guard used to demand lowercase after the headword, which silently
    dropped DIOS, PACTO, CARNE and PALABRA — a third of the book."""
    e = _entries('DIOS. Este nombre, cuya derivación es incierta, se lo damos.',
                 tmp_path)
    assert 'DIOS' in e and e['DIOS'].startswith('Este nombre')


def test_a_bare_capitalised_line_is_not_a_headword(tmp_path):
    e = _entries('FE\n\nFARISEOS, célebres rabinos de la generación anterior.',
                 tmp_path)
    assert 'FE' not in e and 'FARISEOS' in e


def test_a_numbered_sub_sense_does_not_become_its_own_entry(tmp_path):
    e = _entries('III. Ciudad en las montañas de Judá, sin identificar.',
                 tmp_path)
    assert 'III' not in e


# ── Which keys a headword becomes ───────────────────────────────────────────


def test_two_names_for_one_thing_become_two_keys():
    assert imp.keys_for('VERBO ó PALABRA') == ['VERBO', 'PALABRA']


def test_the_printers_spaced_hyphens_make_one_word():
    assert imp.keys_for('ABEL - BETH - MAACA') == ['ABEL-BETH-MAACA']


def test_a_descriptive_phrase_is_dropped():
    """No double-click can select "Cena del Señor", and giving the article to
    its first word would hand `cabeza` the entry on Cabeza de Baal."""
    assert imp.keys_for('CENA DEL SEÑOR') == []
    assert imp.keys_for('CABEZA DE BAAL') == []


# ── Where a definition stops ────────────────────────────────────────────────


def test_a_citation_does_not_end_the_lead():
    body = ('En la Biblia esta palabra tiene el de género humano, como raza, '
            'Gén. 6:12; Salm. 145:21; el de todas las criaturas vivientes de '
            'la tierra, Gén. 6:17. Otra cosa.')
    out = imp.lead(body)
    assert not out.endswith('Salm.') and not out.endswith('Gén.')


def test_the_lead_reaches_past_an_opening_etymology():
    """These entries open on a gloss before they define anything.
    Circuncisión's first sentence is the surgery; the second is the point."""
    body = ('una incisión al rededor, porque en este rito se cortaba el '
            'prepucio. Era signo de consagración á Dios, y de purificación. '
            'Dios mandó á Abraham que usara la circuncisión.')
    assert 'consagración' in imp.lead(body)


def test_a_runaway_sentence_is_cut_on_a_word_and_says_so():
    body = 'palabra ' * 200
    out = imp.lead(body)
    assert out.endswith(imp.ELLIPSIS) and 'palabr…' not in out


def test_headword_case_follows_scriptures_own_usage():
    caps = {imp._strip_accents('moisés')}
    assert imp.headword_case('MOISÉS', caps) == 'Moisés'
    assert imp.headword_case('GRACIA', caps) == 'gracia'


# ── 1909 spellings reaching 1890 articles ───────────────────────────────────


def test_the_two_spellings_of_a_name_fold_together():
    """Nineteen years and one orthographic reform apart, the Reina-Valera and
    the Rand write the same names differently."""
    for nineteen_o_nine, eighteen_ninety in (('Ephraim', 'Efraím'),
                                             ('Josaphat', 'Josafat'),
                                             ('Jerusalén', 'Jerusalem'),
                                             ('Esther', 'Ester')):
        assert imp.spelling_key(nineteen_o_nine) == \
            imp.spelling_key(eighteen_ninety), nineteen_o_nine


def test_an_alias_reaches_the_article_the_1890_headword_holds():
    """`Abraham` occurs 249 times in the Reina-Valera and the Rand files its
    article under ABRAM — which the article itself says: "llamado después
    Abraham". Without the alias the reader's double-click reached Wiktionary's
    "Nombre de pila de varón"."""
    kept = {'Abram': 'sumo padre, llamado después Abraham.'}
    out = imp.bible_aliases(kept, ['abraham'], {})
    assert out == {'Abraham': kept['Abram']}


def test_two_different_men_are_not_folded_into_one():
    """`issach` and `Isaac` reduce to the same letters, and answering a click
    on one with the article about the other is the failure this whole layer
    exists to avoid. The guard is the opening letters and the length."""
    assert imp.bible_aliases({'Isaac': 'el hijo de Abraham.'},
                             ['issach'], {}) == {}


def test_a_common_noun_keeps_its_own_meaning():
    """Only words Scripture writes capitalised are aliased. `caña` is a reed
    long before it is a place, and a fold that took it would answer a question
    the reader did not ask."""
    assert imp.bible_aliases({'Caná': 'aldea de Galilea.'}, [], {}) == {}


def test_a_spelling_that_folds_onto_two_articles_is_dropped():
    """There is no evidence here for choosing between them."""
    kept = {'Anna': 'la profetisa.', 'Ana': 'la madre de Samuel.'}
    assert imp.bible_aliases(kept, ['aná'], {}) == {}


def test_an_accented_capital_is_not_read_as_a_word_of_its_own():
    """The scan splits the accent off the end of a headword — JUDÁ arrives as
    "JUD A" — and a headword with a space in it is a phrase, which `keys_for`
    drops. That lost the article on Judah, 826 occurrences."""
    assert imp.repair('JUD  A,  celebre , es lo mismo') \
        .startswith('JUDA,')


def test_a_connector_inside_a_headword_still_survives():
    """The rejoin must not eat "EPÍSTOLA Á LOS" — a connector is followed by
    more of the headword, never by the comma that ends it."""
    assert imp.repair('FILIPENSES, EPÍSTOLA Á LOS. En ésta elogia') \
        .startswith('FILIPENSES, EPÍSTOLA Á LOS.')


def test_an_etymology_that_already_stopped_is_not_stopped_twice():
    """Judá's article closes its etymology on a period before the numbered
    senses begin, and the sub-sense break added another: "nombre.. El"."""
    body = 'celebre, es lo mismo que Judas. Véase este nombre. I. El cuarto hijo'
    assert '..' not in imp.open_subsense(body)


def test_the_printers_other_abbreviations_do_not_end_a_lead():
    """`Jue.` ended 41 leads on a bare book name with the chapter and verse
    cut off. The set had `jueces` but not the short form the printer uses."""
    for citation in ('Jue', 'Efes', 'Cró', 'Esdr', 'Eccl', 'comp'):
        assert not imp._ends_sentence(f'y le auxilió allí, {citation}.'), citation


def test_a_quoted_verse_alone_is_not_the_definition():
    """`amor` opens on 1 John 4:16 and then says what the word means. Falling
    back to the last clean sentence end returned the quote by itself."""
    body = ('“Dios es amor, y el que vive en amor vive en Dios, y Dios en '
            'él,” 1 Juan 4:16. El amor es el atributo principal de Jehová, '
            'cuya longitud, anchura, altura y profundidad están fuera de '
            'nuestra comprensión, porque son infinitas, Efes. 3:18.')
    assert 'atributo principal' in imp.lead(body)


def test_the_two_misreads_the_lexicon_check_found():
    """Every word of the curated layer was checked against the module's own
    million keys. These two were all it found — and `tina` is a real word,
    so it is only corrected where an article belongs."""
    assert 'padre de una multitud' in imp.repair('padre de tina multitud')
    assert imp.repair('el agua qne corre') == 'el agua que corre'
    assert 'una tina de agua' in imp.repair('una tina de agua')
