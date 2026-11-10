"""Tests for the staff chart API, against real tables and real templates.

These tests cover route behavior, so the per-patient access decision is stubbed
to "allowed" here. The access rules themselves, and the gate's refusals, are
tested against real Staff, Patient and care-team rows in ``test_access.py``.
"""

import datetime as dt
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.common import (
    ContactPointState,
    ContactPointSystem,
    ContactPointUse,
)
from canvas_sdk.v1.data.patient import PatientContactPoint
from pydantic import ValidationError

from oura_ring_viewer.models import OuraOAuthToken
from oura_ring_viewer.protocols.chart_api import OuraChartAPI, _has_messageable_channel
from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.fetch import FetchResult
from oura_ring_viewer.services.normalize import NormalizedDay
from oura_ring_viewer.services.oauth import RefreshFailed, TokensNotFound
from oura_ring_viewer.services.oura_client import OuraAPIError, OuraAuthError
from oura_ring_viewer.services.storage import (
    get_sync_state,
    upsert_sync_state,
    upsert_tokens,
)

PATIENT = "abc123"
SECRETS = {
    "OURA_CLIENT_ID": "cid",
    "OURA_CLIENT_SECRET": "sec",
    "OURA_REDIRECT_URI": "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/callback",
    "OURA_ENVIRONMENT": "sandbox",
    "OURA_MAGIC_LINK_SECRET": "m" * 40,
}
STAFF = "staff-42"
STAFF_HEADERS = {"canvas-logged-in-user-type": "Staff", "canvas-logged-in-user-id": STAFF}


@pytest.fixture(autouse=True)
def _access_granted() -> Any:
    with patch("oura_ring_viewer.protocols.chart_api.staff_can_view", return_value=True) as granted:
        yield granted


class _Request:
    def __init__(self, query: dict[str, str], headers: dict[str, str]) -> None:
        self.query_params = query
        self.headers = headers


class _Event:
    def __init__(self, method: str, path: str) -> None:
        self.context = {"method": method, "path": path}


