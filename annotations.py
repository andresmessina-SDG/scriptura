import json
import logging
import os
from typing import Any, Callable, TypedDict

import paths

ANNOTATIONS_FILE: str = paths.annotations_path()
_log = logging.getLogger('scriptura.annotations')

# The on-disk JSON is intentionally schemaless across versions —
# legacy data may have a bare highlight color string where a current
# file has a verse dict; chapter_note may be a string or a dict.
# We type the cache as dict[str, Any] for that reason; specific
# helpers narrow via isinstance() at the boundary.
ChapterData = dict[str, Any]
Annotations = dict[str, ChapterData]


class ChapterNoteData(TypedDict):
    note: str
    tags: list[str]


_cache: Annotations | None = None
_load_failed: bool = False  # Set if an existing file failed to parse; the
                            # window reads this once at startup to surface a toast.

# The UI registers a handler here so a failed save (disk full, bad
# permissions) becomes a visible toast. _save() updates the in-memory
# cache before writing, so without this the change would persist for the
# session and silently vanish on the next launch.
_on_save_error: Callable[[], None] | None = None


def set_save_error_handler(handler: Callable[[], None]) -> None:
    global _on_save_error
    _on_save_error = handler


def load_failed() -> bool:
    _load()  # ensure load was attempted before we read the flag
    return _load_failed


def _load() -> Annotations:
    global _cache, _load_failed
    if _cache is not None:
        return _cache
    if not os.path.exists(ANNOTATIONS_FILE):
        _cache = {}
        return _cache
    try:
        with open(ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Corrupted file producing a non-dict — start over rather than crash.
        if isinstance(data, dict):
            _cache = data
        else:
            _cache = {}
            _load_failed = True
    except Exception:
        _log.exception('load failed, using defaults')
        _cache = {}
        _load_failed = True
    return _cache


def _save(data: Annotations) -> None:
    global _cache
    _cache = data
    # Atomic write: build the file beside the destination, fsync, then
    # os.replace (atomic on POSIX). A crash mid-write leaves the
    # original intact instead of truncating it to zero bytes —
    # annotations.json holds the user's irreplaceable highlights,
    # notes, and tags.
    try:
        tmp = ANNOTATIONS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ANNOTATIONS_FILE)
    except Exception:
        _log.exception('Failed to save')
        if _on_save_error is not None:
            try:
                _on_save_error()
            except Exception:
                _log.exception('save-error handler raised')

def get_annotations(module: str, book: str, chapter: int) -> ChapterData:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    return data.get(key, {})

def save_highlight(module: str, book: str, chapter: int, verse: int, color: str | None) -> None:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data: data[key] = {}

    # Migrate old string data to dict if necessary
    vkey = str(verse)
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}

    data[key][vkey]['highlight'] = color
    _save(data)

def save_underline(module: str, book: str, chapter: int, verse: int, enabled: bool) -> None:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data: data[key] = {}

    vkey = str(verse)
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}

    data[key][vkey]['underline'] = enabled
    _save(data)

def save_note(module: str, book: str, chapter: int, verse: int, text: str | None) -> None:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data: data[key] = {}

    vkey = str(verse)
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}

    data[key][vkey]['note'] = text
    _save(data)


def _ensure_verse_dict(data: Annotations, key: str, vkey: str) -> None:
    if key not in data:
        data[key] = {}
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}


def save_tags(module: str, book: str, chapter: int, verse: int, tags: list[str]) -> None:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    _ensure_verse_dict(data, key, str(verse))
    # Coerce to strings before stripping — defensive against None / non-string
    # entries that can sneak in from corrupt JSON or tests.
    data[key][str(verse)]['tags'] = [
        str(t).strip() for t in tags if t is not None and str(t).strip()
    ]
    _save(data)


def get_all_tags() -> list[str]:
    tags: set[str] = set()
    for verses in _load().values():
        for anno in verses.values():
            if isinstance(anno, dict):
                tags.update(anno.get('tags', []))
    return sorted(tags)


def get_tag_counts() -> dict[str, int]:
    """Return {tag: count} across every verse annotation and chapter note."""
    counts: dict[str, int] = {}
    for verses in _load().values():
        for anno in verses.values():
            if not isinstance(anno, dict):
                continue
            for t in anno.get('tags', []) or []:
                if isinstance(t, str) and t.strip():
                    counts[t] = counts.get(t, 0) + 1
    return counts


