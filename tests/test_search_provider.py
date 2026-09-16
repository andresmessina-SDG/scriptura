"""The GNOME Shell search provider: what counts as a reference, what the
Shell is sent back, and the install files that point the Shell at it. No
display and no SWORD modules: verse text is stubbed."""
import configparser
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import search_provider as sp

REPO = Path(__file__).resolve().parents[1]
APP_ID = 'io.github.andresmessina_SDG.Scriptura'


def test_a_reference_parses():
    assert sp.parse(['john', '3:16']) == ('John', 3, 16)
    assert sp.parse(['1', 'john', '4']) == ('1 John', 4, None)
    assert sp.parse(['Ps', '23']) == ('Psalms', 23, None)


def test_a_bare_word_is_never_a_reference():
    # The Shell sends every keystroke; "gen" on the way to an app's name
    # must not answer with Genesis.
    assert sp.parse(['gen']) is None
    assert sp.parse(['john']) is None
    assert sp.parse(['a', '1']) is None
    assert sp.parse(['firefox', '2']) is None
    assert sp.parse([]) is None


def test_a_chapter_the_book_lacks_is_no_result():
    assert sp.parse(['john', '22']) is None
    assert sp.parse(['john', '0']) is None


def test_results_need_the_verse_text(monkeypatch):
    monkeypatch.setattr(sp, '_module', lambda: 'KJV')
    monkeypatch.setattr(sp.passage_export, 'verse_text',
                        lambda m, b, c, v: 'For God so loved' if v == [16] else '')
    assert sp.results(['john', '3:16']) == ['John 3:16']
    # A verse past the chapter's end has no text, so no row.
    assert sp.results(['john', '3:99']) == []


def test_no_bible_installed_is_no_result(monkeypatch):
    monkeypatch.setattr(sp.content, 'text_bible_names', lambda: [])
    assert sp.results(['john', '3:16']) == []


def test_the_open_translation_is_used(monkeypatch):
    monkeypatch.setattr(sp.content, 'text_bible_names', lambda: ['KJV', 'WEB'])
    monkeypatch.setattr(sp.settings, 'get', lambda k: 'WEB')
    assert sp._module() == 'WEB'
    monkeypatch.setattr(sp.settings, 'get', lambda k: 'MHC')   # a commentary
    assert sp._module() == 'KJV'


def test_meta_cuts_a_long_passage_at_a_word(monkeypatch):
    monkeypatch.setattr(sp, '_module', lambda: 'KJV')
    monkeypatch.setattr(sp.passage_export, 'verse_text',
                        lambda m, b, c, v: 'word ' * 100)
    row = sp.meta('Psalms 23')
    assert row['id'] == 'Psalms 23'
    assert row['name'] == 'Psalms 23'
    assert row['description'].endswith('word…')
    assert len(row['description']) <= sp._DESCRIPTION_CHARS + 1


def test_the_identifier_opens_through_a_bible_link():
    import main
    ident = sp.identifier(('1 John', 4, 8))
    assert main._parse_bible_uri('bible:1%20John%204:8') == ident


def test_the_ini_names_this_object():
    ini = configparser.ConfigParser()
    ini.read(REPO / 'data' / f'{APP_ID}.search-provider.ini')
    section = ini['Shell Search Provider']
    assert section['DesktopId'] == f'{APP_ID}.desktop'
    assert section['BusName'] == APP_ID
    assert section['ObjectPath'] == sp.OBJECT_PATH
    assert section['Version'] == '2'


def test_the_service_starts_the_app_windowless():
    text = (REPO / 'data' / f'{APP_ID}.service.in').read_text()
    assert f'Name={APP_ID}' in text
    assert re.search(rf'^Exec=@bindir@/{re.escape(APP_ID)} --gapplication-service$',
                     text, re.MULTILINE)
    meson = (REPO / 'data' / 'meson.build').read_text()
    assert "'gnome-shell' / 'search-providers'" in meson
    assert "'dbus-1' / 'services'" in meson
