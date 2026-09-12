"""Sermons — full-prose manuscripts, grouped by series, anchored to passages.

A sermon is not a long journal entry. An entry (`journal.py`) is a page about
a day's reading and carries the date it is *about*; a sermon is a manuscript
that is written across a span and *preached* on days of its own, belongs to a
series, and leads with a claim rather than a passage. MANUSCRIPT_RESEARCH.md
§4 measured the alternative — a `kind` on the journal store — and refused it:
the moment an entry grows a series and a delivery history the journal has
become the word processor JOURNAL_RESEARCH.md §4 ruled out.

**There is no `date` field on purpose.** The journal's `date` means "the day
this is about", and a sermon has a writing span and a preaching day, neither
of which is that. `created` orders the archive until a `preached` date exists.

`preached` is a list that may stay empty forever and is never prompted for —
a reader who does not care to record every delivery must not be nagged into
it, and a sermon with no dates is simply one not yet preached.

Anchor verses are **app space** (KJV numbering), the rule the marks settled:
`annotations.module_verse()` is the door they go back out through. Nothing
here imports annotations — a number is a number until someone renders it.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Callable

import paths

SERMONS_FILE: str = paths.sermons_path()
_log = logging.getLogger('scriptura.sermons')

#: Bumped only for a shape the readers below cannot absorb. A file from a
#: NEWER version is left alone rather than rewritten — see _load.
SCHEMA_VERSION = 1

#: Passed where None is a legitimate value the caller may mean. `series` is
#: the only such field: None IS "no series", so it cannot double as "leave it
#: alone" the way it does for the list fields, where empty already says
#: "cleared".
_KEEP: Any = object()

Sermon = dict[str, Any]
Store = dict[str, Any]

_cache: Store | None = None
_load_failed: bool = False

_on_save_error: Callable[[], None] | None = None
_save_error_reported = False


def set_save_error_handler(handler: Callable[[], None]) -> None:
    global _on_save_error, _save_error_reported
    _on_save_error = handler
    _save_error_reported = False


def load_failed() -> bool:
    _load()  # the flag means nothing until a load has been attempted
    return _load_failed


def _now() -> str:
    """Local time, seconds precision, ISO 8601 with offset — as journal._now,
    and for the same reason."""
    return datetime.now().astimezone().isoformat(timespec='seconds')


def new_id() -> str:
    """Mint an id without writing anything — the editor holds one until
    there is a title or a body to file under it."""
    return uuid.uuid4().hex


# ── Narrowing ────────────────────────────────────────────────────────────────
# Everything below comes off disk, so it is checked at the boundary. A damaged
# field costs its own value and nothing else: a sermon with one bad anchor
# keeps its words.

def _str(value: Any, fallback: str = '') -> str:
    return value if isinstance(value, str) else fallback


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else None


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for tag in value:
        if isinstance(tag, str) and tag and tag not in out:
            out.append(tag)
    return out


def _anchor(value: Any) -> dict[str, Any] | None:
    """One `{book, chapter, verses}` anchor, or None. An anchor with no
    verses is the whole chapter, which is not the same as no anchor."""
    if not isinstance(value, dict):
        return None
    book = value.get('book')
    chapter = _int(value.get('chapter'))
    if not isinstance(book, str) or not book or chapter is None:
        return None
    verses = [v for v in value.get('verses', [])
              if isinstance(v, int) and not isinstance(v, bool)] \
        if isinstance(value.get('verses'), list) else []
    return {'book': book, 'chapter': chapter, 'verses': verses}


def _anchors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [a for a in (_anchor(raw) for raw in value) if a is not None]


def _series(value: Any) -> dict[str, Any] | None:
    """`{name, part}`, or None for a sermon in no series.

    `part` is nullable on purpose: a series you are in the middle of does not
    always know its length, and "part 3 of ?" has to be sayable. A series
    with no name is no series — the name is what groups the list.
    """
    if not isinstance(value, dict):
        return None
    name = value.get('name')
    if not isinstance(name, str) or not name.strip():
        return None
    return {'name': name.strip(), 'part': _int(value.get('part'))}


def _preached(value: Any) -> list[str]:
    """The days it was preached, `YYYY-MM-DD`, oldest first, deduped.

    Kept sorted here rather than at the editor, because a date added months
    after the fact is normally an older one being remembered.
    """
    if not isinstance(value, list):
        return []
    out = {d for d in value if isinstance(d, str) and d.strip()}
    return sorted(out)


def _sermon(sermon_id: str, raw: Any) -> Sermon | None:
    """One stored sermon, narrowed, with its id folded in for the caller."""
    if not isinstance(raw, dict):
        return None
    return {
        'id': sermon_id,
        'title': _str(raw.get('title')),
        'idea': _str(raw.get('idea')),
        'body': _str(raw.get('body')),
        'anchors': _anchors(raw.get('anchors')),
        'series': _series(raw.get('series')),
        'preached': _preached(raw.get('preached')),
        # `collect` is the church_year designation key collects.collect_for
        # speaks ("anglican:sexagesima"), not a bare slug.
        'collect': _str(raw.get('collect')) or None,
        'tags': _tags(raw.get('tags')),
        'created': _str(raw.get('created')) or None,
        'modified': _str(raw.get('modified')) or None,
    }


def _stored(sermon: Sermon) -> dict[str, Any]:
    """The on-disk half — everything but the id it is filed under, so the id
    is never written twice and can never disagree."""
    return {k: v for k, v in sermon.items() if k != 'id'}


# ── Load / save ──────────────────────────────────────────────────────────────

def _empty() -> Store:
    return {'version': SCHEMA_VERSION, 'sermons': {}}


def _load() -> Store:
    global _cache, _load_failed
    if _cache is not None:
        return _cache
    if not os.path.exists(SERMONS_FILE):
        _cache = _empty()
        return _cache
    try:
        with open(SERMONS_FILE, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('sermons.json is not an object')
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
        paths.quarantine_unreadable(SERMONS_FILE)
    else:
        stored = data.get('sermons')
        _cache = {
            'version': data.get('version')
            if isinstance(data.get('version'), int) else SCHEMA_VERSION,
            'sermons': stored if isinstance(stored, dict) else {},
        }
    return _cache


def _save(data: Store) -> bool:
    """Write the store, reporting whether it reached disk. Atomic (tmp +
    fsync + os.replace); the cache is updated either way, so the return
    value is the only signal that the file behind it is stale."""
    global _cache, _save_error_reported
    _cache = data
    try:
        tmp = SERMONS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SERMONS_FILE)
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

def get(sermon_id: str) -> Sermon | None:
    raw = _load()['sermons'].get(sermon_id)
    return None if raw is None else _sermon(sermon_id, raw)


def all_sermons() -> list[Sermon]:
    """Every sermon, narrowed, each carrying its own id, in store order.
    Grouping and sorting are the window's business."""
    out: list[Sermon] = []
    for sermon_id, raw in _load()['sermons'].items():
        if not isinstance(sermon_id, str):
            continue
        sermon = _sermon(sermon_id, raw)
        if sermon is not None:
            out.append(sermon)
    return out


