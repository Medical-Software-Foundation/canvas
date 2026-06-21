"""ACCESS inspector JSON API: invokes CMS operations and reports alignment state.

The inspector UI is rendered inline by the ACCESS chart-header button; these routes are the JSON API the
inspector's embedded JS calls. All routes are served under the ``/app`` prefix
(``/plugin-io/api/cms_access_fhir_client/app/...``):

    GET  /state                — current ACCESS alignment rows for a patient
    POST /eligibility          — submits $check-eligibility to CMS
    POST /align                — submits $align to CMS
    POST /unalign              — submits $unalign to CMS
    POST /poll                 — polls the stored submission-status URL once

Every CMS-invoking route returns an ``exchange`` object (full request +
response: URL, method, headers, body, status, Content-Location) so the UI can
show exactly what was sent and received — including error bodies — for
troubleshooting.

Authentication: StaffSessionAuthMixin — all routes require a logged-in Canvas staff session.
"""
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from logger import log

from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.questionnaire import Interview

from cms_access_fhir_client.cms_client import (
    align,
    check_eligibility,
    poll_submission_status,
    unalign,
)
from cms_access_fhir_client.cms_client import report_data as submit_report_data
from cms_access_fhir_client.conditions import build_active_conditions, build_track_conditions
from cms_access_fhir_client.coverage_lookup import get_active_medicare_part_b_coverage
from cms_access_fhir_client.cron.submission_status_poller import _apply_poll_result
from cms_access_fhir_client.models import ACCESSAlignment, ACCESSOperationLog
from cms_access_fhir_client.models.access_alignment import CustomPatient
from cms_access_fhir_client.operation_log import record_operation_event
from cms_access_fhir_client.report_data import (
    TRACK_INSTRUMENTS,
    TRACK_MEASURES,
    build_data_bundle,
    build_organization,
    build_practitioner,
    is_questionnaire_track,
    supported_track,
)


def _log_submitted(patient, track: str, operation: str, content_location: str, debug: list) -> None:
    """Append a 'submitted' audit row when an async operation is accepted (202)."""
    record_operation_event(
        patient=patient,
        track=track or "",
        operation=operation,
        phase=ACCESSOperationLog.PHASE_SUBMITTED,
        http_status=202,
        content_location=content_location or "",
        exchange=debug[0] if debug else {},
    )

# BP panel + component LOINCs (the one multi-component measure).
_LOINC = "http://loinc.org"
_BP_PANEL_LOINC = "85354-9"
_BP_SYSTOLIC_LOINC = "8480-6"
_BP_DIASTOLIC_LOINC = "8462-4"

# Other measure LOINCs we special-case.
_WEIGHT_LOINC = "29463-7"
_HEIGHT_LOINC = "8302-2"
_BMI_LOINC = "39156-5"

# Canvas records some measures under a different LOINC than the CMS section code.
# Accept these as input sources; the bundle always emits under the CMS code.
_MEASURE_SOURCE_ALIASES = {
    "8280-0": ("56086-2",),  # waist circumference: Canvas vitals uses 56086-2, CMS wants 8280-0
}

# Unit conversions to the UCUM units CMS uses in its examples (kg, kg/m2, m via cm/in).
_OZ_TO_KG = 0.028349523125
_LB_TO_KG = 0.45359237
_IN_TO_M = 0.0254


def _to_kg(value: float, unit: str | None) -> float | None:
    """Normalize a body-weight value to kilograms; None if the unit is unrecognized."""
    u = (unit or "").strip().lower()
    if u in ("kg", "kilogram", "kilograms"):
        return value
    if u in ("g", "gram", "grams"):
        return value / 1000.0
    if u in ("oz", "[oz_av]", "ounce", "ounces"):
        return value * _OZ_TO_KG
    if u in ("lb", "lbs", "[lb_av]", "pound", "pounds"):
        return value * _LB_TO_KG
    return None


def _to_meters(value: float, unit: str | None) -> float | None:
    """Normalize a height value to meters; None if the unit is unrecognized."""
    u = (unit or "").strip().lower()
    if u in ("m", "meter", "meters"):
        return value
    if u in ("cm", "centimeter", "centimeters"):
        return value / 100.0
    if u in ("in", "[in_i]", "inch", "inches"):
        return value * _IN_TO_M
    return None


def _latest_valued_observation(patient_id: str, codes):
    """Most recent non-retracted Observation across the given LOINC codes that actually
    has a parseable numeric value. Skips blank readings — Canvas may store an empty newer
    vitals entry on top of a valid older one, so 'most recent' alone isn't enough.
    """
    qs = (
        Observation.objects.filter(
            patient__id=patient_id,
            entered_in_error__isnull=True,
            codings__code__in=list(codes),
        )
        .order_by("-effective_datetime")
    )
    for obs in qs:
        try:
            float(obs.value)
        except (TypeError, ValueError):
            continue
        return obs
    return None


