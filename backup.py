"""One-file backup and restore of the user's study data.

Bundles the five stores a reader accumulates by hand — annotations
(highlights, underlines, notes, tags), journal entries, sermon manuscripts,
bookmarks, and reading-plan progress — into a single JSON document the user
can keep anywhere. Settings and downloaded content are deliberately excluded:
preferences are device-local, and modules/packs are re-downloadable from
Module Manager.

Restore replaces the five stores wholesale. That is the honest
semantic for the primary use case (bringing your study life to a new
machine); merging two divergent annotation histories has no right
answer, so we don't pretend to do it. The window confirms with the
incoming counts before calling restore().

VERSION 2 added the journal, VERSION 3 the sermons. An older file restores
with that section empty, which is exactly right — it was written by a
Scriptura that had none. The bump is for the other direction: validate()
refuses a payload from a newer version, so an older Scriptura declines the
file rather than silently dropping the writing in it.

daily_copy() writes the same document once a day, at launch, to a folder on
this device, and keeps the last DAILY_KEEP of them. It runs before the reader
touches anything, so a copy never holds a mistake made that day.
"""

import datetime
import json
import logging
import os
from typing import Any

import annotations
import bookmarks
import journal
import paths
import reading_plans
import sermons

FORMAT = 'scriptura-study-data'
VERSION = 3
DAILY_KEEP = 14
_DAILY_PREFIX = 'scriptura-study-data-'

_log = logging.getLogger('scriptura.backup')


def collect() -> dict[str, Any]:
    """The full backup document, ready for json.dump."""
    return {
        'format': FORMAT,
        'version': VERSION,
        'exported': datetime.date.today().isoformat(),
        'annotations': annotations.export_raw(),
        'journal': journal.export_raw(),
        'sermons': sermons.export_raw(),
        'bookmarks': bookmarks.export_raw(),
        'reading_plans': reading_plans.export_raw(),
    }


def validate(payload: Any) -> dict[str, Any]:
    """Check that `payload` is a backup document this version can restore.
    Returns it typed; raises ValueError with a user-presentable reason."""
    if not isinstance(payload, dict) or payload.get('format') != FORMAT:
        raise ValueError('not a Scriptura study-data file')
    if not isinstance(payload.get('version'), int) or payload['version'] > VERSION:
        raise ValueError('made by a newer version of Scriptura')
    for key, typ in (('annotations', dict), ('journal', dict),
                     ('sermons', dict), ('bookmarks', list),
                     ('reading_plans', dict)):
        if not isinstance(payload.get(key, typ()), typ):
            raise ValueError('file is damaged')
    # The reading-plan inner shapes are consumed without further checks
    # (get_active does start_dates.get(...)), so a damaged section must be
    # rejected here rather than crash the plan UI after a restore.
    plans = payload.get('reading_plans', {})
    if (not isinstance(plans.get('start_dates', {}), dict)
            or not isinstance(plans.get('completed', {}), dict)
            or not all(isinstance(days, list)
                       for days in plans.get('completed', {}).values())):
        raise ValueError('file is damaged')
    return payload


def counts(payload: dict[str, Any]) -> dict[str, int]:
    """Entry counts for the restore confirmation dialog:
    verse annotations + chapter notes, journal entries, sermons, bookmarks,
    plan days marked read."""
    n_annotations = 0
    for chapter_data in payload.get('annotations', {}).values():
        if isinstance(chapter_data, dict):
            n_annotations += len(chapter_data)
    entries = payload.get('journal', {}).get('entries', {})
    n_journal = len(entries) if isinstance(entries, dict) else 0
    preached = payload.get('sermons', {}).get('sermons', {})
    n_sermons = len(preached) if isinstance(preached, dict) else 0
    n_days = 0
    completed = payload.get('reading_plans', {}).get('completed', {})
    if isinstance(completed, dict):
        n_days = sum(len(v) for v in completed.values() if isinstance(v, list))
    return {
        'annotations': n_annotations,
        'journal': n_journal,
        'sermons': n_sermons,
        'bookmarks': len(payload.get('bookmarks', [])),
        'plan_days': n_days,
    }


def restore(payload: dict[str, Any]) -> list[str]:
    """Replace all five stores with the (validated) payload's contents.
    Missing sections are treated as empty — the file's state is the truth.

    Returns the keys of any sections that did not reach disk. A store whose
    write failed still holds the restored data in memory, so the app looks
    right until the next launch: the caller must not report success without
    checking this.
    """
    return [key for key, ok in (
        ('annotations', annotations.replace_all(payload.get('annotations', {}))),
        ('journal', journal.replace_all(payload.get('journal', {}))),
        ('sermons', sermons.replace_all(payload.get('sermons', {}))),
        ('bookmarks', bookmarks.replace_all(payload.get('bookmarks', []))),
        ('reading_plans', reading_plans.replace_all(payload.get('reading_plans', {}))),
    ) if not ok]


def _daily_copies(folder: str) -> list[str]:
    """Daily copy file names, oldest first (ISO dates sort by name)."""
    return sorted(n for n in os.listdir(folder)
                  if n.startswith(_DAILY_PREFIX) and n.endswith('.json'))


def daily_copy(folder: str | None = None,
               today: datetime.date | None = None) -> str | None:
    """Write today's copy unless one exists, then drop all but the newest
    DAILY_KEEP. Returns the path written, or None. Never raises: a failed
    copy must not stop the app from opening."""
    try:
        folder = folder or paths.backups_dir()
        day = (today or datetime.date.today()).isoformat()
        dest = os.path.join(folder, f'{_DAILY_PREFIX}{day}.json')
        written = None
        if not os.path.exists(dest):
            doc = collect()
            doc['exported'] = day
            tmp = dest + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
            written = dest
        # Days the app was not opened make no copy, so this keeps the last
        # DAILY_KEEP days of use, not of the calendar.
        copies = _daily_copies(folder)
        for name in copies[:-DAILY_KEEP]:
            os.remove(os.path.join(folder, name))
        return written
    except Exception:
        _log.exception('daily copy failed')
        return None


def newest_daily_copy(folder: str | None = None) -> str | None:
    """The most recent daily copy, or None when there is none yet."""
    folder = folder or paths.backups_dir()
    copies = _daily_copies(folder)
    return os.path.join(folder, copies[-1]) if copies else None
