"""The reference a study-journal entry wears.

Annotations are keyed by module and store the verse number that module
RENDERS, which is what the write-backs need. That number is not a
reference: a Synodal or Vulgate psalter counts the superscription, so its
verse 1 is app-space verse 0. Everywhere an entry leaves its module — the
label, the sort, the jump — has to say app space or two different verses
wear the same reference.
"""
import pytest

import annotations
import study_journal


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    return tmp_path


def _entry(module):
    return next(e for e in study_journal._all_entries()
                if e['module'] == module)


def test_an_app_keyed_module_is_left_alone(isolated):
    annotations.save_highlight('KJVA', 'Psalms', 3, 1, '#ffff00')
    e = _entry('KJVA')
    assert e['verse'] == 1
    assert e['app_verse'] == 1


def test_a_synodal_psalter_reports_the_app_space_verse(isolated):
    """Its verse 1 is «Псалом Давида, когда он бежал от Авессалома» — the
    superscription, which the KJV does not number. Labelled "Psalms 3:1"
    it was indistinguishable from the KJV entry on the line below it."""
    annotations.save_highlight('RusSynodal', 'Psalms', 3, 1, '#ffff00')
    e = _entry('RusSynodal')
    assert e['verse'] == 1, 'the store stays keyed by what the module renders'
    assert e['app_verse'] == 0, 'the reference is app space'


def test_two_modules_on_the_same_line_do_not_collide(isolated):
    annotations.save_highlight('KJVA', 'Psalms', 3, 1, '#ffff00')
    annotations.save_highlight('RusSynodal', 'Psalms', 3, 1, '#ffff00')
    refs = {(e['book'], e['chapter'], e['app_verse'])
            for e in study_journal._all_entries()}
    assert len(refs) == 2, refs


def test_a_chapter_note_carries_no_verse_either_way(isolated):
    annotations.save_chapter_note('RusSynodal', 'Psalms', 3, 'a thought')
    e = _entry('RusSynodal')
    assert e['is_chapter_note'] is True
    assert e['verse'] is None and e['app_verse'] is None


def test_every_entry_the_builder_makes_carries_an_app_verse(isolated):
    """A field the display and the jump both read must never be absent —
    a KeyError here is a blank journal."""
    annotations.save_highlight('KJVA', 'Genesis', 1, 1, '#ffff00')
    annotations.save_note('KJVA', 'John', 3, 16, 'a note')
    annotations.save_chapter_note('KJVA', 'Psalms', 23, 'a thought')
    entries = study_journal._all_entries()
    assert len(entries) == 3
    for e in entries:
        assert 'app_verse' in e, e
