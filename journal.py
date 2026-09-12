"""The journal — dated entries, anchored to passages or to nothing.

An entry is not a longer note. A mark (`annotations.py`) is a margin: one
verse, a sentence, keyed by the reference it belongs to. An entry is a page:
none, one, or the day's four passages, a paragraph or more, keyed by an id of
its own. The length and the anchor count are the distinction — the moment an
entry becomes a longer note the store has two ways to say the same thing and
the reader has to guess which one they meant.

**A verse-less entry is legal and is not an orphan.** Not every reading ends
at a verse: a sermon, a conversation, a season. The canon is still the
organizing axis everywhere it can be, and the dateless ones simply group at
the end — which is the window's business, not this module's. This module
stores; it does not sort.

Anchor verses are **app space** (KJV numbering), the same rule the marks
settled: `annotations.module_verse()` is the door they go back out through.
Nothing here imports annotations — a number is a number until someone renders
it — so the two stores stay independent.

`date` is the day the entry is *about* and the reader can correct it; writing
up Sunday on Tuesday is the normal case, and an entry whose date cannot be
fixed is a log rather than a journal. `created` / `modified` are the machine's
and are never shown in its place.
"""

import json
import logging
import os
import uuid
from datetime import date as _date, datetime
from typing import Any, Callable

import paths

JOURNAL_FILE: str = paths.journal_path()
_log = logging.getLogger('scriptura.journal')

#: Bumped only for a shape the readers below cannot absorb. A file from a
#: NEWER version is left alone rather than rewritten — see _load.
SCHEMA_VERSION = 1

Entry = dict[str, Any]
Journal = dict[str, Any]

_cache: Journal | None = None
_load_failed: bool = False  # An existing file that would not parse; the UI
                            # reads this once at startup to raise a toast.

_on_save_error: Callable[[], None] | None = None
# Reported once per run of failures, not once per write — the entry editor
# autosaves on a timer, so an unwritable store would otherwise stack a toast
# every time the reader paused typing. Cleared by the next write that works.
_save_error_reported = False


def set_save_error_handler(handler: Callable[[], None]) -> None:
    global _on_save_error, _save_error_reported
    _on_save_error = handler
    _save_error_reported = False


def load_failed() -> bool:
    _load()  # the flag means nothing until a load has been attempted
    return _load_failed


def _now() -> str:
    """Local time, seconds precision, ISO 8601 with offset — as
    annotations._now, and for the same reason: these are only ever read to
    show a reader a date, and an entry written at 11pm belongs to that
    evening."""
    return datetime.now().astimezone().isoformat(timespec='seconds')


def today() -> str:
    """Today as an entry `date` — the day, with no time on it."""
    return _date.today().isoformat()


def new_id() -> str:
    """Mint an id without writing anything.

    The editor takes one when it opens and holds it; the first save happens
    on the first non-empty title or body. Opening the editor and closing it
    again must leave journal.json exactly as it was, so minting and writing
    are deliberately two separate acts.
    """
    return uuid.uuid4().hex


# ── Narrowing ────────────────────────────────────────────────────────────────
# Everything below comes off disk, so it is checked at the boundary rather
# than trusted. A damaged field costs its own value and nothing else: an
# entry with one bad anchor keeps its words.

def _str(value: Any, fallback: str = '') -> str:
    return value if isinstance(value, str) else fallback


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for tag in value:
        if isinstance(tag, str) and tag and tag not in out:
            out.append(tag)
    return out


def _anchor(value: Any) -> dict[str, Any] | None:
    """One `{book, chapter, verses}` anchor, or None if it is not one.

    An anchor with no verses is kept: a whole chapter is a legitimate thing
    to write about, and it is not the same as no anchor at all.
    """
    if not isinstance(value, dict):
        return None
    book = value.get('book')
    chapter = value.get('chapter')
    if not isinstance(book, str) or not book:
        return None
    if not isinstance(chapter, int) or isinstance(chapter, bool):
        return None
    verses = [v for v in value.get('verses', [])
              if isinstance(v, int) and not isinstance(v, bool)] \
        if isinstance(value.get('verses'), list) else []
    return {'book': book, 'chapter': chapter, 'verses': verses}


def _anchors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [a for a in (_anchor(raw) for raw in value) if a is not None]


