"""Tests for my_schedule.handlers.availability (own availability shading)."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from my_schedule.handlers import availability
from my_schedule.handlers.availability import occurs_on, own_blocks, window_on

NY = ZoneInfo("America/New_York")


def _event(start, end, recurrence=None, **kw):
    return SimpleNamespace(
        id=kw.get("id", 1),
        calendar_id=kw.get("calendar_id", 10),
        title=kw.get("title", "Available"),
        starts_at=start,
        ends_at=end,
        recurrence=recurrence,
        recurrence_ends_at=kw.get("recurrence_ends_at"),
        is_all_day=kw.get("is_all_day", False),
    )


MON_9 = datetime(2026, 10, 26, 9, 0, tzinfo=NY)  # a Monday
MON_17 = datetime(2026, 10, 26, 17, 0, tzinfo=NY)


class TestOccursOn:
    def test_one_off(self) -> None:
        ev = _event(MON_9, MON_17)
        assert occurs_on(ev, date(2026, 10, 26), NY)
        assert not occurs_on(ev, date(2026, 10, 27), NY)

    def test_weekly_byday(self) -> None:
        ev = _event(MON_9, MON_17, "RRULE:FREQ=WEEKLY;BYDAY=MO,WE")
        assert occurs_on(ev, date(2026, 10, 28), NY)  # Wed
        assert not occurs_on(ev, date(2026, 10, 27), NY)  # Tue
        assert not occurs_on(ev, date(2026, 10, 19), NY)  # before first

    def test_weekly_without_byday_uses_first_weekday(self) -> None:
        ev = _event(MON_9, MON_17, "FREQ=WEEKLY")
        assert occurs_on(ev, date(2026, 11, 2), NY)
        assert not occurs_on(ev, date(2026, 11, 3), NY)

    def test_weekly_interval(self) -> None:
        ev = _event(MON_9, MON_17, "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")
        assert not occurs_on(ev, date(2026, 11, 2), NY)
        assert occurs_on(ev, date(2026, 11, 9), NY)

    def test_weekly_interval_counts_calendar_weeks(self) -> None:
        # Every other week on Mon and Wed, first occurrence on a Wednesday.
        wed = datetime(2026, 10, 28, 9, tzinfo=NY)
        ev = _event(wed, wed + timedelta(hours=8), "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE")
        assert not occurs_on(ev, date(2026, 11, 2), NY)  # Monday of the skipped week
        assert occurs_on(ev, date(2026, 11, 9), NY)  # Monday of the next on-week
        assert occurs_on(ev, date(2026, 11, 11), NY)

    def test_daily_interval_and_until(self) -> None:
        ev = _event(MON_9, MON_17, "FREQ=DAILY;INTERVAL=2;UNTIL=20261030T000000Z")
        assert occurs_on(ev, date(2026, 10, 28), NY)
        assert not occurs_on(ev, date(2026, 10, 29), NY)
        assert not occurs_on(ev, date(2026, 11, 1), NY)

    def test_recurrence_ends_at(self) -> None:
        ev = _event(
            MON_9,
            MON_17,
            "FREQ=DAILY",
            recurrence_ends_at=datetime(2026, 10, 27, 12, tzinfo=NY),
        )
        assert occurs_on(ev, date(2026, 10, 27), NY)
        assert not occurs_on(ev, date(2026, 10, 28), NY)

    def test_bad_values_are_safe(self) -> None:
        assert not occurs_on(
            _event(MON_9, MON_17, "FREQ=MONTHLY"), date(2026, 11, 26), NY
        )
        ev = _event(MON_9, MON_17, "FREQ=DAILY;INTERVAL=x;UNTIL=garbage")
        assert occurs_on(ev, date(2026, 10, 29), NY)


class TestWindowOn:
    def test_same_day(self) -> None:
        s, e = window_on(_event(MON_9, MON_17), date(2026, 10, 28), NY)
        assert s == datetime(2026, 10, 28, 9, 0, tzinfo=NY)
        assert e == datetime(2026, 10, 28, 17, 0, tzinfo=NY)

    def test_overnight_keeps_its_full_length(self) -> None:
        ev = _event(
            datetime(2026, 10, 26, 22, tzinfo=NY), datetime(2026, 10, 27, 2, tzinfo=NY)
        )
        start, end = window_on(ev, date(2026, 10, 28), NY)
        assert start == datetime(2026, 10, 28, 22, 0, tzinfo=NY)
        assert end == datetime(2026, 10, 29, 2, 0, tzinfo=NY)

    def test_all_day(self) -> None:
        s, e = window_on(_event(MON_9, MON_17, is_all_day=True), date(2026, 10, 26), NY)
        assert (e - s) == timedelta(days=1)

    def test_empty_window(self) -> None:
        assert window_on(_event(MON_9, MON_9), date(2026, 10, 26), NY) is None


def _staff(first="Jane", last="Doe"):
    return SimpleNamespace(first_name=first, last_name=last)


class TestOwnBlocks:
    def _run(self, calendars, events, children=(), staff=None, start=None, end=None):
        start = start or datetime(2026, 10, 26, 4, tzinfo=timezone.utc)
        end = end or start + timedelta(days=1)
        with (
            patch.object(availability, "Calendar") as cal_model,
            patch.object(availability, "Event") as ev_model,
        ):
            cal_model.objects.filter.return_value = calendars
            chain = ev_model.objects.filter.return_value
            chain.filter.return_value.select_related.return_value = events
            ev_model.objects.filter.side_effect = [chain, list(children)]
            result = own_blocks(staff or _staff(), start, end)
        return result, cal_model

    def test_blank_name_returns_nothing(self) -> None:
        with patch.object(availability, "Calendar") as cal_model:
            assert (
                own_blocks(
                    _staff("", ""),
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc),
                )
                == []
            )
        cal_model.objects.filter.assert_not_called()

    def test_no_calendars(self) -> None:
        result, _ = self._run(calendars=[], events=[])
        assert result == []

    def test_only_own_named_calendars_are_queried(self) -> None:
        _, cal_model = self._run(calendars=[], events=[])
        q = cal_model.objects.filter.call_args.args[0]
        assert "Jane Doe: Clinic" in str(q) and "Jane Doe: Admin" in str(q)

    def test_clinic_and_admin_blocks(self) -> None:
        clinic = SimpleNamespace(
            id=10, title="Jane Doe: Clinic", timezone="America/New_York"
        )
        admin = SimpleNamespace(
            id=11, title="Jane Doe: Admin: Main", timezone="America/New_York"
        )
        other = SimpleNamespace(id=12, title="Jane Doe: Something", timezone="UTC")
        events = [
            _event(MON_9, MON_17, id=1, calendar_id=10),
            _event(
                datetime(2026, 10, 26, 12, tzinfo=NY),
                datetime(2026, 10, 26, 13, tzinfo=NY),
                id=2,
                calendar_id=11,
                title="Lunch",
            ),
        ]
        result, _ = self._run(calendars=[clinic, admin, other], events=events)
        kinds = [(b["kind"], b["title"]) for b in result]
        assert ("available", "Available") in kinds
        assert ("busy", "Lunch") in kinds
        assert all(b["start"] < b["end"] for b in result)

    def test_moved_occurrence_is_skipped(self) -> None:
        clinic = SimpleNamespace(
            id=10, title="Jane Doe: Clinic", timezone="America/New_York"
        )
        weekly = _event(
            datetime(2026, 10, 19, 9, tzinfo=NY),
            datetime(2026, 10, 19, 17, tzinfo=NY),
            "FREQ=WEEKLY",
            id=5,
            calendar_id=10,
        )
        child = SimpleNamespace(
            recurring_parent_event_id=5,
            original_starts_at=datetime(2026, 10, 26, 13, tzinfo=timezone.utc),
        )
        result, _ = self._run(calendars=[clinic], events=[weekly], children=[child])
        assert result == []

    def test_utc_default_timezone(self) -> None:
        clinic = SimpleNamespace(id=10, title="Jane Doe: Clinic", timezone=None)
        ev = _event(
            datetime(2026, 10, 26, 14, tzinfo=timezone.utc),
            datetime(2026, 10, 26, 16, tzinfo=timezone.utc),
            calendar_id=10,
        )
        result, _ = self._run(calendars=[clinic], events=[ev])
        assert result and result[0]["start"].endswith("+00:00")
