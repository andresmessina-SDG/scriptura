"""List rows carry a short date. "Edited 28 September 2026" on every mark
row took 24 characters and cut "John 3 — Chapter Note" to "John 3 — Chapt…"
at the 340px sidebar. The editor's header keeps the full date."""
import datetime as dt

import annotations_window as aw
import i18n

TODAY = dt.date(2026, 9, 28)


def test_short_dates():
    assert i18n.format_short_date(TODAY, TODAY) == 'Today'
    assert i18n.format_short_date(dt.date(2026, 9, 27), TODAY) == 'Yesterday'
    assert i18n.format_short_date(dt.date(2026, 9, 14), TODAY) == '14 Sep'
    assert i18n.format_short_date(dt.date(2025, 12, 1), TODAY) == '1 Dec 2025'
    # Tomorrow is not "yesterday", and a future date is still a date.
    assert i18n.format_short_date(dt.date(2026, 9, 29), TODAY) == '29 Sep'


def test_mark_rows_say_edited_briefly_and_the_header_in_full():
    mark = {'modified': '2026-09-28T09:00:00'}
    assert aw._edited_label(mark, short=True, today=TODAY) == 'Edited today'
    mark = {'modified': '2026-09-27T09:00:00'}
    assert aw._edited_label(mark, short=True, today=TODAY) == 'Edited yesterday'
    mark = {'modified': '2026-03-02T09:00:00'}
    assert aw._edited_label(mark, short=True, today=TODAY) == 'Edited 2 Mar'
    assert aw._edited_label(mark) == 'Edited 2 March 2026'


def test_entry_and_sermon_rows_are_short():
    assert aw._entry_day_label({'date': '2026-09-20'}, today=TODAY) == '20 Sep'
    assert aw._preached_label({'preached': ['2026-09-28']},
                              today=TODAY) == 'Today'