def _api(
    method: str,
    path: str,
    query: dict[str, str] | None = None,
    *,
    secrets: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> OuraChartAPI:
    handler = OuraChartAPI(event=_Event(method, path))
    handler.request = _Request(
        {"patient_id": PATIENT, **(query or {})}, STAFF_HEADERS if headers is None else headers
    )
    handler.secrets = SECRETS if secrets is None else secrets
    return handler


def _json(effect: Any) -> Any:
    assert isinstance(effect, JSONResponse)
    return json.loads(effect.content)


def _connect() -> None:
    upsert_tokens(
        PATIENT,
        access_token_ciphertext="AT",
        refresh_token_ciphertext="RT",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
        scopes="daily spo2",
        now=dt.datetime.now(dt.UTC),
        is_initial_connection=True,
    )


ROUTES = [
    ("GET", "/", "chart_shell"),
    ("GET", "/data", "chart_data"),
    ("GET", "/status", "status"),
    ("POST", "/send-link", "send_link"),
    ("POST", "/disconnect", "disconnect"),
]


@pytest.mark.parametrize("method, path, name", ROUTES)
@pytest.mark.parametrize("patient_id", ["", "bad id", '"><script>alert(1)</script>'])
def test_every_route_rejects_an_implausible_patient_id(
    method: str, path: str, name: str, patient_id: str
) -> None:
    handler = _api(method, path, {"patient_id": patient_id})
    effects = getattr(handler, name)()
    assert effects[0].status_code == HTTPStatus.BAD_REQUEST
    if name == "chart_shell":
        assert "could not identify the patient" in effects[0].content.decode()
    else:
        assert _json(effects[0]) == {"error": "invalid_patient_id"}


class TestShellAndData:
    def test_shell_renders_the_real_template_bound_to_the_patient(self) -> None:
        effect = _api("GET", "/").chart_shell()[0]
        assert isinstance(effect, HTMLResponse)
        html = effect.content.decode()
        assert 'data-patient-id="abc123"' in html
        assert 'data-api="/plugin-io/api/oura_ring_viewer"' in html
        assert '<script src="/plugin-io/api/oura_ring_viewer/static/chart.js">' in html
        assert "<script>" not in html and "<style>" not in html, "scripts and styles are static files"
        assert 'id="sandbox"' in html

    def test_data_returns_the_view_model(self) -> None:
        body = _json(_api("GET", "/data", {"range": "30d"}).chart_data()[0])
        assert body["connection_status"] == "disconnected"
        assert body["range"] == "30d"
        assert len(body["days"]) == 30

    def test_unknown_range_falls_back_to_the_default(self) -> None:
        body = _json(_api("GET", "/data", {"range": "999"}).chart_data()[0])
        assert body["range"] == "14d"


FETCH = "oura_ring_viewer.protocols.chart_api.fetch_window"


class TestLiveData:
    def test_a_patient_who_is_not_connected_never_reaches_oura(self) -> None:
        upsert_sync_state(PATIENT, link_pending=True)
        with patch(FETCH) as fetch:
            body = _json(_api("GET", "/data").chart_data()[0])
        fetch.assert_not_called()
        assert body["connection_status"] == "link_pending"
        assert body["has_data"] is False

    def test_reports_missing_settings_without_calling_oura(self) -> None:
        _connect()
        with patch(FETCH) as fetch:
            effect = _api("GET", "/data", secrets={"OURA_ENVIRONMENT": "sandbox"}).chart_data()[0]
        fetch.assert_not_called()
        assert effect.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert set(_json(effect)["settings"]) == {
            "OURA_CLIENT_ID", "OURA_CLIENT_SECRET", "OURA_REDIRECT_URI"
        }

    def test_fetches_the_requested_window_and_shapes_it(self) -> None:
        _connect()
        today = dt.datetime.now(dt.UTC).date()
        result = FetchResult(
            rows=[NormalizedDay(day=today, family="activity", payload={"steps": 5_000})],
            forbidden_endpoints=("daily_spo2",),
        )
        with patch(FETCH, return_value=result) as fetch:
            body = _json(_api("GET", "/data", {"range": "7d"}).chart_data()[0])

        kwargs = fetch.call_args.kwargs
        assert kwargs["patient_id"] == PATIENT
        assert (kwargs["start_day"], kwargs["end_day"]) == (today - dt.timedelta(days=6), today)
        assert body["connection_status"] == "connected"
        assert body["latest"]["steps"] == {"value": 5_000, "day": today.isoformat()}
        assert body["forbidden_endpoints"] == ["daily_spo2"]
        assert body["fetch_error"] == ""

    @pytest.mark.parametrize(
        "error, code",
        [
            (RefreshFailed("x"), "reconnect_required"),
            (OuraAuthError("x"), "reconnect_required"),
            (OuraAPIError(429, "slow down"), "rate_limited"),
            (OuraAPIError(500, "down"), "oura_unavailable"),
        ],
    )
    def test_failures_still_return_the_view_model(self, error: Exception, code: str) -> None:
        _connect()
        with patch(FETCH, side_effect=error):
            effect = _api("GET", "/data").chart_data()[0]
        assert effect.status_code == HTTPStatus.OK
        body = _json(effect)
        assert body["fetch_error"] == code
        assert body["has_data"] is False

    def test_reconnect_errors_recorded_by_the_fetch_show_as_expired(self) -> None:
        _connect()

        def fail(**kwargs: Any) -> Any:
            upsert_sync_state(PATIENT, last_error="refresh_failed")
            raise RefreshFailed("x")

        with patch(FETCH, side_effect=fail):
            body = _json(_api("GET", "/data").chart_data()[0])
        assert body["connection_status"] == "expired"

    def test_a_disconnect_mid_request_is_not_an_error(self) -> None:
        _connect()
        with patch(FETCH, side_effect=TokensNotFound("p")):
            body = _json(_api("GET", "/data").chart_data()[0])
        assert body["fetch_error"] == ""

    def test_a_programming_error_is_not_swallowed(self) -> None:
        _connect()
        with patch(FETCH, side_effect=KeyError("x")), pytest.raises(KeyError):
            _api("GET", "/data").chart_data()


class TestSendLink:
    def _send(self, channels: str | None = "", **kwargs: Any) -> list[Any]:
        query = {} if channels is None else {"channels": channels}
        return list(_api("POST", "/send-link", query, **kwargs).send_link())

    def test_copy_only_link_is_signed_stored_and_returned(self) -> None:
        body = _json(self._send()[-1])
        prefix = "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/connect?token="
        assert body["connection_link"].startswith(prefix)
        assert body["expires_in_seconds"] == 72 * 60 * 60
        assert (body["portal_status"], body["portal_error"]) == ("skipped", "not_selected")

        token = body["connection_link"][len(prefix):]
        claims = magic_link.verify_link(token, SECRETS["OURA_MAGIC_LINK_SECRET"])
        state = get_sync_state(PATIENT)
        assert state is not None
        assert claims.patient_id == PATIENT
        assert state.last_link_nonce == claims.nonce
        assert state.link_pending is True

    def test_reuse_resends_the_same_link_without_cancelling_it(self) -> None:
        first = _json(self._send()[-1])
        nonce = get_sync_state(PATIENT).last_link_nonce  # type: ignore[union-attr]
        again = _json(list(_api("POST", "/send-link", {"channels": "", "reuse": "1"}).send_link())[-1])
        assert again["connection_link"] == first["connection_link"]
        assert again["reused"] is True and first["reused"] is False
        assert again["expires_in_seconds"] <= first["expires_in_seconds"]
        assert get_sync_state(PATIENT).last_link_nonce == nonce  # type: ignore[union-attr]

    def test_reuse_with_no_live_link_issues_a_new_one(self) -> None:
        upsert_sync_state(PATIENT, link_pending=True, last_link_nonce="old",
                          last_link_sent_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=4))
        body = _json(list(_api("POST", "/send-link", {"channels": "", "reuse": "1"}).send_link())[-1])
        assert body["reused"] is False
        assert get_sync_state(PATIENT).last_link_nonce != "old"  # type: ignore[union-attr]

    def test_a_new_link_replaces_the_previous_nonce(self) -> None:
        self._send()
        first = get_sync_state(PATIENT)
        self._send()
        second = get_sync_state(PATIENT)
        assert first is not None and second is not None
        assert first.last_link_nonce != second.last_link_nonce

    @pytest.mark.parametrize(
        "override, expected",
        [
            ({"OURA_MAGIC_LINK_SECRET": "short"}, "OURA_MAGIC_LINK_SECRET (shorter than 32 characters)"),
            ({"OURA_REDIRECT_URI": "http://acme.example/cb"}, "OURA_REDIRECT_URI (must be an absolute https URL)"),
        ],
    )
    def test_unsafe_configuration_issues_no_link(self, override: dict[str, str], expected: str) -> None:
        effects = self._send(secrets={**SECRETS, **override})
        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert _json(effects[0])["settings"] == [expected]
        assert get_sync_state(PATIENT) is None

    def test_portal_is_the_default_channel(self) -> None:
        body = _json(self._send(channels=None)[-1])
        assert body["portal_error"] != "not_selected"

    def test_portal_is_skipped_when_the_patient_cannot_be_messaged(self) -> None:
        body = _json(self._send(channels="portal")[-1])
        assert (body["portal_status"], body["portal_error"]) == ("skipped", "no_messageable_channel")

    def test_portal_message_effect_is_emitted_before_the_response(self) -> None:
        sentinel = MagicMock(name="message_effect")
        with (
            patch("oura_ring_viewer.protocols.chart_api._has_messageable_channel", return_value=True),
            patch("oura_ring_viewer.protocols.chart_api.Message") as message,
        ):
            message.return_value.create_and_send.return_value = sentinel
            effects = self._send(channels="portal")

        assert effects[0] is sentinel
        kwargs = message.call_args.kwargs
        assert (kwargs["sender_id"], kwargs["recipient_id"]) == (STAFF, PATIENT)
        assert _json(effects[-1])["connection_link"] in kwargs["content"]
        assert "\u2014" not in kwargs["content"]  # no em dashes in patient-facing copy
        assert _json(effects[-1])["portal_status"] == "sent"

    def test_a_rejected_portal_message_still_returns_the_link(self) -> None:
        with (
            patch("oura_ring_viewer.protocols.chart_api._has_messageable_channel", return_value=True),
            patch("oura_ring_viewer.protocols.chart_api.Message") as message,
        ):
            message.return_value.create_and_send.side_effect = ValidationError.from_exception_data(
                "Message", []
            )
            effects = self._send(channels="portal")
        body = _json(effects[-1])
        assert len(effects) == 1
        assert (body["portal_status"], body["portal_error"]) == ("failed", "invalid_sender_or_recipient")
        assert body["connection_link"]


