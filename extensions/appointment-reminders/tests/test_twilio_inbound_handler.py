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
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from appointment_reminders.handlers.twilio_inbound_api import TwilioInboundAPI
from appointment_reminders.services.config import CampaignConfig
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
    # Valid signature + no patient match → 200 with no effects (proves the gate
    # let it through; the unresolved sender is audited separately below).
    api = _api("Body=Y&From=%2B15005550999")
    with patch.object(api, "_resolve_patient", return_value=None), \
         patch(f"{_MOD}.log_unresolved_sender"), \
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
         patch.object(api, "_decline_task_team_id", return_value=None), \
         patch(f"{_MOD}.load_config", return_value=CampaignConfig()), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()
    mock_task.assert_called_once()
    kwargs = mock_task.call_args.kwargs
    assert kwargs["patient_id"] == "pat-1"
    assert "appointment-decline" in kwargs["labels"]
    assert mock_log.call_args.kwargs["status"] == "declined"


def test_inbound_unknown_sender_produces_no_effects() -> None:
    """No patient means no appointment or task to act on — but see the audit below."""
    api = _api("Body=Y&From=%2B19998887777")
    with patch.object(api, "_resolve_patient", return_value=None), \
         patch(f"{_MOD}.log_unresolved_sender"), \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        result = api.inbound()
    mock_log.assert_not_called()  # the patient-keyed writer cannot run
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK


def test_inbound_unknown_sender_writes_an_unresolved_audit_row() -> None:
    """A verified reply from an unmatched number must leave a trace.

    Previously it returned 200 and wrote nothing, so the appointment simply
    stayed unconfirmed and ops read that as the patient never replying — when
    they had replied, from a number on no chart.
    """
    api = _api("Body=Y&From=%2B19998887777")
    with patch.object(api, "_resolve_patient", return_value=None), \
         patch(f"{_MOD}.log_unresolved_sender") as mock_unresolved:
        api.inbound()

    mock_unresolved.assert_called_once_with(body="Y", from_number="+19998887777")


def test_inbound_does_not_audit_an_unresolved_sender_without_a_valid_signature() -> None:
    """The audit row is for verified traffic only.

    Writing on an unverified request would let anyone POST arbitrary phone
    numbers and message bodies into the activity log.
    """
    api = _api("Body=Y&From=%2B19998887777", headers={"X-Twilio-Signature": "bogus"})
    with patch(f"{_MOD}.log_unresolved_sender") as mock_unresolved:
        result = api.inbound()

    mock_unresolved.assert_not_called()
    assert result[0].status_code == HTTPStatus.UNAUTHORIZED


def test_inbound_does_not_audit_a_replayed_unresolved_sender() -> None:
    """The replay guard runs first, so a replayed SID cannot inflate the log."""
    api = _api("Body=Y&From=%2B19998887777&MessageSid=SM999")
    with patch.object(api, "_resolve_patient", return_value=None), \
         patch(f"{_MOD}.log_unresolved_sender") as mock_unresolved:
        api.inbound()
        api.inbound()  # replay of the same MessageSid

    mock_unresolved.assert_called_once()


def test_inbound_audits_a_resolved_sender_via_the_patient_writer_only() -> None:
    """The two writers are mutually exclusive — never both for one reply."""
    api = _api("Body=Y&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment"), \
         patch(f"{_MOD}.log_unresolved_sender") as mock_unresolved, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()

    mock_unresolved.assert_not_called()
    mock_log.assert_called_once()


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
         patch.object(api, "_decline_task_team_id", return_value=None), \
         patch(f"{_MOD}.load_config", return_value=CampaignConfig()), \
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


def test_inbound_cancel_opts_out_without_touching_the_appointment() -> None:
    """CANCEL is an unsubscribe keyword, not an appointment decline.

    Twilio publishes it as a STOP synonym, so it clears consent — but it must
    not open a reschedule Task, which would attribute an intent about the visit
    that the patient never expressed.
    """
    api = _api("Body=CANCEL&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch.object(api, "_decline_task_team_id", return_value=None), \
         patch(f"{_MOD}.load_config", return_value=CampaignConfig()), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.Appointment") as mock_appt, \
         patch(f"{_MOD}.sms_consent_effect", return_value=MagicMock()) as mock_consent, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        api.inbound()

    assert mock_consent.call_args.kwargs["has_consent"] is False
    mock_task.assert_not_called()
    mock_appt.assert_not_called()
    assert mock_log.call_args.kwargs["status"] == "opted_out"


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
    assert api._resolve_patient("+12") is None  # < 10 digits, no query


