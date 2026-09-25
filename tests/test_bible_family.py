"""The Bible Family Tree's data file and where it places each Bible.

No display required. The data checks are the ones the file was built against
(ids, sources, descent, spectrum ranges); the rest pin the placement rules
decided on 2026-09-24.
"""

import os
import sys
import tomllib
from collections import Counter, defaultdict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bible_family as bf              # noqa: E402

with open(bf._DATA_FILE, 'rb') as _f:
    DATA = tomllib.load(_f)
NODES = DATA['node']
EDGES = DATA['edge']
BY_ID = {n['id']: n for n in NODES}
TRANSLATIONS = [n for n in NODES if n.get('kind', 'translation') == 'translation']


# ── the data file ──────────────────────────────────────────────────────────

def test_ids_are_unique():
    assert [i for i, c in Counter(n['id'] for n in NODES).items() if c > 1] == []


def test_every_node_has_its_facts():
    bases = {'MT', 'LXX', 'VUL', 'TR', 'MAJ', 'CT', 'ENG', 'SPA', 'MIX', 'SYR'}
    for n in NODES:
        for f in ('name', 'year', 'check', 'src'):
            assert f in n, (n['id'], f)
        assert n['check'] in ('checked', 'reference', 'disputed'), n['id']
        if n['check'] == 'disputed':
            assert n.get('dispute'), n['id']
        for f in ('base_ot', 'base_nt'):
            assert n.get(f, 'MT') in bases, (n['id'], f)
    for n in TRANSLATIONS:
        assert n.get('scope') in ('bible', 'nt', 'ot', 'partial'), n['id']
        assert n.get('tradition'), n['id']


def test_every_source_resolves():
    prefixes = ('wp:', 'bg:', 'br:', 'conf:')
    for n in NODES + EDGES:
        for s in n.get('src', []):
            assert s in DATA['source'] or s.startswith(prefixes), (n, s)


def test_descent_runs_forward_in_time_without_a_cycle():
    children = defaultdict(list)
    for e in EDGES:
        a, b = e['from'], e['to']
        assert a in BY_ID and b in BY_ID, e
        assert e['type'] in ('rev', 'drew', 'para'), e
        assert e.get('src'), e
        assert BY_ID[a]['year'] <= BY_ID[b]['year'], e
        children[a].append(b)
    state = {}

    def visit(u):
        state[u] = 1
        for v in children[u]:
            assert state.get(v) != 1, f'cycle through {u} -> {v}'
            if not state.get(v):
                visit(v)
        state[u] = 2
    for u in BY_ID:
        if not state.get(u):
            visit(u)


def test_spectrum_values_are_in_range():
    for n in TRANSLATIONS:
        sp = n.get('spectrum', {})
        if 'band' in sp:
            lo, med, hi = sp['band']
            assert 0 <= lo <= med <= hi <= 1, n['id']
            assert 'n' in sp, n['id']
        if 'measured' in sp:
            assert 0 <= sp['measured'] <= 1.2, n['id']


def test_a_module_belongs_to_one_bible():
    """A module in two nodes would take whichever one loaded last."""
    owners = Counter(m for n in NODES for m in n.get('installable', []))
    assert [m for m, c in owners.items() if c > 1] == []


# ── placement ──────────────────────────────────────────────────────────────

def test_published_band_outranks_the_measurement():
    """The KJV is measured too, but the charts' median is what places it."""
    p = bf.place('KJV')
    assert p.kind == 'band'
    assert p.value == BY_ID['kjv']['spectrum']['band'][1]


def test_archaic_measurement_is_corrected():
    """Old thee/thou English measures freer than it is; 0.05 comes off."""
    raw = BY_ID['webster']['spectrum']['measured']
    assert BY_ID['webster'].get('archaic') is True
    assert bf.place('Webster').value == pytest.approx(raw - bf.ARCHAIC_PENALTY)


def test_modern_measurement_is_left_alone():
    assert not BY_ID['bsb'].get('archaic')
    assert bf.place('BSB').value == BY_ID['bsb']['spectrum']['measured']


def test_an_archaic_text_is_flagged_and_a_modern_one_is_not():
    for nid in ('kjv', 'asv', 'ylt', 'darby', 'challoner', 'rv'):
        assert BY_ID[nid].get('archaic') is True, nid
    for nid in ('bsb', 'leb', 'esv', 'nasb1995'):
        assert not BY_ID[nid].get('archaic'), nid


def test_the_passion_translation_has_no_place():
    """A plain note on its Card, never a mark on the Line."""
    assert BY_ID['tpt'].get('installable') is None
    assert bf._CLASS_SPANS.get(BY_ID['tpt']['spectrum'].get('class')) is None


