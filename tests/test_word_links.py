"""A double-click in a tagged Bible opens the article that verse's word is
about, even where no spelling of it is a dictionary key.

Russian inflects: `спросил` is filed under СПРАШИВАТЬ, and by spelling alone
the Russian Bible dictionary answered 9.6% of John. Door43's word links
name the article per verse and Strong's number; tools/build_russian_tw_dict.py
ships them beside the dictionary's data as `links.tsv.gz`.
"""
import gzip
import types

import gi

gi.require_version('Gtk', '4.0')

import content  # noqa: E402
import sword_bridge  # noqa: E402
import word_links  # noqa: E402
from pane_peek import PeekController  # noqa: E402

DICT = ('RussianBibleWords', 'Библейский словарь')


def _links(monkeypatch, tmp_path, lines):
    with gzip.open(tmp_path / word_links.LINKS_FILE, 'wt',
                   encoding='utf-8') as fh:
        fh.write(''.join('\t'.join(map(str, row)) + '\n' for row in lines))
    monkeypatch.setattr(sword_bridge, 'module_data_path',
                        lambda m: str(tmp_path) if m == DICT[0] else '')
    monkeypatch.setattr(word_links, '_links', {})


def test_a_link_names_the_key_for_the_word_in_its_verse(monkeypatch, tmp_path):
    _links(monkeypatch, tmp_path, [('John', 3, 16, 'G25', 'ЛЮБОВЬ')])
    assert word_links.key_for(DICT[0], 'John', 3, 16, ['G0025']) == 'ЛЮБОВЬ'
    assert word_links.key_for(DICT[0], 'John', 3, 17, ['G25']) is None


def test_two_articles_for_one_word_answer_nothing(monkeypatch, tmp_path):
    """"сотворил" carries H1254 and H853; were both linked to different
    articles, choosing one would be a guess."""
    _links(monkeypatch, tmp_path, [('Genesis', 1, 1, 'H1254', 'ТВОРЕНИЕ'),
                                   ('Genesis', 1, 1, 'H853', 'ЗНАК')])
    assert word_links.key_for(
        DICT[0], 'Genesis', 1, 1, ['H1254', 'H853']) is None
    assert word_links.key_for(
        DICT[0], 'Genesis', 1, 1, ['H1254']) == 'ТВОРЕНИЕ'


def test_a_dictionary_without_links_answers_nothing(monkeypatch, tmp_path):
    _links(monkeypatch, tmp_path, [])
    assert word_links.key_for('Easton', 'John', 3, 16, ['G25']) is None


def _peek(module, book, chapter, verse):
    peek = PeekController(types.SimpleNamespace(
        module=module, book=book, chapter=chapter))
    peek._peek_verse = verse
    return peek


def test_the_peek_opens_the_linked_article(monkeypatch, tmp_path):
    """The spelling finds nothing; the link finds the article, and it counts
    as an exact answer so its tab opens first."""
    _links(monkeypatch, tmp_path, [('John', 18, 21, 'G2065', 'СПРАШИВАТЬ')])
    looked_up = []

    def lookup(mod, word):
        looked_up.append(word)
        return ('<p>спрашивать</p>', True) if word == 'СПРАШИВАТЬ' else (
            '', False)

    monkeypatch.setattr(sword_bridge, 'lookup_dict_entry', lookup)
    monkeypatch.setattr(sword_bridge, 'map_verse_to_app',
                        lambda m, b, c, v: v)
    monkeypatch.setattr(content, 'language_code', lambda m: 'ru')
    results = _peek('RusSynodalLIO', 'John', 18, 21).dict_results(
        'спросил', [DICT], strongs=('G2065',))
    assert [html for _m, _d, html in results] == ['<p>спрашивать</p>']
    assert looked_up == ['СПРАШИВАТЬ']


def test_without_a_tag_the_peek_spells_as_before(monkeypatch, tmp_path):
    _links(monkeypatch, tmp_path, [('John', 18, 21, 'G2065', 'СПРАШИВАТЬ')])
    looked_up = []
    monkeypatch.setattr(sword_bridge, 'lookup_dict_entry',
                        lambda mod, word: looked_up.append(word) or ('', False))
    monkeypatch.setattr(content, 'language_code', lambda m: 'ru')
    _peek('RusSynodal', 'John', 18, 21).dict_results('спросил', [DICT])
    assert looked_up == ['спросил']


def test_the_verse_is_asked_in_app_numbering(monkeypatch, tmp_path):
    """The Synodal Bible numbers some verses its own way; the links are in
    app-space, so the displayed verse goes through map_verse_to_app."""
    _links(monkeypatch, tmp_path, [('Psalms', 3, 1, 'H3068', 'ЯХВЕ')])
    monkeypatch.setattr(sword_bridge, 'map_verse_to_app',
                        lambda m, b, c, v: v - 1)
    monkeypatch.setattr(
        sword_bridge, 'lookup_dict_entry',
        lambda mod, word: ('<p>yhwh</p>', True) if word == 'ЯХВЕ'
        else ('', False))
    monkeypatch.setattr(content, 'language_code', lambda m: 'ru')
    results = _peek('RusSynodalLIO', 'Psalms', 3, 2).dict_results(
        'Господи', [DICT], strongs=('H3068',))
    assert results and results[0][2] == '<p>yhwh</p>'


def test_the_word_under_the_click_gives_its_numbers():
    """What the pane tags each word with (`strg:` per number) is what the
    peek hands the links; a word the text left untagged gives nothing."""
    from gi.repository import Gtk
    buf = Gtk.TextBuffer()
    buf.set_text('Иисус спросил их')
    tag = buf.create_tag('strg:G2065')
    buf.apply_tag(tag, buf.get_iter_at_offset(6), buf.get_iter_at_offset(13))
    peek = PeekController(types.SimpleNamespace(_buffer=buf))
    assert peek._strongs_at_offset(6) == ('G2065',)
    assert peek._strongs_at_offset(0) == ()
