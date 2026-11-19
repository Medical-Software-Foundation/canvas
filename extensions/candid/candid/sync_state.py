"""Durable state for the nightly sync (cursor and last start date).

The plugin cache is not safe for this. Once an instance's shared plugin cache
holds more than 300 entries, the platform deletes about a third of them in
alphabetical key order, whatever their expiry, and ``candid:`` keys sort near
the front. A cursor kept there can vanish between hourly ticks, and the cycle
then silently stops after its first batch.

This store keeps each value in an ``AttributeHub`` in the plugin's custom data
namespace, which nothing culls. It has the same ``get``/``set``/``delete``
interface as the cache, including expiry. There is deliberately no fallback to
the cache: the manifest always ships the namespace with this code, and a split
between two stores could leave a stale cursor behind. A database error fails
the tick loudly, and the next hourly tick retries from the last saved cursor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_sdk.v1.data import AttributeHub
from canvas_sdk.v1.data.custom_attribute import CustomAttribute

HUB_TYPE = "candid_sync_state"
HUB_ID = "nightly_sync"


class SyncState:
    """Durable key-value store with expiry, backed by an AttributeHub."""

    def get(self, key: str) -> Any:
        attribute = CustomAttribute.objects.filter(
            hub__type=HUB_TYPE, hub__id=HUB_ID, name=key
        ).first()
        return _unwrap(attribute.value if attribute is not None else None)

    def set(self, key: str, value: Any, timeout_seconds: int) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
        self._write(key, {"value": value, "expires_at": expires_at.isoformat()})

    def delete(self, key: str) -> None:
        self._write(key, {"value": None, "expires_at": None})

    def _write(self, key: str, payload: dict) -> None:
        hub, _created = AttributeHub.objects.get_or_create(type=HUB_TYPE, id=HUB_ID)
        hub.set_attribute(key, json.dumps(payload))


def _unwrap(raw: Any) -> Any:
    """Return the stored value, or None when it is missing, malformed or expired."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    expires_at = raw.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
                return None
        except (TypeError, ValueError):
            return None
    return raw.get("value")
