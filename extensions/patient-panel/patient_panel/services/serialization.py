"""Per-row serialization: turn a Patient model into a template-ready dict
driven by the column configuration.

`get_builtin_column` and `process_patient` take a `ctx` dict supplied by the
controller so the class keeps ownership of instance/cache state (BASE_PATH,
tz-bound format_local, care-team reader). Pure formatting helpers are imported
directly from services.formatting.
"""

import json
from typing import Any

import arrow

from patient_panel.services.formatting import (
    compare_threshold,
    format_primary_address,
    get_coverage,
    get_flag_color,
    is_patient_flagged,
)
from patient_panel.services.observations import format_weight_lb_oz


def resolve_metadata_value(raw: str, path: str) -> str:
    """Resolve a metadata value, optionally traversing a dotted path.

    If the value is a JSON dict/list and a path is given, walk into it.
    Without a path, dicts/lists are rendered as JSON.

    Examples:
        path=""               → '{"key1": ...}'  (full JSON)
        path="ide-gas.status" → "signed"
    """
    # Try to parse as JSON
    parsed: Any = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        # RecursionError (deeply nested JSON) is a RuntimeError subclass,
        # not a JSONDecodeError — catch it so one pathological metadata
        # value can't crash the row/table render.
        except (json.JSONDecodeError, TypeError, RecursionError):
            return raw

    # Walk the dotted path
    if path:
        segments = path.split(".")
        for i, segment in enumerate(segments):
            if isinstance(parsed, dict):
                parsed = parsed.get(segment)
            elif isinstance(parsed, list):
                if segment == "*":
                    # Wildcard: map remaining path over every element
                    remaining = ".".join(segments[i + 1:])
                    parts = []
                    for item in parsed:
                        if remaining:
                            val = resolve_metadata_value(
                                json.dumps(item) if isinstance(item, (dict, list)) else str(item),
                                remaining,
                            )
                        else:
                            val = str(item) if item is not None else ""
                        if val:
                            parts.append(val)
                    return ", ".join(parts)
                try:
                    parsed = parsed[int(segment)]
                except (ValueError, IndexError):
                    return ""
            else:
                return ""
            if parsed is None:
                return ""
        return str(parsed)

    # No path — render the full JSON
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed)
    return str(parsed)


def get_builtin_column(
    key: str,
    patient: Any,
    secrets: dict[str, Any],
    metadata_by_key: dict[str, Any] | None,
    ctx: dict[str, Any],
) -> Any:
    """Get data for a built-in column key.

    `ctx` carries controller-owned state: base_path, prefix, cache_bust,
    format_local (tz-bound callable), get_care_team.
    """
    if key == "patient":
        # Include the module-load cache-bust so a redeploy invalidates the
        # browser's cached 302→default-avatar response (Cache-Control:
        # public, max-age=3600). Without this, a browser that cached the
        # fallback continues to render it for up to an hour after the
        # server-side cache has been corrected.
        photo_url = f"{ctx['base_path']}{ctx['prefix']}/{patient.id}/photo?v={ctx['cache_bust']}"
        return {
            "photo_url": photo_url,
            "name": f"{patient.first_name} {patient.last_name}"
            + (f" ({patient.nickname})" if patient.nickname else ""),
            "age": int(patient.age_at(arrow.now())),
            "gender": patient.sex_at_birth,
            "dob": (
                arrow.get(patient.birth_date).format("M/D/YYYY")
                if patient.birth_date
                else ""
            ),
            "is_flagged": is_patient_flagged(patient, metadata_by_key),
            "flag_color": get_flag_color(patient, metadata_by_key),
        }
    elif key == "care_team":
        return ctx["get_care_team"](patient)
    elif key == "last_visit":
        # `last_visit_ann` is the datetime of the most recent billable visit,
        # computed as a subquery in build_base_queryset (replaces the old
        # get_last_visit loop over a full notes prefetch).
        last_visit_dt = getattr(patient, "last_visit_ann", None)
        return {
            "date": (
                ctx["format_local"](last_visit_dt, "MM.DD.YYYY")
                if last_visit_dt
                else None
            ),
            "color": (
                f"highlight-{compare_threshold(last_visit_dt, secrets)}"
                if last_visit_dt
                else None
            ),
        }
    elif key == "facility":
        return patient.facility_name_ann
    elif key == "room":
        return patient.room_number_ann or ""
    elif key == "tasks":
        return {"all": patient.tasks_all_count, "open": patient.tasks_open_count}
    elif key == "gaps":
        return {"due": patient.gaps_due_count, "total": patient.gaps_total_count}
    elif key == "insurance":
        insurance = get_coverage(patient)
        return {
            "name": insurance,
            "logo": (
                secrets.get("insurances_logos", {}).get(insurance) if insurance else None
            ),
        }
    elif key == "caption":
        return patient.clinical_note or ""
    elif key == "next_visit":
        nv = getattr(patient, "next_visit_ann", None)
        return ctx["format_local"](nv, "MM.DD.YYYY") if nv else None
    elif key == "mrn":
        return patient.mrn or ""
    elif key == "phone":
        # Iterate the prefetched telecom cache rather than .filter()
        # (which re-queries). Sort by rank in Python; missing/None rank
        # sorts last so explicit ranks always win.
        phones = sorted(
            (t for t in patient.telecom.all() if t.system == "phone"),
            key=lambda t: (
                getattr(t, "rank", None) is None,
                getattr(t, "rank", 0) or 0,
            ),
        )
        return phones[0].value if phones and phones[0].value else ""
    elif key == "email":
        email = next(
            (t.value for t in patient.telecom.all() if t.system == "email"),
            "",
        )
        return email or ""
    elif key == "address":
        return format_primary_address(patient)
    elif key == "default_provider":
        prov = patient.default_provider
        if prov:
            return f"{prov.first_name} {prov.last_name}"
        return ""
    elif key == "conditions":
        return {"count": getattr(patient, "conditions_count_ann", 0)}
    elif key == "medications":
        return {"count": getattr(patient, "medications_count_ann", 0)}
    elif key == "allergies":
        return {"count": getattr(patient, "allergies_count_ann", 0)}
    elif key == "referrals":
        return {"count": getattr(patient, "referrals_count_ann", 0)}
    elif key == "active_status":
        return "Active" if patient.active else "Inactive"
    return None


