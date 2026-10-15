"""Tests that the dashboard surface is gated while the rest of the plugin is not."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers.application import ApplicationScope

from candid.access import ALLOWED_STAFF_KEYS_SECRET
from candid.api.app import CandidAppAssets
from candid.api.dashboard import CandidDashboardAPI
from candid.applications.candid_dashboard import CandidDashboard

DENIED_MESSAGE = "You are not authorized to access the Candid Dashboard."


def _headers_get(staff_key):
    return lambda k, d=None: staff_key if k == "canvas-logged-in-user-id" else d


# --- CandidDashboard (provider-menu application) ---


def _dashboard_app(staff_key, secrets, user_type="Staff"):
    app = CandidDashboard.__new__(CandidDashboard)
    app.secrets = secrets
    app.event = MagicMock()
    app.event.context = {
        "user": {"id": staff_key, "type": user_type},
        "scope": ApplicationScope.PROVIDER_MENU,
    }
    return app


def _menu_entry(app):
    app.event.type = EventType.APPLICATION__ON_GET
    effects = app.compute()
    assert len(effects) == 1
    assert effects[0].type == EffectType.SHOW_APPLICATION
    return json.loads(effects[0].payload)["data"]


def test_menu_entry_hidden_for_unlisted_staff():
    app = _dashboard_app("staff-9", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    entry = _menu_entry(app)
    assert entry["visible"] is False


def test_menu_entry_shown_at_top_for_allowed_staff():
    app = _dashboard_app("staff-1", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    entry = _menu_entry(app)
    assert entry["visible"] is True
    assert entry["name"] == "Candid Dashboard"
    assert entry["menu_position"] == "top"


def test_menu_entry_shown_when_unconfigured():
    app = _dashboard_app("anyone", {})
    assert _menu_entry(app)["visible"] is True


def _modal_data(effect):
    assert effect.type == EffectType.LAUNCH_MODAL
    return json.loads(effect.payload)["data"]


def test_on_open_shows_denied_page_when_denied():
    app = _dashboard_app("staff-9", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    data = _modal_data(app.on_open())
    assert data["content"] == DENIED_MESSAGE
    assert data["url"] is None


def test_on_open_denied_for_non_staff_user():
    app = _dashboard_app("pat-1", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"}, user_type="Patient")
    data = _modal_data(app.on_open())
    assert data["content"] == DENIED_MESSAGE
    assert data["url"] is None


def test_on_open_launches_dashboard_when_allowed():
    app = _dashboard_app("staff-1", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    data = _modal_data(app.on_open())
    assert data["url"] == "/plugin-io/api/candid/app/dashboard"


def test_on_open_launches_dashboard_when_unconfigured():
    app = _dashboard_app("anyone", {})
    data = _modal_data(app.on_open())
    assert data["url"] == "/plugin-io/api/candid/app/dashboard"


# --- CandidDashboardAPI (aggregated claim data) ---


def _dashboard_api(staff_key, secrets):
    handler = CandidDashboardAPI.__new__(CandidDashboardAPI)
    handler.secrets = secrets
    handler.request = MagicMock()
    handler.request.headers.get.side_effect = _headers_get(staff_key)
    handler.request.query_params.get.side_effect = lambda k, d="": d
    return handler


def test_dashboard_api_forbidden_for_unlisted_staff():
    handler = _dashboard_api("staff-9", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    effects = handler.get()
    assert effects[0].status_code == HTTPStatus.FORBIDDEN
    assert json.loads(effects[0].content)["error"] == "forbidden"


def test_dashboard_api_allows_when_unconfigured():
    handler = _dashboard_api("staff-9", {})
    base_qs = MagicMock()
    base_qs.count.return_value = 0
    base_qs.__getitem__.return_value = []
    with (
        patch("candid.api.dashboard.Claim") as MockClaim,
        patch(
            "candid.api.dashboard._get_filter_options",
            return_value={"statuses": [], "queues": []},
        ),
    ):
        (
            MockClaim.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.distinct.return_value.order_by.return_value
        ) = base_qs
        effects = handler.get()
    assert effects[0].status_code == HTTPStatus.OK
    assert json.loads(effects[0].content)["total"] == 0


# --- CandidAppAssets (static HTML/CSS/JS) ---


def _assets(staff_key, secrets):
    handler = CandidAppAssets.__new__(CandidAppAssets)
    handler.secrets = secrets
    handler.request = MagicMock()
    handler.request.headers.get.side_effect = _headers_get(staff_key)
    handler.request.query_params.get.side_effect = lambda k, d=None: d
    return handler


def test_dashboard_assets_forbidden_for_unlisted_staff():
    handler = _assets("staff-9", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    for effects in (handler.dashboard(), handler.dashboard_css(), handler.dashboard_js()):
        assert effects[0].status_code == HTTPStatus.FORBIDDEN


def test_dashboard_assets_served_when_allowed():
    handler = _assets("staff-1", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    with patch("candid.api.app.render_to_string", return_value="<html></html>"):
        assert handler.dashboard()[0].status_code == HTTPStatus.OK
        assert handler.dashboard_css()[0].status_code == HTTPStatus.OK
        assert handler.dashboard_js()[0].status_code == HTTPStatus.OK


def test_claim_timeline_assets_not_gated_by_dashboard_allowlist():
    # A dashboard-denied staff member can still load the claim-timeline app.
    handler = _assets("staff-9", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    with patch("candid.api.app.render_to_string", return_value="<html></html>"):
        assert handler.claim_timeline()[0].status_code == HTTPStatus.OK
        assert handler.claim_timeline_css()[0].status_code == HTTPStatus.OK
        assert handler.claim_timeline_js()[0].status_code == HTTPStatus.OK
