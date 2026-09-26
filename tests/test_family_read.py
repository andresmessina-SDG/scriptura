"""Read the difference: one verse down the Line.

Built and walked, never shown; skips without a display, since building GTK
widgets without one segfaults (see test_genealogy_reader.py).
"""
import re
import types

import pytest
from gi.repository import Gdk, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import bible_family as bf
import family_read as fr
import family_tree as ft
from family_line import line_group


# ── references ───────────────────────────────────────────────────────────

def test_a_typed_reference_is_found_and_clamped():
    assert fr.parse_reference('John 3:16') == ('John', 3, 16)
    assert fr.parse_reference('  jn 3 ') == ('John', 3, 1)
    assert fr.parse_reference('1 cor 13:4') == ('1 Corinthians', 13, 4)
    assert fr.parse_reference('Genesis 99:99') == ('Genesis', 50, 26)
    assert fr.parse_reference('Jude 1:0') == ('Jude', 1, 1)
    for bad in ('', 'nonsense 9', 'John', '3:16'):
        assert fr.parse_reference(bad) is None


def test_stepping_crosses_chapters_and_books_and_stops_at_the_ends():
    assert fr.step(('John', 3, 16), 1) == ('John', 3, 17)
    assert fr.step(('John', 3, 36), 1) == ('John', 4, 1)
    assert fr.step(('John', 4, 1), -1) == ('John', 3, 36)
    assert fr.step(('Malachi', 4, 6), 1) == ('Matthew', 1, 1)
    assert fr.step(('Matthew', 1, 1), -1) == ('Malachi', 4, 6)
    assert fr.step(('Genesis', 1, 1), -1) == ('Genesis', 1, 1)
    assert fr.step(('Revelation', 22, 21), 1) == ('Revelation', 22, 21)


# ── which Bibles get a row ───────────────────────────────────────────────

def test_rows_are_the_installed_and_the_installable_that_hold_the_verse():
    nt = {r['id']: m for r, m in fr.rows_for(('John', 3, 16), ['KJVA'])}
    ot = {r['id']: m for r, m in fr.rows_for(('Psalms', 23, 1), ['KJVA'])}
    assert nt['kjv'] == 'KJVA' and ot['kjv'] == 'KJVA'
    # A New Testament the reader lacks is offered for John, not a Psalm;
    # an Old Testament the other way round.
    assert 'worsley' in nt and 'worsley' not in ot
    assert 'brenton' in ot and 'brenton' not in nt
    # A part of the Bible may not hold the verse: offered only once installed.
    assert 'tyndale' not in nt
    # Nothing the app can neither show nor install.
    for record in bf.translations():
        if record['id'] in nt and nt[record['id']] is None:
            assert record.get('installable')


def test_rows_run_down_the_line():
    rows = fr.rows_for(('John', 3, 16), ['KJVA', 'ESV'])
    keys = [(line_group(bf.place_of(r))[0],
             bf.place_of(r).value if bf.place_of(r) else 0.0)
            for r, _m in rows]
    assert keys == sorted(keys)


# ── the view ─────────────────────────────────────────────────────────────

def _read(monkeypatch, texts=None, names=('KJVA', 'ESV'), root=None,
          rows='all'):
    """A FamilyRead whose verses arrive at once: `texts` maps a module to
    its verse, '' for a Bible without it."""
    texts = texts or {}

    class _Now:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(fr.threading, 'Thread', _Now)
    monkeypatch.setattr(fr.GLib, 'idle_add', lambda fn, *a: fn(*a))
    monkeypatch.setattr(fr, 'verse_text',
                        lambda m, ref: texts.get(m, f'{m} {ref}'))
    monkeypatch.setattr(fr.interlinear_data, 'is_installed', lambda n: False)
    store = {'family_read_rows': rows, 'family_read_marks': True}
    monkeypatch.setattr(fr.settings, 'get', lambda k: store.get(k))
    monkeypatch.setattr(fr.settings, 'put',
                        lambda k, v: store.__setitem__(k, v))
    pane = types.SimpleNamespace(_names=list(names), _came_from='KJVA',
                                 book='John', chapter=3, _selected_verse=16,
                                 get_root=lambda: root)
    read = fr.FamilyRead(pane)
    read.render()
    return read


def _shown(read):
    return [r for r in read._rows if not r.empty]


def test_it_opens_at_the_verse_the_pane_was_reading(monkeypatch):
    read = _read(monkeypatch)
    assert read.ref == ('John', 3, 16)
    assert read._entry.get_text() == 'John 3:16'
    kjv = next(r for r in read._rows if r.record['id'] == 'kjv')
    assert kjv.text.get_text() == "KJVA ('John', 3, 16)"