def rename_tag(old: str, new: str) -> None:
    """Rename tag `old` → `new` across every annotation. If `new` already
    sits on the same annotation as `old`, the result is deduped, so this
    doubles as a merge. No-op when either side is empty or the names match."""
    old = (old or '').strip()
    new = (new or '').strip()
    if not old or not new or old == new:
        return
    data = _load()
    changed = False
    for verses in data.values():
        for anno in verses.values():
            if not isinstance(anno, dict):
                continue
            tags = anno.get('tags')
            if not tags or old not in tags:
                continue
            seen: set[str] = set()
            out: list[str] = []
            for t in tags:
                if not isinstance(t, str):
                    continue
                replaced = new if t == old else t
                if replaced not in seen:
                    seen.add(replaced)
                    out.append(replaced)
            anno['tags'] = out
            changed = True
    if changed:
        _save(data)


def delete_tag(tag: str) -> None:
    """Remove `tag` from every annotation it appears on. Notes/highlights
    are untouched."""
    tag = (tag or '').strip()
    if not tag:
        return
    data = _load()
    changed = False
    for verses in data.values():
        for anno in verses.values():
            if not isinstance(anno, dict):
                continue
            tags = anno.get('tags')
            if not tags or tag not in tags:
                continue
            anno['tags'] = [t for t in tags if t != tag]
            changed = True
    if changed:
        _save(data)


def _chapter_note_data(raw: Any) -> ChapterNoteData | None:
    """Normalise chapter_note storage: string (old) or dict (new) → dict."""
    if isinstance(raw, str):
        return {'note': raw, 'tags': []}
    if isinstance(raw, dict):
        return {'note': raw.get('note', ''), 'tags': raw.get('tags', [])}
    return None


def get_chapter_note(module: str, book: str, chapter: int) -> str | None:
    raw = _load().get(f"{module}/{book}/{chapter}", {}).get('chapter_note')
    d = _chapter_note_data(raw)
    return d['note'] if d and d['note'].strip() else None


def get_chapter_note_data(module: str, book: str, chapter: int) -> ChapterNoteData | None:
    raw = _load().get(f"{module}/{book}/{chapter}", {}).get('chapter_note')
    return _chapter_note_data(raw)


def save_chapter_note(module: str, book: str, chapter: int, text: str) -> None:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data:
        data[key] = {}
    existing = _chapter_note_data(data[key].get('chapter_note'))
    tags = existing['tags'] if existing else []
    if text.strip() or tags:
        data[key]['chapter_note'] = {'note': text, 'tags': tags}
    else:
        data[key].pop('chapter_note', None)
    _save(data)


def save_chapter_note_tags(module: str, book: str, chapter: int, tags: list[str]) -> None:
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data:
        data[key] = {}
    existing = _chapter_note_data(data[key].get('chapter_note'))
    note = existing['note'] if existing else ''
    if note.strip() or tags:
        data[key]['chapter_note'] = {'note': note, 'tags': tags}
    else:
        data[key].pop('chapter_note', None)
    _save(data)


def delete_annotation(module: str, book: str, chapter: int, verse: int | None) -> Any:
    """Remove all annotation data for a verse. verse=None removes the chapter
    note. Returns the removed payload so the caller can offer an undo
    (see restore_annotation), or None if there was nothing to remove."""
    data = _load()
    key = f"{module}/{book}/{chapter}"
    if key not in data:
        return None
    if verse is None:
        removed = data[key].pop('chapter_note', None)
    else:
        removed = data[key].pop(str(verse), None)
    if removed is not None:
        _save(data)
    return removed


def restore_annotation(module: str, book: str, chapter: int, verse: int | None,
                       payload: Any) -> None:
    """Reinstate a payload returned by delete_annotation — the undo half."""
    if payload is None:
        return
    data = _load()
    key = f"{module}/{book}/{chapter}"
    data.setdefault(key, {})['chapter_note' if verse is None else str(verse)] = payload
    _save(data)


def export_raw() -> Annotations:
    """The whole store in its on-disk shape, for study-data backup.
    Callers must treat the returned dict as read-only."""
    return _load()


def replace_all(data: Annotations) -> None:
    """Swap in a whole store (study-data restore). Same light validation
    as _load: keep only chapter entries that are dicts."""
    _save({str(k): v for k, v in data.items() if isinstance(v, dict)})
