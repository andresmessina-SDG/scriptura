"""The cross-reference bar's sets: UBS parallels, Thompson's chains, and the
caption that chooses between them."""
import os
import sys

import gi
import pytest

gi.require_version('Gtk', '4.0')

import open_data  # noqa: E402
import settings  # noqa: E402
import sword_bridge  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import build_ubs_parallels  # noqa: E402


# ── UBS parallels, as shipped ────────────────────────────────────────────────

@pytest.fixture
def fresh_ubs(monkeypatch):
    monkeypatch.setattr(open_data, '_ubs', None)


def _refs(rows):
    return [r[:3] for r in rows]


def test_genesis_1_27_gives_matthew_and_mark(fresh_ubs):
    refs = _refs(open_data.get_parallels('Genesis', 1, 27))
    assert ('Matthew', 19, 4) in refs
    assert ('Mark', 10, 6) in refs


def test_parallels_run_both_ways(fresh_ubs):
    assert ('Genesis', 1, 27) in _refs(open_data.get_parallels('Mark', 10, 6))


def test_hebrew_numbers_moved_to_english(fresh_ubs):
    # UBS lists the Hebrew Joel 3:1, which the KJV numbers 2:28.
    assert ('Acts', 2, 17) in _refs(open_data.get_parallels('Joel', 2, 28))
    # Hebrew Ps 18:2-3 is KJV 18:1-2, beside 2 Samuel 22:2-3.
    assert ('2 Samuel', 22, 2) in _refs(open_data.get_parallels('Psalms', 18, 1))


def test_a_verse_never_links_to_itself(fresh_ubs):
    open_data._load_ubs()
    for vid, links in open_data._ubs.items():
        assert open_data._parse_vid(vid) not in links


def test_every_shipped_verse_is_readable():
    with open(open_data._UBS_PATH, encoding='utf-8') as f:
        for line in f:
            members = line.rstrip('\n').split('\t')
            assert len(members) > 1
            for m in members:
                for o in m.split():
                    assert open_data._parse_osis_one(o), o


def test_missing_file_gives_none(monkeypatch, tmp_path):
    monkeypatch.setattr(open_data, '_ubs', None)
    monkeypatch.setattr(open_data, '_UBS_PATH', str(tmp_path / 'none.tsv'))
    assert open_data.get_parallels('Genesis', 1, 27) is None


def test_outside_the_66_gives_none(fresh_ubs):
    assert open_data.get_parallels('Tobit', 1, 1) is None


# ── The build tool ───────────────────────────────────────────────────────────

_TVTMS = '\n'.join([
    'header',
    '#DataStart(Condensed)',
    '$Mal.4:1-4:6\tEnglish KJV\tHebrew\tLatin\tGreek',
    'OneToOne\tMal.4:1-3\tMal.3:19-21\tMal.4:1-3\tMal.4:1-3',
    '',
    '$Psa.51:1-51:19',
    'BIBLES\tEnglish KJV\tHebrew\tLatin\tGreek',
    'SubdividedVerse\tPsa.51:Title\tPsa.51:1-2\tPsa.50:1-2\tPsa.50:1-2',
    'OneToOne\tPsa.51:1\tPsa.51:3\tPsa.50:3\tPsa.50:3',
    '',
    '$Rev.12:17-13.1a\tEnglish KJV (+NIV etc)\tEnglish2\tLatin\tGreek',
    '*Rev.12:18\t*Rev.13:1\tRev.12:17b\tRev.13:1a\tRev.12:18',
    '#DataEnd(Condensed)',
    '',
])


def test_tvtms_pairs_hebrew_and_greek_with_kjv(tmp_path):
    path = tmp_path / 'tvtms.txt'
    path.write_text(_TVTMS, encoding='utf-8')
    maps = build_ubs_parallels.load_tvtms(str(path))
    assert maps['HEB'][('MAL', 3, 19)] == ('MAL', 4, 1)
    assert maps['HEB'][('MAL', 3, 21)] == ('MAL', 4, 3)
    assert maps['HEB'][('PSA', 51, 3)] == ('PSA', 51, 1)
    # A psalm title lands on verse 1, above which the KJV prints it.
    assert maps['HEB'][('PSA', 51, 2)] == ('PSA', 51, 1)
    assert ('PSA', 51, 1) not in maps['HEB']
    assert maps['GRK'][('REV', 12, 18)] == ('REV', 13, 1)


