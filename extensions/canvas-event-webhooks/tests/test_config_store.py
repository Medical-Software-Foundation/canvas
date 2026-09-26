"""Tests for webhook configuration storage, secrets, and validation."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from canvas_event_webhooks.config_store import (
    ATTR_NAME,
    HUB_ID,
    HUB_TYPE,
    INTERNAL_HOST_ERROR,
    LEGACY_WEBHOOK_ID,
    MAX_WEBHOOKS,
    SECRET_PREFIX,
    AttributeHubBackend,
    InMemoryWebhookBackend,
    WebhookConfig,
    WebhookConfigLimitError,
    WebhookConfigStore,
    WebhookConfigValidationError,
    WebhookNotFoundError,
    generate_secret,
    validate_webhook_url,
    webhook_host,
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
    removed = store.delete(webhook.id)
    assert removed.id == webhook.id
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


LEGACY_SECRETS = {
    "webhook-url": "https://legacy.example.com/canvas",
    "webhook-secret": "cli-secret",
}


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/canvas",
        "https://example.com:8443/a?b=c#d",
        "https://api.local-example.com/hook",
        "https://8.8.8.8/hook",
        "https://172.32.0.1/hook",
        "https://[2606:4700:4700::1111]:8443/hook",
        "https://[::ffff:8.8.8.8]/hook",
        "https://[2606:4700:4700:0:0:0:0:1111]/hook",
        "https://[2001:4860:4860::8888]/hook",
        "https://my_service.example.com/hook",
    ],
)
def test_public_destinations_are_accepted(url):
    assert validate_webhook_url(url) == (None, None)


@pytest.mark.parametrize(
    "url",
    [
        "https://[fe80:0:0:0:0:0:0:1]/hook",
        "https://localhost/hook",
        "https://LOCALHOST./hook",
        "https://api.localhost/hook",
        "https://printer.local/hook",
        "https://metadata.google.internal/computeMetadata/v1",
        "https://127.0.0.1/hook",
        "https://user:pass@127.0.0.1/hook",
        "https://0.0.0.0/hook",
        "https://10.1.2.3/hook",
        "https://100.64.0.1/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://172.16.0.1/hook",
        "https://172.31.255.255/hook",
        "https://192.168.1.10:8443/hook",
        "https://224.0.0.1/hook",
        "https://255.255.255.255/hook",
        "https://[::1]:8443/hook",
        "https://[::]/hook",
        "https://[fe80::1]/hook",
        "https://[fd00::1]/hook",
        "https://[ff02::1]/hook",
        "https://[::ffff:127.0.0.1]/hook",
        "https://[::ffff:a9fe:a9fe]/hook",
        "https://[64:ff9b::a9fe:a9fe]/hook",
        "https://[64:ff9b:1::a9fe:a9fe]/hook",
        "https://[2002:7f00:1::]/hook",
        "https://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/hook",
    ],
)
def test_internal_destinations_are_rejected(url):
    assert validate_webhook_url(url) == (INTERNAL_HOST_ERROR, None)


@pytest.mark.parametrize(
    "url",
    [
        "https://2130706433/hook",
        "https://0x7f000001/hook",
        "https://127.1/hook",
        "https://010.0.0.1/hook",
        "https://1.2.3.256/hook",
        "https://./hook",
        "https://ｌｏｃａｌｈｏｓｔ/hook",
        "https://[::1/hook",
        "https://[not-an-ip]/hook",
        "https://[1::2::3]/hook",
        "https://[1:2:3:4:5:6:7:8:9]/hook",
        "https://[1:2:3:4:5:6:7:8::]/hook",
        "https://[fe80::1%25eth0]/hook",
        "https://[::ffff:1.2.3]/hook",
        # HTTP clients end the host at a backslash; these would connect to the internal address.
        "https://127.0.0.1\\@example.com/hook",
        "https://169.254.169.254\\@example.com/",
        "https://localhost\\.example.com/hook",
        "https://127.0.0.1\t@example.com/hook",
        "https://exam\x00ple.com/hook",
        "https://example.com/ho ok",
        "https://exa%6dple.com/hook",
    ],
)
def test_ambiguous_or_malformed_hosts_are_rejected(url):
    assert validate_webhook_url(url) == ("URL is not valid.", None)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://Hooks.Example.com:8443/a?b=c", "hooks.example.com"),
        ("https://user:pw@example.com/x", "example.com"),
        ("https://[2606:4700::1111]:443/x", "[2606:4700::1111]"),
        ("", ""),
    ],
)
def test_webhook_host(url, expected):
    assert webhook_host(url) == expected


def test_webhook_name_is_required_and_limited_to_80_characters():
    store = _store()
    with pytest.raises(WebhookConfigValidationError, match="name is required"):
        _create(store, name="   ")
    with pytest.raises(WebhookConfigValidationError, match="80 characters"):
        _create(store, name="x" * 81)
    assert _create(store, name=f"  {'x' * 80}  ").name == "x" * 80


def test_unknown_webhook_id_raises_not_found():
    store = _store(data=[])
    with pytest.raises(WebhookNotFoundError):
        store.get("nope")
    with pytest.raises(WebhookNotFoundError):
        store.update("nope", name="Renamed")
    with pytest.raises(WebhookNotFoundError):
        store.regenerate_secret("nope")


def test_legacy_id_is_not_found_without_cli_webhook_url():
    with pytest.raises(WebhookNotFoundError):
        _store(data=[]).get(LEGACY_WEBHOOK_ID)


def test_update_rejects_invalid_url_and_keeps_saved_url():
    store = _store()
    webhook = _create(store)
    with pytest.raises(WebhookConfigValidationError, match="HTTPS"):
        store.update(webhook.id, url="http://example.com/hook")
    assert store.get(webhook.id).url == "https://example.com/hook"


def test_import_legacy_persists_cli_webhook():
    backend = InMemoryWebhookBackend()
    store = WebhookConfigStore(secrets=LEGACY_SECRETS, backend=backend)

    imported = store.import_legacy()

    assert imported.id != LEGACY_WEBHOOK_ID
    assert imported.legacy is False
    assert imported.name == "Legacy CLI webhook"
    assert imported.url == "https://legacy.example.com/canvas"
    assert imported.secret == "cli-secret"
    assert imported.events == all_event_names()
    assert backend.data == [imported.to_dict()]


def test_import_legacy_refused_once_ui_config_exists():
    with pytest.raises(WebhookConfigValidationError, match="already exists"):
        _store(secrets=LEGACY_SECRETS, data=[]).import_legacy()


def test_import_legacy_requires_cli_webhook_url():
    with pytest.raises(WebhookConfigValidationError, match="No CLI webhook-url"):
        _store().import_legacy()


def test_unreadable_saved_config_falls_back_to_cli_secrets():
    backend = Mock()
    backend.load.side_effect = ValueError("corrupt attribute")
    store = WebhookConfigStore(secrets=LEGACY_SECRETS, backend=backend)

    with patch("canvas_event_webhooks.config_store.log") as mock_log:
        items = store.list()

    assert mock_log.mock_calls == [
        call.warning(
            "[Webhooks] Failed to load webhook configuration (%s); "
            "falling back to CLI secrets if present.",
            "ValueError",
        ),
        call.debug("[Webhooks] Using legacy CLI webhook configuration (no UI webhooks saved yet)."),
    ]
    assert backend.mock_calls == [call.load()]
    assert [wh.id for wh in items] == [LEGACY_WEBHOOK_ID]


@pytest.mark.parametrize(
    "stored,expected",
    [
        pytest.param([{"id": "a"}], [{"id": "a"}], id="list"),
        pytest.param('[{"id": "a"}]', [{"id": "a"}], id="json_string"),
        pytest.param(None, None, id="unset"),
        pytest.param("not json", None, id="invalid_json"),
        pytest.param({"id": "a"}, None, id="not_a_list"),
    ],
)
def test_attribute_hub_backend_load_reads_one_attribute_in_one_query(stored, expected):
    with patch("canvas_sdk.v1.data.custom_attribute.CustomAttribute") as mock_attribute:
        mock_attribute.objects.filter.return_value.first.return_value.value = stored

        result = AttributeHubBackend().load()

    assert mock_attribute.mock_calls == [
        call.objects.filter(hub__type=HUB_TYPE, hub__id=HUB_ID, name=ATTR_NAME),
        call.objects.filter().first(),
    ]
    assert result == expected


def test_attribute_hub_backend_load_without_saved_attribute_returns_none():
    with patch("canvas_sdk.v1.data.custom_attribute.CustomAttribute") as mock_attribute:
        mock_attribute.objects.filter.return_value.first.return_value = None

        result = AttributeHubBackend().load()

    assert mock_attribute.mock_calls == [
        call.objects.filter(hub__type=HUB_TYPE, hub__id=HUB_ID, name=ATTR_NAME),
        call.objects.filter().first(),
    ]
    assert result is None


def test_attribute_hub_backend_load_query_is_a_single_join_on_real_fields():
    # Mocked querysets never resolve field names; build the real query (no DB access).
    from canvas_sdk.v1.data.custom_attribute import CustomAttribute

    queryset = CustomAttribute.objects.filter(hub__type=HUB_TYPE, hub__id=HUB_ID, name=ATTR_NAME)

    assert set(queryset.query.alias_map) == {"custom_attribute", "attribute_hub"}
    # No manager-level prefetch adds a second query.
    assert not queryset._prefetch_related_lookups


def test_attribute_hub_backend_save_upserts_hub():
    items = [{"id": "a", "name": "A"}]
    hub = MagicMock()
    with patch("canvas_sdk.v1.data.custom_attribute.AttributeHub") as mock_hub:
        mock_hub.objects.get_or_create.return_value = (hub, True)

        AttributeHubBackend().save(items)

    assert mock_hub.mock_calls == [call.objects.get_or_create(type=HUB_TYPE, id=HUB_ID)]
    assert hub.mock_calls == [call.set_attribute(ATTR_NAME, items)]


def test_attribute_hub_backend_save_lookup_resolves_real_fields():
    # get_or_create above is verified with a mock; build its lookup on the real model
    # (no database access) so a wrong field name fails here.
    from canvas_sdk.v1.data.custom_attribute import AttributeHub

    query = AttributeHub.objects.filter(type=HUB_TYPE, id=HUB_ID).query

    assert set(query.alias_map) == {"attribute_hub"}
