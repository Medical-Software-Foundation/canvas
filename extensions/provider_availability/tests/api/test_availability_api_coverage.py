"""Additional coverage tests for provider_availability.api.availability_api.

Targets the branches left uncovered by test_availability_api.py and
test_form_handlers.py: the per-provider timezone endpoints, the lead-time
refresh / orphan-cleanup branches on rule delete + override edits, the
per-date timed block path, the recurring-block replace/apply-to-group
branches, and the remaining form-* helper branches.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from datetime import date, datetime, time
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from provider_availability.api.availability_api import (
    AvailabilityAPI,
    _check_write_access,
    _sort_providers_you_first,
)
from provider_availability.engine.models import (
    AdminBlock,
    BookingInterval,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)


# ── Helpers (mirrors test_availability_api.py) ─────────────────────────────

PROVIDER_ID = "provider-uuid-123"
PROVIDER_ID_2 = "provider-uuid-456"
LOCATION_ID = "location-uuid-456"
VISIT_TYPE_ID = "visit-type-uuid-789"

MODULE = "provider_availability.api.availability_api"

def _saved(mock):
    """Every block passed to a batched save or delete mock, in call order."""
    return [b for c in mock.mock_calls for b in c.args[0]]


# Saved ids are UUIDs; the save routes refuse anything else.
RULE_ID = "0a1b2c3d-0000-4000-8000-000000000001"
BLOCK_ID = "0a1b2c3d-0000-4000-8000-000000000002"
RB_ID = "0a1b2c3d-0000-4000-8000-000000000003"
BLOCK_ID_2 = "0a1b2c3d-0000-4000-8000-000000000004"
RB_ID_2 = "0a1b2c3d-0000-4000-8000-000000000005"


def _parse(response) -> tuple[dict, int]:
    """Extract (body_dict, status_code) from a JSONResponse."""
    body = json.loads(getattr(response, "content"))
    return body, response.status_code


def _session_headers(staff_id: str = "staff-1", user_type: str = "Staff") -> dict[str, str]:
    """The headers Canvas uses to identify the signed-in user.

    Canvas sends identity as request headers, not as an attribute on the
    request object. Tests that set a `staff_id` attribute passed while
    production denied everyone, so building real headers here is what keeps
    these tests honest.
    """
    return {
        "canvas-logged-in-user-id": staff_id,
        "canvas-logged-in-user-type": user_type,
    }


def _make_handler(
    query_params: dict | None = None,
    path_params: dict | None = None,
    json_body: dict | None = None,
    staff_id: str = "staff-1",
) -> AvailabilityAPI:
    """Create an AvailabilityAPI handler with a mocked request."""
    handler = AvailabilityAPI(MagicMock())
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.request.path_params = path_params or {}
    handler.request.json.return_value = json_body or {}
    handler.request.headers = _session_headers(staff_id)
    handler.secrets = {}
    return handler


def _make_form_handler(method: str, path: str, body: dict) -> AvailabilityAPI:
    """Create a handler with a form_data() payload for handle_form_action."""
    handler = _make_handler()
    field_method = MagicMock()
    field_method.value = method
    field_path = MagicMock()
    field_path.value = path
    field_body = MagicMock()
    field_body.value = json.dumps(body)
    handler.request.form_data.return_value = {
        "_method": field_method,
        "_path": field_path,
        "_body": field_body,
    }
    return handler


def _lead_time_rule(rule_id: str = "r-lead") -> ProviderAvailabilityRule:
    """An active rule with a positive min_lead_hours (triggers lead-time blocks)."""
    return ProviderAvailabilityRule(
        id=rule_id,
        provider_id=PROVIDER_ID,
        weekly_schedule={"thursday": [TimeWindow(start=time(9, 0), end=time(15, 0))]},
        booking_interval=BookingInterval(min_lead_hours=24),
        is_active=True,
    )


# ── update_rule_group: preserve-existing + lead-time / orphan branches ─────


class TestUpdateRuleGroupBranches:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_provider_lead_time_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    @patch(f"{MODULE}.get_rules_for_provider")
    def test_preserves_existing_overrides_and_timezone_and_syncs_lead_time(
        self,
        mock_get_rules,
        mock_get_rule,
        mock_overlap,
        mock_save,
        mock_sync,
        mock_lead,
        mock_access,
    ):
        """When payload omits date_overrides/timezone, they come from the existing
        rule; an active lead-time rule produces lead-time block effects."""
        existing = ProviderAvailabilityRule(
            id=RULE_ID,
            provider_id=PROVIDER_ID,
            timezone="US/Eastern",
            date_overrides=[
                DateOverride(
                    date=date(2026, 4, 9),
                    time_windows=[TimeWindow(start=time(9, 0), end=time(10, 0))],
                )
            ],
        )
        mock_get_rule.return_value = existing
        mock_get_rules.return_value = [_lead_time_rule()]

        body = {
            "id": RULE_ID,
            "provider_id": PROVIDER_ID,
            "effective_start": "2026-01-05",
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_rule_group()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Updated 1 rule(s)" in data["message"]
        # Preserved timezone from existing rule is echoed back on the saved rule
        assert data["rule"]["timezone"] == "US/Eastern"
        assert len(data["rule"]["date_overrides"]) == 1
        # Lead-time effects were appended ahead of the JSONResponse
        assert "lead-fx" in result
        assert mock_lead.mock_calls == [call(PROVIDER_ID, mock_get_rules.return_value)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_provider_lead_time_events", return_value=["orphan-del-fx"])
    @patch(f"{MODULE}.build_provider_lead_time_effects")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    def test_no_lead_time_cleans_orphan_events(
        self,
        mock_get_rules,
        mock_get_rule,
        mock_overlap,
        mock_save,
        mock_sync,
        mock_lead,
        mock_del_orphans,
        mock_access,
    ):
        """No remaining lead-time rule -> orphaned Lead Time events are cleaned up
        via delete_provider_lead_time_events."""
        body = {
            "id": RULE_ID,
            "provider_id": PROVIDER_ID,
            "effective_start": "2026-01-05",
            "weekly_schedule": {},
        }
        handler = _make_handler(json_body=body)
        result = handler.update_rule_group()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "orphan-del-fx" in result
        assert mock_lead.mock_calls == []
        assert mock_del_orphans.mock_calls == [call(PROVIDER_ID)]


# ── delete_rule: lead-time refresh + orphan cleanup ────────────────────────


class TestDeleteRuleBranches:
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_provider_lead_time_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_refreshes_lead_time_for_remaining_rule(
        self, mock_delete, mock_get_rules, mock_sync, mock_lead, mock_access, _get_rule
    ):
        mock_get_rules.return_value = [_lead_time_rule()]
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "r1"}
        )
        result = handler.delete_rule()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Rule deleted"
        assert "lead-fx" in result
        assert mock_delete.mock_calls == [call(PROVIDER_ID, "r1")]
        assert mock_lead.mock_calls == [call(PROVIDER_ID, mock_get_rules.return_value)]

    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_provider_lead_time_events", return_value=["orphan-del-fx"])
    @patch(f"{MODULE}.build_provider_lead_time_effects")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_orphan_cleanup_when_no_remaining_lead_time(
        self, mock_delete, mock_get_rules, mock_sync, mock_lead, mock_del_orphans, mock_access, _get_rule
    ):
        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "r1"}
        )
        result = handler.delete_rule()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "orphan-del-fx" in result
        assert mock_lead.mock_calls == []
        assert mock_del_orphans.mock_calls == [call(PROVIDER_ID)]


# ── add_override / remove_override: lead-time + recurring re-sync ──────────


class TestOverrideResyncBranches:
    def _rule(self) -> ProviderAvailabilityRule:
        return ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"thursday": [TimeWindow(start=time(9, 0), end=time(15, 0))]},
            is_active=True,
        )

    @patch(f"{MODULE}.check_override_overlap", new=lambda *a, **k: None)
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.build_provider_lead_time_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_resyncs_lead_time_and_recurring(
        self,
        mock_get,
        mock_save,
        mock_get_rules,
        mock_sync,
        mock_lead,
        mock_get_rb,
        mock_rb_sync,
        mock_access,
    ):
        mock_get.return_value = self._rule()
        mock_get_rules.return_value = [_lead_time_rule()]
        active_rb = RecurringBlock(id="rb1", provider_id=PROVIDER_ID, is_active=True)
        other_rb = RecurringBlock(
            id="rb2", provider_id=PROVIDER_ID_2, is_active=True
        )
        mock_get_rb.return_value = [active_rb, other_rb]

        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "rule-1"},
            # 2026-04-09 is a Thursday, which the rule schedules
            json_body={"date": "2026-04-09", "time_windows": [{"start": "12:00", "end": "17:00"}]},
        )
        result = handler.add_override()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Override saved"
        assert "lead-fx" in result
        assert "rb-fx" in result
        # Only the provider's own active recurring block is re-synced
        assert mock_rb_sync.mock_calls == [call([active_rb])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.build_provider_lead_time_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_remove_override_resyncs_lead_time_and_recurring(
        self,
        mock_get,
        mock_save,
        mock_get_rules,
        mock_sync,
        mock_lead,
        mock_get_rb,
        mock_rb_sync,
        mock_access,
    ):
        existing = DateOverride(
            date=date(2026, 4, 9),
            time_windows=[TimeWindow(start=time(9, 0), end=time(12, 0))],
        )
        rule = self._rule()
        rule.date_overrides = [existing]
        mock_get.return_value = rule
        mock_get_rules.return_value = [_lead_time_rule()]
        active_rb = RecurringBlock(id="rb1", provider_id=PROVIDER_ID, is_active=True)
        mock_get_rb.return_value = [active_rb]

        handler = _make_handler(
            path_params={
                "provider_id": PROVIDER_ID,
                "rule_id": "rule-1",
                "override_date": "2026-04-09",
            },
        )
        result = handler.remove_override()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Override removed"
        assert len(rule.date_overrides) == 0
        assert "lead-fx" in result
        assert "rb-fx" in result
        assert mock_rb_sync.mock_calls == [call([active_rb])]


# ── create_block: per-date timed path + replace_recurring_block ────────────


class TestCreateBlockBranches:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_blocks")
    def test_multi_date_timed_applies_time_of_day(
        self, mock_save, mock_effects, mock_access
    ):
        """all_day=false with dates fans out timed blocks per date."""
        body = {
            "provider_id": PROVIDER_ID,
            "dates": ["2026-07-06", "2026-07-07"],
            "all_day": False,
            "start": "09:00:00",
            "end": "11:00:00",
            "reason": "Timed batch",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Created 2 block(s)"
        assert data["blocks"][0]["start"] == "2026-07-06T09:00:00"
        assert data["blocks"][0]["end"] == "2026-07-06T11:00:00"
        assert data["blocks"][1]["start"] == "2026-07-07T09:00:00"
        assert len(_saved(mock_save)) == 2

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_multi_date_timed_missing_start_end_errors(self, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "dates": ["2026-07-06"],
            "all_day": False,
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "start and end are required when all_day=false" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_multi_date_timed_start_after_end_errors(self, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "dates": ["2026-07-06"],
            "all_day": False,
            "start": "14:00:00",
            "end": "09:00:00",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Start must be before end for date 2026-07-06" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.build_delete_recurring_block_effects", return_value=["del-rb"])
    @patch(f"{MODULE}.delete_recurring_block")
    @patch(f"{MODULE}.get_recurring_block_by_id")
    @patch(f"{MODULE}.save_block")
    def test_single_block_replaces_recurring_block(
        self,
        mock_save,
        mock_get_rb,
        mock_del_rb,
        mock_del_effects,
        mock_effects,
        mock_access,
    ):
        old_rb = RecurringBlock(id="rb-old", provider_id=PROVIDER_ID)
        mock_get_rb.return_value = old_rb
        body = {
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
            "replace_recurring_block_id": "rb-old",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_block()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Block created"
        assert "del-rb" in result
        assert mock_get_rb.mock_calls == [call(PROVIDER_ID, "rb-old")]
        assert mock_del_rb.mock_calls == [call(PROVIDER_ID, "rb-old")]
        assert mock_del_effects.mock_calls == [call(PROVIDER_ID, old_rb)]


# ── update_block: apply_to_group skip-self ─────────────────────────────────


class TestUpdateBlockGroupSkipsSelf:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_block_by_id", return_value=None)
    @patch(f"{MODULE}.get_blocks_by_group")
    def test_group_update_skips_same_id(
        self,
        mock_group,
        mock_get,
        mock_del_effects,
        mock_save,
        mock_create_effects,
        mock_access,
    ):
        same = AdminBlock(
            id=BLOCK_ID,
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 8, 0),
            end=datetime(2026, 3, 10, 11, 0),
            group_id="g1",
        )
        mock_group.return_value = [same]
        body = {
            "id": BLOCK_ID,
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T12:00:00",
            "group_id": "g1",
            "apply_to_group": True,
        }
        handler = _make_handler(json_body=body)
        result = handler.update_block()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Updated 1 block(s)" in data["message"]
        # Only the primary block is saved (group member shares id and is skipped)
        assert len(mock_save.mock_calls) == 1


# ── delete_block_endpoint: apply_to_group ──────────────────────────────────


class TestDeleteBlockApplyToGroup:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.delete_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_blocks_by_group")
    @patch(f"{MODULE}.get_blocks_for_provider")
    def test_deletes_all_group_members(
        self, mock_get_blocks, mock_group, mock_effects, mock_delete, mock_access
    ):
        target = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 7, 4, 0, 0),
            end=datetime(2026, 7, 5, 0, 0),
            group_id="g1",
        )
        member = AdminBlock(
            id="b2",
            provider_id=PROVIDER_ID_2,
            start=datetime(2026, 12, 25, 0, 0),
            end=datetime(2026, 12, 26, 0, 0),
            group_id="g1",
        )
        mock_get_blocks.return_value = [target]
        mock_group.return_value = [target, member]

        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "block_id": "b1"},
            query_params={"apply_to_group": "true"},
        )
        result = handler.delete_block_endpoint()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["deleted_count"] == 2
        assert data["message"] == "Deleted 2 block(s)"
        assert mock_group.mock_calls == [call("g1")]
        # Deleted both the target and the group member (target skipped in loop)
        assert mock_delete.mock_calls == [
            call(PROVIDER_ID, "b1"),
            call(PROVIDER_ID_2, "b2"),
        ]


# ── create_recurring_block: replace_block branch ───────────────────────────


class TestCreateRecurringBlockReplace:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.build_delete_block_effects", return_value=["del-blk"])
    @patch(f"{MODULE}.delete_block")
    @patch(f"{MODULE}.get_block_by_id")
    @patch(f"{MODULE}.save_recurring_block")
    def test_replaces_single_block(
        self,
        mock_save,
        mock_get_block,
        mock_del_block,
        mock_del_effects,
        mock_sync_effects,
        mock_access,
    ):
        old_block = AdminBlock(
            id="b-old",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        mock_get_block.return_value = old_block
        body = {
            "provider_id": PROVIDER_ID,
            "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "12:00", "end": "13:00"}]},
            "replace_block_id": "b-old",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_recurring_block()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        assert data["message"] == "Recurring block created"
        assert "del-blk" in result
        assert mock_get_block.mock_calls == [call(PROVIDER_ID, "b-old")]
        assert mock_del_block.mock_calls == [call(PROVIDER_ID, "b-old")]
        assert mock_del_effects.mock_calls == [call(PROVIDER_ID, old_block)]


# ── Per-provider timezone: get_provider_tz / get_all_provider_tzs ──────────


class TestGetProviderTz:
    def test_missing_provider_id(self):
        handler = _make_handler(query_params={})
        result = handler.get_provider_tz()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id is required" in data["error"]

    @patch(f"{MODULE}.get_provider_timezone", return_value="US/Pacific")
    def test_explicit_timezone(self, mock_get):
        handler = _make_handler(query_params={"provider_id": PROVIDER_ID})
        result = handler.get_provider_tz()
        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["provider_id"] == PROVIDER_ID
        assert data["timezone"] == "US/Pacific"
        assert data["explicit"] is True
        assert mock_get.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.get_provider_timezone", return_value=None)
    def test_falls_back_to_practice_timezone(self, mock_get, mock_practice):
        handler = _make_handler(query_params={"provider_id": PROVIDER_ID})
        result = handler.get_provider_tz()
        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["timezone"] == "US/Eastern"
        assert data["explicit"] is False
        assert mock_practice.mock_calls == [call()]


class TestGetAllProviderTzs:
    @patch(
        f"{MODULE}.get_all_provider_timezones",
        return_value={PROVIDER_ID: "US/Pacific"},
    )
    def test_returns_all(self, mock_all):
        handler = _make_handler()
        result = handler.get_all_provider_tzs()
        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["timezones"] == {PROVIDER_ID: "US/Pacific"}
        assert mock_all.mock_calls == [call()]


# ── set_provider_tz ────────────────────────────────────────────────────────


class TestSetProviderTz:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_id(self, mock_access):
        handler = _make_handler(json_body={"timezone": "US/Eastern"})
        result = handler.set_provider_tz()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id is required" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone(self, mock_access):
        handler = _make_handler(
            json_body={"provider_id": PROVIDER_ID, "timezone": "Mars/Base"}
        )
        result = handler.set_provider_tz()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.set_provider_timezone")
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    def test_success_resyncs_matching_recurring_blocks(
        self, mock_get_blocks, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
    ):
        matching = RecurringBlock(id="rb1", provider_id=PROVIDER_ID)
        other = RecurringBlock(id="rb2", provider_id=PROVIDER_ID_2)
        mock_get_rb.return_value = [matching, other]

        handler = _make_handler(
            json_body={"provider_id": PROVIDER_ID, "timezone": "US/Pacific"}
        )
        result = handler.set_provider_tz()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["timezone"] == "US/Pacific"
        assert data["provider_id"] == PROVIDER_ID
        assert "sync-fx" in result
        assert "rb-fx" in result
        assert mock_set.mock_calls == [call(PROVIDER_ID, "US/Pacific")]
        assert mock_sync.mock_calls == [call(PROVIDER_ID)]
        # Only the matching provider's recurring block is re-synced
        assert mock_rb_sync.mock_calls == [call([matching])]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(
            json_body={"provider_id": PROVIDER_ID, "timezone": "US/Pacific"}
        )
        result = handler.set_provider_tz()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN


# ── clear_provider_tz ──────────────────────────────────────────────────────


class TestClearProviderTz:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Pacific")
    @patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.clear_provider_timezone")
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    def test_clears_override_and_resyncs(
        self, mock_get_blocks, mock_clear, mock_sync, mock_get_rb, mock_rb_sync, mock_default_tz, mock_access
    ):
        matching = RecurringBlock(id="rb1", provider_id=PROVIDER_ID)
        other = RecurringBlock(id="rb2", provider_id=PROVIDER_ID_2)
        mock_get_rb.return_value = [matching, other]

        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.clear_provider_tz()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["explicit"] is False
        assert data["timezone"] == "US/Pacific"
        assert data["provider_id"] == PROVIDER_ID
        assert "sync-fx" in result
        assert "rb-fx" in result
        assert mock_clear.mock_calls == [call(PROVIDER_ID)]
        assert mock_sync.mock_calls == [call(PROVIDER_ID)]
        # Only the matching provider's recurring block is re-synced
        assert mock_rb_sync.mock_calls == [call([matching])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Pacific")
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    def test_rebuilds_one_off_blocks_around_the_clear(
        self, mock_sync, mock_get_rb, mock_default_tz, mock_access
    ):
        # Block events are deleted under the old TZ, then rebuilt under the practice
        # default, so a block entered at 1:00 PM stays at 1:00 PM after the clear.
        mine = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 10, 6, 13, 0),
            end=datetime(2026, 10, 6, 14, 0),
        )
        theirs = AdminBlock(
            id="b2",
            provider_id=PROVIDER_ID_2,
            start=datetime(2026, 10, 6, 13, 0),
            end=datetime(2026, 10, 6, 14, 0),
        )
        order = MagicMock()
        order.get_all_blocks.return_value = [mine, theirs]
        order.build_delete_block_effects.return_value = ["del-blk"]
        order.build_block_event_effects.return_value = ["new-blk"]
        with (
            patch(f"{MODULE}.get_all_blocks", order.get_all_blocks),
            patch(f"{MODULE}.build_delete_block_effects", order.build_delete_block_effects),
            patch(f"{MODULE}.clear_provider_timezone", order.clear_provider_timezone),
            patch(f"{MODULE}.build_block_event_effects", order.build_block_event_effects),
        ):
            handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
            result = handler.clear_provider_tz()

        _, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert result.index("del-blk") < result.index("new-blk")
        # Only this provider's block, deleted before the clear and rebuilt after it
        assert order.mock_calls == [
            call.get_all_blocks(),
            call.build_delete_block_effects(PROVIDER_ID, mine, keep_others=False),
            call.clear_provider_timezone(PROVIDER_ID),
            call.build_block_event_effects(mine),
        ]

    @patch(f"{MODULE}._check_write_access")
    def test_write_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [
            JSONResponse({"error": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)
        ]
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID})
        result = handler.clear_provider_tz()
        _, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN


# ── set_provider_tz_bulk ───────────────────────────────────────────────────


class TestSetProviderTzBulk:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_ids(self, mock_access):
        handler = _make_handler(json_body={"timezone": "US/Eastern"})
        result = handler.set_provider_tz_bulk()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_ids is required" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone(self, mock_access):
        handler = _make_handler(
            json_body={"provider_ids": [PROVIDER_ID], "timezone": "Nowhere"}
        )
        result = handler.set_provider_tz_bulk()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.set_provider_timezone")
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    def test_success_sets_all_and_resyncs(
        self, mock_get_blocks, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
    ):
        matching = RecurringBlock(id="rb1", provider_id=PROVIDER_ID)
        other = RecurringBlock(id="rb2", provider_id="not-in-list")
        mock_get_rb.return_value = [matching, other]

        handler = _make_handler(
            json_body={
                "provider_ids": [PROVIDER_ID, PROVIDER_ID_2],
                "timezone": "US/Eastern",
            }
        )
        result = handler.set_provider_tz_bulk()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["count"] == 2
        assert data["timezone"] == "US/Eastern"
        assert "sync-fx" in result
        assert "rb-fx" in result
        assert mock_set.mock_calls == [
            call(PROVIDER_ID, "US/Eastern"),
            call(PROVIDER_ID_2, "US/Eastern"),
        ]
        assert mock_sync.mock_calls == [call(PROVIDER_ID), call(PROVIDER_ID_2)]
        assert mock_rb_sync.mock_calls == [call([matching])]


# ── recurrence validation (daily) ──────────────────────────────────────────


class TestRecurrenceValidation:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_invalid_frequency_rejected(self, mock_resolve, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
            "recurrence_frequency": "hourly",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "recurrence_frequency must be one of" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_non_integer_interval_rejected(self, mock_resolve, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
            "recurrence_interval": "abc",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "recurrence_interval must be an integer" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_interval_below_one_rejected(self, mock_resolve, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
            "recurrence_interval": 0,
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "recurrence_interval must be >= 1" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_daily_requires_time_windows(self, mock_resolve, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
            "recurrence_frequency": "daily",
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "time_windows is required when recurrence_frequency is 'daily'" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_daily_time_window_start_after_end_rejected(self, mock_resolve, mock_access):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
            "recurrence_frequency": "daily",
            "time_windows": [{"start": "17:00", "end": "09:00"}],
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Start time must be before end time" in data["error"]


# ── create_or_update_rule: lead-time effect path ───────────────────────────


class TestCreateRuleLeadTime:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_provider_lead_time_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    @patch(f"{MODULE}.get_rules_for_provider")
    def test_active_lead_time_rule_appends_effects(
        self, mock_get_rules, mock_resolve, mock_overlap, mock_save, mock_sync, mock_lead, mock_access
    ):
        mock_get_rules.return_value = [_lead_time_rule()]
        body = {
            "provider_id": PROVIDER_ID,
            "effective_start": "2026-01-05",
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
            "is_active": True,
            "booking_interval": {"min_lead_hours": 48},
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        assert "lead-fx" in result
        assert mock_lead.mock_calls == [call(PROVIDER_ID, mock_get_rules.return_value)]


# ── _form_set_provider_timezone / _form_set_provider_tz_bulk ───────────────


# ── _dispatch_write routing for provider-timezone form paths ───────────────


# ── _check_write_access: secret-based path ─────────────────────────────────


class TestCheckWriteAccessSecret:
    def test_secret_allows_matching_staff(self):
        request = MagicMock()
        # Access control reads the logged-in staff id from request headers
        # (canvas-logged-in-user-id), not request.staff_id.
        request.headers = {"canvas-logged-in-user-id": "staff-42"}
        result = _check_write_access(
            request, {"allowed-staff-keys": "staff-1, staff-42 , staff-9"}
        )
        assert result is None

    def test_secret_denies_unlisted_staff(self):
        request = MagicMock()
        request.headers = {"canvas-logged-in-user-id": "intruder"}
        result = _check_write_access(request, {"allowed-staff-keys": "staff-1,staff-2"})
        assert result is not None
        body, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert "Access denied" in body["error"]


# ── _form_delete_rule: lead-time + orphan cleanup ──────────────────────────


# ── _form_add_override / _form_remove_override ─────────────────────────────


# ── _form_create_block / _form_update_block / _form_create_recurring_block ─


# ── _build_preloaded_data with data ────────────────────────────────────────


class TestBuildPreloadedDataWithData:
    @pytest.fixture(autouse=True)
    def _no_saved_view(self):
        """The saved view reads the plugin cache, which tests have no context for."""
        with patch(f"{MODULE}.get_my_view", return_value=[]):
            yield

    @patch(f"{MODULE}.generate_template_csv", return_value="csv")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={PROVIDER_ID: "US/Pacific"})
    @patch(f"{MODULE}.get_provider_displays", return_value={PROVIDER_ID: {"name": "Dr. Smith"}})
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.get_all_blocks")
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_practice_timezone", return_value="UTC")
    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[{"id": VISIT_TYPE_ID, "name": "Follow-up"}])
    @patch(f"{MODULE}.get_active_locations", return_value=[{"id": LOCATION_ID, "name": "Main"}])
    @patch(f"{MODULE}.get_active_providers", return_value=[{"id": PROVIDER_ID, "name": "Dr. Smith"}])
    def test_assembles_overview_with_rules_blocks_recurring(
        self,
        mock_providers,
        mock_locs,
        mock_vts,
        mock_practice,
        mock_rules,
        mock_blocks,
        mock_rb,
        mock_displays,
        mock_ptzs,
        mock_csv,
    ):
        rule = ProviderAvailabilityRule(
            id="r1",
            provider_id=PROVIDER_ID,
            location_ids=[LOCATION_ID],
            visit_types=[VISIT_TYPE_ID],
        )
        block = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        recurring = RecurringBlock(
            id="rb1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"monday": [TimeWindow(start=time(9, 0), end=time(10, 0))]},
        )
        mock_rules.return_value = [rule]
        mock_blocks.return_value = [block]
        mock_rb.return_value = [recurring]

        handler = _make_handler()
        preloaded = handler._build_preloaded_data()

        assert preloaded["csv_template"] == "csv"
        assert preloaded["timezone"]["timezone"] == "UTC"
        overview = preloaded["overview"]["providers"]
        assert len(overview) == 1
        prov = overview[0]
        assert prov["provider_name"] == "Dr. Smith"
        # Explicit provider timezone from get_all_provider_timezones wins over practice tz
        assert prov["provider_timezone"] == "US/Pacific"
        assert prov["provider_timezone_explicit"] is True
        assert prov["rules"][0]["location_names"] == ["Main"]
        assert prov["rules"][0]["visit_type_names"] == ["Follow-up"]
        assert len(prov["blocks"]) == 1
        assert len(prov["recurring_blocks"]) == 1


# ── Schedulable roles endpoints ────────────────────────────────────────────


class TestSchedulableRolesEndpoints:
    @patch(f"{MODULE}.get_available_roles", return_value=[
        {"code": "CC", "name": "Care Coordinator", "abbreviation": "", "domain": "HYB", "staff_count": 8},
    ])
    @patch(f"{MODULE}.get_schedulable_roles", return_value=None)
    @patch(f"{MODULE}.get_effective_schedulable_roles", return_value=["LCSW", "MD"])
    @patch(f"{MODULE}.is_provider_type_fallback_active", return_value=False)
    def test_get_roles(self, mock_fallback, mock_effective, mock_get, mock_avail):
        """Before roles are saved, the selection shows the Provider-type codes in effect."""
        handler = _make_handler()
        result = handler.get_roles()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["schedulable_roles"] == ["LCSW", "MD"]
        assert data["configured"] is False
        assert data["available"][0]["code"] == "CC"
        assert data["fallback_active"] is False
        assert mock_effective.mock_calls == [call()]
        assert mock_get.mock_calls == [call()]
        assert mock_avail.mock_calls == [call()]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}._reconcile_availability_to_roles", return_value=[])
    @patch(f"{MODULE}.set_schedulable_roles")
    def test_set_roles_normalizes_and_saves(self, mock_set, mock_reconcile, mock_access):
        handler = _make_handler(json_body={"schedulable_roles": ["cc", " md ", ""]})
        result = handler.set_roles()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["schedulable_roles"] == ["CC", "MD"]
        assert mock_set.mock_calls == [call(["CC", "MD"])]
        # Saving roles reconciles availability so the change takes effect now.
        assert mock_reconcile.mock_calls == [call()]

    @patch(f"{MODULE}.sync_provider_availability", return_value=["fx"])
    @patch(f"{MODULE}.set_seen_schedulable_ids")
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_schedulable_provider_ids", return_value={PROVIDER_ID})
    def test_reconcile_availability_clears_descheduled_and_syncs_schedulable(
        self, mock_sched, mock_rules, mock_seen, mock_sync
    ):
        from provider_availability.api.availability_api import _reconcile_availability_to_roles

        schedulable_rule = ProviderAvailabilityRule(id="r1", provider_id=PROVIDER_ID)
        descheduled_rule = ProviderAvailabilityRule(id="r2", provider_id=PROVIDER_ID_2)
        mock_rules.return_value = [schedulable_rule, descheduled_rule]

        effects = _reconcile_availability_to_roles()

        # Both providers are re-synced with the schedulable set passed through;
        # sync_provider_availability clears the de-scheduled one internally.
        assert effects == ["fx", "fx"]
        called_pids = {c.args[0] for c in mock_sync.call_args_list}
        assert called_pids == {PROVIDER_ID, PROVIDER_ID_2}
        for c in mock_sync.call_args_list:
            assert c.kwargs["schedulable_ids"] == {PROVIDER_ID}
        # Recorded so the background job does not reconcile the same change again.
        assert mock_seen.mock_calls == [call([PROVIDER_ID])]

    @patch(f"{MODULE}.sync_provider_availability", return_value=["fx"])
    @patch(f"{MODULE}.set_seen_schedulable_ids")
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_schedulable_provider_ids", return_value={PROVIDER_ID})
    def test_reconcile_limited_to_changed_providers(self, mock_sched, mock_rules, mock_seen, mock_sync):
        from provider_availability.api.availability_api import _reconcile_availability_to_roles

        mock_rules.return_value = [
            ProviderAvailabilityRule(id="r1", provider_id=PROVIDER_ID),
            ProviderAvailabilityRule(id="r2", provider_id=PROVIDER_ID_2),
        ]

        assert _reconcile_availability_to_roles(only={PROVIDER_ID_2}) == ["fx"]
        assert mock_sync.mock_calls == [call(PROVIDER_ID_2, schedulable_ids={PROVIDER_ID})]

    @patch(f"{MODULE}._check_write_access", return_value=["DENIED"])
    @patch(f"{MODULE}.set_schedulable_roles")
    def test_set_roles_respects_write_access(self, mock_set, mock_access):
        handler = _make_handler(json_body={"schedulable_roles": ["CC"]})
        result = handler.set_roles()

        assert result == ["DENIED"]
        assert mock_set.mock_calls == []

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_set_roles_rejects_non_list(self, mock_access):
        handler = _make_handler(json_body={"schedulable_roles": "MD,DO"})
        result = handler.set_roles()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "must be a list" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}._reconcile_availability_to_roles", return_value=[])
    @patch(f"{MODULE}.set_schedulable_roles")
    def test_set_roles_rejects_empty_list(self, mock_set, mock_reconcile, mock_access):
        """An empty set would de-schedule every provider at once."""
        handler = _make_handler(json_body={"schedulable_roles": []})
        result = handler.set_roles()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "at least one" in data["error"].lower()
        assert mock_set.mock_calls == []
        assert mock_reconcile.mock_calls == []

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}._reconcile_availability_to_roles", return_value=[])
    @patch(f"{MODULE}.set_schedulable_roles")
    def test_set_roles_rejects_blanks_only(self, mock_set, mock_reconcile, mock_access):
        """Entries that are only whitespace normalize away to nothing."""
        handler = _make_handler(json_body={"schedulable_roles": ["", "  ", "\t"]})
        result = handler.set_roles()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert mock_set.mock_calls == []
        assert mock_reconcile.mock_calls == []


class TestProviderSortOrder:
    def test_viewer_is_pinned_first_and_flagged(self):
        """A provider should not have to hunt the list for their own row."""
        rows = [
            {"provider_id": "p-zed", "provider_name": "Zed Adams"},
            {"provider_id": "staff-1", "provider_name": "Wendy Yandura"},
            {"provider_id": "p-amy", "provider_name": "Amy Brooks"},
        ]

        result = _sort_providers_you_first(rows, "staff-1")

        assert [r["provider_id"] for r in result] == ["staff-1", "p-amy", "p-zed"]
        assert [r["is_you"] for r in result] == [True, False, False]

    def test_others_stay_alphabetical_when_the_viewer_is_not_a_provider(self):
        rows = [
            {"provider_id": "p-zed", "provider_name": "Zed Adams"},
            {"provider_id": "p-amy", "provider_name": "Amy Brooks"},
        ]

        result = _sort_providers_you_first(rows, "staff-99")

        assert [r["provider_id"] for r in result] == ["p-amy", "p-zed"]
        assert all(r["is_you"] is False for r in result)

    def test_unidentified_viewer_pins_nobody(self):
        rows = [{"provider_id": "p-amy", "provider_name": "Amy Brooks"}]

        result = _sort_providers_you_first(rows, "")

        assert result[0]["is_you"] is False

    def test_blank_names_sort_last(self):
        rows = [
            {"provider_id": "p-blank", "provider_name": ""},
            {"provider_id": "p-amy", "provider_name": "Amy Brooks"},
        ]

        result = _sort_providers_you_first(rows, "")

        assert [r["provider_id"] for r in result] == ["p-amy", "p-blank"]


class TestSavedView:
    @patch(f"{MODULE}.get_my_view", return_value=["p1", "p2"])
    def test_get_returns_the_viewers_saved_providers(self, mock_get):
        handler = _make_handler(staff_id="staff-1")

        result = handler.get_saved_view()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["provider_ids"] == ["p1", "p2"]
        assert mock_get.mock_calls == [call("staff-1")]

    @patch(f"{MODULE}.clear_my_view")
    @patch(f"{MODULE}.set_my_view")
    def test_save_uses_the_session_staff_id_not_the_body(self, mock_set, mock_clear):
        """One person must not be able to overwrite another person's saved view."""
        handler = _make_handler(
            json_body={"provider_ids": ["p1"], "staff_id": "someone-else"},
            staff_id="staff-1",
        )

        result = handler.save_saved_view()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert mock_set.mock_calls == [call("staff-1", ["p1"])]
        assert mock_clear.mock_calls == []

    @patch(f"{MODULE}.clear_my_view")
    @patch(f"{MODULE}.set_my_view")
    def test_empty_selection_means_show_everyone(self, mock_set, mock_clear):
        handler = _make_handler(json_body={"provider_ids": []}, staff_id="staff-1")

        result = handler.save_saved_view()

        data, code = _parse(result[0])
        assert code == HTTPStatus.OK
        assert data["provider_ids"] == []
        assert mock_set.mock_calls == []
        assert mock_clear.mock_calls == [call("staff-1")]

    @patch(f"{MODULE}.clear_my_view")
    @patch(f"{MODULE}.set_my_view")
    def test_blank_entries_are_dropped(self, mock_set, mock_clear):
        handler = _make_handler(
            json_body={"provider_ids": ["p1", "", "  ", "p2"]}, staff_id="staff-1"
        )

        result = handler.save_saved_view()

        data, _ = _parse(result[0])
        assert data["provider_ids"] == ["p1", "p2"]
        assert mock_set.mock_calls == [call("staff-1", ["p1", "p2"])]

    @patch(f"{MODULE}.set_my_view")
    def test_rejects_a_non_list(self, mock_set):
        handler = _make_handler(json_body={"provider_ids": "p1,p2"}, staff_id="staff-1")

        result = handler.save_saved_view()

        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "must be a list" in data["error"]
        assert mock_set.mock_calls == []

    @patch(f"{MODULE}.set_my_view")
    def test_rejects_when_the_viewer_cannot_be_identified(self, mock_set):
        handler = _make_handler(json_body={"provider_ids": ["p1"]}, staff_id="")

        result = handler.save_saved_view()

        data, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert mock_set.mock_calls == []


