"""Tests for provider_availability.engine.overlap."""

import datetime as dt
from datetime import date, time
from unittest.mock import MagicMock, call, patch

from provider_availability.engine.models import ProviderAvailabilityRule, TimeWindow
from provider_availability.engine.overlap import _date_ranges_overlap, check_rule_overlap


# ── _date_ranges_overlap ──────────────────────────────────────────────


class TestDateRangesOverlap:
    def test_both_unbounded(self):
        assert _date_ranges_overlap(None, None, None, None) is True

    def test_a_unbounded_b_bounded(self):
        assert _date_ranges_overlap(
            None, None, date(2026, 1, 1), date(2026, 12, 31)
        ) is True

    def test_non_overlapping_a_before_b(self):
        assert _date_ranges_overlap(
            date(2026, 1, 1), date(2026, 3, 31),
            date(2026, 4, 1), date(2026, 6, 30),
        ) is False

    def test_non_overlapping_b_before_a(self):
        assert _date_ranges_overlap(
            date(2026, 4, 1), date(2026, 6, 30),
            date(2026, 1, 1), date(2026, 3, 31),
        ) is False

    def test_overlapping(self):
        assert _date_ranges_overlap(
            date(2026, 1, 1), date(2026, 6, 30),
            date(2026, 3, 1), date(2026, 12, 31),
        ) is True

    def test_adjacent_dates_no_overlap(self):
        # March 31 < April 1 → no overlap
        assert _date_ranges_overlap(
            date(2026, 1, 1), date(2026, 3, 31),
            date(2026, 4, 1), date(2026, 6, 30),
        ) is False

    def test_same_end_and_start_overlaps(self):
        # March 31 end == March 31 start → overlap (not strictly less than)
        assert _date_ranges_overlap(
            date(2026, 1, 1), date(2026, 3, 31),
            date(2026, 3, 31), date(2026, 6, 30),
        ) is True

    def test_a_end_unbounded(self):
        assert _date_ranges_overlap(
            date(2026, 1, 1), None,
            date(2026, 3, 1), date(2026, 6, 30),
        ) is True

    def test_b_start_unbounded(self):
        assert _date_ranges_overlap(
            date(2026, 1, 1), date(2026, 6, 30),
            None, date(2026, 12, 31),
        ) is True


# ── check_rule_overlap ────────────────────────────────────────────────


class TestCheckRuleOverlap:
    def _make_rule(self, rule_id="r1", provider_id="p1", schedule=None, is_active=True,
                   eff_start=None, eff_end=None):
        if schedule is None:
            schedule = {"monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))]}
        return ProviderAvailabilityRule(
            id=rule_id,
            provider_id=provider_id,
            weekly_schedule=schedule,
            is_active=is_active,
            effective_start=eff_start,
            effective_end=eff_end,
        )

    def test_no_existing_rules(self):
        new_rule = self._make_rule("new")
        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = []

            result = check_rule_overlap(new_rule)

            assert mock_get.mock_calls == [call("p1")]
            assert result is None

    def test_overlapping_time_windows(self):
        existing = self._make_rule("existing", schedule={
            "monday": [TimeWindow(start=dt.time(10, 0), end=dt.time(14, 0))],
        })
        new_rule = self._make_rule("new", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })

        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = [existing]

            result = check_rule_overlap(new_rule)

            assert mock_get.mock_calls == [call("p1")]
            assert result is not None
            assert "Monday" in result
            assert "09:00-12:00" in result

    def test_non_overlapping_time_windows(self):
        existing = self._make_rule("existing", schedule={
            "monday": [TimeWindow(start=dt.time(13, 0), end=dt.time(17, 0))],
        })
        new_rule = self._make_rule("new", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })

        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = [existing]

            result = check_rule_overlap(new_rule)

            assert mock_get.mock_calls == [call("p1")]
            assert result is None

    def test_different_days_no_overlap(self):
        existing = self._make_rule("existing", schedule={
            "tuesday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })
        new_rule = self._make_rule("new", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })

        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = [existing]

            result = check_rule_overlap(new_rule)

            assert mock_get.mock_calls == [call("p1")]
            assert result is None

    def test_excluded_rule_id(self):
        existing = self._make_rule("same-rule", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })
        new_rule = self._make_rule("same-rule", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })

        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = [existing]

            result = check_rule_overlap(new_rule, exclude_rule_id="same-rule")

            assert mock_get.mock_calls == [call("p1")]
            assert result is None

    def test_inactive_rule_skipped(self):
        existing = self._make_rule("existing", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        }, is_active=False)
        new_rule = self._make_rule("new", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        })

        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = [existing]

            result = check_rule_overlap(new_rule)

            assert mock_get.mock_calls == [call("p1")]
            assert result is None

    def test_non_overlapping_date_ranges(self):
        existing = self._make_rule("existing", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        }, eff_start=date(2026, 1, 1), eff_end=date(2026, 3, 31))
        new_rule = self._make_rule("new", schedule={
            "monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(12, 0))],
        }, eff_start=date(2026, 4, 1), eff_end=date(2026, 6, 30))

        with patch("provider_availability.engine.overlap.get_rules_for_provider") as mock_get:
            mock_get.return_value = [existing]

            result = check_rule_overlap(new_rule)

            assert mock_get.mock_calls == [call("p1")]
            assert result is None


