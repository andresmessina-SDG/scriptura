"""Where a mark lives, and what number it wears.

A mark belongs to a place in Scripture, not to the module that happened to be
open when it was made: the store is keyed `book/chapter` with verse numbers in
app space (KJV), so a note written in the KJV is there in the RVR60. The module
is the lens. It is not part of the key, and every number crossing that boundary
is translated — inward on write, outward on read — because a Synodal or Vulgate
psalter numbers the superscription, so its verse 1 is app-space verse 0.

Most of this proves the wiring, so it fakes the mapping and runs anywhere. The
one test that asks a real Synodal psalter what its first verse is needs that
module installed, and says so when it is not: CI fetches KJVA and MHCC and
nothing else.
"""
import json

import pytest

import annotations
import annotations_window
import sword_bridge


@pytest.fixture
def display():
    """Skip a test that builds the real Annotations window when there is no
    display to build it on — CI has none, and `Adw.Window.__init__` raises
    there (other GTK paths segfault outright, which is why the check is
    `Gdk.Display.get_default()` and never `Gtk.init_check()`, whose True
    means nothing; GUIDANCE §4).

    A fixture rather than this file's module-level skip: almost everything
    here is dict- and mapping-level and must go on running on CI. Only the
    four window tests need a screen.
    """
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: the Annotations window is a real '
                    'Adw.Window')


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_outward_maps', {})
    return tmp_path


@pytest.fixture
def offset_by_a_superscription(monkeypatch):
    """A stand-in for a psalter that numbers the superscription: module
    verse n is app verse n-1, and every other module is left alone."""
    real_to_app = sword_bridge.map_verse_to_app
    real_to_module = sword_bridge.map_target_verse
    real_mapped = sword_bridge.mapped_chapter
    fake_module = 'SuperscribedPsalter'

    def to_app(module, book, chapter, verse):
        if module == fake_module and verse is not None:
            return verse - 1
        return real_to_app(module, book, chapter, verse)

    def to_module(module, book, chapter, verse):
        if module == fake_module and verse is not None:
            return verse + 1
        return real_to_module(module, book, chapter, verse)

    def mapped(module, book, chapter):
        if module == fake_module:
            return (book, chapter)
        return real_mapped(module, book, chapter)

    real_load = sword_bridge.load_chapter

    def load(module, book, chapter):
        # The rendered chapter is what the outward map is built from: this
        # psalter numbers the superscription, so it has one line more than
        # the KJV's eight.
        if module == fake_module:
            return [(v, f'verse {v}') for v in range(1, 10)]
        return real_load(module, book, chapter)

    monkeypatch.setattr(sword_bridge, 'map_verse_to_app', to_app)
    monkeypatch.setattr(sword_bridge, 'map_target_verse', to_module)
    monkeypatch.setattr(sword_bridge, 'mapped_chapter', mapped)
    monkeypatch.setattr(sword_bridge, 'load_chapter', load)


def _only_entry():
    entries = annotations_window._all_entries()
    assert len(entries) == 1, entries
    return entries[0]


# ── The key is a reference ───────────────────────────────────────────────────

def test_the_store_is_keyed_by_reference_not_by_module(isolated):
    annotations.save_highlight('KJVA', 'Psalms', 3, 1, '#ffff00')
    assert list(annotations._load()) == ['Psalms/3']


def test_a_mark_made_in_one_module_is_there_in_another(isolated):
    """The whole point. A reader who highlights in the KJV and then opens a
    Spanish text used to find an unmarked Bible."""
    annotations.save_highlight('KJVA', 'John', 3, 16, '#ffff00')
    assert annotations.get_annotations(
        'SpaRV', 'John', 3)['16']['highlight'] == '#ffff00'


def test_a_chapter_note_crosses_modules_too(isolated):
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'a thought')
    assert annotations.get_chapter_note('SpaRV', 'Psalms', 23) == 'a thought'


# ── The lens: module numbering in, app numbering stored, module numbering out ─

