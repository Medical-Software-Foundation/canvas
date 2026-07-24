"""Tests for notification delivery service."""
from unittest.mock import MagicMock

from pytest_mock import MockerFixture

from patient_notify.services.delivery import (
    DeliveryResult,
    _escape_html,
    _normalize_phone_e164,
    _plaintext_to_html,
    deliver_to_patient,
)


_TWILIO_SECRETS = {
    "twilio-account-sid": "AC123",
    "twilio-auth-token": "token123",
    "twilio-phone-number": "+15551234567",
}

_SENDGRID_SECRETS = {
    "sendgrid-api-key": "SG.test",
    "sendgrid-from-email": "noreply@clinic.com",
}

_ALL_SECRETS = {**_TWILIO_SECRETS, **_SENDGRID_SECRETS}


def _make_patient(
    phones: list[str] | None = None,
    emails: list[str] | None = None,
) -> MagicMock:
    """Create a mock patient with configurable contacts."""
    patient = MagicMock()
    patient.id = "patient-123"
    contacts = []
    for phone in (phones or []):
        c = MagicMock()
        c.system = "phone"
        c.value = phone
        contacts.append(c)
    for email in (emails or []):
        c = MagicMock()
        c.system = "email"
        c.value = email
        contacts.append(c)
    patient.telecom.filter.return_value = contacts
    return patient


# E.164 normalization tests


def test_normalize_phone_10_digits() -> None:
    """Test 10-digit number gets +1 prefix."""
    assert _normalize_phone_e164("5551234567") == "+15551234567"


def test_normalize_phone_11_digits() -> None:
    """Test 11-digit number starting with 1 gets + prefix."""
    assert _normalize_phone_e164("15551234567") == "+15551234567"


def test_normalize_phone_already_e164() -> None:
    """Test already formatted E.164 number."""
    assert _normalize_phone_e164("+15551234567") == "+15551234567"


def test_normalize_phone_with_formatting() -> None:
    """Test number with dashes and parens gets cleaned."""
    assert _normalize_phone_e164("(555) 123-4567") == "+15551234567"


def test_normalize_phone_invalid_short() -> None:
    """Test too-short number returns None."""
    assert _normalize_phone_e164("555123") is None


def test_normalize_phone_invalid_long() -> None:
    """Test too-long number returns None."""
    assert _normalize_phone_e164("155512345678") is None


# Direct SMS path tests


def test_sends_sms_when_keys_and_phone_available(mocker: MockerFixture) -> None:
    """Test SMS sent via Twilio when keys and phone are available."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"sid": "SM123"}
    mock_post = mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello SMS", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].channel == "sms"
    assert results[0].message_id == "SM123"
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "twilio.com" in call_args[0][0]
    assert call_args[1]["auth"] == ("AC123", "token123")
    # Verify E.164 normalization was applied
    assert call_args[1]["data"]["To"] == "+15551234567"


def test_sms_failure_returns_error_result(mocker: MockerFixture) -> None:
    """Test SMS failure captured in DeliveryResult."""
    mocker.patch(
        "patient_notify.services.delivery.requests.post",
        side_effect=Exception("Connection refused"),
    )

    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].channel == "sms"
    assert results[0].error is not None
    assert "Connection refused" in results[0].error


def test_skip_reason_no_phone() -> None:
    """Test skip reason logged when patient has no phone."""
    patient = _make_patient(phones=[], emails=["p@test.com"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms", "email"], "confirmation", _ALL_SECRETS,
    )

    sms_results = [r for r in results if r.channel == "sms"]
    assert len(sms_results) == 1
    assert sms_results[0].success is False
    assert sms_results[0].error is not None
    assert "no consented active phone number" in sms_results[0].error


def test_skip_reason_no_twilio_keys() -> None:
    """Test skip reason logged when Twilio keys are missing."""
    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", {},
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error is not None
    assert "Twilio credentials not configured" in results[0].error


def test_skip_reason_no_email() -> None:
    """Test skip reason logged when patient has no email."""
    patient = _make_patient(phones=["5551234567"], emails=[])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms", "email"], "confirmation", _ALL_SECRETS,
    )

    email_results = [r for r in results if r.channel == "email"]
    assert len(email_results) == 1
    assert email_results[0].success is False
    assert email_results[0].error is not None
    assert "no consented active email address" in email_results[0].error


def test_skip_reason_no_sendgrid_keys() -> None:
    """Test skip reason logged when SendGrid keys are missing."""
    patient = _make_patient(emails=["p@test.com"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["email"], "confirmation", {},
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error is not None
    assert "SendGrid credentials not configured" in results[0].error


def test_skip_reason_phone_normalization_fails() -> None:
    """Test skip reason when phone cannot be normalized to E.164."""
    patient = _make_patient(phones=["123"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error is not None
    assert "could not be normalized to E.164" in results[0].error


def test_skips_sms_when_channel_not_selected(mocker: MockerFixture) -> None:
    """Test no SMS when channels only includes email."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"X-Message-Id": "msg-1"}
    mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567"], emails=["p@test.com"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["email"], "confirmation", _ALL_SECRETS,
    )

    sms_results = [r for r in results if r.channel == "sms"]
    assert len(sms_results) == 0
    email_results = [r for r in results if r.channel == "email"]
    assert len(email_results) == 1


