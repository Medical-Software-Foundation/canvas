"""
Persistence and validation for up to three independent webhook configurations.

Production storage uses Canvas ``AttributeHub`` / ``CustomAttribute`` (durable
key-value). Tests may inject an in-memory backend.

Legacy CLI secrets (``webhook-url`` / ``webhook-secret``) are used as a
fallback when no UI configuration has been saved yet, so existing installs
keep working until the operator saves from the UI.
"""

from __future__ import annotations

import json
from uuid import uuid4

from logger import log

from canvas_event_webhooks.events_catalog import all_event_names, known_event

MAX_WEBHOOKS = 3
SECRET_PREFIX = "canvaswebhook_"
HUB_TYPE = "plugin_config"
HUB_ID = "canvas_event_webhooks"
ATTR_NAME = "webhooks"
LEGACY_WEBHOOK_ID = "legacy"


class WebhookConfigError(Exception):
    """Base error for webhook configuration problems."""


class WebhookConfigLimitError(WebhookConfigError):
    """Raised when a fourth webhook would be created."""


class WebhookConfigValidationError(WebhookConfigError):
    """Raised when a create/update payload is invalid."""


class WebhookNotFoundError(WebhookConfigError):
    """Raised when a webhook id does not exist."""


class WebhookConfig:
    """One independently-routed webhook destination."""

    def __init__(
        self,
        id: str,
        name: str,
        url: str,
        secret: str,
        enabled: bool = True,
        events: list[str] | None = None,
        legacy: bool = False,
        include_details: bool = False,
    ) -> None:
        self.id = id
        self.name = name
        self.url = url
        self.secret = secret
        self.enabled = enabled
        self.events = list(events or [])
        self.legacy = legacy
        self.include_details = include_details

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "secret": self.secret,
            "enabled": self.enabled,
            "events": list(self.events),
            "legacy": self.legacy,
            "include_details": self.include_details,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WebhookConfig:
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or ""),
            url=str(data.get("url") or ""),
            secret=str(data.get("secret") or ""),
            enabled=bool(data.get("enabled", True)),
            events=list(data.get("events") or []),
            legacy=bool(data.get("legacy", False)),
            include_details=bool(data.get("include_details", False)),
        )

    def accepts(self, event_name: str) -> bool:
        return self.enabled and event_name in self.events


def generate_secret() -> str:
    """Return a cryptographically secure webhook signing secret.

    The Canvas plugin sandbox does not allow the ``secrets`` module. ``uuid4``
    is backed by ``os.urandom``; two UUIDs give 32 bytes of hex-encoded entropy.
    """
    return SECRET_PREFIX + uuid4().hex + uuid4().hex


def new_webhook_id() -> str:
    return uuid4().hex


def is_https_url(url: str) -> bool:
    return (url or "").strip().lower().startswith("https://")


def validate_webhook_url(url: str) -> tuple[str | None, str | None]:
    """
    Validate a webhook URL.

    Returns (error, warning). ``error`` is set when the URL must be rejected.
    Only ``https://`` URLs are accepted.

    Implemented without ``urllib.parse.urlparse`` (not allowed in the Canvas sandbox).
    """
    cleaned = (url or "").strip()
    if not cleaned:
        return "Webhook URL is required.", None
    lowered = cleaned.lower()
    if lowered.startswith("http://"):
        return "URL must use HTTPS. HTTP is not allowed.", None
    if not lowered.startswith("https://"):
        return "URL must start with https://.", None
    rest = cleaned[8:]
    host = rest.split("/")[0].split("?")[0].split("#")[0]
    hostname = host.rsplit("@", 1)[-1]
    if hostname.startswith("["):
        # IPv6 literal: [::1]:port
        if "]" not in hostname:
            return "URL is not valid.", None
        hostname = hostname.split("]", 1)[0] + "]"
    else:
        hostname = hostname.split(":")[0]
    if not hostname or " " in hostname:
        return "URL is not valid.", None
    return None, None


