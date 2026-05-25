"""Tests for reading_plans.py — pure-Python plan generation, grouping, and
date math. No GTK / SWORD dependency."""

import datetime
import pytest

import reading_plans


# ── _expand: (book, n) → flat list of (book, chapter) ────────────────────────

def test_expand_single_book():
    assert reading_plans._expand([('Genesis', 3)]) == [
        ('Genesis', 1), ('Genesis', 2), ('Genesis', 3)
    ]


def test_expand_multiple_books():
    result = reading_plans._expand([('Ruth', 2), ('Jonah', 4)])
    assert result == [
        ('Ruth', 1), ('Ruth', 2),
        ('Jonah', 1), ('Jonah', 2), ('Jonah', 3), ('Jonah', 4),
    ]


def test_expand_empty():
    assert reading_plans._expand([]) == []


# ── _spread: distribute N chapters across D days ─────────────────────────────

def test_spread_even_division():
    chapters = [('A', i) for i in range(1, 11)]   # 10 chapters
    days = reading_plans._spread(chapters, 5)
    assert len(days) == 5
    assert all(len(d) == 2 for d in days)
    assert days[0] == [('A', 1), ('A', 2)]
    assert days[4] == [('A', 9), ('A', 10)]


def test_spread_uneven_division_distributes_remainder():
    # 7 chapters across 3 days — sizes should be 2, 2, 3 (last larger).
    chapters = [('A', i) for i in range(1, 8)]
    days = reading_plans._spread(chapters, 3)
    sizes = [len(d) for d in days]
    assert sum(sizes) == 7
    assert sizes == [2, 2, 3]


def test_spread_more_days_than_chapters_pads_empty():
    chapters = [('A', 1), ('A', 2)]
    days = reading_plans._spread(chapters, 5)
    assert len(days) == 5
    assert sum(len(d) for d in days) == 2
    # Some days should be empty when there aren't enough chapters.
    assert any(d == [] for d in days)


def test_spread_single_day_gets_everything():
    chapters = [('A', i) for i in range(1, 11)]
    days = reading_plans._spread(chapters, 1)
    assert days == [chapters]


# ── group_readings: contiguous same-book runs ────────────────────────────────

def test_group_readings_single_chapter():
    assert reading_plans.group_readings([('Genesis', 1)]) == [('Genesis', 1, 1)]


def test_group_readings_contiguous_same_book():
    chapters = [('Genesis', 1), ('Genesis', 2), ('Genesis', 3)]
    assert reading_plans.group_readings(chapters) == [('Genesis', 1, 3)]


def test_group_readings_breaks_on_chapter_gap():
    chapters = [('Genesis', 1), ('Genesis', 2), ('Genesis', 5)]
    assert reading_plans.group_readings(chapters) == [
        ('Genesis', 1, 2),
        ('Genesis', 5, 5),
    ]


def test_group_readings_breaks_on_book_change():
    chapters = [('Genesis', 50), ('Exodus', 1), ('Exodus', 2)]
    assert reading_plans.group_readings(chapters) == [
        ('Genesis', 50, 50),
        ('Exodus', 1, 2),
    ]


def test_group_readings_multiple_streams():
    # Blended-plan day: 4 different books.
    chapters = [
        ('Genesis', 1), ('Genesis', 2),
        ('Isaiah', 1),
        ('Matthew', 1),
        ('Psalms', 1), ('Psalms', 2),
    ]
    assert reading_plans.group_readings(chapters) == [
        ('Genesis', 1, 2),
        ('Isaiah', 1, 1),
        ('Matthew', 1, 1),
        ('Psalms', 1, 2),
    ]


def test_group_readings_empty():
    assert reading_plans.group_readings([]) == []


# ── format_passages: human-readable rendering ────────────────────────────────

def test_format_passages_single_chapter():
    assert reading_plans.format_passages([('Genesis', 1)]) == 'Gen 1'


def test_format_passages_contiguous_range_uses_dash():
    result = reading_plans.format_passages([('Genesis', 1), ('Genesis', 2), ('Genesis', 3)])
    # Uses en-dash (–) per the implementation.
    assert 'Gen 1' in result
    assert '–3' in result or '-3' in result   # tolerant: en-dash or hyphen


