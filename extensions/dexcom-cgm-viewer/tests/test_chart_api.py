"""Staff-authenticated SimpleAPI for the chart drawer."""

from __future__ import annotations

import datetime as dt
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.handlers.simple_api.security import SessionCredentials
from dexcom_cgm_viewer.services import storage
from dexcom_cgm_viewer.protocols.chart_api import (
    DexcomChartAPI,
    _build_connect_url,
    _build_client,
    _missing_secrets,
)


PATIENT = "patient-api-1"


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)


def _full_secrets() -> dict[str, str]:
    return {
        "DEXCOM_CLIENT_ID": "cid",
        "DEXCOM_CLIENT_SECRET": "csec",
        "DEXCOM_REDIRECT_URI": "https://canvas.example.com/plugin-io/api/dexcom_cgm_viewer/callback",
        "DEXCOM_ENVIRONMENT": "sandbox",
        "DEXCOM_MAGIC_LINK_SECRET": "magic-secret-of-sufficient-length-padding",
    }


class DummyRequest:
    """Minimal SimpleAPI Request stand-in."""

    def __init__(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.query_params = query_params or {}
        self.headers = headers or {}
        self._body = body

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


class DummyEvent:
    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self.context = context or {"method": "GET", "path": "/"}


def _make_api(
    method: str,
    path: str,
    *,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    secrets: dict[str, str] | None = None,
) -> DexcomChartAPI:
    api = DexcomChartAPI(event=DummyEvent(context={"method": method, "path": path}))
    api.request = DummyRequest(query_params=query_params, headers=headers, body=body)
    api.secrets = secrets if secrets is not None else _full_secrets()
    return api


def _json_body(effects: list[Any]) -> dict[str, Any]:
    for effect in effects:
        if isinstance(effect, JSONResponse):
            content = effect.content
            if isinstance(content, bytes):
                return dict(json.loads(content.decode("utf-8")))
            if isinstance(content, str):
                return dict(json.loads(content))
            if isinstance(content, dict):
                return dict(content)
    raise AssertionError("no JSONResponse in effects")


# ---- auth: StaffSessionAuthMixin --------------------------------------------


def test_authenticate_rejects_patient_session() -> None:
    api = _make_api("GET", "/")
    creds = MagicMock(spec=SessionCredentials)
    creds.logged_in_user = {"id": "x", "type": "Patient"}
    with pytest.raises(InvalidCredentialsError):
        api.authenticate(creds)


def test_authenticate_accepts_staff_session() -> None:
    api = _make_api("GET", "/")
    creds = MagicMock(spec=SessionCredentials)
    creds.logged_in_user = {"id": "x", "type": "Staff"}
    assert api.authenticate(creds) is True


# ---- shell ------------------------------------------------------------------


def test_shell_requires_patient_id() -> None:
    api = _make_api("GET", "/", query_params={})
    body = _json_body(api.shell())
    assert body == {"error": "patient_id query parameter is required"}


def test_shell_renders_html_with_patient_id() -> None:
    api = _make_api("GET", "/", query_params={"patient_id": PATIENT})
    with patch(
        "dexcom_cgm_viewer.protocols.chart_api.render_to_string",
        return_value=f"<html>{PATIENT}</html>",
    ) as mock_render:
        effects = api.shell()
    assert isinstance(effects[0], HTMLResponse)
    assert PATIENT.encode("utf-8") in effects[0].content
    mock_render.assert_called_once_with(
        "templates/chart.html",
        context={"patient_id": PATIENT},
    )


# ---- /data ------------------------------------------------------------------


def test_data_requires_patient_id() -> None:
    api = _make_api("GET", "/data", query_params={})
    body = _json_body(api.get_data())
    assert "patient_id" in body["error"]


def test_data_returns_payload_for_disconnected_patient() -> None:
    api = _make_api("GET", "/data", query_params={"patient_id": PATIENT, "range": "14d"})
    body = _json_body(api.get_data())
    assert body["connection_status"] == "disconnected"
    assert body["range"] == "14d"
    assert body["egvs"] == []


def test_data_propagates_unexpected_errors_for_observability() -> None:
    """Per REVIEW.md §3: build_payload only does local DB reads + pure-Python
    aggregation. Any failure is a programmer bug and must surface to the
    plugin runtime (which renders a 500), not be swallowed by the handler."""
    api = _make_api("GET", "/data", query_params={"patient_id": PATIENT})
    with patch("dexcom_cgm_viewer.protocols.chart_api.build_payload",
               side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            api.get_data()


# ---- /sync ------------------------------------------------------------------


def test_sync_requires_patient_id() -> None:
    api = _make_api("POST", "/sync", query_params={})
    body = _json_body(api.sync_now())
    assert "patient_id" in body["error"]


def test_sync_returns_503_when_secrets_missing() -> None:
    api = _make_api("POST", "/sync", query_params={"patient_id": PATIENT}, secrets={})
    effects = api.sync_now()
    body = _json_body(effects)
    assert effects[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert "missing plugin secrets" in body["error"]


def test_sync_returns_409_when_patient_not_connected() -> None:
    api = _make_api("POST", "/sync", query_params={"patient_id": PATIENT, "range": "7d"})
    effects = api.sync_now()
    body = _json_body(effects)
    assert effects[0].status_code == HTTPStatus.CONFLICT
    assert "not connected" in body["error"]


def test_sync_returns_200_on_success() -> None:
    api = _make_api("POST", "/sync", query_params={"patient_id": PATIENT, "range": "7d"})
    storage.upsert_tokens(
        PATIENT, access_token_ciphertext="x", refresh_token_ciphertext="y",
        expires_at=_now(), dexcom_user_id="DEX",
        now=_now(), is_initial_connection=True,
    )
    fake_result = MagicMock(
        egvs_persisted=3, egvs_purged=1, summaries_written=1,
        last_egv_system_time=_now(),
    )
    with patch("dexcom_cgm_viewer.protocols.chart_api.sync_patient",
               return_value=fake_result):
        body = _json_body(api.sync_now())
    assert body["egvs_persisted"] == 3


def test_sync_returns_502_on_dexcom_outage() -> None:
    """A Dexcom-side failure (DexcomAPIError) is the expected 502 path."""
    from dexcom_cgm_viewer.services.dexcom_client import DexcomAPIError
    api = _make_api("POST", "/sync", query_params={"patient_id": PATIENT, "range": "7d"})
    storage.upsert_tokens(
        PATIENT, access_token_ciphertext="x", refresh_token_ciphertext="y",
        expires_at=_now(), dexcom_user_id="DEX",
        now=_now(), is_initial_connection=True,
    )
    with patch("dexcom_cgm_viewer.protocols.chart_api.sync_patient",
               side_effect=DexcomAPIError(503, "dexcom down")):
        effects = api.sync_now()
    assert effects[0].status_code == HTTPStatus.BAD_GATEWAY
    # The sync-state row records the error so the UI can surface it.
    state = storage.get_sync_state(PATIENT)
    assert state is not None and state.last_error == "sync_failed"


def test_sync_returns_502_on_refresh_failure() -> None:
    """RefreshFailed (single-use refresh-token race) is also a 502."""
    from dexcom_cgm_viewer.services.oauth import RefreshFailed
    api = _make_api("POST", "/sync", query_params={"patient_id": PATIENT, "range": "7d"})
    storage.upsert_tokens(
        PATIENT, access_token_ciphertext="x", refresh_token_ciphertext="y",
        expires_at=_now(), dexcom_user_id="DEX",
        now=_now(), is_initial_connection=True,
    )
    with patch("dexcom_cgm_viewer.protocols.chart_api.sync_patient",
               side_effect=RefreshFailed("refresh rejected")):
        effects = api.sync_now()
    assert effects[0].status_code == HTTPStatus.BAD_GATEWAY


def test_sync_propagates_unexpected_errors_for_observability() -> None:
    """Per REVIEW.md §3: a programmer bug (AttributeError, etc.) must surface
    rather than be masked as a generic 502 'sync_failed'."""
    api = _make_api("POST", "/sync", query_params={"patient_id": PATIENT, "range": "7d"})
    storage.upsert_tokens(
        PATIENT, access_token_ciphertext="x", refresh_token_ciphertext="y",
        expires_at=_now(), dexcom_user_id="DEX",
        now=_now(), is_initial_connection=True,
    )
    with patch("dexcom_cgm_viewer.protocols.chart_api.sync_patient",
               side_effect=AttributeError("oops")):
        with pytest.raises(AttributeError, match="oops"):
            api.sync_now()
    # The handler must NOT have written sync_failed state for a non-Dexcom bug.
    state = storage.get_sync_state(PATIENT)
    assert state is None or state.last_error != "sync_failed"


# ---- /send-link --------------------------------------------------------------


def test_send_link_requires_patient_id() -> None:
    api = _make_api("POST", "/send-link", query_params={})
    body = _json_body(api.send_link())
    assert "patient_id" in body["error"]


def test_send_link_returns_503_when_secrets_missing() -> None:
    api = _make_api("POST", "/send-link", query_params={"patient_id": PATIENT}, secrets={})
    effects = api.send_link()
    assert effects[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_send_link_returns_link_and_persists_state() -> None:
    api = _make_api("POST", "/send-link", query_params={"patient_id": PATIENT})
    effects = api.send_link()
    # No staff header → portal channel skipped, so only the JSON response is emitted.
    assert len(effects) == 1
    state = storage.get_sync_state(PATIENT)
    assert state is not None and state.link_pending is True and state.last_link_nonce
    body = _json_body(effects)
    assert "link_sent_at" in body
    assert body["connection_link"].startswith(
        "https://canvas.example.com/plugin-io/api/dexcom_cgm_viewer/connect?token="
    )
    assert body["expires_in_seconds"] == 15 * 60
    # SendGrid not configured for the default test secrets — email is skipped.
    assert body["email_status"] == "skipped"
    assert body["email_error"] == "sendgrid_not_configured"
    assert body["email_to"] is None
    # Portal channel also skipped because we passed no staff header.
    assert body["portal_status"] == "skipped"
    assert body["portal_error"] == "no_staff_sender"


def test_send_link_emits_portal_message_when_staff_header_present() -> None:
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    fake_effect = MagicMock()
    with patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=True,
    ), patch("dexcom_cgm_viewer.protocols.chart_api.Message") as MockMsg:
        instance = MagicMock()
        instance.create_and_send.return_value = fake_effect
        MockMsg.return_value = instance
        effects = api.send_link()
    # First effect is the portal Message, second is the JSON response.
    assert len(effects) == 2
    assert effects[0] is fake_effect
    body = _json_body(effects)
    assert body["portal_status"] == "sent"
    assert body["portal_error"] is None
    msg_kwargs = MockMsg.call_args.kwargs
    assert msg_kwargs["sender_id"] == "staff-1"
    assert msg_kwargs["recipient_id"] == PATIENT
    assert body["connection_link"] in msg_kwargs["content"]


def test_send_link_skips_portal_when_no_messageable_channel() -> None:
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    with patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=False,
    ):
        effects = api.send_link()
    assert len(effects) == 1
    body = _json_body(effects)
    assert body["portal_status"] == "skipped"
    assert body["portal_error"] == "no_messageable_channel"


def test_send_link_records_portal_failure_when_message_validation_fails() -> None:
    """A Pydantic ValidationError from Message.create_and_send (e.g. invalid
    sender/recipient id) is the documented failure mode and is caught."""
    from pydantic_core import InitErrorDetails, PydanticCustomError
    from pydantic import ValidationError
    validation_err = ValidationError.from_exception_data(
        "Message",
        [InitErrorDetails(
            type=PydanticCustomError("value_error", "invalid recipient"),
            input="bad-id",
            loc=("recipient_id",),
        )],
    )
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    with patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=True,
    ), patch(
        "dexcom_cgm_viewer.protocols.chart_api.Message",
        side_effect=validation_err,
    ):
        effects = api.send_link()
    assert len(effects) == 1
    body = _json_body(effects)
    assert body["portal_status"] == "failed"
    assert "invalid recipient" in body["portal_error"]


def test_send_link_propagates_unexpected_portal_errors() -> None:
    """Per REVIEW.md §3: only ValidationError is caught from Message
    construction. Any other exception is a bug and must surface."""
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    with patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=True,
    ), patch(
        "dexcom_cgm_viewer.protocols.chart_api.Message",
        side_effect=RuntimeError("portal infra exploded"),
    ):
        with pytest.raises(RuntimeError, match="portal infra exploded"):
            api.send_link()


