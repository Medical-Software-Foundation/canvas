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
from datetime import date, datetime, time
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

from provider_availability.api.availability_api import (
    AvailabilityAPI,
    _check_write_access,
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


def _parse(response) -> tuple[dict, int]:
    """Extract (body_dict, status_code) from a JSONResponse."""
    body = json.loads(getattr(response, "content"))
    return body, response.status_code


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
    handler.request.staff_id = staff_id
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
    @patch(f"{MODULE}.build_lead_time_block_effects", return_value=["lead-fx"])
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
            id="r1",
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
            "id": "r1",
            "provider_id": PROVIDER_ID,
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
        assert mock_lead.mock_calls == [call(mock_lead.call_args[0][0])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_lead_time_block_effects")
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
        mock_access,
    ):
        """No remaining lead-time rule -> orphaned Lead Time events are deleted."""
        cal = MagicMock()
        cal.id = "cal-1"
        evt = MagicMock()
        evt.id = "evt-1"
        del_effect = MagicMock()
        event_effect = MagicMock()
        event_effect.delete.return_value = del_effect

        body = {
            "id": "r1",
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {},
        }
        handler = _make_handler(json_body=body)
        with patch(
            "provider_availability.engine.admin_calendar.get_admin_calendars",
            return_value=[cal],
        ) as mock_cals, patch(
            "canvas_sdk.v1.data.calendar.Event"
        ) as mock_event_model, patch(
            "canvas_sdk.effects.calendar.Event", return_value=event_effect
        ) as mock_event_effect:
            mock_event_model.objects.filter.return_value = [evt]
            result = handler.update_rule_group()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert del_effect in result
        assert mock_lead.mock_calls == []
        assert mock_cals.mock_calls == [call(PROVIDER_ID)]
        mock_event_effect.assert_called_once_with(event_id="evt-1")


# ── delete_rule: lead-time refresh + orphan cleanup ────────────────────────


class TestDeleteRuleBranches:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_lead_time_block_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_refreshes_lead_time_for_remaining_rule(
        self, mock_delete, mock_get_rules, mock_sync, mock_lead, mock_access
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
        assert mock_lead.mock_calls == [call(mock_lead.call_args[0][0])]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_lead_time_block_effects")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_orphan_cleanup_when_no_remaining_lead_time(
        self, mock_delete, mock_get_rules, mock_sync, mock_lead, mock_access
    ):
        cal = MagicMock()
        cal.id = "cal-9"
        evt = MagicMock()
        evt.id = "evt-9"
        del_effect = MagicMock()
        event_effect = MagicMock()
        event_effect.delete.return_value = del_effect

        handler = _make_handler(
            path_params={"provider_id": PROVIDER_ID, "rule_id": "r1"}
        )
        with patch(
            "provider_availability.engine.admin_calendar.get_admin_calendars",
            return_value=[cal],
        ) as mock_cals, patch(
            "canvas_sdk.v1.data.calendar.Event"
        ) as mock_event_model, patch(
            "canvas_sdk.effects.calendar.Event", return_value=event_effect
        ) as mock_event_effect:
            mock_event_model.objects.filter.return_value = [evt]
            result = handler.delete_rule()

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert del_effect in result
        assert mock_lead.mock_calls == []
        assert mock_cals.mock_calls == [call(PROVIDER_ID)]
        mock_event_effect.assert_called_once_with(event_id="evt-9")


# ── add_override / remove_override: lead-time + recurring re-sync ──────────


class TestOverrideResyncBranches:
    def _rule(self) -> ProviderAvailabilityRule:
        return ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"thursday": [TimeWindow(start=time(9, 0), end=time(15, 0))]},
            is_active=True,
        )

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.build_lead_time_block_effects", return_value=["lead-fx"])
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
        assert mock_rb_sync.mock_calls == [call(active_rb)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.build_lead_time_block_effects", return_value=["lead-fx"])
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
        assert mock_rb_sync.mock_calls == [call(active_rb)]


# ── create_block: per-date timed path + replace_recurring_block ────────────


class TestCreateBlockBranches:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
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
        assert len(mock_save.mock_calls) == 2

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
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 8, 0),
            end=datetime(2026, 3, 10, 11, 0),
            group_id="g1",
        )
        mock_group.return_value = [same]
        body = {
            "id": "b1",
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
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.set_provider_timezone")
    def test_success_resyncs_matching_recurring_blocks(
        self, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
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
        assert mock_rb_sync.mock_calls == [call(matching)]

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
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.set_provider_timezone")
    def test_success_sets_all_and_resyncs(
        self, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
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
        assert mock_rb_sync.mock_calls == [call(matching)]


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
    @patch(f"{MODULE}.build_lead_time_block_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value=None)
    @patch(f"{MODULE}.resolve_provider_id", return_value=PROVIDER_ID)
    def test_active_lead_time_rule_appends_effects(
        self, mock_resolve, mock_overlap, mock_save, mock_sync, mock_lead, mock_access
    ):
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
            "is_active": True,
            "booking_interval": {"min_lead_hours": 48},
        }
        handler = _make_handler(json_body=body)
        result = handler.create_or_update_rule()
        data, code = _parse(result[-1])
        assert code == HTTPStatus.CREATED
        assert "lead-fx" in result
        assert mock_lead.mock_calls == [call(mock_lead.call_args[0][0])]


# ── _form_set_provider_timezone / _form_set_provider_tz_bulk ───────────────


class TestFormSetProviderTimezone:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_id(self, mock_access):
        handler = _make_handler()
        result = handler._form_set_provider_timezone({"timezone": "US/Eastern"})
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id required" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone(self, mock_access):
        handler = _make_handler()
        result = handler._form_set_provider_timezone(
            {"provider_id": PROVIDER_ID, "timezone": "Bad/Zone"}
        )
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.set_provider_timezone")
    def test_success_resyncs(
        self, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
    ):
        matching = RecurringBlock(id="rb1", provider_id=PROVIDER_ID)
        other = RecurringBlock(id="rb2", provider_id=PROVIDER_ID_2)
        mock_get_rb.return_value = [matching, other]
        handler = _make_handler()
        result = handler._form_set_provider_timezone(
            {"provider_id": PROVIDER_ID, "timezone": "US/Pacific"}
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Provider timezone set to US/Pacific" in data["message"]
        assert "sync-fx" in result
        assert "rb-fx" in result
        assert mock_set.mock_calls == [call(PROVIDER_ID, "US/Pacific")]
        assert mock_rb_sync.mock_calls == [call(matching)]


class TestFormSetProviderTzBulk:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_missing_provider_ids(self, mock_access):
        handler = _make_handler()
        result = handler._form_set_provider_tz_bulk({"timezone": "US/Eastern"})
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_ids required" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_invalid_timezone(self, mock_access):
        handler = _make_handler()
        result = handler._form_set_provider_tz_bulk(
            {"provider_ids": [PROVIDER_ID], "timezone": "Bad"}
        )
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Invalid timezone" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"])
    @patch(f"{MODULE}.get_all_recurring_blocks")
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.set_provider_timezone")
    def test_success(
        self, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
    ):
        matching = RecurringBlock(id="rb1", provider_id=PROVIDER_ID)
        other = RecurringBlock(id="rb2", provider_id="unrelated")
        mock_get_rb.return_value = [matching, other]
        handler = _make_handler()
        result = handler._form_set_provider_tz_bulk(
            {"provider_ids": [PROVIDER_ID, PROVIDER_ID_2], "timezone": "US/Eastern"}
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Timezone set to US/Eastern for 2 providers" in data["message"]
        assert mock_set.mock_calls == [
            call(PROVIDER_ID, "US/Eastern"),
            call(PROVIDER_ID_2, "US/Eastern"),
        ]
        assert mock_rb_sync.mock_calls == [call(matching)]


# ── _dispatch_write routing for provider-timezone form paths ───────────────


class TestDispatchWriteProviderTimezone:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.set_provider_timezone")
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_put_provider_timezone(
        self, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
    ):
        handler = _make_handler()
        result = handler._dispatch_write(
            "PUT", "/provider-timezone", {"provider_id": PROVIDER_ID, "timezone": "US/Pacific"}
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Provider timezone set" in data["message"]
        assert mock_set.mock_calls == [call(PROVIDER_ID, "US/Pacific")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.set_provider_timezone")
    @patch(f"{MODULE}.COMMON_TIMEZONES", ["US/Eastern", "US/Pacific", "UTC"])
    def test_put_provider_timezones_bulk(
        self, mock_set, mock_sync, mock_get_rb, mock_rb_sync, mock_access
    ):
        handler = _make_handler()
        result = handler._dispatch_write(
            "PUT",
            "/provider-timezones/bulk",
            {"provider_ids": [PROVIDER_ID], "timezone": "US/Eastern"},
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Timezone set to US/Eastern for 1 providers" in data["message"]
        assert mock_set.mock_calls == [call(PROVIDER_ID, "US/Eastern")]


# ── _check_write_access: secret-based path ─────────────────────────────────


class TestCheckWriteAccessSecret:
    def test_secret_allows_matching_staff(self):
        request = MagicMock()
        request.staff_id = "staff-42"
        result = _check_write_access(
            request, {"allowed-staff-keys": "staff-1, staff-42 , staff-9"}
        )
        assert result is None

    def test_secret_denies_unlisted_staff(self):
        request = MagicMock()
        request.staff_id = "intruder"
        result = _check_write_access(request, {"allowed-staff-keys": "staff-1,staff-2"})
        assert result is not None
        body, code = _parse(result[0])
        assert code == HTTPStatus.FORBIDDEN
        assert "Access denied" in body["error"]


# ── _form_delete_rule: lead-time + orphan cleanup ──────────────────────────


class TestFormDeleteRule:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_lead_time_block_effects", return_value=["lead-fx"])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider")
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_refreshes_lead_time(
        self, mock_delete, mock_get_rules, mock_sync, mock_lead, mock_access
    ):
        mock_get_rules.return_value = [_lead_time_rule()]
        handler = _make_handler()
        result = handler._form_delete_rule(PROVIDER_ID, "r1")
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Rule deleted"
        assert "lead-fx" in result
        assert mock_delete.mock_calls == [call(PROVIDER_ID, "r1")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_lead_time_block_effects")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_orphan_cleanup(
        self, mock_delete, mock_get_rules, mock_sync, mock_lead, mock_access
    ):
        cal = MagicMock()
        cal.id = "cal-form"
        evt = MagicMock()
        evt.id = "evt-form"
        del_effect = MagicMock()
        event_effect = MagicMock()
        event_effect.delete.return_value = del_effect

        handler = _make_handler()
        with patch(
            "provider_availability.engine.admin_calendar.get_admin_calendars",
            return_value=[cal],
        ), patch("canvas_sdk.v1.data.calendar.Event") as mock_event_model, patch(
            "canvas_sdk.effects.calendar.Event", return_value=event_effect
        ) as mock_event_effect:
            mock_event_model.objects.filter.return_value = [evt]
            result = handler._form_delete_rule(PROVIDER_ID, "r1")

        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert del_effect in result
        assert mock_lead.mock_calls == []
        mock_event_effect.assert_called_once_with(event_id="evt-form")


# ── _form_add_override / _form_remove_override ─────────────────────────────


class TestFormOverrideHelpers:
    def _rule(self) -> ProviderAvailabilityRule:
        return ProviderAvailabilityRule(
            id="rule-1",
            provider_id=PROVIDER_ID,
            weekly_schedule={"thursday": [TimeWindow(start=time(9, 0), end=time(15, 0))]},
            is_active=True,
        )

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_add_override_rule_not_found(self, mock_get, mock_access):
        handler = _make_handler()
        result = handler._form_add_override(
            PROVIDER_ID, "missing", {"date": "2026-04-09", "time_windows": [{"start": "12:00", "end": "17:00"}]}
        )
        data, code = _parse(result[0])
        assert code == HTTPStatus.NOT_FOUND
        assert "Rule not found" in data["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_missing_windows(self, mock_get, mock_access):
        mock_get.return_value = self._rule()
        handler = _make_handler()
        result = handler._form_add_override(PROVIDER_ID, "rule-1", {"date": "2026-04-09"})
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "time window" in data["error"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_bad_window(self, mock_get, mock_access):
        mock_get.return_value = self._rule()
        handler = _make_handler()
        result = handler._form_add_override(
            PROVIDER_ID, "rule-1", {"date": "2026-04-09", "time_windows": [{"start": "17:00", "end": "12:00"}]}
        )
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "start must be before end" in data["error"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_wrong_weekday(self, mock_get, mock_access):
        mock_get.return_value = self._rule()
        handler = _make_handler()
        # 2026-04-06 is a Monday; rule only schedules Thursday
        result = handler._form_add_override(
            PROVIDER_ID, "rule-1", {"date": "2026-04-06", "time_windows": [{"start": "09:00", "end": "12:00"}]}
        )
        data, code = _parse(result[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "monday" in data["error"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_add_override_success(self, mock_get, mock_save, mock_sync, mock_access):
        rule = self._rule()
        mock_get.return_value = rule
        handler = _make_handler()
        result = handler._form_add_override(
            PROVIDER_ID, "rule-1", {"date": "2026-04-09", "time_windows": [{"start": "12:00", "end": "17:00"}]}
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Override saved"
        assert len(rule.date_overrides) == 1
        assert "sync-fx" in result

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_remove_override_rule_not_found(self, mock_get, mock_access):
        handler = _make_handler()
        result = handler._form_remove_override(PROVIDER_ID, "missing", "2026-04-09")
        data, code = _parse(result[0])
        assert code == HTTPStatus.NOT_FOUND

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=["sync-fx"])
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    def test_remove_override_success(self, mock_get, mock_save, mock_sync, mock_access):
        rule = self._rule()
        rule.date_overrides = [
            DateOverride(
                date=date(2026, 4, 9),
                time_windows=[TimeWindow(start=time(9, 0), end=time(12, 0))],
            )
        ]
        mock_get.return_value = rule
        handler = _make_handler()
        result = handler._form_remove_override(PROVIDER_ID, "rule-1", "2026-04-09")
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Override removed"
        assert len(rule.date_overrides) == 0
        assert "sync-fx" in result


# ── _form_create_block / _form_update_block / _form_create_recurring_block ─


class TestFormBlockHelpers:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.build_delete_recurring_block_effects", return_value=["del-rb"])
    @patch(f"{MODULE}.delete_recurring_block")
    @patch(f"{MODULE}.get_recurring_block_by_id")
    @patch(f"{MODULE}.save_block")
    def test_create_block_replaces_recurring(
        self, mock_save, mock_get_rb, mock_del_rb, mock_del_effects, mock_effects, mock_access
    ):
        old_rb = RecurringBlock(id="rb-old", provider_id=PROVIDER_ID)
        mock_get_rb.return_value = old_rb
        handler = _make_handler()
        result = handler._form_create_block(
            {
                "provider_id": PROVIDER_ID,
                "start": "2026-03-10T09:00:00",
                "end": "2026-03-10T12:00:00",
                "replace_recurring_block_id": "rb-old",
            }
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Block created"
        assert "del-rb" in result
        assert mock_del_rb.mock_calls == [call(PROVIDER_ID, "rb-old")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_delete_block_effects", return_value=["del-blk"])
    @patch(f"{MODULE}.get_block_by_id")
    def test_update_block_with_existing_old_block(
        self, mock_get, mock_del_effects, mock_save, mock_effects, mock_access
    ):
        old = AdminBlock(
            id="b1",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 8, 0),
            end=datetime(2026, 3, 10, 11, 0),
        )
        mock_get.return_value = old
        handler = _make_handler()
        result = handler._form_update_block(
            {
                "id": "b1",
                "provider_id": PROVIDER_ID,
                "start": "2026-03-10T09:00:00",
                "end": "2026-03-10T12:00:00",
            }
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Updated 1 block(s)" in data["message"]
        assert "del-blk" in result
        assert mock_del_effects.mock_calls == [call(PROVIDER_ID, old)]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.build_delete_block_effects", return_value=["del-blk"])
    @patch(f"{MODULE}.delete_block")
    @patch(f"{MODULE}.get_block_by_id")
    @patch(f"{MODULE}.save_recurring_block")
    def test_create_recurring_block_replaces_block(
        self, mock_save, mock_get_block, mock_del_block, mock_del_effects, mock_sync, mock_access
    ):
        old_block = AdminBlock(
            id="b-old",
            provider_id=PROVIDER_ID,
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 12, 0),
        )
        mock_get_block.return_value = old_block
        handler = _make_handler()
        result = handler._form_create_recurring_block(
            {
                "provider_id": PROVIDER_ID,
                "weekly_schedule": {"friday": [{"start": "12:00", "end": "13:00"}]},
                "replace_block_id": "b-old",
            }
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert data["message"] == "Recurring block created"
        assert "del-blk" in result
        assert mock_del_block.mock_calls == [call(PROVIDER_ID, "b-old")]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.save_recurring_block")
    @patch(f"{MODULE}.get_recurring_blocks_by_group")
    def test_update_recurring_block_apply_to_group(
        self, mock_group, mock_save, mock_effects, mock_access
    ):
        member = RecurringBlock(
            id="rb2",
            provider_id=PROVIDER_ID_2,
            group_id="g1",
            weekly_schedule={"tuesday": [TimeWindow(start=time(8, 0), end=time(9, 0))]},
        )
        mock_group.return_value = [member]
        handler = _make_handler()
        result = handler._form_update_recurring_block(
            {
                "id": "rb1",
                "provider_id": PROVIDER_ID,
                "group_id": "g1",
                "apply_to_group": True,
                "weekly_schedule": {"monday": [{"start": "09:00", "end": "12:00"}]},
            }
        )
        data, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "Updated 2 recurring block(s)" in data["message"]
        assert len(mock_save.mock_calls) == 2


# ── _build_preloaded_data with data ────────────────────────────────────────


class TestBuildPreloadedDataWithData:
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