def process_patient(
    patient: Any,
    secrets: dict[str, Any],
    columns: list[dict[str, Any]],
    obs_data: dict[str, dict[str, dict[str, str]]],
    vitals_data: dict[str, dict[str, dict[str, str]]] | None,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Process a single patient into a template-ready dict driven by columns."""
    data: dict[str, Any] = {
        "id": patient.id,
        "url": f"/patient/{patient.id}",
    }
    vitals_data = vitals_data or {}

    # Build metadata index once per patient — patient.metadata is prefetched,
    # so this hits the cache. Reused for every metadata column + the daily flag.
    metadata_by_key: dict[str, Any] = {
        m.key: m for m in patient.metadata.all()
    }

    for col in columns:
        key = col["key"]
        col_type = col.get("type", "built-in")

        if col_type == "built-in":
            data[key] = get_builtin_column(key, patient, secrets, metadata_by_key, ctx)
        elif col_type == "observation":
            pid = str(patient.id)
            fmt = col.get("format", "value")
            # Try LOINC-based lookup first, then vital-name lookup
            loinc = col.get("loinc", "")
            vital_name = col.get("vital_name", "")
            obs_entry: dict[str, str] = {}
            if loinc:
                obs_entry = obs_data.get(loinc, {}).get(pid, {})
            if not obs_entry and vital_name:
                obs_entry = vitals_data.get(vital_name, {}).get(pid, {})
            value = obs_entry.get("value", "")
            units = obs_entry.get("units", "")
            if fmt == "weight_lb_oz" and value:
                data[key] = format_weight_lb_oz(value, units)
            elif fmt == "value_units" and value and units:
                data[key] = f"{value} {units}"
            else:
                data[key] = value
        elif col_type == "metadata":
            meta = metadata_by_key.get(key)
            if not meta:
                data[key] = [] if col.get("render") == "tags" else ""
            else:
                raw = meta.value
                path = col.get("path", "")
                resolved = resolve_metadata_value(raw, path)
                if col.get("render") == "tags":
                    data[key] = [
                        part.strip()
                        for part in str(resolved).split("|")
                        if part.strip()
                    ]
                else:
                    data[key] = resolved

    # Build columns_data for easy template iteration
    columns_data = []
    for col in columns:
        columns_data.append({
            **col,
            "value": data.get(col["key"]),
        })
    data["columns_data"] = columns_data

    return data