def test_patient_has_messageable_channel_returns_false_for_missing_patient() -> None:
    from canvas_sdk.v1.data import Patient
    from dexcom_cgm_viewer.protocols.chart_api import _patient_has_messageable_channel
    with patch.object(Patient.objects, "get", side_effect=Patient.DoesNotExist):
        assert _patient_has_messageable_channel("nope") is False


def test_patient_has_messageable_channel_filters_by_consent_and_state() -> None:
    from canvas_sdk.v1.data import Patient
    from dexcom_cgm_viewer.protocols.chart_api import _patient_has_messageable_channel
    fake_patient = MagicMock()
    fake_qs = MagicMock()
    fake_qs.exists.return_value = True
    fake_patient.telecom.filter.return_value = fake_qs
    with patch.object(Patient.objects, "get", return_value=fake_patient):
        assert _patient_has_messageable_channel(PATIENT) is True
    filter_kwargs = fake_patient.telecom.filter.call_args.kwargs
    assert filter_kwargs["system__in"] == ("email", "sms")
    assert filter_kwargs["has_consent"] is True
    assert filter_kwargs["opted_out"] is False
    assert filter_kwargs["state"] == "active"


def test_send_link_emails_when_sendgrid_configured() -> None:
    secrets = _full_secrets() | {
        "SENDGRID_API_KEY": "SG.test", "SENDGRID_FROM_EMAIL": "noreply@example.com",
    }
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT}, secrets=secrets,
    )
    fake_patient = MagicMock(first_name="Alex")
    fake_email_qs = MagicMock()
    fake_email_qs.order_by.return_value.first.return_value = MagicMock(value="alex@example.com")
    fake_patient.telecom.filter.return_value = fake_email_qs
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", return_value=fake_patient), \
         patch("dexcom_cgm_viewer.protocols.chart_api.send_magic_link_email",
               return_value=True) as mock_send:
        body = _json_body(api.send_link())
    assert body["email_status"] == "sent"
    assert body["email_to"] == "alex@example.com"
    assert mock_send.call_count == 1
    sent_kwargs = mock_send.call_args.kwargs
    assert sent_kwargs["to_email"] == "alex@example.com"
    assert sent_kwargs["patient_first_name"] == "Alex"
    assert sent_kwargs["link"] == body["connection_link"]