def test_an_app_keyed_module_is_left_alone(isolated):
    annotations.save_highlight('KJVA', 'Psalms', 3, 1, '#ffff00')
    assert annotations._load()['Psalms/3']['1']['highlight'] == '#ffff00'
    assert _only_entry()['verse'] == 1


def test_a_mapped_module_writes_the_app_space_verse(
        isolated, offset_by_a_superscription):
    annotations.save_highlight('SuperscribedPsalter', 'Psalms', 3, 1, '#ffff00')
    assert list(annotations._load()['Psalms/3']) == ['0'], \
        'module verse 1 is the superscription — app-space verse 0'
    assert _only_entry()['verse'] == 0


def test_the_module_reads_back_its_own_numbering(
        isolated, offset_by_a_superscription):
    """Round trip: what the pane wrote under its own number it must find
    again under that number, or the highlight paints the wrong line."""
    annotations.save_highlight('SuperscribedPsalter', 'Psalms', 3, 1, '#ffff00')
    annos = annotations.get_annotations('SuperscribedPsalter', 'Psalms', 3)
    assert list(annos) == ['1']
    assert annotations.get_annotations('KJVA', 'Psalms', 3)['0']


def test_the_last_line_of_a_longer_chapter_round_trips(
        isolated, offset_by_a_superscription):
    """This psalter renders nine lines where the KJV renders eight. The
    outward map is built from what the module renders for exactly this
    verse: a count taken from app space would stop at eight and strand it."""
    annotations.save_highlight('SuperscribedPsalter', 'Psalms', 3, 9, '#ffff00')
    assert list(annotations._load()['Psalms/3']) == ['8']
    assert list(annotations.get_annotations(
        'SuperscribedPsalter', 'Psalms', 3)) == ['9']


def test_two_modules_on_the_same_line_do_not_collide(
        isolated, offset_by_a_superscription):
    """Highlight the first rendered line of Psalm 3 in each: they are two
    different verses and must stay two rows, not one label over both."""
    annotations.save_highlight('KJVA', 'Psalms', 3, 1, '#ffff00')
    annotations.save_highlight('SuperscribedPsalter', 'Psalms', 3, 1, '#ffff00')
    refs = {(e['book'], e['chapter'], e['verse'])
            for e in annotations_window._all_entries()}
    assert len(refs) == 2, refs


def test_the_sort_orders_by_the_app_space_verse(
        isolated, offset_by_a_superscription):
    """Module verse 1 is app verse 0, so it sorts above the KJV's verse 1
    rather than beside it."""
    annotations.save_highlight('KJVA', 'Psalms', 3, 1, '#ffff00')
    annotations.save_highlight('SuperscribedPsalter', 'Psalms', 3, 1, '#ffff00')
    assert [e['verse'] for e in annotations_window._all_entries()] == [0, 1]


def test_delete_reaches_the_verse_the_module_is_showing(
        isolated, offset_by_a_superscription):
    annotations.save_highlight('SuperscribedPsalter', 'Psalms', 3, 1, '#ffff00')
    assert annotations.delete_annotation(
        'SuperscribedPsalter', 'Psalms', 3, 1) is not None
    assert annotations.get_annotations('KJVA', 'Psalms', 3) == {}


def test_a_chapter_note_carries_no_verse_either_way(
        isolated, offset_by_a_superscription):
    annotations.save_chapter_note('SuperscribedPsalter', 'Psalms', 3, 'a thought')
    e = _only_entry()
    assert e['is_chapter_note'] is True
    assert e['verse'] is None


def test_every_entry_the_builder_makes_carries_a_verse_key(isolated):
    """A field the display and the jump both read must never be absent —
    a KeyError here is a blank list."""
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    annotations.save_note('KJVA', 'John', 3, 16, 'a note')
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'a thought')
    entries = annotations_window._all_entries()
    assert len(entries) == 3
    for e in entries:
        assert 'verse' in e, e


# ── Timestamps ───────────────────────────────────────────────────────────────

