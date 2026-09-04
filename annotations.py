import json
import logging
import os
import shutil
from datetime import datetime
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


# ── Keys and versification ───────────────────────────────────────────────────
#
# A mark belongs to a PLACE IN SCRIPTURE, not to the module that happened to be
# open when it was made. The store is keyed `book/chapter` and its verse numbers
# are app space (KJV), so a note written in the KJV is there in the RVR60 and in
# whatever Russian text is installed next year.
#
# The public functions still take `module` first. It is not part of the key: it
# is the LENS — and `None` is a caller that already speaks app space, such as
# the Annotations window writing back an entry it read out of this store. A module renders its own verse numbers, and on a Synodal or
# Vulgate psalter its verse 1 is the superscription, which is app-space verse 0.
# So every number crossing this boundary is translated — inward on write,
# outward on read — and callers go on speaking the numbers they can see.

def _chapter_key(book: str, chapter: int) -> str:
    return f"{book}/{chapter}"


def _sword() -> Any:
    """sword_bridge, or None. Imported lazily and defensively: this module
    is loaded by the backup and test paths, which must not drag libsword in,
    and a broken import must degrade to identity rather than lose a mark."""
    try:
        import sword_bridge
        return sword_bridge
    except Exception:
        return None


def _is_mapped(module: str | None, book: str, chapter: int) -> bool:
    """Whether this module numbers this chapter differently from app space.
    False for KJV/KJVA and every module without versification tables, which
    is most of them — the identity path costs one cached lookup."""
    if not module:
        return False
    sb = _sword()
    if sb is None:
        return False
    try:
        return sb.mapped_chapter(module, book, chapter) is not None
    except Exception:
        return False


def _to_app(module: str | None, book: str, chapter: int,
            verse: int | None) -> int | None:
    """A verse number as the module renders it → the app-space verse."""
    if verse is None or not module:
        return verse
    sb = _sword()
    if sb is None:
        return verse
    try:
        mapped: int | None = sb.map_verse_to_app(module, book, chapter, verse)
    except Exception:
        return verse
    return mapped


# {(module, book, chapter): {app verse: module verse}} — see _outward_map.
_outward_maps: dict[tuple[str, str, int], dict[int, int]] = {}


def _outward_map(module: str, book: str, chapter: int) -> dict[int, int]:
    """{app verse: the number this module renders for it}, built by asking
    the module about each verse it renders and inverting the answers.

    Built by inversion rather than mapped in reverse because app space cannot
    express every module verse. A Synodal psalter numbers the superscription,
    so its Psalm 3:1 is app verse 0 — and a KJV VerseKey has no verse 0 to map
    back from, which would strand every mark on a superscription.
    """
    key = (module, book, chapter)
    cached = _outward_maps.get(key)
    if cached is not None:
        return cached
    out: dict[int, int] = {}
    sb = _sword()
    if sb is not None:
        try:
            # The verses the module actually renders, not a count taken from
            # app space: a mapped psalter has one more line in the chapter
            # than the KJV does, and it is the one most likely to be marked.
            # load_chapter is cached, and the pane is about to call it anyway.
            for mverse, _html in sb.load_chapter(module, book, chapter):
                app = sb.map_verse_to_app(module, book, chapter, mverse)
                out.setdefault(app, mverse)
        except Exception:
            _log.exception('could not map %s %s %s outward',
                           module, book, chapter)
            out = {}
    _outward_maps[key] = out
    return out


def _to_module(module: str | None, book: str, chapter: int,
               verse: int | None) -> int | None:
    """An app-space verse → the number this module renders for it."""
    if verse is None or not module:
        return verse
    return _outward_map(module, book, chapter).get(verse, verse)


def module_verse(module: str | None, book: str, chapter: int,
                 verse: int | None) -> int | None:
    """The number `module` renders for an app-space verse.

    Public because callers outside this file hold app-space verses now — the
    window repainting a pane, the detail pane quoting the verse — and they
    must not reach for `sword_bridge.map_target_verse` to do it. That one maps
    through a KJV VerseKey, which has no verse 0, so a mark on a psalter's
    superscription comes back unchanged and lands on the wrong line. See
    _outward_map.
    """
    return _to_module(module, book, chapter, verse)


# ── Timestamps ───────────────────────────────────────────────────────────────

def _now() -> str:
    """Local time, seconds precision, ISO 8601 with offset. Local rather than
    UTC because the only thing these are read for is a date shown to the
    reader, and a mark made at 11pm belongs to that evening."""
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _stamp(entry: dict[str, Any]) -> None:
    """Record when this annotation was first made and last touched.
    Entries written before this existed simply have neither."""
    now = _now()
    entry.setdefault('created', now)
    entry['modified'] = now


# ── Migration: module-keyed (v1) → reference-keyed (v2) ──────────────────────

def _merge_tags(a: list[str], b: list[str]) -> list[str]:
    out = [t for t in a if isinstance(t, str)]
    for t in b:
        if isinstance(t, str) and t not in out:
            out.append(t)
    return out


