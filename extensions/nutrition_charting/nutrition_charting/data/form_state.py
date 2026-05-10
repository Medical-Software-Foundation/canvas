"""Per-note form-state persistence backed by the plugin's AttributeHub.

Each note gets its own AttributeHub keyed by `(NAMESPACE, note_uuid)`. Section
drafts are stored as `section:<section_id>` attributes whose value is the
section's form-data dict (round-trips through CustomAttribute's typed value
columns — JSON dicts are supported).
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import AttributeHub

NAMESPACE = "canvas__nutrition_charting"
SECTION_PREFIX = "section:"
COMMAND_PREFIX = "command:"
MULTI_COMMAND_PREFIX = "multi_commands:"
VISIT_TYPE_KEY = "visit_type"


def _get_or_create_hub(note_uuid: str) -> AttributeHub:
    hub, _ = AttributeHub.objects.get_or_create(type=NAMESPACE, id=note_uuid)
    return hub


def get_form_state(note_uuid: str) -> dict[str, Any]:
    """Return all sections + metadata previously saved for this note."""
    if not note_uuid:
        return {"sections": {}, "visit_type": ""}
    hub = AttributeHub.objects.filter(type=NAMESPACE, id=note_uuid).first()
    if hub is None:
        return {"sections": {}, "visit_type": ""}

    sections: dict[str, Any] = {}
    visit_type = ""
    for attr in hub.custom_attributes.all():
        name = attr.name or ""
        if name.startswith(SECTION_PREFIX):
            sections[name.removeprefix(SECTION_PREFIX)] = attr.value
        elif name == VISIT_TYPE_KEY:
            visit_type = str(attr.value or "")
    return {"sections": sections, "visit_type": visit_type}


def save_section(
    note_uuid: str,
    section_id: str,
    data: dict[str, Any],
    *,
    visit_type: str | None = None,
) -> None:
    """Persist a section's form state. Optionally piggybacks the visit-type
    write onto the same hub fetch so the API's save handler doesn't
    `get_or_create` the same row twice in a row."""
    if not note_uuid or not section_id:
        return
    hub = _get_or_create_hub(note_uuid)
    hub.set_attribute(f"{SECTION_PREFIX}{section_id}", data)
    if visit_type in ("initial", "follow_up"):
        hub.set_attribute(VISIT_TYPE_KEY, visit_type)


def save_visit_type(note_uuid: str, visit_type: str) -> None:
    """Standalone visit-type writer kept for back-compat (and for callers
    that don't have a section payload at hand). The save handler in the
    API layer now passes visit_type through `save_section(...)` instead so
    only one hub write fires."""
    if not note_uuid:
        return
    if visit_type not in ("initial", "follow_up"):
        return
    hub = _get_or_create_hub(note_uuid)
    hub.set_attribute(VISIT_TYPE_KEY, visit_type)


def get_originated_command(note_uuid: str, section_id: str) -> str | None:
    """Return the command_uuid we previously originated for this section,
    or None if this section has not been saved yet on this note."""
    if not note_uuid or not section_id:
        return None
    hub = AttributeHub.objects.filter(type=NAMESPACE, id=note_uuid).first()
    if hub is None:
        return None
    value = hub.get_attribute(f"{COMMAND_PREFIX}{section_id}")
    if not value:
        return None
    return str(value)


def record_originated_command(note_uuid: str, section_id: str, command_uuid: str) -> None:
    """Stash the command_uuid we originated so the next save can `.edit()` it
    in place instead of creating a duplicate command on the note."""
    if not note_uuid or not section_id or not command_uuid:
        return
    hub = _get_or_create_hub(note_uuid)
    hub.set_attribute(f"{COMMAND_PREFIX}{section_id}", command_uuid)


def clear_originated_command(note_uuid: str, section_id: str) -> None:
    """Drop the stashed command_uuid so the next save originates a fresh
    command. Used when we delete the previously-emitted command (e.g. the
    dietician unchecked a gating checkbox)."""
    if not note_uuid or not section_id:
        return
    hub = AttributeHub.objects.filter(type=NAMESPACE, id=note_uuid).first()
    if hub is None:
        return
    hub.custom_attributes.filter(name=f"{COMMAND_PREFIX}{section_id}").delete()


def get_multi_command_map(note_uuid: str, section_id: str) -> dict[str, str]:
    """Return {row_id: command_uuid} for a multi-command section, or {} if no
    rows have been originated yet on this note."""
    if not note_uuid or not section_id:
        return {}
    hub = AttributeHub.objects.filter(type=NAMESPACE, id=note_uuid).first()
    if hub is None:
        return {}
    raw = hub.get_attribute(f"{MULTI_COMMAND_PREFIX}{section_id}")
    if not isinstance(raw, dict):
        return {}
    # Normalize values to strings; AttributeHub round-trips JSON dicts but the
    # contained types are best-effort.
    return {str(k): str(v) for k, v in raw.items() if k and v}


def save_multi_command_map(
    note_uuid: str, section_id: str, mapping: dict[str, str],
) -> None:
    """Persist the {row_id: command_uuid} mapping after a multi-command save."""
    if not note_uuid or not section_id:
        return
    hub = _get_or_create_hub(note_uuid)
    # JSON-friendly dict — set_attribute drops it into the json_value column.
    hub.set_attribute(
        f"{MULTI_COMMAND_PREFIX}{section_id}",
        {str(k): str(v) for k, v in (mapping or {}).items() if k and v},
    )