def test_send_link_reports_failed_when_sendgrid_rejects() -> None:
    from dexcom_cgm_viewer.services.email import EmailDeliveryError
    secrets = _full_secrets() | {
        "SENDGRID_API_KEY": "SG.test", "SENDGRID_FROM_EMAIL": "noreply@example.com",
    }
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT}, secrets=secrets,
    )
    fake_patient = MagicMock(first_name="Sam")
    fake_email_qs = MagicMock()
    fake_email_qs.order_by.return_value.first.return_value = MagicMock(value="sam@example.com")
    fake_patient.telecom.filter.return_value = fake_email_qs
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", return_value=fake_patient), \
         patch("dexcom_cgm_viewer.protocols.chart_api.send_magic_link_email",
               side_effect=EmailDeliveryError(401, "bad key")):
        body = _json_body(api.send_link())
    assert body["email_status"] == "failed"
    assert body["email_to"] == "sam@example.com"
    assert "401" in body["email_error"]
    # Link is still returned for copyable fallback.
    assert body["connection_link"].startswith("https://canvas.example.com/")


def test_send_link_propagates_unexpected_email_errors() -> None:
    """Per REVIEW.md §3: only the documented EmailDeliveryError is caught.
    A RuntimeError (e.g. requests-side network bug) must surface."""
    secrets = _full_secrets() | {
        "SENDGRID_API_KEY": "SG.test", "SENDGRID_FROM_EMAIL": "noreply@example.com",
    }
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT}, secrets=secrets,
    )
    fake_patient = MagicMock(first_name="Sam")
    fake_email_qs = MagicMock()
    fake_email_qs.order_by.return_value.first.return_value = MagicMock(value="sam@example.com")
    fake_patient.telecom.filter.return_value = fake_email_qs
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", return_value=fake_patient), \
         patch("dexcom_cgm_viewer.protocols.chart_api.send_magic_link_email",
               side_effect=RuntimeError("network blew up")):
        with pytest.raises(RuntimeError, match="network blew up"):
            api.send_link()