# Multi-contact tests


def test_sends_to_multiple_phones(mocker: MockerFixture) -> None:
    """Test SMS sent to all consented phone numbers."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"sid": "SM123"}
    mock_post = mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567", "5559876543"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 2
    assert all(r.success for r in results)
    assert mock_post.call_count == 2


def test_sends_to_multiple_emails(mocker: MockerFixture) -> None:
    """Test email sent to all consented email addresses."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"X-Message-Id": "msg-1"}
    mock_post = mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(emails=["a@test.com", "b@test.com"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["email"], "reminder", _ALL_SECRETS,
    )

    assert len(results) == 2
    assert all(r.success for r in results)
    assert mock_post.call_count == 2


def test_multi_contact_with_one_bad_phone(mocker: MockerFixture) -> None:
    """Test mixed result when one phone fails normalization."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"sid": "SM123"}
    mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567", "123"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is False
    assert results[1].error is not None
    assert "could not be normalized" in results[1].error


# Direct email path tests


def test_sends_email_when_keys_and_email_available(mocker: MockerFixture) -> None:
    """Test email sent via SendGrid when keys and email are available."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"X-Message-Id": "msg-abc"}
    mock_post = mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(emails=["p@test.com"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello Email</p>", ["email"], "reminder", _ALL_SECRETS,
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].channel == "email"
    assert results[0].message_id == "msg-abc"
    call_args = mock_post.call_args
    assert "sendgrid.com" in call_args[0][0]
    assert "Bearer SG.test" in call_args[1]["headers"]["Authorization"]


def test_email_failure_returns_error_result(mocker: MockerFixture) -> None:
    """Test email failure captured in DeliveryResult."""
    mocker.patch(
        "patient_notify.services.delivery.requests.post",
        side_effect=Exception("Timeout"),
    )

    patient = _make_patient(emails=["p@test.com"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["email"], "reminder", _ALL_SECRETS,
    )

    assert results[0].success is False
    assert results[0].channel == "email"
    assert results[0].error is not None
    assert "Timeout" in results[0].error


def test_email_subject_matches_campaign_type(mocker: MockerFixture) -> None:
    """Test email subject line maps to campaign type."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"X-Message-Id": "msg-1"}
    mock_post = mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(emails=["p@test.com"])

    for campaign, expected_subject in [
        ("confirmation", "Appointment Confirmation"),
        ("reminder", "Appointment Reminder"),
        ("noshow", "We Missed You"),
        ("cancellation", "Appointment Cancelled"),
    ]:
        mock_post.reset_mock()
        deliver_to_patient(
            patient, "sms", "<p>email</p>", ["email"], campaign, _ALL_SECRETS,
        )
        payload = mock_post.call_args[1]["json"]
        assert payload["subject"] == expected_subject


# Twilio error code surfacing tests


def test_twilio_known_error_code_returns_friendly_message(mocker: MockerFixture) -> None:
    """Test known Twilio error code mapped to friendly message."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"code": 21610, "message": "Attempt to send to unsubscribed recipient"}
    mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error_code == 21610
    assert results[0].error is not None
    assert "opted out" in results[0].error


def test_twilio_auth_error_20003_returns_credentials_message(mocker: MockerFixture) -> None:
    """Test Twilio auth error 20003 maps to credentials message, not raw 'invalid username'."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"code": 20003, "message": "Authentication Error - invalid username"}
    mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error_code == 20003
    assert results[0].error is not None
    assert "username" not in results[0].error
    assert "credentials" in results[0].error


def test_twilio_unknown_error_code_uses_twilio_message(mocker: MockerFixture) -> None:
    """Test unknown Twilio error code falls back to Twilio message."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"code": 99999, "message": "Some new error"}
    mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert results[0].success is False
    assert results[0].error_code == 99999
    assert results[0].error == "Some new error"


def test_twilio_non_json_error_response(mocker: MockerFixture) -> None:
    """Test non-JSON error response returns HTTP status."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500
    mock_resp.json.side_effect = Exception("Not JSON")
    mocker.patch("patient_notify.services.delivery.requests.post", return_value=mock_resp)

    patient = _make_patient(phones=["5551234567"])
    effects, results = deliver_to_patient(
        patient, "Hello", "<p>Hello</p>", ["sms"], "confirmation", _ALL_SECRETS,
    )

    assert results[0].success is False
    assert results[0].error is not None
    assert "HTTP 500" in results[0].error


# General tests


def test_returns_effects_and_results_tuple() -> None:
    """Test return type is a tuple of (effects, results)."""
    patient = _make_patient(phones=["5551234567"])
    result = deliver_to_patient(
        patient, "msg", "<p>msg</p>", ["sms"], "test", {},
    )

    assert isinstance(result, tuple)
    assert len(result) == 2
    effects, results = result
    assert isinstance(effects, list)
    assert isinstance(results, list)
    assert all(isinstance(r, DeliveryResult) for r in results)


def test_plaintext_to_html_wraps_paragraphs() -> None:
    """Test plain text with double newlines becomes separate p tags."""
    result = _plaintext_to_html("Hello world.\n\nSecond paragraph.")
    assert result == "<p>Hello world.</p><p>Second paragraph.</p>"


def test_plaintext_to_html_converts_single_newlines_to_br() -> None:
    """Test single newlines within a paragraph become br tags."""
    result = _plaintext_to_html("Line one.\nLine two.")
    assert result == "<p>Line one.<br>Line two.</p>"


def test_plaintext_to_html_passes_through_existing_html() -> None:
    """Test strings already containing HTML tags are returned as-is."""
    html = "<p>Already formatted</p>"
    assert _plaintext_to_html(html) == html

    br_html = "Line one<br>Line two"
    assert _plaintext_to_html(br_html) == br_html


def test_plaintext_to_html_escapes_special_chars() -> None:
    """Test HTML special characters are escaped."""
    result = _plaintext_to_html("Use <b> tags & \"quotes\"")
    assert "&lt;b&gt;" in result
    assert "&amp;" in result


def test_escape_html_all_entities() -> None:
    """Test all five XML entity replacements."""
    result = _escape_html('Tom & Jerry <"rock \'n roll">')
    assert result == "Tom &amp; Jerry &lt;&quot;rock &#x27;n roll&quot;&gt;"


def test_escape_html_no_double_escape() -> None:
    """Test that ampersands are not double-escaped."""
    assert _escape_html("&amp;") == "&amp;amp;"


def test_escape_html_plain_text_unchanged() -> None:
    """Test that text without special characters passes through."""
    assert _escape_html("Hello world") == "Hello world"
