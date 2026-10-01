"""Tests that the dashboard surface is gated while the rest of the plugin is not."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from candid.access import ALLOWED_STAFF_KEYS_SECRET
from candid.api.app import CandidAppAssets
from candid.api.dashboard import CandidDashboardAPI
from candid.applications.candid_dashboard import CandidDashboard


def _headers_get(staff_key):
    return lambda k, d=None: staff_key if k == "canvas-logged-in-user-id" else d


# --- CandidDashboard.on_open (provider-menu launcher) ---


def _dashboard_app(staff_key, secrets, user_type="Staff"):
    app = CandidDashboard.__new__(CandidDashboard)
    app.secrets = secrets
    app.event = MagicMock()
    app.event.context = {"user": {"id": staff_key, "type": user_type}}
    return app


def test_on_open_returns_no_effect_when_denied():
    app = _dashboard_app("staff-9", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    assert app.on_open() == []


def test_on_open_denied_for_non_staff_user():
    app = _dashboard_app("pat-1", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"}, user_type="Patient")
    assert app.on_open() == []


def test_on_open_launches_modal_when_allowed():
    app = _dashboard_app("staff-1", {ALLOWED_STAFF_KEYS_SECRET: "staff-1"})
    with patch("candid.applications.candid_dashboard.LaunchModalEffect") as MockModal:
        MockModal.return_value.apply.return_value = "effect"
        assert app.on_open() == "effect"


def test_on_open_launches_modal_when_unconfigured():
    app = _dashboard_app("anyone", {})
    with patch("candid.applications.candid_dashboard.LaunchModalEffect") as MockModal:
        MockModal.return_value.apply.return_value = "effect"
        assert app.on_open() == "effect"


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