def test_a_bible_without_the_verse_leaves_the_list(monkeypatch):
    read = _read(monkeypatch, texts={'ESV': ''})
    ids = [r.record['id'] for r in _shown(read)]
    assert 'kjv' in ids and 'esv' not in ids


def test_an_uninstalled_row_offers_its_install(monkeypatch):
    asked = []
    root = types.SimpleNamespace(open_bibles=asked.append)
    read = _read(monkeypatch, root=root)
    row = next(r for r in read._rows if r.record['id'] == 'darby')
    assert row.module is None and row.text is None
    button = row.get_child().get_last_child()
    assert button.get_label() == 'Install to read it here'
    button.emit('clicked')
    assert asked == [bf.node('darby')['installable'][0]]


def test_the_original_or_the_way_to_install_it(monkeypatch):
    asked = []
    root = types.SimpleNamespace(open_bibles=asked.append)
    read = _read(monkeypatch, root=root)
    door = read._source.get_first_child()
    assert 'Greek interlinear' in door.get_label()
    door.emit('clicked')
    assert asked == ['']

    word = types.SimpleNamespace(verse=1, surface='יְהוָה', gloss='Yahweh')
    other = types.SimpleNamespace(verse=2, surface='x', gloss='y')
    monkeypatch.setattr(fr.interlinear_data, 'is_installed', lambda n: True)
    monkeypatch.setattr(fr.interlinear_data, 'load_chapter',
                        lambda n, b, c: [word, other])
    read.show_verse('Psalms', 23, 1)
    kids = []
    c = read._source.get_first_child()
    while c is not None:
        kids.append(c)
        c = c.get_next_sibling()
    kicker, card = kids
    wrap = card.get_first_child()
    assert 'Hebrew' in kicker.get_label()
    assert wrap.get_direction() == Gtk.TextDirection.RTL
    cell = wrap.get_first_child()
    assert cell.get_first_child().get_label() == 'יְהוָה'
    assert cell.get_next_sibling() is None      # verse 1 only


def test_the_field_and_the_arrows_move_the_verse(monkeypatch):
    read = _read(monkeypatch)
    read._entry.set_text('Romans 3:23')
    read._on_entry(read._entry)
    assert read.ref == ('Romans', 3, 23)
    read._step(1)
    assert read.ref == ('Romans', 3, 24)
    read._entry.set_text('nonsense')
    read._on_entry(read._entry)
    assert read.ref == ('Romans', 3, 24)
    assert read._entry.has_css_class('error')


def test_a_stale_fetch_never_fills_the_new_verse(monkeypatch):
    """Two verses asked in quick succession: the first's texts arrive after
    the second's rows are built, and must not land in them."""
    read = _read(monkeypatch)
    queued = []
    monkeypatch.setattr(fr.GLib, 'idle_add',
                        lambda fn, *a: queued.append((fn, a)))
    read.show_verse('John', 1, 1)
    read.show_verse('John', 1, 2)
    first, second = queued
    first[0](*first[1])
    kjv = next(r for r in read._rows if r.record['id'] == 'kjv')
    assert kjv.text.get_text() == "KJVA ('John', 3, 16)"
    second[0](*second[1])
    assert kjv.text.get_text() == "KJVA ('John', 1, 2)"


# ── the page ─────────────────────────────────────────────────────────────

