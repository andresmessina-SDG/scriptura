"""Tests for settings.py — JSON-backed key/value store with debounced
write + synchronous flush(). Pure-Python; no GTK / SWORD."""

import json

import pytest

import settings


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect _FILE and reset module-level state. Also force any
    in-flight debounce timer from a previous test to stop."""
    if settings._save_timer is not None:
        settings._save_timer.cancel()
    monkeypatch.setattr(settings, '_FILE', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(settings, '_cache', None)
    monkeypatch.setattr(settings, '_load_failed', False)
    monkeypatch.setattr(settings, '_save_timer', None)
    yield tmp_path
    # Teardown: kill any timer the test started so it can't write to the
    # tmp_path after pytest has cleaned it up.
    if settings._save_timer is not None:
        settings._save_timer.cancel()


# ── Defaults ────────────────────────────────────────────────────────────────

def test_get_unset_returns_default(isolated):
    assert settings.get('font_size') == 12.5
    assert settings.get('font_family') == 'serif'
    assert settings.get('split_pane_mode') is True


def test_get_unknown_key_returns_none(isolated):
    assert settings.get('not_a_real_setting') is None


def test_defaults_dont_pollute_cache(isolated):
    """Reading a default value must not insert it into the on-disk file."""
    settings.get('font_size')
    settings.flush()  # writes whatever's in the cache
    saved = json.loads((isolated / 'settings.json').read_text())
    assert 'font_size' not in saved


# ── put / get round-trip via flush() ────────────────────────────────────────

def test_put_then_get(isolated):
    settings.put('font_size', 16.0)
    assert settings.get('font_size') == 16.0


def test_put_overrides_default(isolated):
    assert settings.get('reading_width') == 720  # default
    settings.put('reading_width', 900)
    assert settings.get('reading_width') == 900


def test_flush_writes_to_disk(isolated):
    settings.put('font_family', 'monospace')
    settings.flush()
    saved = json.loads((isolated / 'settings.json').read_text())
    assert saved['font_family'] == 'monospace'


def test_flush_with_no_changes_writes_empty_object(isolated):
    """Even with no put() calls, flush() materialises the (empty) cache.
    This is fine — the file just contains {} and reads back as such."""
    settings.flush()
    saved = json.loads((isolated / 'settings.json').read_text())
    assert saved == {}


def test_put_preserves_types(isolated):
    settings.put('an_int', 42)
    settings.put('a_float', 3.14)
    settings.put('a_bool', True)
    settings.put('a_list', [1, 2, 3])
    settings.put('a_dict', {'a': 1})
    settings.put('a_none', None)
    settings.flush()

    # Reload from disk.
    settings._cache = None
    assert settings.get('an_int') == 42
    assert settings.get('a_float') == 3.14
    assert settings.get('a_bool') is True
    assert settings.get('a_list') == [1, 2, 3]
    assert settings.get('a_dict') == {'a': 1}
    assert settings.get('a_none') is None


# ── Debounce coalescing ─────────────────────────────────────────────────────

def test_burst_of_puts_writes_once(isolated):
    """The debounce timer should coalesce many puts into a single write
    when followed by flush(). The pre-flush file shouldn't exist."""
    for size in range(10, 20):
        settings.put('font_size', float(size))
    # No flush yet — debounce timer is pending, no write should have
    # landed at the synchronous level.
    assert not (isolated / 'settings.json').exists()
    settings.flush()
    saved = json.loads((isolated / 'settings.json').read_text())
    assert saved['font_size'] == 19.0  # last value wins


def test_flush_cancels_pending_debounce(isolated):
    settings.put('font_size', 15.0)
    assert settings._save_timer is not None
    settings.flush()
    assert settings._save_timer is None


# ── Load from existing file ─────────────────────────────────────────────────

def test_load_existing_file(isolated):
    (isolated / 'settings.json').write_text(
        json.dumps({'font_size': 18.0, 'font_family': 'sans-serif'}))
    assert settings.get('font_size') == 18.0
    assert settings.get('font_family') == 'sans-serif'
    # Defaults still apply for keys not in the file.
    assert settings.get('split_pane_mode') is True


def test_no_file_no_error(isolated):
    # First get() loads with no file present — should fall back cleanly.
    assert settings.get('font_size') == 12.5
    assert settings.load_failed() is False


# ── Corrupt-file recovery ───────────────────────────────────────────────────

def test_corrupt_json_falls_back_to_defaults(isolated):
    (isolated / 'settings.json').write_text('this is not json')
    assert settings.get('font_size') == 12.5
    assert settings.load_failed() is True


def test_non_dict_top_level_falls_back_to_defaults(isolated):
    (isolated / 'settings.json').write_text('["a", "b"]')
    assert settings.get('font_size') == 12.5
    assert settings.load_failed() is True


def test_load_failed_attempts_load_first(isolated):
    (isolated / 'settings.json').write_text('garbage')
    # Don't trigger a get() — load_failed() must trigger the load itself.
    assert settings.load_failed() is True


# ── Atomic write ────────────────────────────────────────────────────────────

def test_flush_does_not_leave_tmp_file(isolated):
    settings.put('font_size', 14.0)
    settings.flush()
    assert not (isolated / 'settings.json.tmp').exists()


def test_flush_is_idempotent(isolated):
    settings.put('font_size', 14.0)
    settings.flush()
    settings.flush()  # second call with empty queue should be a no-op write
    saved = json.loads((isolated / 'settings.json').read_text())
    assert saved['font_size'] == 14.0


# ── UTF-8 preservation ─────────────────────────────────────────────────────

def test_non_ascii_values_preserved(isolated):
    settings.put('last_book', 'Génesis')
    settings.flush()
    content = (isolated / 'settings.json').read_text(encoding='utf-8')
    assert 'Génesis' in content
