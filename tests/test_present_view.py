"""The projected reference follows the verses actually on the slide."""
import pytest
import types
from gi.repository import Gdk, Gtk

from present import PresentView
import present_mode
import sword_bridge


@pytest.fixture
def view():
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds real widgets')
    return PresentView()


def test_parallel_reference_tracks_steps_and_keeps_missing_verses_as_gaps(view):
    view.load_chapter('John', 3, 'King James Version',
                      [(16, 'First'), (18, 'Second'), (19, 'Third')],
                      secondary=('Berean Standard Bible', [(18, 'Other')]),
                      abbreviation='KJV', secondary_abbreviation='BSB')
    view.set_parallel(True)
    assert view._parallel_ref.get_text() == 'John 3:16, 18–19   ·   John 3:18'
    assert view._version_a.get_text() == 'KJV'
    assert view._version_b.get_text() == 'BSB'
    view.set_verse_at_a_time(True)
    assert view._parallel_ref.get_text() == 'John 3:16'
    view.step_next()
    assert view._parallel_ref.get_text() == 'John 3:18'
    view.set_show_numbers(False)
    assert view._parallel_ref.get_text() == 'John 3:18'
    assert [view._grid.get_child_at(column, 0).get_text()
            for column in (0, 1)] == ['Second', 'Other']
    view.set_parallel(False)
    assert not view._parallel_header.get_visible()
    assert not view._parallel_divider.get_visible()
    assert view._eyebrow.get_visible()
    assert 'King James Version' in view._eyebrow.get_text()


def test_reference_updates_when_parallel_loads_another_chapter(view):
    view.set_verse_at_a_time(True)
    for chapter, verses in [(3, [(16, 'First')]), (4, [(5, 'Second')])]:
        view.load_chapter('John', chapter, 'King James Version', verses,
                          secondary=('Berean Standard Bible', verses))
        view.set_parallel(True)
        assert view._parallel_ref.get_text() == f'John {chapter}:{verses[0][0]}'
    # A chapter with no secondary collapses the layout. A later secondary
    # restores its width even when the parallel intent is already on.
    view.load_chapter('John', 5, 'King James Version', [(1, 'First')])
    assert not view._parallel_header.get_visible()
    assert view._clamp.get_maximum_size() == 1100
    view.load_chapter('John', 6, 'King James Version', [(1, 'First')],
                      secondary=('Berean Standard Bible', [(1, 'Other')]))
    assert view._parallel_header.get_visible()
    assert view._clamp.get_maximum_size() == 1700


@pytest.fixture
def mapped_numbers(monkeypatch):
    # Real engine tables, independent of which modules CI has installed.
    monkeypatch.setattr(sword_bridge, '_module_v11n',
                        lambda m: {'FakeSynodal': 'Synodal',
                                   'RusSynodal': 'Synodal',
                                   'eBible: test-synodal': 'Synodal',
                                   'FakeVulg': 'Vulg'}.get(m))
    monkeypatch.setattr(sword_bridge, '_book_maps', {})
    monkeypatch.setattr(sword_bridge, '_line_maps', {})


@pytest.mark.parametrize('module', ['FakeSynodal', 'FakeVulg',
                                    'eBible: test-synodal'])
def test_numbered_titles_stay_separate_and_parallel_rows_match(
        view, mapped_numbers, module):
    view.set_verse_at_a_time(True)
    view.load_chapter('Psalms', 3, 'Mapped',
                      [(1, 'Title'), (2, 'Lord'), (3, 'Many')],
                      secondary=('KJV', [(1, 'Lord'), (2, 'Many')]),
                      module=module, secondary_module='FakeKJV', focus_verse=1)
    view.set_parallel(True)
    assert view._current_verse_number() == 0
    assert view._grid.get_child_at(0, 0).get_text() == '1 Title'
    assert view._grid.get_child_at(1, 0).get_text() == ''
    view.step_next()
    assert view._current_verse_number() == 1
    assert view._grid.get_child_at(0, 0).get_text() == '2 Lord'
    assert view._grid.get_child_at(1, 0).get_text() == '1 Lord'
    assert view._parallel_ref.get_text() == 'Psalms 3:2   ·   Psalms 3:1'
    view.set_parallel(False)
    assert view._text.get_text() == '2 Lord'
    assert view._eyebrow.get_text().startswith('Psalms 3:2')