def all_series() -> list[str]:
    """Every series name in use, sorted — what the series field completes
    against, so a second sermon joins a series rather than founding a
    near-identical one."""
    return sorted({s['series']['name'] for s in all_sermons()
                   if s['series']}, key=str.casefold)


def all_tags() -> list[str]:
    """Every tag any sermon carries, sorted. One namespace with marks and
    entries; the union happens where they are shown."""
    return sorted({tag for sermon in all_sermons() for tag in sermon['tags']})


def tag_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for sermon in all_sermons():
        for tag in sermon['tags']:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def sermons_on(book: str, chapter: int) -> list[Sermon]:
    """Every sermon anchored anywhere on `book` `chapter` — what the reading
    page asks so a chapter can say what has been preached on it."""
    return [s for s in all_sermons()
            if any(a['book'] == book and a['chapter'] == chapter
                   for a in s['anchors'])]


def most_recent() -> Sermon | None:
    """The sermon a collecting door adds to: the one most recently written
    in, falling back to the most recently created.

    The target of "Add to …" is not a setting and not a mode — a pin is one
    more thing to get out of sync with what you are actually working on. The
    door names this sermon in its own label, so it can never be wrong about
    where the text went.
    """
    sermons = [s for s in all_sermons() if s['modified'] or s['created']]
    if not sermons:
        return None
    # Store order IS write order (see save), so the last one wins. Reading
    # it off the timestamps instead would tie: `modified` is seconds-precise
    # on purpose, and two writes inside one second are the normal case the
    # moment a door creates a sermon and then appends to it.
    return sermons[-1]


def rename_tag(old: str, new: str) -> None:
    """Rename across every sermon, deduping — so this doubles as a merge,
    the same as `annotations.rename_tag`."""
    old = (old or '').strip()
    new = (new or '').strip()
    if not old or not new or old == new:
        return
    data = _load()
    changed = False
    for raw in data['sermons'].values():
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
    """Remove `tag` from every sermon it sits on. The writing is untouched."""
    tag = (tag or '').strip()
    if not tag:
        return
    data = _load()
    changed = False
    for raw in data['sermons'].values():
        if not isinstance(raw, dict):
            continue
        tags = _tags(raw.get('tags'))
        if tag not in tags:
            continue
        raw['tags'] = [t for t in tags if t != tag]
        changed = True
    if changed:
        _save(data)


