"""Tests for form-action dispatch and admin UI endpoints in availability_api."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

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
    json_body: dict | None = None,
    staff_id: str = "staff-1",
) -> AvailabilityAPI:
    handler = AvailabilityAPI(MagicMock())
    handler.request = MagicMock()
    handler.request.query_params = {}
    handler.request.path_params = {}
    handler.request.json.return_value = json_body or {}
    handler.request.headers = _session_headers(staff_id)
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


_ROUTES = [
    ("POST", "rules", "create_or_update_rule", {}),
    ("PUT", "rules", "update_rule_group", {}),
    ("DELETE", "rules/p1/r1", "delete_rule", {"provider_id": "p1", "rule_id": "r1"}),
    ("DELETE", "rules/p1", "delete_provider_rules", {"provider_id": "p1"}),
    ("POST", "rules/p1/r1/overrides", "add_override", {"provider_id": "p1", "rule_id": "r1"}),
    ("DELETE", "rules/p1/r1/overrides/2026-05-01", "remove_override",
     {"provider_id": "p1", "rule_id": "r1", "override_date": "2026-05-01"}),
    ("POST", "blocks", "create_block", {}),
    ("PUT", "blocks", "update_block", {}),
    ("DELETE", "blocks/p1/b1", "delete_block_endpoint", {"provider_id": "p1", "block_id": "b1"}),
    ("POST", "recurring-blocks", "create_recurring_block", {}),
    ("PUT", "recurring-blocks", "update_recurring_block", {}),
    ("DELETE", "recurring-blocks/p1/rb1", "delete_recurring_block_endpoint", {"provider_id": "p1", "block_id": "rb1"}),
    ("PUT", "timezone", "set_timezone", {}),
    ("PUT", "provider-timezone", "set_provider_tz", {}),
    ("DELETE", "provider-timezone/p1", "clear_provider_tz", {"provider_id": "p1"}),
    ("PUT", "provider-timezones/bulk", "set_provider_tz_bulk", {}),
    ("PUT", "roles", "set_roles", {}),
    ("PUT", "my-view", "save_saved_view", {}),
    ("POST", "expired/remove", "remove_expired_items", {}),
    ("POST", "expired/snooze", "snooze_expired_items", {}),
]


class TestDoDispatch:
    """The backup form path runs the same route the page's fetch() would, with the form's body and path."""

    @pytest.mark.parametrize("method,path,route,params", _ROUTES)
    def test_routes_to_the_api_handler(self, method, path, route, params):
        handler = _make_handler()
        original = handler.request
        seen = {}

        def fake_route():
            seen["body"] = handler.request.json()
            seen["params"] = handler.request.path_params
            seen["headers"] = handler.request.headers
            return ["done"]

        with patch.object(AvailabilityAPI, route, lambda self: fake_route()):
            result = handler._do_dispatch(method, "/" + path, {"x": 1})

        assert result == ["done"]
        assert seen == {"body": {"x": 1}, "params": params, "headers": original.headers}
        # The real request is back once the route returns.
        assert handler.request is original

    def test_request_is_restored_when_the_route_raises(self):
        handler = _make_handler()
        original = handler.request

        def boom(self):
            raise ValueError("bad")

        with patch.object(AvailabilityAPI, "create_block", boom), pytest.raises(ValueError):
            handler._do_dispatch("POST", "blocks", {})
        assert handler.request is original

    def test_unknown_path(self):
        handler = _make_handler()
        msg, code = _parse(handler._do_dispatch("POST", "nope", {})[0])
        assert code == HTTPStatus.BAD_REQUEST
        assert "Unknown: POST /nope" in msg["error"]

    def test_method_must_match(self):
        handler = _make_handler()
        msg, code = _parse(handler._do_dispatch("GET", "blocks", {})[0])
        assert code == HTTPStatus.BAD_REQUEST

    @patch(f"{MODULE}._check_write_access", return_value=None)
    @patch(f"{MODULE}.build_delete_block_effects", return_value=[])
    @patch(f"{MODULE}.get_blocks_by_group", return_value=[])
    @patch(f"{MODULE}.get_blocks_for_provider")
    @patch(f"{MODULE}.delete_block")
    def test_real_route_reads_path_and_query(self, mock_delete, mock_blocks, mock_group, mock_build, mock_access):
        """End to end through an unpatched route: the swapped request carries the ids and the query."""
        mock_blocks.return_value = [AdminBlock(id="b1", provider_id="p1", group_id="g1",
                                               start=datetime(2026, 7, 4, 9, tzinfo=UTC), end=datetime(2026, 7, 4, 10, tzinfo=UTC))]
        handler = _make_handler()
        handler._do_dispatch("DELETE", "blocks/p1/b1?apply_to_group=true", {})
        assert mock_delete.mock_calls == [call("p1", "b1")]
        assert mock_group.mock_calls == [call("g1")]


# ── handle_form_action ────────────────────────────────────────────────


class TestHandleFormAction:
    @pytest.fixture(autouse=True)
    def _no_saved_view(self):
        """The saved view reads the plugin cache, which tests have no context for."""
        with patch(f"{MODULE}.get_my_view", return_value=[]):
            yield

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
    @pytest.fixture(autouse=True)
    def _no_saved_view(self):
        """The saved view reads the plugin cache, which tests have no context for."""
        with patch(f"{MODULE}.get_my_view", return_value=[]):
            yield

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