def test_resolve_patient_returns_none_below_ten_digits() -> None:
    """Fewer than 10 digits cannot match; fail safe rather than over-match."""
    api = _bare_api()
    with patch(f"{_MOD}.Patient") as mock_patient:
        assert api._resolve_patient("+141555512") is None  # 9 digits
    mock_patient.objects.filter.assert_not_called()  # bailed before querying


def test_resolve_patient_filters_on_the_full_ten_digit_suffix() -> None:
    """The query must anchor on a 10-digit suffix, not a 4-digit substring.

    ``telecom__value__contains=last4`` matched those digits anywhere in the
    value, so a number merely *containing* 1234 was a candidate alongside the
    one ending in it.
    """
    api = _bare_api()
    with patch(f"{_MOD}.Patient") as mock_patient:
        (mock_patient.objects.filter.return_value
            .prefetch_related.return_value
            .distinct.return_value) = []
        api._resolve_patient("+14155551234")

    mock_patient.objects.filter.assert_called_once_with(
        telecom__system="phone", telecom__value__endswith="4155551234"
    )


def test_resolve_patient_finds_match_beyond_the_old_50_row_cap() -> None:
    """Regression: the target must resolve even when it sorts past row 50.

    The old query sliced ``[:50]`` off a queryset with no ``ORDER BY``, so at
    production scale (~200 candidates sharing a last-4) it threw away three
    quarters of them before the exact-match loop ever ran — and silently, since
    a miss returns 200 with no audit row and reads as patient non-response.
    """
    decoys = [
        _patient_with_contacts([_contact(value=f"555{i:07d}")], f"decoy-{i}")
        for i in range(200)
    ]
    target = _patient_with_contacts([_contact(value="4155551234")], "pat-target")
    candidates = decoys[:150] + [target] + decoys[150:]  # target sits at index 150

    api = _bare_api()
    with patch(f"{_MOD}.Patient") as mock_patient:
        (mock_patient.objects.filter.return_value
            .prefetch_related.return_value
            .distinct.return_value) = candidates
        result = api._resolve_patient("+14155551234")

    assert result is target


def test_resolve_patient_query_is_not_capped() -> None:
    """No slice on the queryset: a truncated candidate set is what caused the bug.

    Guards the `.distinct()` result against a `[:N]` creeping back in — with a
    mock, slicing silently succeeds on the returned list, so only asserting the
    absence of `__getitem__` catches it.
    """
    api = _bare_api()
    with patch(f"{_MOD}.Patient") as mock_patient:
        distinct = (mock_patient.objects.filter.return_value
                    .prefetch_related.return_value
                    .distinct.return_value)
        distinct.__iter__ = lambda self: iter([])
        api._resolve_patient("+14155551234")
        distinct.__getitem__.assert_not_called()


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


# ---- decline task team routing ----

def test_decline_task_is_assigned_to_the_configured_team() -> None:
    api = _api("Body=N&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch.object(api, "_decline_task_team_id", return_value="team-7"), \
         patch(f"{_MOD}.load_config", return_value=CampaignConfig()), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response"):
        api.inbound()
    assert mock_task.call_args.kwargs["team_id"] == "team-7"


def _bare_with_config(team_id: str):
    return _bare_api(), CampaignConfig(decline_task_team_id=team_id)


def test_decline_team_none_when_unconfigured() -> None:
    """Unassigned is the pre-existing behavior and stays the default."""
    api, cfg = _bare_with_config("")
    with patch(f"{_MOD}.Team") as mock_team:
        assert api._decline_task_team_id(cfg) is None
    mock_team.objects.filter.assert_not_called()  # nothing to verify


def test_decline_team_none_when_configured_blank() -> None:
    api, cfg = _bare_with_config("   ")
    with patch(f"{_MOD}.Team"):
        assert api._decline_task_team_id(cfg) is None


def test_decline_team_returned_when_it_exists() -> None:
    api, cfg = _bare_with_config("team-7")
    with patch(f"{_MOD}.Team") as mock_team:
        mock_team.objects.filter.return_value.exists.return_value = True
        assert api._decline_task_team_id(cfg) == "team-7"
    mock_team.objects.filter.assert_called_once_with(id="team-7")