def _latest_bp_components(patient_id: str, codes) -> dict | None:
    """Systolic/diastolic from the most recent BP Observation that has both components."""
    qs = (
        Observation.objects.filter(
            patient__id=patient_id,
            entered_in_error__isnull=True,
            codings__code__in=list(codes),
        )
        .order_by("-effective_datetime")
    )
    for obs in qs:
        components: dict = {}
        for comp in obs.components.all():
            for coding in comp.codings.all():
                if coding.code in (_BP_SYSTOLIC_LOINC, _BP_DIASTOLIC_LOINC):
                    try:
                        components[coding.code] = float(comp.value_quantity)
                    except (TypeError, ValueError):
                        continue
        if _BP_SYSTOLIC_LOINC in components and _BP_DIASTOLIC_LOINC in components:
            return components
    return None


def _compute_bmi(patient_id: str) -> dict | None:
    """Derive BMI (kg/m2) from the latest valued height + weight.

    Canvas computes BMI for display only — it never persists a 39156-5 Observation — so
    when a track requires BMI we calculate it ourselves rather than leave it missing.
    """
    h_obs = _latest_valued_observation(patient_id, (_HEIGHT_LOINC,))
    w_obs = _latest_valued_observation(patient_id, (_WEIGHT_LOINC,))
    if h_obs is None or w_obs is None:
        return None
    meters = _to_meters(float(h_obs.value), h_obs.units)
    kg = _to_kg(float(w_obs.value), w_obs.units)
    if not meters or not kg:
        return None
    return {"value": round(kg / (meters * meters), 1), "unit": "kg/m2"}


def _gather_measures(patient_id: str, track: str) -> dict:
    """Pull the patient's latest valued Observation per required measure for the track.

    Returns {loinc: value_dict} for measures found in Canvas; missing measures are
    omitted (CMS reports them as incomplete-data). BP is read from its components,
    weight is normalized to kg, BMI is derived when absent, and waist accepts Canvas's
    56086-2 source code while always emitting under the CMS 8280-0 section code.
    """
    measures: dict = {}
    track_codes = [m[0] for m in TRACK_MEASURES[track]]
    for code, _title, _profile, _category, _unit in TRACK_MEASURES[track]:
        source_codes = (code,) + _MEASURE_SOURCE_ALIASES.get(code, ())
        if code == _BP_PANEL_LOINC:
            components = _latest_bp_components(patient_id, source_codes)
            if components:
                measures[code] = {"components": components}
            continue
        obs = _latest_valued_observation(patient_id, source_codes)
        if obs is None:
            continue
        value = float(obs.value)
        if code == _WEIGHT_LOINC:
            kg = _to_kg(value, obs.units)
            if kg is None:
                continue  # unknown unit — don't send a mis-labeled weight
            measures[code] = {"value": round(kg, 1), "unit": "kg"}
        else:
            measures[code] = {"value": value, "unit": obs.units or None}

    # BMI is never an Observation in Canvas — derive it from height + weight when the
    # track requires it and we didn't otherwise find one.
    if _BMI_LOINC in track_codes and _BMI_LOINC not in measures:
        bmi = _compute_bmi(patient_id)
        if bmi is not None:
            # NB: the Canvas RestrictedPython sandbox forbids using an underscore-prefixed
            # name directly as a subscript-assignment key, so route through a plain local.
            bmi_code = _BMI_LOINC
            measures[bmi_code] = bmi

    return measures


def _latest_interview_response(patient_id: str, lookup_code: str, title: str) -> dict | None:
    """Most recent committed, non-retracted Canvas Interview for the questionnaire with the
    given LOINC code, shaped into the dict _questionnaire_response_resource expects.

    Returns None when the patient has no such completed questionnaire. Item answers and the
    summed ordinal score are best-effort from Canvas's response options.
    """
    interview = (
        Interview.objects.filter(
            patient__id=patient_id,
            entered_in_error__isnull=True,
            deleted=False,
            questionnaires__code=lookup_code,
        )
        .order_by("-created")
        .first()
    )
    if interview is None:
        return None

    items: list[dict] = []
    total = 0.0
    have_score = False
    responses = (
        interview.interview_responses.filter(questionnaire__code=lookup_code)
        .select_related("question", "response_option")
    )
    for r in responses:
        question = r.question
        option = r.response_option
        item: dict = {
            "linkId": (getattr(question, "code", None) or str(getattr(question, "dbid", "item"))) if question else "item",
            "text": getattr(question, "name", "") if question else "",
        }
        if option is not None:
            item["answer_code"] = option.code or ""
            item["answer_system"] = getattr(question, "code_system", None) or _LOINC
            item["answer_display"] = option.name or ""
            ordinal = None
            for candidate in (option.value, option.ordering):
                try:
                    ordinal = float(candidate)
                    break
                except (TypeError, ValueError):
                    continue
            if ordinal is not None:
                item["ordinal"] = ordinal
                total += ordinal
                have_score = True
        elif r.response_option_value:
            item["answer_text"] = r.response_option_value
        items.append(item)

    narrative = f"{title}. Score: {total:g}." if have_score else title
    authored = interview.created.isoformat() if getattr(interview, "created", None) else None
    return {"items": items, "narrative": narrative, "authored": authored, "questionnaire": None}