def test_ubs_reference_shapes():
    assert build_ubs_parallels._ubs_verses('MRK 10:7-8') == [
        ('MRK', 10, 7), ('MRK', 10, 8)]
    assert build_ubs_parallels._ubs_verses('LUK 6:27-28,35') == [
        ('LUK', 6, 27), ('LUK', 6, 28), ('LUK', 6, 35)]
    with pytest.raises(ValueError):
        build_ubs_parallels._ubs_verses('nonsense')


# ── Thompson's chains ────────────────────────────────────────────────────────

_SUFFERINGS = (
    '<b>(1) General References to</b><br /><br />'
    '<scripRef>Ps 69:20; Isa 50:6</scripRef><br /><br />'
    '<b>--SEE</b> Sacrifice of Christ, <term>SAVIOUR</term><br /><br />'
    '<b>(3) "The Man of Sorrows"</b><br /><br />'
    '<scripRef>Isa 53:3; Mr 7:34; Lu 19:41</scripRef><br /><br />'
    '<b>(4)</b> Was Despised<br /><scripRef>Isa 53:3; Mt 13:55</scripRef>'
    '<br /><br /><b>SEE</b> Contempt<br /><scripRef>Ge 1:1; Ge 2:1</scripRef>'
)


def test_topic_names_read_as_titles():
    assert sword_bridge._thompson_topic('SUFFERINGS OF CHRIST') == 'Sufferings of Christ'
    assert sword_bridge._thompson_topic('HUMILITY-PRIDE') == 'Humility-Pride'
    assert sword_bridge._thompson_topic('REJECTION of God') == 'Rejection of God'


def test_chains_split_on_headings_and_skip_see_lines():
    chains = sword_bridge._thompson_chains('SUFFERINGS OF CHRIST', _SUFFERINGS)
    shorts = [c[0] for c in chains]
    # "General References to" is half a sentence: the topic stands in.
    assert shorts == ['Sufferings of Christ', 'The Man of Sorrows', 'Was Despised']
    assert chains[1][1] == 'Sufferings of Christ — The Man of Sorrows'
    assert [r[:3] for r in chains[1][2]] == [
        ('Isaiah', 53, 3), ('Mark', 7, 34), ('Luke', 19, 41)]
    # Nothing after a SEE line joins a chain.
    assert all(('Genesis', 1, 1) not in [r[:3] for r in c[2]] for c in chains)


class _FakeLD:
    """Enough of a SWORD dictionary module for _load_thompson's walk."""

    def __init__(self, entries):
        self._entries = entries
        self._i = 0

    def setPosition(self, _pos):
        self._i = 0

    def popError(self):
        return '\x00' if self._i < len(self._entries) else '\x01'

    def getKeyText(self):
        return self._entries[self._i][0]

    def getRawEntry(self):
        return self._entries[self._i][1]

    def increment(self):
        self._i += 1


@pytest.fixture
def thompson(monkeypatch):
    fake = _FakeLD([('SUFFERINGS OF CHRIST', _SUFFERINGS)])
    mgr = type('M', (), {'getModule': lambda self, name: fake})()
    monkeypatch.setattr(sword_bridge, 'mgr', lambda: mgr)
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: ['TCR'])
    monkeypatch.setattr(sword_bridge, '_thompson', None)


def test_each_chain_offers_its_next_link(thompson):
    links = sword_bridge.get_thompson_links('Isaiah', 53, 3)
    assert [(l[4], l[:3]) for l in links] == [
        ('The Man of Sorrows', ('Mark', 7, 34)),
        ('Was Despised', ('Matthew', 13, 55)),
    ]


def test_the_last_link_leads_back_to_the_first(thompson):
    links = sword_bridge.get_thompson_links('Luke', 19, 41)
    assert [l[:3] for l in links] == [('Isaiah', 53, 3)]


