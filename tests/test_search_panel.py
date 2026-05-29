"""Tests for the pure search-history helpers in search_panel.py — save,
load, per-entry delete, clear, dedupe, and the size cap. _HISTORY_FILE is
redirected to a tmp file per test; no GTK widgets are constructed."""

import pytest

import search_panel


@pytest.fixture(autouse=True)
def tmp_history(tmp_path, monkeypatch):
    monkeypatch.setattr(search_panel, '_HISTORY_FILE', str(tmp_path / 'history.json'))


def test_save_and_load_roundtrip():
    search_panel._save_history('grace', 'KJV')
    assert search_panel._load_history() == [{'query': 'grace', 'module': 'KJV'}]


def test_most_recent_first():
    search_panel._save_history('a', 'KJV')
    search_panel._save_history('b', 'KJV')
    assert [e['query'] for e in search_panel._load_history()] == ['b', 'a']


def test_dedupe_moves_to_front():
    search_panel._save_history('a', 'KJV')
    search_panel._save_history('b', 'KJV')
    search_panel._save_history('a', 'KJV')
    hist = search_panel._load_history()
    assert [e['query'] for e in hist] == ['a', 'b']
    assert len(hist) == 2


def test_cap_at_max():
    for i in range(search_panel._HISTORY_MAX + 5):
        search_panel._save_history(f'q{i}', 'KJV')
    assert len(search_panel._load_history()) == search_panel._HISTORY_MAX


def test_delete_one_entry():
    search_panel._save_history('a', 'KJV')
    search_panel._save_history('b', 'KJV')
    search_panel._delete_history({'query': 'a', 'module': 'KJV'})
    assert [e['query'] for e in search_panel._load_history()] == ['b']


def test_delete_only_matches_same_module():
    search_panel._save_history('a', 'KJV')
    search_panel._save_history('a', 'ESV')
    search_panel._delete_history({'query': 'a', 'module': 'KJV'})
    assert search_panel._load_history() == [{'query': 'a', 'module': 'ESV'}]


def test_clear_history():
    search_panel._save_history('a', 'KJV')
    search_panel._save_history('b', 'KJV')
    search_panel._clear_history()
    assert search_panel._load_history() == []