def _gather_questionnaire_responses(patient_id: str, track: str) -> dict:
    """Pull the patient's latest QuestionnaireResponse per required PROM instrument.

    Returns {section_code: response_dict} for instruments found in Canvas. Each instrument is
    discovered by its ``lookup_code`` (a LOINC, when one exists) or — for the instruments CMS
    identifies with an ACCESS section code that has no LOINC (WHODAS/PGIC/QuickDASH) — by that
    section code itself. So an implementer codes their licensed Canvas Questionnaire with the
    ACCESS code and it is picked up automatically; nothing is silently skipped. Missing
    instruments are omitted (CMS reports them as incomplete-data).
    """
    responses: dict = {}
    for section_code, _system, title, lookup_code in TRACK_INSTRUMENTS[track]:
        code = lookup_code or section_code
        data = _latest_interview_response(patient_id, code, title)
        if data is not None:
            responses[section_code] = data
    return responses


# Canonical track codes, in display order. Kept as a module constant (rather than reading
# ACCESSAlignment.TRACK_CHOICES) so the enabled-tracks gate is independent of the model.
_ALL_TRACKS = ["eCKM", "CKM", "MSK", "BH"]


def _enabled_tracks(secrets: dict) -> list[str]:
    """Tracks the plugin should expose, from the ``ACCESS_ENABLED_TRACKS`` variable.

    Comma-separated, case-insensitive (e.g. ``"CKM,BH"`` or ``"ckm, bh"``). Blank or
    unset means all tracks are enabled (the default, so a fresh install shows everything).
    Returns canonical track codes in display order; a non-blank value is honored strictly
    (only the tracks it names appear).
    """
    raw = (secrets.get("ACCESS_ENABLED_TRACKS") or "").strip()
    if not raw:
        return list(_ALL_TRACKS)
    wanted = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return [track for track in _ALL_TRACKS if track.lower() in wanted]


def _serialize_alignment(alignment: ACCESSAlignment) -> dict:
    """Serialize an ACCESSAlignment row for the inspector's state view."""
    return {
        "dbid": alignment.dbid,
        "track": alignment.track,
        "status": alignment.status,
        "status_message": alignment.status_message or "",
        "submission_state": alignment.submission_state or "",
        "submission_op": alignment.submission_op or "",
        "alignment_id": alignment.alignment_id or "",
        "poll_attempts": alignment.poll_attempts,
        "report_result": alignment.report_result or "",
        "report_result_at": alignment.report_result_at.isoformat() if alignment.report_result_at else "",
        "updated_at": alignment.updated_at.isoformat() if alignment.updated_at else "",
    }


def _get_payer_id(coverage, secrets: dict) -> str | None:
    """Resolve the CMS payerID for a Coverage record.

    Lookup order:
    1. coverage.issuer.payer_id — the Transactor identifier, preferred when populated.
    2. ACCESS_DEFAULT_PAYER_ID secret — escape hatch when Transactor.payer_id is empty.
    3. Returns None if both are absent, signalling fail-closed to the caller.
    """
    payer_id = getattr(coverage.issuer, "payer_id", None)
    if payer_id:
        return payer_id
    default = secrets.get("ACCESS_DEFAULT_PAYER_ID", "")
    if default:
        # Visible in logs: every patient whose Transactor lacks a payer_id falls back to
        # one global default, so a wrong/stale default would be submitted silently otherwise.
        log.warning(
            f"[cms-access] coverage {getattr(coverage, 'dbid', '?')} issuer has no payer_id; "
            "falling back to ACCESS_DEFAULT_PAYER_ID"
        )
        return default
    return None


# Canvas sex_at_birth / gender codes → FHIR Patient.gender value set.
_GENDER_MAP = {
    "f": "female",
    "m": "male",
    "o": "other",
    "female": "female",
    "male": "male",
    "other": "other",
    "unknown": "unknown",
    "unk": "unknown",
}


def _resolve_gender(patient) -> str:
    """Map a patient's sex_at_birth / gender to a FHIR Patient.gender code (default 'unknown')."""
    for attr in ("sex_at_birth", "gender"):
        raw = (getattr(patient, attr, "") or "").strip().lower()
        if raw:
            return _GENDER_MAP.get(raw, "unknown")
    return "unknown"


def _build_patient_resource(patient, mbi: str) -> dict:
    """Build a US Core Patient FHIR resource for inclusion in CMS ACCESS API requests.

    Per Operations Manual v0.9.11 §Patient Identification, the resource must contain:
    - identifier with cmsMBI system + MC type code
    - name (family + given)
    - gender (male/female/other/unknown)
    - birthDate (REQUIRED — CMS rejects requests without it)

    Raises ValueError if patient.birth_date is None, because CMS will reject the
    payload. Callers must ensure the patient has a birth date on file before
    invoking any ACCESS operation.
    """
    if patient.birth_date is None:
        raise ValueError(
            f"Patient {patient.id} has no birth_date — CMS ACCESS requires birthDate "
            "in the Patient resource. Ensure birth date is recorded before submitting."
        )

    # The MBI is the patient's identifier to CMS — never send an empty/placeholder value.
    # The /state route guards this for display; the mutating operations must too.
    if not (mbi or "").strip():
        raise ValueError(
            f"Patient {patient.id} has no Medicare Beneficiary Identifier (MBI) on the "
            "active Medicare Part B coverage — CMS ACCESS requires it."
        )

    # Resolve gender to a FHIR Patient.gender value. Canvas stores sex_at_birth as a
    # single-letter code ("F"/"M"/"O") or "UNK"; map those to the FHIR value set,
    # falling back to the gender attribute, then to "unknown".
    gender = _resolve_gender(patient)

    return {
        "resourceType": "Patient",
        "id": str(patient.id),
        # IMPL requires a profile claim; CMS ACCESS uses US Core Patient 6.1.0.
        "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient|6.1.0"]},
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "MC",
                        }
                    ]
                },
                "system": "http://terminology.hl7.org/NamingSystem/cmsMBI",
                "value": mbi,
            }
        ],
        "name": [
            {
                "family": patient.last_name or "",
                "given": [patient.first_name or ""],
            }
        ],
        "gender": gender,
        "birthDate": patient.birth_date.isoformat(),
    }


