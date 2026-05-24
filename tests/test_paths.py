"""Tests for paths.py — XDG base-dir resolution + one-shot legacy file
migration. Pure-Python; only touches the filesystem under tmp_path.

The legacy migration is the most consequential code path here: it runs
once per file on app startup for any user upgrading from a pre-XDG
build, and a bug means lost annotations / bookmarks / settings.
"""

import os
from types import SimpleNamespace

import pytest

import paths


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point XDG dirs and _LEGACY_DIR at tmp_path subdirs.

    GLib caches the user-dir lookups, so monkeypatching the env vars
    isn't enough — we patch the wrapper functions directly."""
    cfg = tmp_path / 'config'
    data = tmp_path / 'data'
    cache = tmp_path / 'cache'
    legacy = tmp_path / 'legacy'
    legacy.mkdir()

    monkeypatch.setattr(paths.GLib, 'get_user_config_dir', lambda: str(cfg))
    monkeypatch.setattr(paths.GLib, 'get_user_data_dir', lambda: str(data))
    monkeypatch.setattr(paths.GLib, 'get_user_cache_dir', lambda: str(cache))
    monkeypatch.setattr(paths, '_LEGACY_DIR', str(legacy))

    return SimpleNamespace(cfg=cfg, data=data, cache=cache, legacy=legacy)


# ── Base directories ─────────────────────────────────────────────────────────

def test_config_dir_created_with_app_subdir(isolated):
    p = paths.config_dir()
    assert p == str(isolated.cfg / 'bible-reader')
    assert os.path.isdir(p)


def test_data_dir_created_with_app_subdir(isolated):
    p = paths.data_dir()
    assert p == str(isolated.data / 'bible-reader')
    assert os.path.isdir(p)


def test_cache_dir_created_with_app_subdir(isolated):
    p = paths.cache_dir()
    assert p == str(isolated.cache / 'bible-reader')
    assert os.path.isdir(p)


def test_base_dirs_idempotent(isolated):
    # Calling twice doesn't fail (makedirs exist_ok=True).
    a = paths.config_dir()
    b = paths.config_dir()
    assert a == b


# ── _migrated_file: no legacy, no target ────────────────────────────────────

def test_settings_path_no_legacy_returns_xdg_path(isolated):
    p = paths.settings_path()
    assert p == str(isolated.cfg / 'bible-reader' / 'settings.json')
    # Nothing was created — _migrated_file only returns the resolved
    # location; the caller (settings.py) creates the file on first write.
    assert not os.path.exists(p)


# ── _migrated_file: legacy present, target missing → move ────────────────────

def test_legacy_file_is_migrated(isolated):
    legacy = isolated.legacy / 'settings.json'
    legacy.write_text('{"theme": "dark"}')

    target = paths.settings_path()

    assert not legacy.exists(), 'legacy file should have moved'
    assert os.path.isfile(target)
    assert open(target).read() == '{"theme": "dark"}'


def test_legacy_bookmarks_migrated(isolated):
    legacy = isolated.legacy / 'bookmarks.json'
    legacy.write_text('[]')
    target = paths.bookmarks_path()
    assert not legacy.exists()
    assert os.path.isfile(target)


# ── _migrated_file: both present → target wins, legacy untouched ─────────────

def test_existing_target_skips_migration(isolated):
    """If the user has both an XDG file (from a prior launch) and a stale
    legacy file (from a yet-earlier version), trust the XDG one and leave
    the legacy file alone — overwriting it could clobber newer data."""
    legacy = isolated.legacy / 'settings.json'
    legacy.write_text('{"legacy": true}')

    # Pre-populate the XDG location.
    cfg_app = isolated.cfg / 'bible-reader'
    cfg_app.mkdir(parents=True)
    target = cfg_app / 'settings.json'
    target.write_text('{"xdg": true}')

    result = paths.settings_path()
    assert result == str(target)
    assert legacy.exists(), 'legacy file should NOT have moved'
    assert open(result).read() == '{"xdg": true}'


# ── _migrated_file: failure is swallowed, path still returned ───────────────

def test_migration_failure_does_not_raise(isolated, monkeypatch):
    legacy = isolated.legacy / 'settings.json'
    legacy.write_text('original')

    def boom(*_a, **_kw):
        raise OSError('disk full')
    monkeypatch.setattr(paths.shutil, 'move', boom)

    # Should not raise; should still return the resolved target path.
    p = paths.settings_path()
    assert p == str(isolated.cfg / 'bible-reader' / 'settings.json')
    # Legacy is still there because the move failed.
    assert legacy.exists()


# ── ebible_db_path: sidecar (-shm / -wal) migration ──────────────────────────

def test_ebible_db_migrates_main_and_sidecars(isolated):
    for name, content in (('ebible.db', 'MAIN'),
                          ('ebible.db-shm', 'SHM'),
                          ('ebible.db-wal', 'WAL')):
        (isolated.legacy / name).write_text(content)

    target = paths.ebible_db_path()
    base = isolated.data / 'bible-reader'

    assert open(target).read() == 'MAIN'
    assert open(base / 'ebible.db-shm').read() == 'SHM'
    assert open(base / 'ebible.db-wal').read() == 'WAL'
    # All three legacy files gone.
    assert not (isolated.legacy / 'ebible.db').exists()
    assert not (isolated.legacy / 'ebible.db-shm').exists()
    assert not (isolated.legacy / 'ebible.db-wal').exists()


