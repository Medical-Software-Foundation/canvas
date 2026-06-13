"""Tests for provider_availability.engine.storage."""

import datetime as dt
from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.engine.models import (
    AdminBlock,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)
from provider_availability.engine.storage import (
    CACHE_TTL_SECONDS,
    INDEX_KEY,
    BLOCK_INDEX_KEY,
    RECURRING_BLOCK_INDEX_KEY,
    EVENT_IDS_PREFIX,
    PRACTICE_TZ_KEY,
    INSTALL_SENTINEL_KEY,
    save_rule,
    get_rule_by_id,
    get_rules_for_provider,
    get_all_rules,
    delete_rule_by_id,
    delete_rules_for_provider,
    save_event_ids,
    get_event_ids,
    delete_event_ids,
    save_block,
    get_blocks_for_provider,
    get_block_by_id,
    get_all_blocks,
    delete_block,
    save_recurring_block,
    get_recurring_blocks_for_provider,
    get_all_recurring_blocks,
    get_recurring_block_by_id,
    delete_recurring_block,
    get_rules_by_group,
    get_blocks_by_group,
    get_recurring_blocks_by_group,
    get_last_sync_date,
    set_last_sync_date,
    get_practice_timezone,
    set_practice_timezone,
    get_provider_timezone,
    set_provider_timezone,
    clear_provider_timezone,
    get_all_provider_timezones,
    is_first_install,
    mark_installed,
    should_refresh_ttls,
    mark_ttl_refresh_done,
    refresh_all_ttls,
)


# ── Rule CRUD ─────────────────────────────────────────────────────────


class TestRuleCRUD:
    def test_save_and_get_rule(self, patch_cache, sample_rule):
        save_rule(sample_rule)
        retrieved = get_rule_by_id(sample_rule.provider_id, sample_rule.id)
        assert retrieved is not None
        assert retrieved.id == sample_rule.id
        assert retrieved.provider_id == sample_rule.provider_id

    def test_get_rule_not_found(self, patch_cache):
        result = get_rule_by_id("p1", "nonexistent")
        assert result is None

    def test_get_rules_for_provider(self, patch_cache, sample_rule):
        save_rule(sample_rule)
        rules = get_rules_for_provider(sample_rule.provider_id)
        assert len(rules) == 1
        assert rules[0].id == sample_rule.id

    def test_get_rules_for_provider_empty(self, patch_cache):
        rules = get_rules_for_provider("nonexistent")
        assert rules == []

    def test_get_all_rules(self, patch_cache, sample_rule):
        save_rule(sample_rule)
        all_rules = get_all_rules()
        assert len(all_rules) == 1

    def test_get_all_rules_empty(self, patch_cache):
        all_rules = get_all_rules()
        assert all_rules == []

    def test_delete_rule_by_id(self, patch_cache, sample_rule):
        save_rule(sample_rule)
        result = delete_rule_by_id(sample_rule.provider_id, sample_rule.id)
        assert result is True
        assert get_rule_by_id(sample_rule.provider_id, sample_rule.id) is None

    def test_delete_rules_for_provider(self, patch_cache, sample_rule):
        save_rule(sample_rule)
        count = delete_rules_for_provider(sample_rule.provider_id)
        assert count == 1
        assert get_rules_for_provider(sample_rule.provider_id) == []

    def test_delete_rules_for_provider_empty(self, patch_cache):
        count = delete_rules_for_provider("nonexistent")
        assert count == 0


# ── Event ID mapping ──────────────────────────────────────────────────


class TestEventIDs:
    def test_save_and_get_event_ids(self, patch_cache):
        save_event_ids("rule-1", ["event-a", "event-b"])
        result = get_event_ids("rule-1")
        assert result == ["event-a", "event-b"]

    def test_get_event_ids_empty(self, patch_cache):
        result = get_event_ids("nonexistent")
        assert result == []

    def test_delete_event_ids(self, patch_cache):
        save_event_ids("rule-1", ["event-a"])
        delete_event_ids("rule-1")
        assert get_event_ids("rule-1") == []


