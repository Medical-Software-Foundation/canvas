"""Tests for provider_availability.engine.expired."""

import datetime as dt
from datetime import date
from unittest.mock import call, patch

from provider_availability.engine.expired import (
    count_expired,
    expired_summary,
    remove_expired,
    snooze_expired,
)
from provider_availability.engine.models import (
    AdminBlock,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
)

MODULE = "provider_availability.engine.expired"
TODAY = date(2026, 10, 5)  # cutoff is 2026-09-05


def _rule(pid, end, overrides=()):
    return ProviderAvailabilityRule(
        provider_id=pid, id=f"r-{pid}-{end}", effective_end=end,
        date_overrides=[DateOverride(date=d) for d in overrides],
    )


def _block(pid, bid, day):
    start = dt.datetime.combine(day, dt.time(9))
    return AdminBlock(provider_id=pid, id=bid, start=start, end=start + dt.timedelta(hours=1))


class _Store:
    """Patches the storage reads with one sample practice: p1 has old items, p2 has one, p3 has none."""

    def __init__(self):
        self.old_rule = _rule("p1", date(2026, 9, 1))
        self.recent_rule = _rule("p1", date(2026, 9, 20), overrides=[date(2026, 8, 1), date(2026, 9, 10)])
        self.p3_rule = _rule("p3", None)
        self.old_block = _block("p1", "b-old", date(2026, 9, 1))
        self.edge_block = _block("p1", "b-edge", date(2026, 9, 5))  # on the cutoff: kept
        self.p2_block = _block("p2", "b-p2", date(2026, 8, 15))
        self.old_rb = RecurringBlock(provider_id="p1", id="rb-old", effective_end=date(2026, 8, 31))
        self.live_rb = RecurringBlock(provider_id="p1", id="rb-live", effective_end=None)

    def patches(self):
        return [
            patch(f"{MODULE}.get_all_rules", return_value=[self.old_rule, self.recent_rule, self.p3_rule]),
            patch(f"{MODULE}.get_all_blocks", return_value=[self.old_block, self.edge_block, self.p2_block]),
            patch(f"{MODULE}.get_all_recurring_blocks", return_value=[self.old_rb, self.live_rb]),
        ]


def _with(store, *extra):
    from contextlib import ExitStack
    stack = ExitStack()
    for p in store.patches() + list(extra):
        stack.enter_context(p)
    return stack


class TestCountExpired:
    def test_counts_per_provider_only_past_the_cutoff(self):
        store = _Store()
        with _with(store):
            counts = count_expired(["p1", "p2", "p3"], TODAY)
        # p1: old rule, one old override, old block, old recurring block. p3 has nothing.
        assert counts == {"p1": 4, "p2": 1}

    def test_only_requested_providers(self):
        store = _Store()
        with _with(store):
            assert count_expired(["p2"], TODAY) == {"p2": 1}


class TestExpiredSummary:
    def test_snoozed_providers_are_left_out_until_the_snooze_ends(self):
        store = _Store()
        with _with(store, patch(f"{MODULE}.get_expired_snoozes", return_value={"p1": "2026-10-20", "p2": "2026-10-05"})):
            summary = expired_summary(["p1", "p2", "p3"], TODAY)
        # p1 is snoozed past today; p2's snooze ended today, so it shows again
        assert summary == {"count": 1, "provider_ids": ["p2"]}

    def test_nothing_for_an_empty_scope(self):
        store = _Store()
        with _with(store, patch(f"{MODULE}.get_expired_snoozes", return_value={})):
            assert expired_summary([], TODAY) == {"count": 0, "provider_ids": []}


class TestRemoveExpired:
    def test_drops_only_the_given_providers_items_past_the_cutoff(self):
        store = _Store()
        with _with(store), \
             patch(f"{MODULE}.delete_rule_by_id") as del_rule, \
             patch(f"{MODULE}.delete_block") as del_block, \
             patch(f"{MODULE}.delete_recurring_block") as del_rb, \
             patch(f"{MODULE}.delete_event_ids") as del_ids, \
             patch(f"{MODULE}.save_rule") as save:
            removed = remove_expired(["p1"], TODAY)

        assert removed == 4
        assert del_rule.mock_calls == [call("p1", store.old_rule.id)]
        # p2's old block and p1's block on the cutoff are untouched
        assert del_block.mock_calls == [call("p1", "b-old")]
        assert del_rb.mock_calls == [call("p1", "rb-old")]
        assert del_ids.mock_calls == [call(store.old_rule.id), call("b-old"), call("rb-old")]
        assert save.mock_calls == [call(store.recent_rule)]
        assert [o.date for o in store.recent_rule.date_overrides] == [date(2026, 9, 10)]

    def test_nothing_to_remove_writes_nothing(self):
        store = _Store()
        with _with(store), patch(f"{MODULE}.save_rule") as save, patch(f"{MODULE}.delete_block") as del_block:
            assert remove_expired(["p3"], TODAY) == 0
        assert save.mock_calls == []
        assert del_block.mock_calls == []


class TestSnoozeExpired:
    def test_sets_thirty_days_per_provider_and_drops_ended_snoozes(self):
        existing = {"p9": "2026-10-01", "p8": "2026-11-01"}
        with patch(f"{MODULE}.get_expired_snoozes", return_value=existing), \
             patch(f"{MODULE}.set_expired_snoozes") as set_snoozes:
            until = snooze_expired(["p1", "p2"], TODAY)
        assert until == date(2026, 11, 4)
        # p9's snooze already ended, so it is dropped; p8's is kept
        assert set_snoozes.mock_calls == [call({"p8": "2026-11-01", "p1": "2026-11-04", "p2": "2026-11-04"})]
