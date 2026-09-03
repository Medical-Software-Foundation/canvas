"""Tests for services/delivery.py — Twilio/SendGrid wiring + skip semantics.

Network calls (`requests.post`) are always mocked. Pure helpers (phone
normalization, error parsing, secret detection) are tested directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from appointment_reminders.services.config import CampaignConfig
from appointment_reminders.services.delivery import (
    DeliveryResult,
    _build_metadata_effects,
    _get_patient_contacts,
    _has_direct_email_keys,
    _has_direct_sms_keys,
    _normalize_phone,
    _parse_twilio_error,
    _patient_allowlisted,
    _recipient_allowlisted,
    _send_email,
    _send_sms,
    is_testing_mode_active,
    _twilio_auth,
    deliver_to_patient,
)


# ---- _normalize_phone ----

def test_normalize_phone_10_digit_us() -> None:
    assert _normalize_phone("4155551234") == "+14155551234"


def test_normalize_phone_with_formatting() -> None:
    assert _normalize_phone("(415) 555-1234") == "+14155551234"


def test_normalize_phone_11_digit_with_leading_one() -> None:
    assert _normalize_phone("14155551234") == "+14155551234"


def test_normalize_phone_already_e164() -> None:
    assert _normalize_phone("+14155551234") == "+14155551234"


def test_normalize_phone_other_country() -> None:
    """7-digit numbers — neither US 10-digit nor E.164 — get a leading +."""
    assert _normalize_phone("5551234").startswith("+")


def test_normalize_phone_empty_returns_input() -> None:
    assert _normalize_phone("") == ""
    assert _normalize_phone("abcdef") == "abcdef"


# ---- _has_direct_sms_keys / _has_direct_email_keys ----

def test_has_direct_sms_keys_all_present() -> None:
    assert _has_direct_sms_keys({
        "twilio-account-sid": "AC...",
        "twilio-auth-token": "tok",
        "twilio-phone-number": "+1...",
    }) is True


def test_has_direct_sms_keys_missing_one_key() -> None:
    assert _has_direct_sms_keys({
        "twilio-account-sid": "AC...",
        "twilio-auth-token": "tok",
    }) is False


def test_has_direct_sms_keys_empty_string_counts_as_missing() -> None:
    assert _has_direct_sms_keys({
        "twilio-account-sid": "",
        "twilio-auth-token": "tok",
        "twilio-phone-number": "+1",
    }) is False


def test_has_direct_sms_keys_api_key_without_auth_token() -> None:
    # An API key pair is a valid auth path even with no master Auth Token.
    assert _has_direct_sms_keys({
        "twilio-account-sid": "AC...",
        "twilio-phone-number": "+1...",
        "twilio-api-key-sid": "SK...",
        "twilio-api-key-secret": "secret",
    }) is True


def test_has_direct_sms_keys_no_auth_path_is_false() -> None:
    # Account SID + phone but neither a token nor a complete API key pair.
    assert _has_direct_sms_keys({
        "twilio-account-sid": "AC...",
        "twilio-phone-number": "+1...",
        "twilio-api-key-sid": "SK...",  # secret missing → incomplete
    }) is False


# ---- _twilio_auth ----

def test_twilio_auth_prefers_api_key() -> None:
    auth = _twilio_auth({
        "twilio-account-sid": "AC1",
        "twilio-auth-token": "tok",
        "twilio-api-key-sid": "SK1",
        "twilio-api-key-secret": "sec",
    })
    assert auth == ("SK1", "sec")


def test_twilio_auth_falls_back_to_account_token() -> None:
    auth = _twilio_auth({"twilio-account-sid": "AC1", "twilio-auth-token": "tok"})
    assert auth == ("AC1", "tok")


def test_twilio_auth_ignores_partial_api_key() -> None:
    # Only a key SID, no secret → not a usable pair; fall back to token.
    auth = _twilio_auth({
        "twilio-account-sid": "AC1",
        "twilio-auth-token": "tok",
        "twilio-api-key-sid": "SK1",
    })
    assert auth == ("AC1", "tok")


def test_has_direct_email_keys_all_present() -> None:
    assert _has_direct_email_keys({
        "sendgrid-api-key": "SG.x",
        "sendgrid-from-email": "noreply@example.com",
    }) is True


def test_has_direct_email_keys_missing() -> None:
    assert _has_direct_email_keys({"sendgrid-api-key": "SG.x"}) is False


# ---- _parse_twilio_error ----

def test_parse_twilio_error_known_code_returns_friendly_message() -> None:
    response = MagicMock()
    response.json.return_value = {"code": 21610, "message": "Stop"}
    assert "opted out" in _parse_twilio_error(response)


def test_parse_twilio_error_unknown_code_falls_back_to_twilio_message() -> None:
    response = MagicMock()
    response.json.return_value = {"code": 99999, "message": "weird error"}
    response.status_code = 400
    assert "weird error" in _parse_twilio_error(response)


def test_parse_twilio_error_no_response_returns_generic() -> None:
    assert _parse_twilio_error(None) == "SMS delivery failed"


def test_parse_twilio_error_invalid_json_falls_back_to_status_code() -> None:
    response = MagicMock()
    response.json.side_effect = ValueError("bad json")
    response.status_code = 500
    msg = _parse_twilio_error(response)
    assert "500" in msg


# ---- _send_sms ----

def test_send_sms_success() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"sid": "SM123"}
    mock_response.raise_for_status.return_value = None
    with patch(
        "appointment_reminders.services.delivery.requests.post",
        return_value=mock_response,
    ) as mock_post:
        result = _send_sms("+14155551234", "hi", "AC...", ("SK1", "sec"), "+1800")
    assert result.success is True
    assert result.message_id == "SM123"
    mock_post.assert_called_once()
    # Account SID builds the URL; the auth pair is forwarded verbatim (API key here).
    _, kwargs = mock_post.call_args
    assert kwargs["auth"] == ("SK1", "sec")
    assert "Accounts/AC.../Messages.json" in mock_post.call_args.args[0]


def test_send_sms_http_error_uses_parse_twilio_error() -> None:
    import requests as requests_lib

    mock_response = MagicMock()
    mock_response.json.return_value = {"code": 21610, "message": "stop"}
    err = requests_lib.exceptions.HTTPError(response=mock_response)
    err.response = mock_response

    def raise_http():
        raise err

    mock_response.raise_for_status.side_effect = raise_http
    with patch(
        "appointment_reminders.services.delivery.requests.post",
        return_value=mock_response,
    ):
        result = _send_sms("+14155551234", "hi", "AC", ("AC", "tok"), "+1800")
    assert result.success is False
    assert "opted out" in (result.error or "")


def test_send_sms_network_error_caught() -> None:
    import requests
    with patch(
        "appointment_reminders.services.delivery.requests.post",
        side_effect=requests.exceptions.ConnectionError("DNS failure"),
    ):
        result = _send_sms("+14155551234", "hi", "AC", ("AC", "tok"), "+1800")
    assert result.success is False
    assert "DNS failure" in (result.error or "")


# ---- _send_email ----

def test_send_email_success_extracts_message_id_header() -> None:
    mock_response = MagicMock()
    mock_response.headers = {"X-Message-Id": "msg-1"}
    mock_response.raise_for_status.return_value = None
    with patch(
        "appointment_reminders.services.delivery.requests.post",
        return_value=mock_response,
    ):
        result = _send_email(
            "to@example.com", "subj", "<p>body</p>", "SG.x", "from@example.com"
        )
    assert result.success is True
    assert result.message_id == "msg-1"


def test_send_email_failure_caught() -> None:
    import requests
    with patch(
        "appointment_reminders.services.delivery.requests.post",
        side_effect=requests.exceptions.RequestException("boom"),
    ):
        result = _send_email("to@example.com", "subj", "body", "SG.x", "from@example.com")
    assert result.success is False
    assert result.error == "boom"


# ---- _get_patient_contacts ----

def _contact(system, value, *, rank=0, has_consent=True, opted_out=False):
    c = MagicMock()
    c.system = system
    c.value = value
    c.rank = rank
    c.has_consent = has_consent
    c.opted_out = opted_out
    return c


def _patient_with_contacts(phone_value: str | None, email_value: str | None) -> MagicMock:
    """Build a Patient mock whose ``telecom.all()`` returns contact rows.

    Mirrors ``_get_patient_contacts`` in-Python selection: SMS requires
    has_consent=True; email only requires not opted_out.
    """
    patient = MagicMock()
    contacts = []
    if phone_value:
        contacts.append(_contact("phone", phone_value, rank=0, has_consent=True))
    if email_value:
        contacts.append(_contact("email", email_value, rank=1, has_consent=True))
    patient.telecom.all.return_value = contacts
    return patient


def test_get_patient_contacts_both() -> None:
    patient = _patient_with_contacts("4155551234", "p@example.com")
    phone, email = _get_patient_contacts(patient)
    assert phone == "+14155551234"
    assert email == "p@example.com"


def test_get_patient_contacts_neither() -> None:
    patient = _patient_with_contacts(None, None)
    assert _get_patient_contacts(patient) == (None, None)


def test_get_patient_contacts_email_does_not_require_has_consent() -> None:
    """Regression: the Canvas chart UI exposes no per-email consent toggle.

    An email row with has_consent=False must still be delivered to (only
    opted_out=True suppresses email). Phone, by contrast, still gates on
    has_consent=True for TCPA compliance.
    """
    patient = MagicMock()
    patient.telecom.all.return_value = [
        _contact("phone", "4155551234", has_consent=False),  # excluded: no consent
        _contact("email", "x@y.com", has_consent=False),     # included: email is implicit
    ]

    phone, email = _get_patient_contacts(patient)
    assert phone is None
    assert email == "x@y.com"


def test_get_patient_contacts_filters_by_not_opted_out() -> None:
    """Regression: opted_out=True must suppress both phone and email."""
    patient = MagicMock()
    patient.telecom.all.return_value = [
        _contact("phone", "4155551234", opted_out=True),
        _contact("email", "x@y.com", opted_out=True),
    ]

    phone, email = _get_patient_contacts(patient)
    assert phone is None
    assert email is None


# ---- _build_metadata_effects ----

def test_build_metadata_effects_records_status_per_channel() -> None:
    results = [
        DeliveryResult(success=True, channel="sms", message_id="SM1"),
        DeliveryResult(success=False, channel="email", error="boom"),
        DeliveryResult(success=False, channel="sms", error="skipped:no_phone_on_file"),
    ]
    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta:
        mock_meta.return_value.upsert.return_value = MagicMock()
        effects = _build_metadata_effects("appt-1", "reminder", results)
    # Three results → three effects
    assert len(effects) == 3
    # Inspect the values passed to upsert
    upserts = [c.kwargs.get("value", c.args[0] if c.args else "")
               for c in mock_meta.return_value.upsert.call_args_list]
    # "accepted|", not "delivered|" — the metadata records that the provider
    # took the request, which is all the plugin can observe.
    assert any(v.startswith("accepted|") for v in upserts)
    assert not any(v.startswith("delivered|") for v in upserts)
    assert any(v.startswith("failed|") for v in upserts)
    assert any(v.startswith("skipped|") for v in upserts)


def test_build_metadata_effects_truncates_long_value_to_256() -> None:
    """Twilio errors can be long — value must fit within the 256-char metadata cap."""
    long_error = "X" * 1000
    results = [DeliveryResult(success=False, channel="sms", error=long_error)]
    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta:
        mock_meta.return_value.upsert.return_value = MagicMock()
        _build_metadata_effects("appt-1", "reminder", results)
    upsert_value = mock_meta.return_value.upsert.call_args.kwargs.get(
        "value", mock_meta.return_value.upsert.call_args.args[0]
        if mock_meta.return_value.upsert.call_args.args else ""
    )
    assert len(upsert_value) == 256


# ---- deliver_to_patient ----

@pytest.fixture
def _full_secrets() -> dict[str, str]:
    return {
        "twilio-account-sid": "AC1",
        "twilio-auth-token": "tok",
        "twilio-phone-number": "+18001112222",
        "sendgrid-api-key": "SG.x",
        "sendgrid-from-email": "noreply@example.com",
    }


def _cfg(testing_mode: bool = False, patients=None, recipients=None) -> CampaignConfig:
    """Config for a delivery call.

    Testing mode defaults OFF here so the ordinary delivery tests exercise the
    sending path. Note this inverts the *product* default, which is ON — see
    test_testing_mode_defaults_on.
    """
    return CampaignConfig(
        testing_mode=testing_mode,
        testing_mode_patients=patients or [],
        testing_mode_recipients=recipients or [],
    )


def test_deliver_to_patient_uses_from_number_override(_full_secrets) -> None:
    """A per-business-line from_number overrides the global Twilio number."""
    patient = _patient_with_contacts("4155551234", None)
    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_sms",
        return_value=DeliveryResult(success=True, channel="sms", message_id="SM1"),
    ) as mock_send:
        mock_meta.return_value.upsert.return_value = MagicMock()
        deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="",
            channels=["sms"],
            campaign_type="reminder",
            secrets=_full_secrets,
            appointment_id="appt-1",
            from_number="+15555550199",
            config=_cfg(),
        )
    assert mock_send.call_args.kwargs["from_number"] == "+15555550199"


def test_deliver_to_patient_falls_back_to_global_from_number(_full_secrets) -> None:
    """With no override, SMS sends from the global twilio-phone-number secret."""
    patient = _patient_with_contacts("4155551234", None)
    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_sms",
        return_value=DeliveryResult(success=True, channel="sms", message_id="SM1"),
    ) as mock_send:
        mock_meta.return_value.upsert.return_value = MagicMock()
        deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="",
            channels=["sms"],
            campaign_type="reminder",
            secrets=_full_secrets,
            appointment_id="appt-1",
            config=_cfg(),
        )
    assert mock_send.call_args.kwargs["from_number"] == "+18001112222"


def test_deliver_to_patient_skips_sms_when_keys_missing(_full_secrets) -> None:
    patient = _patient_with_contacts("4155551234", "p@example.com")
    secrets = {k: v for k, v in _full_secrets.items() if not k.startswith("twilio")}

    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_email",
        return_value=DeliveryResult(success=True, channel="email", message_id="m1"),
    ):
        mock_meta.return_value.upsert.return_value = MagicMock()
        effects, results = deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="email",
            channels=["sms", "email"],
            campaign_type="reminder",
            secrets=secrets,
            appointment_id="appt-1",
            config=_cfg(),
        )

    sms_result = next(r for r in results if r.channel == "sms")
    assert sms_result.success is False
    assert sms_result.error == "skipped:twilio_keys_not_configured"


def test_deliver_to_patient_skips_sms_when_no_phone(_full_secrets) -> None:
    patient = _patient_with_contacts(None, "p@example.com")

    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_email",
        return_value=DeliveryResult(success=True, channel="email", message_id="m1"),
    ):
        mock_meta.return_value.upsert.return_value = MagicMock()
        _effects, results = deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="email",
            channels=["sms", "email"],
            campaign_type="reminder",
            secrets=_full_secrets,
            appointment_id="appt-1",
            config=_cfg(),
        )

    sms_result = next(r for r in results if r.channel == "sms")
    assert sms_result.error == "skipped:no_phone_on_file"


def test_deliver_to_patient_skips_email_when_keys_missing(_full_secrets) -> None:
    patient = _patient_with_contacts("4155551234", "p@example.com")
    secrets = {k: v for k, v in _full_secrets.items() if not k.startswith("sendgrid")}

    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_sms",
        return_value=DeliveryResult(success=True, channel="sms", message_id="SM1"),
    ):
        mock_meta.return_value.upsert.return_value = MagicMock()
        _effects, results = deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="email",
            channels=["sms", "email"],
            campaign_type="reminder",
            secrets=secrets,
            appointment_id="appt-1",
            config=_cfg(),
        )

    email_result = next(r for r in results if r.channel == "email")
    assert email_result.error == "skipped:sendgrid_keys_not_configured"


def test_deliver_to_patient_skips_email_when_no_email_on_file(_full_secrets) -> None:
    patient = _patient_with_contacts("4155551234", None)

    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_sms",
        return_value=DeliveryResult(success=True, channel="sms", message_id="SM1"),
    ):
        mock_meta.return_value.upsert.return_value = MagicMock()
        _effects, results = deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="email",
            channels=["sms", "email"],
            campaign_type="reminder",
            secrets=_full_secrets,
            appointment_id="appt-1",
            config=_cfg(),
        )

    email_result = next(r for r in results if r.channel == "email")
    assert email_result.error == "skipped:no_email_on_file"


def test_deliver_to_patient_no_appointment_id_returns_no_metadata_effects(_full_secrets) -> None:
    """Direct messages and form reminders without an appointment shouldn't
    produce AppointmentsMetadata effects."""
    patient = _patient_with_contacts("4155551234", "p@example.com")
    with patch(
        "appointment_reminders.services.delivery._send_sms",
        return_value=DeliveryResult(success=True, channel="sms", message_id="SM1"),
    ), patch(
        "appointment_reminders.services.delivery._send_email",
        return_value=DeliveryResult(success=True, channel="email", message_id="m1"),
    ):
        effects, results = deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="email",
            channels=["sms", "email"],
            campaign_type="message_notification",
            secrets=_full_secrets,
            appointment_id="",
            config=_cfg(),
        )
    assert effects == []
    assert len(results) == 2


def test_deliver_to_patient_sms_failure_logs_warning(_full_secrets) -> None:
    """The SMS-failure branch is exercised when _send_sms returns a failed result."""
    patient = _patient_with_contacts("4155551234", "p@example.com")

    with patch(
        "appointment_reminders.services.delivery.AppointmentsMetadata"
    ) as mock_meta, patch(
        "appointment_reminders.services.delivery._send_sms",
        return_value=DeliveryResult(success=False, channel="sms", error="boom"),
    ), patch(
        "appointment_reminders.services.delivery._send_email",
        return_value=DeliveryResult(success=False, channel="email", error="boom"),
    ):
        mock_meta.return_value.upsert.return_value = MagicMock()
        _effects, results = deliver_to_patient(
            patient,
            sms_content="sms",
            email_content="email",
            channels=["sms", "email"],
            campaign_type="reminder",
            secrets=_full_secrets,
            appointment_id="appt-1",
            config=_cfg(),
        )
    # Both sends failed but we still got results back
    assert len(results) == 2
    assert all(r.success is False for r in results)


# ---- testing mode gate (safe-launch / troubleshooting allowlist) ----

def test_is_testing_mode_active_reads_the_config() -> None:
    assert is_testing_mode_active(CampaignConfig(testing_mode=True)) is True
    assert is_testing_mode_active(CampaignConfig(testing_mode=False)) is False


def test_testing_mode_defaults_on() -> None:
    """Fail closed by default.

    A fresh install, and one upgrading from the old TESTING_MODE secret, must
    both land with the gate shut rather than silently broadcasting to every
    patient. With both allowlists empty that means nothing sends at all.
    """
    assert CampaignConfig().testing_mode is True
    assert CampaignConfig().testing_mode_patients == []
    assert CampaignConfig().testing_mode_recipients == []


def test_is_testing_mode_active_assumes_on_when_the_field_is_absent() -> None:
    """An object predating the field must not read as an open gate."""
    class Old:
        pass

    assert is_testing_mode_active(Old()) is True


def test_recipient_allowlisted_phone_normalized_and_email_ci() -> None:
    allow = {"+14155551234", "Test@Example.com"}
    assert _recipient_allowlisted("4155551234", "sms", allow) is True   # normalized match
    assert _recipient_allowlisted("+19998887777", "sms", allow) is False
    assert _recipient_allowlisted("test@example.com", "email", allow) is True  # case-insensitive
    assert _recipient_allowlisted("x@example.com", "email", allow) is False
    assert _recipient_allowlisted("4155551234", "sms", set()) is False  # empty ⇒ fail-closed


def _allowlist_patient(pid="pat-1", dbid=42, mrn="900000001") -> MagicMock:
    """A patient carrying the three identifiers the allowlist accepts.

    `spec=` matters: a bare MagicMock answers every getattr, so a lookup of a
    field the model does not have would appear to succeed. That is how the dead
    `key` branch survived — a mock happily returned p.key even though
    Patient.id is declared CharField(db_column="key") and `.key` never existed.
    """
    p = MagicMock(spec=["id", "dbid", "mrn"])
    p.id, p.dbid, p.mrn = pid, dbid, mrn
    return p


def test_patient_allowlisted_matches_any_identifier() -> None:
    p = _allowlist_patient()
    assert _patient_allowlisted(p, {"pat-1"}) is True        # chart-URL id
    assert _patient_allowlisted(p, {"42"}) is True           # internal dbid
    assert _patient_allowlisted(p, {"900000001"}) is True    # MRN
    assert _patient_allowlisted(p, {"nope"}) is False
    assert _patient_allowlisted(p, set()) is False


def test_patient_allowlisted_accepts_an_mrn() -> None:
    """MRN is what staff see and quote, so it is the likeliest paste.

    It used to match nothing, and the failure was silent: every send skipped
    with `skipped:testing_mode`, indistinguishable from a gate working as
    configured. Reproduced against a live instance, where a patient's undashed
    32-character id and their 9-digit MRN are different strings and only the id
    matched. The values below are synthetic and carry that same shape.
    """
    p = _allowlist_patient(pid="0" * 32, mrn="900000001")
    assert _patient_allowlisted(p, {"900000001"}) is True


def test_patient_allowlisted_tolerates_a_missing_or_blank_mrn() -> None:
    """Not every patient has one, and a blank must not match a blank entry."""
    p = MagicMock(spec=["id", "dbid", "mrn"])
    p.id, p.dbid, p.mrn = "pat-1", 42, None
    assert _patient_allowlisted(p, {"pat-1"}) is True
    assert _patient_allowlisted(p, {""}) is False

    without = MagicMock(spec=["id", "dbid"])
    without.id, without.dbid = "pat-1", 42
    assert _patient_allowlisted(without, {"pat-1"}) is True


def test_patient_allowlisted_does_not_consult_a_key_attribute() -> None:
    """Regression: the `key` lookup was dead code, and the old test asserted it.

    Patient.id is CharField(db_column="key"), so the attribute is `id` and
    `.key` does not exist. Anything relying on it only ever worked against a
    permissive mock.
    """
    p = MagicMock(spec=["id", "dbid", "mrn", "key"])
    p.id, p.dbid, p.mrn, p.key = "pat-1", 42, "900000001", "KEYX"
    assert _patient_allowlisted(p, {"KEYX"}) is False


def _deliver_sms(patient, secrets, config):
    with patch("appointment_reminders.services.delivery.AppointmentsMetadata") as mm, \
         patch("appointment_reminders.services.delivery._send_sms",
               return_value=DeliveryResult(success=True, channel="sms", message_id="SM1")) as ms:
        mm.return_value.upsert.return_value = MagicMock()
        _, results = deliver_to_patient(
            patient, sms_content="hi", email_content="", channels=["sms"],
            campaign_type="confirmation", secrets=secrets, appointment_id="a1",
            config=config)
    return ms, results


def test_testing_mode_sends_when_patient_and_recipient_allowlisted(_full_secrets) -> None:
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    ms, results = _deliver_sms(p, _full_secrets, _cfg(
        True, patients=["pat-1"], recipients=["+14155551234"]))
    ms.assert_called_once()
    assert results[0].success is True


def test_testing_mode_blocks_when_recipient_not_allowlisted(_full_secrets) -> None:
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    ms, results = _deliver_sms(p, _full_secrets, _cfg(
        True, patients=["pat-1"], recipients=["+19998887777"]))
    ms.assert_not_called()
    assert results[0].error == "skipped:testing_mode"


def test_testing_mode_blocks_when_patient_not_allowlisted(_full_secrets) -> None:
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    ms, results = _deliver_sms(p, _full_secrets, _cfg(
        True, patients=["someone-else"], recipients=["+14155551234"]))
    ms.assert_not_called()
    assert results[0].error == "skipped:testing_mode"


def test_testing_mode_fail_closed_when_allowlists_empty(_full_secrets) -> None:
    """The default state of a fresh install: on, with nothing allowlisted."""
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    ms, results = _deliver_sms(p, _full_secrets, _cfg(True))
    ms.assert_not_called()
    assert results[0].error == "skipped:testing_mode"


def test_testing_mode_off_ignores_allowlists(_full_secrets) -> None:
    # Allowlists present but mode off ⇒ normal send (gate inactive).
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    ms, results = _deliver_sms(p, _full_secrets, _cfg(
        False, patients=["nobody"], recipients=["+19998887777"]))
    ms.assert_called_once()
    assert results[0].success is True


def test_testing_mode_tolerates_allowlists_stored_as_text(_full_secrets) -> None:
    """A hand-edited config row may hold the lists as comma/newline text."""
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    config = CampaignConfig.from_dict({
        "testing_mode": True,
        "testing_mode_patients": "pat-1, other",
        "testing_mode_recipients": "+14155551234\n+19998887777",
    })
    ms, results = _deliver_sms(p, _full_secrets, config)
    ms.assert_called_once()
    assert results[0].success is True


def test_testing_mode_gates_email_channel(_full_secrets) -> None:
    # Patient allowlisted + phone allowlisted, but the EMAIL address is not ⇒ email blocked.
    p = _patient_with_contacts(None, "pt@example.com"); p.id = "pat-1"
    with patch("appointment_reminders.services.delivery.AppointmentsMetadata") as mm, \
         patch("appointment_reminders.services.delivery._send_email") as me:
        mm.return_value.upsert.return_value = MagicMock()
        _, results = deliver_to_patient(
            p, sms_content="", email_content="e", channels=["email"],
            campaign_type="confirmation", secrets=_full_secrets, appointment_id="a1",
            config=_cfg(True, patients=["pat-1"], recipients=["+14155551234"]))
    me.assert_not_called()
    assert results[0].error == "skipped:testing_mode"


def test_passing_config_avoids_a_per_delivery_config_read(_full_secrets) -> None:
    """Callers hand over the config they already hold.

    Falling back to load_config() here would be one query per patient inside
    the reminder cron's loop, which is why every call site passes it.
    """
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    with patch("appointment_reminders.services.delivery.load_config") as mock_load:
        _deliver_sms(p, _full_secrets, _cfg())
    mock_load.assert_not_called()


def test_omitting_config_falls_back_to_loading_it(_full_secrets) -> None:
    """The fallback still has to work — and still has to fail closed."""
    p = _patient_with_contacts("4155551234", None); p.id = "pat-1"
    with patch("appointment_reminders.services.delivery.load_config",
               return_value=CampaignConfig()) as mock_load, \
         patch("appointment_reminders.services.delivery.AppointmentsMetadata") as mm, \
         patch("appointment_reminders.services.delivery._send_sms") as ms:
        mm.return_value.upsert.return_value = MagicMock()
        _, results = deliver_to_patient(
            p, sms_content="hi", email_content="", channels=["sms"],
            campaign_type="confirmation", secrets=_full_secrets, appointment_id="a1")

    mock_load.assert_called_once()
    ms.assert_not_called()  # default config has testing mode on, allowlists empty
    assert results[0].error == "skipped:testing_mode"
