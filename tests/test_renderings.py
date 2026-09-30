"""The es/ru line under the English Strong's entry, and the data behind it.

His decisions 2026-09-29: a Spanish or Russian reader sees how that
language's Bible renders the word, the Bible named, under the English entry,
which stays. Spanish from the Reina-Valera 1909 (Public Domain), Russian from
the Door43 Russian Literal Open Bible (CC BY-SA 4.0).
"""

import importlib.util
import os

import pytest

import renderings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool():
    spec = importlib.util.spec_from_file_location(
        'build_renderings', os.path.join(ROOT, 'tools', 'build_renderings.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── The shipped data ────────────────────────────────────────────────────────

@pytest.mark.parametrize('strong, lang, want', [
    ('G26', 'es', 'amor'), ('G26', 'ru', 'любовь'),
    ('H430', 'es', 'Dios'), ('H430', 'ru', 'Бог'),
    ('G5485', 'es', 'gracia'), ('G5485', 'ru', 'благодать'),
    # A name the analyser does not know keeps the Bible's spelling; guessing
    # at it cut "Яхве" to "Яхв".
    ('H3068', 'ru', 'Яхве'),
    # A phrase folds with its agreement kept: «верной любви», not
    # "верный любовь".
    ('H2617', 'ru', 'верная любовь'),
])
def test_known_words_render_as_their_bible_does(strong, lang, want):
    assert want in renderings.words(strong, lang)


def test_a_one_word_rendering_is_kept_whole():
    """The Reina-Valera renders the Greek article with an article; stripping
    function words from one-word spans left its rare exception, "él". Russian
    has no article and renders none."""
    assert renderings.words('G3588', 'es')[:2] == ['el', 'la']
    assert renderings.words('G3588', 'ru') == []
    # Capitalised as this translation writes pronouns for God.
    assert 'мой' in [w.lower() for w in renderings.words('G1699', 'ru')]


@pytest.mark.parametrize('lang', ['es', 'ru'])
def test_every_line_is_short_and_clean(lang):
    tool = _tool()
    path = os.path.join(ROOT, 'data', 'renderings', f'{lang}.tsv')
    bad = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#'):
                continue
            key, words = line.rstrip('\n').split('\t')
            found = words.split(' | ')
            edges = [w for r in found if len(r.split()) > 1
                     for w in (r.split()[0], r.split()[-1])
                     if w.lower() in tool.STOP[lang]]
            if not found or len(found) > tool.MOST or '' in found or edges:
                bad.append(line.strip())
    assert not bad, bad[:5]


def test_the_russian_file_carries_its_licence():
    with open(os.path.join(ROOT, 'data', 'renderings', 'ru.tsv'),
              encoding='utf-8') as f:
        head = ''.join(next(f) for _ in range(5))
    assert 'CC BY-SA 4.0' in head and 'ru_rlob' in head


# ── The line ────────────────────────────────────────────────────────────────

def test_the_line_names_the_bible(monkeypatch):
    monkeypatch.setattr(renderings, 'current_language', lambda: 'es')
    assert renderings.line('G0026') == 'Reina-Valera 1909: amor, caridad'


def test_english_readers_get_no_line(monkeypatch):
    monkeypatch.setattr(renderings, 'current_language', lambda: 'en')
    assert renderings.line('G26') is None


def test_keys_are_read_the_way_the_app_writes_them():
    """Module markup zero-pads; the interlinear adds a sense letter."""
    assert renderings.words('G0026', 'es') == renderings.words('G26', 'es')
    assert renderings.words('H430a', 'ru') == renderings.words('H430', 'ru')
    assert renderings.words('nonsense', 'es') == []


# ── The generator's rules ───────────────────────────────────────────────────

def test_ugnt_five_digit_numbers_are_read():
    tool = _tool()
    assert tool.strong_key('G37540') == 'G3754'
    assert tool.strong_key('G00260') == 'G26'
    assert tool.strong_key('strong:H0430') == 'H430'


def test_rv1909_words_and_footnotes():
    tool = _tool()
    usfm = ('\\v 16 \\w Porque|strong="G1063"\\w* \\w amó|strong="G0025"\\w* '
            '\\f + \\ft \\w nota|strong="G9999"\\w*\\f*')
    assert list(tool.parse_rv1909(usfm)) == [('G1063', ['Porque'], True),
                                            ('G25', ['amó'], False)]


def test_nested_alignments_credit_every_word():
    """Two Greek words to one Russian phrase open two alignments first."""
    tool = _tool()
    usfm = ('\\zaln-s |x-strong="G35880"\\*\\zaln-s |x-strong="G54850"\\*'
            '\\w благодати|x-occurrence="1"\\w*\\zaln-e\\*\\zaln-e\\*')
    assert sorted(tool.parse_aligned(usfm)) == [
        ('G3588', ['благодати'], True), ('G5485', ['благодати'], True)]


def test_edges_lose_function_words_not_the_middle():
    tool = _tool()
    es = tool.stop_in('es')
    assert tool.clean(['de', 'tal', 'manera'], es) == 'tal manera'
    assert tool.clean(['á', 'su', 'Hijo'], es) == 'Hijo'
    assert tool.clean(['el'], es) == 'el'
    assert tool.clean(['de', 'el'], es) == ''


def test_a_capital_at_a_sentence_start_says_nothing():
    """«Y» and «Mas» open most of their verses; counted there, the
    conjunctions came out capitalised like names."""
    tool = _tool()
    spans = [('G1161', ['Y'], True)] * 9 + [('G1161', ['y'], False)]
    counts, caps, bare = tool.tally(spans, tool.stop_in('es'))
    assert tool.pick(counts['G1161'], caps['G1161']) == ['y']
    names = [('H3389', ['Jerusalem'], False)] * 3
    counts, caps, bare = tool.tally(names, tool.stop_in('es'))
    assert tool.pick(counts['H3389'], caps['H3389']) == ['Jerusalem']