def test_net_is_placed_by_its_text():
    """One mark for the text; its formal notes are the Card's to explain.
    The chart and the measurement both read the text, and agree on the zone."""
    sp = BY_ID['net']['spectrum']
    assert bf.zone_label(sp['band'][1]) == bf.zone_label(sp['measured']) == 'Between'
    assert bf.zone_label(bf.place('NETfree').value) == 'Between'


def test_an_ebible_module_is_placed_by_its_app_key():
    """The app names an eBible Bible with a prefix; the data holds the bare
    catalogue id. Without the strip every eBible Bible went unplaced."""
    import ebible_bridge
    key = ebible_bridge.PREFIX + 'engwebp'
    assert bf.place(key) is not None
    assert bf.place(key) == bf.place('engwebp')


def test_unknown_and_foreign_modules_have_no_place():
    assert bf.place('RST') is None
    assert bf.place('NoSuchModule') is None


def test_past_the_free_end_still_sorts_last():
    t4t = bf.place('eng-t4t')
    assert t4t.value > 1.0
    assert bf.zone_label(t4t.value) == 'Free'
    assert bf.order_by_line(['eng-t4t', 'BBE', 'KJV']) == ['KJV', 'BBE', 'eng-t4t']


def test_order_puts_unplaced_modules_last_in_their_own_order():
    got = bf.order_by_line(['RST', 'BBE', 'NoSuchModule', 'YLT', 'KJV'])
    assert got == ['YLT', 'KJV', 'BBE', 'RST', 'NoSuchModule']


def test_zone_boundaries():
    assert bf.zone_label(0.0) == 'Word for word'
    assert bf.zone_label(0.33) == 'Between'
    assert bf.zone_label(0.66) == 'Thought for thought'
    assert bf.zone_label(0.90) == 'Free'


# ── the compare popover's mark ─────────────────────────────────────────────

def _paint(spot, hc=False):
    """Paint the tick at its real size; return the alpha channel by row."""
    import cairo
    from collections import namedtuple
    import family_card
    w, h = 56, 12
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ink = namedtuple('Ink', 'red green blue')(0.0, 0.0, 0.0)
    family_card.paint_track(cairo.Context(surf), w, h, spot, ink, hc=hc)
    surf.flush()
    data, stride = surf.get_data(), surf.get_stride()
    return lambda x, y: data[y * stride + x * 4 + 3]