def test_a_written_mark_records_when(isolated):
    annotations.save_note('KJVA', 'John', 3, 16, 'so loved')
    entry = annotations._load()['John/3']['16']
    assert entry['created'] and entry['modified']
    assert annotations_window._all_entries()[0]['modified'] == entry['modified']


def test_editing_moves_modified_and_leaves_created(isolated):
    annotations.save_note('KJVA', 'John', 3, 16, 'first')
    created = annotations._load()['John/3']['16']['created']
    annotations._load()['John/3']['16']['modified'] = '2000-01-01T00:00:00+00:00'
    annotations.save_note('KJVA', 'John', 3, 16, 'second')
    entry = annotations._load()['John/3']['16']
    assert entry['created'] == created
    assert entry['modified'] > '2000-01-01T00:00:00+00:00'


def test_a_chapter_note_is_dated_too(isolated):
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'a thought')
    assert annotations._load()['Psalms/23']['chapter_note']['modified']


def test_an_undated_mark_sorts_last_not_first(isolated):
    """Marks made before the store kept dates have none, and must not be
    ordered as if they were made in 1970."""
    annotations.save_note('KJVA', 'John', 3, 16, 'dated')
    data = annotations._load()
    data['Genesis/1'] = {'1': {'note': 'undated'}}
    annotations._save(data)
    entries = sorted(annotations_window._all_entries(),
                     key=lambda e: (e.get('modified') or e.get('created') or ''),
                     reverse=True)
    assert [e['note'] for e in entries] == ['dated', 'undated']


# ── Migration off the module-keyed store ─────────────────────────────────────

def _write_v1(path, payload):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f)


def test_a_module_keyed_store_migrates_on_load(isolated,
                                               offset_by_a_superscription):
    _write_v1(annotations.ANNOTATIONS_FILE, {
        'KJVA/John/3': {'16': {'note': 'so loved', 'tags': ['grace']}},
        'SuperscribedPsalter/Psalms/3': {'1': {'highlight': '#ffff00'}},
    })
    data = annotations._load()
    assert sorted(data) == ['John/3', 'Psalms/3']
    assert data['John/3']['16']['note'] == 'so loved'
    assert list(data['Psalms/3']) == ['0'], 'the psalter verse moved to app space'


def test_the_pre_migration_file_is_kept(isolated):
    _write_v1(annotations.ANNOTATIONS_FILE,
              {'KJVA/John/3': {'16': {'note': 'so loved'}}})
    annotations._load()
    with open(annotations.ANNOTATIONS_FILE + '.v1.bak', encoding='utf-8') as f:
        assert 'KJVA/John/3' in json.load(f)


def test_two_modules_marking_one_verse_merge_losslessly(isolated):
    _write_v1(annotations.ANNOTATIONS_FILE, {
        'KJVA/John/3': {'16': {'highlight': '#ffff00', 'note': 'so loved',
                               'tags': ['grace']}},
        'SpaRV/John/3': {'16': {'underline': True, 'note': 'de tal manera',
                                'tags': ['gracia', 'grace']}},
    })
    entry = annotations._load()['John/3']['16']
    assert entry['highlight'] == '#ffff00'
    assert entry['underline'] is True
    assert entry['note'] == 'so loved\n\nde tal manera'
    assert entry['tags'] == ['grace', 'gracia']


def test_migration_is_idempotent(isolated):
    _write_v1(annotations.ANNOTATIONS_FILE,
              {'KJVA/John/3': {'16': {'note': 'so loved'}}})
    first = dict(annotations._load())
    annotations._cache = None
    assert dict(annotations._load()) == first


def test_a_backup_written_before_the_migration_restores(isolated):
    """`replace_all` bypasses the load path, so it has to migrate too or an
    old study-data backup restores into a store the app cannot read."""
    annotations.replace_all({'KJVA/John/3': {'16': {'note': 'so loved'}}})
    assert annotations.get_annotations('SpaRV', 'John', 3)['16']['note'] \
        == 'so loved'


# ── Against the real tables ──────────────────────────────────────────────────

