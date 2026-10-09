"""Tests for provider_availability.engine.expired."""

import datetime as dt
from contextlib import ExitStack
from datetime import date, time
from unittest.mock import call, patch

from provider_availability.engine.expired import (
    expired_summary,
    list_expired,
    remove_expired,
    snooze_expired,
)
from provider_availability.engine.models import (
    AdminBlock,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)

MODULE = "provider_availability.engine.expired"
TODAY = date(2026, 10, 5)  # cutoff is 2026-09-05


def _rule(pid, rid, end, overrides=(), schedule=None, reason=""):
    return ProviderAvailabilityRule(
        provider_id=pid, id=rid, effective_end=end, reason=reason,
        weekly_schedule=schedule or {},
        date_overrides=[DateOverride(date=d, is_closed=True, reason="Half day") for d in overrides],
    )


def _block(pid, bid, day, reason=""):
    start = dt.datetime.combine(day, time(9))
    return AdminBlock(provider_id=pid, id=bid, start=start, end=start + dt.timedelta(hours=4, minutes=30), reason=reason)


class _Store:
    """p1 has old items of every kind; p2 has one old block; p3 has nothing old."""

    def __init__(self):
        mwf = {d: [TimeWindow(start=time(9), end=time(15))] for d in ("monday", "wednesday", "friday")}
        self.old_rule = _rule("p1", "r-old", date(2026, 9, 1), schedule=mwf, reason="Office hours")
        self.recent_rule = _rule("p1", "r-recent", date(2026, 9, 20), overrides=[date(2026, 8, 1), date(2026, 9, 10)])
        self.p3_rule = _rule("p3", "r-p3", None)
        self.old_block = _block("p1", "b-old", date(2026, 9, 1), reason="Seminar")
        self.edge_block = _block("p1", "b-edge", date(2026, 9, 5))  # on the cutoff: kept
        self.p2_block = _block("p2", "b-p2", date(2026, 8, 15))
        self.old_hold = RecurringBlock(provider_id="p1", id="rb-old", effective_end=date(2026, 8, 31), hold_type="next_day",
                                       weekly_schedule={"tuesday": [TimeWindow(start=time(13), end=time(15))]})
        self.live_rb = RecurringBlock(provider_id="p1", id="rb-live", effective_end=None)

    def patches(self):
        return [
            patch(f"{MODULE}.get_all_rules", return_value=[self.old_rule, self.recent_rule, self.p3_rule]),
            patch(f"{MODULE}.get_all_blocks", return_value=[self.old_block, self.edge_block, self.p2_block]),
            patch(f"{MODULE}.get_all_recurring_blocks", return_value=[self.old_hold, self.live_rb]),
        ]


def _with(store, *extra):
    stack = ExitStack()
    for p in store.patches() + list(extra):
        stack.enter_context(p)
    return stack


class TestListExpired:
    def test_lists_each_old_item_with_readable_details(self):
        with _with(_Store()):
            items = list_expired(["p1", "p2", "p3"], TODAY)
        by_key = {i["key"]: i for i in items}
        assert sorted(by_key) == ["block:b-old", "block:b-p2", "override:r-recent:2026-08-01", "recurring:rb-old", "rule:r-old"]
        assert by_key["rule:r-old"] == {"key": "rule:r-old", "provider_id": "p1", "kind": "available",
                                         "when": "Mon, Wed, Fri 9:00 AM – 3:00 PM", "reason": "Office hours", "ended": "2026-09-01"}
        assert by_key["block:b-old"]["when"] == "Tue 9/1 9:00 AM – 1:30 PM"
        assert by_key["override:r-recent:2026-08-01"]["when"] == "Sat 8/1 closed"
        assert by_key["recurring:rb-old"]["kind"] == "hold"
        assert by_key["recurring:rb-old"]["when"] == "Tue 1:00 PM – 3:00 PM"

    def test_grouped_by_provider_then_oldest_first(self):
        with _with(_Store()):
            items = list_expired(["p1", "p2"], TODAY)
        assert [(i["provider_id"], i["ended"]) for i in items] == [
            ("p1", "2026-08-01"), ("p1", "2026-08-31"), ("p1", "2026-09-01"), ("p1", "2026-09-01"), ("p2", "2026-08-15")]

    def test_only_requested_providers(self):
        with _with(_Store()):
            assert [i["key"] for i in list_expired(["p2"], TODAY)] == ["block:b-p2"]


class TestExpiredSummary:
    def test_snoozed_items_are_left_out_until_the_snooze_ends(self):
        snoozes = {"rule:r-old": "2026-10-20", "block:b-p2": "2026-10-05"}
        with _with(_Store(), patch(f"{MODULE}.get_expired_snoozes", return_value=snoozes)):
            summary = expired_summary(["p1", "p2"], TODAY)
        keys = [i["key"] for i in summary["items"]]
        # r-old is snoozed past today; b-p2's snooze ended today, so it shows again
        assert "rule:r-old" not in keys
        assert "block:b-p2" in keys
        assert summary["count"] == 4


class TestRemoveExpired:
    def test_drops_only_picked_items_in_scope_and_past_the_cutoff(self):
        store = _Store()
        picked = ["rule:r-old", "override:r-recent:2026-08-01", "block:b-old", "block:b-edge", "block:b-p2", "recurring:rb-old"]
        with _with(store), \
             patch(f"{MODULE}.delete_rule_by_id") as del_rule, \
             patch(f"{MODULE}.delete_block") as del_block, \
             patch(f"{MODULE}.delete_recurring_block") as del_rb, \
             patch(f"{MODULE}.delete_event_ids") as del_ids, \
             patch(f"{MODULE}.save_rule") as save:
            removed = remove_expired(picked, ["p1"], TODAY)

        assert removed == 4
        assert del_rule.mock_calls == [call("p1", "r-old")]
        # b-edge is on the cutoff and b-p2 belongs to a provider outside the scope
        assert del_block.mock_calls == [call("p1", "b-old")]
        assert del_rb.mock_calls == [call("p1", "rb-old")]
        assert del_ids.mock_calls == [call("r-old"), call("b-old"), call("rb-old")]
        assert save.mock_calls == [call(store.recent_rule)]
        assert [o.date for o in store.recent_rule.date_overrides] == [date(2026, 9, 10)]

    def test_unpicked_items_are_untouched(self):
        with _with(_Store()), patch(f"{MODULE}.save_rule") as save, patch(f"{MODULE}.delete_block") as del_block, \
             patch(f"{MODULE}.delete_rule_by_id") as del_rule, patch(f"{MODULE}.delete_recurring_block") as del_rb:
            assert remove_expired([], ["p1", "p2"], TODAY) == 0
        assert save.mock_calls == del_block.mock_calls == del_rule.mock_calls == del_rb.mock_calls == []


class TestSnoozeExpired:
    def test_sets_thirty_days_per_item_and_drops_ended_snoozes(self):
        existing = {"block:old": "2026-10-01", "rule:kept": "2026-11-01"}
        with patch(f"{MODULE}.get_expired_snoozes", return_value=existing), \
             patch(f"{MODULE}.set_expired_snoozes") as set_snoozes:
            until = snooze_expired(["rule:a", "block:b"], TODAY)
        assert until == date(2026, 11, 4)
        assert set_snoozes.mock_calls == [call({"rule:kept": "2026-11-01", "rule:a": "2026-11-04", "block:b": "2026-11-04"})]
