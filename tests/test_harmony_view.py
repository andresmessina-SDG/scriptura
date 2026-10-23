"""The harmony page, the widget driven without a screen.

The widgets are built and driven, never presented; a display is still needed
to build them (see test_genealogy_reader.py for why that is a skip, not a
failure).
"""
import time

import pytest
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

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


def test_an_accounts_text_asks_no_width_and_keeps_its_height():
    """GTK measures a wrapping label's width a letter to a line, which for
    a long passage took most of a second; the column sets it instead. The
    height at a given width is the plain label's."""
    m = hv._markup([(5, v, [('Blessed are the poor in spirit: for theirs '
                             'is the kingdom of heaven. ', frozenset())])
                    for v in range(1, 40)], set())
    fast = hv._PassageText(wrap=True, use_markup=True)
    plain = Gtk.Label(wrap=True, use_markup=True)
    for lab in (fast, plain):
        lab.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lab.set_markup(m)
    assert fast.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == (0, 0)
    assert (fast.measure(Gtk.Orientation.VERTICAL, 400)[:2]
            == plain.measure(Gtk.Orientation.VERTICAL, 400)[:2])


def test_the_margin_signs_are_placed_once_a_layout():
    """Placing a sign lays its line out, and a scroll paints every frame:
    the places hold until the layout, the chapter's signs or a tag change.
    A pointer away from the margin asks nothing."""
    from reading_view import BibleTextView
    view = BibleTextView()
    buf = view.get_buffer()
    buf.set_text('30 And the apostles gathered themselves together unto Jesus')
    signs = [(buf.create_mark(None, buf.get_start_iter(), True), '72',
              (True,) * 4, 1)]
    view.set_harmony_signs(signs)
    view.set_harmony(True)
    first = view._sign_lines()
    assert view._sign_lines() is first
    view._stamp = 'the layout moved'
    moved = view._sign_lines()
    assert moved is not first and view._sign_lines() is moved
    buf.create_tag(None, invisible=True)            # footnote markers hidden
    tagged = view._sign_lines()
    assert tagged is not moved
    view.set_harmony_signs(list(signs))
    assert view._sign_lines() is not tagged
    _mark, x, y0, *_rest = view._sign_lines()[0]
    assert view.harmony_sign_at(x, y0 + 1) == ['72']
    assert view.harmony_sign_at(x + 50, y0 + 1) is None


def test_the_outline_moves_into_the_popover_once(page):
    """Medium to phone width keeps the outline in its popover. A popover
    holds its child inside a widget of its own, so the outline's parent is
    never the popover; taking it from the page again was a GTK critical."""
    page._wide = False
    page._apply_width()
    removed = []
    page._body.remove = lambda w: removed.append(w)
    page._apply_width()
    assert page._outline_pop.get_child() is page._outline_scroll
    assert removed == []


def test_canon_heads_name_the_gospels():
    row = next(r for r in harmony.eusebius_rows('72') if r['table'] == 'I')
    assert hv._canon_head(row) == 'Canon I · Matthew, Mark, Luke, John'


def test_a_click_closes_the_outline_popover_and_keys_do_not(page):
    page.select('72')
    page._on_key(None, Gdk.KEY_Down, 0, 0)
    assert page.current_section() == '73'
    page._on_row(None, '56')
    assert page.current_section() == '56'


# ── the threads in the pillars band ──────────────────────────────────────────

def test_the_accounts_are_joined_gospel_to_gospel_in_order():
    two = ('robertson', 'eusebius')
    rows = [[((0.5, 0.51), 'section', two, None)], [],
            [((0.3, 0.31), 'section', two, None)],
            [((0.2, 0.21), 'section', two, None)]]
    assert hv._threads(rows) == [
        ((0, (0.5, 0.51), 'section'), (2, (0.3, 0.31), 'section'), 'section', 2),
        ((2, (0.3, 0.31), 'section'), (3, (0.2, 0.21), 'section'), 'section', 2)]