def _validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise WebhookConfigValidationError("Webhook name is required.")
    if len(cleaned) > 80:
        raise WebhookConfigValidationError("Webhook name must be 80 characters or fewer.")
    return cleaned


def _validate_events(events: list[str]) -> list[str]:
    if not events:
        raise WebhookConfigValidationError("Select at least one event.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in events:
        if not isinstance(name, str) or not known_event(name):
            raise WebhookConfigValidationError(f"Unknown event: {name!r}.")
        if name not in seen:
            seen.add(name)
            cleaned.append(name)
    return cleaned


def _materialize(webhook: WebhookConfig) -> WebhookConfig:
    """Copy a (possibly legacy) config into a persistable record."""
    return WebhookConfig(
        id=new_webhook_id() if webhook.legacy or webhook.id == LEGACY_WEBHOOK_ID else webhook.id,
        name=webhook.name,
        url=webhook.url,
        secret=webhook.secret or generate_secret(),
        enabled=webhook.enabled,
        events=webhook.events,
        legacy=False,
        include_details=webhook.include_details,
    )


class InMemoryWebhookBackend:
    """List-backed store for unit tests. ``data is None`` means 'never saved'."""

    def __init__(self, data: list[dict] | None = None) -> None:
        self.data = data

    def load(self) -> list[dict] | None:
        return self.data

    def save(self, items: list[dict]) -> None:
        self.data = items


class AttributeHubBackend:
    """Durable store using Canvas AttributeHub custom attributes."""

    def load(self) -> list[dict] | None:
        from canvas_sdk.v1.data.custom_attribute import AttributeHub

        try:
            hub = AttributeHub.objects.get(type=HUB_TYPE, id=HUB_ID)
        except AttributeHub.DoesNotExist:
            return None
        value = hub.get_attribute(ATTR_NAME)
        if value is None:
            return None
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, list):
            return None
        return value

    def save(self, items: list[dict]) -> None:
        from canvas_sdk.v1.data.custom_attribute import AttributeHub

        hub, _created = AttributeHub.objects.get_or_create(type=HUB_TYPE, id=HUB_ID)
        hub.set_attribute(ATTR_NAME, items)


