import json
import logging
import os
import datetime
from typing import Any, TypedDict

import paths

# A reading is a (book, chapter) pair; a day's readings is a list of them;
# a plan stores 'days' as a list of days.
Reading = tuple[str, int]
ReadingGroup = tuple[str, int, int]  # (book, start_ch, end_ch)


class Plan(TypedDict):
    id: str
    name: str
    description: str
    days: list[list[Reading]]


class PlanSummary(TypedDict):
    id: str
    name: str
    description: str
    total_days: int

_FILE: str = paths.reading_plans_path()
_log = logging.getLogger('scriptura.plans')
_cache: dict[str, Any] | None = None
_load_failed: bool = False  # Flipped if an existing file failed to parse.


def load_failed() -> bool:
    _load()  # ensure load was attempted before we read the flag
    return _load_failed

# (book, n_chapters) — names match sword_bridge._ALL_BOOKS exactly
_CHAPTERS = [
    ('Genesis', 50), ('Exodus', 40), ('Leviticus', 27), ('Numbers', 36), ('Deuteronomy', 34),
    ('Joshua', 24), ('Judges', 21), ('Ruth', 4), ('1 Samuel', 31), ('2 Samuel', 24),
    ('1 Kings', 22), ('2 Kings', 25), ('1 Chronicles', 29), ('2 Chronicles', 36),
    ('Ezra', 10), ('Nehemiah', 13), ('Esther', 10), ('Job', 42), ('Psalms', 150),
    ('Proverbs', 31), ('Ecclesiastes', 12), ('Song of Solomon', 8), ('Isaiah', 66),
    ('Jeremiah', 52), ('Lamentations', 5), ('Ezekiel', 48), ('Daniel', 12),
    ('Hosea', 14), ('Joel', 3), ('Amos', 9), ('Obadiah', 1), ('Jonah', 4),
    ('Micah', 7), ('Nahum', 3), ('Habakkuk', 3), ('Zephaniah', 3), ('Haggai', 2),
    ('Zechariah', 14), ('Malachi', 4),
    ('Matthew', 28), ('Mark', 16), ('Luke', 24), ('John', 21), ('Acts', 28),
    ('Romans', 16), ('1 Corinthians', 16), ('2 Corinthians', 13), ('Galatians', 6),
    ('Ephesians', 6), ('Philippians', 4), ('Colossians', 4), ('1 Thessalonians', 5),
    ('2 Thessalonians', 3), ('1 Timothy', 6), ('2 Timothy', 4), ('Titus', 3),
    ('Philemon', 1), ('Hebrews', 13), ('James', 5), ('1 Peter', 5), ('2 Peter', 3),
    ('1 John', 5), ('2 John', 1), ('3 John', 1), ('Jude', 1), ('Revelation', 22),
]

_OT = _CHAPTERS[:39]
_NT = _CHAPTERS[39:]

_ABBREV = {
    'Genesis': 'Gen', 'Exodus': 'Exod', 'Leviticus': 'Lev', 'Numbers': 'Num',
    'Deuteronomy': 'Deut', 'Joshua': 'Josh', 'Judges': 'Judg', 'Ruth': 'Ruth',
    '1 Samuel': '1 Sam', '2 Samuel': '2 Sam', '1 Kings': '1 Kgs', '2 Kings': '2 Kgs',
    '1 Chronicles': '1 Chr', '2 Chronicles': '2 Chr', 'Ezra': 'Ezra', 'Nehemiah': 'Neh',
    'Esther': 'Esth', 'Job': 'Job', 'Psalms': 'Ps', 'Proverbs': 'Prov',
    'Ecclesiastes': 'Eccl', 'Song of Solomon': 'Song', 'Isaiah': 'Isa',
    'Jeremiah': 'Jer', 'Lamentations': 'Lam', 'Ezekiel': 'Ezek', 'Daniel': 'Dan',
    'Hosea': 'Hos', 'Joel': 'Joel', 'Amos': 'Amos', 'Obadiah': 'Obad',
    'Jonah': 'Jonah', 'Micah': 'Mic', 'Nahum': 'Nah', 'Habakkuk': 'Hab',
    'Zephaniah': 'Zeph', 'Haggai': 'Hag', 'Zechariah': 'Zech', 'Malachi': 'Mal',
    'Matthew': 'Matt', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John',
    'Acts': 'Acts', 'Romans': 'Rom', '1 Corinthians': '1 Cor', '2 Corinthians': '2 Cor',
    'Galatians': 'Gal', 'Ephesians': 'Eph', 'Philippians': 'Phil', 'Colossians': 'Col',
    '1 Thessalonians': '1 Thess', '2 Thessalonians': '2 Thess', '1 Timothy': '1 Tim',
    '2 Timothy': '2 Tim', 'Titus': 'Titus', 'Philemon': 'Phlm', 'Hebrews': 'Heb',
    'James': 'Jas', '1 Peter': '1 Pet', '2 Peter': '2 Pet', '1 John': '1 Jn',
    '2 John': '2 Jn', '3 John': '3 Jn', 'Jude': 'Jude', 'Revelation': 'Rev',
}


def _expand(books: list[tuple[str, int]]) -> list[Reading]:
    return [(b, c) for b, n in books for c in range(1, n + 1)]


