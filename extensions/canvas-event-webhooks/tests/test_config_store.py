"""Tests for webhook configuration storage, secrets, and validation."""

from __future__ import annotations

import re

import pytest

from canvas_event_webhooks.config_store import (
    LEGACY_WEBHOOK_ID,
    MAX_WEBHOOKS,
    SECRET_PREFIX,
    InMemoryWebhookBackend,
    WebhookConfig,
    WebhookConfigLimitError,
    WebhookConfigStore,
    WebhookConfigValidationError,
    WebhookNotFoundError,
    generate_secret,
    validate_webhook_url,
)
from canvas_event_webhooks.events_catalog import all_event_names


def _store(secrets: dict | None = None, data=None) -> WebhookConfigStore:
    return WebhookConfigStore(secrets=secrets or {}, backend=InMemoryWebhookBackend(data=data))


def _create(
    store: WebhookConfigStore,
    name="Production API",
    url="https://example.com/hook",
    events=None,
):
    return store.create(
        name=name,
        url=url,
        events=events or ["PATIENT_CREATED"],
    )[0]


def test_generate_secret_format_and_entropy():
    secret = generate_secret()
    assert secret.startswith(SECRET_PREFIX)
    token = secret[len(SECRET_PREFIX) :]
    assert len(token) >= 32
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_secrets_are_unique_and_unpredictable():
    generated = {generate_secret() for _ in range(50)}
    assert len(generated) == 50
    assert "canvaswebhook_hsdfjdhs4214fjho423" not in generated


def test_create_webhook_assigns_secret():
    webhook = _create(_store())
    assert webhook.name == "Production API"
    assert webhook.url == "https://example.com/hook"
    assert webhook.enabled is True
    assert webhook.events == ["PATIENT_CREATED"]
    assert webhook.secret.startswith(SECRET_PREFIX)
    assert webhook.id
    assert webhook.legacy is False


def test_update_webhook():
    store = _store()
    webhook = _create(store)
    updated, _ = store.update(
        webhook.id,
        name="Zapier",
        url="https://hooks.zapier.com/a",
        events=["TASK_CREATED", "TASK_UPDATED"],
        enabled=False,
    )
    assert updated.name == "Zapier"
    assert updated.url == "https://hooks.zapier.com/a"
    assert updated.events == ["TASK_CREATED", "TASK_UPDATED"]
    assert updated.enabled is False
    assert updated.secret == webhook.secret


def test_delete_webhook():
    store = _store()
    webhook = _create(store)
    store.delete(webhook.id)
    assert store.list() == []


def test_create_defaults_include_details_off():
    webhook = _create(_store())
    assert webhook.include_details is False
    assert webhook.to_dict()["include_details"] is False


def test_include_details_round_trip():
    store = _store()
    webhook = _create(store)
    updated, _ = store.update(webhook.id, include_details=True)
    assert updated.include_details is True
    listed = store.list()
    assert listed[0].include_details is True
    disabled, _ = store.update(webhook.id, include_details=False)
    assert disabled.include_details is False


def test_from_dict_missing_include_details_defaults_false():
    webhook = WebhookConfig.from_dict(
        {
            "id": "abc",
            "name": "Old",
            "url": "https://example.com/h",
            "secret": "s",
            "enabled": True,
            "events": ["PATIENT_CREATED"],
        }
    )
    assert webhook.include_details is False


def test_regenerate_preserves_include_details():
    store = _store()
    webhook = _create(store)
    store.update(webhook.id, include_details=True)
    rotated = store.regenerate_secret(webhook.id)
    assert rotated.include_details is True


def test_enable_disable_webhook():
    store = _store()
    webhook = _create(store)
    disabled, _ = store.update(webhook.id, enabled=False)
    assert disabled.enabled is False
    enabled, _ = store.update(webhook.id, enabled=True)
    assert enabled.enabled is True


def test_maximum_three_webhooks():
    store = _store()
    for i in range(MAX_WEBHOOKS):
        _create(store, name=f"Hook {i}", url=f"https://example.com/{i}")
    with pytest.raises(WebhookConfigLimitError):
        _create(store, name="Too many", url="https://example.com/4")