def test_no_tcr_means_no_thompson(monkeypatch):
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: ['KJV'])
    assert sword_bridge.get_thompson_links('Isaiah', 53, 3) is None


# ── Choosing a set ───────────────────────────────────────────────────────────

def test_default_set_is_the_old_choice():
    d = sword_bridge.default_crossref_set
    assert d(['openbible', 'tsk', 'ubs']) == 'openbible'
    assert d(['tsk', 'ubs']) == 'tsk'
    assert d(['ubs', 'thompson']) == 'ubs'
    assert d([]) is None


def test_sets_listed_in_order(monkeypatch):
    monkeypatch.setattr(open_data, 'has_cross_refs', lambda: False)
    monkeypatch.setattr(open_data, 'has_parallels', lambda: True)
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: ['TCR', 'TSK'])
    assert sword_bridge.crossref_sets() == ['tsk', 'ubs', 'thompson']


def test_a_missing_set_falls_back_as_before(monkeypatch):
    calls = []

    def fake(set_id, *ref):
        calls.append(set_id)
        return [('Romans', 5, 8, 'Ro 5:8')] if set_id == 'tsk' else None

    monkeypatch.setattr(sword_bridge, 'get_cross_refs_from', fake)
    refs = sword_bridge.get_cross_refs('John', 3, 16, 'thompson')
    assert refs == [('Romans', 5, 8, 'Ro 5:8')]
    assert calls == ['thompson', 'openbible', 'tsk']


# ── The caption as chooser ───────────────────────────────────────────────────

@pytest.fixture
def panel(monkeypatch):
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds the real panel')
    monkeypatch.setattr(settings, 'put', lambda *a: None)
    from crossref_panel import CrossRefPanel
    p = CrossRefPanel(on_ref_clicked=lambda *a: None, on_close=lambda: None)
    p._place = ('John', 3, 16)
    return p


def test_caption_names_the_set_and_verse(panel):
    panel._show_lookup((['openbible', 'ubs'], 'ubs', []))
    assert panel._title.get_text() == 'Parallels · John 3:16'
    assert panel._chevron.get_visible()
    assert panel._set_button.get_can_target()


def test_narrow_window_keeps_the_chooser(panel):
    panel._show_lookup((['openbible', 'ubs'], 'openbible', []))
    panel.set_compact(True)
    assert panel._set_button.get_visible()
    assert panel._title.get_text() == 'OpenBible'


def test_one_set_is_a_plain_caption(panel):
    panel._show_lookup((['ubs'], 'ubs', []))
    assert panel._title.get_text() == 'Cross-references · John 3:16'
    assert not panel._chevron.get_visible()
    assert not panel._set_button.get_can_target()
    toggle = panel._set_button.get_first_child()
    assert not toggle.get_focusable() and not toggle.get_can_target()
    panel.set_compact(True)
    assert not panel._set_button.get_visible()


def test_thompson_chip_shows_chain_and_next_verse(panel):
    panel._show_lookup((['ubs', 'thompson'], 'thompson', [
        ('Mark', 7, 34, 'Mr 7:34', 'The Man of Sorrows',
         'Sufferings of Christ — The Man of Sorrows')]))
    chip = panel._ref_box.get_first_child()
    name = chip.get_child().get_first_child()
    assert (name.get_text(), name.get_next_sibling().get_text()) == (
        'The Man of Sorrows', '→ Mr 7:34')
    assert chip.get_tooltip_text() == 'Sufferings of Christ — The Man of Sorrows'


def test_parallels_alone_still_point_to_the_full_sets(panel):
    panel._show_lookup((['ubs'], 'ubs', []))
    hint = panel._ref_box.get_first_child().get_text()
    assert 'TSK' in hint and 'OpenBible' in hint


def test_two_sets_restore_the_toggle(panel):
    panel._show_lookup((['ubs'], 'ubs', []))
    panel._show_lookup((['tsk', 'ubs'], 'tsk', []))
    toggle = panel._set_button.get_first_child()
    assert toggle.get_focusable() and toggle.get_can_target()