# ── expired items ──────────────────────────────────────────────────────


def _admin_access():
    from provider_availability.engine.access import Access
    return Access("staff1", True, None, "full")


def _no_access():
    from provider_availability.engine.access import Access
    return Access("staff1", False, None, "none")


class TestExpiredRoutes:
    @patch(f"{MODULE}.expired_summary", return_value={"count": 1, "items": [{"key": "rule:r1"}]})
    @patch(f"{MODULE}.get_active_providers", return_value=[{"id": "p1"}, {"id": "p2"}])
    @patch(f"{MODULE}._access", side_effect=lambda *a: _admin_access())
    def test_summary_covers_every_provider_an_admin_can_edit(self, mock_access, mock_providers, mock_summary):
        data, code = _parse(_make_handler().get_expired_summary()[0])
        assert code == HTTPStatus.OK
        assert data == {"count": 1, "items": [{"key": "rule:r1"}]}
        assert mock_summary.mock_calls == [call(["p1", "p2"])]

    @patch(f"{MODULE}.expired_summary", return_value={"count": 0, "items": []})
    @patch(f"{MODULE}.get_active_providers", return_value=[{"id": "p1"}, {"id": "p2"}])
    @patch(f"{MODULE}._access", side_effect=lambda *a: _no_access())
    def test_summary_is_empty_for_someone_who_cannot_edit(self, mock_access, mock_providers, mock_summary):
        _make_handler().get_expired_summary()
        assert mock_summary.mock_calls == [call([])]

    @patch(f"{MODULE}.remove_expired", return_value=2)
    @patch(f"{MODULE}.get_active_providers", return_value=[{"id": "p1"}])
    @patch(f"{MODULE}._access", side_effect=lambda *a: _admin_access())
    def test_remove_passes_the_picked_keys_and_the_viewers_scope(self, mock_access, mock_providers, mock_remove):
        handler = _make_handler(json_body={"keys": ["rule:r1", "block:b1"]})
        data, code = _parse(handler.remove_expired_items()[0])
        assert code == HTTPStatus.OK
        assert data["removed"] == 2
        assert mock_remove.mock_calls == [call(["rule:r1", "block:b1"], ["p1"])]

    @patch(f"{MODULE}.snooze_expired", return_value=date(2026, 11, 4))
    @patch(f"{MODULE}.list_expired", return_value=[{"key": "rule:r1"}])
    @patch(f"{MODULE}.get_active_providers", return_value=[{"id": "p1"}])
    @patch(f"{MODULE}._access", side_effect=lambda *a: _admin_access())
    def test_snooze_only_keeps_keys_the_viewer_can_see(self, mock_access, mock_providers, mock_list, mock_snooze):
        handler = _make_handler(json_body={"keys": ["rule:r1", "rule:someone-else"]})
        data, code = _parse(handler.snooze_expired_items()[0])
        assert code == HTTPStatus.OK
        assert data == {"until": "2026-11-04"}
        assert mock_snooze.mock_calls == [call(["rule:r1"])]

    def test_malformed_body_is_rejected(self):
        handler = _make_handler(json_body={"keys": "rule:r1"})
        _, code = _parse(handler.remove_expired_items()[0])
        assert code == HTTPStatus.BAD_REQUEST
        _, code = _parse(handler.snooze_expired_items()[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}.remove_expired", return_value=0)
    @patch(f"{MODULE}.get_active_providers", return_value=[{"id": "p1"}])
    @patch(f"{MODULE}._access", side_effect=lambda *a: _no_access())
    def test_someone_who_cannot_edit_removes_nothing(self, mock_access, mock_providers, mock_remove):
        """No separate gate: the scope is empty, so no provider's items can be touched."""
        handler = _make_handler(json_body={"keys": ["rule:r1"]})
        data, code = _parse(handler.remove_expired_items()[0])
        assert code == HTTPStatus.OK
        assert data["removed"] == 0
        assert mock_remove.mock_calls == [call(["rule:r1"], [])]


# ── malformed dates are a 400, not a server error ──────────────────────


class TestMalformedDates:
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_slots_bad_date(self, mock_resolve):
        handler = _make_handler()
        handler.request.query_params = {"provider_id": PROVIDER_ID, "start_date": "05/01/2026", "end_date": "2026-05-02"}
        data, code = _parse(handler.get_available_slots()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "YYYY-MM-DD" in data["error"]

    def test_available_providers_bad_date(self):
        handler = _make_handler()
        handler.request.query_params = {"start_date": "2026-05-01", "end_date": "soon"}
        data, code = _parse(handler.get_available_providers()[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_remove_override_bad_date(self, mock_get, mock_access):
        mock_get.return_value = ProviderAvailabilityRule(id="r1", provider_id=PROVIDER_ID)
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID, "rule_id": "r1", "override_date": "nope"})
        data, code = _parse(handler.remove_override()[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_update_block_bad_datetime(self, mock_access):
        handler = _make_handler(json_body={"id": "b1", "provider_id": PROVIDER_ID, "start": "tomorrow", "end": "later"})
        data, code = _parse(handler.update_block()[0])
        assert code == HTTPStatus.BAD_REQUEST


class TestStartDateRequired:
    @pytest.mark.parametrize("route", ["create_or_update_rule", "update_rule_group", "create_recurring_block", "update_recurring_block"])
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", new=lambda *a: None)
    @patch(f"{MODULE}.get_recurring_block_by_id", new=lambda *a: None)
    def test_missing_start_date_is_rejected(self, mock_access, route):
        handler = _make_handler(json_body={
            "id": RULE_ID, "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
        })
        data, code = _parse(getattr(handler, route)()[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert data["error"] == "Start date is required"

    def test_bad_start_date_is_rejected(self):
        from provider_availability.api.availability_api import _validate_recurrence_payload

        assert _validate_recurrence_payload({"effective_start": "10/05/2026"}) == "Start date must be YYYY-MM-DD"
        assert _validate_recurrence_payload({"effective_start": "2026-10-05"}) is None


# ── facility rounds on save ────────────────────────────────────────────────


ROUND_FACILITY_ID = "0d3c9f4e-5a2b-4c8d-9e1f-123456789abc"
ROUND_BODY = {
    "provider_id": PROVIDER_ID,
    "weekly_schedule": {"tuesday": [{"start": "08:00", "end": "12:00"}]},
    "facility_id": ROUND_FACILITY_ID,
    "facility_name": "Typed by the browser",
    "max_visits": 10,
    "effective_start": "2026-11-03",
}


class TestRoundSave:
    @patch(f"{MODULE}.is_feature_on", side_effect=lambda name: name != "facility_rounds")
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_new_round_refused_while_the_switch_is_off(self, _resolve, _access, _feature):
        handler = _make_handler(json_body=dict(ROUND_BODY))
        with patch(f"{MODULE}.save_rule") as save:
            result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert data["error"] == "Facility rounds are turned off in Settings."
        assert save.mock_calls == []

    @patch(f"{MODULE}.build_provider_lead_time_effects", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.is_feature_on", return_value=True)
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_round_saved_with_the_facility_name_from_canvas(self, _resolve, _access, _feature, _overlap, _sync, _lead):
        handler = _make_handler(json_body=dict(ROUND_BODY))
        with patch("provider_availability.engine.facilities.active_facility_name", return_value="Apple Valley Care"), \
             patch(f"{MODULE}.get_rules_for_provider", return_value=[]), \
             patch(f"{MODULE}.refresh_round_limits", return_value=["round-fx"]) as refresh, \
             patch(f"{MODULE}.save_rule") as save:
            result = handler.create_or_update_rule()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        saved = save.call_args.args[0]
        assert (saved.facility_id, saved.facility_name, saved.max_visits) == (ROUND_FACILITY_ID, "Apple Valley Care", 10)
        assert data["rule"]["facility_name"] == "Apple Valley Care"
        assert "sync-fx" in result
        assert "round-fx" in result
        assert refresh.mock_calls == [call(PROVIDER_ID)]

    @patch(f"{MODULE}.is_feature_on", return_value=True)
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_round_needs_an_active_facility(self, _resolve, _access, _feature):
        handler = _make_handler(json_body=dict(ROUND_BODY))
        with patch("provider_availability.engine.facilities.active_facility_name", return_value=None):
            result = handler.create_or_update_rule()
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert data["error"] == "Choose an active facility for this round."

    @patch(f"{MODULE}.delete_provider_lead_time_events", return_value=[])
    @patch(f"{MODULE}.lead_time_rules", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.is_feature_on", return_value=True)
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_group_update_copies_the_round_to_every_rule_in_the_group(
        self, _access, _feature, _overlap, _sync, _lead, _del_lead
    ):
        sibling = ProviderAvailabilityRule(id="r2", provider_id=PROVIDER_ID_2, group_id="g1")
        body = dict(ROUND_BODY, id=RULE_ID, group_id="g1", apply_to_group=True, max_visits=6)
        handler = _make_handler(json_body=body)
        with patch("provider_availability.engine.facilities.active_facility_name", return_value="Apple Valley Care"), \
             patch(f"{MODULE}.get_rules_by_group", return_value=[sibling]), \
             patch(f"{MODULE}.get_rule_by_id", return_value=None), \
             patch(f"{MODULE}.get_rules_for_provider", return_value=[]), \
             patch(f"{MODULE}.refresh_round_limits", return_value=[]) as refresh, \
             patch(f"{MODULE}.save_rule") as save:
            handler.update_rule_group()
        saved = {r.id: r for r in (c.args[0] for c in save.call_args_list)}
        assert (saved["r2"].facility_id, saved["r2"].facility_name, saved["r2"].max_visits) == (
            ROUND_FACILITY_ID, "Apple Valley Care", 6,
        )
        assert sorted(c.args[0] for c in refresh.mock_calls) == sorted([PROVIDER_ID, PROVIDER_ID_2])

    @patch(f"{MODULE}.delete_provider_lead_time_events", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.delete_rule_by_id")
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_deleting_a_round_clears_its_full_blocks(self, _access, _delete, _sync, _rules, _lead):
        doomed = ProviderAvailabilityRule(id=RULE_ID, provider_id=PROVIDER_ID, facility_id=ROUND_FACILITY_ID)
        handler = _make_handler(path_params={"provider_id": PROVIDER_ID, "rule_id": RULE_ID})
        with patch(f"{MODULE}.get_rule_by_id", return_value=doomed), \
             patch(f"{MODULE}.refresh_round_limits", return_value=["round-fx"]) as refresh:
            result = handler.delete_rule()
        assert "round-fx" in result
        assert refresh.mock_calls == [call(PROVIDER_ID)]


# ── Facility blocks ────────────────────────────────────────────────────────

FACILITY_ID = "0d3c9f4e-5a2b-4c8d-9e1f-123456789abc"
FACILITIES = "provider_availability.engine.facilities"


@pytest.fixture
def facility_blocks_on():
    from provider_availability.engine.settings import set_feature

    set_feature("facility_blocks", True)
    with patch(f"{FACILITIES}.active_facility_name", return_value="Riverstone Assisted Living"):
        yield


@patch(f"{MODULE}._check_write_access", return_value=None)
class TestFacilityBlocks:
    def test_a_single_facility_block_is_titled_for_canvas_and_blocks_every_location(self, _access, facility_blocks_on):
        body = {
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T13:00:00",
            "end": "2026-03-10T16:00:00",
            "reason": "PTO",
            "location_ids": [LOCATION_ID],
            "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.save_block") as save, patch(f"{MODULE}.build_block_event_effects", return_value=["evt"]) as draw:
            result = _make_handler(json_body=body).create_block()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        saved = save.call_args.args[0]
        assert (saved.reason, saved.location_ids, saved.facility_id, saved.facility_name) == (
            "Riverstone Assisted Living Visit", [], FACILITY_ID, "Riverstone Assisted Living",
        )
        assert draw.mock_calls == [call(saved)]
        assert data["block"]["facility_name"] == "Riverstone Assisted Living"

    def test_multi_date_facility_blocks_carry_the_facility(self, _access, facility_blocks_on):
        body = {"provider_id": PROVIDER_ID, "dates": ["2026-03-10", "2026-03-11"], "all_day": True, "facility_id": FACILITY_ID}
        with patch(f"{MODULE}.save_blocks") as save, patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            _make_handler(json_body=body).create_block()
        assert [(b.facility_id, b.reason) for b in _saved(save)] == [
            (FACILITY_ID, "Riverstone Assisted Living Visit")
        ] * 2

    def test_no_new_facility_block_while_the_switch_is_off(self, _access):
        body = {"provider_id": PROVIDER_ID, "start": "2026-03-10T13:00:00", "end": "2026-03-10T16:00:00", "facility_id": FACILITY_ID}
        with patch(f"{MODULE}.save_block") as save:
            result = _make_handler(json_body=body).create_block()
        data, code = _parse(result[0])
        assert (code, data["error"]) == (HTTPStatus.BAD_REQUEST, "Facility blocks are turned off in Settings.")
        assert save.mock_calls == []

    def test_a_saved_facility_block_can_be_edited_while_the_switch_is_off(self, _access):
        old = AdminBlock(
            id=BLOCK_ID, provider_id=PROVIDER_ID, start=datetime(2026, 3, 10, 13), end=datetime(2026, 3, 10, 16),
            reason="Old Name Visit", facility_id=FACILITY_ID, facility_name="Old Name",
        )
        body = {"id": BLOCK_ID, "provider_id": PROVIDER_ID, "start": "2026-03-10T14:00:00", "end": "2026-03-10T17:00:00", "facility_id": FACILITY_ID}
        with patch(f"{MODULE}.get_block_by_id", return_value=old), \
             patch(f"{MODULE}.build_delete_block_effects", return_value=[]), \
             patch(f"{MODULE}.build_block_event_effects", return_value=[]), \
             patch(f"{FACILITIES}.active_facility_name", return_value=None), \
             patch(f"{MODULE}.save_block") as save:
            result = _make_handler(json_body=body).update_block()
        assert _parse(result[-1])[1] == HTTPStatus.OK
        saved = save.call_args.args[0]
        assert (saved.reason, saved.facility_name, saved.start) == ("Old Name Visit", "Old Name", datetime(2026, 3, 10, 14))

    def test_a_group_edit_moves_every_block_to_the_facility(self, _access, facility_blocks_on):
        other = AdminBlock(
            id=BLOCK_ID_2, provider_id=PROVIDER_ID_2, start=datetime(2026, 3, 10, 9), end=datetime(2026, 3, 10, 12),
            reason="PTO", location_ids=[LOCATION_ID], group_id="g-1",
        )
        body = {
            "id": BLOCK_ID, "provider_id": PROVIDER_ID, "start": "2026-03-10T13:00:00", "end": "2026-03-10T16:00:00",
            "group_id": "g-1", "apply_to_group": True, "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.get_blocks_by_group", return_value=[other]), \
             patch(f"{MODULE}.get_block_by_id", return_value=None), \
             patch(f"{MODULE}.build_delete_block_effects", return_value=[]), \
             patch(f"{MODULE}.build_block_event_effects", return_value=[]), \
             patch(f"{MODULE}.save_block"):
            _make_handler(json_body=body).update_block()
        assert (other.reason, other.facility_id, other.location_ids) == ("Riverstone Assisted Living Visit", FACILITY_ID, [])

    def test_a_recurring_facility_block(self, _access, facility_blocks_on):
        body = {
            "provider_id": PROVIDER_ID,
            "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]},
            "location_ids": [LOCATION_ID],
            "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.save_recurring_block") as save, patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[]):
            result = _make_handler(json_body=body).create_recurring_block()
        assert _parse(result[-1])[1] == HTTPStatus.CREATED
        saved = save.call_args.args[0]
        assert (saved.reason, saved.location_ids, saved.facility_name, saved.hold_type) == (
            "Riverstone Assisted Living Visit", [], "Riverstone Assisted Living", "none",
        )

    def test_moving_a_time_off_block_to_a_facility_needs_the_switch(self, _access):
        old = AdminBlock(id=BLOCK_ID, provider_id=PROVIDER_ID, start=datetime(2026, 3, 10, 13), end=datetime(2026, 3, 10, 16), reason="PTO")
        body = {"id": BLOCK_ID, "provider_id": PROVIDER_ID, "start": "2026-03-10T13:00:00", "end": "2026-03-10T16:00:00", "facility_id": FACILITY_ID}
        with patch(f"{MODULE}.get_block_by_id", return_value=old), patch(f"{MODULE}.save_block") as save:
            result = _make_handler(json_body=body).update_block()
        data, code = _parse(result[0])
        assert (code, data["error"]) == (HTTPStatus.BAD_REQUEST, "Facility blocks are turned off in Settings.")
        assert save.mock_calls == []

    def test_no_new_recurring_facility_block_while_the_switch_is_off(self, _access):
        body = {
            "provider_id": PROVIDER_ID, "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.save_recurring_block") as save:
            result = _make_handler(json_body=body).create_recurring_block()
        data, code = _parse(result[0])
        assert (code, data["error"]) == (HTTPStatus.BAD_REQUEST, "Facility blocks are turned off in Settings.")
        assert save.mock_calls == []

    def _group(self):
        return [
            AdminBlock(id=f"b-{i}", provider_id=PROVIDER_ID, start=datetime(2026, 3, 10 + i, 13), end=datetime(2026, 3, 10 + i, 16),
                       reason="Old Name Visit", group_id="g-1", facility_id=FACILITY_ID, facility_name="Old Name")
            for i in range(3)
        ]

    def test_editing_a_saved_facility_group_while_off_replaces_it_after_the_checks(self, _access):
        group = self._group()
        by_id = {b.id: b for b in group}
        body = {
            "provider_id": PROVIDER_ID, "dates": ["2026-03-10", "2026-03-12"], "all_day": False,
            "start": "1970-01-01T14:00:00", "end": "1970-01-01T17:00:00", "group_id": "g-1",
            "facility_id": FACILITY_ID, "replace_block_ids": [b.id for b in group],
        }
        with patch(f"{MODULE}.get_block_by_id", side_effect=lambda pid, bid: by_id.get(bid)), \
             patch(f"{FACILITIES}.active_facility_name", return_value=None), \
             patch(f"{MODULE}.build_delete_blocks_effects", return_value=["del"]) as dele, \
             patch(f"{MODULE}.delete_blocks") as delete, \
             patch(f"{MODULE}.build_block_event_effects", return_value=["new"]), \
             patch(f"{MODULE}.save_blocks") as save:
            result = _make_handler(json_body=body).create_block()
        assert _parse(result[-1])[1] == HTTPStatus.CREATED
        assert result[:-1] == ["del"] + ["new"] * 2
        assert [(b.provider_id, b.id) for b in _saved(delete)] == [(PROVIDER_ID, b.id) for b in group]
        assert [b.id for b in _saved(dele)] == [b.id for b in group]
        assert [b.reason for b in _saved(save)] == ["Old Name Visit"] * 2

    def test_a_refused_replacement_leaves_the_saved_blocks(self, _access):
        group = self._group()
        by_id = {b.id: b for b in group}
        other = "11111111-2222-3333-4444-555555555555"
        body = {
            "provider_id": PROVIDER_ID, "dates": ["2026-03-10"], "all_day": True, "group_id": "g-1",
            "facility_id": other, "replace_block_ids": [b.id for b in group],
        }
        with patch(f"{MODULE}.get_block_by_id", side_effect=lambda pid, bid: by_id.get(bid)), \
             patch(f"{MODULE}.delete_block") as delete, patch(f"{MODULE}.save_block") as save:
            result = _make_handler(json_body=body).create_block()
        data, code = _parse(result[0])
        assert (code, data["error"]) == (HTTPStatus.BAD_REQUEST, "Facility blocks are turned off in Settings.")
        assert delete.mock_calls == [] and save.mock_calls == []

    def test_a_bad_date_leaves_the_saved_blocks(self, _access, facility_blocks_on):
        group = self._group()
        body = {
            "provider_id": PROVIDER_ID, "dates": ["2026-03-10", "2026-03-11"], "all_day": False,
            "start": "1970-01-01T17:00:00", "end": "1970-01-01T14:00:00", "facility_id": FACILITY_ID,
            "replace_block_ids": [b.id for b in group],
        }
        with patch(f"{MODULE}.get_block_by_id", side_effect=lambda pid, bid: group[0]), \
             patch(f"{MODULE}.delete_block") as delete, patch(f"{MODULE}.save_block") as save:
            result = _make_handler(json_body=body).create_block()
        assert _parse(result[0])[1] == HTTPStatus.BAD_REQUEST
        assert delete.mock_calls == [] and save.mock_calls == []

    def test_converting_a_saved_facility_block_to_recurring_while_off(self, _access):
        old = self._group()[0]
        body = {
            "provider_id": PROVIDER_ID, "effective_start": "2026-01-05", "replace_block_id": old.id,
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.get_block_by_id", return_value=old), \
             patch(f"{FACILITIES}.active_facility_name", return_value=None), \
             patch(f"{MODULE}.build_delete_block_effects", return_value=[]), \
             patch(f"{MODULE}.delete_block"), \
             patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[]), \
             patch(f"{MODULE}.save_recurring_block") as save:
            result = _make_handler(json_body=body).create_recurring_block()
        assert _parse(result[-1])[1] == HTTPStatus.CREATED
        assert save.call_args.args[0].reason == "Old Name Visit"

    def test_a_facility_block_sent_as_a_hold_saves_while_holds_are_off(self, _access, facility_blocks_on):
        from provider_availability.engine.settings import set_feature

        set_feature("holds", False)
        body = {
            "provider_id": PROVIDER_ID, "effective_start": "2026-01-05", "hold_type": "same_day",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.save_recurring_block") as save, patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[]):
            result = _make_handler(json_body=body).create_recurring_block()
        assert _parse(result[-1])[1] == HTTPStatus.CREATED
        assert save.call_args.args[0].hold_type == "none"

    def test_a_recurring_facility_block_edit_needs_the_switch_for_a_new_facility(self, _access):
        before = RecurringBlock(id=RB_ID, provider_id=PROVIDER_ID, reason="PTO")
        body = {
            "id": RB_ID, "provider_id": PROVIDER_ID, "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.get_recurring_block_by_id", return_value=before), \
             patch(f"{MODULE}.save_recurring_block") as save:
            result = _make_handler(json_body=body).update_recurring_block()
        data, code = _parse(result[0])
        assert (code, data["error"]) == (HTTPStatus.BAD_REQUEST, "Facility blocks are turned off in Settings.")
        assert save.mock_calls == []

    def test_a_recurring_group_edit_moves_every_block_to_the_facility(self, _access, facility_blocks_on):
        other = RecurringBlock(id=RB_ID_2, provider_id=PROVIDER_ID_2, reason="PTO", location_ids=[LOCATION_ID], group_id="g-1", hold_type="same_day")
        body = {
            "id": RB_ID, "provider_id": PROVIDER_ID, "group_id": "g-1", "apply_to_group": True, "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "facility_id": FACILITY_ID,
        }
        with patch(f"{MODULE}.get_recurring_blocks_by_group", return_value=[other]), \
             patch(f"{MODULE}.get_recurring_block_by_id", return_value=None), \
             patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=[]), \
             patch(f"{MODULE}.save_recurring_block"):
            _make_handler(json_body=body).update_recurring_block()
        assert (other.reason, other.facility_id, other.location_ids, other.hold_type) == (
            "Riverstone Assisted Living Visit", FACILITY_ID, [], "none",
        )


class TestFacilityList:
    FACS = [{"id": FACILITY_ID, "name": "Riverstone"}]

    def test_nothing_sent_while_both_switches_are_off(self):
        with patch(f"{MODULE}.get_active_facilities") as facs:
            assert _make_handler()._round_facilities() == {"facilities": [], "by_provider": {}}
        assert facs.mock_calls == []

    def test_facility_blocks_on_sends_the_list_without_counting_patients(self):
        from provider_availability.engine.settings import set_feature

        set_feature("facility_blocks", True)
        with patch(f"{MODULE}.get_active_facilities", return_value=self.FACS), \
             patch(f"{MODULE}.facility_patient_counts") as counts, \
             patch(f"{MODULE}.get_provider_facilities", return_value={}) as by_provider:
            assert _make_handler()._round_facilities() == {"facilities": self.FACS, "by_provider": {}}
        assert counts.mock_calls == []
        assert by_provider.mock_calls == [call({FACILITY_ID}, None)]

    def test_patient_counts_come_on_request_while_facility_blocks_are_on(self):
        from provider_availability.engine.settings import set_feature

        set_feature("facility_blocks", True)
        with patch(f"{MODULE}.facility_patient_counts", return_value={FACILITY_ID: 6}):
            data, code = _parse(_make_handler().get_facility_patient_counts()[0])
        assert (code, data) == (HTTPStatus.OK, {"counts": {FACILITY_ID: 6}})

    def test_no_patient_counts_while_facility_blocks_are_off(self):
        with patch(f"{MODULE}.facility_patient_counts") as counts:
            data, _ = _parse(_make_handler().get_facility_patient_counts()[0])
        assert data == {"counts": {}}
        assert counts.mock_calls == []

    def test_no_patient_counts_for_staff_with_no_access_to_others(self):
        from provider_availability.engine.access import Access
        from provider_availability.engine.settings import set_feature

        set_feature("facility_blocks", True)
        no_access = Access("staff-1", is_admin=False, group_providers=None, default_access="none")
        with patch(f"{MODULE}._access", return_value=no_access), \
             patch(f"{MODULE}.facility_patient_counts") as counts:
            data, _ = _parse(_make_handler().get_facility_patient_counts()[0])
        assert data == {"counts": {}}
        assert counts.mock_calls == []


@pytest.mark.parametrize("route", ["create_or_update_rule", "update_rule_group", "create_block", "update_block", "create_recurring_block", "update_recurring_block"])
def test_an_id_that_is_not_a_uuid_is_refused(route):
    body = {"id": 'x"),alert(1),("', "provider_id": PROVIDER_ID}
    with patch(f"{MODULE}._check_write_access", return_value=None):
        data, code = _parse(getattr(_make_handler(json_body=body), route)()[0])
    assert (code, data["error"]) == (HTTPStatus.BAD_REQUEST, "id must be the id of a saved item")


def test_an_undashed_uuid_id_is_accepted():
    from provider_availability.api.availability_api import _id_error

    assert _id_error({"id": "0a1b2c3d00004000800000000000000a"}) is None
    assert _id_error({}) is None
    assert _id_error({"id": 5}) is not None



@patch(f"{MODULE}._check_write_access", return_value=None)
class TestReplaceAndGroupLocations:
    def test_one_request_saves_dates_with_their_own_times(self, _access):
        body = {
            "provider_id": PROVIDER_ID,
            "entries": [
                {"date": "2026-03-12", "all_day": False, "start": "09:00:00", "end": "10:00:00"},
                {"date": "2026-03-10", "all_day": True, "start": "", "end": ""},
            ],
        }
        with patch(f"{MODULE}.save_blocks") as save, patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            result = _make_handler(json_body=body).create_block()
        data, code = _parse(result[-1])
        saved = _saved(save)
        assert code == HTTPStatus.CREATED
        assert [(b.start, b.end, b.all_day) for b in saved] == [
            (datetime(2026, 3, 10, 0, 0), datetime(2026, 3, 10, 23, 59, 59), True),
            (datetime(2026, 3, 12, 9, 0), datetime(2026, 3, 12, 10, 0), False),
        ]
        assert saved[0].group_id and saved[0].group_id == saved[1].group_id == data["group_id"]

    def test_one_bad_entry_saves_nothing_and_keeps_the_replaced_blocks(self, _access):
        old = AdminBlock(id=BLOCK_ID, provider_id=PROVIDER_ID, start=datetime(2026, 3, 10, 9), end=datetime(2026, 3, 10, 10))
        body = {
            "provider_id": PROVIDER_ID, "replace_block_ids": [BLOCK_ID],
            "entries": [
                {"date": "2026-03-10", "all_day": True},
                {"date": "2026-03-11", "all_day": False, "start": "10:00:00", "end": "09:00:00"},
            ],
        }
        with patch(f"{MODULE}.get_block_by_id", return_value=old), \
             patch(f"{MODULE}.delete_block") as delete, patch(f"{MODULE}.save_block") as save:
            result = _make_handler(json_body=body).create_block()
        assert _parse(result[0])[1] == HTTPStatus.BAD_REQUEST
        assert delete.mock_calls == [] and save.mock_calls == []

    def test_entries_must_be_a_list_of_objects(self, _access):
        result = _make_handler(json_body={"provider_id": PROVIDER_ID, "entries": ["2026-03-10"]}).create_block()
        assert _parse(result[0]) == ({"error": "entries must be a list of dates with times"}, HTTPStatus.BAD_REQUEST)

    def test_a_single_replacement_removes_the_old_block_before_saving_the_new_one(self, _access):
        old = AdminBlock(id=BLOCK_ID, provider_id=PROVIDER_ID, start=datetime(2026, 3, 10, 9), end=datetime(2026, 3, 10, 10))
        order: list[str] = []

        def delete_events(*args, **kwargs):
            order.append("delete events")
            return []

        body = {"provider_id": PROVIDER_ID, "start": "2026-03-10T09:00:00", "end": "2026-03-10T10:00:00", "replace_block_ids": [BLOCK_ID]}
        with patch(f"{MODULE}.get_block_by_id", return_value=old), \
             patch(f"{MODULE}.build_delete_blocks_effects", side_effect=delete_events), \
             patch(f"{MODULE}.delete_blocks", side_effect=lambda *a: order.append("delete block")), \
             patch(f"{MODULE}.save_block", side_effect=lambda b: order.append("save")), \
             patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            _make_handler(json_body=body).create_block()
        assert order == ["delete events", "delete block", "save"]

    def test_a_group_leaving_a_facility_takes_the_edited_blocks_locations(self, _access):
        other = AdminBlock(
            id=BLOCK_ID_2, provider_id=PROVIDER_ID_2, start=datetime(2026, 3, 10, 9), end=datetime(2026, 3, 10, 12),
            reason="Riverstone Visit", group_id="g-1", facility_id=FACILITY_ID, facility_name="Riverstone",
        )
        body = {
            "id": BLOCK_ID, "provider_id": PROVIDER_ID, "start": "2026-03-10T13:00:00", "end": "2026-03-10T16:00:00",
            "group_id": "g-1", "apply_to_group": True, "reason": "PTO", "location_ids": [LOCATION_ID],
        }
        with patch(f"{MODULE}.get_blocks_by_group", return_value=[other]), \
             patch(f"{MODULE}.get_block_by_id", return_value=None), \
             patch(f"{MODULE}.build_delete_block_effects", return_value=[]), \
             patch(f"{MODULE}.build_block_event_effects", return_value=[]), \
             patch(f"{MODULE}.save_block"):
            _make_handler(json_body=body).update_block()
        assert (other.facility_id, other.reason, other.location_ids) == ("", "PTO", [LOCATION_ID])

    def test_a_time_off_group_keeps_each_blocks_own_locations(self, _access):
        other = AdminBlock(
            id=BLOCK_ID_2, provider_id=PROVIDER_ID_2, start=datetime(2026, 3, 10, 9), end=datetime(2026, 3, 10, 12),
            reason="PTO", group_id="g-1", location_ids=["loc-own"],
        )
        body = {
            "id": BLOCK_ID, "provider_id": PROVIDER_ID, "start": "2026-03-10T13:00:00", "end": "2026-03-10T16:00:00",
            "group_id": "g-1", "apply_to_group": True, "reason": "PTO", "location_ids": [LOCATION_ID],
        }
        with patch(f"{MODULE}.get_blocks_by_group", return_value=[other]), \
             patch(f"{MODULE}.get_block_by_id", return_value=None), \
             patch(f"{MODULE}.build_delete_block_effects", return_value=[]), \
             patch(f"{MODULE}.build_block_event_effects", return_value=[]), \
             patch(f"{MODULE}.save_block"):
            _make_handler(json_body=body).update_block()
        assert other.location_ids == ["loc-own"]

    def test_a_recurring_group_leaving_a_facility_takes_the_edited_blocks_locations(self, _access):
        other = RecurringBlock(id=RB_ID_2, provider_id=PROVIDER_ID_2, reason="Riverstone Visit", group_id="g-1",
                               facility_id=FACILITY_ID, facility_name="Riverstone")
        body = {
            "id": RB_ID, "provider_id": PROVIDER_ID, "group_id": "g-1", "apply_to_group": True, "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "reason": "Lunch", "location_ids": [LOCATION_ID],
        }
        with patch(f"{MODULE}.get_recurring_blocks_by_group", return_value=[other]), \
             patch(f"{MODULE}.get_recurring_block_by_id", return_value=None), \
             patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=[]), \
             patch(f"{MODULE}.save_recurring_block"):
            _make_handler(json_body=body).update_recurring_block()
        assert (other.facility_id, other.location_ids) == ("", [LOCATION_ID])


@patch(f"{MODULE}._check_write_access", return_value=None)
class TestManyProvidersInOneRequest:
    P1 = "0a1b2c3d00004000800000000000a001"
    P2 = "0a1b2c3d00004000800000000000a002"
    ENTRIES = [{"date": "2026-03-10", "all_day": True}, {"date": "2026-03-11", "all_day": False, "start": "09:00:00", "end": "10:00:00"}]

    def test_every_provider_gets_every_date_in_one_group(self, access):
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES}
        with patch(f"{MODULE}.save_blocks") as save, patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            result = _make_handler(json_body=body).create_block()
        saved = _saved(save)
        assert _parse(result[-1])[1] == HTTPStatus.CREATED
        assert [(b.provider_id, b.start.day) for b in saved] == [(self.P1, 10), (self.P1, 11), (self.P2, 10), (self.P2, 11)]
        assert len({b.group_id for b in saved}) == 1 and saved[0].group_id
        assert access.call_args.args[2] == [self.P1, self.P2]

    def test_the_same_provider_dashed_and_undashed_gets_one_set(self, access):
        dashed = "0a1b2c3d-0000-4000-8000-00000000a002"
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2, dashed], "entries": self.ENTRIES}
        with patch(f"{MODULE}.save_blocks") as save, patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            _make_handler(json_body=body).create_block()
        assert len(_saved(save)) == 4

    def test_a_malformed_provider_id_is_refused_before_anything(self, access):
        body = {"provider_id": self.P1, "provider_ids": [self.P1, "abc"], "entries": self.ENTRIES}
        with patch(f"{MODULE}.save_block") as save:
            data, code = _parse(_make_handler(json_body=body).create_block()[0])
        assert code == HTTPStatus.BAD_REQUEST and save.mock_calls == []

    def test_an_error_building_events_leaves_saved_blocks_alone(self, access):
        old = AdminBlock(id=BLOCK_ID, provider_id=self.P1, start=datetime(2026, 3, 9, 9), end=datetime(2026, 3, 9, 10))
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES,
                "replace_blocks": [{"provider_id": self.P1, "id": BLOCK_ID}]}
        with patch(f"{MODULE}.get_block_by_id", return_value=old), \
             patch(f"{MODULE}.build_delete_block_effects", return_value=[]), \
             patch(f"{MODULE}.build_block_event_effects", side_effect=[[], [], RuntimeError("calendar lookup failed")]), \
             patch(f"{MODULE}.delete_block") as delete, patch(f"{MODULE}.save_block") as save:
            with pytest.raises(RuntimeError):
                _make_handler(json_body=body).create_block()
        assert delete.mock_calls == [] and save.mock_calls == []

    def test_one_lookups_dict_is_shared_across_the_save(self, access):
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES}
        with patch(f"{MODULE}.save_blocks"), patch(f"{MODULE}.build_block_event_effects", return_value=[]) as draw:
            _make_handler(json_body=body).create_block()
        memos = {id(c.args[1]) for c in draw.mock_calls}
        assert len(draw.mock_calls) == 4 and len(memos) == 1

    def test_a_provider_the_user_cant_edit_saves_nothing(self, access):
        access.return_value = ["denied"]
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES, "replace_block_ids": [BLOCK_ID]}
        with patch(f"{MODULE}.delete_block") as delete, patch(f"{MODULE}.save_block") as save:
            assert _make_handler(json_body=body).create_block() == ["denied"]
        assert delete.mock_calls == [] and save.mock_calls == []

    def test_replaced_blocks_are_found_under_each_provider(self, access):
        old_a = AdminBlock(id=BLOCK_ID, provider_id=self.P1, start=datetime(2026, 3, 9, 9), end=datetime(2026, 3, 9, 10), group_id="g")
        old_b = AdminBlock(id=BLOCK_ID_2, provider_id=self.P2, start=datetime(2026, 3, 9, 9), end=datetime(2026, 3, 9, 10), group_id="g")
        found = {(self.P1, BLOCK_ID): old_a, (self.P2, BLOCK_ID_2): old_b}
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES, "group_id": "g",
                "replace_blocks": [{"provider_id": self.P1, "id": BLOCK_ID}, {"provider_id": self.P2, "id": BLOCK_ID_2},
                                   {"provider_id": "0a1b2c3d00004000800000000000ffff", "id": BLOCK_ID}]}
        with patch(f"{MODULE}.get_block_by_id", side_effect=lambda p, b: found.get((p, b))) as lookup, \
             patch(f"{MODULE}.build_delete_blocks_effects", return_value=[]), \
             patch(f"{MODULE}.delete_blocks") as delete, \
             patch(f"{MODULE}.save_blocks"), patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            _make_handler(json_body=body).create_block()
        # One lookup per block, under its own provider; a provider outside the save is ignored.
        assert lookup.mock_calls == [call(self.P1, BLOCK_ID), call(self.P2, BLOCK_ID_2)]
        assert [(b.provider_id, b.id) for b in _saved(delete)] == [(self.P1, BLOCK_ID), (self.P2, BLOCK_ID_2)]

    def test_provider_ids_must_be_a_list_with_dates(self, access):
        bad: list[dict[str, Any]] = [{"provider_ids": PROVIDER_ID_2, "entries": self.ENTRIES}, {"provider_ids": [PROVIDER_ID_2]}, {"provider_ids": [5], "entries": self.ENTRIES}]
        for extra in bad:
            data, code = _parse(_make_handler(json_body={"provider_id": PROVIDER_ID, **extra}).create_block()[0])
            assert code == HTTPStatus.BAD_REQUEST

    def test_a_recurring_block_is_replaced_for_one_provider_only(self, access):
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES, "replace_recurring_block_id": RB_ID}
        data, code = _parse(_make_handler(json_body=body).create_block()[0])
        assert code == HTTPStatus.BAD_REQUEST

    def test_changing_a_recurring_block_to_several_dates_removes_it(self, access):
        rb = RecurringBlock(id=RB_ID, provider_id=PROVIDER_ID, reason="Lunch")
        body = {"provider_id": PROVIDER_ID, "entries": self.ENTRIES, "replace_recurring_block_id": RB_ID}
        with patch(f"{MODULE}.get_recurring_block_by_id", return_value=rb), \
             patch(f"{MODULE}.build_delete_recurring_block_effects", return_value=["del-rb"]), \
             patch(f"{MODULE}.delete_recurring_block") as delete_rb, \
             patch(f"{MODULE}.save_blocks") as save, patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            result = _make_handler(json_body=body).create_block()
        assert "del-rb" in result
        assert delete_rb.mock_calls == [call(PROVIDER_ID, RB_ID)]
        assert len(_saved(save)) == 2

    def test_a_recurring_group_leaving_a_facility_takes_the_hold_setting(self, access):
        other = RecurringBlock(id=RB_ID_2, provider_id=PROVIDER_ID_2, reason="Riverstone Visit", group_id="g-1",
                               facility_id=FACILITY_ID, facility_name="Riverstone")
        body = {
            "id": RB_ID, "provider_id": PROVIDER_ID, "group_id": "g-1", "apply_to_group": True, "effective_start": "2026-01-05",
            "weekly_schedule": {"friday": [{"start": "13:00", "end": "16:00"}]}, "hold_type": "same_day", "location_ids": [LOCATION_ID],
        }
        with patch(f"{MODULE}.get_recurring_blocks_by_group", return_value=[other]), \
             patch(f"{MODULE}.get_recurring_block_by_id", return_value=None), \
             patch(f"{MODULE}.build_recurring_blocks_resync_effects", return_value=[]), \
             patch(f"{MODULE}.save_recurring_block"):
            _make_handler(json_body=body).update_recurring_block()
        assert (other.hold_type, other.location_ids) == ("same_day", [LOCATION_ID])


