"""An unreadable store must be set aside, not overwritten.

Every JSON store here loads into a cache, falls back to an empty cache
when the parse fails, and later writes that cache back over the file. So
a corrupt read used to destroy the only copy of the user's data on the
next save — while the startup toast told them "your file is preserved".
These tests hold that promise to the fire.
"""

import json

import pytest

import annotations
import bookmarks
import module_positions
import paths
import reading_plans
import settings

CORRUPT = '{"font_size": 18}\n{"trailing": "garbage"}'


# ── The helper ──────────────────────────────────────────────────────────────

def test_quarantine_moves_the_file_aside(tmp_path):
    f = tmp_path / 'store.json'
    f.write_text(CORRUPT)
    dest = paths.quarantine_unreadable(str(f))
    assert dest == str(tmp_path / 'store.json.corrupt')
    assert not f.exists()
    assert (tmp_path / 'store.json.corrupt').read_text() == CORRUPT


def test_quarantine_does_not_clobber_an_earlier_corruption(tmp_path):
    (tmp_path / 'store.json.corrupt').write_text('the first one')
    f = tmp_path / 'store.json'
    f.write_text(CORRUPT)
    dest = paths.quarantine_unreadable(str(f))
    assert dest is not None
    assert dest != str(tmp_path / 'store.json.corrupt')
    assert (tmp_path / 'store.json.corrupt').read_text() == 'the first one'
    assert open(dest).read() == CORRUPT


def test_quarantine_of_a_missing_file_is_a_no_op(tmp_path):
    assert paths.quarantine_unreadable(str(tmp_path / 'nope.json')) is None


def test_quarantine_failure_is_survivable(tmp_path, monkeypatch):
    """Best-effort: if the move fails the app must still start."""
    f = tmp_path / 'store.json'
    f.write_text(CORRUPT)

    def boom(*a):
        raise OSError('read-only filesystem')

    monkeypatch.setattr(paths.os, 'replace', boom)
    assert paths.quarantine_unreadable(str(f)) is None
    assert f.read_text() == CORRUPT  # untouched


# ── Per-store: corrupt contents survive the next save ───────────────────────

def test_settings_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'settings.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(settings, '_FILE', str(f))
    monkeypatch.setattr(settings, '_cache', None)
    monkeypatch.setattr(settings, '_load_failed', False)
    monkeypatch.setattr(settings, '_save_timer', None)

    assert settings.get('font_size') == 12.5   # fell back to defaults
    assert settings.load_failed() is True
    settings.put('font_size', 20)
    settings.flush()                            # the write that used to destroy it

    assert (tmp_path / 'settings.json.corrupt').read_text() == CORRUPT
    assert json.loads(f.read_text())['font_size'] == 20
    if settings._save_timer is not None:
        settings._save_timer.cancel()


def test_annotations_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'annotations.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE', str(f))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_load_failed', False)

    assert annotations.load_failed() is True
    annotations.save_highlight('KJV', 'John', 3, 16, 'yellow')

    assert (tmp_path / 'annotations.json.corrupt').read_text() == CORRUPT


def test_bookmarks_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'bookmarks.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(bookmarks, '_FILE', str(f))
    monkeypatch.setattr(bookmarks, '_load_failed', False)

    assert bookmarks.load_failed() is True
    bookmarks.add('John', 3, 16)

    assert (tmp_path / 'bookmarks.json.corrupt').read_text() == CORRUPT


def test_reading_plans_corrupt_file_survives_a_later_save(tmp_path, monkeypatch):
    f = tmp_path / 'reading_plans.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(reading_plans, '_FILE', str(f))
    monkeypatch.setattr(reading_plans, '_cache', None)
    monkeypatch.setattr(reading_plans, '_load_failed', False)

    assert reading_plans.load_failed() is True

    assert (tmp_path / 'reading_plans.json.corrupt').read_text() == CORRUPT


def test_module_positions_corrupt_file_is_set_aside(tmp_path, monkeypatch):
    f = tmp_path / 'module_positions.json'
    f.write_text(CORRUPT)
    monkeypatch.setattr(module_positions, '_FILE', str(f))
    monkeypatch.setattr(module_positions, '_state', {})
    monkeypatch.setattr(module_positions, '_load_failed', False)

    module_positions._load()

    assert module_positions.load_failed() is True
    assert (tmp_path / 'module_positions.json.corrupt').read_text() == CORRUPT


# ── An unreadable file is not the same as an unparseable one ────────────────

@pytest.mark.parametrize('mod,attr', [
    (settings, '_FILE'),
    (bookmarks, '_FILE'),
    (reading_plans, '_FILE'),
])
def test_os_error_leaves_the_file_in_place(mod, attr, tmp_path, monkeypatch):
    """A permissions or I/O failure says nothing about the bytes. Moving
    the file there would quarantine a perfectly good store."""
    f = tmp_path / 'store.json'
    f.write_text('{"real": "data"}')
    monkeypatch.setattr(mod, attr, str(f))
    for name, value in (('_cache', None), ('_load_failed', False)):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)

    def boom(*a, **k):
        raise PermissionError('nope')

    monkeypatch.setattr('builtins.open', boom)
    mod._load()

    monkeypatch.undo()
    assert f.read_text() == '{"real": "data"}'
    assert not (tmp_path / 'store.json.corrupt').exists()
