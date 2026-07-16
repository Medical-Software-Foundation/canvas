"""Batch loaders for lab observations and vital signs, plus unit conversion.

Pure functions over the Django ORM — no dependency on the SimpleAPI instance.
"""

from django.db.models import F

from canvas_sdk.v1.data.observation import (
    Observation,
    ObservationCoding,
    ObservationComponent,
    ObservationComponentCoding,
)

# Chunk size for streamed (.iterator) reads of observation history. Bounds
# peak memory to ~chunk rows + the small result dict instead of the patient's
# entire observation history.
_OBS_CHUNK_SIZE = 500


WEIGHT_TO_KG: dict[str, float] = {
    "kg": 1.0, "kgs": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "g": 0.001, "gram": 0.001, "grams": 0.001,
    "lb": 0.45359237, "lbs": 0.45359237,
    "pound": 0.45359237, "pounds": 0.45359237,
    "oz": 0.028349523125, "ounce": 0.028349523125, "ounces": 0.028349523125,
}

HEIGHT_TO_M: dict[str, float] = {
    "m": 1.0, "meter": 1.0, "meters": 1.0,
    "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
    "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254, '"': 0.0254,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
}


def to_kilograms(value: float, units: str) -> float | None:
    """Convert weight to kg. Returns None for unknown units."""
    key = (units or "").strip().lower()
    # Default to kg if units are missing — Canvas stores metric by default
    if not key:
        return value
    factor = WEIGHT_TO_KG.get(key)
    return value * factor if factor is not None else None


_OZ_PER_LB = 16
_KG_TO_OZ = 1.0 / 0.028349523125  # ounces per kilogram