# ── date overrides against other rules ─────────────────────────────────


def _rule(rule_id, start, end, overrides=None):
    return ProviderAvailabilityRule(
        id=rule_id, provider_id="p1", is_active=True,
        weekly_schedule={"monday": [TimeWindow(start=time(start), end=time(end))]},
        date_overrides=overrides or [],
    )


class TestOverrideOverlap:
    MONDAY = date(2026, 12, 7)

    def test_override_stretching_into_another_rule_is_rejected(self):
        from provider_availability.engine.models import DateOverride
        from provider_availability.engine.overlap import check_override_overlap

        morning, afternoon = _rule("am", 9, 12), _rule("pm", 13, 17)
        stretch = DateOverride(date=self.MONDAY, time_windows=[TimeWindow(start=time(9), end=time(17))])
        msg = check_override_overlap(morning, stretch, existing_rules=[morning, afternoon])
        assert msg and "2026-12-07" in msg and "13:00-17:00" in msg

    def test_override_inside_its_own_hours_is_fine(self):
        from provider_availability.engine.models import DateOverride
        from provider_availability.engine.overlap import check_override_overlap

        morning, afternoon = _rule("am", 9, 12), _rule("pm", 13, 17)
        shorter = DateOverride(date=self.MONDAY, time_windows=[TimeWindow(start=time(9), end=time(11))])
        assert check_override_overlap(morning, shorter, existing_rules=[morning, afternoon]) is None

    def test_other_rule_closed_that_day_is_fine(self):
        from provider_availability.engine.models import DateOverride
        from provider_availability.engine.overlap import check_override_overlap

        closed = DateOverride(date=self.MONDAY, is_closed=True, time_windows=[])
        morning, afternoon = _rule("am", 9, 12), _rule("pm", 13, 17, overrides=[closed])
        stretch = DateOverride(date=self.MONDAY, time_windows=[TimeWindow(start=time(9), end=time(17))])
        assert check_override_overlap(morning, stretch, existing_rules=[morning, afternoon]) is None

    def test_rule_edit_into_another_rules_override_day_is_rejected(self):
        """The afternoon rule's one-day override reaches 11:00; a new 10-12 morning rule hits it."""
        from provider_availability.engine.models import DateOverride

        early = DateOverride(date=self.MONDAY, time_windows=[TimeWindow(start=time(11), end=time(17))])
        afternoon = _rule("pm", 13, 17, overrides=[early])
        new_morning = _rule("am", 10, 12)
        msg = check_rule_overlap(new_morning, existing_rules=[afternoon])
        assert msg and "2026-12-07" in msg