def test_invalid_url_rejected():
    store = _store()
    with pytest.raises(WebhookConfigValidationError, match="http"):
        store.create(name="Bad", url="ftp://example.com/x", events=["PATIENT_CREATED"])
    with pytest.raises(WebhookConfigValidationError, match="required"):
        store.create(name="Bad", url="  ", events=["PATIENT_CREATED"])
    with pytest.raises(WebhookConfigValidationError, match="not valid"):
        store.create(name="Bad", url="https://", events=["PATIENT_CREATED"])


def test_http_url_rejected():
    error, warning = validate_webhook_url("http://example.com/hook")
    assert error is not None
    assert "HTTPS" in error
    assert warning is None
    store = _store()
    with pytest.raises(WebhookConfigValidationError, match="HTTPS"):
        store.create(
            name="Insecure",
            url="http://example.com/hook",
            events=["PATIENT_CREATED"],
        )


def test_empty_event_selection_rejected():
    store = _store()
    with pytest.raises(WebhookConfigValidationError, match="at least one"):
        store.create(name="Empty", url="https://example.com/h", events=[])


def test_unknown_event_rejected():
    store = _store()
    with pytest.raises(WebhookConfigValidationError, match="Unknown event"):
        store.create(
            name="Fake",
            url="https://example.com/h",
            events=["PATIENT_DELETED"],
        )


def test_regenerate_secret_changes_value():
    store = _store()
    webhook = _create(store)
    rotated = store.regenerate_secret(webhook.id)
    assert rotated.secret != webhook.secret
    assert rotated.secret.startswith(SECRET_PREFIX)


def test_legacy_cli_fallback_when_nothing_saved():
    store = _store(
        secrets={
            "webhook-url": "https://legacy.example.com/canvas",
            "webhook-secret": "cli-secret",
        }
    )
    items = store.list()
    assert len(items) == 1
    assert items[0].id == LEGACY_WEBHOOK_ID
    assert items[0].legacy is True
    assert items[0].url == "https://legacy.example.com/canvas"
    assert items[0].secret == "cli-secret"
    assert set(items[0].events) == set(all_event_names())


def test_saving_legacy_materializes_ui_config():
    store = _store(
        secrets={
            "webhook-url": "https://legacy.example.com/canvas",
            "webhook-secret": "cli-secret",
        }
    )
    updated, _ = store.update(LEGACY_WEBHOOK_ID, name="Imported")
    assert updated.legacy is False
    assert updated.id != LEGACY_WEBHOOK_ID
    assert updated.name == "Imported"
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == updated.id
    assert listed[0].legacy is False


def test_create_alongside_legacy_keeps_cli_card_addressable():
    """First UI create rematerializes the CLI webhook; id 'legacy' still works."""
    store = _store(
        secrets={
            "webhook-url": "https://legacy.example.com/canvas",
            "webhook-secret": "cli-secret",
        }
    )
    created = _create(store, name="New destination")
    listed = store.list()
    assert len(listed) == 2
    assert created.id != LEGACY_WEBHOOK_ID
    assert all(wh.id != LEGACY_WEBHOOK_ID for wh in listed)
    assert all(wh.legacy is False for wh in listed)

    stale = store.get(LEGACY_WEBHOOK_ID)
    assert stale.url == "https://legacy.example.com/canvas"
    assert stale.id != LEGACY_WEBHOOK_ID

    updated, _ = store.update(LEGACY_WEBHOOK_ID, name="CLI imported")
    assert updated.name == "CLI imported"
    assert updated.url == "https://legacy.example.com/canvas"

    rotated = store.regenerate_secret(LEGACY_WEBHOOK_ID)
    assert rotated.secret != "cli-secret"
    assert rotated.url == "https://legacy.example.com/canvas"

    store.delete(LEGACY_WEBHOOK_ID)
    remaining = store.list()
    assert len(remaining) == 1
    assert remaining[0].id == created.id


def test_delete_missing_webhook():
    with pytest.raises(WebhookNotFoundError):
        _store(data=[]).delete("nope")
