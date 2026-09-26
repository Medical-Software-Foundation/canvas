"""Tests for the Twilio inbound webhook pure helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac

from appointment_reminders.services.twilio_inbound import (
    classify_consent,
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


def test_parse_form_body_preserves_empty_values():
    """Twilio signs key+"" for empty params; dropping them breaks the HMAC."""
    body = b"AccountSid=AC1&Body=Y&From=%2B15551230000&FromCity=&FromZip=&To=%2B15559990000"
    params = parse_form_body(body)
    assert params["FromCity"] == ""
    assert params["FromZip"] == ""
    assert len(params) == 6


def test_signature_valid_when_params_include_empty_values():
    """A signature computed over blanks must verify when blanks are preserved."""
    url = "https://example.com/hook"
    params = {"Body": "Y", "From": "+15551230000", "FromCity": "", "MessageSid": "SM1"}
    token = "test-token"
    data = url + "".join(k + params[k] for k in sorted(params))
    sig = base64.b64encode(
        hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()

    assert valid_twilio_signature(url, params, token, sig) is True
    # Dropping the blank, as form_data() did, must NOT verify.
    without_blank = {k: v for k, v in params.items() if v != ""}
    assert valid_twilio_signature(url, without_blank, token, sig) is False


# ---- classify_reply ----

def test_classify_confirm_variants() -> None:
    for body in ["Y", "y", "YES", "Yes", "  yes  ", "1", "confirm", "Confirmed", "Y."]:
        assert classify_reply(body) == "confirm", body


def test_classify_decline_variants() -> None:
    for body in ["N", "no", "NO", "2", "Decline", "declined"]:
        assert classify_reply(body) == "decline", body


def test_cancel_is_not_an_appointment_decline() -> None:
    """Twilio publishes CANCEL as an unsubscribe synonym, not an appointment word.

    A patient texting it means "stop texting me". Reading it as a decline would
    attribute an intent they never expressed — and open a reschedule Task off
    the back of it. Consent still clears; see classify_consent.
    """
    for body in ["cancel", "CANCEL", "Cancel"]:
        assert classify_reply(body) == "unrecognized", body
        assert classify_consent(body) == "opt_out", body


def test_classify_unrecognized() -> None:
    for body in ["", None, "maybe", "stop", "no problem, see you then",
                 "yes please, I have a question", "reschedule"]:
        assert classify_reply(body) == "unrecognized", body


# ---- classify_consent ----

def test_classify_opt_out_keywords() -> None:
    for body in ["STOP", "stop", " Stop ", "stop.", "STOPALL", "unsubscribe",
                 "CANCEL", "end", "QUIT", "revoke", "optout"]:
        assert classify_consent(body) == "opt_out", body


def test_classify_opt_in_keywords() -> None:
    for body in ["START", "start", "Yes", "YES", "unstop", "UNSTOP"]:
        assert classify_consent(body) == "opt_in", body


def test_classify_consent_ignores_everything_else() -> None:
    for body in ["", None, "Y", "N", "no", "confirm", "1", "2", "maybe",
                 "please cancel", "stop texting me about this"]:
        assert classify_consent(body) == "", body


def test_consent_and_reply_classification_are_independent() -> None:
    """A token carrying both meanings must register on both axes.

    YES is the case that needs it: the patient is opting back in *and*
    confirming. Collapsing the two into a single verdict would drop half of
    what they asked for.
    """
    assert (classify_consent("YES"), classify_reply("YES")) == ("opt_in", "confirm")
    # Opt-out/opt-in keywords that carry no appointment intent — CANCEL among
    # them, since it means "stop texting me" rather than anything about a visit.
    assert (classify_consent("STOP"), classify_reply("STOP")) == ("opt_out", "unrecognized")
    assert (classify_consent("CANCEL"), classify_reply("CANCEL")) == ("opt_out", "unrecognized")
    assert (classify_consent("START"), classify_reply("START")) == ("opt_in", "unrecognized")
    # Y/N carry no consent change.
    assert (classify_consent("Y"), classify_reply("Y")) == ("", "confirm")
    assert (classify_consent("N"), classify_reply("N")) == ("", "decline")
