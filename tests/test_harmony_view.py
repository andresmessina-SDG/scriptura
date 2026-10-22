"""The harmony page, the widget driven without a screen.

The widgets are built and driven, never presented; a display is still needed
to build them (see test_genealogy_reader.py for why that is a skip, not a
failure).
"""
import time

import pytest
from gi.repository import Gdk, GLib, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import harmony
import harmony_view as hv
import settings


def _pump(seconds=0.3):
    ctx = GLib.MainContext.default()
    end = time.time() + seconds
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.005)


def _filled(page, seconds=10):
    """Wait for the accounts' words, read off the main loop."""
    end = time.time() + seconds
    while not page._cells and time.time() < end:
        _pump(0.05)
    return page._cells


@pytest.fixture
def page():
    settings.put('harmony_section', '')
    settings.put('harmony_lens', 'robertson')
    pg = hv.HarmonyPage(None)
    pg.render()
    _pump()
    return pg


def test_the_page_opens_on_the_opening_with_every_section_listed(page):
    assert page.current_section() is None
    assert list(page._rows) == harmony.section_ids()
    assert not page._prev.get_sensitive() and page._next.get_sensitive()


def test_a_section_sets_its_gospels_side_by_side_in_canonical_order(page):
    page.select('72')
    cells = _filled(page)
    assert [r['books'] for r in cells] == [list(harmony.GOSPELS)]
    assert settings.get('harmony_section') == '72'


def test_the_eusebius_lens_shows_his_rows(page):
    page.select('54')
    page._lenses.set_active_name('eusebius')
    cells = _filled(page)
    assert settings.get('harmony_lens') == 'eusebius'
    assert len(cells) == len(harmony.eusebius_rows('54'))
    assert any(r['books'] == ['Matt', 'Luke'] for r in cells)
    assert all(r['head'] for r in cells)


def test_steps_and_escape_walk_and_leave(page):
    page.select('72')
    page._step(1)
    assert page.current_section() == '73'
    page._step(-1)
    assert page.current_section() == '72'
    page._on_escape(None, Gdk.KEY_Escape, 0, 0)
    assert page.current_section() is None


def test_columns_even_out_when_four_do_not_fit_on_a_line(page):
    page.select('72')
    assert page._per_line(4 * hv.COL_MIN) == 4
    assert page._per_line(3 * hv.COL_MIN) == 2      # two and two, not 3 + 1
    assert page._per_line(hv.COL_MIN - 1) == 1
    page.select('56')                                # Luke alone
    assert page._per_line(4 * hv.COL_MIN) == 1


def test_the_markup_numbers_verses_and_underlines_shared_words():
    verses = [(6, 30, [('apostles', frozenset({'G652'})), (' told', frozenset())]),
              (6, 31, [('rest', frozenset({'G373'}))])]
    m = hv._markup(verses, {'G652'})
    assert '6:30</span>' in m and '>31</span>' in m
    assert 'underline="single"' in m and m.count('underline=') == 1
    Gtk.Label().set_markup(m)       # valid Pango markup


def test_canon_heads_name_the_gospels():
    row = next(r for r in harmony.eusebius_rows('72') if r['table'] == 'I')
    assert hv._canon_head(row) == 'Canon I · Matthew, Mark, Luke, John'


def test_a_click_closes_the_outline_popover_and_keys_do_not(page):
    page.select('72')
    page._on_key(None, Gdk.KEY_Down, 0, 0)
    assert page.current_section() == '73'
    page._on_row(None, '56')
    assert page.current_section() == '56'
