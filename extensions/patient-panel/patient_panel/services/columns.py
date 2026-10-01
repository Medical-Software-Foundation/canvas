"""Column configuration: PANEL_CONFIG parsing, flag labels, user prefs, and
metadata-field validation.

Pure functions taking `secrets` (and, where needed, a `cache` object) so they
have no dependency on the SimpleAPI instance. Cache access is the caller's
responsibility — these never call get_cache() themselves.
"""

import json
from typing import Any


DEFAULT_FLAG_LABELS: dict[str, str] = {
    "green": "Green",
    "yellow": "Yellow",
    "red": "Red",
}

DEFAULT_COLUMNS: list[dict[str, Any]] = [
    # --- Visible by default ---
    {"type": "built-in", "key": "patient", "visible": True, "label": "Patient", "sortable": True, "sort_key": "patient"},
    {"type": "built-in", "key": "care_team", "visible": True, "label": "Care Team"},
    {"type": "built-in", "key": "last_visit", "visible": True, "label": "Last Visit", "sortable": True, "sort_key": "last_visit"},
    {"type": "built-in", "key": "next_visit", "visible": False, "label": "Next Visit", "sortable": True, "sort_key": "next_visit"},
    {"type": "built-in", "key": "facility", "visible": True, "label": "Facility"},
    {"type": "built-in", "key": "room", "visible": True, "label": "Room", "sortable": True, "sort_key": "room"},
    {"type": "built-in", "key": "tasks", "visible": True, "label": "Tasks", "sortable": True, "sort_key": "tasks"},
    {"type": "built-in", "key": "gaps", "visible": True, "label": "Gaps", "sortable": True, "sort_key": "gaps"},
    {"type": "built-in", "key": "insurance", "visible": True, "label": "Insurance"},
    {"type": "built-in", "key": "caption", "visible": True, "label": "Clinical Caption"},
    # --- Hidden by default (opt-in via PANEL_CONFIG) ---
    {"type": "built-in", "key": "mrn", "visible": False, "label": "MRN"},
    {"type": "built-in", "key": "phone", "visible": False, "label": "Phone"},
    {"type": "built-in", "key": "email", "visible": False, "label": "Email"},
    {"type": "built-in", "key": "address", "visible": False, "label": "Address"},
    {"type": "built-in", "key": "default_provider", "visible": False, "label": "Default Provider"},
    {"type": "built-in", "key": "conditions", "visible": False, "label": "Conditions"},
    {"type": "built-in", "key": "medications", "visible": False, "label": "Medications"},
    {"type": "built-in", "key": "allergies", "visible": False, "label": "Allergies"},
    {"type": "built-in", "key": "referrals", "visible": False, "label": "Referrals"},
    {"type": "built-in", "key": "active_status", "visible": False, "label": "Status"},
]

# Lookup for enriching user-provided built-in columns with labels/sort info
BUILTIN_COLUMN_DEFAULTS: dict[str, dict[str, Any]] = {
    c["key"]: c for c in DEFAULT_COLUMNS
}


def get_flag_color_labels(secrets: dict[str, Any]) -> dict[str, str]:
    """Resolve flag color labels from the `FLAG_COLOR_LABELS` secret.

    Format: JSON dict like `{"red": "Urgent", "yellow": "Follow-up",
    "green": "On track"}`. Missing keys fall back to the capitalized color name.
    """
    raw = secrets.get("FLAG_COLOR_LABELS")
    labels: dict[str, str] = dict(DEFAULT_FLAG_LABELS)
    if not isinstance(raw, str) or not raw.strip():
        return labels
    try:
        parsed = json.loads(raw.strip().strip("'\""))
    except (json.JSONDecodeError, TypeError):
        return labels
    if not isinstance(parsed, dict):
        return labels
    for color in ("green", "yellow", "red"):
        value = parsed.get(color)
        if isinstance(value, str) and value.strip():
            labels[color] = value.strip()
    return labels


def normalize_metadata_column(col: dict[str, Any]) -> dict[str, Any]:
    """Repair metadata-column key/path pairs from PANEL_CONFIG.

    Accepts both shapes:
      {"key": "consent_signatures", "path": "consents.ide-gas.status"}
      {"key": "consent_signatures.consents.ide-gas.status"}  (shorthand)

    Strips whitespace from key/path. When the key contains a dot and no
    explicit path is set, splits on the first dot: the segment before becomes
    the metadata record key, the rest becomes the dotted path. This keeps the
    rendered CSS class name (`col-<key>`) valid.
    """
    normalized = dict(col)
    key = str(normalized.get("key", "")).strip()
    path = str(normalized.get("path", "")).strip()

    if "." in key and not path:
        head, _, tail = key.partition(".")
        key = head.strip()
        path = tail.strip()

    normalized["key"] = key
    if path:
        normalized["path"] = path
    elif "path" in normalized:
        normalized["path"] = ""
    return normalized


def default_columns(visible_only: bool) -> list[dict[str, Any]]:
    """Fallback column set when PANEL_CONFIG is absent/invalid."""
    if visible_only:
        return [c for c in DEFAULT_COLUMNS if c.get("visible", True)]
    return [dict(c) for c in DEFAULT_COLUMNS]


