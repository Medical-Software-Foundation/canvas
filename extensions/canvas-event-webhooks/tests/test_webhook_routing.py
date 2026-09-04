"""Event routing, HMAC isolation, retries, and log-safety tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.config_store import WebhookConfig
from canvas_event_webhooks.handlers.base import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    _RETRY_ON,
    sign_body,
)
from canvas_event_webhooks.handlers.event_handlers import PatientWebhookHandler


def _event(event_type: int, context: dict | None = None, target_id: str = "rec-1") -> Mock:
    event = Mock()
    event.type = event_type
    event.target = Mock()
    event.target.id = target_id
    event.target.type = None
    event.context = context or {}
    return event


def _handler(event_type: int = EventType.PATIENT_CREATED, context: dict | None = None):
    return PatientWebhookHandler(event=_event(event_type, context=context), secrets={})


def _wh(
    name: str, events: list[str], secret: str, enabled: bool = True, url: str | None = None
) -> WebhookConfig:
    return WebhookConfig(
        id=name,
        name=name,
        url=url or f"https://{name}.example.com/hook",
        secret=secret,
        enabled=enabled,
        events=events,
    )


def _http_effects(effects):
    return [e for e in effects if e.type == EffectType.HTTP_REQUEST]


def _data(effect) -> dict:
    return json.loads(effect.payload)["data"]


def test_webhook_a_receives_only_selected_events():
    webhooks = [
        _wh("A", ["PATIENT_CREATED"], "secret-a"),
        _wh("B", ["PATIENT_UPDATED"], "secret-b"),
    ]
    created = _http_effects(_handler(EventType.PATIENT_CREATED)._dispatch(webhooks=webhooks))
    assert len(created) == 1
    assert _data(created[0])["url"] == "https://A.example.com/hook"

    updated = _http_effects(_handler(EventType.PATIENT_UPDATED)._dispatch(webhooks=webhooks))
    assert len(updated) == 1
    assert _data(updated[0])["url"] == "https://B.example.com/hook"


def test_each_of_three_webhooks_filters_independently():
    webhooks = [
        _wh("A", ["PATIENT_CREATED"], "sa"),
        _wh("B", ["PATIENT_CREATED", "PATIENT_UPDATED"], "sb"),
        _wh("C", ["TASK_CREATED"], "sc"),
    ]
    effects = _http_effects(_handler(EventType.PATIENT_CREATED)._dispatch(webhooks=webhooks))
    urls = {_data(e)["url"] for e in effects}
    assert urls == {"https://A.example.com/hook", "https://B.example.com/hook"}


def test_disabled_webhook_does_not_receive_events():
    webhooks = [
        _wh("on", ["PATIENT_CREATED"], "s1", enabled=True),
        _wh("off", ["PATIENT_CREATED"], "s2", enabled=False),
    ]
    effects = _http_effects(_handler(EventType.PATIENT_CREATED)._dispatch(webhooks=webhooks))
    assert len(effects) == 1
    assert _data(effects[0])["url"] == "https://on.example.com/hook"


def _assert_signed(secret: str, body: str, headers: dict) -> None:
    ts = int(headers[TIMESTAMP_HEADER])
    assert headers[SIGNATURE_HEADER] == sign_body(secret, body, ts)


def test_hmac_uses_each_webhook_secret():
    webhooks = [
        _wh("A", ["PATIENT_CREATED"], "secret-a"),
        _wh("B", ["PATIENT_CREATED"], "secret-b"),
    ]
    effects = _http_effects(_handler(EventType.PATIENT_CREATED)._dispatch(webhooks=webhooks))
    assert len(effects) == 2
    for effect, secret in zip(effects, ["secret-a", "secret-b"], strict=True):
        data = _data(effect)
        body = data["body"]
        _assert_signed(secret, body, data["headers"])
        other = "secret-b" if secret == "secret-a" else "secret-a"
        ts = int(data["headers"][TIMESTAMP_HEADER])
        assert data["headers"][SIGNATURE_HEADER] != sign_body(other, body, ts)


def test_sign_body_binds_timestamp():
    body = '{"event":"PATIENT_CREATED"}'
    ts = 1756830000
    expected = "t=1756830000,v1=" + hmac.new(
        b"abc", f"{ts}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert sign_body("abc", body, ts) == expected


def test_http_webhook_is_not_delivered():
    webhooks = [
        _wh("insecure", ["PATIENT_CREATED"], "s1", url="http://example.com/hook"),
        _wh("secure", ["PATIENT_CREATED"], "s2"),
    ]
    effects = _http_effects(_handler()._dispatch(webhooks=webhooks))
    assert len(effects) == 1
    assert _data(effects[0])["url"] == "https://secure.example.com/hook"


def test_signature_timestamp_is_current():
    webhooks = [_wh("A", ["PATIENT_CREATED"], "s")]
    effects = _http_effects(_handler()._dispatch(webhooks=webhooks))
    headers = _data(effects[0])["headers"]
    ts = int(headers[TIMESTAMP_HEADER])
    assert abs(time.time() - ts) < 10
    _assert_signed("s", _data(effects[0])["body"], headers)
    stale = ts - 301
    assert time.time() - stale > 300


def test_one_webhook_construction_failure_does_not_block_others(monkeypatch):
    webhooks = [
        _wh("bad", ["PATIENT_CREATED"], "s1"),
        _wh("good", ["PATIENT_CREATED"], "s2"),
    ]
    handler = _handler()
    original = handler._effect_for_webhook

    def boom(webhook, body):
        if webhook.name == "bad":
            raise RuntimeError("network down")
        return original(webhook, body)

    monkeypatch.setattr(handler, "_effect_for_webhook", boom)
    effects = _http_effects(handler._dispatch(webhooks=webhooks))
    assert len(effects) == 1
    assert _data(effects[0])["url"] == "https://good.example.com/hook"


def test_retry_status_codes_are_configured():
    webhooks = [_wh("A", ["PATIENT_CREATED"], "s")]
    effects = _http_effects(_handler()._dispatch(webhooks=webhooks))
    retry_codes = _data(effects[0])["retry_on_status_codes"]
    for code in [429, 500, 502, 503, 504]:
        assert code in retry_codes
    assert retry_codes == _RETRY_ON


def test_partial_success_still_queues_successful_webhooks():
    webhooks = [
        _wh("one", ["PATIENT_CREATED"], "s1"),
        _wh("two", ["PATIENT_CREATED"], "s2"),
        _wh("three", ["PATIENT_CREATED"], "s3"),
    ]
    effects = _http_effects(_handler()._dispatch(webhooks=webhooks))
    assert len(effects) == 3


def test_secrets_are_not_written_to_logs(monkeypatch):
    recorded: list[str] = []

    def capture(message, *args, **kwargs):
        recorded.append(message % args if args else str(message))

    from canvas_event_webhooks.handlers import base as base_mod

    monkeypatch.setattr(base_mod.log, "info", capture)
    monkeypatch.setattr(base_mod.log, "warning", capture)
    monkeypatch.setattr(base_mod.log, "exception", capture)

    secret = "canvaswebhook_super-secret-value"
    webhooks = [_wh("Prod", ["PATIENT_CREATED"], secret)]
    _handler()._dispatch(webhooks=webhooks)
    joined = "\n".join(recorded)
    assert secret not in joined
    assert "super-secret-value" not in joined


def test_no_matching_webhooks_returns_empty():
    webhooks = [_wh("A", ["TASK_CREATED"], "s")]
    assert _handler(EventType.PATIENT_CREATED)._dispatch(webhooks=webhooks) == []