@pytest.mark.skipif(
    sword_bridge._module_v11n('RusSynodal') != 'Synodal',
    reason='RusSynodal not installed')
def test_a_real_synodal_psalter_numbers_the_superscription(isolated):
    """Its verse 1 is «Псалом Давида, когда он бежал от Авессалома» — the
    superscription, which the KJV does not number. This is the case the
    fake above stands for, measured against the real mapping tables."""
    annotations.save_highlight('RusSynodal', 'Psalms', 3, 1, '#ffff00')
    assert list(annotations._load()['Psalms/3']) == ['0']
    assert list(annotations.get_annotations('RusSynodal', 'Psalms', 3)) == ['1']


def test_the_public_inverse_reaches_a_superscription(
        isolated, offset_by_a_superscription):
    """window.py and the detail pane hold app-space verses now. They must go
    through annotations.module_verse, not sword_bridge.map_target_verse: that
    one maps through a KJV VerseKey, which has no verse 0, so app verse 0
    comes back unchanged and the pane repaints the wrong line."""
    assert annotations.module_verse(
        'SuperscribedPsalter', 'Psalms', 3, 0) == 1
    assert sword_bridge.map_target_verse(
        'SuperscribedPsalter', 'Psalms', 3, 0) == 1, \
        'the fake inverts cleanly; the real tables are what cannot'
    assert annotations.module_verse('KJVA', 'Psalms', 3, 1) == 1


@pytest.mark.skipif(
    sword_bridge._module_v11n('RusSynodal') != 'Synodal',
    reason='RusSynodal not installed')
def test_the_real_tables_cannot_map_verse_zero_back(isolated):
    """The measurement behind module_verse. Against the real Synodal tables
    map_target_verse hands app verse 0 straight back; the inverted map does
    not."""
    assert sword_bridge.map_target_verse('RusSynodal', 'Psalms', 3, 0) == 0
    assert annotations.module_verse('RusSynodal', 'Psalms', 3, 0) == 1


# ── The window keeps what is open when the list is rebuilt ───────────────────

def test_a_re_sort_does_not_close_the_open_entry(isolated, display):
    """Reordering the list is not a change of what you are reading. Emptying
    the list emits row-selected(None), which used to drop the open entry and
    put the detail pane back to "No entry selected"."""
    import annotations_window
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'first')
    annotations.save_note('KJVA', 'John', 3, 16, 'second')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        row = win._list.get_first_child()
        while row is not None and not hasattr(row, '_entry'):
            row = row.get_next_sibling()
        win._list.select_row(row)
        open_key = annotations_window._entry_key(win._current_entry)
        assert win._detail_stack.get_visible_child_name() == 'editor'

        win._sort_drop.set_selected(1)   # Recently edited

        assert win._detail_stack.get_visible_child_name() == 'editor'
        assert annotations_window._entry_key(win._current_entry) == open_key
    finally:
        win.destroy()


def test_a_filter_that_excludes_the_open_entry_still_clears_it(
        isolated, display):
    import annotations_window
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'a note')
    annotations.save_highlight('KJVA', 'John', 3, 16, '#ffff00')
    win = annotations_window.AnnotationsWindow(on_navigate=lambda *a: None)
    try:
        row = win._list.get_first_child()
        while row is not None and not hasattr(row, '_entry'):
            row = row.get_next_sibling()
        win._list.select_row(row)          # Genesis 1:1, a note
        assert win._detail_stack.get_visible_child_name() == 'editor'

        win._type_drop.set_selected(2)     # Highlights only — Genesis drops out

        assert win._detail_stack.get_visible_child_name() == 'empty'
        assert win._current_entry is None
    finally:
        win.destroy()


# ── Which translation the quotation is set in ────────────────────────────
#
# A mark belongs to a place in Scripture, so the words it is quoted with
# follow the language the reader has the app in rather than whichever pane
# happens to be open — which quoted a Russian reader's note back at them in
# the English text beside it.