def parse_org_columns(secrets: dict[str, Any], visible_only: bool) -> list[dict[str, Any]]:
    """Parse PANEL_CONFIG into enriched column dicts.

    visible_only=True drops columns with visible=False (the runtime layout);
    visible_only=False returns every column with its visibility flag intact
    (the column picker). Both share PANEL_CONFIG parsing, the DEFAULT_COLUMNS
    fallback, and built-in/metadata enrichment.
    """
    raw = secrets.get("PANEL_CONFIG")
    if not raw or not isinstance(raw, str) or not raw.strip():
        return default_columns(visible_only)

    cleaned = raw.strip().strip("'\"")
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return default_columns(visible_only)

    columns = parsed.get("columns") if isinstance(parsed, dict) else None
    if not isinstance(columns, list):
        return default_columns(visible_only)

    result = []
    for col in columns:
        if visible_only and not col.get("visible", True):
            continue
        # Enrich built-in columns with defaults (label, sortable, sort_key)
        if col.get("type", "built-in") == "built-in":
            defaults = BUILTIN_COLUMN_DEFAULTS.get(col.get("key", ""))
            # Unknown built-in keys have no resolver/label — rendering them
            # produces dead columns (empty header, `—` cells). Drop them.
            # Metadata-backed fields (e.g. services/risk) belong under
            # type "metadata", not "built-in".
            if defaults is None:
                continue
            result.append({**defaults, **col})
        else:
            enriched = (
                normalize_metadata_column(col)
                if col.get("type") == "metadata"
                else dict(col)
            )
            if "label" not in enriched:
                enriched["label"] = (
                    str(enriched.get("key", "")).replace("_", " ").title()
                )
            result.append(enriched)
    return result


def get_panel_config(secrets: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse PANEL_CONFIG secret. Returns visible columns only."""
    return parse_org_columns(secrets, visible_only=True)


def get_all_org_columns(secrets: dict[str, Any]) -> list[dict[str, Any]]:
    """Get ALL columns from PANEL_CONFIG including hidden ones (column picker)."""
    return parse_org_columns(secrets, visible_only=False)


def get_user_column_prefs(cache: Any, staff_id: str) -> dict[str, bool] | None:
    """Load per-user column visibility preferences from the given cache."""
    raw = cache.get(f"column_prefs_{staff_id}")
    if not raw:
        return None
    try:
        prefs = json.loads(raw)
        if isinstance(prefs, dict):
            return prefs
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def get_effective_columns(
    secrets: dict[str, Any], cache: Any, staff_id: str
) -> list[dict[str, Any]]:
    """Columns with per-user preferences overlaid on org defaults.

    Resolution: org columns -> overlay user visibility -> return visible only.
    Falls back to org defaults if no user preferences exist.
    """
    org_columns = get_all_org_columns(secrets)
    user_prefs = get_user_column_prefs(cache, staff_id)

    if not user_prefs:
        return [c for c in org_columns if c.get("visible", True)]

    result = []
    for col in org_columns:
        key = col["key"]
        visible = user_prefs.get(key, col.get("visible", True))
        if visible:
            result.append({**col, "visible": True})
    return result


def get_editable_metadata_field(secrets: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Return the METADATA_FIELDS entry for `key` iff editable=True."""
    raw = secrets.get("METADATA_FIELDS", "") if secrets else ""
    if not raw or not isinstance(raw, str):
        return None
    try:
        config = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(config, list):
        return None
    for entry in config:
        if not isinstance(entry, dict):
            continue
        if entry.get("key") != key:
            continue
        if not entry.get("editable", False):
            return None
        return entry
    return None


def resolve_inline_edit(
    col: dict[str, Any], secrets: dict[str, Any]
) -> dict[str, Any] | None:
    """Return an inline-edit descriptor for a metadata column, or None.

    A descriptor is ``{"type": "SELECT"|"TEXT"|"DATE", "options": [...]}`` and
    is returned ONLY when inline-editing the cell is safe. The edit endpoint
    upserts the WHOLE metadata value for ``col[key]``, so a column is editable
    only when its rendered value IS that whole value:

      - it is a ``metadata`` column declared ``editable: true`` in
        METADATA_FIELDS (via get_editable_metadata_field);
      - it has NO dotted ``path`` — editing a nested path would clobber the
        surrounding JSON blob;
      - it does not use ``render: "tags"`` — that value is a pipe-joined list a
        single-value upsert would clobber;
      - for ``SELECT``, METADATA_FIELDS declares a non-empty ``options`` list
        (the same set the endpoint validates against; never the column's
        ``sort_order``).
    """
    if col.get("type") != "metadata":
        return None
    if col.get("path"):
        return None
    if col.get("render") == "tags":
        return None
    key = col.get("key", "")
    if not key:
        return None

    field = get_editable_metadata_field(secrets, key)
    if field is None:
        return None

    field_type = str(field.get("type", "TEXT")).upper()
    if field_type == "SELECT":
        options = [str(o) for o in (field.get("options") or [])]
        if not options:
            return None
        return {"type": "SELECT", "options": options}
    if field_type not in ("TEXT", "DATE"):
        return None
    return {"type": field_type, "options": []}


def enrich_columns_for_render(
    columns: list[dict[str, Any]], secrets: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return a copy of `columns` with an `inline_edit` descriptor attached to
    each metadata column that is safe to inline-edit (see resolve_inline_edit).
    Non-editable columns are returned unchanged (no `inline_edit` key). Never
    mutates the input."""
    result: list[dict[str, Any]] = []
    for col in columns:
        edit = resolve_inline_edit(col, secrets)
        result.append({**col, "inline_edit": edit} if edit is not None else dict(col))
    return result


def is_valid_metadata_value(field: dict[str, Any], value: str) -> bool:
    """Validate `value` against the field's declared input type."""
    # Empty value always clears the field — allow regardless of type.
    if value == "":
        return True
    field_type = str(field.get("type", "TEXT")).upper()
    if field_type == "SELECT":
        options = field.get("options") or []
        if not isinstance(options, list):
            return False
        return value in {str(o) for o in options}
    # TEXT and DATE accept any non-empty string; deeper DATE format validation
    # is the caller's concern (the form widget enforces it).
    return True