def _plan(value: Any) -> dict[str, Any] | None:
    """`{id, day}` provenance, or None. Stamped once at creation and never
    edited: which plan day an entry came out of cannot be recovered later."""
    if not isinstance(value, dict):
        return None
    plan_id = value.get('id')
    day = value.get('day')
    if not isinstance(plan_id, str) or not plan_id:
        return None
    if not isinstance(day, int) or isinstance(day, bool):
        return None
    return {'id': plan_id, 'day': day}


def _entry(entry_id: str, raw: Any) -> Entry | None:
    """One stored entry, narrowed, with its id folded in for the caller."""
    if not isinstance(raw, dict):
        return None
    return {
        'id': entry_id,
        'date': _str(raw.get('date')),
        'title': _str(raw.get('title')),
        'body': _str(raw.get('body')),
        'anchors': _anchors(raw.get('anchors')),
        'tags': _tags(raw.get('tags')),
        # `collect` is the church_year designation key collects.collect_for
        # already speaks ("anglican:trinity7"), not a bare slug — so an entry
        # can still say which Sunday it was written on years later.
        'plan': _plan(raw.get('plan')),
        'collect': _str(raw.get('collect')) or None,
        'created': _str(raw.get('created')) or None,
        'modified': _str(raw.get('modified')) or None,
    }


def _stored(entry: Entry) -> dict[str, Any]:
    """The on-disk half of an entry — everything but the id it is filed
    under, so the id is never written twice and can never disagree."""
    return {k: v for k, v in entry.items() if k != 'id'}


# ── Load / save ──────────────────────────────────────────────────────────────

def _empty() -> Journal:
    return {'version': SCHEMA_VERSION, 'entries': {}}


def _load() -> Journal:
    global _cache, _load_failed
    if _cache is not None:
        return _cache
    if not os.path.exists(JOURNAL_FILE):
        _cache = _empty()
        return _cache
    try:
        with open(JOURNAL_FILE, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('journal.json is not an object')
    except OSError:
        # The bytes may be perfectly good — a busy disk, a permission. Leave
        # the file alone and start empty for this run.
        _log.exception('load failed, using defaults')
        _cache = _empty()
        _load_failed = True
    except paths.UNPARSEABLE:
        _log.exception('load failed, using defaults')
        _cache = _empty()
        _load_failed = True
        paths.quarantine_unreadable(JOURNAL_FILE)
    else:
        entries = data.get('entries')
        _cache = {
            'version': data.get('version')
            if isinstance(data.get('version'), int) else SCHEMA_VERSION,
            'entries': entries if isinstance(entries, dict) else {},
        }
    return _cache


def _save(data: Journal) -> bool:
    """Write the store, reporting whether it reached disk.

    The cache is updated either way — the running app must show what the
    reader just wrote — so the return value is the only signal that the file
    behind it is stale. Atomic write (tmp + fsync + os.replace), as every
    other store here: a crash mid-write leaves the previous journal intact
    rather than truncating it to nothing.
    """
    global _cache, _save_error_reported
    _cache = data
    try:
        tmp = JOURNAL_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, JOURNAL_FILE)
    except Exception:
        _log.exception('Failed to save')
        if _on_save_error is not None and not _save_error_reported:
            _save_error_reported = True
            try:
                _on_save_error()
            except Exception:
                _log.exception('save-error handler raised')
        return False
    _save_error_reported = False
    return True


# ── Reading ──────────────────────────────────────────────────────────────────

def get(entry_id: str) -> Entry | None:
    """One entry by id, narrowed, or None."""
    raw = _load()['entries'].get(entry_id)
    return None if raw is None else _entry(entry_id, raw)


def all_entries() -> list[Entry]:
    """Every entry, narrowed, each carrying its own id.

    Returned in the store's own order. Ordering is the window's business —
    anchored entries sort by the canon and the dateless ones by date, and
    neither rule belongs down here.
    """
    out: list[Entry] = []
    for entry_id, raw in _load()['entries'].items():
        if not isinstance(entry_id, str):
            continue
        entry = _entry(entry_id, raw)
        if entry is not None:
            out.append(entry)
    return out


def all_tags() -> list[str]:
    """Every tag any entry carries, sorted.

    Tags are one namespace across marks and entries; the union with
    `annotations.get_all_tags()` happens where they are shown, because two
    tag vocabularies in one window is a second organizing axis by the back
    door.
    """
    return sorted({tag for entry in all_entries() for tag in entry['tags']})