def test_send_link_skips_when_patient_not_found() -> None:
    secrets = _full_secrets() | {
        "SENDGRID_API_KEY": "SG.test", "SENDGRID_FROM_EMAIL": "noreply@example.com",
    }
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT}, secrets=secrets,
    )
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", side_effect=Patient.DoesNotExist):
        body = _json_body(api.send_link())
    assert body["email_status"] == "skipped"
    assert body["email_error"] == "patient_not_found"


def test_send_link_skips_when_patient_has_no_email() -> None:
    secrets = _full_secrets() | {
        "SENDGRID_API_KEY": "SG.test", "SENDGRID_FROM_EMAIL": "noreply@example.com",
    }
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT}, secrets=secrets,
    )
    fake_patient = MagicMock(first_name="Pat")
    fake_email_qs = MagicMock()
    fake_email_qs.order_by.return_value.first.return_value = None
    fake_patient.telecom.filter.return_value = fake_email_qs
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", return_value=fake_patient):
        body = _json_body(api.send_link())
    assert body["email_status"] == "skipped"
    assert body["email_error"] == "no_email_on_file"


def test_send_link_channels_param_skips_email_when_not_selected() -> None:
    secrets = _full_secrets() | {
        "SENDGRID_API_KEY": "SG.test", "SENDGRID_FROM_EMAIL": "noreply@example.com",
    }
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT, "channels": "portal"},
        headers={"canvas-logged-in-user-id": "staff-1"},
        secrets=secrets,
    )
    with patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=True,
    ), patch("dexcom_cgm_viewer.protocols.chart_api.Message") as MockMsg, \
         patch("dexcom_cgm_viewer.protocols.chart_api.send_magic_link_email") as mock_send:
        MockMsg.return_value.create_and_send.return_value = MagicMock()
        body = _json_body(api.send_link())
    # Email channel not selected → skipped without touching SendGrid.
    assert body["email_status"] == "skipped"
    assert body["email_error"] == "not_selected"
    assert mock_send.call_count == 0
    # Portal channel selected → still attempted.
    assert body["portal_status"] == "sent"