def test_format_passages_multi_book_uses_separator():
    result = reading_plans.format_passages([('Genesis', 1), ('Matthew', 1)])
    assert 'Gen 1' in result
    assert 'Matt 1' in result
    # Multiple groups separated by middle dot · per the implementation.
    assert '·' in result or '|' in result   # tolerant


def test_format_passages_empty_returns_empty_string():
    assert reading_plans.format_passages([]) == ''


# ── today_index: date arithmetic ─────────────────────────────────────────────

def test_today_index_for_today():
    today = datetime.date.today().isoformat()
    assert reading_plans.today_index(today) == 0


def test_today_index_for_yesterday():
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    # If yesterday was the start, today is day index 1.
    assert reading_plans.today_index(yesterday) == 1


def test_today_index_for_future_date_is_negative():
    future = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    assert reading_plans.today_index(future) == -5


def test_today_index_invalid_format_returns_zero():
    assert reading_plans.today_index('not a date') == 0
    assert reading_plans.today_index('') == 0


# ── Plan catalog ─────────────────────────────────────────────────────────────

def test_get_plans_returns_all_six():
    plans = reading_plans.get_plans()
    assert len(plans) == 6
    ids = {p['id'] for p in plans}
    assert ids == {
        'bible_1_year', 'blended_1_year', 'ot_1_year',
        'nt_90_days', 'psalms_30_days', 'proverbs_31_days',
    }


def test_each_plan_has_required_fields():
    for p in reading_plans.get_plans():
        assert 'id' in p
        assert 'name' in p
        assert 'description' in p
        assert 'total_days' in p
        assert p['total_days'] > 0


def test_get_plan_days_returns_correct_length():
    assert len(reading_plans.get_plan_days('bible_1_year')) == 365
    assert len(reading_plans.get_plan_days('nt_90_days')) == 90
    assert len(reading_plans.get_plan_days('psalms_30_days')) == 30
    assert len(reading_plans.get_plan_days('proverbs_31_days')) == 31


def test_get_plan_days_unknown_id_returns_empty():
    assert reading_plans.get_plan_days('does_not_exist') == []


def test_blended_plan_reads_each_chapter_once():
    """The blended plan's four streams must partition the canon — no book
    read twice. Regression: Psalms/Proverbs once appeared in both the
    Gen–Song stream and their own stream."""
    from collections import Counter
    flat = [ch for day in reading_plans.get_plan_days('blended_1_year')
            for ch in day]
    assert len(flat) == 1189  # whole Bible, exactly once
    assert max(Counter(flat).values()) == 1


# ── Progress persistence ─────────────────────────────────────────────────────

@pytest.fixture
def isolated_plans(tmp_path, monkeypatch):
    """Redirect the persistence file and reset module cache."""
    monkeypatch.setattr(reading_plans, '_FILE', str(tmp_path / 'reading_plans.json'))
    monkeypatch.setattr(reading_plans, '_cache', None)
    return tmp_path


def test_set_and_get_active_plan(isolated_plans):
    reading_plans.set_plan('nt_90_days')
    plan_id, start = reading_plans.get_active()
    assert plan_id == 'nt_90_days'
    assert start is None  # not started yet


def test_set_start_date(isolated_plans):
    reading_plans.set_start_date('nt_90_days', '2026-01-01')
    plan_id, start = reading_plans.get_active()
    assert plan_id == 'nt_90_days'
    assert start == '2026-01-01'


def test_set_day_done_and_get_completed(isolated_plans):
    reading_plans.set_plan('nt_90_days')
    reading_plans.set_day_done('nt_90_days', 0, True)
    reading_plans.set_day_done('nt_90_days', 5, True)
    reading_plans.set_day_done('nt_90_days', 12, True)
    assert reading_plans.get_completed('nt_90_days') == {0, 5, 12}


def test_set_day_done_can_unset(isolated_plans):
    reading_plans.set_plan('nt_90_days')
    reading_plans.set_day_done('nt_90_days', 0, True)
    reading_plans.set_day_done('nt_90_days', 0, False)
    assert reading_plans.get_completed('nt_90_days') == set()


def test_clear_start_date(isolated_plans):
    reading_plans.set_start_date('nt_90_days', '2026-01-01')
    reading_plans.clear_start_date('nt_90_days')
    _, start = reading_plans.get_active()
    assert start is None


def test_get_completed_unknown_plan_returns_empty(isolated_plans):
    assert reading_plans.get_completed('unknown_plan') == set()