class TestMessageableChannel:
    """Runs the contact-point query against real Patient rows, so the field
    names and enum values it depends on are checked against the SDK schema."""

    def _patient_with(self, **contact: Any) -> str:
        patient = PatientFactory.create()
        fields: dict[str, Any] = {
            "system": ContactPointSystem.EMAIL.value,
            "value": "pat@example.com",
            "use": ContactPointUse.HOME.value,
            "use_notes": "",
            "rank": 1,
            "state": ContactPointState.ACTIVE.value,
            "has_consent": True,
            "opted_out": False,
            "verification_token": "",
        }
        fields.update(contact)
        PatientContactPoint.objects.create(patient=patient, **fields)
        return str(patient.id)

    def test_consenting_active_email(self) -> None:
        assert _has_messageable_channel(self._patient_with()) is True

    def test_consenting_active_phone(self) -> None:
        patient_id = self._patient_with(system=ContactPointSystem.PHONE.value, value="5555550100")
        assert _has_messageable_channel(patient_id) is True

    @pytest.mark.parametrize(
        "contact",
        [
            {"has_consent": False},
            {"opted_out": True},
            {"state": ContactPointState.DELETED.value},
            {"system": ContactPointSystem.FAX.value},
        ],
    )
    def test_unusable_contact_points(self, contact: dict[str, Any]) -> None:
        assert _has_messageable_channel(self._patient_with(**contact)) is False

    def test_unknown_patient(self) -> None:
        assert _has_messageable_channel("no-such-patient") is False


def test_disconnect_removes_tokens_and_status() -> None:
    _connect()
    upsert_sync_state(PATIENT, last_synced_at=dt.datetime.now(dt.UTC))
    with patch("oura_ring_viewer.services.disconnect.build_client"):
        body = _json(_api("POST", "/disconnect").disconnect()[0])
    assert body == {"disconnected": True, "revoked_at_oura": True}
    assert not OuraOAuthToken.objects.filter(patient__id=PATIENT).exists()
    assert get_sync_state(PATIENT) is None


class TestStatusRoute:
    def test_reports_status_without_calling_oura(self) -> None:
        _connect()
        with patch("oura_ring_viewer.protocols.chart_api.fetch_window") as fetch:
            body = _json(_api("GET", "/status").status()[0])
        fetch.assert_not_called()
        assert body == {"connection_status": "connected"}

    def test_a_patient_who_stopped_sharing(self) -> None:
        assert _json(_api("GET", "/status").status()[0]) == {"connection_status": "disconnected"}