def test_send_link_channels_param_skips_portal_when_not_selected() -> None:
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT, "channels": "email"},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    with patch("dexcom_cgm_viewer.protocols.chart_api.Message") as MockMsg:
        effects = api.send_link()
    # Portal not selected → no Message effect emitted, only the JSON response.
    assert MockMsg.call_count == 0
    assert len(effects) == 1
    body = _json_body(effects)
    assert body["portal_status"] == "skipped"
    assert body["portal_error"] == "not_selected"


def test_send_link_channels_empty_skips_both() -> None:
    api = _make_api(
        "POST", "/send-link",
        query_params={"patient_id": PATIENT, "channels": ""},
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    effects = api.send_link()
    assert len(effects) == 1
    body = _json_body(effects)
    assert body["email_status"] == "skipped"
    assert body["email_error"] == "not_selected"
    assert body["portal_status"] == "skipped"
    assert body["portal_error"] == "not_selected"
    # Link is still minted and returned for the copyable fallback.
    assert body["connection_link"].startswith("https://canvas.example.com/")


def test_parse_channels_defaults_to_both_when_absent() -> None:
    from dexcom_cgm_viewer.protocols.chart_api import _parse_channels
    assert _parse_channels(None) == {"email", "portal"}


def test_parse_channels_handles_explicit_selections_and_garbage() -> None:
    from dexcom_cgm_viewer.protocols.chart_api import _parse_channels
    assert _parse_channels("") == set()
    assert _parse_channels("email") == {"email"}
    assert _parse_channels("portal,email") == {"email", "portal"}
    assert _parse_channels(" Email , PORTAL ") == {"email", "portal"}
    assert _parse_channels("email,sms,bogus") == {"email"}
    assert _parse_channels("sms") == set()


# ---- /diagnose ---------------------------------------------------------------


def test_diagnose_requires_patient_id() -> None:
    api = _make_api("GET", "/diagnose", query_params={})
    body = _json_body(api.diagnose())
    assert "patient_id" in body["error"]


def test_diagnose_returns_404_when_patient_missing() -> None:
    api = _make_api("GET", "/diagnose", query_params={"patient_id": PATIENT})
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", side_effect=Patient.DoesNotExist):
        effects = api.diagnose()
    assert effects[0].status_code == HTTPStatus.NOT_FOUND


def test_diagnose_returns_contact_point_state() -> None:
    api = _make_api("GET", "/diagnose", query_params={"patient_id": PATIENT})
    fake_patient = MagicMock(id=PATIENT, first_name="Alex")
    fake_cp = MagicMock(
        system="email", value="alex@example.com", use="home", rank=1,
        state="active", has_consent=True, opted_out=False, last_verified=None,
    )
    fake_qs = MagicMock()
    fake_qs.order_by.return_value = [fake_cp]
    fake_patient.telecom.filter.return_value = fake_qs
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", return_value=fake_patient), patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=True,
    ):
        body = _json_body(api.diagnose())
    assert body["patient_id"] == PATIENT
    assert body["messageable_channel_present"] is True
    assert body["contact_points"][0]["system"] == "email"
    assert body["contact_points"][0]["value"] == "alex@example.com"
    assert body["contact_points"][0]["has_consent"] is True
    assert body["contact_points"][0]["opted_out"] is False


