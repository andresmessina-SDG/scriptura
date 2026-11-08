"""The dictionary articles that cite a verse: the index and its door, the
'Dictionaries' set on the cross-reference bar."""
import gi
import pytest

gi.require_version('Gtk', '4.0')

import settings  # noqa: E402
import sword_bridge  # noqa: E402
import verse_articles as va  # noqa: E402


# ── Reading the citations out of an entry ───────────────────────────────────

def test_osis_refs_are_read():
    raw = ('<p>wife of Jether (<ref osisRef="Bible:1Chr.2.16">1 Chr. 2:16</ref>)'
           ' and of Nabal (<ref osisRef="Bible:1Sam.25.3">1 Sam. 25:3</ref>).</p>')
    assert va.cited_verses(raw) == [('1 Chronicles', 2, 16), ('1 Samuel', 25, 3)]


def test_a_bare_continuation_keeps_the_book_before_it():
    # Easton's own markup for Shobal: the bare "52", "4:1", "2" belong to
    # 1 Chronicles, though the module codes them as Genesis.
    raw = ('(<ref osisRef="Bible:1Chr.2.50">1 Chr. 2:50</ref>, '
           '<ref osisRef="Bible:Gen.2.21">52</ref>; '
           '<ref osisRef="Bible:Gen.4.1">4:1</ref>, '
           '<ref osisRef="Bible:Gen.4.2">2</ref>)')
    assert va.cited_verses(raw) == [
        ('1 Chronicles', 2, 50), ('1 Chronicles', 2, 52),
        ('1 Chronicles', 4, 1), ('1 Chronicles', 4, 2)]


def test_thml_passages_are_read():
    raw = ('(<scripRef passage="1sa 25:14">1 Samuel 25:14</scripRef>) and '
           '<scripRef>Ge 4:2; 5:3</scripRef>')
    assert va.cited_verses(raw) == [
        ('1 Samuel', 25, 14), ('Genesis', 4, 2), ('Genesis', 5, 3)]


def test_a_long_range_counts_as_its_first_verse():
    raw = '<ref osisRef="Bible:Ps.119.1-Ps.119.176">Ps. 119</ref>'
    assert va.cited_verses(raw) == [('Psalms', 119, 1)]
    short = '<ref osisRef="Bible:Gen.1.1-Gen.1.3">Gen. 1:1-3</ref>'
    assert va.cited_verses(short) == [
        ('Genesis', 1, 1), ('Genesis', 1, 2), ('Genesis', 1, 3)]


def test_russian_references_move_to_kjv_numbers(monkeypatch):
    # The Russian Bible dictionary cites its own Bible, in Synodal psalm
    # numbers: hyssop is "Ps 50:9", the KJV's Psalm 51:7.
    monkeypatch.setattr(va, '_work_v11n',
                        lambda w: 'SynodalProt' if w == 'RusCARST' else None)
    raw = ('см. <reference osisRef="RusCARST:Ps.50.9">Заб. 50:9</reference>; '
           '<reference osisRef="RusCARSTDICT:СОРО" type="x-glosslink">Соро</reference>'
           ' <reference osisRef="RusCARST:Gen.16">Нач. 16</reference>')
    assert va.cited_verses(raw) == [('Psalms', 51, 7), ('Genesis', 16, 1)]


def test_a_psalm_title_lands_on_verse_one():
    assert va._to_app('SynodalProt', ('Psalms', 23, 1)) == ('Psalms', 24, 1)
    assert va._to_app(None, ('Psalms', 23, 1)) == ('Psalms', 23, 1)


def test_repeats_are_dropped():
    raw = ('<ref osisRef="Bible:John.3.16">John 3:16</ref> '
           '<ref osisRef="Bible:John.3.16">John 3:16</ref>')
    assert va.cited_verses(raw) == [('John', 3, 16)]


# ── The index ────────────────────────────────────────────────────────────────

# (entries that cite, entries walked)
_WALKS = {
    'Easton': ([(('ABIGAIL', 0), [('1 Samuel', 25, 3)]),
                (('CHURL', 0), [('1 Samuel', 25, 3), ('Isaiah', 32, 5)]),
                (('DAVID', 0), [('1 Samuel', 25, 3)] +
                 [('Psalms', 23, v) for v in range(1, 7)])], 3),
    'Smith': ([(('ABEL', 0), [('Genesis', 4, 2)]),
               (('ABEL', 1), [('2 Samuel', 20, 14)])], 2),
    # A general dictionary: one entry in fifty cites a verse.
    'Webster1913': ([(('CHURL', 0), [('1 Samuel', 25, 3)])], 50),
    'FreDAW': ([(('ABIGAÏL', 0), [('1 Samuel', 25, 3)])], 1),
}
_LANGS = {'Easton': 'en', 'Smith': 'en', 'Webster1913': 'en', 'FreDAW': 'fr'}


@pytest.fixture
def fake_index(monkeypatch, tmp_path):
    walked = []

    def walk(name):
        walked.append(name)
        return _WALKS[name]

    monkeypatch.setattr(va, '_walk', walk)
    monkeypatch.setattr(va, '_modules', lambda: list(_WALKS))
    import content
    monkeypatch.setattr(content, 'language_code', lambda n: _LANGS.get(n, ''))
    monkeypatch.setattr(va, '_signature', lambda names: ('sig', tuple(names)))
    monkeypatch.setattr(va.paths, 'cache_dir', lambda: str(tmp_path))
    monkeypatch.setattr(va, '_index', None)
    return walked