def format_weight_lb_oz(value: str, units: str) -> str:
    """Render a weight as whole 'X lb Y oz', converting from any known unit.

    Canvas stores weight in ounces; this normalizes via kg so any source unit
    (oz/lb/kg/g) renders consistently. Returns "" when the value is non-numeric
    or the units are unrecognized.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    kg = to_kilograms(numeric, units)
    if kg is None:
        return ""
    total_oz = round(kg * _KG_TO_OZ)
    lb, oz = divmod(total_oz, _OZ_PER_LB)
    return f"{lb} lb {oz} oz"


def to_meters(value: float, units: str) -> float | None:
    """Convert height to meters. Returns None for unknown units."""
    key = (units or "").strip().lower()
    # Default to cm if units are missing — Canvas stores height in cm
    if not key:
        return value * 0.01
    factor = HEIGHT_TO_M.get(key)
    return value * factor if factor is not None else None


def load_observations_batch(
    patient_ids: list[str],
    loinc_codes: list[str],
) -> dict[str, dict[str, dict[str, str]]]:
    """Batch-load most recent lab observations per LOINC code per patient.

    Returns: {loinc_code: {patient_id: {"value": ..., "units": ...}}}
    """
    if not loinc_codes:
        return {}

    codes_set = set(loinc_codes)
    result: dict[str, dict[str, dict[str, str]]] = {c: {} for c in loinc_codes}

    # Stream the coding child table directly, newest-first per (patient, code).
    # Querying ObservationCoding (not Observation + prefetch) avoids Django's
    # duplicate-join trap and lets us select only the columns we need. With
    # .values().iterator() the patient's full observation history is NEVER
    # materialised — peak memory is the result dict + one chunk. The first row
    # seen per (code, patient) is the most recent and wins.
    coding_rows = (
        ObservationCoding.objects.filter(
            code__in=loinc_codes,
            observation__patient__id__in=patient_ids,
            observation__deleted=False,
        )
        # nulls_last is explicit: a NULL effective_datetime must NOT outrank a
        # real-dated observation. Postgres (prod) sorts NULLs first under DESC
        # while SQLite (test) sorts them last — without nulls_last the "first
        # seen wins" pick would silently differ between prod and test.
        .order_by(
            "observation__patient_id",
            "code",
            F("observation__effective_datetime").desc(nulls_last=True),
        )
        .values(
            "code",
            "observation__patient__id",
            "observation__value",
            "observation__units",
        )
        .iterator(chunk_size=_OBS_CHUNK_SIZE)
    )
    for row in coding_rows:
        code = row["code"]
        pid = str(row["observation__patient__id"])
        if code in codes_set and pid not in result[code]:
            result[code][pid] = {
                "value": row["observation__value"] or "",
                "units": row["observation__units"] or "",
            }

    # Fallback: component codings, only for codes with no top-level hit.
    missing_codes = [c for c in loinc_codes if not result[c]]
    if missing_codes:
        missing_set = set(missing_codes)
        comp_rows = (
            ObservationComponentCoding.objects.filter(
                code__in=missing_codes,
                observation_component__observation__patient__id__in=patient_ids,
                observation_component__observation__deleted=False,
            )
            .order_by(
                "observation_component__observation__patient_id",
                "code",
                F("observation_component__observation__effective_datetime").desc(
                    nulls_last=True
                ),
            )
            .values(
                "code",
                "observation_component__observation__patient__id",
                "observation_component__value_quantity",
                "observation_component__value_quantity_unit",
            )
            .iterator(chunk_size=_OBS_CHUNK_SIZE)
        )
        for row in comp_rows:
            code = row["code"]
            pid = str(row["observation_component__observation__patient__id"])
            if code in missing_set and pid not in result[code]:
                result[code][pid] = {
                    "value": row["observation_component__value_quantity"] or "",
                    "units": row["observation_component__value_quantity_unit"] or "",
                }

    return result


def load_vitals_batch(
    patient_ids: list[str],
    vital_names: list[str],
) -> dict[str, dict[str, dict[str, str]]]:
    """Batch-load most recent vital-sign observations per name per patient.

    Vital signs use the Observation.name field (e.g. "weight",
    "blood_pressure") rather than LOINC codes in the codings table.

    Returns: {vital_name: {patient_id: {"value": ..., "units": ...}}}
    """
    if not vital_names:
        return {}

    # BMI is calculated from weight + height, not stored directly
    needs_bmi = "bmi" in vital_names
    query_names = [n for n in vital_names if n != "bmi"]
    if needs_bmi:
        for dep in ("weight", "height"):
            if dep not in query_names:
                query_names.append(dep)

    result: dict[str, dict[str, dict[str, str]]] = {n: {} for n in vital_names}
    # Temporary storage for weight/height used in BMI calc — (value, units)
    bmi_inputs: dict[str, dict[str, tuple[float, str]]] = {}

    if query_names:
        # Stream newest-first per (patient, name); first seen wins. .values()
        # + .iterator() avoids materialising the full vital-sign history (a
        # patient can have one vitals row per visit). Blood pressure is
        # backfilled from components in a single follow-up query rather than a
        # per-observation prefetch.
        rows = (
            Observation.objects.filter(
                patient__id__in=patient_ids,
                category="vital-signs",
                name__in=query_names,
                deleted=False,
            )
            .order_by(
                "patient_id",
                "name",
                F("effective_datetime").desc(nulls_last=True),
            )
            .values("dbid", "patient__id", "name", "value", "units")
            .iterator(chunk_size=_OBS_CHUNK_SIZE)
        )
        seen: set[tuple[str, str]] = set()
        # Latest BP observation (dbid) per patient whose top-level value is
        # empty — backfilled from components below.
        bp_to_backfill: dict[str, int] = {}
        for row in rows:
            pid = str(row["patient__id"])
            name = row["name"]
            key = (pid, name)
            if key in seen:  # already captured the most-recent for this vital
                continue
            seen.add(key)
            value = row["value"] or ""
            units = row["units"] or ""

            if not value and name == "blood_pressure":
                bp_to_backfill[pid] = row["dbid"]

            if name in result:
                result[name][pid] = {"value": value, "units": units}

            # Collect weight/height for BMI calculation (preserve units)
            if needs_bmi and value and name in ("weight", "height"):
                if pid not in bmi_inputs:
                    bmi_inputs[pid] = {}
                if name not in bmi_inputs[pid]:
                    try:
                        bmi_inputs[pid][name] = (float(value), units)
                    except (ValueError, TypeError):
                        pass

        # Backfill blood pressure from components — one query for all BP obs.
        # Ordered by component name (diastolic before systolic), matching the
        # previous prefetch ordering.
        if bp_to_backfill and "blood_pressure" in result:
            parts_by_obs: dict[int, list[str]] = {}
            comp_rows = (
                ObservationComponent.objects.filter(
                    observation_id__in=list(bp_to_backfill.values()),
                )
                .order_by("name")
                .values("observation_id", "value_quantity")
            )
            for c in comp_rows:
                if c["value_quantity"]:
                    parts_by_obs.setdefault(c["observation_id"], []).append(
                        c["value_quantity"]
                    )
            for pid, obs_dbid in bp_to_backfill.items():
                parts = parts_by_obs.get(obs_dbid, [])
                result["blood_pressure"][pid] = {
                    "value": "/".join(parts) if parts else "",
                    "units": "mmHg" if parts else "",
                }

    # Calculate BMI in metric (kg / m²), converting from source units.
    # Units are kept on the value so columns configured with
    # format: "value_units" can render them; convention is to omit
    # them when format: "value" is used.
    if needs_bmi:
        for pid, vals in bmi_inputs.items():
            weight_pair = vals.get("weight")
            height_pair = vals.get("height")
            if not weight_pair or not height_pair:
                continue
            weight_kg = to_kilograms(*weight_pair)
            height_m = to_meters(*height_pair)
            if weight_kg is None or height_m is None or height_m <= 0:
                continue
            bmi_val = weight_kg / (height_m * height_m)
            result["bmi"][pid] = {
                "value": f"{bmi_val:.1f}",
                "units": "kg/m²",
            }

    # Remove helper entries that weren't originally requested
    for dep in ("weight", "height"):
        if dep not in vital_names and dep in result:
            del result[dep]

    return result
