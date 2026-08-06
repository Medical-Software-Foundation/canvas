"""Tests for the Twilio inbound webhook pure helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac

from appointment_reminders.services.twilio_inbound import (
    classify_reply,
    parse_form_body,
    valid_twilio_signature,
)


def _sign(url: str, params: dict[str, str], token: str) -> str:
    """Independent reference implementation of Twilio's signing algorithm."""
    data = url
    for key in sorted(params):
        data += key + params[key]
    return base64.b64encode(
        hmac.new(token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode()


# ---- parse_form_body ----

def test_parse_form_body_bytes() -> None:
    result = parse_form_body(b"From=%2B14155551234&Body=Y&To=%2B18005551000")
    assert result == {"From": "+14155551234", "Body": "Y", "To": "+18005551000"}


def test_parse_form_body_str() -> None:
    assert parse_form_body("Body=YES")["Body"] == "YES"


def test_parse_form_body_none_returns_empty() -> None:
    assert parse_form_body(None) == {}


def test_parse_form_body_keeps_blank_values() -> None:
    assert parse_form_body("Body=") == {"Body": ""}


# ---- valid_twilio_signature ----

_URL = "https://x.canvasmedical.com/plugin-io/api/appointment_reminders/twilio/inbound"
_PARAMS = {"From": "+14155551234", "To": "+18005551000", "Body": "Y"}
_TOKEN = "test-auth-token"


def test_valid_signature_accepts_correct() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert valid_twilio_signature(_URL, _PARAMS, _TOKEN, sig) is True


def test_valid_signature_rejects_tampered_body() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    tampered = dict(_PARAMS, Body="N")  # attacker flips the reply
    assert valid_twilio_signature(_URL, tampered, _TOKEN, sig) is False


def test_valid_signature_rejects_wrong_token() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert valid_twilio_signature(_URL, _PARAMS, "other-token", sig) is False


def test_valid_signature_fails_closed_without_token() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert valid_twilio_signature(_URL, _PARAMS, "", sig) is False


def test_valid_signature_fails_closed_without_url() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert valid_twilio_signature("", _PARAMS, _TOKEN, sig) is False


def test_valid_signature_fails_closed_without_signature() -> None:
    assert valid_twilio_signature(_URL, _PARAMS, _TOKEN, None) is False


# ---- classify_reply ----

def test_classify_confirm_variants() -> None:
    for body in ["Y", "y", "YES", "Yes", "  yes  ", "1", "confirm", "Confirmed", "Y."]:
        assert classify_reply(body) == "confirm", body


def test_classify_decline_variants() -> None:
    for body in ["N", "no", "NO", "2", "cancel", "Decline"]:
        assert classify_reply(body) == "decline", body


def test_classify_unrecognized() -> None:
    for body in ["", None, "maybe", "stop", "no problem, see you then",
                 "yes please, I have a question", "reschedule"]:
        assert classify_reply(body) == "unrecognized", body