def test_can_view_others():
    from provider_availability.engine.access import Access

    assert Access("s", False, None, "view").can_view_others() is True
    assert Access("s", False, None, "none").can_view_others() is False
    assert Access("s", False, set(), "none").can_view_others() is False  # a group with no providers
    assert Access("s", False, {"p"}, "none").can_view_others() is True
    assert Access("s", True, None, "none").can_view_others() is True
    assert Access("", True, None, "full").can_view_others() is False


@patch(f"{MODULE}._check_write_access", return_value=None)
class TestReplaceLookups:
    P1 = "0a1b2c3d00004000800000000000a001"
    P1_DASHED = "0a1b2c3d-0000-4000-8000-00000000a001"
    P2 = "0a1b2c3d00004000800000000000a002"
    ENTRIES = [{"date": "2026-03-10", "all_day": True}]

    def test_old_shape_finds_a_siblings_block_under_its_provider(self, _access):
        old_b = AdminBlock(id=BLOCK_ID_2, provider_id=self.P2, start=datetime(2026, 3, 9, 9), end=datetime(2026, 3, 9, 10))
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES, "replace_block_ids": [BLOCK_ID_2]}
        with patch(f"{MODULE}.get_block_by_id", side_effect=lambda p, b: old_b if p == self.P2 else None), \
             patch(f"{MODULE}.build_delete_blocks_effects", return_value=[]), \
             patch(f"{MODULE}.delete_blocks") as delete, \
             patch(f"{MODULE}.save_blocks"), patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            _make_handler(json_body=body).create_block()
        assert [(b.provider_id, b.id) for b in _saved(delete)] == [(self.P2, BLOCK_ID_2)]

    def test_a_block_saved_under_the_dashed_id_is_found(self, _access):
        old = AdminBlock(id=BLOCK_ID, provider_id=self.P1_DASHED, start=datetime(2026, 3, 9, 9), end=datetime(2026, 3, 9, 10))
        body = {"provider_id": self.P1, "provider_ids": [self.P1, self.P2], "entries": self.ENTRIES,
                "replace_blocks": [{"provider_id": self.P1_DASHED, "id": BLOCK_ID}]}
        with patch(f"{MODULE}.get_block_by_id", side_effect=lambda p, b: old if p == self.P1_DASHED else None), \
             patch(f"{MODULE}.build_delete_blocks_effects", return_value=[]), \
             patch(f"{MODULE}.delete_blocks") as delete, \
             patch(f"{MODULE}.save_blocks"), patch(f"{MODULE}.build_block_event_effects", return_value=[]):
            _make_handler(json_body=body).create_block()
        assert [(b.provider_id, b.id) for b in _saved(delete)] == [(self.P1_DASHED, BLOCK_ID)]


def test_a_scheduler_grouped_only_with_themselves_sees_no_counts():
    from provider_availability.engine.access import Access

    assert Access("s", False, {"s"}, "none").can_view_others() is False
    assert Access("s", False, {"s", "p"}, "none").can_view_others() is True