def test_ebible_db_sidecars_skipped_if_target_already_has_them(isolated):
    """If a sidecar already exists at the destination, don't overwrite —
    SQLite at the new location may already own it."""
    # Main DB lives only at legacy → it WILL be migrated.
    (isolated.legacy / 'ebible.db').write_text('LEGACY MAIN')
    (isolated.legacy / 'ebible.db-wal').write_text('LEGACY WAL')

    # Sidecar already present at target.
    base = isolated.data / 'bible-reader'
    base.mkdir(parents=True)
    (base / 'ebible.db-wal').write_text('TARGET WAL')

    paths.ebible_db_path()

    # Target sidecar unchanged.
    assert (base / 'ebible.db-wal').read_text() == 'TARGET WAL'
    # Legacy sidecar still there (skipped, not moved).
    assert (isolated.legacy / 'ebible.db-wal').exists()


def test_ebible_db_no_legacy_returns_path_without_creating_file(isolated):
    target = paths.ebible_db_path()
    assert target == str(isolated.data / 'bible-reader' / 'ebible.db')
    assert not os.path.exists(target)


def test_ebible_db_sidecar_move_failure_is_swallowed(isolated, monkeypatch):
    (isolated.legacy / 'ebible.db').write_text('M')
    (isolated.legacy / 'ebible.db-wal').write_text('W')

    real_move = paths.shutil.move

    def selective_boom(src, dst, *a, **kw):
        if src.endswith('-wal'):
            raise OSError('locked')
        return real_move(src, dst, *a, **kw)
    monkeypatch.setattr(paths.shutil, 'move', selective_boom)

    # Main DB still migrates; -wal failure is logged, not raised.
    target = paths.ebible_db_path()
    assert open(target).read() == 'M'
    assert (isolated.legacy / 'ebible.db-wal').exists()  # failed move left it


# ── open_data_dir: per-file migration ────────────────────────────────────────

def test_open_data_dir_created_even_with_no_legacy(isolated):
    d = paths.open_data_dir()
    assert d == str(isolated.data / 'bible-reader' / 'open_data')
    assert os.path.isdir(d)


def test_open_data_dir_migrates_individual_files(isolated):
    legacy_data = isolated.legacy / 'data'
    legacy_data.mkdir()
    (legacy_data / 'cross_references.txt').write_text('XR')
    (legacy_data / 'dodson.csv').write_text('DODSON')
    # topic-scores.txt deliberately absent.

    d = paths.open_data_dir()

    assert open(os.path.join(d, 'cross_references.txt')).read() == 'XR'
    assert open(os.path.join(d, 'dodson.csv')).read() == 'DODSON'
    assert not os.path.exists(os.path.join(d, 'topic-scores.txt'))
    # Legacy copies gone (the ones that existed).
    assert not (legacy_data / 'cross_references.txt').exists()
    assert not (legacy_data / 'dodson.csv').exists()


def test_open_data_dir_target_wins_over_legacy(isolated):
    legacy_data = isolated.legacy / 'data'
    legacy_data.mkdir()
    (legacy_data / 'dodson.csv').write_text('LEGACY')

    # Pre-populate target.
    target_dir = isolated.data / 'bible-reader' / 'open_data'
    target_dir.mkdir(parents=True)
    (target_dir / 'dodson.csv').write_text('TARGET')

    paths.open_data_dir()

    assert (target_dir / 'dodson.csv').read_text() == 'TARGET'
    assert (legacy_data / 'dodson.csv').exists()


def test_open_data_dir_only_migrates_known_filenames(isolated):
    legacy_data = isolated.legacy / 'data'
    legacy_data.mkdir()
    (legacy_data / 'cross_references.txt').write_text('YES')
    (legacy_data / 'something_unrelated.bin').write_text('NO')

    d = paths.open_data_dir()

    assert os.path.isfile(os.path.join(d, 'cross_references.txt'))
    assert not os.path.exists(os.path.join(d, 'something_unrelated.bin'))
    # Untracked file stays in legacy.
    assert (legacy_data / 'something_unrelated.bin').exists()


# ── All wrapper helpers return paths under the right XDG dir ─────────────────

def test_each_helper_returns_correctly_categorised_path(isolated):
    cfg = str(isolated.cfg / 'bible-reader')
    data = str(isolated.data / 'bible-reader')
    cache = str(isolated.cache / 'bible-reader')

    assert paths.settings_path().startswith(cfg)
    assert paths.bookmarks_path().startswith(cfg)
    assert paths.reading_plans_path().startswith(cfg)
    assert paths.module_positions_path().startswith(cfg)

    assert paths.annotations_path().startswith(data)
    assert paths.ebible_db_path().startswith(data)
    assert paths.open_data_dir().startswith(data)

    assert paths.search_history_path().startswith(cache)
    assert paths.ebible_catalog_path().startswith(cache)
