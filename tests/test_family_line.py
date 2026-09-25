"""The Line: every English Bible on one track, filtered and sorted.

Built and walked, never shown; skips without a display, since building GTK
widgets without one segfaults (see test_genealogy_reader.py).
"""
import types

import pytest
from gi.repository import Gdk, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import bible_family as bf
import family_line as fl


def _pane(names=('KJVA', 'ESV', 'RusSynodal'), came_from='KJVA'):
    return types.SimpleNamespace(_names=list(names), _came_from=came_from,
                                 get_root=lambda: None)


def _line(**kw):
    line = fl.FamilyLine(_pane(**kw))
    line.render()
    return line


def _shown(line):
    return [r for r in line._rows if line._filter(r)]


def test_every_bible_has_a_row_and_a_spoken_sentence():
    line = _line()
    assert len(line._rows) == len(bf.translations())
    for row in line._rows:
        spoken = row._sentence('Protestant')
        assert spoken.startswith(row.record['name'])
        assert spoken.endswith(('reading this.', 'Installed.',
                                'Not installed.'))


def test_the_reading_bible_is_marked_from_where_the_pane_came():
    line = _line()
    assert [r.record['id'] for r in line._rows if r.reading] == ['kjv']
    assert {r.record['id'] for r in line._rows if r.installed} == \
        {'kjv', 'esv'}


def test_availability_filters():
    line = _line()
    line._set_availability('installed')
    assert {r.record['id'] for r in _shown(line)} == {'kjv', 'esv'}
    line._set_availability('can')
    shown = _shown(line)
    assert shown and all(r.installed is None and r.record.get('installable')
                         for r in shown)
    line._set_availability('all')
    assert len(_shown(line)) == len(line._rows)


def test_tradition_and_era_filters_combine():
    line = _line()
    line._set_tradition('catholic')
    assert len(_shown(line)) == 14
    line._set_era(0)                  # before 1611: Douay–Rheims only
    assert [r.record['id'] for r in _shown(line)] == ['douay-rheims']
    line._set_tradition('')
    assert all(r.era == 0 for r in _shown(line))


def test_place_sort_runs_word_for_word_to_free_with_described_after():
    line = _line()
    rows = sorted(line._rows, key=lambda r: r.sort_key('place'))
    groups = [r.group('place')[0] for r in rows]
    assert groups == sorted(groups)
    placed = [r.spot.value for r in rows
              if r.spot is not None and r.spot.kind != 'class']
    zones = [r.group('place')[0] for r in rows
             if r.spot is not None and r.spot.kind != 'class']
    for z in set(zones):
        vals = [v for v, g in zip(placed, zones) if g == z]
        assert vals == sorted(vals)
    assert rows[-1].spot is None      # the unplaced come last


def test_header_counts_follow_the_filters():
    line = _line()
    line._set_tradition('jewish')
    assert sum(line._counts.values()) == len(_shown(line)) == 6


def test_a_narrow_pane_stacks_the_rows():
    line = _line()
    line._set_stacked(True)
    row = line._rows[0]
    assert row._box.get_orientation() == Gtk.Orientation.VERTICAL
    assert not line._axis_clamp.get_visible()
    line._set_stacked(False)
    assert row._box.get_orientation() == Gtk.Orientation.HORIZONTAL


def _settle():
    from gi.repository import GLib
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def test_a_rerender_does_not_throw_the_reader_back_to_their_row(monkeypatch):
    """A theme switch or a restored backup re-renders the pane; only a new
    Bible being read may scroll the Line to it."""
    line = _line()
    _settle()                           # the first render's scroll lands
    calls = []
    monkeypatch.setattr(line, '_scroll_to', lambda row: calls.append(row))
    line.render()
    _settle()
    assert calls == []                  # same Bible: stay where the reader is
    line._pane._came_from = 'ESV'
    line.render()
    _settle()
    assert [r.record['id'] for r in calls] == ['esv']