class AccessOperationsApi(StaffSessionAuthMixin, SimpleAPI):
    """Backs the ACCESS inspector modal and invokes CMS operations.

    All routes are gated on a Canvas staff session via StaffSessionAuthMixin and
    served under the ``/app`` prefix. The inspector UI itself is rendered inline by
    the ACCESS chart-header button (not served here); these routes are the JSON API the inspector calls.
    """

    PREFIX = "/app"

    @api.get("/state")
    def state(self) -> list[Response | Effect]:
        """Return the patient's current ACCESS state — the latest row per track.

        Shows one row per track (most recent), so the panel reflects current
        per-track state rather than full history. Orphaned rows with a blank track
        (left over from early failed submissions before track was validated) are
        skipped so they don't masquerade as current results.
        """
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id query param is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        rows = (
            ACCESSAlignment.objects.filter(patient__id=patient_id)
            .order_by("-updated_at")
        )
        seen: set[str] = set()
        latest: list[ACCESSAlignment] = []
        for row in rows:
            if not row.track or row.track in seen:
                continue
            seen.add(row.track)
            latest.append(row)

        # Patient identifiers for the header — name, DOB, and MBI (the ACCESS-relevant ID).
        # Best-effort: never let a demographics lookup break the state panel.
        patient_info = {"name": "", "dob": "", "mbi": ""}
        try:
            patient = CustomPatient.objects.get(id=patient_id)
            patient_info["name"] = f"{patient.first_name or ''} {patient.last_name or ''}".strip()
            if patient.birth_date:
                patient_info["dob"] = patient.birth_date.isoformat()
            coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
            if coverage is not None and coverage.id_number:
                patient_info["mbi"] = coverage.id_number
        except CustomPatient.DoesNotExist:
            pass
        except Exception as exc:  # noqa: BLE001 - demographics are display-only, never fatal
            log.error(f"[cms-access] state demographics lookup failed: {exc}")

        return [
            JSONResponse({
                "alignments": [_serialize_alignment(a) for a in latest],
                "patient": patient_info,
                "enabled_tracks": _enabled_tracks(self.secrets),
            })
        ]

    @api.post("/eligibility")
    def submit_eligibility(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        track = body.get("track")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not track:
            return [JSONResponse({"error": "Missing track"}, status_code=HTTPStatus.BAD_REQUEST)]
        if track not in _enabled_tracks(self.secrets):
            return [JSONResponse({"error": f"The {track} track is not enabled for this organization."}, status_code=HTTPStatus.FORBIDDEN)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        try:
            patient_resource = _build_patient_resource(patient, mbi=coverage.id_number)
        except ValueError as exc:
            log.error(f"[cms-access] Cannot build Patient resource for {patient.id}: {exc}")
            return [
                JSONResponse(
                    {"error": str(exc)},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        # Optionally include the patient's track-qualifying conditions (0..*) so CMS can
        # confirm eligibility against a diagnosis rather than returning eligible-pending-diagnosis.
        conditions = build_track_conditions(patient, track, patient_fhir_id=str(patient.id))

        debug: list = []
        try:
            status_code, content_location, _ = check_eligibility(
                self.secrets,
                patient_resource=patient_resource,
                payer_id=payer_id,
                track=track,
                conditions=conditions,
                debug=debug,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $check-eligibility failed for patient {patient.id}: {exc}")
            alignment, _ = ACCESSAlignment.objects.get_or_create(
                patient=patient,
                track=track,
                defaults={"status": ACCESSAlignment.STATUS_ERROR},
            )
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = str(exc)
            alignment.last_eligibility_check_at = _utcnow()
            alignment.save()
            return [
                JSONResponse(
                    {
                        "error": f"CMS request failed: {exc}",
                        "status": alignment.status,
                        "exchange": debug[0] if debug else None,
                    },
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

        alignment, _ = ACCESSAlignment.objects.get_or_create(
            patient=patient,
            track=track,
            defaults={"status": ACCESSAlignment.STATUS_PENDING},
        )
        alignment.last_eligibility_check_at = _utcnow()

        # $check-eligibility is always async: CMS returns 202 + Content-Location (OM v0.9.11).
        # Any other 2xx is a contract violation — surface it rather than parking the row in a
        # stuck PENDING state that reports success but can never be polled.
        if not (status_code == 202 and content_location):
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = f"Unexpected CMS response: HTTP {status_code} without Content-Location"
            alignment.save()
            return [
                JSONResponse(
                    {
                        "error": f"Unexpected CMS response (HTTP {status_code}) — expected 202 with Content-Location",
                        "status": alignment.status,
                        "exchange": debug[0] if debug else None,
                    },
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

        alignment.status = ACCESSAlignment.STATUS_PENDING
        alignment.submission_status_url = content_location
        alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
        alignment.submission_op = ACCESSAlignment.SUB_OP_ELIGIBILITY
        alignment.submission_started_at = _utcnow()
        alignment.poll_attempts = 0
        _log_submitted(patient, track, ACCESSAlignment.SUB_OP_ELIGIBILITY, content_location, debug)
        alignment.save()

        return [
            JSONResponse(
                {
                    "status": alignment.status,
                    "content_location": content_location,
                    "exchange": debug[0] if debug else None,
                },
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

    @api.post("/align")
    def submit_align(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        track = body.get("track")
        switch_consent = bool(body.get("switch_consent", False))

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not track:
            return [JSONResponse({"error": "Missing track"}, status_code=HTTPStatus.BAD_REQUEST)]
        if track not in _enabled_tracks(self.secrets):
            return [JSONResponse({"error": f"The {track} track is not enabled for this organization."}, status_code=HTTPStatus.FORBIDDEN)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        try:
            patient_resource = _build_patient_resource(patient, mbi=coverage.id_number)
        except ValueError as exc:
            log.error(f"[cms-access] Cannot build Patient resource for {patient.id}: {exc}")
            return [
                JSONResponse(
                    {"error": str(exc)},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        # $align requires at least one track-qualifying Condition (OM v0.9.11).
        # Build them from the patient's active problem list; fail closed if none qualify.
        conditions = build_track_conditions(patient, track, patient_fhir_id=str(patient.id))
        if not conditions:
            return [
                JSONResponse(
                    {
                        "error": (
                            f"Patient has no active diagnosis qualifying for the {track} track — "
                            "$align requires at least one qualifying condition on the problem list"
                        )
                    },
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        debug: list = []
        try:
            status_code, content_location, _ = align(
                self.secrets,
                patient_resource=patient_resource,
                payer_id=payer_id,
                track=track,
                conditions=conditions,
                switch_consent=switch_consent,
                debug=debug,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $align failed for patient {patient.id}: {exc}")
            alignment, _ = ACCESSAlignment.objects.get_or_create(
                patient=patient,
                track=track,
                defaults={"status": ACCESSAlignment.STATUS_ERROR},
            )
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = str(exc)
            alignment.save()
            return [
                JSONResponse(
                    {
                        "error": f"CMS request failed: {exc}",
                        "status": alignment.status,
                        "exchange": debug[0] if debug else None,
                    },
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

        alignment, _ = ACCESSAlignment.objects.get_or_create(
            patient=patient,
            track=track,
            defaults={"status": ACCESSAlignment.STATUS_PENDING},
        )

        # $align is always async: CMS returns 202 + Content-Location (OM v0.9.11). Any other 2xx
        # is a contract violation — surface it rather than parking the row in a stuck PENDING
        # state that reports success but can never be polled.
        if not (status_code == 202 and content_location):
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = f"Unexpected CMS response: HTTP {status_code} without Content-Location"
            alignment.save()
            return [
                JSONResponse(
                    {
                        "error": f"Unexpected CMS response (HTTP {status_code}) — expected 202 with Content-Location",
                        "status": alignment.status,
                        "exchange": debug[0] if debug else None,
                    },
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

        alignment.status = ACCESSAlignment.STATUS_PENDING
        alignment.submission_status_url = content_location
        alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
        alignment.submission_op = ACCESSAlignment.SUB_OP_ALIGN
        alignment.submission_started_at = _utcnow()
        alignment.poll_attempts = 0
        _log_submitted(patient, track, ACCESSAlignment.SUB_OP_ALIGN, content_location, debug)
        alignment.save()
        log.info(f"[cms-access] Align submitted for patient {patient_id}, track {track}")

        return [
            JSONResponse(
                {
                    "status": alignment.status,
                    "content_location": content_location,
                    "exchange": debug[0] if debug else None,
                },
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

    @api.post("/unalign")
    def submit_unalign(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id")
        reason_code = body.get("reason_code")
        requested_track = body.get("track")  # optional: which aligned track to unalign

        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not reason_code:
            return [JSONResponse({"error": "Missing reason_code"}, status_code=HTTPStatus.BAD_REQUEST)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        try:
            patient_resource = _build_patient_resource(patient, mbi=coverage.id_number)
        except ValueError as exc:
            log.error(f"[cms-access] Cannot build Patient resource for {patient.id}: {exc}")
            return [
                JSONResponse(
                    {"error": str(exc)},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            f"[cms-access] Using Medicare Part B coverage {coverage.dbid} "
            f"(issuer={coverage.issuer.name}) for patient {patient.id}"
        )

        # Treat both 'aligned' and 'already-aligned' as an active CMS alignment: a
        # repeat $align returns 'already-aligned', which overwrites the local 'aligned'
        # status, but the patient IS still aligned at CMS. Let CMS be the authority on
        # whether the unalign succeeds rather than blocking locally on exact status.
        # If the caller specifies a track, unalign that one; otherwise the most recent.
        alignments = ACCESSAlignment.objects.filter(
            patient=patient,
            status__in=[ACCESSAlignment.STATUS_ALIGNED, ACCESSAlignment.STATUS_ALREADY_ALIGNED],
        )
        if requested_track:
            alignments = alignments.filter(track=requested_track)
        alignment = alignments.order_by("-updated_at").first()

        if not alignment:
            # Distinguish "nothing to unalign" from "an unalignment is already underway".
            # A track sitting in unalignment-pending (status PENDING) won't match the
            # aligned/already-aligned filter above, so explain that rather than implying
            # the patient was never aligned.
            existing_q = ACCESSAlignment.objects.filter(patient=patient)
            if requested_track:
                existing_q = existing_q.filter(track=requested_track)
            existing = existing_q.order_by("-updated_at").first()
            track_label = f" on the {requested_track} track" if requested_track else ""
            if existing and existing.submission_state == ACCESSAlignment.SUB_STATE_IN_PROGRESS:
                detail = (
                    f"An unalignment is already in progress{track_label} "
                    f"(currently {existing.status_message or existing.status}). "
                    "Use Poll now to check its status — don't resubmit."
                )
            elif existing and existing.status == ACCESSAlignment.STATUS_PENDING:
                detail = (
                    f"An unalignment is already pending CMS review{track_label} "
                    f"({existing.status_message or 'unalignment-pending'}). "
                    "No need to resubmit — Poll to refresh, or wait for CMS to resolve it."
                )
            else:
                detail = f"No active alignment found to unalign{track_label}."
            return [JSONResponse({"error": detail}, status_code=HTTPStatus.NOT_FOUND)]

        # v0.9.11 $unalign does not carry an alignmentId parameter (it was removed from
        # the canonical payload; alignment_id is kept on the model for reference only),
        # so we do not gate unalignment on it here.

        # v0.9.11: a disqualifying condition is required when unaligning because the
        # patient is no longer clinically eligible. Build it from the active problem list.
        conditions: list[dict] = []
        if reason_code == ACCESSAlignment.UNALIGN_REASON_NO_LONGER_CLINICALLY_ELIGIBLE:
            conditions = build_active_conditions(patient, patient_fhir_id=str(patient.id))
            if not conditions:
                return [
                    JSONResponse(
                        {
                            "error": (
                                "Unaligning for 'no longer clinically eligible' requires a "
                                "disqualifying diagnosis, but the patient has no active condition "
                                "on the problem list"
                            )
                        },
                        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                    )
                ]

        debug: list = []
        try:
            status_code, content_location, _ = unalign(
                self.secrets,
                patient_resource=patient_resource,
                payer_id=payer_id,
                track=alignment.track,
                reason_code=reason_code,
                conditions=conditions,
                debug=debug,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $unalign failed for patient {patient.id}: {exc}")
            alignment.status = ACCESSAlignment.STATUS_ERROR
            alignment.status_message = str(exc)
            alignment.save()
            return [
                JSONResponse(
                    {
                        "error": f"CMS request failed: {exc}",
                        "status": alignment.status,
                        "exchange": debug[0] if debug else None,
                    },
                    status_code=HTTPStatus.BAD_GATEWAY,
                ),
            ]

        alignment.unalignment_reason = reason_code
        if status_code == 202 and content_location:
            alignment.submission_status_url = content_location
            alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
            alignment.submission_op = ACCESSAlignment.SUB_OP_UNALIGN
            alignment.submission_started_at = _utcnow()
            alignment.poll_attempts = 0
            _log_submitted(patient, alignment.track, ACCESSAlignment.SUB_OP_UNALIGN, content_location, debug)
        else:
            alignment.status = ACCESSAlignment.STATUS_UNALIGNED

        alignment.save()
        log.info(f"[cms-access] Unalign submitted for patient {patient_id}")

        return [
            JSONResponse(
                {
                    "status": alignment.status,
                    "content_location": content_location,
                    "exchange": debug[0] if debug else None,
                },
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

    @api.post("/poll")
    def poll(self) -> list[Response | Effect]:
        """Poll the stored submission-status URL once and return the full exchange.

        The client never supplies the URL (avoids SSRF) — we read the
        ``submission_status_url`` off the patient's most recent in-progress
        ACCESSAlignment row, poll it once, apply the result to the row, and return
        the raw request/response exchange plus the updated status.
        """
        body = self.request.json() or {}
        patient_id = body.get("patient_id")
        track = body.get("track")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]

        alignments = ACCESSAlignment.objects.filter(
            patient__id=patient_id,
            submission_state=ACCESSAlignment.SUB_STATE_IN_PROGRESS,
        )
        if track:
            alignments = alignments.filter(track=track)
        alignment = alignments.order_by("-updated_at").first()

        if not alignment or not alignment.submission_status_url:
            return [
                JSONResponse(
                    {"error": "No in-progress submission to poll for this patient"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        debug: list = []
        try:
            status_code, poll_body = poll_submission_status(
                self.secrets, alignment.submission_status_url, debug=debug
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] poll failed for patient {patient_id}: {exc}")
            return [
                JSONResponse(
                    {"error": f"Poll request failed: {exc}", "exchange": debug[0] if debug else None},
                    status_code=HTTPStatus.BAD_GATEWAY,
                )
            ]

        alignment.poll_attempts = alignment.poll_attempts + 1
        alignment.last_poll_at = _utcnow()
        _apply_poll_result(alignment, status_code, poll_body)
        alignment.save()

        return [
            JSONResponse(
                {
                    "status": alignment.status,
                    "submission_state": alignment.submission_state,
                    "exchange": debug[0] if debug else None,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/report-data")
    def submit_report(self) -> list[Response | Effect]:
        """Submit $report-data: assemble the CKM/eCKM document Bundle from the patient's
        Canvas vitals/labs and POST it. Returns the full exchange + the measures found.
        """
        body = self.request.json()
        patient_id = body.get("patient_id")
        track = body.get("track")
        report_type = body.get("report_type")
        if not patient_id:
            return [JSONResponse({"error": "Missing patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not track:
            return [JSONResponse({"error": "Missing track"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not report_type:
            return [JSONResponse({"error": "Missing report_type"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not supported_track(track):
            return [
                JSONResponse(
                    {"error": f"Unknown track {track!r} — expected one of CKM, eCKM, MSK, BH"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]
        if track not in _enabled_tracks(self.secrets):
            return [JSONResponse({"error": f"The {track} track is not enabled for this organization."}, status_code=HTTPStatus.FORBIDDEN)]

        try:
            patient = CustomPatient.objects.get(id=patient_id)
        except CustomPatient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        # Don't start a report-data submission while an alignment operation (align/unalign)
        # is still being polled — the model tracks one async submission per (patient, track),
        # so starting report-data would clobber the in-flight op. Per OM v0.9.11 p.70 a
        # pending unalignment must persist until CMS finalizes it; report-data is a separate
        # reporting lifecycle and must not disturb it.
        existing = ACCESSAlignment.objects.filter(patient=patient, track=track).first()
        if (
            existing
            and existing.submission_state == ACCESSAlignment.SUB_STATE_IN_PROGRESS
            and existing.submission_op != ACCESSAlignment.SUB_OP_REPORT_DATA
        ):
            return [
                JSONResponse(
                    {
                        "error": (
                            f"A ${existing.submission_op} operation is still in progress for "
                            f"the {track} track — Poll it to completion before reporting data, "
                            "so the alignment result isn't lost."
                        )
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        coverage = get_active_medicare_part_b_coverage(patient, self.secrets)
        if coverage is None:
            return [
                JSONResponse(
                    {"error": "Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]
        payer_id = _get_payer_id(coverage, self.secrets)
        if not payer_id:
            return [
                JSONResponse(
                    {"error": "Cannot determine payerID — populate Transactor.payer_id on the Medicare Part B payer or set ACCESS_DEFAULT_PAYER_ID secret"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]
        try:
            patient_resource = _build_patient_resource(patient, mbi=coverage.id_number)
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.UNPROCESSABLE_ENTITY)]

        participant_id = self.secrets.get("ACCESS_PARTICIPANT_ID", "")
        organization = build_organization(
            participant_id, self.secrets.get("ACCESS_ORG_NAME") or "Canvas ACCESS Participant"
        )
        practitioner = build_practitioner(
            staff_id=participant_id, first_name="ACCESS", last_name="Reporter", npi=None
        )

        # Gather the patient's data and assemble the document Bundle. Surface any failure
        # here as a clear 500 with the exception detail (and log the traceback) rather than
        # letting it become an opaque bare HTTP 500 in the inspector.
        timestamp = _utcnow().isoformat()
        try:
            if is_questionnaire_track(track):
                # MSK/BH: PROM QuestionnaireResponses gathered from Canvas Interviews.
                responses = _gather_questionnaire_responses(str(patient.id), track)
                elements_found = sorted(responses)
                data_bundle = build_data_bundle(
                    track=track,
                    patient_resource=patient_resource,
                    practitioner=practitioner,
                    organization=organization,
                    responses=responses,
                    bundle_id=f"{patient.id}-{track}-{report_type}",
                    timestamp=timestamp,
                )
            else:
                # CKM/eCKM: structured Observations (vitals + labs).
                measures = _gather_measures(str(patient.id), track)
                elements_found = sorted(measures)
                data_bundle = build_data_bundle(
                    track=track,
                    patient_resource=patient_resource,
                    practitioner=practitioner,
                    organization=organization,
                    measures=measures,
                    bundle_id=f"{patient.id}-{track}-{report_type}",
                    timestamp=timestamp,
                )
        except Exception as exc:  # noqa: BLE001 - report to the user instead of a bare 500
            log.exception(f"[cms-access] $report-data assembly failed for patient {patient.id}, track {track}")
            return [
                JSONResponse(
                    {"error": f"Report assembly failed: {exc}"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        debug: list = []
        try:
            status_code, content_location, _ = submit_report_data(
                self.secrets,
                payer_id=payer_id,
                track=track,
                report_type=report_type,
                data_bundle=data_bundle,
                debug=debug,
            )
        except RuntimeError as exc:
            log.error(f"[cms-access] $report-data failed for patient {patient.id}: {exc}")
            return [
                JSONResponse(
                    {
                        "error": f"CMS request failed: {exc}",
                        "elements_found": elements_found,
                        "exchange": debug[0] if debug else None,
                    },
                    status_code=HTTPStatus.BAD_GATEWAY,
                )
            ]

        if status_code == 202 and content_location:
            alignment, _ = ACCESSAlignment.objects.get_or_create(
                patient=patient, track=track, defaults={"status": ACCESSAlignment.STATUS_PENDING}
            )
            alignment.submission_status_url = content_location
            alignment.submission_state = ACCESSAlignment.SUB_STATE_IN_PROGRESS
            alignment.submission_op = ACCESSAlignment.SUB_OP_REPORT_DATA
            alignment.submission_started_at = _utcnow()
            alignment.poll_attempts = 0
            alignment.save()
            _log_submitted(patient, track, ACCESSAlignment.SUB_OP_REPORT_DATA, content_location, debug)
        log.info(f"[cms-access] Report-data ({report_type}) submitted for patient {patient_id}, track {track}")

        return [
            JSONResponse(
                {
                    "status": "report-data submitted",
                    "content_location": content_location,
                    "elements_found": elements_found,
                    "exchange": debug[0] if debug else None,
                },
                status_code=HTTPStatus.ACCEPTED,
            )
        ]


def _extract_eligibility_status(result: dict) -> tuple[str, str]:
    """Parse a completed $submission-status Parameters response (eligibility op).

    The OM v0.9.11 uses `result` (valueCodeableConcept) in the polling response,
    not `status` (valueCode) as in the earlier flat-payload implementation.

    Returns (alignment_status_constant, raw_cms_code) so the caller can persist
    the raw code in status_message for display in the banner.

    Mapping rules:
    - starts with "eligible"                → STATUS_ELIGIBLE
    - "not-eligible-already-aligned"        → STATUS_ALREADY_ALIGNED
    - starts with "not-eligible-"           → STATUS_INELIGIBLE
    - anything else                         → STATUS_ERROR
    """
    for param in result.get("parameter", []):
        if param.get("name") == "result":
            codings = (
                param.get("valueCodeableConcept", {})
                .get("coding", [])
            )
            if codings:
                raw_code = codings[0].get("code", "")
                return _map_eligibility_code(raw_code), raw_code
        # Also handle legacy/direct invocation responses that may use valueCode
        if param.get("name") == "status":
            raw_code = param.get("valueCode", "")
            return _map_eligibility_code(raw_code), raw_code
    return ACCESSAlignment.STATUS_ERROR, ""


def _map_eligibility_code(code: str) -> str:
    """Map a CMS ACCESSEligibilityResultCS code to an ACCESSAlignment status constant."""
    if not code:
        return ACCESSAlignment.STATUS_ERROR
    if code == "not-eligible-already-aligned":
        return ACCESSAlignment.STATUS_ALREADY_ALIGNED
    if code.startswith("eligible"):
        return ACCESSAlignment.STATUS_ELIGIBLE
    if code.startswith("not-eligible-"):
        return ACCESSAlignment.STATUS_INELIGIBLE
    return ACCESSAlignment.STATUS_ERROR


def _extract_alignment_result(result: dict) -> str:
    """Return the raw ACCESSAlignmentResultCS code from a completed $align Parameters body.

    The OM v0.9.11 polling response carries the outcome in the `result` parameter as a
    valueCodeableConcept (e.g. `aligned`, `not-aligned-diagnoses`).
    """
    for param in result.get("parameter", []):
        if param.get("name") == "result":
            codings = param.get("valueCodeableConcept", {}).get("coding", [])
            if codings:
                return codings[0].get("code", "")
    return ""


def _map_alignment_code(code: str) -> str:
    """Map a CMS ACCESSAlignmentResultCS code to an ACCESSAlignment status constant.

    `aligned` / `aligned-switch-approved` → aligned; `not-aligned-already-aligned` →
    already-aligned; any other `not-aligned-*` → ineligible (technically not aligned).
    """
    if not code:
        return ACCESSAlignment.STATUS_ERROR
    if code == "not-aligned-already-aligned":
        return ACCESSAlignment.STATUS_ALREADY_ALIGNED
    if code.startswith("aligned"):
        return ACCESSAlignment.STATUS_ALIGNED
    if code.startswith("not-aligned-"):
        return ACCESSAlignment.STATUS_INELIGIBLE
    return ACCESSAlignment.STATUS_ERROR


def _extract_unalignment_result(result: dict) -> str:
    """Return the raw ACCESSUnalignmentResultCS code from a completed $unalign body."""
    for param in result.get("parameter", []):
        if param.get("name") == "result":
            codings = param.get("valueCodeableConcept", {}).get("coding", [])
            if codings:
                return codings[0].get("code", "")
    return ""


def _map_unalignment_code(code: str) -> str:
    """Map a CMS ACCESSUnalignmentResultCS code to an ACCESSAlignment status constant.

    `unaligned` → unaligned; `unalignment-pending` → pending (awaiting manual review);
    `patient-not-aligned` / `cannot-unalign-during-lock-in` → error (could not unalign).
    """
    if code == "unaligned":
        return ACCESSAlignment.STATUS_UNALIGNED
    if code == "unalignment-pending":
        return ACCESSAlignment.STATUS_PENDING
    if code in ("patient-not-aligned", "cannot-unalign-during-lock-in"):
        return ACCESSAlignment.STATUS_ERROR
    return ACCESSAlignment.STATUS_ERROR


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