EN = ('en', 'en')


def test_narrow_articles_come_first(fake_index):
    assert va.articles_for('1 Samuel', 25, 3, EN) == [
        ('Easton', 'ABIGAIL', 0), ('Easton', 'CHURL', 0), ('Easton', 'DAVID', 0)]


def test_a_general_dictionary_is_left_to_the_word_peek(fake_index):
    va._load()
    assert 'Webster1913' not in va.works(EN)


def test_only_languages_the_reader_reads(fake_index):
    va._load()
    assert va.works(EN) == ['Easton', 'Smith']
    # A French Bible open: its dictionary first, then the interface's.
    assert va.works(('fr', 'en')) == ['FreDAW', 'Easton', 'Smith']
    assert va.articles_for('1 Samuel', 25, 3, ('fr', 'en'))[0] == (
        'FreDAW', 'ABIGAÏL', 0)
    assert va.works(('de', 'de')) == []


def test_asking_which_works_never_builds(fake_index):
    assert va.works(EN) == ['Easton', 'Smith', 'Webster1913']
    assert fake_index == []


def test_repeated_keys_stay_apart(fake_index):
    assert va.articles_for('2 Samuel', 20, 14, EN) == [('Smith', 'ABEL', 1)]


def test_the_index_is_kept_and_reused(fake_index, monkeypatch):
    va.articles_for('Genesis', 4, 2, EN)
    assert fake_index == list(_WALKS)
    monkeypatch.setattr(va, '_index', None)      # a new session
    assert va.articles_for('Genesis', 4, 2, EN) == [('Smith', 'ABEL', 0)]
    assert fake_index == list(_WALKS)            # read from the cache


def test_a_changed_dictionary_rebuilds(fake_index, monkeypatch):
    va.articles_for('Genesis', 4, 2, EN)
    monkeypatch.setattr(va, '_modules', lambda: ['Smith'])
    assert va.articles_for('1 Samuel', 25, 3, EN) == []
    assert fake_index == list(_WALKS) + ['Smith']


# ── On the bar ───────────────────────────────────────────────────────────────

def test_titles_read_as_names():
    t = sword_bridge._article_title
    assert t('ABIGAIL') == 'Abigail'
    assert t('ABEL, STONE OF') == 'Abel, Stone of'
    assert t('ABIGAÏL OU ABIGAL') == 'Abigaïl ou Abigal'
    assert t('Abigail') == 'Abigail'


def test_the_set_offers_articles(monkeypatch, fake_index):
    monkeypatch.setattr(sword_bridge, 'installed_dict_modules',
                        lambda: [('Easton', "Easton's Bible Dictionary"),
                                 ('Smith', "Smith's Bible Dictionary")])
    arts = sword_bridge.get_cross_refs_from('dictionaries', '1 Samuel', 25, 3, EN)
    assert [a.label for a in arts] == [
        "Easton's · Abigail", "Easton's · Churl", "Easton's · David"]
    assert (arts[0].module, arts[0].key, arts[0].nth) == ('Easton', 'ABIGAIL', 0)


def test_no_dictionary_no_set(monkeypatch):
    monkeypatch.setattr(sword_bridge, 'dictionary_works', lambda langs: [])
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: [])
    assert 'dictionaries' not in sword_bridge.crossref_sets()
    assert sword_bridge.get_cross_refs_from('dictionaries', 'John', 3, 16) is None


@pytest.fixture
def panel(monkeypatch):
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds the real panel')
    monkeypatch.setattr(settings, 'put', lambda *a: None)
    from crossref_panel import CrossRefPanel
    p = CrossRefPanel(on_ref_clicked=lambda *a: None, on_close=lambda: None)
    p._place = ('1 Samuel', 25, 3)
    return p


def test_an_article_chip_names_its_dictionary(panel):
    art = sword_bridge.Article('Easton', 'ABIGAIL', 0, "Easton's · Abigail")
    panel._show_lookup((['tsk', 'dictionaries'], 'dictionaries', [art]))
    chip = panel._ref_box.get_first_child()
    assert chip.get_label() == "Easton's · Abigail"
    assert panel._title.get_text() == 'Dictionaries · 1 Samuel 25:3'


def test_a_build_in_progress_does_not_hold_up_the_bar(fake_index):
    # Another thread is building: asking which works count must not wait.
    va._lock.acquire()
    try:
        assert va.works(EN) == ['Easton', 'Smith', 'Webster1913']
    finally:
        va._lock.release()


def test_the_walk_lets_go_of_the_sword_lock(monkeypatch):
    """Webster's takes 5 s to walk; the page must still render meanwhile."""
    released = []

    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def release(self):
            released.append(1)

        def acquire(self):
            pass

    class Mod:
        n = 0

        def setPosition(self, _p):
            pass

        def popError(self):
            return '\x00' if self.n < 4500 else '\x01'

        def getKeyText(self):
            return f'K{self.n}'

        def getRawEntry(self):
            return ''

        def increment(self):
            self.n += 1

    mod = Mod()
    monkeypatch.setattr(va.Sword, 'SWMgr',
                        lambda: type('M', (), {'getModule': lambda s, n: mod})())
    monkeypatch.setattr(sword_bridge, '_lock', Lock())
    assert va._walk('Webster1913') == ([], 4500)
    assert len(released) == 2
