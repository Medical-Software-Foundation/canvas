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


def test_inbound_accepts_a_realistic_twilio_payload_with_blank_geo_fields() -> None:
    """Regression: the shape real Twilio actually posts.

    Carriers routinely omit the geo fields, so Twilio sends them empty and signs
    over ``key + ""`` for each. Sourcing params from the SDK's ``form_data()``
    dropped those keys, the recomputed HMAC differed, and every genuine inbound
    SMS was rejected 401 — the two-way confirm flow had never worked live. Every
    other test here builds a fully-populated payload, which is exactly the case
    that passed.
    """
    body = (
        "AccountSid=AC123&MessageSid=SM456&Body=Y&From=%2B14155551234"
        "&To=%2B15559990000&FromCity=&FromState=&FromZip=&FromCountry=US"
        "&ToCity=&ToState=CA&ToZip=&NumMedia=0"
    )
    api = _api(body)
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()

    assert result[-1].status_code == HTTPStatus.OK  # not 401
    mock_appt.return_value.update.assert_called_once()  # and it actually confirmed
    assert mock_log.call_args.kwargs["status"] == "confirmed"


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
    # "C" confirms without also being a Twilio opt-in keyword, so this isolates
    # the no-appointment branch. The YES overlap is covered separately below.
    api = _api("Body=C&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=None), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.sms_consent_effect") as mock_consent, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()
    mock_appt.assert_not_called()
    mock_consent.assert_not_called()
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


# ---- consent write-back (STOP / START) ----

def test_inbound_stop_clears_sms_consent() -> None:
    api = _api("Body=STOP&From=%2B14155551234")
    effect = MagicMock()
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.sms_consent_effect", return_value=effect) as mock_consent, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()

    mock_consent.assert_called_once()
    assert mock_consent.call_args.args[1] == "+14155551234"
    assert mock_consent.call_args.kwargs["has_consent"] is False
    # STOP says nothing about the appointment itself.
    mock_appt.assert_not_called()
    mock_task.assert_not_called()
    assert mock_log.call_args.kwargs["status"] == "opted_out"
    assert effect in result


def test_inbound_start_restores_sms_consent() -> None:
    api = _api("Body=START&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.sms_consent_effect", return_value=MagicMock()) as mock_consent, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()

    assert mock_consent.call_args.kwargs["has_consent"] is True
    assert mock_log.call_args.kwargs["status"] == "opted_in"


def test_inbound_cancel_both_opts_out_and_opens_decline_task() -> None:
    """CANCEL is a Twilio opt-out keyword *and* this plugin's decline token.

    Acting on only one half would either leave a patient Twilio has blocked
    still marked as consenting, or silently drop their request to cancel.
    """
    api = _api("Body=CANCEL&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.sms_consent_effect", return_value=MagicMock()) as mock_consent, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()

    assert mock_consent.call_args.kwargs["has_consent"] is False
    mock_task.assert_called_once()
    assert mock_log.call_args.kwargs["status"] == "opted_out+declined"


def test_inbound_yes_both_opts_in_and_confirms_appointment() -> None:
    """YES is a Twilio opt-in keyword as well as a confirm token."""
    api = _api("Body=YES&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.sms_consent_effect", return_value=MagicMock()) as mock_consent, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()

    assert mock_consent.call_args.kwargs["has_consent"] is True
    mock_appt.return_value.update.assert_called_once()
    assert mock_log.call_args.kwargs["status"] == "opted_in+confirmed"


def test_inbound_logs_opt_out_even_when_no_write_is_needed() -> None:
    """A redundant STOP emits no patient effect but is still audited."""
    api = _api("Body=STOP&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.sms_consent_effect", return_value=None), \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()

    assert mock_log.call_args.kwargs["status"] == "opted_out"
    assert len(result) == 1  # response only, no patient update


def test_inbound_confirm_does_not_touch_consent() -> None:
    api = _api("Body=Y&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment"), \
         patch(f"{_MOD}.sms_consent_effect") as mock_consent, \
         patch(f"{_MOD}.log_inbound_response"):
        api.inbound()
    mock_consent.assert_not_called()


# ---- _form_params (source-of-params) ----

def _bare_api() -> TwilioInboundAPI:
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    api.request = MagicMock()
    return api


def test_form_params_parses_the_raw_body_in_preference_to_form_data() -> None:
    """The raw body wins because ``form_data()`` silently drops blank values."""
    api = _bare_api()
    api.request.body = "Body=N&From=%2B14155551234"
    api.request.form_data.return_value = {"Body": MagicMock(value="WRONG")}
    params = api._form_params()
    assert params["Body"] == "N"
    assert params["From"] == "+14155551234"  # %2B decoded by parse_form_body


def test_form_params_keeps_empty_valued_twilio_params() -> None:
    """Regression: blanks are part of the signed string and must survive.

    ``form_data()`` runs ``parse_qsl`` without ``keep_blank_values``, so it
    returns 2 of these 4 keys. Rebuilding the signing string from that subset
    produced a different HMAC and rejected every real inbound SMS with 401.
    """
    api = _bare_api()
    api.request.body = "Body=Y&From=%2B14155551234&FromCity=&FromZip="
    params = api._form_params()
    assert params == {
        "Body": "Y",
        "From": "+14155551234",
        "FromCity": "",
        "FromZip": "",
    }


def test_form_params_falls_back_to_form_data_when_body_is_unavailable() -> None:
    api = _bare_api()
    api.request.body = ""
    form_part = MagicMock()
    form_part.value = "Y"  # FormPart-like: value read off .value
    api.request.form_data.return_value = {"Body": form_part, "From": "+14155551234"}
    params = api._form_params()
    assert params == {"Body": "Y", "From": "+14155551234"}  # str fallback for plain str


def test_form_params_returns_empty_when_neither_source_works() -> None:
    api = _bare_api()
    api.request.body = ""
    api.request.form_data.side_effect = RuntimeError("form_data unavailable")
    assert api._form_params() == {}


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
