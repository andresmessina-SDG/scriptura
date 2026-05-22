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
"""

import json
import threading

import paths

_FILE = paths.module_positions_path()
_lock = threading.Lock()
_state = {}
_load_failed = False


def _load():
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


def _save_unlocked():
    try:
        with open(_FILE, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=0)
    except OSError:
        pass


def remember_verse_position(module, book, chapter, top_verse):
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
        _save_unlocked()


def get_verse_position(module, book, chapter):
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


def remember_genbook_path(module, path):
    """Save the current entry path for a genbook module."""
    if not module or not path:
        return
    with _lock:
        _state[module] = {
            'kind': 'genbook',
            'genbook_path': list(path),
        }
        _save_unlocked()


def get_genbook_path(module):
    """Return the saved entry path for a genbook module, or None."""
    with _lock:
        entry = _state.get(module)
        if not isinstance(entry, dict):
            return None
        if entry.get('kind') != 'genbook':
            return None
        p = entry.get('genbook_path')
        if isinstance(p, list):
            return list(p)
    return None


def load_failed():
    return _load_failed