def rename_series(old: str, new: str) -> None:
    """Rename a series across every sermon in it; an empty `new` unfiles
    them. Nothing else groups the list, so this is the only way to correct a
    series name without opening every sermon in it."""
    old = (old or '').strip()
    new = (new or '').strip()
    if not old or old == new:
        return
    data = _load()
    changed = False
    for raw in data['sermons'].values():
        if not isinstance(raw, dict):
            continue
        series = _series(raw.get('series'))
        if series is None or series['name'] != old:
            continue
        raw['series'] = None if not new else {'name': new,
                                              'part': series['part']}
        changed = True
    if changed:
        _save(data)


# ── Writing ──────────────────────────────────────────────────────────────────

def save(sermon_id: str, *, title: str = '', idea: str = '', body: str = '',
         anchors: list[dict[str, Any]] | None = None,
         series: Any = _KEEP,
         preached: list[str] | None = None,
         tags: list[str] | None = None,
         collect: str | None = None) -> bool:
    """Write a sermon, creating it if it is new. Returns whether it reached
    disk.

    `created` survives a rewrite and `modified` moves. `collect` is
    provenance — stamped at creation and kept when the caller passes none,
    because which Sunday a sermon was begun for cannot be recovered later.

    `series` and `preached` are NOT provenance and are passed every time the
    editor writes: both are the reader's to clear. `series=None` therefore
    means *no series*, not *leave it alone* — omit the argument for that.

    **A write moves the sermon to the end of the store**, so the file's own
    order is the order things were last written in, and `most_recent` can
    read the collecting door's target off it. The timestamps cannot answer
    that question: they are seconds-precise by house rule, and two writes
    inside one second are ordinary.
    """
    data = _load()
    existing = data['sermons'].get(sermon_id)
    existing = existing if isinstance(existing, dict) else {}
    now = _now()
    stored = {
        'title': title,
        'idea': idea,
        'body': body,
        'anchors': _anchors(anchors if anchors is not None
                            else existing.get('anchors')),
        'series': _series(existing.get('series') if series is _KEEP
                          else series),
        'preached': _preached(preached if preached is not None
                              else existing.get('preached')),
        'collect': collect if isinstance(collect, str) and collect
        else _str(existing.get('collect')) or None,
        'tags': _tags(tags if tags is not None else existing.get('tags')),
        'created': _str(existing.get('created')) or now,
        'modified': now,
    }
    data['sermons'].pop(sermon_id, None)  # re-file at the end; see above
    data['sermons'][sermon_id] = stored
    return _save(data)


def append(sermon_id: str, text: str,
           anchor: dict[str, Any] | None = None) -> Sermon | None:
    """Add collected text to the end of a sermon's body, and its passage to
    the anchors. Returns the sermon as it now stands, or None if there is no
    such sermon.

    The anchor half is the point: text collected from the reading pane
    arrives with a reference, and a sermon that quotes a passage it is not
    anchored to would be invisible at that verse and in the book filter.

    Used only when the sermon is NOT open in an editor — an open editor owns
    its buffer, and a write underneath it would be overwritten by the next
    autosave.
    """
    sermon = get(sermon_id)
    if sermon is None:
        return None
    body = sermon['body']
    joined = f'{body.rstrip()}\n\n{text}' if body.strip() else text
    anchors = list(sermon['anchors'])
    merged = _anchor(anchor)
    if merged is not None and merged not in anchors:
        anchors.append(merged)
    save(sermon_id, title=sermon['title'], idea=sermon['idea'], body=joined,
         anchors=anchors, series=sermon['series'],
         preached=sermon['preached'], tags=sermon['tags'])
    return get(sermon_id)


def delete(sermon_id: str) -> Sermon | None:
    """Remove a sermon, returning it so the caller can offer an undo."""
    data = _load()
    removed = data['sermons'].pop(sermon_id, None)
    if removed is None:
        return None
    _save(data)
    return _sermon(sermon_id, removed)


def restore(sermon: Sermon) -> bool:
    """Put back a sermon returned by delete. The timestamps come back as
    they were: undoing a deletion is not an edit."""
    sermon_id = sermon.get('id')
    if not isinstance(sermon_id, str) or not sermon_id:
        return False
    data = _load()
    data['sermons'][sermon_id] = _stored(sermon)
    return _save(data)


# ── Backup ───────────────────────────────────────────────────────────────────

def export_raw() -> Store:
    """The whole store in its on-disk shape, for study-data backup.
    Treat as read-only."""
    return _load()


def replace_all(data: Any) -> bool:
    """Swap in a whole store (study-data restore). A backup that carried no
    sermons arrives as an empty dict and correctly empties the store — the
    file's state is the truth."""
    stored = data.get('sermons') if isinstance(data, dict) else None
    return _save({
        'version': SCHEMA_VERSION,
        'sermons': dict(stored) if isinstance(stored, dict) else {},
    })
