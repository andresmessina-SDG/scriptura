"""The es/ru names of Bible places, and the rules that chose them.

His decisions 2026-09-29: a place carries the name the reader's Bible gives
it — the Reina-Valera 1909's spelling, the Synodal's in the nominative — and
the modern site's Wikidata label where it has one; anything uncertain goes to
a review list and the app keeps the English.
"""

import importlib.util
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'place_names')


def _tool():
    spec = importlib.util.spec_from_file_location(
        'build_place_names', os.path.join(ROOT, 'tools', 'build_place_names.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(lang):
    with open(os.path.join(DATA, f'{lang}.tsv'), encoding='utf-8') as f:
        return [line.rstrip('\n').split('\t') for line in f if not line.startswith('#')]


# ── The shipped data ────────────────────────────────────────────────────────

@pytest.mark.parametrize('lang, script', [
    ('es', r"^[A-ZÁÉÍÓÚÑÂÊÎÔÛ][\w\-’ ]*$"),
    ('ru', r'^[А-ЯЁ][А-Яа-яЁё\- ]*$'),
])
def test_every_bible_name_is_clean(lang, script):
    tool = _tool()
    bad = []
    seen = set()
    for row in _rows(lang):
        pid, bible, modern = row
        edges = bible.split()[:1] + bible.split()[-1:]
        if (len(row) != 3 or not re.fullmatch(r'a[0-9a-f]{6}', pid) or pid in seen
                or not (bible or modern)
                or (bible and not re.match(script, bible))
                or (lang == 'es' and any(w.lower() in tool.ES_STOP for w in edges))):
            bad.append(row)
        seen.add(pid)
    assert not bad, bad[:5]


@pytest.mark.parametrize('lang, place, want', [
    ('es', 'a112427', 'Beth-lehem'),        # the RV1909's own spelling
    ('ru', 'a112427', 'Вифлеем'),
    ('es', 'a6057f5', 'Puerta del Pescado'),
    ('ru', 'af301ca', 'Египет'),            # not «Египт», from «Египта»
    ('ru', 'a1fe6e7', 'Афины'),             # a plural name
])
def test_known_places(lang, place, want):
    rows = {r[0]: r for r in _rows(lang)}
    assert rows[place][1] == want


def test_the_files_name_their_sources():
    for lang in ('es', 'ru'):
        with open(os.path.join(DATA, f'{lang}.tsv'), encoding='utf-8') as f:
            head = ''.join(line for line in f if line.startswith('#'))
        assert 'Public Domain' in head and 'OpenBible' in head and 'Wikidata' in head


# ── Which Hebrew or Greek word is the name ──────────────────────────────────

def test_a_gloss_names_the_place_not_its_people():
    tool = _tool()
    assert tool.matches('Salt', 'Salt( Sea)')
    assert tool.matches('Bethlehem', 'Beth-lehem')
    assert tool.matches('Jabesh-gilead', 'Jabesh')
    assert not tool.matches('Jebus', 'Jebusite')


def test_ugnt_five_digit_numbers_are_read():
    tool = _tool()
    assert tool.strong_key('G45160') == 'G4516'
    assert tool.strong_key('H01035') == 'H1035'


# ── Spanish ─────────────────────────────────────────────────────────────────

def test_the_tag_keeps_only_the_name():
    """The RV1909 tags the words around a name with it: «estaban en Aroer»,
    «Desde Havila» at a sentence's start."""
    tool = _tool()
    items = tool.rv1909_items('\\w Desde Havila|strong="H2341"\\w*')
    assert tool.spanish_in_verse(items, {'H2341'}, {}) == ('Havila', True)
    items = tool.rv1909_items('\\w y|strong="H9999"\\w* \\w estaban en Aroer|strong="H6177"\\w*')
    assert tool.spanish_in_verse(items, {'H6177'}, {}) == ('Aroer', True)


def test_a_name_of_several_words_spans_its_tags():
    tool = _tool()
    items = tool.rv1909_items('\\w edificaron|strong="H1129"\\w* \\w la puerta|strong="H8179"\\w* '
                              '\\w del Pescado|strong="H1709"\\w*')
    assert tool.spanish_in_verse(items, {'H8179', 'H1709'}, {'H8179': {'puerta'}}) == \
        ('puerta del Pescado', True)


def test_a_common_word_is_not_a_name():
    tool = _tool()
    items = tool.rv1909_items('\\w y|strong="H9999"\\w* \\w el bosque|strong="H3293"\\w*')
    assert tool.spanish_in_verse(items, {'H3293'}, {'H3293': {'bosque'}}) == ('bosque', False)


# ── Russian ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('word, english, names, own, want', [
    # the nominative printed in its own verses
    ('Сихема', 'Shechem', {'сихем'}, {'сихема', 'сихем'}, ('сихем', True)),
    # never printed, but only a masculine takes -ом
    ('Мигдола', 'Migdol', {'мигдолом'}, {'мигдола'}, ('мигдол', True)),
    # the text's «Рам» is another word; «Рамою» shows the feminine
    ('Раме', 'Ramah', {'рам', 'рама', 'рамою'}, {'раме'}, ('рама', True)),
    # -а alone: a masculine genitive, unprinted nominative → review
    ('Лаккума', 'Lakkum', set(), {'лаккума'}, ('лаккум', False)),
    # an ending the English also has is the name's own
    ('Рекем', 'Rekem', {'рекем'}, {'рекем'}, ('рекем', True)),
    ('Сеном', 'Shen', {'сен'}, {'сеном'}, ('сен', True)),
    ('Хали', 'Hali', {'хали'}, {'хали'}, ('хали', True)),
    # a vowel that drops out of the other forms, and a plural
    ('Египта', 'Egypt', {'египет', 'египтом'}, {'египта'}, ('египет', True)),
    ('Афинах', 'Athens', {'афины'}, {'афинах'}, ('афины', True)),
    ('Вифании', 'Bethany', {'вифания'}, {'вифании'}, ('вифания', True)),
    # a word made from the name is not it
    ('Елласарский', 'Ellasar', {'елласар'}, set(), (None, False)),
])
def test_russian_nominative(word, english, names, own, want):
    assert _tool().name_nominative(word, names, own, english) == want


