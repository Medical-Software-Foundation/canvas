"""Tests for the inbound-webhook routing check.

The bias under test is that UNKNOWN is preferred over NOT_ROUTED whenever Twilio
cannot settle the question. A false "replies are being dropped" on a healthy
install would train people to ignore the warning, which costs more than the
warning is worth.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from appointment_reminders.services.twilio_routing import (
    NOT_ROUTED,
    ROUTED,
    UNKNOWN,
    describe,
    inbound_webhook_status,
)

_MOD = "appointment_reminders.services.twilio_routing"
_URL = "https://x.canvasmedical.com/plugin-io/api/appointment_reminders/twilio/inbound"

_SECRETS = {
    "twilio-account-sid": "AC1",
    "twilio-auth-token": "tok",
    "twilio-phone-number": "+15555550100",
    "twilio-inbound-webhook-url": _URL,
}


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value, timeout_seconds=None):
        self.store[key] = value


def _resp(status_code=200, payload=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload if payload is not None else {}
    return r


def _run(number_resp, service_resp=None, cache=None):
    """Drive the check with stubbed Twilio responses."""
    def _http(base_url=""):
        client = MagicMock()
        client.get.return_value = (
            number_resp if "api.twilio.com" in base_url else service_resp or _resp()
        )
        return client

    with patch(f"{_MOD}.get_cache", return_value=cache or _FakeCache()), \
         patch(f"{_MOD}.Http", side_effect=_http):
        return inbound_webhook_status(dict(_SECRETS))


def _number(sms_url=None, sms_application_sid=None, phone="+15555550100"):
    return _resp(200, {"incoming_phone_numbers": [{
        "phone_number": phone,
        "sms_url": sms_url,
        "sms_application_sid": sms_application_sid,
    }]})


def test_routed_when_the_number_points_at_the_plugin() -> None:
    assert _run(_number(sms_url=_URL)) == ROUTED


def test_not_routed_when_the_numbers_webhook_is_cleared() -> None:
    """The failure that actually happened: webhook removed, sends still fine."""
    assert _run(_number(sms_url=""), _resp(200, {"services": []})) == NOT_ROUTED
    assert _run(_number(sms_url=None), _resp(200, {"services": []})) == NOT_ROUTED


def test_not_routed_when_the_webhook_points_somewhere_else() -> None:
    assert _run(
        _number(sms_url="https://elsewhere.example.com/hook"),
        _resp(200, {"services": []}),
    ) == NOT_ROUTED


def test_routed_via_a_messaging_service() -> None:
    """The arrangement the README recommends: dedicated number in its own service."""
    services = _resp(200, {"services": [
        {"inbound_request_url": _URL, "use_inbound_webhook_on_number": False},
    ]})
    assert _run(_number(sms_url=""), services) == ROUTED


def test_messaging_service_ignored_when_the_number_overrides_it() -> None:
    """use_inbound_webhook_on_number means the number's webhook wins, and the
    number's webhook is empty — so replies really are dropped."""
    services = _resp(200, {"services": [
        {"inbound_request_url": _URL, "use_inbound_webhook_on_number": True},
    ]})
    assert _run(_number(sms_url=""), services) == NOT_ROUTED


def test_unknown_when_a_twiml_app_governs_the_number() -> None:
    """Twilio ignores every sms_*_url when an application SID is set."""
    assert _run(_number(sms_url="", sms_application_sid="AP123")) == UNKNOWN


def test_unknown_when_the_number_is_not_in_this_account() -> None:
    """Hosted numbers and short codes do not appear, so absence proves nothing."""
    assert _run(_resp(200, {"incoming_phone_numbers": []})) == UNKNOWN


def test_unknown_on_a_twilio_error_or_outage() -> None:
    for code in (401, 403, 429, 500):
        assert _run(_resp(code)) == UNKNOWN, code


def test_unknown_when_the_request_raises() -> None:
    def _boom(base_url=""):
        client = MagicMock()
        client.get.side_effect = RuntimeError("connection reset")
        return client

    with patch(f"{_MOD}.get_cache", return_value=_FakeCache()), \
         patch(f"{_MOD}.Http", side_effect=_boom):
        assert inbound_webhook_status(dict(_SECRETS)) == UNKNOWN


def test_not_routed_without_a_configured_webhook_url_and_no_api_call() -> None:
    """No URL means the signature check fails closed on every request anyway."""
    secrets = dict(_SECRETS, **{"twilio-inbound-webhook-url": ""})
    with patch(f"{_MOD}.get_cache", return_value=_FakeCache()), \
         patch(f"{_MOD}.Http") as mock_http:
        assert inbound_webhook_status(secrets) == NOT_ROUTED
    mock_http.assert_not_called()


def test_unknown_without_credentials_to_ask_with() -> None:
    for missing in ("twilio-account-sid", "twilio-phone-number"):
        secrets = dict(_SECRETS, **{missing: ""})
        with patch(f"{_MOD}.get_cache", return_value=_FakeCache()), \
             patch(f"{_MOD}.Http") as mock_http:
            assert inbound_webhook_status(secrets) == UNKNOWN, missing
        mock_http.assert_not_called()


def test_result_is_cached_so_the_admin_page_does_not_call_twilio_each_load() -> None:
    """The SDK HTTP client enforces a fixed 30s timeout with no override."""
    cache = _FakeCache()
    calls = []

    def _http(base_url=""):
        client = MagicMock()
        calls.append(base_url)
        client.get.return_value = _number(sms_url=_URL)
        return client

    with patch(f"{_MOD}.get_cache", return_value=cache), \
         patch(f"{_MOD}.Http", side_effect=_http):
        assert inbound_webhook_status(dict(_SECRETS)) == ROUTED
        assert inbound_webhook_status(dict(_SECRETS)) == ROUTED
    assert len(calls) == 1, f"called Twilio {len(calls)} times, expected 1"


def test_cache_key_changes_with_the_configured_inputs() -> None:
    """Re-pointing a webhook must not keep serving the old verdict."""
    from appointment_reminders.services.twilio_routing import _cache_key

    base = _cache_key(dict(_SECRETS))
    assert _cache_key(dict(_SECRETS, **{"twilio-inbound-webhook-url": "https://other"})) != base
    assert _cache_key(dict(_SECRETS, **{"twilio-phone-number": "+19998887777"})) != base


def test_describe_never_claims_configured_when_replies_are_dropped() -> None:
    """The point of the whole change."""
    assert describe(ROUTED) == {"ok": True, "label": "Configured"}
    assert describe(NOT_ROUTED)["ok"] is False
    assert "Configured" != describe(NOT_ROUTED)["label"]
    # Unverified is not an alarm — it must not read as a failure.
    assert describe(UNKNOWN)["ok"] is True
