"""Tests for the TwilioInboundAPI webhook handler.

The endpoint is public (authenticate returns True); the security gate is the
X-Twilio-Signature check inside inbound(). These tests drive inbound() directly
with a validly-signed request by default (see _api), so the signature gate is
exercised end-to-end rather than mocked away.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from appointment_reminders.handlers.twilio_inbound_api import TwilioInboundAPI
from appointment_reminders.services.twilio_inbound import parse_form_body

_MOD = "appointment_reminders.handlers.twilio_inbound_api"
_URL = "https://example.canvasmedical.com/plugin-io/api/appointment_reminders/twilio/inbound"
_TOKEN = "auth-tok"


def _sign(url: str, params: dict[str, str], token: str) -> str:
    data = url
    for key in sorted(params):
        data += key + params[key]
    return base64.b64encode(
        hmac.new(token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode()


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, timeout_seconds=None):
        self.store[key] = value


@pytest.fixture(autouse=True)
def _mock_cache():
    with patch(f"{_MOD}.get_cache", return_value=_FakeCache()):
        yield


def _api(
    body: str,
    headers: dict | None = None,
    secrets: dict | None = None,
    sign: bool = True,
) -> TwilioInboundAPI:
    """Build a handler instance. By default attaches a VALID X-Twilio-Signature
    computed over the body's params, so requests pass the gate unless a test
    overrides the header or omits the token."""
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    api.request = MagicMock()
    api.request.body = body
    api.request.form_data.return_value = {}  # force fallback to parse_form_body(body)
    api.secrets = secrets if secrets is not None else {
        "twilio-auth-token": _TOKEN,
        "twilio-inbound-webhook-url": _URL,
    }
    hdrs = dict(headers or {})
    if sign and "X-Twilio-Signature" not in hdrs:
        hdrs["X-Twilio-Signature"] = _sign(
            _URL, parse_form_body(body), api.secrets.get("twilio-auth-token", "")
        )
    api.request.headers = MagicMock()
    api.request.headers.get = MagicMock(side_effect=lambda k, d=None: hdrs.get(k, d))
    return api


def _patient(pid: str = "pat-1") -> MagicMock:
    p = MagicMock()
    p.id = pid
    return p


def _appt(aid: str = "appt-1") -> MagicMock:
    a = MagicMock()
    a.id = aid
    return a


# ---- signature gate (inside inbound) ----

def test_inbound_valid_signature_passes_gate() -> None:
    # Valid signature + no patient match → 200 no-op (proves the gate let it through).
    api = _api("Body=Y&From=%2B15005550999")
    with patch.object(api, "_resolve_patient", return_value=None), \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()
    mock_log.assert_not_called()
    assert result[0].status_code == HTTPStatus.OK


def test_inbound_rejects_invalid_signature() -> None:
    api = _api("Body=Y&From=%2B14155551234", headers={"X-Twilio-Signature": "bogus"})
    with patch.object(api, "_resolve_patient") as mock_resolve:
        result = api.inbound()
    mock_resolve.assert_not_called()  # rejected before any work
    assert result[0].status_code == HTTPStatus.UNAUTHORIZED


def test_inbound_fails_closed_without_token() -> None:
    api = _api(
        "Body=Y&From=%2B14155551234",
        secrets={"twilio-inbound-webhook-url": _URL},  # no auth token
    )
    result = api.inbound()
    assert result[0].status_code == HTTPStatus.UNAUTHORIZED


def test_authenticate_is_public() -> None:
    # authenticate() is intentionally public; the signature gate lives in inbound().
    api = _api("Body=Y")
    assert api.authenticate(MagicMock()) is True


# ---- inbound (confirm / decline / no-op) ----

def test_inbound_confirm_updates_appointment_status() -> None:
    api = _api("Body=Y&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()
    mock_appt.assert_called_once_with(instance_id="appt-1")
    mock_appt.return_value.update.assert_called_once()
    assert mock_log.call_args.kwargs["status"] == "confirmed"
    assert result[-1].status_code == HTTPStatus.OK


def test_inbound_confirm_without_appointment_logs_no_appointment() -> None:
    api = _api("Body=YES&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=None), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()
    mock_appt.assert_not_called()
    assert mock_log.call_args.kwargs["status"] == "confirmed_no_appointment"


def test_inbound_decline_opens_followup_task() -> None:
    api = _api("Body=N&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()
    mock_task.assert_called_once()
    kwargs = mock_task.call_args.kwargs
    assert kwargs["patient_id"] == "pat-1"
    assert "appointment-decline" in kwargs["labels"]
    assert mock_log.call_args.kwargs["status"] == "declined"


def test_inbound_unknown_sender_is_noop() -> None:
    api = _api("Body=Y&From=%2B19998887777")
    with patch.object(api, "_resolve_patient", return_value=None), \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()
    mock_log.assert_not_called()
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK


def test_inbound_unrecognized_logs_only_no_effects() -> None:
    api = _api("Body=maybe%20later&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()
    mock_appt.assert_not_called()
    mock_task.assert_not_called()
    assert mock_log.call_args.kwargs["status"] == "unrecognized"
    assert len(result) == 1


def test_inbound_replayed_message_sid_is_ignored() -> None:
    api = _api("Body=N&From=%2B14155551234&MessageSid=SM123ABC")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()           # first: acts (opens a Task)
        second = api.inbound()  # replay of same MessageSid: no-op
    mock_task.assert_called_once()
    mock_log.assert_called_once()
    assert len(second) == 1
    assert second[0].status_code == HTTPStatus.OK


# ---- _form_params (source-of-params) ----

def _bare_api() -> TwilioInboundAPI:
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    api.request = MagicMock()
    return api


def test_form_params_prefers_form_data_and_coerces_values() -> None:
    api = _bare_api()
    form_part = MagicMock()
    form_part.value = "Y"  # FormPart-like: value read off .value
    api.request.form_data.return_value = {"Body": form_part, "From": "+14155551234"}
    params = api._form_params()
    assert params == {"Body": "Y", "From": "+14155551234"}  # str fallback for plain str


def test_form_params_falls_back_to_body_when_form_data_raises() -> None:
    api = _bare_api()
    api.request.form_data.side_effect = RuntimeError("form_data unavailable")
    api.request.body = "Body=N&From=%2B14155551234"
    params = api._form_params()
    assert params["Body"] == "N"
    assert params["From"] == "+14155551234"  # %2B decoded by parse_form_body


# ---- _resolve_patient (real ORM path, mocked) ----

def _contact(system: str = "phone", value: str = "+14155551234") -> MagicMock:
    c = MagicMock()
    c.system = system
    c.value = value
    return c


def _patient_with_contacts(contacts: list, pid: str = "pat-1") -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.telecom.all.return_value = contacts
    return p


def test_resolve_patient_none_when_too_few_digits() -> None:
    api = _bare_api()
    assert api._resolve_patient("+12") is None  # < 4 digits, no query


def test_resolve_patient_returns_match_on_normalized_phone() -> None:
    api = _bare_api()
    # Stored in a different format; must still match after normalization.
    match = _patient_with_contacts([_contact(value="(415) 555-1234")], "pat-match")
    with patch(f"{_MOD}.Patient") as mock_patient:
        (mock_patient.objects.filter.return_value
            .prefetch_related.return_value
            .distinct.return_value) = [match]
        result = api._resolve_patient("+14155551234")
    assert result is match


def test_resolve_patient_none_when_no_contact_normalizes_to_number() -> None:
    api = _bare_api()
    # A non-phone contact and a phone that normalizes to a different number.
    candidate = _patient_with_contacts(
        [_contact(system="email", value="a@b.com"), _contact(value="+19998887777")],
        "pat-x",
    )
    with patch(f"{_MOD}.Patient") as mock_patient:
        (mock_patient.objects.filter.return_value
            .prefetch_related.return_value
            .distinct.return_value) = [candidate]
        result = api._resolve_patient("+14155551234")
    assert result is None


# ---- _nearest_upcoming_appointment (real ORM path, mocked) ----

def test_nearest_upcoming_appointment_returns_first_ordered() -> None:
    api = _bare_api()
    appt = _appt("appt-9")
    with patch(f"{_MOD}.AppointmentModel") as mock_appt:
        (mock_appt.objects.filter.return_value
            .order_by.return_value.first.return_value) = appt
        result = api._nearest_upcoming_appointment(_patient())
    assert result is appt
    mock_appt.objects.filter.return_value.order_by.assert_called_once_with("start_time")