def _spread(chapters: list[Reading], n_days: int) -> list[list[Reading]]:
    n = len(chapters)
    return [chapters[n * d // n_days: n * (d + 1) // n_days] for d in range(n_days)]


def _make_blended() -> list[list[Reading]]:
    # Four daily streams: OT history/wisdom, OT prophecy, NT, Psalms+Proverbs.
    # Psalms and Proverbs are excluded from s1 — they're their own stream (s4),
    # so without this they'd be read twice a year.
    s1 = _spread(_expand([b for b in _OT[:22]
                          if b[0] not in ('Psalms', 'Proverbs')]), 365)
    s2 = _spread(_expand(_OT[22:]), 365)   # Isaiah–Malachi
    s3 = _spread(_expand(_NT), 365)
    s4 = _spread(_expand([('Psalms', 150), ('Proverbs', 31)]), 365)
    return [s1[d] + s2[d] + s3[d] + s4[d] for d in range(365)]


_PLANS: list[Plan] = [
    {
        'id': 'bible_1_year',
        'name': 'Bible in a Year',
        'description': 'Read the entire Bible cover to cover in 365 days.',
        'days': _spread(_expand(_OT + _NT), 365),
    },
    {
        'id': 'blended_1_year',
        'name': 'Bible in a Year — Blended',
        'description': 'Four daily readings: OT history, OT prophecy, NT, and Psalms/Proverbs.',
        'days': _make_blended(),
    },
    {
        'id': 'ot_1_year',
        'name': 'Old Testament in a Year',
        'description': 'Read the Old Testament in 365 days.',
        'days': _spread(_expand(_OT), 365),
    },
    {
        'id': 'nt_90_days',
        'name': 'New Testament in 90 Days',
        'description': 'Read through the entire New Testament in three months.',
        'days': _spread(_expand(_NT), 90),
    },
    {
        'id': 'psalms_30_days',
        'name': 'Psalms in 30 Days',
        'description': 'Five psalms per day for a month.',
        'days': _spread(_expand([('Psalms', 150)]), 30),
    },
    {
        'id': 'proverbs_31_days',
        'name': 'Proverbs in 31 Days',
        'description': 'One chapter of Proverbs each day of the month.',
        'days': _spread(_expand([('Proverbs', 31)]), 31),
    },
]


def get_plans() -> list[PlanSummary]:
    return [{'id': p['id'], 'name': p['name'], 'description': p['description'],
             'total_days': len(p['days'])} for p in _PLANS]


def get_plan_days(plan_id: str) -> list[list[Reading]]:
    for p in _PLANS:
        if p['id'] == plan_id:
            return p['days']
    return []


def group_readings(readings: list[Reading]) -> list[ReadingGroup]:
    """Return [(book, start_ch, end_ch)] for contiguous same-book runs."""
    groups: list[ReadingGroup] = []
    i = 0
    while i < len(readings):
        book, ch = readings[i]
        end = ch
        while (i + 1 < len(readings)
               and readings[i + 1][0] == book
               and readings[i + 1][1] == end + 1):
            i += 1
            end = readings[i][1]
        groups.append((book, ch, end))
        i += 1
    return groups


def format_passages(readings: list[Reading]) -> str:
    """Compress [(book, ch), …] into e.g. 'Gen 1–3 · Matt 1'."""
    if not readings:
        return ''
    parts = []
    for book, start, end in group_readings(readings):
        a = _ABBREV.get(book, book)
        parts.append(f'{a} {start}' if start == end else f'{a} {start}–{end}')
    return ' · '.join(parts)


# ── Progress persistence ───────────────────────────────────────────────────────

def _load() -> dict[str, Any]:
    global _cache, _load_failed
    if _cache is None:
        if not os.path.exists(_FILE):
            _cache = {}
            return _cache
        try:
            with open(_FILE, encoding='utf-8') as f:
                data = json.load(f)
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


def _save(d: dict[str, Any]) -> None:
    global _cache
    _cache = d
    try:
        with open(_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
    except Exception:
        _log.exception('save failed')


def get_active() -> tuple[str | None, str | None]:
    """Return (plan_id, start_date_str_or_None) for the currently selected plan."""
    d = _load()
    plan_id = d.get('plan_id')
    if not plan_id:
        return None, None
    start_date = d.get('start_dates', {}).get(plan_id)
    return plan_id, start_date


def set_plan(plan_id: str) -> None:
    d = _load()
    d['plan_id'] = plan_id
    _save(d)


def set_start_date(plan_id: str, date_str: str) -> None:
    d = _load()
    d['plan_id'] = plan_id
    d.setdefault('start_dates', {})[plan_id] = date_str
    _save(d)


def clear_start_date(plan_id: str) -> None:
    d = _load()
    d.setdefault('start_dates', {}).pop(plan_id, None)
    _save(d)


def get_completed(plan_id: str) -> set[int]:
    return set(_load().get('completed', {}).get(plan_id, []))


def set_day_done(plan_id: str, day_idx: int, done: bool) -> None:
    d = _load()
    comp = d.setdefault('completed', {}).setdefault(plan_id, [])
    if done and day_idx not in comp:
        comp.append(day_idx)
    elif not done and day_idx in comp:
        comp.remove(day_idx)
    _save(d)


def today_index(start_date_str: str) -> int:
    """0-based day index for today. Negative if plan hasn't started yet."""
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(start_date_str)).days
    except Exception:
        return 0