def _library(monkeypatch, lang, sword=(), ebible=()):
    monkeypatch.setattr(annotations_window, 'current_language', lambda: lang)
    monkeypatch.setattr(annotations_window.sword_bridge, 'module_names',
                        lambda: list(sword))
    monkeypatch.setattr(annotations_window.ebible_bridge, 'installed_ids',
                        lambda: set(ebible))


@pytest.mark.parametrize('lang, opener', [
    ('en', 'BSB'), ('es', 'NBLA'), ('ru', 'RusOpenBible')])
def test_each_language_quotes_what_its_welcome_bundle_opens_on(
        lang, opener, monkeypatch):
    _library(monkeypatch, lang, sword=['ACV', 'BSB', 'NBLA', 'RusOpenBible'])
    assert annotations_window.quote_module() == opener


def test_a_reader_without_the_first_choice_gets_the_next_one(monkeypatch):
    """The Russian bundle installs the Open Bible, but a reader who declined
    it and fetched a Synodal from CrossWire must still be quoted in Russian."""
    _library(monkeypatch, 'ru', sword=['ASV', 'RusSynodal'])
    assert annotations_window.quote_module() == 'RusSynodal'


def test_the_chain_reaches_an_ebible_import(monkeypatch):
    """A reader whose only Spanish text came from eBible, not CrossWire."""
    _library(monkeypatch, 'es', sword=['ASV'],
             ebible={'spaRV1909', 'engwebp'})
    assert annotations_window.quote_module() == 'eBible: spaRV1909'


def test_nothing_installed_in_the_language_defers_to_the_reading_module(
        monkeypatch):
    _library(monkeypatch, 'ru', sword=['ASV'], ebible={'eng-asv'})
    assert annotations_window.quote_module() is None


def test_a_language_with_no_list_defers_to_the_reading_module(monkeypatch):
    """The fourth translation to ship must read as unfinished, not as English:
    no entry means quote whatever the reader has open."""
    _library(monkeypatch, 'de', sword=['BSB'])
    assert annotations_window.quote_module() is None


def test_a_verse_the_preferred_module_cannot_render_falls_back(
        isolated, monkeypatch, display):
    """BSB carries no deuterocanon. A note on Sirach must not come up blank
    while the reader can plainly see the words in the pane behind it."""
    annotations.save_note('KJVA', 'Sirach', 1, 1, 'a note')
    monkeypatch.setattr(annotations_window, 'quote_module', lambda: 'BSB')
    asked = []

    def quote(module, book, chapter, verse):
        asked.append(module)
        return '' if module == 'BSB' else 'All wisdom cometh from the Lord'

    monkeypatch.setattr(annotations_window, 'verse_quote', quote)
    win = annotations_window.AnnotationsWindow(
        on_navigate=lambda *a: None, reading_module=lambda: 'KJVA')
    try:
        row = win._list.get_first_child()
        while row is not None and not hasattr(row, '_entry'):
            row = row.get_next_sibling()
        win._list.select_row(row)
        assert asked == ['BSB', 'KJVA']
        assert win._verse_label.get_visible()
        assert 'wisdom' in win._verse_label.get_text()
    finally:
        win.destroy()


def test_the_reading_module_is_not_asked_twice(isolated, monkeypatch,
                                               display):
    """When the preferred module IS the one in the pane, and it renders
    nothing, one miss is one miss — not two."""
    annotations.save_note('KJVA', 'Genesis', 1, 1, 'a note')
    monkeypatch.setattr(annotations_window, 'quote_module', lambda: 'KJVA')
    asked = []
    monkeypatch.setattr(annotations_window, 'verse_quote',
                        lambda m, b, c, v: asked.append(m) or '')
    win = annotations_window.AnnotationsWindow(
        on_navigate=lambda *a: None, reading_module=lambda: 'KJVA')
    try:
        row = win._list.get_first_child()
        while row is not None and not hasattr(row, '_entry'):
            row = row.get_next_sibling()
        win._list.select_row(row)
        assert asked == ['KJVA']
        assert not win._verse_label.get_visible()
    finally:
        win.destroy()