def _merge_entry(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Fold one verse's annotation into another's at the same reference.

    Only reachable when the reader marked the same verse in two modules. The
    rule is lossless: nothing the reader typed is dropped. Two different notes
    become two paragraphs rather than one of them winning silently.
    """
    merged = dict(old)
    if not merged.get('highlight') and new.get('highlight'):
        merged['highlight'] = new['highlight']
    merged['underline'] = bool(merged.get('underline')) or bool(new.get('underline'))
    a = (merged.get('note') or '').strip()
    b = (new.get('note') or '').strip()
    if a and b and a != b:
        merged['note'] = f'{a}\n\n{b}'
    elif b and not a:
        merged['note'] = b
    merged['tags'] = _merge_tags(merged.get('tags') or [], new.get('tags') or [])
    for field, pick in (('created', min), ('modified', max)):
        stamps = [s for s in (merged.get(field), new.get(field))
                  if isinstance(s, str) and s]
        if stamps:
            merged[field] = pick(stamps)
    return merged


def _merge_chapter_note(old: Any, new: Any) -> Any:
    a = _chapter_note_data(old)
    b = _chapter_note_data(new)
    if a is None:
        return new
    if b is None:
        return old
    at, bt = a['note'].strip(), b['note'].strip()
    note = f'{at}\n\n{bt}' if at and bt and at != bt else (at or bt)
    return {'note': note, 'tags': _merge_tags(a['tags'], b['tags'])}


def _migrate(data: Annotations) -> tuple[Annotations, bool]:
    """Rekey `module/book/chapter` → `book/chapter`, verses into app space.

    Idempotent: a store already in the new shape has no three-part keys and
    comes back untouched. Runs on load and on restore-from-backup, so an old
    backup file restored next year still lands in the new shape.
    """
    legacy = [k for k in data if k.count('/') == 2]
    if not legacy:
        return data, False

    out: Annotations = {k: v for k, v in data.items() if k.count('/') != 2}
    for key in legacy:
        verses = data[key]
        if not isinstance(verses, dict):
            continue
        module, book, chapter_str = key.split('/', 2)
        try:
            chapter = int(chapter_str)
        except ValueError:
            continue
        dest = out.setdefault(_chapter_key(book, chapter), {})
        for vkey, anno in verses.items():
            if vkey == 'chapter_note':
                dest['chapter_note'] = (
                    _merge_chapter_note(dest['chapter_note'], anno)
                    if 'chapter_note' in dest else anno)
                continue
            try:
                verse = int(vkey)
            except ValueError:
                continue
            if isinstance(anno, str):
                anno = {'highlight': anno}
            if not isinstance(anno, dict):
                continue
            app_key = str(_to_app(module, book, chapter, verse))
            dest[app_key] = (_merge_entry(dest[app_key], anno)
                             if app_key in dest else anno)
    return out, True


def _backup_v1() -> None:
    """Keep the module-keyed file beside the new one before the first
    migrated write. The migration is one-way and these are the reader's
    irreplaceable marks; a copy costs nothing."""
    bak = ANNOTATIONS_FILE + '.v1.bak'
    if os.path.exists(ANNOTATIONS_FILE) and not os.path.exists(bak):
        try:
            shutil.copy2(ANNOTATIONS_FILE, bak)
        except OSError:
            _log.exception('could not back up the pre-migration store')


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
        if not isinstance(data, dict):
            raise ValueError('annotations.json is not an object')
        _cache = data
    except OSError:
        _log.exception('load failed, using defaults')
        _cache = {}
        _load_failed = True
    except paths.UNPARSEABLE:
        _log.exception('load failed, using defaults')
        _cache = {}
        _load_failed = True
        paths.quarantine_unreadable(ANNOTATIONS_FILE)
    else:
        migrated, changed = _migrate(_cache)
        if changed:
            _backup_v1()
            _save(migrated)
    return _cache


def _save(data: Annotations) -> bool:
    """Write the store, reporting whether it reached disk.

    The cache is updated either way — the running app must reflect what the
    user just did — so the return value is the only signal that the file
    behind it is stale.
    """
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
        return False
    return True


def get_annotations(module: str, book: str, chapter: int) -> ChapterData:
    """This chapter's marks, keyed by the verse numbers `module` renders.

    The store speaks app space; the caller is about to index this with the
    numbers it read out of the module, so the translation happens here.
    """
    chap = _load().get(_chapter_key(book, chapter), {})
    if not chap or not _is_mapped(module, book, chapter):
        return chap
    out: ChapterData = {}
    for vkey, anno in chap.items():
        if vkey == 'chapter_note':
            out[vkey] = anno
            continue
        try:
            verse = int(vkey)
        except ValueError:
            continue
        out[str(_to_module(module, book, chapter, verse))] = anno
    return out


def _ensure_verse_dict(data: Annotations, key: str, vkey: str) -> None:
    if key not in data:
        data[key] = {}
    if vkey not in data[key] or not isinstance(data[key][vkey], dict):
        old_val = data[key].get(vkey)
        data[key][vkey] = {'highlight': old_val if isinstance(old_val, str) else None}


def _verse_slot(module: str | None, book: str, chapter: int,
                verse: int) -> tuple[Annotations, str, str]:
    """(store, chapter key, app-space verse key) ready to be written into."""
    data = _load()
    key = _chapter_key(book, chapter)
    vkey = str(_to_app(module, book, chapter, verse))
    _ensure_verse_dict(data, key, vkey)
    return data, key, vkey


def save_highlight(module: str | None, book: str, chapter: int, verse: int, color: str | None) -> None:
    data, key, vkey = _verse_slot(module, book, chapter, verse)
    data[key][vkey]['highlight'] = color
    _stamp(data[key][vkey])
    _save(data)


def save_underline(module: str | None, book: str, chapter: int, verse: int, enabled: bool) -> None:
    data, key, vkey = _verse_slot(module, book, chapter, verse)
    data[key][vkey]['underline'] = enabled
    _stamp(data[key][vkey])
    _save(data)


def save_note(module: str | None, book: str, chapter: int, verse: int, text: str | None) -> None:
    data, key, vkey = _verse_slot(module, book, chapter, verse)
    data[key][vkey]['note'] = text
    _stamp(data[key][vkey])
    _save(data)


def save_tags(module: str | None, book: str, chapter: int, verse: int, tags: list[str]) -> None:
    data, key, vkey = _verse_slot(module, book, chapter, verse)
    # Coerce to strings before stripping — defensive against None / non-string
    # entries that can sneak in from corrupt JSON or tests.
    data[key][vkey]['tags'] = [
        str(t).strip() for t in tags if t is not None and str(t).strip()
    ]
    _stamp(data[key][vkey])
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
    raw = _load().get(_chapter_key(book, chapter), {}).get('chapter_note')
    d = _chapter_note_data(raw)
    return d['note'] if d and d['note'].strip() else None


def get_chapter_note_data(module: str, book: str, chapter: int) -> ChapterNoteData | None:
    raw = _load().get(_chapter_key(book, chapter), {}).get('chapter_note')
    return _chapter_note_data(raw)


def _write_chapter_note(book: str, chapter: int, note: str,
                        tags: list[str]) -> None:
    data = _load()
    key = _chapter_key(book, chapter)
    if key not in data:
        data[key] = {}
    if note.strip() or tags:
        entry: dict[str, Any] = {'note': note, 'tags': tags}
        existing = data[key].get('chapter_note')
        if isinstance(existing, dict):
            for field in ('created', 'modified'):
                if existing.get(field):
                    entry[field] = existing[field]
        _stamp(entry)
        data[key]['chapter_note'] = entry
    else:
        data[key].pop('chapter_note', None)
    _save(data)


def save_chapter_note(module: str | None, book: str, chapter: int, text: str) -> None:
    existing = _chapter_note_data(
        _load().get(_chapter_key(book, chapter), {}).get('chapter_note'))
    _write_chapter_note(book, chapter, text,
                        existing['tags'] if existing else [])


def save_chapter_note_tags(module: str | None, book: str, chapter: int, tags: list[str]) -> None:
    existing = _chapter_note_data(
        _load().get(_chapter_key(book, chapter), {}).get('chapter_note'))
    _write_chapter_note(book, chapter,
                        existing['note'] if existing else '', tags)


def delete_annotation(module: str | None, book: str, chapter: int, verse: int | None) -> Any:
    """Remove all annotation data for a verse. verse=None removes the chapter
    note. Returns the removed payload so the caller can offer an undo
    (see restore_annotation), or None if there was nothing to remove."""
    data = _load()
    key = _chapter_key(book, chapter)
    if key not in data:
        return None
    if verse is None:
        removed = data[key].pop('chapter_note', None)
    else:
        removed = data[key].pop(str(_to_app(module, book, chapter, verse)), None)
    if removed is not None:
        _save(data)
    return removed


def restore_annotation(module: str | None, book: str, chapter: int, verse: int | None,
                       payload: Any) -> None:
    """Reinstate a payload returned by delete_annotation — the undo half."""
    if payload is None:
        return
    data = _load()
    key = _chapter_key(book, chapter)
    vkey = ('chapter_note' if verse is None
            else str(_to_app(module, book, chapter, verse)))
    data.setdefault(key, {})[vkey] = payload
    _save(data)


def export_raw() -> Annotations:
    """The whole store in its on-disk shape, for study-data backup.
    Callers must treat the returned dict as read-only."""
    return _load()


def replace_all(data: Annotations) -> bool:
    """Swap in a whole store (study-data restore). Same light validation
    as _load: keep only chapter entries that are dicts. A backup written
    before the reference-keyed migration is migrated on the way in, so an
    old file restores into the shape the app now reads. Returns whether the
    new store reached disk."""
    clean = {str(k): v for k, v in data.items() if isinstance(v, dict)}
    migrated, _changed = _migrate(clean)
    return _save(migrated)