def test_diagnose_serializes_last_verified_datetime() -> None:
    api = _make_api("GET", "/diagnose", query_params={"patient_id": PATIENT})
    fake_patient = MagicMock(id=PATIENT, first_name="Sam")
    fake_dt = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.timezone.utc)
    fake_cp = MagicMock(
        system="email", value="sam@example.com", use="home", rank=1,
        state="active", has_consent=True, opted_out=False, last_verified=fake_dt,
    )
    fake_qs = MagicMock()
    fake_qs.order_by.return_value = [fake_cp]
    fake_patient.telecom.filter.return_value = fake_qs
    from canvas_sdk.v1.data import Patient
    with patch.object(Patient.objects, "get", return_value=fake_patient), patch(
        "dexcom_cgm_viewer.protocols.chart_api._patient_has_messageable_channel",
        return_value=True,
    ):
        body = _json_body(api.diagnose())
    assert body["contact_points"][0]["last_verified"] == fake_dt.isoformat()


# ---- /disconnect -------------------------------------------------------------


def test_disconnect_requires_patient_id() -> None:
    api = _make_api("POST", "/disconnect", query_params={})
    body = _json_body(api.disconnect())
    assert "patient_id" in body["error"]


def test_disconnect_purges_state() -> None:
    storage.upsert_tokens(
        PATIENT, access_token_ciphertext="x", refresh_token_ciphertext="y",
        expires_at=_now(), dexcom_user_id="DEX",
        now=_now(), is_initial_connection=True,
    )
    api = _make_api("POST", "/disconnect", query_params={"patient_id": PATIENT})
    body = _json_body(api.disconnect())
    assert body == {"disconnected": True}
    assert storage.get_tokens(PATIENT) is None


# ---- helpers ----------------------------------------------------------------


def test_missing_secrets_lists_every_required_when_dict_is_empty() -> None:
    assert "DEXCOM_CLIENT_ID" in _missing_secrets({})
    assert "DEXCOM_CLIENT_ID" in _missing_secrets(None)


def test_missing_secrets_returns_empty_when_full() -> None:
    assert _missing_secrets(_full_secrets()) == ""


def test_build_client_routes_to_environment_url() -> None:
    secrets = _full_secrets()
    secrets["DEXCOM_ENVIRONMENT"] = "production"
    client = _build_client(secrets)
    assert client.base_url == "https://api.dexcom.com"


def test_build_connect_url_uses_redirect_host_only() -> None:
    url = _build_connect_url(
        "https://canvas.example.com/plugin-io/api/dexcom_cgm_viewer/callback",
        "abc.def",
    )
    assert url.startswith("https://canvas.example.com/plugin-io/api/dexcom_cgm_viewer/connect?token=")
    assert "token=abc.def" in url


def test_build_connect_url_rejects_non_absolute_url() -> None:
    with pytest.raises(ValueError):
        _build_connect_url("/relative/path", "abc.def")


def test_build_connect_url_rejects_empty_redirect_uri() -> None:
    with pytest.raises(ValueError):
        _build_connect_url("", "abc.def")


def test_build_connect_url_rejects_missing_host() -> None:
    # ``https://`` has scheme + sep but empty authority; should raise.
    with pytest.raises(ValueError, match="missing a host"):
        _build_connect_url("https:///just/path", "abc.def")
