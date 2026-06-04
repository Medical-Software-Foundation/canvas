"""SimpleAPI route serving the PREVENT calculator modal.

Endpoints:
  GET  /calculator?patient_id=<id>  → renders the pre-filled HTML modal
  POST /calculate?patient_id=<id>   → accepts edited inputs, returns risk
                                       scores, emits Observation effects for
                                       the 10-year scores.
"""

import datetime
import json
from http import HTTPStatus
from typing import Any, Optional, Union

from canvas_sdk.effects import Effect
from canvas_sdk.effects.observation import CodingData, Observation
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from logger import log

from prevent_calculator.services.chart_data import (
    _latest_observation_by_name,
    chart_prefill_to_dict,
    fetch_chart_prefill,
)
from prevent_calculator.services.equations import (
    PreventInput,
    PreventResult,
    compute_prevent,
    compute_prevent_base,
)
from prevent_calculator.services.equations_full import has_any_enhanced_input
from prevent_calculator.services.loinc import (
    LOINC_10YR_ASCVD_RISK,
    LOINC_10YR_HF_RISK,
    LOINC_10YR_TOTAL_CVD_RISK,
    LOINC_30YR_ASCVD_RISK,
    LOINC_30YR_HF_RISK,
    LOINC_30YR_TOTAL_CVD_RISK,
    LOINC_BMI,
    LOINC_BP_PANEL,
    LOINC_EGFR_2021,
    LOINC_HBA1C,
    LOINC_HDL_CHOLESTEROL,
    LOINC_TOTAL_CHOLESTEROL,
    LOINC_UACR,
)