def test_a_zone_heading_counts_every_bible_in_it():
    """Described-only Bibles sit under their zone and count in it."""
    line = _line()
    for zone in range(len(bf.ZONES)):
        in_zone = [r for r in line._rows if r.spot is not None
                   and r.group('place')[0] // 2 == zone]
        assert line._counts.get((zone, 'zone'), 0) == len(in_zone)


def test_a_zone_of_described_bibles_alone_still_gets_its_heading():
    line = _line()
    line._set_availability('all')
    described = [r for r in line._rows
                 if r.spot is not None and r.spot.kind == 'class']
    assert described
    row = described[0]
    other_zone = next(r for r in line._rows
                      if r.spot is not None and r.spot.kind != 'class'
                      and r.group('place')[0] // 2 != row.group('place')[0] // 2)
    line._header(row, other_zone)
    texts = [c.get_text() for c in _children(row.get_header())]
    assert len(texts) == 2 and 'Described by their makers' in texts[1]


def _children(w):
    c = w.get_first_child()
    while c is not None:
        yield c
        c = c.get_next_sibling()


def test_a_filter_menu_names_its_choice_and_clears():
    line = _line()
    menu = line._trad_menu
    assert menu._label.get_label() == 'All traditions'
    assert not menu._clear.get_visible()
    menu.pick('catholic')
    assert line._tradition == 'catholic'
    assert menu._label.get_label() == 'Catholic'
    assert menu._clear.get_visible() and menu.has_css_class('narrowed')
    menu._clear.emit('clicked')
    assert line._tradition == '' and not menu._clear.get_visible()


def test_sort_is_a_menu_without_a_clear():
    line = _line()
    line._sort_menu.pick('year')
    assert line._sort == 'year'
    assert line._sort_menu._label.get_label() == 'Sort: Year'
    assert not line._sort_menu._clear.get_visible()


def test_every_track_starts_at_the_same_x():
    """The name column asks for exactly its width whatever the row holds,
    and even when measured against a height: a label that wrapped once
    asked for its one-line width there and pushed its track right."""
    line = _line()
    for row in line._rows:
        for for_height in (-1, 40):
            nat = row._text.measure(Gtk.Orientation.HORIZONTAL, for_height)[1]
            assert nat == fl.NAME_W, (row.record['id'], for_height, nat)


def test_only_a_name_that_outruns_its_column_gets_a_tooltip():
    line = _line()
    tips = {r.record['id']: r._name.get_tooltip_text() for r in line._rows}
    assert tips['improved-edition'] == bf.node('improved-edition')['name']
    assert tips['esv'] is None
    assert 0 < sum(1 for t in tips.values() if t) < 10


def test_each_filter_clears_with_its_own_words():
    line = _line()
    words = {m._clear.get_tooltip_text() for m in
             (line._avail_menu, line._trad_menu, line._era_menu)}
    assert words == {'Show every Bible again', 'Show every tradition again',
                     'Show every era again'}
    assert not line._sort_menu._clearable


def test_narrow_puts_the_sort_among_the_filters_and_wide_takes_it_back():
    line = _line()
    line._set_stacked(True)
    assert line._sort_menu.get_parent() is line._filters
    line._set_stacked(False)
    assert line._sort_menu.get_parent() is line._bar
    line._set_stacked(False)                    # idempotent
    assert line._sort_menu.get_parent() is line._bar


# ── Find a Bible ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('query,expected', [
    ('nasb 1995', {'nasb1995'}),              # name and year together
    ('NKJV', {'nkjv'}),                       # the abbreviation
    ('Douay–Rhéims', {'douay-rheims', 'challoner'}),   # dash and accent fold
    ('kjv 1611', {'kjv1611'}),
    ('nothing like this', set()),
])
def test_find_a_bible(query, expected):
    line = _line()
    line._search.set_text(query)
    line._on_search(line._search)     # search-changed waits for a timeout
    assert {r.record['id'] for r in _shown(line)} == expected


def test_the_search_narrows_what_the_filters_left_and_clears():
    line = _line()
    line._set_tradition('catholic')
    line._search.set_text('bible')
    line._on_search(line._search)
    shown = _shown(line)
    assert shown and all(r.chip == 'catholic' for r in shown)
    line._search.set_text('')
    line._on_search(line._search)
    assert len(_shown(line)) == 14             # the tradition filter alone


def test_a_bible_asked_for_by_name_shows_whatever_the_filters():
    """Compare's 'See on the Line' asks for the Bible being read; a filter
    left on from before must not hide it."""
    line = _line()
    line._set_tradition('catholic')
    line._search.set_text('douay')
    line._on_search(line._search)
    line.show_node('kjv')
    assert line._last_row.record['id'] == 'kjv'
    assert line._filter(line._last_row)
    assert line._search.get_text() == '' and line._tradition == ''