def entries_on(book: str, chapter: int) -> list[Entry]:
    """Every entry anchored anywhere on `book` `chapter`.

    Anywhere: an entry anchored to three passages counts on all three. What
    the reading page asks, so that a chapter can say how much has been
    written about it without the window being open.
    """
    return [e for e in all_entries()
            if any(a['book'] == book and a['chapter'] == chapter
                   for a in e['anchors'])]


def tag_counts() -> dict[str, int]:
    """{tag: how many entries carry it}. The window adds this to
    `annotations.get_tag_counts()` — one vocabulary, counted across both."""
    counts: dict[str, int] = {}
    for entry in all_entries():
        for tag in entry['tags']:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def rename_tag(old: str, new: str) -> None:
    """Rename `old` → `new` across every entry, deduping — so this doubles
    as a merge, the same as `annotations.rename_tag`. No-op when either side
    is empty or the names match."""
    old = (old or '').strip()
    new = (new or '').strip()
    if not old or not new or old == new:
        return
    data = _load()
    changed = False
    for raw in data['entries'].values():
        if not isinstance(raw, dict):
            continue
        tags = _tags(raw.get('tags'))
        if old not in tags:
            continue
        raw['tags'] = _tags([new if t == old else t for t in tags])
        changed = True
    if changed:
        _save(data)


def delete_tag(tag: str) -> None:
    """Remove `tag` from every entry it sits on. The writing is untouched."""
    tag = (tag or '').strip()
    if not tag:
        return
    data = _load()
    changed = False
    for raw in data['entries'].values():
        if not isinstance(raw, dict):
            continue
        tags = _tags(raw.get('tags'))
        if tag not in tags:
            continue
        raw['tags'] = [t for t in tags if t != tag]
        changed = True
    if changed:
        _save(data)


# ── Writing ──────────────────────────────────────────────────────────────────

def save(entry_id: str, *, date: str | None = None, title: str = '',
         body: str = '', anchors: list[dict[str, Any]] | None = None,
         tags: list[str] | None = None,
         plan: dict[str, Any] | None = None,
         collect: str | None = None) -> bool:
    """Write an entry, creating it if it is new. Returns whether it reached
    disk.

    `created` survives a rewrite and `modified` moves, so an entry keeps the
    day it was begun. `plan` and `collect` are provenance: kept from the
    existing entry when the caller passes none, because they are stamped at
    creation and are not the editor's to change afterwards.
    """
    data = _load()
    existing = data['entries'].get(entry_id)
    existing = existing if isinstance(existing, dict) else {}
    now = _now()
    stored = {
        'date': date if isinstance(date, str) and date else
        _str(existing.get('date')) or today(),
        'title': title,
        'body': body,
        'anchors': _anchors(anchors if anchors is not None
                            else existing.get('anchors')),
        'tags': _tags(tags if tags is not None else existing.get('tags')),
        'plan': _plan(plan if plan is not None else existing.get('plan')),
        'collect': collect if isinstance(collect, str) and collect
        else _str(existing.get('collect')) or None,
        'created': _str(existing.get('created')) or now,
        'modified': now,
    }
    data['entries'][entry_id] = stored
    return _save(data)


def delete(entry_id: str) -> Entry | None:
    """Remove an entry, returning it so the caller can offer an undo (see
    restore), or None if there was nothing to remove."""
    data = _load()
    removed = data['entries'].pop(entry_id, None)
    if removed is None:
        return None
    _save(data)
    return _entry(entry_id, removed)


def restore(entry: Entry) -> bool:
    """Put back an entry returned by delete — the undo half. The timestamps
    come back as they were: undoing a deletion is not an edit."""
    entry_id = entry.get('id')
    if not isinstance(entry_id, str) or not entry_id:
        return False
    data = _load()
    data['entries'][entry_id] = _stored(entry)
    return _save(data)


# ── Backup ───────────────────────────────────────────────────────────────────

def export_raw() -> Journal:
    """The whole journal in its on-disk shape, for study-data backup.
    Treat as read-only."""
    return _load()


def replace_all(data: Any) -> bool:
    """Swap in a whole journal (study-data restore). Returns whether it
    reached disk.

    A restore from a backup that carried no journal at all arrives here as
    an empty dict and correctly empties the store — the file's state is the
    truth, which is the same rule the other three restore by.
    """
    entries = data.get('entries') if isinstance(data, dict) else None
    return _save({
        'version': SCHEMA_VERSION,
        'entries': dict(entries) if isinstance(entries, dict) else {},
    })
