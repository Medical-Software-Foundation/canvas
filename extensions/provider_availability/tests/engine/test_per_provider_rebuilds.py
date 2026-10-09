"""Lead-time and hold events are per provider, so they are rebuilt once per provider.

Building them per rule or per hold block made each one delete the others' events.
"""

import datetime as dt
from datetime import datetime
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

from tests.conftest import QS

from provider_availability.cron.cache_refresh import _refresh_hold_blocks, _refresh_lead_time_blocks
from provider_availability.engine.event_sync import (
    build_delete_recurring_block_effects,
    build_recurring_block_sync_effects,
    build_recurring_blocks_resync_effects,
    build_provider_hold_refresh_effects,
    build_provider_lead_time_effects,
)
from provider_availability.engine.models import (
    BookingInterval,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)

MODULE = "provider_availability.engine.event_sync"
CR_MODULE = "provider_availability.cron.cache_refresh"
PROVIDER_ID = "provider-uuid-123"
TZ = ZoneInfo("US/Eastern")


def _lead_rule(rule_id: str, start: int, end: int, hours: int = 8) -> ProviderAvailabilityRule:
    return ProviderAvailabilityRule(
        id=rule_id,
        provider_id=PROVIDER_ID,
        booking_interval=BookingInterval(min_lead_hours=hours),
        weekly_schedule={"monday": [TimeWindow(start=dt.time(start, 0), end=dt.time(end, 0))]},
    )


def _hold(block_id: str, provider_id: str = PROVIDER_ID, hold_type: str = "same_day") -> RecurringBlock:
    return RecurringBlock(
        id=block_id, provider_id=provider_id, reason="Hold", hold_type=hold_type, is_active=True,
        weekly_schedule={"monday": [TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))]},
    )


def _build_lead(rules: list, existing: list) -> tuple[list, MagicMock, MagicMock]:
    """Run the per-provider lead-time build at Monday 10:00 Eastern."""
    with patch(f"{MODULE}.resolve_provider_name", return_value="Jane Doe"), \
         patch(f"{MODULE}.get_admin_calendar_id", return_value=("admin-cal-1", [])), \
         patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")]), \
         patch(f"{MODULE}.provider_tz", return_value=TZ), \
         patch(f"{MODULE}.to_utc", side_effect=lambda x: x), \
         patch(f"{MODULE}.EventModel.objects") as mock_events, \
         patch(f"{MODULE}.EventEffect") as mock_effect, \
         patch(f"{MODULE}.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 2, 10, 0, tzinfo=TZ)
        mock_datetime.combine = datetime.combine
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        mock_events.filter.return_value = QS(existing)
        result = build_provider_lead_time_effects(PROVIDER_ID, rules)
    return result, mock_events, mock_effect


class TestProviderLeadTime:
    def test_two_rules_share_one_query_and_one_set_of_events(self):
        """Morning and afternoon rules: existing events are read and deleted once, and
        each rule's slice of the lead window is created (10-12 and 13-18)."""
        old = MagicMock(id="old-lead-1")
        result, mock_events, mock_effect = _build_lead(
            [_lead_rule("am", 9, 12), _lead_rule("pm", 13, 17)], [old]
        )

        assert mock_events.filter.call_count == 1
        assert mock_effect.call_args_list.count(call(event_id="old-lead-1")) == 1
        created = [c.kwargs for c in mock_effect.call_args_list if "starts_at" in c.kwargs]
        assert [(c["starts_at"].hour, c["ends_at"].hour) for c in created] == [(10, 12), (13, 17)]
        assert len(result) == 3  # 1 delete + 2 creates

    def test_overlapping_rules_merge_into_one_event(self):
        result, _, mock_effect = _build_lead(
            [_lead_rule("a", 9, 14), _lead_rule("b", 12, 17)], []
        )

        created = [c.kwargs for c in mock_effect.call_args_list if "starts_at" in c.kwargs]
        assert [(c["starts_at"].hour, c["ends_at"].hour) for c in created] == [(10, 17)]
        assert len(result) == 1

    def test_rules_without_lead_time_clear_leftover_events(self):
        """Turning lead time off removes the Lead Time events that would otherwise keep blocking."""
        with patch(f"{MODULE}.get_admin_calendar_id") as mock_cal, \
             patch(f"{MODULE}.delete_provider_lead_time_events", return_value=["del-lead"]) as mock_clear:
            result = build_provider_lead_time_effects(PROVIDER_ID, [_lead_rule("z", 9, 17, hours=0)])
        assert result == ["del-lead"]
        assert mock_clear.mock_calls == [call(PROVIDER_ID)]
        assert mock_cal.mock_calls == []

    def test_ended_rule_keeps_no_window_open(self):
        """A 48h rule that ended yesterday adds nothing; the current 2h rule sets the window."""
        ended = _lead_rule("old", 9, 17, hours=48)
        ended.effective_end = dt.date(2026, 3, 1)  # the Sunday before "now"
        current = _lead_rule("new", 9, 17, hours=2)
        result, _, mock_effect = _build_lead([ended, current], [])

        created = [c.kwargs for c in mock_effect.call_args_list if "starts_at" in c.kwargs]
        assert [(c["starts_at"].hour, c["ends_at"].hour) for c in created] == [(10, 12)]
        assert len(result) == 1


