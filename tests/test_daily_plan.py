from datetime import date
from unittest.mock import patch

from app.models import MasterTask
from app.services.daily_plan import (
    build_calendar_weeks,
    is_work_day,
    next_work_day,
    prev_work_day,
    priority_sort_key,
    resolve_today,
    sort_master_tasks,
)


class TestWorkDays:
    def test_sunday_is_not_a_work_day(self):
        assert is_work_day(date(2026, 8, 9)) is False  # Sunday

    def test_monday_is_a_work_day(self):
        assert is_work_day(date(2026, 8, 10)) is True

    def test_next_work_day_skips_sunday(self):
        assert next_work_day(date(2026, 8, 8)) == date(2026, 8, 10)

    def test_prev_work_day_skips_sunday(self):
        assert prev_work_day(date(2026, 8, 10)) == date(2026, 8, 8)


class TestResolveToday:
    def test_returns_monday_when_today_is_sunday(self):
        with patch("app.services.daily_plan.date") as mock_date:
            mock_date.today.return_value = date(2026, 8, 9)
            assert resolve_today() == date(2026, 8, 10)

    def test_returns_today_on_work_days(self):
        with patch("app.services.daily_plan.date") as mock_date:
            mock_date.today.return_value = date(2026, 8, 11)
            assert resolve_today() == date(2026, 8, 11)


class TestPrioritySortKey:
    def test_zero_priority_sorts_last(self):
        assert priority_sort_key(0) == 999_999

    def test_positive_priority_is_unchanged(self):
        assert priority_sort_key(3) == 3


class TestSortMasterTasks:
    def test_orders_by_priority_then_target_date(self):
        tasks = [
            MasterTask(id=1, task="low", priority=0, target_completion_date=date(2026, 3, 1)),
            MasterTask(id=2, task="high", priority=1, target_completion_date=date(2026, 2, 1)),
            MasterTask(id=3, task="mid", priority=2, target_completion_date=date(2026, 1, 1)),
        ]
        ordered = sort_master_tasks(tasks)
        assert [t.id for t in ordered] == [2, 3, 1]


class TestBuildCalendarWeeks:
    def test_august_2026_starts_on_saturday(self):
        weeks = build_calendar_weeks(2026, 8)
        assert weeks[0][0] is None  # padding before Aug 1 (Saturday)
        assert weeks[0][6] == date(2026, 8, 1)
