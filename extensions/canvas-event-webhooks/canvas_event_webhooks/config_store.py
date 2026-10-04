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


INTERNAL_HOST_ERROR = (
    "URL must point to a public host. Loopback, private, and link-local addresses are not allowed."
)
_INTERNAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_HEX_DIGITS = frozenset("0123456789abcdef")
_HOSTNAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")


def webhook_host(url: str) -> str:
    """Return the lowercased host of a URL, without userinfo or port ("" when absent).

    IPv6 literals keep their brackets. Implemented without ``urllib.parse``
    (not allowed in the Canvas sandbox).
    """
    rest = (url or "").strip().split("://", 1)[-1]
    authority = rest.split("/")[0].split("?")[0].split("#")[0]
    host = authority.rsplit("@", 1)[-1].lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]" if "]" in host else host
    return host.split(":")[0]


def _ipv4_to_int(text: str) -> int | None:
    """Parse a standard dotted-quad IPv4 address; shorthand, octal, and hex forms return None."""
    parts = text.split(".")
    if len(parts) != 4:
        return None
    value = 0
    for part in parts:
        if not (part.isascii() and part.isdigit()) or (len(part) > 1 and part[0] == "0"):
            return None
        octet = int(part)
        if octet > 255:
            return None
        value = (value << 8) | octet
    return value


def _hextets(text: str, *, allow_ipv4: bool) -> list[int] | None:
    if not text:
        return []
    items = text.split(":")
    groups: list[int] = []
    for index, item in enumerate(items):
        if allow_ipv4 and index == len(items) - 1 and "." in item:
            ipv4 = _ipv4_to_int(item)
            if ipv4 is None:
                return None
            groups.extend((ipv4 >> 16, ipv4 & 0xFFFF))
        elif 1 <= len(item) <= 4 and set(item) <= _HEX_DIGITS:
            groups.append(int(item, 16))
        else:
            return None
    return groups


def _ipv6_to_int(text: str) -> int | None:
    """Parse a lowercase IPv6 literal (no brackets), including ``::`` and a trailing IPv4 part."""
    head, separator, tail = text.partition("::")
    if "::" in tail:
        return None
    left = _hextets(head, allow_ipv4=not separator)
    right = _hextets(tail, allow_ipv4=True)
    if left is None or right is None:
        return None
    if separator:
        missing = 8 - len(left) - len(right)
        if missing < 1:
            return None
        groups = [*left, *([0] * missing), *right]
    elif len(left) == 8:
        groups = left
    else:
        return None
    value = 0
    for group in groups:
        value = (value << 16) | group
    return value


_BLOCKED_IPV4_NETWORKS = tuple(
    (_ipv4_to_int(address), prefix)
    for address, prefix in (
        ("0.0.0.0", 8),  # "this" network
        ("10.0.0.0", 8),  # private
        ("100.64.0.0", 10),  # carrier-grade NAT
        ("127.0.0.0", 8),  # loopback
        ("169.254.0.0", 16),  # link-local, cloud metadata
        ("172.16.0.0", 12),  # private
        ("192.0.0.0", 24),  # IETF protocol assignments
        ("192.168.0.0", 16),  # private
        ("198.18.0.0", 15),  # benchmarking
        ("224.0.0.0", 4),  # multicast
        ("240.0.0.0", 4),  # reserved, broadcast
    )
)

_BLOCKED_IPV6_NETWORKS = (
    (0, 96),  # unspecified, loopback, IPv4-compatible
    (0x0064FF9B << 96, 96),  # NAT64 well-known prefix (embeds IPv4)
    (0x0064FF9B0001 << 80, 48),  # NAT64 local-use prefix (embeds IPv4)
    (0x2001 << 112, 32),  # Teredo (embeds IPv4)
    (0x2002 << 112, 16),  # 6to4 (embeds IPv4)
    (0xFC00 << 112, 7),  # unique local
    (0xFE80 << 112, 10),  # link-local
    (0xFEC0 << 112, 10),  # site-local (deprecated)
    (0xFF00 << 112, 8),  # multicast
)


def _in_networks(value: int, networks, bits: int) -> bool:
    return any(value >> (bits - prefix) == network >> (bits - prefix) for network, prefix in networks)


def _is_blocked_ipv4(value: int) -> bool:
    return _in_networks(value, _BLOCKED_IPV4_NETWORKS, 32)


def _is_blocked_ipv6(value: int) -> bool:
    if value >> 32 == 0xFFFF:  # IPv4-mapped (::ffff:a.b.c.d)
        return _is_blocked_ipv4(value & 0xFFFFFFFF)
    return _in_networks(value, _BLOCKED_IPV6_NETWORKS, 128)


