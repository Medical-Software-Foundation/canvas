"""Tests for the shared recurrence date calculation utility."""

import datetime
from zoneinfo import ZoneInfo

import pytest

from facility_recurring_scheduler.utils.recurrence import calculate_recurrence_date


class TestCalculateRecurrenceDate:
    """Tests for calculate_recurrence_date function."""

    def test_daily_recurrence(self) -> None:
        """Test daily recurrence advances by the correct number of days."""
        start = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = calculate_recurrence_date(start, 5, "daily", ZoneInfo("America/New_York"))
        assert result.date() == datetime.date(2024, 1, 6)

    def test_weekly_recurrence(self) -> None:
        """Test weekly recurrence advances by the correct number of weeks."""
        start = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = calculate_recurrence_date(start, 2, "weekly", ZoneInfo("America/New_York"))
        assert result.date() == datetime.date(2024, 1, 15)

    def test_every_2_weeks_recurrence(self) -> None:
        """Test every-2-weeks recurrence advances by correct number of fortnights."""
        start = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = calculate_recurrence_date(start, 2, "every 2 weeks", ZoneInfo("America/New_York"))
        # 2 intervals of 2 weeks = 4 weeks = 28 days
        assert result.date() == datetime.date(2024, 1, 29)

    def test_every_3_weeks_recurrence(self) -> None:
        """Test every-3-weeks recurrence advances by correct number of 3-week intervals."""
        start = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = calculate_recurrence_date(start, 2, "every 3 weeks", ZoneInfo("America/New_York"))
        # 2 intervals of 3 weeks = 6 weeks = 42 days
        assert result.date() == datetime.date(2024, 2, 12)

    def test_monthly_recurrence_nth_weekday(self) -> None:
        """Monthly recurs on the same ordinal weekday, not the same calendar date.

        Jan 15 2024 is the 3rd Monday. Two months later is the 3rd Monday of
        March 2024, which is March 18 (not March 15).
        """
        start = datetime.datetime(2024, 1, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = calculate_recurrence_date(start, 2, "monthly", ZoneInfo("America/New_York"))
        assert result.date() == datetime.date(2024, 3, 18)
        assert result.astimezone(ZoneInfo("America/New_York")).weekday() == 0  # Monday

    def test_monthly_recurrence_stays_on_weekday_across_months(self) -> None:
        """Monthly never lands on a different weekday (e.g. a weekend)."""
        # Jan 9 2024 is the 2nd Tuesday
        start = datetime.datetime(2024, 1, 9, 14, 0, tzinfo=ZoneInfo("UTC"))
        eastern = ZoneInfo("America/New_York")
        for count in range(1, 7):
            result = calculate_recurrence_date(start, count, "monthly", eastern)
            local = result.astimezone(eastern)
            assert local.weekday() == 1  # always a Tuesday
            assert (local.day - 1) // 7 + 1 == 2  # always the 2nd Tuesday

    def test_monthly_fifth_weekday_uses_last_weekday(self) -> None:
        """An anchor on the 5th weekday recurs on the *last* such weekday.

        Jan 31 2024 is the 5th Wednesday. February 2024 has only 4 Wednesdays,
        so the next occurrence is the last Wednesday, Feb 28 (not the 29th).
        """
        start = datetime.datetime(2024, 1, 31, 14, 0, tzinfo=ZoneInfo("UTC"))
        eastern = ZoneInfo("America/New_York")
        result = calculate_recurrence_date(start, 1, "monthly", eastern)
        local = result.astimezone(eastern)
        assert local.date() == datetime.date(2024, 2, 28)
        assert local.weekday() == 2  # Wednesday

    def test_monthly_preserves_wall_clock_time(self) -> None:
        """Monthly recurrence preserves the local time-of-day."""
        start = datetime.datetime(2024, 1, 15, 14, 0, tzinfo=ZoneInfo("UTC"))  # 9:00 AM ET
        eastern = ZoneInfo("America/New_York")
        result = calculate_recurrence_date(start, 1, "monthly", eastern)
        assert result.astimezone(eastern).hour == 9

    def test_unknown_recurrence_raises_value_error(self) -> None:
        """Test that unknown recurrence types raise ValueError."""
        start = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        with pytest.raises(ValueError, match="Unknown recurrence type"):
            calculate_recurrence_date(start, 1, "biweekly", ZoneInfo("America/New_York"))

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Test that naive datetimes are treated as UTC."""
        start = datetime.datetime(2024, 1, 1, 14, 0)
        result = calculate_recurrence_date(start, 1, "daily", ZoneInfo("America/New_York"))
        assert result.tzinfo is not None
        assert result.date() == datetime.date(2024, 1, 2)

    def test_result_is_utc(self) -> None:
        """Test that the result is always in UTC."""
        start = datetime.datetime(2024, 1, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
        result = calculate_recurrence_date(start, 1, "daily", ZoneInfo("America/Chicago"))
        assert result.tzinfo == ZoneInfo("UTC")

    def test_dst_spring_forward(self) -> None:
        """Test that wall-clock time is preserved across spring-forward DST transition.

        In 2024, US Eastern DST starts March 10 at 2:00 AM.
        A 9:00 AM ET event should stay at 9:00 AM ET after the transition,
        which means its UTC offset shifts from -5 to -4.
        """
        # March 9, 2024 at 9:00 AM ET = 14:00 UTC (EST, UTC-5)
        start = datetime.datetime(2024, 3, 9, 14, 0, tzinfo=ZoneInfo("UTC"))
        eastern = ZoneInfo("America/New_York")

        result = calculate_recurrence_date(start, 1, "daily", eastern)

        # March 10 at 9:00 AM ET = 13:00 UTC (EDT, UTC-4)
        local_result = result.astimezone(eastern)
        assert local_result.hour == 9
        assert result.hour == 13  # UTC shifted by 1 hour

    def test_dst_spring_forward_every_2_weeks(self) -> None:
        """Test that wall-clock time is preserved across spring-forward for every-2-weeks."""
        # March 2, 2024 at 9:00 AM ET = 14:00 UTC (EST, UTC-5)
        start = datetime.datetime(2024, 3, 2, 14, 0, tzinfo=ZoneInfo("UTC"))
        eastern = ZoneInfo("America/New_York")

        # 1 interval of 2 weeks = March 16 (after DST spring-forward on March 10)
        result = calculate_recurrence_date(start, 1, "every 2 weeks", eastern)

        local_result = result.astimezone(eastern)
        assert local_result.hour == 9  # wall-clock preserved
        assert result.hour == 13  # UTC shifted from 14 to 13

    def test_dst_spring_forward_every_3_weeks(self) -> None:
        """Test that wall-clock time is preserved across spring-forward for every-3-weeks."""
        # Feb 24, 2024 at 9:00 AM ET = 14:00 UTC (EST, UTC-5)
        start = datetime.datetime(2024, 2, 24, 14, 0, tzinfo=ZoneInfo("UTC"))
        eastern = ZoneInfo("America/New_York")

        # 1 interval of 3 weeks = March 16 (after DST spring-forward on March 10)
        result = calculate_recurrence_date(start, 1, "every 3 weeks", eastern)

        local_result = result.astimezone(eastern)
        assert local_result.hour == 9
        assert result.hour == 13

    def test_dst_fall_back(self) -> None:
        """Test that wall-clock time is preserved across fall-back DST transition.

        In 2024, US Eastern DST ends November 3 at 2:00 AM.
        A 9:00 AM ET event should stay at 9:00 AM ET after the transition,
        which means its UTC offset shifts from -4 to -5.
        """
        # November 2, 2024 at 9:00 AM ET = 13:00 UTC (EDT, UTC-4)
        start = datetime.datetime(2024, 11, 2, 13, 0, tzinfo=ZoneInfo("UTC"))
        eastern = ZoneInfo("America/New_York")

        result = calculate_recurrence_date(start, 1, "daily", eastern)

        # November 3 at 9:00 AM ET = 14:00 UTC (EST, UTC-5)
        local_result = result.astimezone(eastern)
        assert local_result.hour == 9
        assert result.hour == 14  # UTC shifted by 1 hour