def test_decline_team_falls_back_to_unassigned_when_team_deleted() -> None:
    """A dangling team id must not cost us the task.

    Handing AddTask an id that no longer resolves risks the effect failing,
    which would lose the one artifact telling staff this patient wants to
    reschedule. An unassigned task beats no task.
    """
    api, cfg = _bare_with_config("team-gone")
    with patch(f"{_MOD}.Team") as mock_team:
        mock_team.objects.filter.return_value.exists.return_value = False
        assert api._decline_task_team_id(cfg) is None


def test_confirm_does_not_read_the_team_config() -> None:
    """Only a decline needs it, so the lookup stays off every other path."""
    api = _api("Body=Y&From=%2B14155551234")
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Appointment"), \
         patch(f"{_MOD}.load_config") as mock_load, \
         patch(f"{_MOD}.log_inbound_response"):
        api.inbound()
    mock_load.assert_not_called()


# ---- decline task due date ----

def _bare_with_env(tz_name: str | None) -> TwilioInboundAPI:
    api = _bare_api()
    api.environment = {} if tz_name is None else {"INSTALLATION_TIME_ZONE": tz_name}
    return api


def test_decline_task_has_no_due_date_when_toggle_is_off() -> None:
    """Off is the default and matches how the task was created before."""
    api = _bare_with_env("America/New_York")
    assert api._decline_task_due(CampaignConfig()) is None


def test_decline_task_due_is_end_of_the_instances_local_day() -> None:
    """The date must be the instance's, not UTC's.

    `due` is a timestamp, so end-of-day computed in UTC renders as the previous
    day anywhere behind it — the off-by-one this anchoring exists to avoid.
    """
    import zoneinfo

    api = _bare_with_env("America/New_York")
    due = api._decline_task_due(CampaignConfig(decline_task_due_end_of_day=True))

    assert due is not None
    local = due.astimezone(zoneinfo.ZoneInfo("America/New_York"))
    assert (local.hour, local.minute, local.second) == (23, 59, 59)
    # Same calendar date the instance is currently on.
    assert local.date() == datetime.now(zoneinfo.ZoneInfo("America/New_York")).date()


def test_decline_task_due_is_in_the_future_so_it_is_not_born_overdue() -> None:
    """`due = now` would render the task as already late the moment it appears."""
    api = _bare_with_env("America/New_York")
    due = api._decline_task_due(CampaignConfig(decline_task_due_end_of_day=True))
    assert due > datetime.now(timezone.utc)


def test_decline_task_due_respects_a_different_instance_timezone() -> None:
    import zoneinfo

    api = _bare_with_env("Australia/Sydney")
    due = api._decline_task_due(CampaignConfig(decline_task_due_end_of_day=True))
    local = due.astimezone(zoneinfo.ZoneInfo("Australia/Sydney"))
    assert (local.hour, local.minute) == (23, 59)
    assert local.date() == datetime.now(zoneinfo.ZoneInfo("Australia/Sydney")).date()


def test_decline_task_due_falls_back_to_utc_without_an_instance_timezone() -> None:
    """Still produce a due date rather than silently dropping a setting the
    admin switched on."""
    for env_tz in (None, "", "Not/AZone"):
        api = _bare_with_env(env_tz)
        due = api._decline_task_due(CampaignConfig(decline_task_due_end_of_day=True))
        assert due is not None, env_tz
        assert due.astimezone(timezone.utc).date() == datetime.now(timezone.utc).date()


def test_decline_task_passes_the_due_date_to_addtask() -> None:
    api = _api("Body=N&From=%2B14155551234")
    api.environment = {"INSTALLATION_TIME_ZONE": "America/New_York"}
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch.object(api, "_decline_task_team_id", return_value="team-7"), \
         patch(f"{_MOD}.load_config",
               return_value=CampaignConfig(decline_task_due_end_of_day=True)), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response"):
        api.inbound()

    due = mock_task.call_args.kwargs["due"]
    assert due is not None and due > datetime.now(timezone.utc)


def test_decline_branch_reads_the_config_once() -> None:
    """Team and due date share one read; other reply paths read nothing."""
    api = _api("Body=N&From=%2B14155551234")
    api.environment = {"INSTALLATION_TIME_ZONE": "America/New_York"}
    with patch.object(api, "_resolve_patient", return_value=_patient()), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=_appt()), \
         patch(f"{_MOD}.Team") as mock_team, \
         patch(f"{_MOD}.load_config", return_value=CampaignConfig()) as mock_load, \
         patch(f"{_MOD}.AddTask"), \
         patch(f"{_MOD}.log_inbound_response"):
        mock_team.objects.filter.return_value.exists.return_value = True
        api.inbound()
    mock_load.assert_called_once()
