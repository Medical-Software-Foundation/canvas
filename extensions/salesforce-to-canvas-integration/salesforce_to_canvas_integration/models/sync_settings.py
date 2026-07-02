"""Persisted operator settings for the deliberate Salesforce sync.

One singleton row holds every tunable the auto apply evaluator reads, stored in
a single JSON ``data`` column. One JSON column dodges the per field type
restrictions in the custom data DDL pipeline, so adding a setting later never
touches the schema. Reading goes through :func:`load_sync_settings`, which
overlays the stored values onto the :class:`SyncSettings` code defaults from
``services.sync_rules``. A missing row or a missing key yields a full settings
object built entirely from defaults, so the plugin behaves before anyone opens
the Settings tab. See journal cnv-938 entries 030 and 032.

This step ships the schema and the read path only. The write path that upserts
the singleton from the Settings form lands with the settings routes in a later
step, and it must stamp ``updated_at`` itself because a queryset update does not
fire ``auto_now``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import (
    DateTimeField,
    Index,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel

from salesforce_to_canvas_integration.services.sync_rules import (
    DELETE_ACTIONS,
    SyncSettings,
)

# The singleton is addressed by a fixed key so the writer can upsert it
# deterministically rather than accumulating rows. The reader tolerates more
# than one row defensively by taking the most recently stamped.
SINGLETON_KEY = "default"


class SyncSettingsRecord(CustomModel):
    # the fixed key that pins the one settings row
    singleton_key: TextField[str, str] = TextField(default=SINGLETON_KEY)

    # every tunable as one JSON blob, overlaid onto the code defaults on read
    data: JSONField[dict[str, Any], dict[str, Any]] = JSONField(default=dict)

    # stamped on create by auto_now. The later write path updates through a
    # queryset, which does not fire auto_now, so that path stamps this column
    # explicitly. See the module docstring.
    updated_at: DateTimeField[str | datetime, datetime] = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["singleton_key"]),
        ]


def load_sync_settings() -> SyncSettings:
    """Read the singleton and overlay it on the code defaults.

    Returns a full :class:`SyncSettings` no matter the stored state. A missing
    row, a non dict payload, a missing key, or a value that fails its type or
    membership check each falls back to that field's code default, so the result
    is always usable and never raises on corrupt storage.
    """
    row = (
        SyncSettingsRecord.objects.filter(singleton_key=SINGLETON_KEY)
        .order_by("-updated_at", "-dbid")
        .first()
    )
    data = row.data if row is not None and isinstance(row.data, dict) else {}
    return _overlay(data)


def _overlay(data: dict[str, Any]) -> SyncSettings:
    defaults = SyncSettings()
    return SyncSettings(
        auto_create=_as_bool(data.get("auto_create"), defaults.auto_create),
        auto_modify=_as_bool(data.get("auto_modify"), defaults.auto_modify),
        auto_delete=_as_bool(data.get("auto_delete"), defaults.auto_delete),
        delete_action=_as_delete_action(
            data.get("delete_action"), defaults.delete_action
        ),
        required_fields=_as_str_tuple(
            data.get("required_fields"), defaults.required_fields
        ),
        address_group_integrity=_as_bool(
            data.get("address_group_integrity"), defaults.address_group_integrity
        ),
        validity_checks=_as_bool(
            data.get("validity_checks"), defaults.validity_checks
        ),
    )


def _as_bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _as_delete_action(value: Any, fallback: str) -> str:
    return value if value in DELETE_ACTIONS else fallback


def _as_str_tuple(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return fallback
    if not all(isinstance(item, str) for item in value):
        return fallback
    cleaned = tuple(item for item in value if item.strip())
    return cleaned if cleaned else fallback


def save_sync_settings(data: dict[str, Any], *, now: datetime) -> SyncSettings:
    """Upsert the singleton with the given data blob and return the overlay.

    The write path the Settings form drives. ``auto_now`` only fires on create,
    and a queryset update does not fire it, so the update branch stamps
    ``updated_at`` explicitly with the caller supplied ``now``. Direct attribute
    assignment on a CustomModel instance is blocked in the sandbox, so the
    existing row is rewritten through the queryset rather than fetched and
    mutated. Returns the freshly loaded overlay so the caller echoes exactly what
    a later read will see, never the raw blob. The caller is responsible for
    validating the blob before it lands here. See journal cnv-938/032 and 038.
    """
    updated = SyncSettingsRecord.objects.filter(singleton_key=SINGLETON_KEY).update(
        data=data, updated_at=now
    )
    if not updated:
        SyncSettingsRecord.objects.create(singleton_key=SINGLETON_KEY, data=data)
    return load_sync_settings()


__all__ = (
    "SINGLETON_KEY",
    "SyncSettingsRecord",
    "load_sync_settings",
    "save_sync_settings",
)
