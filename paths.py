"""Single source of truth for where user-mutable state lives.

User data is partitioned across the three XDG base directories so a
Flatpak install (which mounts the app dir read-only at /app) and a
clean uninstall both behave correctly:

  - **config** (`$XDG_CONFIG_HOME/bible-reader/`) — preferences and
    durable user lists: settings.json, bookmarks.json, reading_plans.json.
  - **data**   (`$XDG_DATA_HOME/bible-reader/`)   — content the user
    accumulates over time: annotations.json, the eBible SQLite
    database, downloaded open-data files (cross-refs, topics, Dodson).
  - **cache**  (`$XDG_CACHE_HOME/bible-reader/`)  — regenerable state:
    search history, downloaded eBible catalog index.

Each public helper migrates the legacy in-tree file on first call so
existing users don't lose their work when they upgrade from a version
that wrote alongside the source code. The migration is a one-shot
`shutil.move` — if the XDG location already exists we skip; if the
legacy file is gone we skip.
"""

import logging
import os
import shutil

from gi.repository import GLib

_APP_NAME = 'bible-reader'
_log = logging.getLogger('scriptura.paths')

# Legacy paths — where state used to live, alongside the source code.
_LEGACY_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Base directories ─────────────────────────────────────────────────────────

def config_dir() -> str:
    p = os.path.join(GLib.get_user_config_dir(), _APP_NAME)
    os.makedirs(p, exist_ok=True)
    return p


def data_dir() -> str:
    p = os.path.join(GLib.get_user_data_dir(), _APP_NAME)
    os.makedirs(p, exist_ok=True)
    return p


def cache_dir() -> str:
    p = os.path.join(GLib.get_user_cache_dir(), _APP_NAME)
    os.makedirs(p, exist_ok=True)
    return p


# ── Per-file path resolution with one-shot legacy migration ──────────────────

def _migrated_file(target_dir: str, filename: str, legacy_subdir: str = '') -> str:
    """Return the path `target_dir/filename`. If that doesn't exist
    yet but a file at `_LEGACY_DIR/legacy_subdir/filename` does, move
    the legacy file into place first. Idempotent."""
    target = os.path.join(target_dir, filename)
    if os.path.exists(target):
        return target
    legacy = os.path.join(_LEGACY_DIR, legacy_subdir, filename) \
        if legacy_subdir else os.path.join(_LEGACY_DIR, filename)
    if os.path.exists(legacy):
        try:
            shutil.move(legacy, target)
            _log.info('migrated %s -> %s', legacy, target)
        except Exception:
            _log.exception('could not migrate %s', legacy)
    return target


# Config (preferences + durable user lists)
def settings_path() -> str:
    return _migrated_file(config_dir(), 'settings.json')


def bookmarks_path() -> str:
    return _migrated_file(config_dir(), 'bookmarks.json')


def reading_plans_path() -> str:
    return _migrated_file(config_dir(), 'reading_plans.json')


def module_positions_path() -> str:
    """Per-module scroll/entry-path memory shared across both panes.
    Lives in config since it's a small durable user-state file (not
    derivable, not cache)."""
    return _migrated_file(config_dir(), 'module_positions.json')


# Data (user content + downloaded reference databases)
def annotations_path() -> str:
    return _migrated_file(data_dir(), 'annotations.json')


def ebible_db_path() -> str:
    """eBible SQLite database. SQLite manages db-shm / db-wal sidecars
    relative to this path; migrate them alongside the main file so any
    uncommitted WAL state isn't stranded at the legacy location."""
    target = _migrated_file(data_dir(), 'ebible.db')
    # Carry sidecars over if the main DB just moved. Best-effort —
    # SQLite would re-create them on first open at the new location
    # anyway, but moving them preserves any uncheckpointed writes.
    for suffix in ('-shm', '-wal'):
        side_legacy = os.path.join(_LEGACY_DIR, f'ebible.db{suffix}')
        side_target = target + suffix
        if os.path.exists(side_legacy) and not os.path.exists(side_target):
            try:
                shutil.move(side_legacy, side_target)
            except Exception:
                _log.exception('could not migrate %s', side_legacy)
    return target


def open_data_dir() -> str:
    """Directory for downloaded reference files (OpenBible cross-refs,
    OpenBible topics, Dodson Greek lexicon). Migrates each file
    individually out of the legacy `data/` subdirectory."""
    d = os.path.join(data_dir(), 'open_data')
    os.makedirs(d, exist_ok=True)
    for fname in ('cross_references.txt', 'topic-scores.txt', 'dodson.csv'):
        target = os.path.join(d, fname)
        if os.path.exists(target):
            continue
        legacy = os.path.join(_LEGACY_DIR, 'data', fname)
        if os.path.exists(legacy):
            try:
                shutil.move(legacy, target)
                _log.info('migrated %s -> %s', legacy, target)
            except Exception:
                _log.exception('could not migrate %s', legacy)
    return d


# Cache (regenerable / downloadable state)
def search_history_path() -> str:
    return _migrated_file(cache_dir(), 'search_history.json')


def ebible_catalog_path() -> str:
    """The downloadable eBible.org translation catalog index. Cacheable
    — re-fetched on demand from inside Module Manager."""
    return _migrated_file(cache_dir(), 'ebible_catalog.csv')