@pytest.mark.parametrize('value', [0.0, 0.33, 0.66, 1.0, 1.1])
def test_a_ring_stays_hollow_anywhere_on_the_track(value):
    """The track's line and the zone ticks must not show inside a ring —
    at either end of the track, or where a ring sits on a zone boundary.
    A ring crossed by a line reads as a different mark."""
    alpha = _paint(bf.Place('measured', value, value, value))
    cx, cy = 4 + min(value, 1.0) * 48, 6.0
    # The ring's inner edge is 2 px from its centre; every pixel wholly
    # inside that must be empty.
    inside = [(px, py) for px in range(56) for py in range(12)
              if ((px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2) ** 0.5 <= 1.2]
    assert inside
    assert [p for p in inside if alpha(*p)] == [], value


def test_a_band_draws_a_solid_dot():
    alpha = _paint(bf.Place('band', 0.5, 0.4, 0.6))
    assert alpha(round(4 + 0.5 * 48 - 0.5), 6) > 200


def test_high_contrast_lifts_the_track_and_the_range():
    """The hairline track and a band's soft range reach 3:1 under high
    contrast; the dot was solid already."""
    import family_card
    spot = bf.Place('band', 0.5, 0.2, 0.8)
    for hc, floor in ((False, 0.3), (True, family_card.HC_LINE)):
        alpha = _paint(spot, hc)
        # The 1px track straddles two pixel rows: its column adds up to it.
        assert sum(alpha(6, y) for y in range(12)) >= round(floor * 255) - 3
        assert alpha(round(4 + 0.3 * 48), 6) >= round(
            (family_card.HC_LINE if hc else 0.25) * 255) - 2   # the range


def test_compare_splits_by_the_language_being_read():
    """Reading the Synodal in an English app: Russian is 'the same language'.
    Each group keeps the order it came in (the Line's, for English)."""
    import annotation_dialogs
    langs = {'YLT': 'en', 'KJV': 'en', 'Wycliffe': 'en', 'RusSynodal': 'ru',
             'LBLA': 'es', 'RusVZh': 'ru'}
    results = [(m, '') for m in bf.order_by_line(
        ['LBLA', 'Wycliffe', 'RusSynodal', 'RusVZh', 'KJV', 'YLT'])]

    def split(lang):
        same, other = annotation_dialogs._split_by_language(
            results, langs.get, lang)
        return [m for m, _t in same], [m for m, _t in other]

    assert split('en') == (['YLT', 'KJV', 'Wycliffe'],
                           ['LBLA', 'RusSynodal', 'RusVZh'])
    assert split('ru') == (['RusSynodal', 'RusVZh'],
                           ['YLT', 'KJV', 'LBLA', 'Wycliffe'])


def test_compare_never_opens_empty_behind_the_switch():
    """An unknown language, or one no row shares, hides nothing."""
    import annotation_dialogs
    results = [('KJV', ''), ('LBLA', '')]
    langs = {'KJV': 'en', 'LBLA': 'es'}
    for lang in ('', 'la'):
        same, other = annotation_dialogs._split_by_language(
            results, langs.get, lang)
        assert same == results and other == [], lang


def test_other_languages_start_hidden():
    import settings
    assert settings.default('compare_other_languages') is False


# ── descent and the Card's facts ───────────────────────────────────────────

def test_descent_runs_back_to_the_root():
    path = [(n['id'], rel) for n, rel in bf.descent('nasb2020')]
    assert path[0] == ('nasb2020', None)
    assert path[-1][0] == 'tyndale'
    assert ('kjv', 'rev') in path


def test_a_reworded_bible_says_so():
    path = [(n['id'], rel) for n, rel in bf.descent('tlb')]
    assert path[1] == ('asv', 'para')


def test_a_second_parent_is_not_lost():
    """Matthew's Bible revised Tyndale AND Coverdale: the main line takes
    the first, and the other is still named."""
    assert bf.descent('matthew')[1][0]['id'] == 'tyndale'
    assert [n['id'] for n in bf.drew_on('matthew')] == ['coverdale']


def test_neighbours_are_charted_bibles_either_side():
    below, above = bf.neighbours('esv')
    esv = bf.place_of(BY_ID['esv']).value
    for n in (below, above):
        assert bf.place_of(n).kind == 'band'
    assert bf.place_of(below).value <= esv < bf.place_of(above).value
    assert bf.neighbours('tpt') == (None, None)


def test_every_citation_has_a_label_and_wikipedia_ones_a_link():
    for n in NODES:
        for key in n.get('src', []):
            label, url = bf.source(key)
            assert label, key
            if key.startswith('wp:'):
                assert url and url.startswith('https://en.wikipedia.org/wiki/'), key


def test_every_card_code_has_words():
    for n in TRANSLATIONS:
        assert n['tradition'] in bf.TRADITIONS, n['id']
        assert n['scope'] in bf.SCOPES, n['id']
        assert n['check'] in bf.CONFIDENCE, n['id']
        for f in ('base_ot', 'base_nt'):
            if f in n:
                assert n[f] in bf.BASE_TEXTS, (n['id'], n[f])


def test_installed_module_matches_by_bible_not_by_name():
    assert bf.installed_module('kjv', ['RusSynodal', 'KJVA']) == 'KJVA'
    assert bf.installed_module(
        'web', [bf.ebible_bridge.PREFIX + 'engwebp']) is not None
    assert bf.installed_module('esv', ['KJVA']) is None


# ── the Line's filters ─────────────────────────────────────────────────────

def test_every_bible_has_one_tradition_chip_and_one_era():
    chips = {k for k, _label in bf.TRADITION_CHIPS}
    for r in bf.translations():
        assert bf.tradition_chip(r) in chips, r['id']
        assert 0 <= bf.era(r) < len(bf.ERAS), r['id']


def test_the_tradition_rulings_hold():
    """Decided 2026-09-24: historic Protestant apart from Pentecostal and
    Charismatic; the Restoration Movement and Wycliffe count as Protestant."""
    chip = {r['id']: bf.tradition_chip(r) for r in bf.translations()}
    assert chip['tpt'] == 'pentecostal'
    assert chip['living-oracles'] == chip['rotherham'] == 'protestant'
    assert chip['wycliffe'] == 'protestant'
    assert chip['noyes'] == chip['diaglott'] == 'other'
    assert chip['nrsv'] == 'ecumenical'
    assert chip['cjb'] == chip['njps'] == 'jewish'
    assert chip['mev'] == 'protestant'


def test_era_boundaries():
    assert [bf.era({'year': y}) for y in (1382, 1610, 1611, 1899, 1900,
                                          1969, 1970, 2020)] == \
        [0, 0, 1, 1, 2, 2, 3, 3]


def test_the_family_module_is_known_to_the_app():
    import content
    import sword_bridge
    assert bf.module_names() == [bf.MODULE_KEY]
    assert content.type_key(bf.MODULE_KEY) == 'family'
    assert bf.MODULE_KEY in content.readable_module_names()
    assert sword_bridge.display_name(bf.MODULE_KEY) == 'The Bible Family Tree'
    assert content.feature_card(bf.MODULE_KEY)['icon'] == \
        'scriptura-bible-family-symbolic'


# ── Compare keeps its size once it is on screen ─────────────────────────────

@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds real widgets')


def test_compare_settles_its_header_before_it_is_shown(display, monkeypatch):
    """The Other languages switch used to appear when the verses arrived,
    making the header taller on a popover already on screen. GNOME Shell
    dismissed the resized popup, so Compare flashed and closed on every
    route. Whether the switch shows is now decided before popup(), and the
    verses arriving leave the header as it was."""
    from gi.repository import Gtk
    import annotation_dialogs as ad

    langs = {'KJV': 'en', 'RusSynodal': 'ru'}
    monkeypatch.setattr(ad, '_compare_names', lambda: ['KJV', 'RusSynodal'])
    monkeypatch.setattr(ad.content, 'language_code', lambda m: langs.get(m, ''))
    monkeypatch.setattr(ad.content, 'load_chapter',
                        lambda m, b, c: [(16, f'{m} text')])
    monkeypatch.setattr(ad.sword_bridge, 'map_target_verse',
                        lambda m, b, c, v: v)
    monkeypatch.setattr(ad.bible_family, 'place', lambda m: None)
    monkeypatch.setattr(ad.settings, 'get', lambda key: False)

    class _Now:                           # the worker and idle, run inline
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(ad.threading, 'Thread', _Now)
    queued = []
    monkeypatch.setattr(ad.GLib, 'idle_add', lambda fn, *a: queued.append(
        (fn, a)))

    at_popup = {}

    def popup(pop):                       # popup() without a window segfaults
        header = pop.get_child().get_first_child()
        at_popup['switch'] = header.get_last_child().get_visible()
        at_popup['height'] = header.measure(Gtk.Orientation.VERTICAL, -1)[1]
        at_popup['pop'] = pop
    monkeypatch.setattr(Gtk.Popover, 'popup', popup)

    class _Pane:
        view = Gtk.Box()          # a TextView loops on a child left at teardown
        book, chapter, module = 'John', 3, 'KJV'

        def _verse_ranges(self, _v):
            return None
    ad.compare_translations(_Pane(), 16)
    for fn, args in queued:               # the verses arrive
        fn(*args)

    header = at_popup['pop'].get_child().get_first_child()
    assert at_popup['switch'] is True
    assert header.get_last_child().get_visible() is True
    assert header.measure(Gtk.Orientation.VERTICAL, -1)[1] == \
        at_popup['height']
    at_popup['pop'].unparent()


# ── Ctrl+Shift+C beside the Family Tree ─────────────────────────────────────

class _ShortcutPane:
    def __init__(self, family, visible=True):
        self._is_family = family
        self._visible = visible
        self.book = 'John'
        self._on_toast = None

    def get_visible(self):
        return self._visible

    def current_verses(self):
        return [16]


def _shortcut_window(pane2_visible):
    import window
    toasts = []

    class _Win:
        _compare_verse = window.BibleWindow._compare_verse
        _bible_pane_in_view = window.BibleWindow._bible_pane_in_view

        def __init__(self):
            self.pane1 = _ShortcutPane(family=True)
            self.pane2 = _ShortcutPane(family=False, visible=pane2_visible)

        def _pane_in_view(self):
            return self.pane1          # the Family Tree has the focus

        def _toast(self, message):
            toasts.append(message)
    return _Win(), toasts


def test_compare_shortcut_reaches_past_the_family_tree(monkeypatch):
    """Focus in the Family Tree used to aim Ctrl+Shift+C at the Family
    pane's hidden text, and nothing happened. It compares in the Bible pane
    beside it."""
    import annotation_dialogs
    calls = []
    monkeypatch.setattr(annotation_dialogs, 'compare_translations',
                        lambda pane, verse: calls.append((pane, verse)))
    win, toasts = _shortcut_window(pane2_visible=True)
    win._compare_verse()
    assert calls == [(win.pane2, 16)] and toasts == []


def test_compare_shortcut_says_why_with_only_the_family_tree(monkeypatch):
    """A window too narrow for two panes shows the Family Tree alone. The
    shortcut used to do nothing at all there; now it says what to do."""
    import annotation_dialogs
    calls = []
    monkeypatch.setattr(annotation_dialogs, 'compare_translations',
                        lambda pane, verse: calls.append((pane, verse)))
    win, toasts = _shortcut_window(pane2_visible=False)
    win._compare_verse()
    assert calls == [] and len(toasts) == 1
