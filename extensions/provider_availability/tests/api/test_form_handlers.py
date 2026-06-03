"""Tests for form-action dispatch and admin UI endpoints in availability_api."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from provider_availability.api.availability_api import AvailabilityAPI
from provider_availability.engine.models import (
    AdminBlock,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
)

MODULE = "provider_availability.api.availability_api"
PROVIDER_ID = "provider-uuid-123"


def _parse(response) -> tuple[dict, int]:
    body = json.loads(getattr(response, "content"))
    return body, response.status_code


def _make_handler(
    json_body: dict | None = None,
    staff_id: str = "staff-1",
) -> AvailabilityAPI:
    handler = AvailabilityAPI(MagicMock())
    handler.request = MagicMock()
    handler.request.query_params = {}
    handler.request.path_params = {}
    handler.request.json.return_value = json_body or {}
    handler.request.staff_id = staff_id
    handler.secrets = {}
    return handler


def _make_form_handler(method: str, path: str, body: dict) -> AvailabilityAPI:
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


# ── _do_dispatch routing ──────────────────────────────────────────────


class TestDoDispatch:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value="")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    def test_post_rules(self, mock_sync, mock_overlap, mock_save, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
        }
        result = handler._do_dispatch("POST", "rules", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "saved" in msg["message"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value="")
    @patch(f"{MODULE}.get_rules_by_group", return_value=[])
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_put_rules(self, mock_get_rule, mock_get_rules, mock_sync, mock_grp, mock_overlap, mock_save, mock_access):
        handler = _make_handler()
        body = {"id": "rule-1", "provider_id": PROVIDER_ID, "weekly_schedule": {}}
        result = handler._do_dispatch("PUT", "rules", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.delete_rule_by_id")
    def test_delete_rule(self, mock_del, mock_get_rules, mock_sync, mock_access):
        handler = _make_handler()
        result = handler._do_dispatch("DELETE", f"rules/{PROVIDER_ID}/rule-1", {})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "deleted" in msg["message"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_delete_effects", return_value=[])
    @patch(f"{MODULE}.delete_rules_for_provider", return_value=3)
    def test_delete_provider_rules(self, mock_del, mock_fx, mock_access):
        handler = _make_handler()
        result = handler._do_dispatch("DELETE", f"rules/{PROVIDER_ID}", {})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "3" in msg["message"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    def test_post_blocks(self, mock_fx, mock_save, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T17:00:00",
        }
        result = handler._do_dispatch("POST", "blocks", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "created" in msg["message"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_block_by_id", return_value=None)
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    def test_put_blocks(self, mock_fx, mock_save, mock_get, mock_access):
        handler = _make_handler()
        body = {
            "id": "block-1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T17:00:00",
        }
        result = handler._do_dispatch("PUT", "blocks", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_blocks_for_provider", return_value=[])
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.delete_block")
    def test_delete_block(self, mock_del, mock_fx, mock_get, mock_access):
        handler = _make_handler()
        result = handler._do_dispatch("DELETE", f"blocks/{PROVIDER_ID}/block-1", {})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_recurring_block")
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    def test_post_recurring_blocks(self, mock_fx, mock_save, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
        }
        result = handler._do_dispatch("POST", "recurring-blocks", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "created" in msg["message"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_recurring_block")
    @patch(f"{MODULE}.get_recurring_blocks_by_group", return_value=[])
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    def test_put_recurring_blocks(self, mock_fx, mock_grp, mock_save, mock_access):
        handler = _make_handler()
        body = {
            "id": "rb-1",
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
        }
        result = handler._do_dispatch("PUT", "recurring-blocks", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_recurring_block_by_id", return_value=None)
    @patch(f"{MODULE}.build_delete_recurring_block_effects", return_value=[])
    @patch(f"{MODULE}.delete_recurring_block")
    def test_delete_recurring_block(self, mock_del, mock_fx, mock_get, mock_access):
        handler = _make_handler()
        result = handler._do_dispatch("DELETE", f"recurring-blocks/{PROVIDER_ID}/rb-1", {})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.set_practice_timezone")
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    def test_put_timezone(self, mock_rbs, mock_rules, mock_set, mock_access):
        handler = _make_handler()
        result = handler._do_dispatch("PUT", "timezone", {"timezone": "US/Eastern"})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        mock_set.assert_called_once_with("US/Eastern")

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    def test_post_override(self, mock_sync, mock_get, mock_save, mock_access):
        rule = ProviderAvailabilityRule.from_dict({
            "id": "rule-1", "provider_id": PROVIDER_ID,
            "weekly_schedule": {"thursday": [{"start": "09:00", "end": "15:00"}]},
        })
        mock_get.return_value = rule
        handler = _make_handler()
        body = {"date": "2026-04-09", "time_windows": [{"start": "12:00", "end": "17:00"}]}
        result = handler._do_dispatch("POST", f"rules/{PROVIDER_ID}/rule-1/overrides", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "saved" in msg["message"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.get_rule_by_id")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    def test_delete_override(self, mock_sync, mock_get, mock_save, mock_access):
        rule = ProviderAvailabilityRule.from_dict({
            "id": "rule-1", "provider_id": PROVIDER_ID,
            "weekly_schedule": {"thursday": [{"start": "09:00", "end": "15:00"}]},
            "date_overrides": [{"date": "2026-04-09", "time_windows": [{"start": "09:00", "end": "12:00"}]}],
        })
        mock_get.return_value = rule
        handler = _make_handler()
        result = handler._do_dispatch("DELETE", f"rules/{PROVIDER_ID}/rule-1/overrides/2026-04-09", {})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        assert "removed" in msg["message"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_rule_by_id")
    def test_post_override_wrong_weekday(self, mock_get, mock_access):
        rule = ProviderAvailabilityRule.from_dict({
            "id": "rule-1", "provider_id": PROVIDER_ID,
            "weekly_schedule": {"thursday": [{"start": "09:00", "end": "15:00"}]},
        })
        mock_get.return_value = rule
        handler = _make_handler()
        # 2026-04-06 is a Monday — rule only has Thursday
        body = {"date": "2026-04-06", "time_windows": [{"start": "09:00", "end": "12:00"}]}
        result = handler._do_dispatch("POST", f"rules/{PROVIDER_ID}/rule-1/overrides", body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST
        assert "monday" in msg["error"].lower()

    def test_unknown_route_returns_400(self):
        handler = _make_handler()
        result = handler._do_dispatch("POST", "nonexistent", {})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST
        assert "unknown" in msg["error"].lower()


# ── Validation ────────────────────────────────────────────────────────


class TestFormValidation:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_rule_missing_provider(self, mock_access):
        handler = _make_handler()
        result = handler._form_create_rule({})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST
        assert "provider_id" in msg["error"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_rule_invalid_time_window(self, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "17:00", "end": "09:00"}]},
        }
        result = handler._form_create_rule(body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST
        assert "invalid" in msg["error"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value="Overlaps with existing rule")
    def test_create_rule_overlap_rejected(self, mock_overlap, mock_save, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
        }
        result = handler._form_create_rule(body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST
        assert "overlap" in msg["error"].lower()
        mock_save.assert_not_called()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_block_missing_fields(self, mock_access):
        handler = _make_handler()
        result = handler._form_create_block({"provider_id": PROVIDER_ID})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_block_start_after_end(self, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T17:00:00",
            "end": "2026-03-10T09:00:00",
        }
        result = handler._form_create_block(body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST
        assert "before" in msg["error"].lower()

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_update_block_missing_fields(self, mock_access):
        handler = _make_handler()
        result = handler._form_update_block({"id": "b-1"})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_update_block_start_after_end(self, mock_access):
        handler = _make_handler()
        body = {
            "id": "b-1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T17:00:00",
            "end": "2026-03-10T09:00:00",
        }
        result = handler._form_update_block(body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_update_rule_missing_id(self, mock_access):
        handler = _make_handler()
        result = handler._form_update_rule({"provider_id": PROVIDER_ID})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_recurring_block_missing_provider(self, mock_access):
        handler = _make_handler()
        result = handler._form_create_recurring_block({})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_recurring_block_missing_schedule(self, mock_access):
        handler = _make_handler()
        result = handler._form_create_recurring_block({"provider_id": PROVIDER_ID})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_create_recurring_block_invalid_time(self, mock_access):
        handler = _make_handler()
        body = {
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"monday": [{"start": "17:00", "end": "09:00"}]},
        }
        result = handler._form_create_recurring_block(body)
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_update_recurring_block_missing_fields(self, mock_access):
        handler = _make_handler()
        result = handler._form_update_recurring_block({"id": "rb-1"})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_update_recurring_block_missing_schedule(self, mock_access):
        handler = _make_handler()
        result = handler._form_update_recurring_block({
            "id": "rb-1", "provider_id": PROVIDER_ID,
        })
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_set_timezone_invalid(self, mock_access):
        handler = _make_handler()
        result = handler._form_set_timezone({"timezone": "Fake/Zone"})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_set_timezone_empty(self, mock_access):
        handler = _make_handler()
        result = handler._form_set_timezone({"timezone": ""})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.BAD_REQUEST


# ── Group operations ──────────────────────────────────────────────────


class TestGroupOperations:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_rule")
    @patch(f"{MODULE}.check_rule_overlap", return_value="")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.get_rules_for_provider", return_value=[])
    @patch(f"{MODULE}.get_rules_by_group")
    @patch(f"{MODULE}.get_rule_by_id", return_value=None)
    def test_update_rule_applies_to_group(self, mock_get_rule, mock_grp, mock_get_rules, mock_sync, mock_overlap, mock_save, mock_access):
        other_rule = ProviderAvailabilityRule.from_dict({
            "id": "rule-2",
            "provider_id": "provider-2",
            "weekly_schedule": {},
        })
        mock_grp.return_value = [other_rule]

        handler = _make_handler()
        body = {
            "id": "rule-1",
            "provider_id": PROVIDER_ID,
            "group_id": "grp-1",
            "apply_to_group": True,
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
        }
        result = handler._form_update_rule(body)
        msg, _ = _parse(result[-1])
        assert "2" in msg["message"]  # Updated 2 rule(s)
        assert mock_save.call_count == 2

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_block")
    @patch(f"{MODULE}.get_block_by_id", return_value=None)
    @patch(f"{MODULE}.build_block_event_effects", return_value=[])
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_blocks_by_group")
    def test_update_block_applies_to_group(self, mock_grp, mock_del_fx, mock_fx, mock_get, mock_save, mock_access):
        other_block = AdminBlock(
            id="block-2",
            provider_id="provider-2",
            start=datetime(2026, 3, 10, 9, 0),
            end=datetime(2026, 3, 10, 17, 0),
            group_id="grp-1",
        )
        mock_grp.return_value = [other_block]

        handler = _make_handler()
        body = {
            "id": "block-1",
            "provider_id": PROVIDER_ID,
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T16:00:00",
            "group_id": "grp-1",
            "apply_to_group": True,
        }
        result = handler._form_update_block(body)
        msg, _ = _parse(result[-1])
        assert "2" in msg["message"]

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.save_recurring_block")
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.get_recurring_blocks_by_group")
    def test_update_recurring_block_applies_to_group(self, mock_grp, mock_fx, mock_save, mock_access):
        other_rb = RecurringBlock.from_dict({
            "id": "rb-2",
            "provider_id": "provider-2",
            "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]},
            "group_id": "grp-1",
        })
        mock_grp.return_value = [other_rb]

        handler = _make_handler()
        body = {
            "id": "rb-1",
            "provider_id": PROVIDER_ID,
            "weekly_schedule": {"tuesday": [{"start": "10:00", "end": "15:00"}]},
            "group_id": "grp-1",
            "apply_to_group": True,
        }
        result = handler._form_update_recurring_block(body)
        msg, _ = _parse(result[-1])
        assert "2" in msg["message"]


# ── handle_form_action ────────────────────────────────────────────────


class TestHandleFormAction:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.set_practice_timezone")
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_active_providers", return_value=[])
    @patch(f"{MODULE}.get_active_locations", return_value=[])
    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.render_admin_page", return_value="<html></html>")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    def test_form_action_success_returns_html(self, mock_ptzs, mock_render, mock_tz, mock_blocks, mock_vt, mock_loc, mock_prov, mock_rbs, mock_rules, mock_set, mock_access):
        handler = _make_form_handler("PUT", "timezone", {"timezone": "US/Eastern"})
        result = handler.handle_form_action()
        # Last response should be HTML
        last = result[-1]
        assert last.status_code == HTTPStatus.OK

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.get_active_providers", return_value=[])
    @patch(f"{MODULE}.get_active_locations", return_value=[])
    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[])
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.render_admin_page", return_value="<html></html>")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    def test_form_action_bad_json_body(self, mock_ptzs, mock_render, mock_tz, mock_rbs, mock_blocks, mock_rules, mock_vt, mock_loc, mock_prov, mock_access):
        handler = _make_handler()
        field_method = MagicMock()
        field_method.value = "POST"
        field_path = MagicMock()
        field_path.value = "nonexistent"
        field_body = MagicMock()
        field_body.value = "not-json{{"
        handler.request.form_data.return_value = {
            "_method": field_method,
            "_path": field_path,
            "_body": field_body,
        }
        result = handler.handle_form_action()
        assert result[-1].status_code == HTTPStatus.OK  # Returns admin page regardless


# ── _dispatch_write error handling ────────────────────────────────────


class TestDispatchWriteError:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    def test_dispatch_catches_exception(self, mock_access):
        handler = _make_handler()
        with patch.object(handler, "_do_dispatch", side_effect=RuntimeError("boom")):
            result = handler._dispatch_write("POST", "rules", {})
            msg, code = _parse(result[-1])
            assert code == HTTPStatus.INTERNAL_SERVER_ERROR
            assert "error" in msg


# ── Admin UI endpoints ────────────────────────────────────────────────


class TestAdminUI:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.render_admin_page", return_value="<html>admin</html>")
    @patch(f"{MODULE}.get_active_providers", return_value=[])
    @patch(f"{MODULE}.get_active_locations", return_value=[])
    @patch(f"{MODULE}.get_scheduleable_visit_types", return_value=[])
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    def test_get_admin_ui_success(self, mock_ptzs, mock_tz, mock_rbs, mock_blocks, mock_rules, mock_vt, mock_loc, mock_prov, mock_render, mock_access):
        handler = _make_handler()
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.OK
        mock_render.assert_called_once()

    @patch(f"{MODULE}._check_write_access")
    def test_get_admin_ui_access_denied(self, mock_access):
        from canvas_sdk.effects.simple_api import JSONResponse

        mock_access.return_value = [JSONResponse({"error": "Denied"}, status_code=HTTPStatus.FORBIDDEN)]
        handler = _make_handler()
        result = handler.get_admin_ui()
        assert result[0].status_code == HTTPStatus.FORBIDDEN

    @patch(f"{MODULE}.get_active_providers", side_effect=Exception("db error"))
    @patch(f"{MODULE}.get_active_locations", side_effect=Exception("db error"))
    @patch(f"{MODULE}.get_scheduleable_visit_types", side_effect=Exception("db error"))
    @patch(f"{MODULE}.get_all_rules", return_value=[])
    @patch(f"{MODULE}.get_all_blocks", return_value=[])
    @patch(f"{MODULE}.get_all_recurring_blocks", return_value=[])
    @patch(f"{MODULE}.get_practice_timezone", return_value="US/Eastern")
    @patch(f"{MODULE}.get_all_provider_timezones", return_value={})
    def test_build_preloaded_data_handles_errors(self, mock_ptzs, mock_tz, mock_rbs, mock_blocks, mock_rules, mock_vt, mock_loc, mock_prov):
        handler = _make_handler()
        data = handler._build_preloaded_data()
        assert data["providers"]["providers"] == []
        assert data["locations"]["locations"] == []
        assert data["visit_types"]["visit_types"] == []



# ── Static asset endpoints ────────────────────────────────────────────


class TestStaticAssets:
    @patch(f"{MODULE}.render_to_string", return_value="body { color: red; }")
    def test_get_admin_css(self, mock_render):
        handler = _make_handler()
        result = handler.get_admin_css()
        assert result[0].status_code == HTTPStatus.OK
        mock_render.assert_called_once_with("static/css/admin.css")

    @patch(f"{MODULE}.render_to_string", return_value="console.log('hi');")
    def test_get_admin_js(self, mock_render):
        handler = _make_handler()
        result = handler.get_admin_js()
        assert result[0].status_code == HTTPStatus.OK
        mock_render.assert_called_once_with("static/js/admin.js")


# ── Timezone sync with rules/blocks ───────────────────────────────────


class TestTimezoneSync:
    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.set_practice_timezone")
    @patch(f"{MODULE}.sync_provider_availability", return_value=[])
    @patch(f"{MODULE}.build_recurring_block_sync_effects", return_value=[])
    @patch(f"{MODULE}.get_all_rules")
    @patch(f"{MODULE}.get_all_recurring_blocks")
    def test_set_timezone_syncs_all_providers(self, mock_rbs, mock_rules, mock_rb_sync, mock_sync, mock_set, mock_access):
        rule1 = ProviderAvailabilityRule.from_dict({"provider_id": "p1", "weekly_schedule": {}})
        rule2 = ProviderAvailabilityRule.from_dict({"provider_id": "p2", "weekly_schedule": {}})
        rb1 = RecurringBlock.from_dict({"provider_id": "p1", "weekly_schedule": {"monday": [{"start": "09:00", "end": "17:00"}]}})
        mock_rules.return_value = [rule1, rule2]
        mock_rbs.return_value = [rb1]

        handler = _make_handler()
        result = handler._form_set_timezone({"timezone": "US/Eastern"})
        msg, code = _parse(result[-1])
        assert code == HTTPStatus.OK
        # Should sync each unique provider once
        assert mock_sync.call_count == 2
        mock_rb_sync.assert_called_once()
