"""Tests for module_positions.py — per-module scroll/entry-path memory
shared across panes. Pure-Python persistence; no GTK or SWORD deps."""

import json
import time

import pytest

import module_positions


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect the module_positions file to a temp path, reset state,
    cancel any pending debounce timer between tests."""
    monkeypatch.setattr(module_positions, '_FILE',
                        str(tmp_path / 'module_positions.json'))
    monkeypatch.setattr(module_positions, '_state', {})
    # Cancel any timer left by an earlier test so it can't fire mid-test
    if module_positions._save_timer is not None:
        module_positions._save_timer.cancel()
        monkeypatch.setattr(module_positions, '_save_timer', None)
    yield tmp_path
    # Same cleanup on exit
    if module_positions._save_timer is not None:
        module_positions._save_timer.cancel()
        monkeypatch.setattr(module_positions, '_save_timer', None)


# ── Round-trip ───────────────────────────────────────────────────────────────

def test_verse_position_roundtrip(isolated):
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    module_positions.flush()
    assert module_positions.get_verse_position('BSB', 'Psalms', 107) == 5


def test_genbook_path_roundtrip(isolated):
    module_positions.remember_genbook_path('Concord', '/Title_Page')
    module_positions.flush()
    assert module_positions.get_genbook_path('Concord') == '/Title_Page'


# ── Chapter / book scoping ──────────────────────────────────────────────────

def test_verse_position_returns_none_for_different_chapter(isolated):
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    module_positions.flush()
    assert module_positions.get_verse_position('BSB', 'Psalms', 23) is None


def test_verse_position_returns_none_for_different_book(isolated):
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    module_positions.flush()
    assert module_positions.get_verse_position('BSB', 'Genesis', 107) is None


# ── Kind discrimination ─────────────────────────────────────────────────────

def test_get_genbook_returns_none_for_verse_kind(isolated):
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    module_positions.flush()
    assert module_positions.get_genbook_path('BSB') is None


def test_get_verse_returns_none_for_genbook_kind(isolated):
    module_positions.remember_genbook_path('Concord', '/Title_Page')
    module_positions.flush()
    assert module_positions.get_verse_position('Concord', 'Psalms', 107) is None


# ── Bad input handling ──────────────────────────────────────────────────────

def test_remember_with_falsy_args_is_noop(isolated):
    module_positions.remember_verse_position('', 'Psalms', 107, 5)
    module_positions.remember_verse_position('BSB', '', 107, 5)
    module_positions.remember_verse_position('BSB', 'Psalms', 0, 5)
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 0)
    module_positions.remember_genbook_path('', '/Foo')
    module_positions.remember_genbook_path('Concord', '')
    module_positions.flush()
    # Nothing should have been saved
    assert module_positions._state == {}


# ── Legacy data recovery (the bug that motivated this test file) ────────────

def test_legacy_char_list_genbook_path_recovers(isolated):
    """Earlier versions had a `list(path)` call that decomposed
    '/Title_Page' into ['/', 'T', 'i', ...]. Tolerate that shape
    by joining the chars back into a string on read."""
    module_positions._state['Concord'] = {
        'kind': 'genbook',
        'genbook_path': list('/Title_Page'),
    }
    assert module_positions.get_genbook_path('Concord') == '/Title_Page'


def test_legacy_recovery_doesnt_fire_on_multichar_list(isolated):
    """Defensive — a real list of segments (each > 1 char) is not
    the corrupted shape and shouldn't be joined back as if it were."""
    module_positions._state['Weird'] = {
        'kind': 'genbook',
        'genbook_path': ['Section', 'Sub'],
    }
    # Not the corrupted shape; falls through to the isinstance(p, str)
    # check, which fails (it's still a list). Returns None.
    assert module_positions.get_genbook_path('Weird') is None


# ── Debounce + flush behaviour ──────────────────────────────────────────────

def test_debounced_save_eventually_lands(isolated):
    """A remember_*() call schedules a save via the 500ms debounce
    timer. Wait past the window and confirm the disk file appears."""
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    # File shouldn't exist yet — save is debounced
    assert not isolated.joinpath('module_positions.json').exists()
    # Wait past the debounce window
    time.sleep(0.6)
    assert isolated.joinpath('module_positions.json').exists()
    with open(isolated / 'module_positions.json', encoding='utf-8') as f:
        data = json.load(f)
    assert data['BSB']['top_verse'] == 5


def test_flush_forces_immediate_write(isolated):
    """flush() cancels the debounce and writes synchronously."""
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    assert not isolated.joinpath('module_positions.json').exists()
    module_positions.flush()
    assert isolated.joinpath('module_positions.json').exists()
    with open(isolated / 'module_positions.json', encoding='utf-8') as f:
        data = json.load(f)
    assert data['BSB']['top_verse'] == 5


def test_debounce_coalesces_burst_into_one_write(isolated):
    """A pane swap fires two remember_*() in immediate succession.
    The debounce should coalesce both into a single disk write."""
    module_positions.remember_verse_position('BSB', 'Psalms', 107, 5)
    module_positions.remember_verse_position('LEB', 'Psalms', 107, 8)
    module_positions.flush()
    with open(isolated / 'module_positions.json', encoding='utf-8') as f:
        data = json.load(f)
    # Both modules should be persisted in the same file
    assert data['BSB']['top_verse'] == 5
    assert data['LEB']['top_verse'] == 8
