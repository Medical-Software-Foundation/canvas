"""Pull the latest matching chart values for the PREVENT calculator pre-fill.

Each helper returns a ``ChartValue`` (value + clinical date) so the UI can
flag stale data with a warning. Returns ``None`` when nothing matched.

The Canvas plugin sandbox rejects PEP-604 union annotations on dataclass
fields and on some module-level signatures, so this module uses plain
``Any``/``Optional[T]`` annotations and avoids ``frozen=True``.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional, Tuple

import arrow

from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import InterviewQuestionResponse

from prevent_calculator.services.loinc import (
    LOINC_BMI,
    LOINC_BODY_HEIGHT,
    LOINC_BODY_WEIGHT,
    LOINC_EGFR_2021,
    LOINC_EGFR_LEGACY,
    LOINC_HBA1C,
    LOINC_HDL_CHOLESTEROL,
    LOINC_SMOKING_STATUS,
    LOINC_TOBACCO_USE_STATUS,
    LOINC_TOTAL_CHOLESTEROL,
    LOINC_UACR,
)


SMOKING_CURRENT_VALUE_CODES = {
    "449868002",  # Smokes tobacco daily
    "428041000124106",  # Occasional tobacco smoker
    "428071000124103",  # Heavy tobacco smoker
    "428061000124105",  # Light tobacco smoker
    "77176002",  # Smoker (finding)
}

# Known tobacco/smoking-related parent concepts and observation-level codes.
# Used as a fallback when an Observation row carries a SNOMED *coding* (i.e.
# the observation itself is identified by SNOMED, not LOINC) — common with
# CCDA-imported or FHIR-imported rows.
SMOKING_OBSERVATION_SNOMED_CODES = {
    "365980008",  # Tobacco use and exposure - finding
    "365981007",  # Tobacco smoking consumption - finding
    "229819007",  # Tobacco use and exposure
    "230056004",  # Cigarette consumption
    "230058003",  # Pipe consumption (was 230058003 in some catalogs)
    "266918002",  # Tobacco smoking behavior - finding
    "228511007",  # Current non-smoker
}

# Status-value SNOMED codes (i.e. what a tobacco observation's value_coding
# might be) that mean "not a current smoker" — used so we can still
# confidently return value=0 when only these are present.
SMOKING_NON_CURRENT_VALUE_CODES = {
    "266919005",  # Never smoker
    "8517006",    # Former smoker
    "266927001",  # Unknown if ever smoked
    "228511007",  # Current non-smoker
}

DIABETES_ICD10_PREFIXES = ("E10", "E11", "E13")

BP_TREATMENT_NAME_HINTS = (
    "ace inhibitor",
    "angiotensin",
    "beta blocker",
    "calcium channel",
    "diuretic",
    "thiazide",
    "lisinopril",
    "losartan",
    "amlodipine",
    "metoprolol",
    "atenolol",
    "hydrochlorothiazide",
    "valsartan",
    "olmesartan",
    "carvedilol",
    "nifedipine",
    "spironolactone",
    "ramipril",
    "enalapril",
    "irbesartan",
    "candesartan",
    "telmisartan",
    "diltiazem",
    "verapamil",
    "labetalol",
    "propranolol",
    "bisoprolol",
    "chlorthalidone",
    "furosemide",
    "indapamide",
)

STATIN_NAME_HINTS = (
    "statin",
    "atorvastatin",
    "simvastatin",
    "rosuvastatin",
    "pravastatin",
    "lovastatin",
    "fluvastatin",
    "pitavastatin",
)


SOURCE_PATIENT_RECORD = "patient_record"  # Sex, age — from Patient
SOURCE_OBSERVATION = "observation"        # Lab/vital — has a real clinical date
SOURCE_CONDITION = "condition"            # ICD-10 condition — has onset date
SOURCE_MEDICATION = "medication"          # Active medication — has start date
SOURCE_DEFAULT_NO_RECORD = "default_no_record"  # Nothing matched — defaulted to 0


@dataclass
class ChartValue:
    """A pre-filled value plus its provenance.

    ``value`` stays typed as ``Any`` because it deliberately carries a
    union of numeric types depending on the source field — float for
    labs (TC, HDL, eGFR), int for the 0/1 flags (sex, diabetes,
    smoking, bp_treatment, statin), and float for derived BMI. Picking
    one would mis-state the contract for the others.

    `source` tells the UI how to describe the field meta text (e.g.
    "From patient record" vs. "Last value 3/10/2026" vs. "No record
    found"). `clinical_date` is the ISO date for sources where one
    exists; ``None`` for patient-record / default sources.
    """

    value: Any
    clinical_date: Optional[str]
    source: str = SOURCE_OBSERVATION


@dataclass
class ChartPrefill:
    """Snapshot of all PREVENT inputs pulled from the chart."""

    sex: Optional[ChartValue]
    age: Optional[ChartValue]
    total_cholesterol: Optional[ChartValue]
    hdl_cholesterol: Optional[ChartValue]
    systolic_bp: Optional[ChartValue]
    bmi: Optional[ChartValue]
    egfr: Optional[ChartValue]
    diabetes: Optional[ChartValue]
    smoking: Optional[ChartValue]
    bp_treatment: Optional[ChartValue]
    statin: Optional[ChartValue]
    hba1c: Optional[ChartValue] = None
    uacr: Optional[ChartValue] = None


def _today_iso() -> str:
    return arrow.utcnow().date().isoformat()


def _to_iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _try_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# LOINC codes the calculator pulls in a single batched fetch on every
# chart-prefill. Order doesn't matter — the batched helper indexes by code.
_BATCHED_LOINC_CODES: Tuple[str, ...] = (
    LOINC_TOTAL_CHOLESTEROL,
    LOINC_HDL_CHOLESTEROL,
    LOINC_BODY_HEIGHT,
    LOINC_BODY_WEIGHT,
    LOINC_BMI,
    LOINC_EGFR_2021,
    LOINC_EGFR_LEGACY,
    LOINC_HBA1C,
    LOINC_UACR,
    LOINC_TOBACCO_USE_STATUS,
    LOINC_SMOKING_STATUS,
)


def _fetch_latest_observation_by_loinc_set(
    patient_id: str, loinc_codes: Tuple[str, ...]
) -> dict:
    """Pull the latest Observation per LOINC code in **one** database round-trip.

    Without this, ``fetch_chart_prefill`` fires one ``.first()`` query per
    code (TC, HDL, height, weight, BMI, eGFR, HbA1c, UACR, two tobacco
    codes) — ~11 queries. The batched fetch loads every matching
    observation for the patient with the codings prefetched, then walks
    them newest-first in Python to pick the first hit per code.

    Returns a ``{loinc_code: Observation}`` map. Codes with no
    matching observation are simply absent from the dict.
    """
    qs = (
        Observation.objects.for_patient(patient_id)
        .filter(codings__system="http://loinc.org", codings__code__in=loinc_codes)
        .exclude(entered_in_error__isnull=False)
        .distinct()
        .prefetch_related("codings")
        .order_by("-effective_datetime")
    )
    by_code: dict = {}
    target_codes = set(loinc_codes)
    for obs in qs:
        for coding in obs.codings.all():
            if (
                coding.system == "http://loinc.org"
                and coding.code in target_codes
                and coding.code not in by_code
            ):
                by_code[coding.code] = obs
        if len(by_code) >= len(target_codes):
            break
    return by_code


def _latest_observation_by_loinc(
    patient_id: str, loinc_codes: Tuple[str, ...]
) -> Optional[Observation]:
    qs = (
        Observation.objects.for_patient(patient_id)
        .filter(codings__system="http://loinc.org", codings__code__in=loinc_codes)
        .exclude(entered_in_error__isnull=False)
        .order_by("-effective_datetime")
    )
    return qs.first()


def _pick_from_loinc_map(
    loinc_map: Optional[dict], codes: Tuple[str, ...]
) -> Optional[Observation]:
    """Return the most-recent Observation among ``codes`` from a pre-fetched map.

    ``loinc_map`` is the dict returned by
    :func:`_fetch_latest_observation_by_loinc_set`. We pick whichever
    code has the newest ``effective_datetime`` so callers that accept
    multiple equivalent LOINCs (e.g. eGFR 2021 + 2009) still get the
    correct row.
    """
    if not loinc_map:
        return None
    candidates = [loinc_map[c] for c in codes if c in loinc_map]
    if not candidates:
        return None
    return max(candidates, key=lambda obs: obs.effective_datetime or 0)


def _latest_observation_by_name(patient_id: str, name: str) -> Optional[Observation]:
    qs = (
        Observation.objects.for_patient(patient_id)
        .filter(name=name)
        .exclude(entered_in_error__isnull=False)
        .order_by("-effective_datetime")
    )
    return qs.first()


def _resolve_sex(patient: Patient) -> Optional[ChartValue]:
    raw = (patient.sex_at_birth or "").upper()
    if raw == "F":
        return ChartValue(value=1, clinical_date=None, source=SOURCE_PATIENT_RECORD)
    if raw == "M":
        return ChartValue(value=0, clinical_date=None, source=SOURCE_PATIENT_RECORD)
    return None


def _resolve_age(patient: Patient) -> Optional[ChartValue]:
    if not patient.birth_date:
        return None
    age_years = patient.age_at(arrow.utcnow())
    return ChartValue(
        value=round(age_years, 1), clinical_date=None, source=SOURCE_PATIENT_RECORD
    )


def _resolve_total_cholesterol(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_TOTAL_CHOLESTEROL,))
        if loinc_map is not None
        else _latest_observation_by_loinc(patient_id, (LOINC_TOTAL_CHOLESTEROL,))
    )
    if not obs:
        return None
    value = _try_float(obs.value)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


def _resolve_hdl(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_HDL_CHOLESTEROL,))
        if loinc_map is not None
        else _latest_observation_by_loinc(patient_id, (LOINC_HDL_CHOLESTEROL,))
    )
    if not obs:
        return None
    value = _try_float(obs.value)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


def _resolve_systolic_bp(patient_id: str) -> Optional[ChartValue]:
    obs = _latest_observation_by_name(patient_id, "blood_pressure")
    if obs is None or not obs.value:
        return None
    raw = obs.value.split("/")[0].strip()
    value = _try_float(raw)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


_OZ_PER_LB = 16.0
_KG_PER_LB = 0.45359237
_KG_PER_OZ = _KG_PER_LB / _OZ_PER_LB
_M_PER_IN = 0.0254
_M_PER_CM = 0.01


def _weight_to_kg(value: float, units: Any) -> Optional[float]:
    """Convert a weight value to kilograms.

    The Canvas Vitals command stamps ``units="oz"`` on the Observation row
    (LOINC 29463-7) and stores the value as total ounces. FHIR-imported,
    CCDA-imported, and admin-edited rows often leave ``units`` blank and
    record the value in pounds or kilograms instead. When the units string
    is empty we pick the unit by magnitude so a typical adult weight
    isn't misinterpreted as ounces (which would give an absurdly small
    BMI ≈ 1.5).
    """
    if value <= 0:
        return None
    raw = (str(units or "")).strip().lower()
    if raw in ("oz", "ounce", "ounces", "[oz_av]"):
        return value * _KG_PER_OZ
    if raw in ("kg", "kilogram", "kilograms"):
        return value
    if raw in ("g", "gram", "grams"):
        return value / 1000.0
    if raw in ("lb", "lbs", "pound", "pounds", "[lb_av]"):
        return value * _KG_PER_LB
    if raw == "":
        # Empty units → infer from magnitude. Plausible ranges:
        #   kg  ≈ 30–250 (US adults concentrated ~50–100)
        #   lb  ≈ 65–550 (US adults concentrated ~110–250)
        #   oz  ≈ 1000–8800 (Canvas-native vitals)
        #
        # The kg/lb split is the ambiguous one because ~50–150 overlaps
        # both ranges. We pick lb in that overlap because every Canvas
        # deployment we've seen with empty-units weight observations is
        # US data imported in pounds — and misreading a 150 lb adult as
        # 150 kg silently produces BMI ≈ 47 that the sanity guard
        # (10..80) does NOT catch. Threshold 100 keeps the lb path for
        # any value a US adult is likely to record while still treating
        # very low values (<100) as kg in case of European imports —
        # those misclassifications produce BMIs below the sanity guard
        # and fall back to direct-BMI.
        if value >= 1000:
            return value * _KG_PER_OZ  # Canvas-native oz
        if value < 100:
            return value  # kg (pediatric or low-end adult)
        return value * _KG_PER_LB  # lb (US adult default)
    return None


def _height_to_m(value: float, units: Any) -> Optional[float]:
    """Convert a height value to meters.

    The Canvas Vitals command stamps ``units="in"`` on the Observation
    row (LOINC 8302-2). FHIR/CCDA-imported rows often leave units blank
    and store cm or m. We pick the unit by magnitude when units is
    empty so a cm-stored 178 isn't read as 178 inches.
    """
    if value <= 0:
        return None
    raw = (str(units or "")).strip().lower()
    if raw in ("in", "inch", "inches", "[in_i]"):
        return value * _M_PER_IN
    if raw in ("cm", "centimeter", "centimeters"):
        return value * _M_PER_CM
    if raw in ("m", "meter", "meters"):
        return value
    if raw in ("ft", "feet", "[ft_i]"):
        return value * _M_PER_IN * 12.0
    if raw == "":
        # Empty units → infer from magnitude. Plausible adult ranges:
        #   m ≈ 1.4–2.2, in ≈ 48–84, cm ≈ 120–220.
        if value < 3:
            return value  # treat as m
        if value <= 100:
            return value * _M_PER_IN  # treat as inches (Canvas default)
        return value * _M_PER_CM  # treat as cm
    return None


def _resolve_bmi(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    """Resolve BMI for the patient.

    Canvas does not consistently store BMI as its own observation, so we
    prefer to compute it from the latest height and weight observations
    (FHIR vitals). The stored ``body_mass_index`` / LOINC 39156-5
    observations are kept as fallbacks for charts that do record BMI
    directly.
    """
    if loinc_map is not None:
        height_obs = _pick_from_loinc_map(loinc_map, (LOINC_BODY_HEIGHT,))
        weight_obs = _pick_from_loinc_map(loinc_map, (LOINC_BODY_WEIGHT,))
    else:
        height_obs = _latest_observation_by_loinc(patient_id, (LOINC_BODY_HEIGHT,))
        weight_obs = _latest_observation_by_loinc(patient_id, (LOINC_BODY_WEIGHT,))
    if height_obs is None:
        height_obs = _latest_observation_by_name(patient_id, "height")
    if weight_obs is None:
        weight_obs = _latest_observation_by_name(patient_id, "weight")

    if height_obs is not None and weight_obs is not None:
        h_raw = _try_float(height_obs.value)
        w_raw = _try_float(weight_obs.value)
        if h_raw is not None and w_raw is not None:
            h_m = _height_to_m(h_raw, getattr(height_obs, "units", ""))
            w_kg = _weight_to_kg(w_raw, getattr(weight_obs, "units", ""))
            if h_m and w_kg and h_m > 0:
                bmi = w_kg / (h_m * h_m)
                # Sanity guard: if the magnitude heuristics in
                # ``_weight_to_kg`` / ``_height_to_m`` mis-pick units we'd
                # otherwise emit an obviously wrong BMI (e.g. ~1.5 when
                # weight stored in lb is misread as oz). Anything outside
                # the plausible human range falls back to direct-BMI.
                if 10.0 <= bmi <= 80.0:
                    # Use the more recent of the two observations as the
                    # "clinical date" so stale-data flagging makes sense.
                    h_dt = height_obs.effective_datetime
                    w_dt = weight_obs.effective_datetime
                    latest = max(h_dt, w_dt) if (h_dt and w_dt) else (h_dt or w_dt)
                    return ChartValue(
                        value=round(bmi, 1), clinical_date=_to_iso(latest)
                    )

    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_BMI,))
        if loinc_map is not None
        else _latest_observation_by_loinc(patient_id, (LOINC_BMI,))
    )
    if obs is None:
        obs = _latest_observation_by_name(patient_id, "body_mass_index")
    if obs is None:
        return None
    value = _try_float(obs.value)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


def _resolve_egfr(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_EGFR_2021, LOINC_EGFR_LEGACY))
        if loinc_map is not None
        else _latest_observation_by_loinc(
            patient_id, (LOINC_EGFR_2021, LOINC_EGFR_LEGACY)
        )
    )
    if not obs:
        return None
    value = _try_float(obs.value)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


def _resolve_diabetes(patient_id: str) -> Optional[ChartValue]:
    qs = (
        Condition.objects.for_patient(patient_id)
        .active()
        .filter(codings__system__in=("ICD-10", "http://hl7.org/fhir/sid/icd-10-cm"))
        .prefetch_related("codings")
        .order_by("-onset_date")
    )
    for condition in qs:
        codes = [c.code for c in condition.codings.all() if c.code]
        if any(c.startswith(DIABETES_ICD10_PREFIXES) for c in codes):
            return ChartValue(
                value=1,
                clinical_date=_to_iso(condition.onset_date),
                source=SOURCE_CONDITION,
            )
    return ChartValue(value=0, clinical_date=None, source=SOURCE_DEFAULT_NO_RECORD)


def _latest_tobacco_interview_response(patient_id: str) -> Any:
    """Return the most recent committed Tobacco-questionnaire response.

    Canvas's Tobacco questionnaire stores responses against LOINC 39240-7
    in the InterviewQuestionResponse table, not as an Observation row.
    Returns ``None`` if the patient has no committed response.
    """
    qs = (
        InterviewQuestionResponse.objects.filter(
            interview__patient__id=patient_id,
            interview__deleted=False,
            interview__entered_in_error__isnull=True,
            interview__committer__isnull=False,
            question__code=LOINC_TOBACCO_USE_STATUS,
            question__code_system="LOINC",
        )
        .select_related("interview", "response_option")
        .order_by("-interview__id")
    )
    return qs.first()


def _latest_observation_by_snomed(
    patient_id: str, snomed_codes: Tuple[str, ...]
) -> Optional[Observation]:
    """Return the latest non-errored Observation coded with a SNOMED code.

    Mirrors :func:`_latest_observation_by_loinc` but filters on the SNOMED
    code system. Used to pick up tobacco-status Observations that were
    imported with a SNOMED concept code instead of (or alongside) a LOINC
    coding — common with CCDA / FHIR ingestion.
    """
    qs = (
        Observation.objects.for_patient(patient_id)
        .filter(codings__system="http://snomed.info/sct", codings__code__in=snomed_codes)
        .exclude(entered_in_error__isnull=False)
        .order_by("-effective_datetime")
    )
    return qs.first()


def _latest_smoking_observation_by_name(patient_id: str) -> Optional[Observation]:
    """Return the latest Observation whose ``name`` looks tobacco-related.

    Last-resort path for rows that lack both a LOINC and a SNOMED coding
    (admin-edited Observations, custom integrations). The match is a
    case-insensitive substring check on the ``name`` field for either
    "smok" or "tobacco".

    Implemented as two separate queries instead of a ``Q(...) | Q(...)``
    because the Canvas plugin sandbox blocks ``from django.db import
    models`` (and ``from django.db.models import Q``). Picking the more
    recent of the two results matches the union semantics.
    """
    def _latest(needle: str) -> Optional[Observation]:
        return (
            Observation.objects.for_patient(patient_id)
            .filter(name__icontains=needle)
            .exclude(entered_in_error__isnull=False)
            .order_by("-effective_datetime")
            .first()
        )

    smok = _latest("smok")
    tobacco = _latest("tobacco")
    if smok is None:
        return tobacco
    if tobacco is None:
        return smok
    # Both matched — return the more recent
    if (tobacco.effective_datetime or 0) > (smok.effective_datetime or 0):
        return tobacco
    return smok


def _classify_smoking_from_value_codings(obs: Observation) -> Optional[int]:
    """Return 1 (current), 0 (not current), or None (indeterminate) from
    the ``value_codings`` of a tobacco-status observation.

    Treats the AHA-recognised current-smoker SNOMED set as positive and
    the never/former/unknown set as negative. If no codings are
    recognised, returns ``None`` so the caller can fall through.
    """
    value_codes = {c.code for c in obs.value_codings.all() if c.code}
    if not value_codes:
        return None
    if value_codes & SMOKING_CURRENT_VALUE_CODES:
        return 1
    if value_codes & SMOKING_NON_CURRENT_VALUE_CODES:
        return 0
    return None


def _resolve_smoking(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    """Resolve current-smoker flag from Observation or Tobacco questionnaire.

    Canvas may record tobacco status as:

    1. A LOINC-coded Observation (39240-7 or 72166-2) with a SNOMED
       value-coding — Canvas's Tobacco questionnaire path on commit, plus
       any CCDA-imported row using the standard tobacco LOINC.
    2. A SNOMED-coded Observation (no LOINC) — some FHIR ingestion
       pipelines code the observation itself with a SNOMED tobacco-status
       concept rather than the LOINC.
    3. A name-based Observation (e.g. ``name="smoking_status"``,
       ``"tobacco"``) — admin-created rows or third-party integrations.
    4. An ``InterviewQuestionResponse`` against the Tobacco questionnaire
       (LOINC 39240-7) — when the staffer answered the questionnaire but
       Canvas hasn't (yet) materialised an Observation row.

    Most-recent match wins across the four paths; if every path returns
    nothing, the caller leaves the field blank.
    """
    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_TOBACCO_USE_STATUS, LOINC_SMOKING_STATUS))
        if loinc_map is not None
        else _latest_observation_by_loinc(
            patient_id, (LOINC_TOBACCO_USE_STATUS, LOINC_SMOKING_STATUS)
        )
    )
    if obs is None:
        obs = _latest_observation_by_snomed(
            patient_id, tuple(SMOKING_OBSERVATION_SNOMED_CODES)
        )
    if obs is None:
        obs = _latest_smoking_observation_by_name(patient_id)

    if obs is not None:
        classification = _classify_smoking_from_value_codings(obs)
        if classification is not None:
            return ChartValue(
                value=classification,
                clinical_date=_to_iso(obs.effective_datetime),
            )
        # Observation exists but its value_codings are unrecognised — fall
        # through to the questionnaire path before giving up so we can
        # still surface a usable answer when one is available.

    response = _latest_tobacco_interview_response(patient_id)
    if response is None:
        # If we found an unclassifiable observation, surface it as
        # "no record" rather than silently treating the patient as a
        # non-smoker — the UI's default_no_record source tells the user
        # to fill it in.
        return None
    option_code = getattr(response.response_option, "code", "") if response.response_option else ""
    is_current = option_code in SMOKING_CURRENT_VALUE_CODES
    # ``Interview`` exposes ``note_id`` as a raw BigIntegerField, not a FK
    # relation — so ``interview.note`` is not a real attribute. Look up
    # the Note by ID to get the clinical date that the UI needs for the
    # "Last value M/D/YYYY" meta text.
    response_date: Any = None
    note_id = getattr(response.interview, "note_id", None)
    if note_id:
        note_obj = Note.objects.filter(id=note_id).only("datetime_of_service").first()
        if note_obj is not None:
            response_date = note_obj.datetime_of_service
    return ChartValue(
        value=1 if is_current else 0,
        clinical_date=_to_iso(response_date),
    )


def _matches_any(text: str, hints: Tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in hints)


def _fetch_active_medications(patient_id: str) -> list:
    """Pull the patient's active medications once with codings prefetched.

    Both BP-treatment and statin resolution walk the same list looking for
    different name hints, so we materialise it here and pass it in to each
    matcher instead of firing two identical queries per prefill.
    """
    qs = (
        Medication.objects.for_patient(patient_id)
        .active()
        .prefetch_related("codings")
    )
    return list(qs)


def _match_medication_by_hints(
    medications: list, hints: Tuple[str, ...]
) -> ChartValue:
    for med in medications:
        candidates = []
        if getattr(med, "clinical_quantity_description", ""):
            candidates.append(med.clinical_quantity_description)
        for coding in med.codings.all():
            if coding.display:
                candidates.append(coding.display)
        joined = " ".join(candidates)
        if joined and _matches_any(joined, hints):
            return ChartValue(
                value=1,
                clinical_date=_to_iso(med.start_date),
                source=SOURCE_MEDICATION,
            )
    return ChartValue(value=0, clinical_date=None, source=SOURCE_DEFAULT_NO_RECORD)


def _resolve_active_medication_flag(
    patient_id: str, hints: Tuple[str, ...]
) -> ChartValue:
    """Standalone resolver kept for backward compatibility with unit tests
    and any external callers; ``fetch_chart_prefill`` uses the cheaper
    fetch-once-and-match-twice path through ``_fetch_active_medications``.
    """
    return _match_medication_by_hints(_fetch_active_medications(patient_id), hints)


def _resolve_bp_treatment(patient_id: str) -> ChartValue:
    return _resolve_active_medication_flag(patient_id, BP_TREATMENT_NAME_HINTS)


def _resolve_statin(patient_id: str) -> ChartValue:
    return _resolve_active_medication_flag(patient_id, STATIN_NAME_HINTS)


def _resolve_hba1c(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_HBA1C,))
        if loinc_map is not None
        else _latest_observation_by_loinc(patient_id, (LOINC_HBA1C,))
    )
    if not obs:
        return None
    value = _try_float(obs.value)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


def _resolve_uacr(
    patient_id: str, loinc_map: Optional[dict] = None
) -> Optional[ChartValue]:
    obs = (
        _pick_from_loinc_map(loinc_map, (LOINC_UACR,))
        if loinc_map is not None
        else _latest_observation_by_loinc(patient_id, (LOINC_UACR,))
    )
    if not obs:
        return None
    value = _try_float(obs.value)
    if value is None:
        return None
    return ChartValue(value=value, clinical_date=_to_iso(obs.effective_datetime))


def fetch_chart_prefill(patient_id: str) -> ChartPrefill:
    """Resolve every PREVENT input from the patient chart.

    Sex/age come from the Patient record. TC/HDL/eGFR/BMI/SBP/smoking come
    from the most recent matching Observation. Diabetes is read from active
    Conditions; BP treatment and statin from active Medications. Defaults
    to ``0`` with today's date when no record matches, so the form can show
    a sensible value while still letting the user override.

    All LOINC-coded observations are pulled in **one** batched query, and
    the active-medication list is materialised **once** and reused by both
    the BP-treatment and statin matchers — see the database-performance
    review report for the rationale.
    """
    patient = Patient.objects.get(id=patient_id)
    loinc_map = _fetch_latest_observation_by_loinc_set(patient_id, _BATCHED_LOINC_CODES)
    active_meds = _fetch_active_medications(patient_id)
    return ChartPrefill(
        sex=_resolve_sex(patient),
        age=_resolve_age(patient),
        total_cholesterol=_resolve_total_cholesterol(patient_id, loinc_map),
        hdl_cholesterol=_resolve_hdl(patient_id, loinc_map),
        systolic_bp=_resolve_systolic_bp(patient_id),
        bmi=_resolve_bmi(patient_id, loinc_map),
        egfr=_resolve_egfr(patient_id, loinc_map),
        diabetes=_resolve_diabetes(patient_id),
        smoking=_resolve_smoking(patient_id, loinc_map),
        bp_treatment=_match_medication_by_hints(active_meds, BP_TREATMENT_NAME_HINTS),
        statin=_match_medication_by_hints(active_meds, STATIN_NAME_HINTS),
        hba1c=_resolve_hba1c(patient_id, loinc_map),
        uacr=_resolve_uacr(patient_id, loinc_map),
    )


def chart_value_to_dict(value: Any) -> Any:
    if value is None:
        return None
    return {
        "value": value.value,
        "clinical_date": value.clinical_date,
        "source": value.source,
    }


def chart_prefill_to_dict(prefill: ChartPrefill) -> dict:
    return {
        "sex": chart_value_to_dict(prefill.sex),
        "age": chart_value_to_dict(prefill.age),
        "total_cholesterol": chart_value_to_dict(prefill.total_cholesterol),
        "hdl_cholesterol": chart_value_to_dict(prefill.hdl_cholesterol),
        "systolic_bp": chart_value_to_dict(prefill.systolic_bp),
        "bmi": chart_value_to_dict(prefill.bmi),
        "egfr": chart_value_to_dict(prefill.egfr),
        "diabetes": chart_value_to_dict(prefill.diabetes),
        "smoking": chart_value_to_dict(prefill.smoking),
        "bp_treatment": chart_value_to_dict(prefill.bp_treatment),
        "statin": chart_value_to_dict(prefill.statin),
        "hba1c": chart_value_to_dict(prefill.hba1c),
        "uacr": chart_value_to_dict(prefill.uacr),
    }