def test_a_russian_name_is_found_near_its_guide():
    tool = _tool()
    tokens = tool.synodal_tokens('И пошел один человек из Вифлеема Иудейского')
    assert tool.russian_in_verse(tokens, [['Вифлеема']]) == ['Вифлеема']
    # «Нетофафянин» is a man from Нетофа, not the town
    tokens = tool.synodal_tokens('Магарай Нетофафянин')
    assert tool.russian_in_verse(tokens, [['Нетофа']]) is None


def test_the_sound_match_holds_names_apart():
    tool = _tool()
    assert tool.sounds_like('Beth-shemesh', 'Вефсамис') >= tool.SOUND
    assert tool.sounds_like('Hazor', 'Асора') >= tool.SOUND
    assert tool.sounds_like('Hadid', 'Оно') < tool.SOUND


# ── Modern names ────────────────────────────────────────────────────────────

def test_a_modern_label_must_be_the_site_openbible_names():
    """An item for the ancient place carries the Bible's name; its label
    would print the ancient name twice."""
    tool = _tool()
    labels = {'Q1': {'en': 'Abel-beth-maachah', 'ru': 'Абель-Бет-Мааха'},
              'Q2': {'en': 'Tel Abel Beth Maacah', 'ru': 'Тель-Авель-Бейт-Мааха'}}
    assert tool.modern_label('Tel Abel Beth Maacah', ['Q1'], labels, 'ru') is None
    assert tool.modern_label('Tel Abel Beth Maacah', ['Q1', 'Q2'], labels, 'ru') == \
        'Тель-Авель-Бейт-Мааха'