# ── Admin Block CRUD ──────────────────────────────────────────────────


class TestBlockCRUD:
    def test_save_and_get_block(self, patch_cache, sample_block):
        save_block(sample_block)
        retrieved = get_block_by_id(sample_block.provider_id, sample_block.id)
        assert retrieved is not None
        assert retrieved.id == sample_block.id

    def test_get_block_not_found(self, patch_cache):
        result = get_block_by_id("p1", "nonexistent")
        assert result is None

    def test_get_blocks_for_provider(self, patch_cache, sample_block):
        save_block(sample_block)
        blocks = get_blocks_for_provider(sample_block.provider_id)
        assert len(blocks) == 1

    def test_get_blocks_for_provider_empty(self, patch_cache):
        blocks = get_blocks_for_provider("nonexistent")
        assert blocks == []

    def test_get_all_blocks(self, patch_cache, sample_block):
        save_block(sample_block)
        all_blocks = get_all_blocks()
        assert len(all_blocks) == 1

    def test_get_all_blocks_empty(self, patch_cache):
        all_blocks = get_all_blocks()
        assert all_blocks == []

    def test_delete_block(self, patch_cache, sample_block):
        save_block(sample_block)
        result = delete_block(sample_block.provider_id, sample_block.id)
        assert result is True
        assert get_block_by_id(sample_block.provider_id, sample_block.id) is None


# ── Recurring Block CRUD ──────────────────────────────────────────────


class TestRecurringBlockCRUD:
    def test_save_and_get(self, patch_cache, sample_recurring_block):
        save_recurring_block(sample_recurring_block)
        retrieved = get_recurring_block_by_id(
            sample_recurring_block.provider_id, sample_recurring_block.id
        )
        assert retrieved is not None
        assert retrieved.id == sample_recurring_block.id

    def test_get_not_found(self, patch_cache):
        result = get_recurring_block_by_id("p1", "nonexistent")
        assert result is None

    def test_get_for_provider(self, patch_cache, sample_recurring_block):
        save_recurring_block(sample_recurring_block)
        blocks = get_recurring_blocks_for_provider(sample_recurring_block.provider_id)
        assert len(blocks) == 1

    def test_get_for_provider_empty(self, patch_cache):
        blocks = get_recurring_blocks_for_provider("nonexistent")
        assert blocks == []

    def test_get_all(self, patch_cache, sample_recurring_block):
        save_recurring_block(sample_recurring_block)
        all_blocks = get_all_recurring_blocks()
        assert len(all_blocks) == 1

    def test_get_all_empty(self, patch_cache):
        all_blocks = get_all_recurring_blocks()
        assert all_blocks == []

    def test_delete(self, patch_cache, sample_recurring_block):
        save_recurring_block(sample_recurring_block)
        result = delete_recurring_block(
            sample_recurring_block.provider_id, sample_recurring_block.id
        )
        assert result is True
        assert get_recurring_block_by_id(
            sample_recurring_block.provider_id, sample_recurring_block.id
        ) is None


# ── Group lookups ─────────────────────────────────────────────────────