@pytest.mark.parametrize('module, chapter, source, target, printed', [
    ('FakeSynodal', 3, [(1, 'Title'), (2, 'First'), (3, 'Target')], 2, (3, 3)),
    ('FakeVulg', 3, [(1, 'Title'), (2, 'First'), (3, 'Target')], 2, (3, 3)),
    ('FakeVulg', 10, [(22, 'First'), (23, 'Target')], 2, (9, 23)),
    ('FakeVulg', 116, [(9, 'First'), (10, 'Target')], 10, (115, 1)),
    ('FakeSynodal', 23, [(1, 'Target'), (2, 'Second')], 1, (22, 1)),
    ('FakeSynodal', 13, [(1, 'Title'), (2, 'First'), (6, 'Target')], 6, (12, 6)),
    ('FakeVulg', 16, [(10, 'First'), (11, 'Target')], 11, (15, 11)),
])
def test_jump_maps_the_app_reference_and_prints_the_module_reference(
        view, mapped_numbers, module, chapter, source, target, printed):
    view.set_verse_at_a_time(True)
    controller = present_mode.PresentController(
        types.SimpleNamespace(_present_view=view))
    controller._present_mode = True
    controller._present_module = module
    controller._present_module_b = None
    controller._present_bilingual = False
    controller._present_load_finish('Psalms', chapter, source, 'Mapped',
                                    None, 'first', target, False)
    assert view._current_verse_number() == view._app_aliases.get(target, target)
    assert view._text.get_text() == f'{printed[1]} Target'
    assert view._eyebrow.get_text().startswith(
        f'Psalms {printed[0]}:{printed[1]}   ·')


def test_a_split_chapter_caption_names_both_printed_chapters(view, mapped_numbers):
    view.load_chapter('Psalms', 116, 'Vulgate', [(9, 'First'), (10, 'Tail')],
                      secondary=('KJV', [(9, 'First'), (10, 'Tail')]),
                      module='FakeVulg', secondary_module='FakeKJV')
    view.set_parallel(True)
    assert view._parallel_ref.get_text() == (
        'Psalms 114:9; Psalms 115:1   ·   Psalms 116:9–10')


def test_a_combined_translation_verse_keeps_both_primary_verses_together(
        view, mapped_numbers):
    view.set_verse_at_a_time(True)
    view.load_chapter('Psalms', 13, 'KJV', [(5, 'Rejoice'), (6, 'Sing')],
                      module='FakeKJV',
                      secondary=('Synodal', [(6, 'Rejoice and sing')]),
                      secondary_module='FakeSynodal', focus_app_verse=6)
    view.set_parallel(True)
    assert view._grid.get_child_at(0, 0).get_text() == '5 Rejoice\n6 Sing'
    assert view._grid.get_child_at(1, 0).get_text() == '6 Rejoice and sing'
    assert view._parallel_ref.get_text() == 'Psalms 13:5–6   ·   Psalms 12:6'
    view.set_parallel(False)
    assert view._text.get_text() == '5 Rejoice'
    view.step_next()
    assert view._text.get_text() == '6 Sing'


def test_synodal_final_combined_line_does_not_target_its_empty_engine_slot(
        view, mapped_numbers):
    view.set_verse_at_a_time(True)
    view.load_chapter('Psalms', 116, 'Synodal',
                      [(8, 'Delivered; walk before the Lord'), (9, '')],
                      module='RusSynodal', focus_app_verse=9,
                      secondary=('KJV', [(8, 'Delivered'), (9, 'Walk')]),
                      secondary_module='FakeKJV')
    view.set_parallel(True)
    assert view._current_verse_number() == 8
    assert view._grid.get_child_at(0, 0).get_text() == (
        '8 Delivered; walk before the Lord')
    assert view._grid.get_child_at(1, 0).get_text() == '8 Delivered\n9 Walk'
    assert view._parallel_ref.get_text() == 'Psalms 114:8   ·   Psalms 116:8–9'


def test_superscription_is_projected_above_its_verse(view):
    """Scripture with no number of its own: it rides with the verse it stands
    above, in italics, so verse-at-a-time puts it on that verse's slide."""
    view.load_chapter('Psalms', 51, 'King James Version',
                      [(1, 'Have mercy upon me'), (2, 'Wash me')])
    view._titles = {1: ['To the chief Musician, A Psalm of David.']}
    first = view._verse_markup(1, 'Have mercy upon me', False)
    assert first.index('To the chief Musician') < first.index('Have mercy')
    assert 'style="italic"' in first
    assert 'Musician' not in view._verse_markup(2, 'Wash me', False)


def test_each_translation_projects_its_own_superscription(view):
    view.load_chapter('Psalms', 51, 'King James Version', [(1, 'Have mercy')],
                      secondary=('Berean Standard Bible', [(1, 'Have mercy on me')]))
    view._titles = {1: ['To the chief Musician.']}
    view._titles_b = {1: ['For the choirmaster.']}
    assert 'choirmaster' in view._verse_markup(1, 'Have mercy on me', False,
                                               secondary=True)
    assert 'choirmaster' not in view._verse_markup(1, 'Have mercy', False)
