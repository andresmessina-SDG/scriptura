import json
import logging
import os
from typing import Callable, TypedDict, cast

import paths


class Bookmark(TypedDict):
    book: str
    chapter: int
    verse: int | None
    label: str


_FILE: str = paths.bookmarks_path()
_log = logging.getLogger('scriptura.bookmarks')
_load_failed: bool = False  # Flipped if an existing file failed to parse; the
                            # window reads this once at startup for a toast.
# The UI registers a handler so a failed save (disk full, bad permissions)
# becomes a visible toast instead of a bookmark that silently vanishes on
# the next launch — see annotations.py for the same pattern.
_on_save_error: Callable[[], None] | None = None


def set_save_error_handler(handler: Callable[[], None]) -> None:
    global _on_save_error
    _on_save_error = handler


def load_failed() -> bool:
    _load()  # ensure load was attempted before we read the flag
    return _load_failed


def _load() -> list[Bookmark]:
    global _load_failed
    if not os.path.exists(_FILE):
        return []
    try:
        with open(_FILE, encoding='utf-8') as f:
            data = json.load(f)
        # Defensive: drop any malformed entries (hand-edited file, version skew).
        # cast() reflects the JSON boundary — the predicate filters to dicts
        # with the required keys, but mypy can't infer Bookmark-shape from
        # runtime checks. Trust is at the I/O edge, not in the static type.
        return cast(list[Bookmark],
                    [e for e in data
                     if isinstance(e, dict) and 'book' in e and 'chapter' in e])
    except Exception:
        if not _load_failed:
            _log.exception('load failed, using defaults')
            _load_failed = True
        return []


def _save(data: list[Bookmark]) -> None:
    # Atomic write — see annotations.py for the rationale.
    try:
        tmp = _FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _FILE)
    except Exception:
        _log.exception('save failed')
        if _on_save_error is not None:
            try:
                _on_save_error()
            except Exception:
                _log.exception('save-error handler raised')


def get_all() -> list[Bookmark]:
    return _load()


def add(book: str, chapter: int, verse: int | None = None) -> bool:
    data = _load()
    label = f'{book} {chapter}' + (f':{verse}' if verse else '')
    for e in data:
        if e.get('book') == book and e.get('chapter') == chapter and e.get('verse') == verse:
            return False
    data.insert(0, {'book': book, 'chapter': chapter, 'verse': verse, 'label': label})
    _save(data)
    return True


def remove(index: int) -> None:
    data = _load()
    if 0 <= index < len(data):
        data.pop(index)
        _save(data)