class TestGroupLookups:
    def test_get_rules_by_group(self, patch_cache):
        rule_a = ProviderAvailabilityRule(
            id="r1", provider_id="p1", group_id="group-1"
        )
        rule_b = ProviderAvailabilityRule(
            id="r2", provider_id="p2", group_id="group-1"
        )
        rule_c = ProviderAvailabilityRule(
            id="r3", provider_id="p3", group_id="group-2"
        )
        save_rule(rule_a)
        save_rule(rule_b)
        save_rule(rule_c)

        result = get_rules_by_group("group-1")
        assert len(result) == 2
        ids = {r.id for r in result}
        assert ids == {"r1", "r2"}

    def test_get_blocks_by_group(self, patch_cache):
        b1 = AdminBlock(
            id="b1", provider_id="p1",
            start=datetime(2026, 1, 1, 9, 0), end=datetime(2026, 1, 1, 12, 0),
            group_id="g1",
        )
        b2 = AdminBlock(
            id="b2", provider_id="p2",
            start=datetime(2026, 1, 1, 9, 0), end=datetime(2026, 1, 1, 12, 0),
            group_id="g2",
        )
        save_block(b1)
        save_block(b2)

        result = get_blocks_by_group("g1")
        assert len(result) == 1
        assert result[0].id == "b1"

    def test_get_recurring_blocks_by_group(self, patch_cache):
        rb1 = RecurringBlock(id="rb1", provider_id="p1", group_id="g1")
        rb2 = RecurringBlock(id="rb2", provider_id="p2", group_id="g1")
        save_recurring_block(rb1)
        save_recurring_block(rb2)

        result = get_recurring_blocks_by_group("g1")
        assert len(result) == 2


# ── Practice timezone ─────────────────────────────────────────────────


class TestPracticeTimezone:
    def test_default_utc(self, patch_cache):
        assert get_practice_timezone() == "UTC"

    def test_set_and_get(self, patch_cache):
        set_practice_timezone("US/Eastern")
        assert get_practice_timezone() == "US/Eastern"


# ── Install sentinel ──────────────────────────────────────────────────


class TestInstallSentinel:
    def test_first_install_true(self, patch_cache):
        assert is_first_install() is True

    def test_first_install_false_after_mark(self, patch_cache):
        mark_installed()
        assert is_first_install() is False


# ── Daily sync date ───────────────────────────────────────────────────


class TestSyncDate:
    def test_get_empty(self, patch_cache):
        assert get_last_sync_date() == ""

    def test_set_and_get(self, patch_cache):
        set_last_sync_date("2026-03-02")
        assert get_last_sync_date() == "2026-03-02"


# ── TTL refresh ───────────────────────────────────────────────────────