def _page(monkeypatch, view='read'):
    import settings
    store = {'family_tree_view': view}
    monkeypatch.setattr(settings, 'get', lambda k: store.get(k))
    monkeypatch.setattr(settings, 'put', lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(fr, 'verse_text', lambda m, ref: 'text')
    pane = types.SimpleNamespace(_names=['KJVA'], _came_from='KJVA',
                                 book='John', chapter=3, _selected_verse=16,
                                 get_root=lambda: None)
    return ft.FamilyTree(pane), store


def test_the_page_remembers_read_and_hides_the_family_tools(monkeypatch):
    page, store = _page(monkeypatch, view='line')
    page.turn_to('read')
    assert page._stack.get_visible_child_name() == 'read'
    assert store['family_tree_view'] == 'read'
    assert page.read.ref == ('John', 3, 16)
    for tool in (page._print_btn, page._list_btn, page._notes_btn,
                 page._arrangements):
        assert not tool.get_visible()
    assert page._hint.get_visible()
    page2, _store = _page(monkeypatch, view='read')
    assert page2._stack.get_visible_child_name() == 'read'


def test_compare_s_verse_is_the_one_shown(monkeypatch):
    """Turned to by Compare, the view shows Compare's verse, not the one the
    pane was reading."""
    page, _store = _page(monkeypatch, view='family')
    page.show_read('Romans', 8, 28)
    assert page._stack.get_visible_child_name() == 'read'
    assert page.read.ref == ('Romans', 8, 28)
    page.show_read('Romans', 8, 29)       # already showing: still moves
    assert page.read.ref == ('Romans', 8, 29)


def test_the_next_verse_keeps_the_rows_and_the_place(monkeypatch):
    """Stepping within a Testament, or a re-render for a theme, shows the
    same Bibles: the rows stay and so does the scroll (rebuilding cost
    ~90ms a step and threw the reader back to the top)."""
    read = _read(monkeypatch)
    rows = list(read._rows)
    adj = read._scroll.get_vadjustment()
    adj.configure(300, 0, 2000, 10, 100, 400)
    read._step(1)
    read.render()
    assert read._rows == rows and adj.get_value() == 300
    kjv = next(r for r in rows if r.record['id'] == 'kjv')
    assert kjv.text.get_text() == "KJVA ('John', 3, 17)"
    read.show_verse('Psalms', 23, 1)          # another Testament: new rows
    assert read._rows != rows and adj.get_value() == 0


# ── bug check 2026-09-25 ─────────────────────────────────────────────────

def test_a_pane_s_verse_is_read_in_the_app_s_numbering(monkeypatch):
    """A Vulgate psalm counts its title as verses 1-2: the pane's verse 4,
    "amplius lava me", is the KJV's verse 2. Read took the pane's number
    as the app's and showed Psalm 51:4."""
    import annotations
    monkeypatch.setattr(annotations, 'app_verse',
                        lambda m, b, c, v: v - 2 if m == 'Vulgate' else v)
    assert fr.app_ref('Vulgate', 'Psalms', 51, 4) == ('Psalms', 51, 2)
    assert fr.app_ref('Vulgate', 'Psalms', 51, 2) == ('Psalms', 51, 1)
    assert fr.app_ref('KJVA', 'John', 3, None) == ('John', 3, 1)

    other = types.SimpleNamespace(
        module='Vulgate', book='Psalms', chapter=51, _is_family=False,
        get_visible=lambda: True, _is_verse_navigable=lambda: True,
        current_verses=lambda: [4])
    root = types.SimpleNamespace(pane1=None, pane2=other)
    read = _read(monkeypatch, root=root)
    assert read.ref == ('Psalms', 51, 2)


def test_a_pane_without_verses_is_not_the_one_being_read(monkeypatch):
    """A dictionary beside the Family Tree keeps a stale book; the verse
    comes from where this pane was reading instead."""
    other = types.SimpleNamespace(
        module='StrongsGreek', book='Genesis', chapter=1, _is_family=False,
        get_visible=lambda: True, _is_verse_navigable=lambda: False)
    root = types.SimpleNamespace(pane1=None, pane2=other)
    read = _read(monkeypatch, root=root)
    assert read.ref == ('John', 3, 16)


def test_an_install_shows_its_verse_where_the_reader_left_it(monkeypatch):
    read = _read(monkeypatch, names=['KJVA'])
    darby = next(r for r in read._rows if r.record['id'] == 'darby')
    assert darby.module is None
    adj = read._scroll.get_vadjustment()
    adj.configure(500, 0, 3000, 10, 100, 400)
    read._pane._names = ['KJVA', 'Darby']
    read.render()
    darby = next(r for r in read._rows if r.record['id'] == 'darby')
    assert darby.module == 'Darby'
    assert darby.text.get_text() == "Darby ('John', 3, 16)"
    assert adj.get_value() == 500


def test_a_superseded_fetch_stops_reading(monkeypatch):
    """Ten quick steps must not queue ten full fetches behind SWORD's lock:
    a fetch whose verse is no longer wanted stops."""
    read = _read(monkeypatch)
    started = []

    class _Later:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            started.append(self.target)
    monkeypatch.setattr(fr.threading, 'Thread', _Later)
    calls = []
    monkeypatch.setattr(fr, 'verse_text',
                        lambda m, ref: calls.append(ref) or 'x')
    read._step(1)
    read._step(1)
    started[0]()
    assert calls == []
    started[1]()
    assert calls and set(calls) == {('John', 3, 18)}


def test_an_install_re_renders_a_family_tree_pane():
    import window
    rendered, refreshed = [], []

    def pane(family):
        return types.SimpleNamespace(
            _is_family=family,
            refresh_modules=lambda: refreshed.append(family),
            _family_tree=types.SimpleNamespace(
                render=lambda: rendered.append(family)))
    fake = types.SimpleNamespace(pane1=pane(False), pane2=pane(True),
                                 _update_fnote_sensitivity=lambda: None)
    window.BibleWindow._on_modules_changed(fake)
    assert refreshed == [False, True] and rendered == [True]


def test_read_opens_with_no_bible_being_read(monkeypatch):
    """The Family Tree alone, not opened from a Bible the data knows: no
    reading Bible, and Read crashed before it could show (2026-09-25)."""
    import settings
    store = {'family_tree_view': 'line'}
    monkeypatch.setattr(settings, 'get', lambda k: store.get(k))
    monkeypatch.setattr(settings, 'put', lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(fr, 'verse_text', lambda m, ref: 'text')
    pane = types.SimpleNamespace(_names=['KJVA'], _came_from=None,
                                 book='John', chapter=3, _selected_verse=None,
                                 get_root=lambda: None)
    page = ft.FamilyTree(pane)
    page.turn_to('read')
    assert page._stack.get_visible_child_name() == 'read'
    assert page.read.ref == ('John', 3, 1)
    assert page.read._rows



# ── installed only, by default (decided 2026-09-25) ──────────────────────

def test_only_installed_bibles_show_until_all_is_chosen(monkeypatch):
    read = _read(monkeypatch, rows='installed')
    assert read._rows_menu.key == 'installed'
    shown = [r for r in read._rows if r.get_child_visible()]
    assert {r.record['id'] for r in shown} == {'kjv', 'esv'}
    read._rows_menu.pick('all')
    assert fr.settings.get('family_read_rows') == 'all'
    shown = [r for r in read._rows if r.get_child_visible()]
    assert any(r.module is None for r in shown)
    # In the Line's order either way.
    read._rows_menu.pick('installed')
    shown = [r for r in read._rows if r.get_child_visible()]
    assert [r.record['id'] for r in shown] == [
        r.record['id'] for r in read._rows
        if r.module is not None and not r.empty]


def test_the_choice_is_remembered(monkeypatch):
    read = _read(monkeypatch, rows='all')
    assert read._rows_menu.key == 'all'
    assert any(r.module is None and r.get_child_visible() for r in read._rows)


def test_no_installed_english_bible_says_what_to_do(monkeypatch):
    read = _read(monkeypatch, names=['RusSynodal'], rows='installed')
    assert not [r for r in read._rows if r.get_child_visible()]
    assert 'All Bibles' in read._empty.get_label()
    assert read._empty.get_mapped() or read._empty.get_child_visible()




# ── the difference marked; the object marker (2026-09-25) ───────────────

def _faded(markup):
    return re.findall(r'<span alpha="58%">([^<]*)</span>', markup)


def test_shared_words_fade_and_differing_words_keep_their_ink():
    m = fr.marked('For God so loved the world, that he gave his only '
                  'begotten Son', 'for God so loved the World that he gave '
                  'his one and only Son')
    faded = _faded(m)
    assert 'begotten' not in faded
    # Case and punctuation are not differences.
    assert {'For', 'world,', 'only', 'Son'} <= set(faded)
    assert fr.marked('a < b & c', None) == 'a &lt; b &amp; c'


def test_every_verse_is_read_against_its_neighbour(monkeypatch):
    texts = {'KJVA': 'For God so loved the world',
             'ESV': 'For God so loved the world'}
    read = _read(monkeypatch, texts=texts)
    rows = [r for r in read._rows if r.module]
    # Identical texts: the first fades too, read against the one below.
    for r in rows:
        assert 'alpha' in r.text.get_label()
    read._marks_btn.set_active(False)
    assert fr.settings.get('family_read_marks') is False
    for r in rows:
        assert r.text.get_label() == 'For God so loved the world'


def test_the_object_marker_leaves_the_gloss_line(monkeypatch):
    assert fr.gloss_text('and <obj.>') == ('and', True)
    assert fr.gloss_text('<obj.>') == ('', True)
    assert fr.gloss_text('<the>') == ('<the>', False)
    read = _read(monkeypatch)
    words = [types.SimpleNamespace(verse=1, surface='אֵת', gloss='<obj.>')]
    monkeypatch.setattr(fr.interlinear_data, 'is_installed', lambda n: True)
    monkeypatch.setattr(fr.interlinear_data, 'load_chapter',
                        lambda n, b, c: words)
    read.show_verse('Genesis', 1, 1)
    card = read._source.get_last_child()
    assert card.has_css_class('family-read-source')
    cell = card.get_first_child().get_first_child()
    assert cell.get_last_child().get_label() == ' '
    assert 'object' in cell.get_tooltip_text()
