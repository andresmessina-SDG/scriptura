"""One-file backup and restore of the user's study data.

Bundles the three stores a reader accumulates by hand — annotations
(highlights, underlines, notes, tags), bookmarks, and reading-plan
progress — into a single JSON document the user can keep anywhere.
Settings and downloaded content are deliberately excluded: preferences
are device-local, and modules/packs are re-downloadable from Module
Manager.

Restore replaces the three stores wholesale. That is the honest
semantic for the primary use case (bringing your study life to a new
machine); merging two divergent annotation histories has no right
answer, so we don't pretend to do it. The window confirms with the
incoming counts before calling restore().
"""

import datetime
from typing import Any

import annotations
import bookmarks
import reading_plans

FORMAT = 'scriptura-study-data'
VERSION = 1


def collect() -> dict[str, Any]:
    """The full backup document, ready for json.dump."""
    return {
        'format': FORMAT,
        'version': VERSION,
        'exported': datetime.date.today().isoformat(),
        'annotations': annotations.export_raw(),
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
    for key, typ in (('annotations', dict), ('bookmarks', list),
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
    verse annotations + chapter notes, bookmarks, plan days marked read."""
    n_annotations = 0
    for chapter_data in payload.get('annotations', {}).values():
        if isinstance(chapter_data, dict):
            n_annotations += len(chapter_data)
    n_days = 0
    completed = payload.get('reading_plans', {}).get('completed', {})
    if isinstance(completed, dict):
        n_days = sum(len(v) for v in completed.values() if isinstance(v, list))
    return {
        'annotations': n_annotations,
        'bookmarks': len(payload.get('bookmarks', [])),
        'plan_days': n_days,
    }


def restore(payload: dict[str, Any]) -> None:
    """Replace all three stores with the (validated) payload's contents.
    Missing sections are treated as empty — the file's state is the truth."""
    annotations.replace_all(payload.get('annotations', {}))
    bookmarks.replace_all(payload.get('bookmarks', []))
    reading_plans.replace_all(payload.get('reading_plans', {}))