class TestTTLRefresh:
    def test_should_refresh_first_time(self, patch_cache):
        assert should_refresh_ttls() is True

    def test_should_not_refresh_just_done(self, patch_cache):
        mark_ttl_refresh_done()
        assert should_refresh_ttls() is False

    def test_should_refresh_with_corrupt_value(self, patch_cache):
        """Corrupt timestamp value should trigger a refresh."""
        from provider_availability.engine.storage import LAST_TTL_REFRESH_KEY
        patch_cache._store[LAST_TTL_REFRESH_KEY] = "not-a-number"
        assert should_refresh_ttls() is True

    def test_refresh_all_ttls_empty(self, patch_cache):
        result = refresh_all_ttls()
        assert result == 0

    def test_refresh_all_ttls_with_rules(self, patch_cache, sample_rule):
        save_rule(sample_rule)
        result = refresh_all_ttls()
        assert result == 1

    def test_refresh_cleans_stale_keys(self, patch_cache):
        """If a cached rule has expired (returns None), it should be removed from the index."""
        # Manually set up a stale index entry
        patch_cache._store[INDEX_KEY] = ["pa:rules:p1:stale"]
        # Don't set the actual key — it's "expired"

        result = refresh_all_ttls()
        assert result == 0
        # Stale key should be removed from index
        index = patch_cache._store.get(INDEX_KEY, [])
        assert "pa:rules:p1:stale" not in index

    def test_refresh_all_ttls_with_blocks(self, patch_cache, sample_block):
        """Refresh should also refresh block TTLs."""
        save_block(sample_block)
        save_rule(ProviderAvailabilityRule(
            id="r1", provider_id="p1",
        ))
        result = refresh_all_ttls()
        assert result == 1  # 1 rule refreshed
        # Block should still be retrievable
        blocks = get_all_blocks()
        assert len(blocks) == 1

    def test_refresh_all_ttls_with_recurring_blocks(self, patch_cache, sample_recurring_block):
        """Refresh should also refresh recurring block TTLs."""
        save_recurring_block(sample_recurring_block)
        result = refresh_all_ttls()
        assert result == 0  # no rules
        # Recurring block should still be retrievable
        rbs = get_all_recurring_blocks()
        assert len(rbs) == 1

    def test_refresh_all_ttls_cleans_stale_blocks(self, patch_cache):
        """Stale block keys should be cleaned from the block index."""
        patch_cache._store[BLOCK_INDEX_KEY] = ["pa:blocks:p1:stale-block"]
        result = refresh_all_ttls()
        assert result == 0
        index = patch_cache._store.get(BLOCK_INDEX_KEY, [])
        assert "pa:blocks:p1:stale-block" not in index

    def test_refresh_all_ttls_cleans_stale_recurring_blocks(self, patch_cache):
        """Stale recurring block keys should be cleaned from the recurring block index."""
        patch_cache._store[RECURRING_BLOCK_INDEX_KEY] = ["pa:recurring:p1:stale-rb"]
        result = refresh_all_ttls()
        assert result == 0
        index = patch_cache._store.get(RECURRING_BLOCK_INDEX_KEY, [])
        assert "pa:recurring:p1:stale-rb" not in index

    def test_refresh_all_ttls_with_practice_timezone(self, patch_cache):
        """Refresh should also refresh practice timezone TTL."""
        set_practice_timezone("US/Eastern")
        result = refresh_all_ttls()
        assert result == 0
        assert get_practice_timezone() == "US/Eastern"

    def test_refresh_all_ttls_with_install_sentinel(self, patch_cache):
        """Refresh should also refresh install sentinel TTL."""
        mark_installed()
        result = refresh_all_ttls()
        assert result == 0
        assert is_first_install() is False

    def test_refresh_all_ttls_with_provider_timezones(self, patch_cache):
        """Refresh should also refresh provider timezone TTLs."""
        set_provider_timezone("p1", "US/Pacific")
        set_provider_timezone("p2", "US/Eastern")
        result = refresh_all_ttls()
        assert result == 0
        assert get_provider_timezone("p1") == "US/Pacific"
        assert get_provider_timezone("p2") == "US/Eastern"

    def test_refresh_all_ttls_with_event_ids(self, patch_cache, sample_rule):
        """Refresh should also refresh event ID mappings for rules."""
        save_rule(sample_rule)
        save_event_ids(sample_rule.id, ["evt-1", "evt-2"])
        result = refresh_all_ttls()
        assert result == 1
        assert get_event_ids(sample_rule.id) == ["evt-1", "evt-2"]


# ── Provider Timezone ────────────────────────────────────────────────


class TestProviderTimezone:
    def test_get_provider_timezone_not_set(self, patch_cache):
        result = get_provider_timezone("p1")
        assert result is None

    def test_set_and_get_provider_timezone(self, patch_cache):
        set_provider_timezone("p1", "US/Pacific")
        result = get_provider_timezone("p1")
        assert result == "US/Pacific"

    def test_clear_provider_timezone(self, patch_cache):
        set_provider_timezone("p1", "US/Pacific")
        clear_provider_timezone("p1")
        result = get_provider_timezone("p1")
        assert result is None

    def test_get_all_provider_timezones_empty(self, patch_cache):
        result = get_all_provider_timezones()
        assert result == {}

    def test_get_all_provider_timezones(self, patch_cache):
        set_provider_timezone("p1", "US/Pacific")
        set_provider_timezone("p2", "US/Eastern")
        result = get_all_provider_timezones()
        assert result == {"p1": "US/Pacific", "p2": "US/Eastern"}

    def test_set_same_provider_twice_no_duplicate_index(self, patch_cache):
        set_provider_timezone("p1", "US/Pacific")
        set_provider_timezone("p1", "US/Eastern")
        result = get_all_provider_timezones()
        assert result == {"p1": "US/Eastern"}

    def test_clear_nonexistent_provider(self, patch_cache):
        """Clearing a provider that was never set should not error."""
        clear_provider_timezone("nonexistent")
        result = get_all_provider_timezones()
        assert result == {}
