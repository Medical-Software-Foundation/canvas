"""Persisted operator choice of field mapping profile, plus the Custom map.

The field map the sync reads is chosen from three profiles, Default, Secret, and
Custom. Default is the code constant, Secret is the ``SF_FIELD_MAPPING_JSON``
secret, both read only. Custom is the one editable profile and it lives here, in a
single custom data row alongside the active profile pointer. A plugin cannot write
its own secrets at runtime, so an editable map can only live in custom data, the
same wall the sync settings hit. See journal cnv-941/049.

A separate model from ``SyncSettingsRecord`` on purpose, because the settings
writer replaces its whole JSON blob on every save and would clobber any mapping
keys parked beside it. Reading goes through :func:`load_field_mapping_state`,
which always returns a usable state, resolving an unset or stale pointer against
whether the secret is present. The write path stamps ``updated_at`` itself because
a queryset update does not fire ``auto_now``.
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

from salesforce_to_canvas_integration.services.config import secret_field_mapping_set
from salesforce_to_canvas_integration.services.field_mapping import FieldMappingState

# The three profiles. Default and Secret are read only mirrors of their source,
# Custom is the editable profile stored on this row.
PROFILE_DEFAULT = "default"
PROFILE_SECRET = "secret"
PROFILE_CUSTOM = "custom"
VALID_PROFILES = (PROFILE_DEFAULT, PROFILE_SECRET, PROFILE_CUSTOM)

# The singleton is addressed by a fixed key so the writer upserts it
# deterministically rather than accumulating rows.
SINGLETON_KEY = "default"


class FieldMappingRecord(CustomModel):
    # the fixed key that pins the one row
    singleton_key: TextField[str, str] = TextField(default=SINGLETON_KEY)

    # the active profile, one of VALID_PROFILES. Empty means never chosen, which
    # the loader resolves against secret presence.
    profile: TextField[str, str] = TextField(default="")

    # the editable Custom map, a list of {salesforce_field, canvas_target} rows.
    # Canvas target is the stable row identity, the Salesforce field is editable
    # and may be empty, an empty Salesforce field meaning that target does not
    # sync. Stored as a JSON list so row order is preserved.
    custom_mapping: JSONField[list[Any], list[Any]] = JSONField(default=list)

    # stamped on create by auto_now. The write path updates through a queryset,
    # which does not fire auto_now, so that path stamps this explicitly.
    updated_at: DateTimeField[str | datetime, datetime] = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["singleton_key"]),
        ]


def _sanitize_custom(value: Any) -> tuple[tuple[str, str], ...]:
    """Coerce stored custom rows into clean ``(sf_field, target)`` pairs.

    Drops anything that is not a row object carrying a string canvas target,
    keeps empty Salesforce fields because an emptied cell is a deliberate do not
    sync marker the operator can fill back in later.
    """
    if not isinstance(value, list):
        return ()
    rows: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target = item.get("canvas_target")
        if not isinstance(target, str) or not target.strip():
            continue
        sf_field = item.get("salesforce_field")
        sf_clean = sf_field.strip() if isinstance(sf_field, str) else ""
        rows.append((sf_clean, target.strip()))
    return tuple(rows)


def load_field_mapping_state(secrets: dict[str, str]) -> FieldMappingState:
    """Read the singleton and resolve the active profile.

    Always returns a usable state. A missing row, a blank pointer, or a stale
    Secret pointer with no secret present each resolve to Secret when the secret
    is set, otherwise Default. Custom rows fall back to an empty list on corrupt
    storage.
    """
    row = (
        FieldMappingRecord.objects.filter(singleton_key=SINGLETON_KEY)
        .order_by("-updated_at", "-dbid")
        .first()
    )
    has_secret = secret_field_mapping_set(secrets)
    stored = row.profile if row is not None and isinstance(row.profile, str) else ""
    if stored not in VALID_PROFILES:
        stored = PROFILE_SECRET if has_secret else PROFILE_DEFAULT
    if stored == PROFILE_SECRET and not has_secret:
        stored = PROFILE_DEFAULT
    custom = _sanitize_custom(row.custom_mapping) if row is not None else ()
    return FieldMappingState(profile=stored, custom=custom)


def save_field_mapping(
    *,
    profile: str,
    custom_mapping: list[dict[str, str]],
    now: datetime,
) -> None:
    """Upsert the singleton with the active profile and the Custom rows.

    ``auto_now`` only fires on create, and a queryset update does not fire it, so
    the update branch stamps ``updated_at`` with the caller supplied ``now``.
    Direct attribute assignment on a CustomModel instance is blocked in the
    sandbox, so the existing row is rewritten through the queryset rather than
    fetched and mutated. The caller validates the payload before it lands here.
    """
    updated = FieldMappingRecord.objects.filter(singleton_key=SINGLETON_KEY).update(
        profile=profile, custom_mapping=custom_mapping, updated_at=now
    )
    if not updated:
        FieldMappingRecord.objects.create(
            singleton_key=SINGLETON_KEY, profile=profile, custom_mapping=custom_mapping
        )


__all__ = (
    "FieldMappingRecord",
    "FieldMappingState",
    "PROFILE_CUSTOM",
    "PROFILE_DEFAULT",
    "PROFILE_SECRET",
    "SINGLETON_KEY",
    "VALID_PROFILES",
    "load_field_mapping_state",
    "save_field_mapping",
)