class WebhookConfigStore:
    """Load, create, update, and delete webhook configurations."""

    def __init__(
        self,
        secrets: dict | None = None,
        backend: InMemoryWebhookBackend | AttributeHubBackend | None = None,
    ) -> None:
        self.secrets = secrets or {}
        self.backend = backend or AttributeHubBackend()

    def list(self) -> list[WebhookConfig]:
        stored = self._load_stored()
        if stored is not None:
            return stored
        return self._legacy_fallback()

    def get(self, webhook_id: str) -> WebhookConfig:
        for webhook in self.list():
            if webhook.id == webhook_id:
                return webhook
        raise WebhookNotFoundError(f"Webhook {webhook_id!r} was not found.")

    def active_webhooks_for_event(self, event_name: str) -> list[WebhookConfig]:
        return [wh for wh in self.list() if wh.accepts(event_name)]

    def create(
        self,
        *,
        name: str,
        url: str,
        events: list[str],
        enabled: bool = True,
        include_details: bool = False,
    ) -> tuple[WebhookConfig, str | None]:
        items = self._working_copy()
        if len(items) >= MAX_WEBHOOKS:
            raise WebhookConfigLimitError(
                f"A maximum of {MAX_WEBHOOKS} webhooks can be configured."
            )
        name = _validate_name(name)
        error, warning = validate_webhook_url(url)
        if error:
            raise WebhookConfigValidationError(error)
        webhook = WebhookConfig(
            id=new_webhook_id(),
            name=name,
            url=url.strip(),
            secret=generate_secret(),
            enabled=enabled,
            events=_validate_events(events),
            include_details=bool(include_details),
        )
        items.append(webhook)
        saved = self._save(items)
        return saved[-1], warning

    def update(
        self,
        webhook_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        events: list[str] | None = None,
        enabled: bool | None = None,
        include_details: bool | None = None,
    ) -> tuple[WebhookConfig, str | None]:
        items = self._working_copy()
        index = next((i for i, wh in enumerate(items) if wh.id == webhook_id), None)
        if index is None:
            raise WebhookNotFoundError(f"Webhook {webhook_id!r} was not found.")
        current = items[index]
        warning: str | None = None
        next_name = _validate_name(name) if name is not None else current.name
        next_url = current.url
        if url is not None:
            error, warning = validate_webhook_url(url)
            if error:
                raise WebhookConfigValidationError(error)
            next_url = url.strip()
        next_events = _validate_events(events) if events is not None else current.events
        next_enabled = current.enabled if enabled is None else bool(enabled)
        next_details = (
            current.include_details if include_details is None else bool(include_details)
        )
        updated = WebhookConfig(
            id=current.id,
            name=next_name,
            url=next_url,
            secret=current.secret or generate_secret(),
            enabled=next_enabled,
            events=next_events,
            include_details=next_details,
        )
        items[index] = updated
        saved = self._save(items)
        return saved[index], warning

    def delete(self, webhook_id: str) -> None:
        items = self._working_copy()
        remaining = [wh for wh in items if wh.id != webhook_id]
        if len(remaining) == len(items):
            raise WebhookNotFoundError(f"Webhook {webhook_id!r} was not found.")
        self._save(remaining)

    def regenerate_secret(self, webhook_id: str) -> WebhookConfig:
        items = self._working_copy()
        index = next((i for i, wh in enumerate(items) if wh.id == webhook_id), None)
        if index is None:
            raise WebhookNotFoundError(f"Webhook {webhook_id!r} was not found.")
        current = items[index]
        updated = WebhookConfig(
            id=current.id,
            name=current.name,
            url=current.url,
            secret=generate_secret(),
            enabled=current.enabled,
            events=current.events,
            include_details=current.include_details,
        )
        items[index] = updated
        saved = self._save(items)
        return saved[index]

    def import_legacy(self) -> WebhookConfig:
        """Persist the CLI secret webhook as a real UI-managed config."""
        stored = self._load_stored()
        if stored is not None:
            raise WebhookConfigValidationError(
                "UI configuration already exists; legacy CLI secrets are not used."
            )
        legacy = self._legacy_fallback()
        if not legacy:
            raise WebhookConfigValidationError("No CLI webhook-url is configured to import.")
        imported = _materialize(legacy[0])
        imported.name = _validate_name(imported.name)
        saved = self._save([imported])
        return saved[0]

    def _working_copy(self) -> list[WebhookConfig]:
        """
        Current configs ready to be mutated and saved.

        If nothing is persisted yet, include the legacy CLI webhook (when
        present) so the first UI save does not drop it. Legacy ids are
        rewritten on save.
        """
        stored = self._load_stored()
        if stored is not None:
            return list(stored)
        return list(self._legacy_fallback())

    def _load_stored(self) -> list[WebhookConfig] | None:
        try:
            raw = self.backend.load()
        except Exception as exc:
            log.warning(
                "[Webhooks] Failed to load webhook configuration (%s); "
                "falling back to CLI secrets if present.",
                exc.__class__.__name__,
            )
            return None
        if raw is None:
            return None
        return [WebhookConfig.from_dict(item) for item in raw]

    def _save(self, items: list[WebhookConfig]) -> list[WebhookConfig]:
        persisted = [_materialize(wh) for wh in items]
        self.backend.save([wh.to_dict() for wh in persisted])
        return persisted

    def _legacy_fallback(self) -> list[WebhookConfig]:
        url = (self.secrets.get("webhook-url") or "").strip()
        if not url:
            return []
        secret = (self.secrets.get("webhook-secret") or "").strip()
        log.info(
            "[Webhooks] Using legacy CLI webhook configuration (no UI webhooks saved yet)."
        )
        return [
            WebhookConfig(
                id=LEGACY_WEBHOOK_ID,
                name="Legacy CLI webhook",
                url=url,
                secret=secret,
                enabled=True,
                events=all_event_names(),
                legacy=True,
                include_details=False,
            )
        ]
