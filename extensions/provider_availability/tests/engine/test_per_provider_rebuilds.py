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
    return RecurringBlock(id=block_id, provider_id=provider_id, reason="Hold", hold_type=hold_type, is_active=True)


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

    def test_rules_without_lead_time_build_nothing(self):
        with patch(f"{MODULE}.get_admin_calendar_id") as mock_cal:
            assert build_provider_lead_time_effects(PROVIDER_ID, [_lead_rule("z", 9, 17, hours=0)]) == []
        assert mock_cal.mock_calls == []


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
    @patch(f"{MODULE}.get_event_ids", return_value=["stored-1"])
    def test_other_active_holds_are_recreated(self, mock_ids, mock_cals, mock_build):
        removed, other = _hold("removed"), _hold("other")
        inactive = _hold("inactive")
        inactive.is_active = False
        plain = _hold("plain", hold_type="none")
        with patch(f"{MODULE}.get_recurring_blocks_for_provider", return_value=[removed, other, inactive, plain]), \
             patch(f"{MODULE}.EventModel.objects") as mock_events:
            mock_events.filter.return_value = QS([MagicMock(id="hold-1")])
            result = build_delete_recurring_block_effects(PROVIDER_ID, removed)

        assert mock_build.mock_calls == [call(other)]
        assert len(result) == 3  # stored delete + hold delete + other hold recreated
        assert result[-1] == "create-other"


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
