"""Per-module position memory shared across panes.

The same module can appear in pane 1 or pane 2 at different times.
This file maintains a single state record per module so that — when
a module is displayed (initial load, pane swap, picker change) — it
restores to where it was last viewed, regardless of which pane is
showing it.

Two kinds of position:

  - **verse**   (Bibles, commentaries): a top-visible verse number
    scoped to (book, chapter). Restored only when the surrounding
    book/chapter match — top_verse for chapter A isn't valid for
    chapter B.
  - **genbook** (Generic Books): an entry path (list of strings)
    identifying the current TOC entry inside the module's tree.

Persisted to `module_positions.json` under the XDG config dir.

Writes are debounced (500 ms) so a burst of module changes
coalesces into one disk write. The lock is released BEFORE the
write so a slow disk doesn't block other callers. `flush()` from
close-request forces a synchronous final save.
"""

import json
import os
import threading
from typing import Any

import paths

_FILE: str = paths.module_positions_path()
_lock = threading.Lock()
# Per-module entry shape is either {'kind': 'verse', 'book', 'chapter',
# 'top_verse'} or {'kind': 'genbook', 'genbook_path'}; dict[str, Any]
# keeps both shapes addressable without union noise.
_state: dict[str, dict[str, Any]] = {}
_load_failed: bool = False

# Mirror of settings.py's debounce pattern: rapid remember_*() calls
# (e.g. a pane swap fires two in a row) coalesce into one disk write.
_SAVE_DEBOUNCE_S: float = 0.5
_save_timer: threading.Timer | None = None
_save_timer_lock = threading.Lock()


def _load() -> None:
    global _state, _load_failed
    try:
        with open(_FILE, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            _state = data
    except FileNotFoundError:
        _state = {}
    except (OSError, ValueError):
        _load_failed = True
        _state = {}


_load()


def _write_snapshot(snapshot: dict[str, dict[str, Any]]) -> None:
    """Atomic write of `snapshot` to disk. Called with the lock NOT
    held — the caller is responsible for taking a consistent
    snapshot under the lock before passing it here."""
    try:
        tmp = _FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=0)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _FILE)
    except OSError:
        pass


def _save_now() -> None:
    """Synchronous save. Snapshots state under the lock, then writes
    outside the lock so disk I/O can't block other callers."""
    with _lock:
        snapshot = dict(_state)
    _write_snapshot(snapshot)


def _on_debounce_fire() -> None:
    global _save_timer
    with _save_timer_lock:
        _save_timer = None
    _save_now()


def _schedule_save() -> None:
    """Start (or restart) the debounce timer. Calling repeatedly
    within the window resets it — only the final save lands."""
    global _save_timer
    with _save_timer_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(_SAVE_DEBOUNCE_S, _on_debounce_fire)
        _save_timer.daemon = True
        _save_timer.start()


def flush() -> None:
    """Force a synchronous write of pending state. Call from
    close-request so unsaved positions aren't lost on exit."""
    global _save_timer
    with _save_timer_lock:
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None
    _save_now()


def remember_verse_position(module: str, book: str, chapter: int, top_verse: int) -> None:
    """Save the user's current top-visible verse for a verse-keyed
    module. Top_verse is scoped to (book, chapter) — viewing the same
    module at a different chapter creates a fresh entry on next save."""
    if not module or not book or not chapter or not top_verse:
        return
    with _lock:
        _state[module] = {
            'kind': 'verse',
            'book': str(book),
            'chapter': int(chapter),
            'top_verse': int(top_verse),
        }
    _schedule_save()


def get_verse_position(module: str, book: str, chapter: int) -> int | None:
    """Return the saved top_verse for this module at (book, chapter),
    or None if nothing saved or saved location is for a different chapter."""
    with _lock:
        entry = _state.get(module)
        if not isinstance(entry, dict):
            return None
        if entry.get('kind') != 'verse':
            return None
        if entry.get('book') != book or entry.get('chapter') != int(chapter):
            return None
        v = entry.get('top_verse')
        if isinstance(v, int):
            return v
    return None


def remember_genbook_path(module: str, path: str) -> None:
    """Save the current entry path for a genbook module. `path` is a
    SWORD genbook key like '/Title_Page' — a string, NOT a list."""
    if not module or not path:
        return
    with _lock:
        _state[module] = {
            'kind': 'genbook',
            'genbook_path': str(path),
        }
    _schedule_save()


def get_genbook_path(module: str) -> str | None:
    """Return the saved entry path string for a genbook module, or None.

    Tolerates legacy data corrupted by an earlier `list(path)` call that
    decomposed strings into per-character lists (e.g. '/Title_Page'
    became ['/', 'T', 'i', 't', ...]). If we see that shape, join it
    back into a string."""
    with _lock:
        entry = _state.get(module)
        if not isinstance(entry, dict):
            return None
        if entry.get('kind') != 'genbook':
            return None
        p = entry.get('genbook_path')
        if isinstance(p, list) and all(
                isinstance(c, str) and len(c) <= 1 for c in p):
            p = ''.join(p)
        if isinstance(p, str) and p:
            return p
    return None


def load_failed() -> bool:
    return _load_failed