def test_a_similar_event_told_twice_takes_one_dashed_thread():
    """§39: Luke alone; the second rejection in Matthew and Mark. Its two
    accounts are joined to each other, and one dashed thread reaches it,
    from Luke to the nearer, Mark — not two side by side through Mark."""
    r = ('robertson',)
    rows = [[((0.45, 0.46), 'look_alike', r, '69')],
            [((0.33, 0.34), 'look_alike', r, '69')],
            [((0.2, 0.21), 'section', r, None)], []]
    assert hv._threads(rows) == [
        ((0, (0.45, 0.46), 'look_alike'), (1, (0.33, 0.34), 'look_alike'),
         'other', 0),
        ((1, (0.33, 0.34), 'look_alike'), (2, (0.2, 0.21), 'section'),
         'look_alike', 1)]


def test_said_elsewhere_takes_no_thread():
    r = ('eusebius',)
    rows = [[((0.5, 0.51), 'section', r, None)],
            [((0.4, 0.41), 'section', r, None)],
            [((0.6, 0.61), 'same_words', r, '113')], []]
    assert not any(t[2] in ('same_words', 'other', 'look_alike')
                   for t in hv._threads(rows))


def test_a_one_gospel_section_and_its_like_in_the_same_gospel_have_nothing_to_join():
    r = ('robertson',)
    rows = [[], [], [((0.5, 0.51), 'section', r, None),
                     ((0.2, 0.21), 'look_alike', r, '59')], []]
    assert hv._threads(rows) == []


def test_a_thread_lands_on_its_mark():
    assert hv._mark_x((0.5, 0.5), 'look_alike', 200) == 100.5
    assert hv._mark_x((0.5, 0.501), 'section', 200) == 100 + 2.5 / 2


def test_the_threads_wait_to_draw_in_until_the_band_is_on_screen(page, monkeypatch):
    """Started on a band not yet placed, the animation was skipped to its
    end and the threads never drew in; it now plays when the band maps."""
    monkeypatch.setattr(hv.motion, 'should_animate', lambda: True)
    page.select('72')
    assert page._band_progress == 0.0
    assert page._band_anim.get_state() == Adw.AnimationState.IDLE


# ── Canon X and a similar event set beside (sketches C and E) ───────────────

def test_canon_x_is_quoted_where_eusebius_too_set_the_whole_section_apart(page):
    assert harmony.canons('56') == ['X']
    assert page._canon_x('56') is not None
    mixed = next(s['id'] for s in harmony.data()['sections']
                 if len(s['gospels']) == 1 and 'X' in harmony.canons(s['id'])
                 and harmony.canons(s['id']) != ['X'])
    assert page._canon_x(mixed) is None          # he paired some of it
    assert page._canon_x('72') is None           # told in all four
    page._lens = 'eusebius'
    assert page._canon_x('56') is None


def test_a_similar_event_goes_beside_the_accounts_and_comes_away(page):
    page.select('55')
    target = next(m['section'] for m in harmony.other_links('55')
                  if m['kind'] == 'look_alike')
    before = page._slots()
    page._set_beside(target)
    extra = [f'+{b}' for b in harmony.gospel_spans(target)]
    assert page._slots() == before + extra
    assert any(c.get('beside') == target
               for c in page._account_rows[0]['cells'])
    assert page._beside_btns[target].get_active()
    page._set_beside(None)
    assert page._slots() == before


def test_choosing_another_section_takes_the_similar_event_away(page):
    page.select('55')
    target = next(m['section'] for m in harmony.other_links('55')
                  if m['kind'] == 'look_alike')
    page._set_beside(target)
    page.select('56')
    assert page._beside is None


def test_a_similar_event_beside_neither_counts_for_nor_wears_an_underline(
        page, monkeypatch):
    seen = []

    def shared(cols):
        seen.append(len(cols))
        return [{1} for _c in cols]
    monkeypatch.setattr(harmony, 'shared_numbers', shared)
    rows = [{'head': None, 'cells': [
        {'book': 'Matt', 'spans': [], 'eus': []},
        {'book': 'Luke', 'spans': [], 'eus': []},
        {'book': 'John', 'spans': [], 'eus': [], 'slot': '+John',
         'beside': '33'}]}]
    made = []
    monkeypatch.setattr(page, '_cell',
                        lambda c, w, s: made.append((c['book'], s)) or Gtk.Label())
    page._grid = None
    page._note = Gtk.Label()
    page._fill(rows, 'KJV')
    assert seen == [2]
    assert made == [('Matt', {1}), ('Luke', {1}), ('John', set())]