def validate_webhook_url(url: str) -> tuple[str | None, str | None]:
    """
    Validate a webhook URL.

    Returns (error, warning). ``error`` is set when the URL must be rejected.
    Only ``https://`` URLs to public hosts are accepted. Loopback, private,
    link-local, and other internal addresses are refused so a webhook cannot
    reach services inside the network Canvas delivers from. Hostnames that
    merely *resolve* to internal addresses cannot be detected here.

    Implemented without ``urllib.parse`` / ``ipaddress`` (not allowed in the Canvas sandbox).
    """
    cleaned = (url or "").strip()
    if not cleaned:
        return "Webhook URL is required.", None
    lowered = cleaned.lower()
    if lowered.startswith("http://"):
        return "URL must use HTTPS. HTTP is not allowed.", None
    if not lowered.startswith("https://"):
        return "URL must start with https://.", None
    if any(ch == "\\" or ch.isspace() or not ch.isprintable() for ch in cleaned):
        # HTTP clients end the host at a backslash, so "https://127.0.0.1\@example.com"
        # would pass the host check below as example.com and then connect to 127.0.0.1.
        return "URL is not valid.", None
    hostname = webhook_host(cleaned)
    if not hostname or " " in hostname or not hostname.isascii():
        return "URL is not valid.", None
    if hostname.startswith("["):
        address = _ipv6_to_int(hostname[1:-1]) if hostname.endswith("]") else None
        if address is None:
            return "URL is not valid.", None
        return (INTERNAL_HOST_ERROR, None) if _is_blocked_ipv6(address) else (None, None)
    host = hostname.rstrip(".")
    if not host or not set(host) <= _HOSTNAME_CHARS:
        return "URL is not valid.", None
    if host == "localhost" or host.endswith(_INTERNAL_HOST_SUFFIXES):
        return INTERNAL_HOST_ERROR, None
    last_label = host.rsplit(".", 1)[-1]
    if last_label.isdigit() or last_label.startswith("0x"):
        # Numeric hosts are IP literals. Shorthand forms (127.1, 2130706433, 0x7f.1) are refused.
        address = _ipv4_to_int(host)
        if address is None:
            return "URL is not valid.", None
        if _is_blocked_ipv4(address):
            return INTERNAL_HOST_ERROR, None
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
        # Runs on every subscribed Canvas event, so read the one attribute in a single
        # indexed query instead of loading the hub and prefetching all of its attributes.
        from canvas_sdk.v1.data.custom_attribute import CustomAttribute

        attribute = CustomAttribute.objects.filter(
            hub__type=HUB_TYPE, hub__id=HUB_ID, name=ATTR_NAME
        ).first()
        value = attribute.value if attribute is not None else None
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return None
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
        items = self.list()
        index = self._resolve_index(items, webhook_id)
        if index is None:
            raise WebhookNotFoundError(f"Webhook {webhook_id!r} was not found.")
        return items[index]

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
        index = self._resolve_index(items, webhook_id)
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

    def delete(self, webhook_id: str) -> WebhookConfig:
        """Remove a webhook and return the removed config."""
        items = self._working_copy()
        index = self._resolve_index(items, webhook_id)
        if index is None:
            raise WebhookNotFoundError(f"Webhook {webhook_id!r} was not found.")
        removed = items[index]
        remaining = [wh for i, wh in enumerate(items) if i != index]
        self._save(remaining)
        return removed

    def regenerate_secret(self, webhook_id: str) -> WebhookConfig:
        items = self._working_copy()
        index = self._resolve_index(items, webhook_id)
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

    def _resolve_index(self, items: list[WebhookConfig], webhook_id: str) -> int | None:
        """Find a webhook, including a stale UI id of ``legacy`` after first save.

        Creating another destination rematerializes the CLI card under a new
        UUID. The config page may still hold ``id="legacy"``. Map that sentinel
        to the persisted row that still matches the CLI ``webhook-url``.
        """
        index = next((i for i, wh in enumerate(items) if wh.id == webhook_id), None)
        if index is not None:
            return index
        if webhook_id != LEGACY_WEBHOOK_ID:
            return None
        cli_url = (self.secrets.get("webhook-url") or "").strip()
        if not cli_url:
            return None
        return next((i for i, wh in enumerate(items) if wh.url == cli_url), None)

    def _load_stored(self) -> list[WebhookConfig] | None:
        try:
            raw = self.backend.load()
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
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
        # Runs on every subscribed event until a UI config is saved; keep it off the default level.
        log.debug(
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
