"""Pure chart-extraction for the Medical Chart Review section (spec §4.2).

No HTML, no Effects — just ORM reads shaped into a JSON-serializable dict.
Kept pure so it can be unit-tested with mocked Django querysets.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.patient import Patient

LOINC_SYSTEM = "http://loinc.org"

HEIGHT_LOINC = "8302-2"
WEIGHT_LOINC = "29463-7"

# Curated nutrition-relevant lab panel. Codes confirmed during implementation;
# extend or trim with the customer once we have real chart data to look at.
NUTRITION_LAB_LOINCS: dict[str, str] = {
    # Lipid panel
    "2093-3": "Total Cholesterol",
    "2085-9": "HDL",
    "13457-7": "LDL (calc)",
    "2571-8": "Triglycerides",
    # Glycemic
    "4548-4": "Hemoglobin A1c",
    "2345-7": "Glucose",
    # BMP / renal
    "1751-7": "Albumin",
    "33914-3": "eGFR",
    "2160-0": "Creatinine",
    "2823-3": "Potassium",
    "2951-2": "Sodium",
    # CBC
    "718-7": "Hemoglobin",
    "4544-3": "Hematocrit",
    "26515-7": "Platelets",
    "6690-2": "Leukocytes",
    # Micronutrients
    "1989-3": "Vitamin D 25-OH",
    "2276-4": "Ferritin",
    "2132-9": "Vitamin B12",
    "2601-3": "Magnesium",
}

# Drug-class display-text keywords confirmed by the customer (spec §7.3).
# Match is case-insensitive substring on the medication coding's display text.
NUTRITION_DRUG_CLASS_KEYWORDS: tuple[str, ...] = (
    # GLP-1 agonists
    "glp-1", "glp1", "semaglutide", "tirzepatide", "liraglutide",
    "dulaglutide", "exenatide",
    # Insulin
    "insulin",
    # Oral antidiabetics
    "metformin", "glipizide", "glyburide", "pioglitazone",
    "sitagliptin", "linagliptin", "empagliflozin", "dapagliflozin",
    # Diuretics
    "furosemide", "hydrochlorothiazide", "spironolactone", "chlorthalidone",
    # Corticosteroids
    "prednisone", "methylprednisolone", "dexamethasone", "hydrocortisone",
    # PPIs / H2 blockers
    "omeprazole", "pantoprazole", "esomeprazole", "lansoprazole",
    "famotidine", "ranitidine",
    # Thyroid
    "levothyroxine",
    # Lipid-lowering
    "atorvastatin", "rosuvastatin", "simvastatin", "pravastatin",
    "fenofibrate", "ezetimibe", "evolocumab", "alirocumab",
)


def get_age(birth_date: date | None, today: date | None = None) -> int | None:
    if not birth_date:
        return None
    today = today or date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(years, 0)


def _first_coding(obj: Any) -> Any:
    """Return the first coding on `obj`, using the prefetch cache when one
    is available. Calling `obj.codings.first()` would issue a separate
    `LIMIT 1` query per object even when `prefetch_related("codings")` is
    in play; iterating `obj.codings.all()` reads from the prefetched
    cache instead."""
    codings = getattr(obj, "codings", None)
    if codings is None:
        return None
    if not hasattr(codings, "all"):
        # Fall back for non-ORM mock-style objects in tests.
        return codings.first() if hasattr(codings, "first") else None
    cached = list(codings.all())
    return cached[0] if cached else None


def get_anthropometrics(patient_id: str) -> dict[str, Any]:
    """Latest height + weight observations (raw values, units passthrough)."""
    rows = list(
        Observation.objects.filter(
            patient__id=patient_id,
            codings__code__in=[HEIGHT_LOINC, WEIGHT_LOINC],
            codings__system=LOINC_SYSTEM,
            deleted=False,
        )
        .order_by("-effective_datetime")
        .values("codings__code", "value", "units", "effective_datetime")
    )

    out: dict[str, Any] = {
        "height": None, "height_units": "", "height_date": "",
        "weight": None, "weight_units": "", "weight_date": "",
    }
    seen: set[str] = set()
    for row in rows:
        code = row.get("codings__code")
        if code in seen or code not in (HEIGHT_LOINC, WEIGHT_LOINC):
            continue
        seen.add(code)
        eff = row.get("effective_datetime")
        eff_date = eff.date().isoformat() if eff else ""
        if code == HEIGHT_LOINC:
            out["height"] = row.get("value")
            out["height_units"] = row.get("units") or ""
            out["height_date"] = eff_date
        else:
            out["weight"] = row.get("value")
            out["weight_units"] = row.get("units") or ""
            out["weight_date"] = eff_date
        if len(seen) == 2:
            break
    return out


def get_pmh(patient_id: str) -> list[dict[str, str]]:
    """Active conditions (PMH). Returns ICD-10/SNOMED codings + display."""
    conditions = (
        Condition.objects.for_patient(patient_id)
        .filter(clinical_status="active", deleted=False)
        .order_by("-onset_date")
        # Prefetch codings so `_first_coding(c)` reads from the cache rather
        # than firing a per-condition `.first()` query (was an N+1 pattern).
        .prefetch_related("codings")
    )
    out: list[dict[str, str]] = []
    for c in conditions:
        coding = _first_coding(c)
        if not coding:
            continue
        display = (getattr(coding, "display", "") or "").strip()
        if not display:
            continue
        out.append({
            "code": getattr(coding, "code", "") or "",
            "system": getattr(coding, "system", "") or "",
            "display": display,
        })
    return out


def get_allergies(patient_id: str) -> list[dict[str, str]]:
    allergies = (
        AllergyIntolerance.objects.for_patient(patient_id)
        .filter(status="active", deleted=False)
        .prefetch_related("codings")
    )
    out: list[dict[str, str]] = []
    for a in allergies:
        coding = _first_coding(a)
        display = ""
        if coding:
            display = (getattr(coding, "display", "") or "").strip()
        narrative = (getattr(a, "narrative", "") or "").strip()
        label = display or narrative
        if not label:
            continue
        out.append({
            "display": label,
            "narrative": narrative,
            "severity": (getattr(a, "severity", "") or "").strip(),
        })
    return out


def _matches_nutrition_drug_class(display: str) -> bool:
    haystack = (display or "").lower()
    return any(kw in haystack for kw in NUTRITION_DRUG_CLASS_KEYWORDS)


def get_nutrition_medications(patient_id: str) -> list[dict[str, str]]:
    """Active meds filtered to the curated nutrition-relevant drug classes.

    Uses the manager's `.active()` queryset method instead of
    `.filter(status="active")`: `Medication.status="active"` matches any
    record not explicitly stopped (expired prescriptions, supplies, historic
    entries with no end_date), which surfaces the patient's full medication
    ledger instead of what the chart sidebar shows. `.active()` applies the
    canonical status + start/end-date logic.
    """
    meds = (
        Medication.objects.for_patient(patient_id)
        .active()
        .filter(deleted=False, entered_in_error__isnull=True)
        .prefetch_related("codings")
    )
    out: list[dict[str, str]] = []
    for m in meds:
        coding = _first_coding(m)
        display = (getattr(coding, "display", "") if coding else "") or ""
        display = display.strip()
        if not display or not _matches_nutrition_drug_class(display):
            continue
        out.append({"display": display})
    return out


def get_recent_nutrition_labs(
    patient_id: str,
    *,
    today: date | None = None,
    days: int = 90,
) -> list[dict[str, Any]]:
    """Most recent value per LOINC code in the last `days` days (default 90)."""
    today = today or date.today()
    since = today - timedelta(days=days)
    rows = list(
        Observation.objects.filter(
            patient__id=patient_id,
            codings__code__in=list(NUTRITION_LAB_LOINCS.keys()),
            codings__system=LOINC_SYSTEM,
            deleted=False,
            effective_datetime__gte=since,
        )
        .order_by("-effective_datetime")
        .values("codings__code", "value", "units", "effective_datetime")
    )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        code = row.get("codings__code")
        if code in seen or code not in NUTRITION_LAB_LOINCS:
            continue
        seen.add(code)
        eff = row.get("effective_datetime")
        out.append({
            "code": code,
            "label": NUTRITION_LAB_LOINCS[code],
            "value": row.get("value"),
            "units": row.get("units") or "",
            "effective_date": eff.date().isoformat() if eff else "",
        })
    return out


def build_chart_review(
    patient_id: str,
    *,
    today: date | None = None,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single entry point: returns the JSON-serializable chart-review payload.

    Pass a `cache` dict scoped to one HTTP request to share the result with
    other call sites in the same request. The cache is keyed by patient_id;
    a new dict per request keeps results from leaking between requests.
    """
    if cache is not None and patient_id in cache:
        cached: dict[str, Any] = cache[patient_id]
        return cached
    payload = _build_chart_review_uncached(patient_id, today=today)
    if cache is not None:
        cache[patient_id] = payload
    return payload


def _build_chart_review_uncached(
    patient_id: str, *, today: date | None = None,
) -> dict[str, Any]:
    if not patient_id:
        return {"missing": True, "patient_id": ""}
    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        return {"missing": True, "patient_id": patient_id}

    return {
        "missing": False,
        "patient_id": patient_id,
        "age": get_age(getattr(patient, "birth_date", None), today=today),
        "sex": (getattr(patient, "sex_at_birth", "") or "").strip(),
        "anthropometrics": get_anthropometrics(patient_id),
        "pmh": get_pmh(patient_id),
        "allergies": get_allergies(patient_id),
        "labs": get_recent_nutrition_labs(patient_id, today=today),
        "medications": get_nutrition_medications(patient_id),
    }