class TestProviderHoldRefresh:
    @patch(f"{MODULE}._build_hold_block_events", side_effect=lambda b: [f"create-{b.id}"])
    @patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")])
    def test_two_hold_blocks_delete_once_and_recreate_both(self, mock_cals, mock_build):
        first, second = _hold("h1"), _hold("h2")
        with patch(f"{MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = QS([MagicMock(id="e1"), MagicMock(id="e2")])
            result = build_provider_hold_refresh_effects(PROVIDER_ID, [first, second])

        assert mock_events.filter.call_count == 1
        assert mock_cals.mock_calls == [call(PROVIDER_ID)]
        assert mock_build.mock_calls == [call(first), call(second)]
        assert len(result) == 4  # 2 deletes + 2 creates
        assert result[-2:] == ["create-h1", "create-h2"]

    @patch(f"{MODULE}.get_admin_calendars")
    def test_no_active_holds_reads_nothing(self, mock_cals):
        inactive = _hold("h1")
        inactive.is_active = False
        assert build_provider_hold_refresh_effects(PROVIDER_ID, [inactive, _hold("b", hold_type="none")]) == []
        assert mock_cals.mock_calls == []


class TestDeleteHoldRebuildsOthers:
    @patch(f"{MODULE}._build_hold_block_events", side_effect=lambda b: [f"create-{b.id}"])
    @patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")])
    def test_other_active_holds_are_recreated(self, mock_cals, mock_build):
        removed, other = _hold("removed"), _hold("other")
        inactive = _hold("inactive")
        inactive.is_active = False
        plain = _hold("plain", hold_type="none")
        with patch(f"{MODULE}.get_recurring_blocks_for_provider", return_value=[removed, other, inactive, plain]), \
             patch(f"{MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = QS([MagicMock(id="hold-1")])
            result = build_delete_recurring_block_effects(PROVIDER_ID, removed)

        assert mock_build.mock_calls == [call(other)]
        assert len(result) == 2  # hold delete + other hold recreated
        assert result[-1] == "create-other"


class TestResyncSeveralBlocks:
    """Timezone changes, override saves, group edits and installs re-sync many blocks at once."""

    @patch(f"{MODULE}._draw_recurring_block_events", side_effect=lambda b: [f"draw-{b.id}"])
    @patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")])
    def test_two_holds_are_cleared_once_and_drawn_once_each(self, mock_cals, mock_draw):
        first, second = _hold("h1"), _hold("h2")
        with patch(f"{MODULE}.get_recurring_blocks_for_provider", return_value=[first, second]), \
             patch(f"{MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = QS([MagicMock(id="e1"), MagicMock(id="e2")])
            result = build_recurring_blocks_resync_effects([first, second])

        assert mock_events.filter.call_count == 1
        assert mock_draw.mock_calls == [call(first), call(second)]
        assert result[2:] == ["draw-h1", "draw-h2"]
        assert len(result) == 4  # each old hold event deleted once, each hold drawn once

    @patch(f"{MODULE}._draw_recurring_block_events", side_effect=lambda b: [f"draw-{b.id}"])
    @patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")])
    def test_deleting_a_block_redraws_others_with_the_same_reason(self, mock_cals, mock_draw):
        lunch_a = _hold("a", hold_type="none")
        lunch_b = _hold("b", hold_type="none")
        meeting = _hold("m", hold_type="none")
        meeting.reason = "Meeting"
        with patch(f"{MODULE}.get_recurring_blocks_for_provider", return_value=[lunch_a, lunch_b, meeting]), \
             patch(f"{MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = QS([MagicMock(id="e1")])
            result = build_delete_recurring_block_effects(PROVIDER_ID, lunch_a)

        assert mock_draw.mock_calls == [call(lunch_b)]
        assert result[-1] == "draw-b"

    @patch(f"{MODULE}._draw_recurring_block_events", side_effect=lambda b: [f"draw-{b.id}"])
    @patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")])
    def test_renamed_block_clears_old_and_new_titles(self, mock_cals, mock_draw):
        before = _hold("a", hold_type="none")
        after = _hold("a", hold_type="none")
        after.reason = "Admin time"
        with patch(f"{MODULE}.get_recurring_blocks_for_provider", return_value=[before]), \
             patch(f"{MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = QS([])
            build_recurring_block_sync_effects(after, before)

        titles = mock_events.filter.call_args.kwargs["title__in"]
        assert titles == ["Admin time", "Hold", "Recurring Block"]
        assert mock_draw.mock_calls == [call(after)]


class TestCronGroupsByProvider:
    def test_lead_time_rules_for_one_provider_build_once(self):
        a, b = _lead_rule("a", 9, 12), _lead_rule("b", 13, 17)
        other = _lead_rule("c", 9, 17)
        other.provider_id = "provider-2"
        with patch(f"{CR_MODULE}.get_all_rules", return_value=[a, b, other]), \
             patch(f"{CR_MODULE}.build_provider_lead_time_effects", return_value=[]) as mock_build:
            _refresh_lead_time_blocks()

        assert mock_build.mock_calls == [call(PROVIDER_ID, [a, b]), call("provider-2", [other])]

    def test_hold_blocks_for_one_provider_refresh_once(self):
        a, b = _hold("a"), _hold("b")
        with patch(f"{CR_MODULE}.get_all_recurring_blocks", return_value=[a, b, _hold("n", hold_type="none")]), \
             patch(f"{CR_MODULE}.build_provider_hold_refresh_effects", return_value=[]) as mock_build:
            _refresh_hold_blocks()

        assert mock_build.mock_calls == [call(PROVIDER_ID, [a, b])]


class TestLeadTimeRuleTimezone:
    def test_rule_timezone_sets_its_working_hours(self):
        """A Pacific rule on an Eastern provider: 9-5 means 9-5 Pacific, as in its availability events."""
        pacific = _lead_rule("west", 9, 17, hours=8)
        pacific.timezone = "US/Pacific"
        now_eastern = datetime(2026, 3, 2, 10, 0, tzinfo=TZ)  # 7:00 Pacific
        with patch(f"{MODULE}.resolve_provider_name", return_value="Jane Doe"), \
             patch(f"{MODULE}.get_admin_calendar_id", return_value=("admin-cal-1", [])), \
             patch(f"{MODULE}.get_admin_calendars", return_value=[MagicMock(id="admin-cal-1")]), \
             patch(f"{MODULE}.provider_tz", return_value=TZ), \
             patch(f"{MODULE}.to_utc", side_effect=lambda x: x), \
             patch(f"{MODULE}.EventModel.objects") as mock_events, \
             patch(f"{MODULE}.EventEffect") as mock_effect, \
             patch(f"{MODULE}.datetime") as mock_datetime:
            mock_datetime.now.side_effect = lambda tz=None: now_eastern.astimezone(tz)
            mock_datetime.combine = datetime.combine
            mock_events.filter.return_value = QS([])
            build_provider_lead_time_effects(PROVIDER_ID, [pacific])

        created = [c.kwargs for c in mock_effect.call_args_list if "starts_at" in c.kwargs]
        # 9:00-15:00 Pacific is 12:00-18:00 Eastern
        assert [(c["starts_at"].astimezone(TZ).hour, c["ends_at"].astimezone(TZ).hour) for c in created] == [(12, 18)]