class PreventCalculatorAPI(StaffSessionAuthMixin, SimpleAPI):
    """SimpleAPI exposing the calculator modal and POST endpoint."""

    @api.get("/calculator")
    def render_calculator(self) -> list[Response | Effect]:
        """Render the calculator modal pre-filled from the patient chart."""
        patient_id = self.request.query_params.get("patient_id") or ""
        if not patient_id:
            return [
                JSONResponse(
                    content={"error": "patient_id query parameter is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            prefill = fetch_chart_prefill(patient_id)
        except Exception:
            log.exception("Failed to fetch PREVENT chart prefill")
            return [
                Response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR),
            ]
        prefill_dict = chart_prefill_to_dict(prefill)
        return [
            HTMLResponse(
                content=render_to_string(
                    "templates/calculator.html",
                    context={
                        "patient_id": patient_id,
                        "prefill_json": _safe_json_for_script(prefill_dict),
                    },
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/calculate")
    def calculate(self) -> list[Response | Effect]:
        """Validate inputs, compute the six PREVENT scores, save 10-yr scores."""
        patient_id = self.request.query_params.get("patient_id") or ""
        if not patient_id:
            return [
                JSONResponse(
                    content={"error": "patient_id query parameter is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            body = self.request.json()
        except Exception:
            return [
                JSONResponse(
                    content={"error": "request body must be valid JSON"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not isinstance(body, dict):
            return [
                JSONResponse(
                    content={"error": "request body must be a JSON object"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        parsed = _parse_inputs(body)
        if isinstance(parsed, dict):
            return [
                JSONResponse(content=parsed, status_code=HTTPStatus.BAD_REQUEST),
            ]

        range_errors = _validate_ranges(parsed)
        if range_errors:
            return [
                JSONResponse(
                    content={
                        "error": "Some inputs are out of the AHA PREVENT valid range.",
                        "field_errors": range_errors,
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        result = compute_prevent(parsed)
        scores_payload = _result_to_payload(result)
        observation_effects = _build_observation_effects(patient_id, result)

        save_inputs = bool(body.get("save_inputs_to_chart"))
        # The frontend tracks which fields the user actually typed into vs.
        # which ones were left at the chart pre-fill, and ships that as a
        # list of JSON-input keys (``total_cholesterol``, ``hba1c``, ...).
        # We only persist values the clinician *added manually* — saving an
        # untouched pre-fill would create a duplicate of the existing
        # source observation. A missing ``modified_fields`` key means the
        # client doesn't support diffing → fall back to "save all filled".
        if "modified_fields" in body and isinstance(body["modified_fields"], list):
            modified_fields: Optional[set] = {
                str(f) for f in body["modified_fields"]
            }
        else:
            modified_fields = None
        input_observation_effects: list = []
        if save_inputs:
            input_observation_effects = _build_input_observation_effects(
                patient_id, parsed, modified_fields=modified_fields
            )

        return [
            *observation_effects,
            *input_observation_effects,
            JSONResponse(
                content={
                    "scores": scores_payload,
                    "model_used": (
                        "full" if has_any_enhanced_input(parsed) else "base"
                    ),
                    "inputs_saved": [
                        _input_save_label(effect) for effect in input_observation_effects
                    ],
                },
                status_code=HTTPStatus.OK,
            ),
        ]


def _safe_json_for_script(payload: Any) -> str:
    """JSON-encode ``payload`` for embedding inside an inline ``<script>`` tag.

    ``json.dumps`` does not escape ``<``, ``>``, ``&``, ``"``, ``'``, or
    line-separator/paragraph-separator characters, so a value containing
    ``</script>`` would break out of the script context — a stored-DOM-XSS
    vector if any chart string ever reaches the prefill dict (today nothing
    does, but the prefill resolvers wrap arbitrary chart data and a future
    addition could). The escape pattern mirrors Django's ``json_script``
    filter and the OWASP guidance for JSON-in-HTML.
    """
    encoded = json.dumps(payload)
    # The LSEP / PSEP search strings use Python ``"\uXXXX"`` escapes
    # rather than the raw invisible Unicode code points so an editor
    # that strips trailing whitespace, normalises file encoding, or
    # "cleans" zero-width characters on save cannot silently turn the
    # replacement into a no-op. A corrupted literal would re-open the
    # XSS vector this helper exists to close, with no test failure
    # (the test file would suffer the same corruption).
    return (
        encoded
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")  # JS line separator (LSEP)
        .replace("\u2029", "\\u2029")  # JS paragraph separator (PSEP)
    )


def _to_int_flag(raw: Any, *, allow_none: bool = False) -> Optional[int]:
    if raw is None:
        return None if allow_none else 0
    if isinstance(raw, bool):
        return 1 if raw else 0
    if isinstance(raw, (int, float)):
        return 1 if int(raw) == 1 else 0
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in {"1", "true", "yes", "y"}:
            return 1
        if v in {"0", "false", "no", "n"}:
            return 0
    return None if allow_none else 0


def _to_float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _validate_ranges(parsed: PreventInput) -> dict:
    """Return per-field error messages for inputs that gate **every** PREVENT
    score. Empty dict means the equation layer can run.

    Only fields that ``compute_prevent_base`` checks via its
    ``common_inputs_ok`` gate are hard-failed here — age, SBP, eGFR — because
    out-of-range values for those nullify all six outputs.

    BMI / TC / HDL are intentionally **not** validated at the API layer.
    Each one only gates a subset of the scores (BMI → HF only;
    TC/HDL/statin → CVD/ASCVD only). Forcing a 400 on those would block
    partial-scoring scenarios that the equation layer is designed to
    handle — e.g. a class-III-obesity patient (BMI ≥ 40) should still
    get the four CVD/ASCVD risks, with the partial-note panel
    explaining that HF needs an in-range BMI.
    """
    errors: dict = {}
    if not (30 <= parsed.age <= 79):
        errors["age"] = "Age must be 30–79 years."
    if not (90 <= parsed.sbp <= 200):
        errors["systolic_bp"] = "Systolic BP must be 90–200 mmHg."
    if parsed.egfr <= 0:
        errors["egfr"] = "eGFR must be greater than 0."
    if parsed.hba1c is not None and not (3.0 <= parsed.hba1c <= 20.0):
        errors["hba1c"] = "HbA1c must be 3.0–20.0%."
    if parsed.uacr is not None and not (0.1 <= parsed.uacr <= 25000):
        errors["uacr"] = "UACR must be 0.1–25000 mg/g."
    if parsed.sdi_decile is not None and (parsed.sdi_decile < 1 or parsed.sdi_decile > 10):
        errors["sdi_decile"] = "SDI decile must be 1–10."
    return errors


def _parse_inputs(body: dict) -> Union[PreventInput, dict]:
    sex = _to_int_flag(body.get("sex"), allow_none=True)
    age = _to_float(body.get("age"))
    sbp = _to_float(body.get("systolic_bp"))
    egfr = _to_float(body.get("egfr"))

    field_errors: dict = {}
    if sex is None:
        field_errors["sex"] = "Sex is required."
    if age is None:
        field_errors["age"] = "Age is required."
    if sbp is None:
        field_errors["systolic_bp"] = "Systolic blood pressure is required."
    if egfr is None:
        field_errors["egfr"] = "eGFR is required."

    if field_errors:
        return {
            "error": "Please fill in the highlighted required field(s).",
            "field_errors": field_errors,
        }

    # The ``field_errors`` early-return above guarantees these are
    # non-None when we reach here; the explicit check narrows the types
    # for mypy and stays in the bytecode under ``python -O`` (an
    # ``assert`` wouldn't).
    if sex is None or age is None or sbp is None or egfr is None:
        raise AssertionError(
            "required fields are None after field_errors early-return — unreachable"
        )

    sdi_raw = body.get("sdi_decile")
    sdi_decile: Optional[int]
    if sdi_raw is None or sdi_raw == "":
        sdi_decile = None
    else:
        try:
            sdi_decile = int(sdi_raw)
        except (TypeError, ValueError):
            sdi_decile = None

    return PreventInput(
        sex=sex,
        age=age,
        tc=_to_float(body.get("total_cholesterol")),
        hdl=_to_float(body.get("hdl_cholesterol")),
        sbp=sbp,
        dm=_to_int_flag(body.get("diabetes")) or 0,
        smoking=_to_int_flag(body.get("smoking")) or 0,
        bmi=_to_float(body.get("bmi")),
        egfr=egfr,
        bptreat=_to_int_flag(body.get("bp_treatment")) or 0,
        statin=_to_int_flag(body.get("statin"), allow_none=True),
        hba1c=_to_float(body.get("hba1c")),
        uacr=_to_float(body.get("uacr")),
        sdi_decile=sdi_decile,
    )


def _result_to_payload(result: PreventResult) -> dict:
    return {
        "risk_10yr_cvd": result.risk_10yr_cvd,
        "risk_10yr_ascvd": result.risk_10yr_ascvd,
        "risk_10yr_hf": result.risk_10yr_hf,
        "risk_30yr_cvd": result.risk_30yr_cvd,
        "risk_30yr_ascvd": result.risk_30yr_ascvd,
        "risk_30yr_hf": result.risk_30yr_hf,
    }


def _build_observation_effects(
    patient_id: str, result: PreventResult
) -> list:
    """Emit one Observation effect per computed PREVENT score.

    Each score is saved as a 'laboratory' Observation so the Canvas chart
    UI surfaces it in the lab section. LOINC codings are attached to the
    two outputs with established LOINC mappings; the remaining four are
    saved with display name only (codings omitted) until LOINC publishes
    PREVENT-specific codes.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    effects = []

    plan = (
        ("PREVENT 10-year Total CVD risk", result.risk_10yr_cvd, LOINC_10YR_TOTAL_CVD_RISK),
        ("PREVENT 10-year ASCVD risk", result.risk_10yr_ascvd, LOINC_10YR_ASCVD_RISK),
        ("PREVENT 10-year Heart Failure risk", result.risk_10yr_hf, LOINC_10YR_HF_RISK),
        ("PREVENT 30-year Total CVD risk", result.risk_30yr_cvd, LOINC_30YR_TOTAL_CVD_RISK),
        ("PREVENT 30-year ASCVD risk", result.risk_30yr_ascvd, LOINC_30YR_ASCVD_RISK),
        ("PREVENT 30-year Heart Failure risk", result.risk_30yr_hf, LOINC_30YR_HF_RISK),
    )

    for display, value, loinc in plan:
        if value is None:
            continue
        codings = None
        if loinc is not None:
            codings = [
                CodingData(
                    code=loinc,
                    display=display,
                    system="http://loinc.org",
                )
            ]
        effect = Observation(
            patient_id=patient_id,
            name=display,
            value=f"{value:.2f}",
            units="%",
            category="laboratory",
            effective_datetime=now,
            codings=codings,
        ).create()
        effects.append(effect)

    return effects


# Numeric inputs that the "Save to chart" checkbox persists. Each tuple is
# ``(PreventInput attr, JSON wire-key, display, LOINC, units, category)``.
# PreventInput uses short attribute names (``tc``, ``hdl``); the JSON wire
# format uses the longer form (``total_cholesterol``, etc.), and the
# frontend's ``modified_fields`` list uses the JSON form — so we carry both.
#
# Categorical fields (sex, diabetes, smoking, bp_treatment, statin) and
# demographics (age, SDI decile) are deliberately omitted — those belong on
# the Patient / Condition / Medication record (or aren't observation-shaped
# at all). Systolic BP is **also** omitted from this plan and handled by
# ``_save_systolic_bp_as_panel`` because Canvas stores BP as a composite
# ``blood_pressure`` panel (LOINC 85354-9, value "<systolic>/<diastolic>"),
# not a standalone systolic row.
#
# Unit strings follow Canvas's native display style (``mmHg``, ``kg/m²``)
# rather than strict UCUM (``mm[Hg]``, ``kg/m2``) so saved values match
# how the rest of the chart renders units.
_INPUT_OBSERVATION_PLAN: tuple = (
    ("tc", "total_cholesterol", "Total cholesterol", LOINC_TOTAL_CHOLESTEROL, "mg/dL", "laboratory"),
    ("hdl", "hdl_cholesterol", "HDL cholesterol", LOINC_HDL_CHOLESTEROL, "mg/dL", "laboratory"),
    ("bmi", "bmi", "Body mass index", LOINC_BMI, "kg/m²", "vital-signs"),
    ("egfr", "egfr", "eGFR (CKD-EPI 2021)", LOINC_EGFR_2021, "mL/min/1.73m²", "laboratory"),
    ("hba1c", "hba1c", "Hemoglobin A1c", LOINC_HBA1C, "%", "laboratory"),
    ("uacr", "uacr", "Urine albumin/creatinine ratio", LOINC_UACR, "mg/g", "laboratory"),
)


def _extract_diastolic_from_bp_value(raw: Any) -> Optional[str]:
    """Pull the diastolic portion out of a Canvas ``blood_pressure``
    observation value string (e.g. ``"128/82"`` → ``"82"``).

    Returns ``None`` if the value isn't in the expected ``systolic/diastolic``
    shape so the caller can skip the save rather than fabricate data.
    """
    if not raw:
        return None
    parts = str(raw).split("/")
    if len(parts) < 2:
        return None
    diastolic = parts[1].strip()
    return diastolic or None


def _save_systolic_bp_as_panel(
    patient_id: str, systolic: float, now: datetime.datetime
) -> Optional[Any]:
    """Emit a Canvas-style composite BP observation for a manually-entered SBP.

    Canvas's native Vitals command stores blood pressure as **one**
    observation with ``name="blood_pressure"`` and ``value="128/82"``
    (LOINC panel 85354-9). Saving a standalone systolic row would put the
    clinician's edit in a different place than the rest of their BP
    history, so we pair the new systolic with the patient's most recent
    recorded diastolic and emit a fresh composite row.

    If the patient has no prior BP observation (so we can't preserve the
    diastolic half), we skip the save — fabricating a "0" diastolic would
    corrupt the chart.
    """
    latest_bp = _latest_observation_by_name(patient_id, "blood_pressure")
    if latest_bp is None:
        return None
    diastolic = _extract_diastolic_from_bp_value(getattr(latest_bp, "value", None))
    if diastolic is None:
        return None
    composite_value = f"{int(round(systolic))}/{diastolic}"
    return Observation(
        patient_id=patient_id,
        name="blood_pressure",
        value=composite_value,
        units="mmHg",
        category="vital-signs",
        effective_datetime=now,
        codings=[
            CodingData(
                code=LOINC_BP_PANEL,
                display="Blood pressure panel with all children optional",
                system="http://loinc.org",
            )
        ],
    ).create()


def _build_input_observation_effects(
    patient_id: str,
    parsed: PreventInput,
    *,
    modified_fields: Optional[set] = None,
) -> list:
    """Emit one Observation effect per **manually-entered** PREVENT input.

    The clinician opts in via the "Save to chart" checkbox; the frontend
    sends the set of fields whose value differs from the chart pre-fill
    (or had no pre-fill) in ``modified_fields``. We only save those —
    re-saving a value that came straight from the chart would create a
    duplicate Observation of an existing source row.

    When ``modified_fields`` is ``None`` (older client without the
    diffing logic), every numeric input is saved as a fallback.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    effects = []

    # Simple LOINC-coded labs / vitals
    for attr, wire_key, display, loinc, units, category in _INPUT_OBSERVATION_PLAN:
        value = getattr(parsed, attr, None)
        if value is None:
            continue
        if modified_fields is not None and wire_key not in modified_fields:
            continue
        codings = [
            CodingData(code=loinc, display=display, system="http://loinc.org")
        ]
        effect = Observation(
            patient_id=patient_id,
            name=display,
            value=f"{value:g}",
            units=units,
            category=category,
            effective_datetime=now,
            codings=codings,
        ).create()
        effects.append(effect)

    # Systolic BP — special case: emit a composite BP-panel observation
    # rather than a standalone systolic so it lives alongside the
    # patient's other BP rows.
    sbp_modified = modified_fields is None or "systolic_bp" in modified_fields
    if sbp_modified and parsed.sbp is not None:
        bp_effect = _save_systolic_bp_as_panel(patient_id, parsed.sbp, now)
        if bp_effect is not None:
            effects.append(bp_effect)

    return effects


def _input_save_label(effect: Any) -> str:
    """Pull the human-readable name off an Observation effect for the response.

    The protobuf payload contains the name; if we can't deserialize it we
    fall back to a generic label so the UI still gets a count. Decode
    failures are logged because they shouldn't happen with effects we
    built ourselves in ``_build_input_observation_effects`` — surfacing
    them keeps the silence from masking an SDK shape change.
    """
    payload = getattr(effect, "payload", None)
    if payload is None:
        return "input"
    try:
        decoded = json.loads(payload)
        return str(decoded.get("name", "input"))
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        # ``AttributeError`` catches a hypothetical SDK change that makes
        # ``effect.payload`` non-string (e.g. a protobuf message where
        # ``.get`` isn't available). The whole point of this fallback is
        # to absorb SDK shape changes without 500'ing the POST response.
        log.warning(
            "Could not decode Observation effect payload for save-inputs label",
            exc_info=True,
        )
        return "input"
