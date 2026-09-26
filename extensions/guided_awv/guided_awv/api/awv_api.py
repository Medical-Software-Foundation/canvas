"""SimpleAPI route handlers for the Guided AWV plugin."""

from __future__ import annotations

import json
import re
from datetime import date as date_type, timedelta
from html import escape as html_escape
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands.commands.chart_section_review import ChartSectionReviewCommand
from canvas_sdk.commands.commands.diagnose import DiagnoseCommand
from canvas_sdk.commands.commands.family_history import FamilyHistoryCommand
from canvas_sdk.commands.commands.follow_up import FollowUpCommand
from canvas_sdk.commands.commands.imaging_order import ImagingOrderCommand
from canvas_sdk.commands.commands.instruct import InstructCommand
from canvas_sdk.commands.commands.lab_order import LabOrderCommand
from canvas_sdk.commands.commands.perform import PerformCommand
from canvas_sdk.commands.commands.plan import PlanCommand
from canvas_sdk.commands.commands.prescribe import PrescribeCommand
from canvas_sdk.commands.commands.task import AssigneeType, TaskAssigner, TaskCommand
from canvas_sdk.commands.commands.structured_assessment import StructuredAssessmentCommand
from canvas_sdk.commands.commands.vitals import VitalsCommand
from canvas_sdk.commands.constants import ClinicalQuantity, Coding, CodeSystems
from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import AddBillingLineItem
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from logger import log


_FORM_STATE_TAG = "AWV_FORM_STATE"
_FORM_STATE_PATTERN = re.compile(
    r"\[//\]: # \(" + _FORM_STATE_TAG + r"::(\w+)::(.*)\)"
)


def _extract_form_states(narratives: list[str]) -> dict[str, dict]:
    """Parse form state tags from narratives. Last write wins per section."""
    sections: dict[str, dict] = {}
    for text in narratives:
        for match in _FORM_STATE_PATTERN.finditer(text):
            section_id = match.group(1)
            try:
                sections[section_id] = json.loads(match.group(2))
            except json.JSONDecodeError:
                pass
    return sections


_CACHE_TTL = 60 * 60 * 24 * 14  # 14 days


def _save_form_state(note_id: str, section_id: str, form_fields: dict) -> None:
    """Persist form field values in plugin cache, keyed by note UUID."""
    cache = get_cache()
    key = f"awv_form_state:{note_id}"
    sections = cache.get(key, default={})
    # _last_saved is set by the frontend before sending
    sections[section_id] = form_fields
    cache.set(key, sections, timeout_seconds=_CACHE_TTL)


def _get_all_form_states(note_id: str) -> dict[str, dict[Any, Any]]:
    """Retrieve all cached form states for a note."""
    cache = get_cache()
    key = f"awv_form_state:{note_id}"
    result: dict[str, dict[Any, Any]] = cache.get(key, default={})
    return result


def _get_questionnaire_id(code: str) -> str | None:
    """Look up a questionnaire UUID by its code. Returns None if not found."""
    from canvas_sdk.v1.data.questionnaire import Questionnaire

    q = Questionnaire.objects.filter(code=code, status="AC").first()
    if q:
        return str(q.id)
    log.warning(f"Questionnaire with code={code!r} not found in instance")
    return None


def _originate_sa(
    note_id: str,
    questionnaire_id: str,
    result: str,
) -> Effect | None:
    """Originate a StructuredAssessmentCommand with clinical text only.

    Returns None on error so callers can proceed with cache-only form state.
    """
    try:
        sa_cmd = StructuredAssessmentCommand(
            note_uuid=note_id,
            questionnaire_id=questionnaire_id,
            result=result,
        )
        return sa_cmd.originate()
    except Exception as exc:
        log.warning(
            f"StructuredAssessmentCommand failed for questionnaire_id={questionnaire_id}: {exc}."
        )
        return None


def _get_z00_assessment_id(note_id: str) -> str | None:
    """Return the Z00.* Assessment id on this note (if any), else None.

    The Z00.00 ("Encounter for general adult medical examination") diagnosis is
    the canonical AWV diagnosis. Once it has been committed as an Assessment on
    the note, every CPT II line item on the AWV should point at it as the
    diagnosis pointer for billing.

    Returns None when no Z00.* Assessment exists yet (e.g. before the user
    commits all commands). Callers should pass the result as `assessment_ids=[]`
    in that case - the link can be backfilled by re-saving the section later.
    """
    if not note_id:
        return None
    try:
        from canvas_sdk.v1.data import Assessment
        from canvas_sdk.v1.data.note import Note as NoteModel

        note_obj = NoteModel.objects.filter(id=note_id).first()
        note_dbid = note_obj.dbid if note_obj else None
        if not note_dbid:
            return None
        z00_id = (
            Assessment.objects.filter(
                note_id=note_dbid,
                condition__codings__code__startswith="Z00",
                # REVIEW.md "Always check": don't link CPT II billing line
                # items to a Z00 assessment the clinician later flagged as
                # entered-in-error.
                entered_in_error_id__isnull=True,
            )
            .values_list("id", flat=True)
            .first()
        )
        return str(z00_id) if z00_id else None
    except Exception as exc:
        log.warning(f"_get_z00_assessment_id: lookup failed for note={note_id}: {exc}")
        return None


def _add_cpt_ii(note_id: str, code: str) -> Effect:
    """Create a billing line item for a CPT Category II quality reporting code.

    Automatically links the line item to the note's Z00.00 Assessment when
    one exists, so the CPT II code has the AWV diagnosis pointer required for
    most billing workflows. If Z00 has not been committed yet (typical on the
    first save of any section), the link is omitted - re-saving the section
    after the user commits all commands will backfill it.
    """
    assessment_id = _get_z00_assessment_id(note_id)
    return AddBillingLineItem(
        note_id=note_id,
        cpt=code,
        assessment_ids=[assessment_id] if assessment_id else [],
    ).apply()


def _section_last_done_iso(section: dict[str, Any], today: date_type) -> str:
    """Extract the date a cached form-state section was actually saved.

    The JS writes ``_last_saved`` as an ISO-8601 timestamp into the section
    dict before every save. We slice the first 10 chars (the YYYY-MM-DD
    portion) and validate via ``date.fromisoformat`` - that handles the
    timestamps the frontend produces, ``Z`` suffix and all, without dragging
    in a heavier parser. Falls back to ``today.isoformat()`` when the field
    is missing, empty, or unparseable so a save with a corrupted timestamp
    still surfaces *some* date instead of dropping the entry entirely.
    """
    raw = section.get("_last_saved") if isinstance(section, dict) else None
    if isinstance(raw, str) and len(raw) >= 10:
        try:
            return date_type.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            pass
    return today.isoformat()


def _form_value_is(val: Any, target: str) -> bool:
    """Return True if a cached form-state value matches *target*.

    The frontend ``getModuleFormData`` collects every checked checkbox value
    into a list (even when there's only one), so cached form_state can hold
    either a bare string or a list of strings depending on which input shape
    contributed. Comparing ``val == "ordered"`` against a list always returns
    False - which is what masked the Prevention Plan's "Ordered today" path
    until UAT caught it.

    Use this helper any time you read ``prev_state.get(...)`` and want to ask
    "did the user pick this option?" - it answers correctly for both shapes.
    """
    if val == target:
        return True
    if isinstance(val, list):
        return target in val
    return False


def _to_int(value: Any) -> int | None:
    """Coerce a form value to int, gracefully rounding fractional input.

    Form values arrive as strings (e.g. "187.5"). The Canvas VitalsCommand
    schema is integer-typed for these fields, so we round to the nearest whole
    unit. Returns None for missing, empty, or unparseable values rather than
    raising - the caller decides whether to skip the field.
    """
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _parse_body(request: Any) -> dict[str, Any]:
    """
    Parse request body as JSON.

    Tries request.json() first (works in test environment), then falls back
    to raw body parsing for the production Canvas environment.
    """
    try:
        result: dict[str, Any] = request.json()
        return result
    except Exception:
        try:
            parsed: dict[str, Any] = json.loads(request.body)
            return parsed
        except Exception:
            return {}


def _lookup_all_screening_dates(patient_id: str, dates: dict[str, dict[str, Any]]) -> None:
    """Look up last-done screening dates from vaccines, labs, imaging, and BH records.

    Populates ``dates`` dict in-place. Uses the same query patterns as
    GetScreeningDatesHandler but as a standalone function for reuse.
    """
    # Vaccine CVX codes
    vaccine_cvx = {
        "influenza": ["141", "150", "153", "155", "168", "171", "185", "186", "197", "205"],
        "pneumococcal": ["33", "100", "109", "133", "152", "215", "216"],
        "covid_vaccine": ["207", "208", "211", "212", "213", "217", "218", "219", "220", "221", "228", "229", "230", "300", "301", "302"],
        "tdap_td": ["113", "115", "138", "139"],
        "shingles": ["121", "187", "188"],
        "rsv": ["303", "304", "305", "306"],
    }
    # Lab LOINC codes
    lab_loinc = {
        "lipids": ["57698-3", "2093-3", "2571-8", "2085-9", "13457-7"],
        "hep_c": ["16128-1", "5199-5", "13955-0"],
        "diabetes_screen": ["4548-4", "2339-0", "2345-7"],
        "prostate_psa": ["2857-1", "35741-8"],
    }
    # Imaging keywords
    imaging_keywords = {
        "mammogram": ["mammog", "77067"],
        "dexa": ["dexa", "bone density", "77080"],
        "ldct_lung": ["ldct", "low-dose ct", "low dose ct", "lung screen", "71271"],
        "aaa": ["aortic aneurysm", "aaa", "76706"],
        "colorectal": ["colonoscop", "cologuard", "fit", "fobt", "G0121"],
        "cervical_cancer": ["pap", "cervical", "hpv", "88175", "87624"],
    }

    # 1. Vaccines — bulk query with reverse code→service mapping
    try:
        from canvas_sdk.v1.data.immunization import (
            ImmunizationCoding,
            ImmunizationStatementCoding,
        )
        # Build reverse map: CVX code → service ID
        cvx_to_svc: dict[str, str] = {}
        all_cvx: list[str] = []
        for svc_id, codes in vaccine_cvx.items():
            for code in codes:
                cvx_to_svc[code] = svc_id
            all_cvx.extend(codes)

        # Strategy 1: Single bulk query on ImmunizationStatementCoding
        stmt_rows = (
            ImmunizationStatementCoding.objects
            .filter(
                immunization_statement__patient__id=patient_id,
                immunization_statement__date__isnull=False,
                code__in=all_cvx,
            )
            .order_by("-immunization_statement__date")
            .values_list("code", "immunization_statement__date")
        )
        for code, rec_date in stmt_rows:
            matched_svc = cvx_to_svc.get(code)
            if matched_svc and matched_svc not in dates:
                dates[matched_svc] = {"last_done": rec_date.isoformat()}

        # Strategy 2: Single bulk query on ImmunizationCoding (fallback)
        missing_cvx = [c for c in all_cvx if cvx_to_svc.get(c) not in dates]
        if missing_cvx:
            imm_rows = (
                ImmunizationCoding.objects
                .filter(
                    immunization__patient__id=patient_id,
                    immunization__date_ordered__isnull=False,
                    code__in=missing_cvx,
                )
                .order_by("-immunization__date_ordered")
                .values_list("code", "immunization__date_ordered")
            )
            for code, rec_date in imm_rows:
                matched_svc = cvx_to_svc.get(code)
                if matched_svc and matched_svc not in dates:
                    dates[matched_svc] = {"last_done": rec_date.isoformat()}

        # Strategy 3: Keyword match on display text (fallback)
        vaccine_keywords = {
            "influenza": ["influenza", "flu vaccine", "flu shot"],
            "pneumococcal": ["pneumococcal", "ppsv23", "pcv13", "pcv15", "pcv20", "prevnar", "pneumovax"],
            "covid_vaccine": ["covid", "sars-cov", "moderna", "pfizer", "janssen", "novavax"],
            "tdap_td": ["tdap", "td vaccine", "tetanus", "diphtheria", "boostrix", "adacel"],
            "shingles": ["shingrix", "zoster", "shingles"],
            "rsv": ["rsv", "abrysvo", "arexvy"],
        }
        if any(svc_id not in dates for svc_id in vaccine_keywords):
            stmt_codings = list(
                ImmunizationStatementCoding.objects
                .filter(
                    immunization_statement__patient__id=patient_id,
                    immunization_statement__date__isnull=False,
                )
                .values_list("display", "immunization_statement__date")
                .order_by("-immunization_statement__date")[:500]
            )
            imm_codings = list(
                ImmunizationCoding.objects
                .filter(
                    immunization__patient__id=patient_id,
                    immunization__date_ordered__isnull=False,
                )
                .values_list("display", "immunization__date_ordered")
                .order_by("-immunization__date_ordered")[:500]
            )
            all_records = stmt_codings + imm_codings
            for svc_id, keywords in vaccine_keywords.items():
                if svc_id in dates:
                    continue
                for display, record_date in all_records:
                    if not display or not record_date:
                        continue
                    display_lower = display.lower()
                    if any(kw in display_lower for kw in keywords):
                        dates[svc_id] = {"last_done": record_date.isoformat()}
                        break
    except Exception:
        log.warning("_lookup_all_screening_dates: vaccine lookup failed", exc_info=True)

    # 2. Labs — bulk query with reverse code→service mapping
    try:
        from canvas_sdk.v1.data.lab import LabValueCoding

        loinc_to_svc: dict[str, str] = {}
        all_loinc: list[str] = []
        for svc_id, codes in lab_loinc.items():
            for code in codes:
                loinc_to_svc[code] = svc_id
            all_loinc.extend(codes)

        lab_rows = (
            LabValueCoding.objects
            .filter(
                value__report__patient__id=patient_id,
                value__report__original_date__isnull=False,
                code__in=all_loinc,
                # REVIEW.md "Always check": exclude entered-in-error lab
                # reports so a lab the clinician later invalidated doesn't
                # claim a screening was done.
                value__report__entered_in_error_id__isnull=True,
            )
            .order_by("-value__report__original_date")
            .values_list("code", "value__report__original_date")
        )
        for code, rec_date in lab_rows:
            matched_svc = loinc_to_svc.get(code)
            if matched_svc and matched_svc not in dates:
                dates[matched_svc] = {"last_done": rec_date.date().isoformat()}
    except Exception:
        log.warning("_lookup_all_screening_dates: lab lookup failed", exc_info=True)

    # 3. Imaging
    try:
        from canvas_sdk.v1.data.imaging import ImagingOrder
        orders = (
            ImagingOrder.objects
            # REVIEW.md "Always check": skip entered-in-error imaging orders.
            .filter(
                patient__id=patient_id,
                date_time_ordered__isnull=False,
                entered_in_error_id__isnull=True,
            )
            .order_by("-date_time_ordered")
            .values_list("imaging", "date_time_ordered")[:200]
        )
        for svc_id, keywords in imaging_keywords.items():
            if svc_id in dates:
                continue
            for imaging_name, ordered_dt in orders:
                name_lower = imaging_name.lower()
                if any(kw.lower() in name_lower for kw in keywords):
                    dates[svc_id] = {"last_done": ordered_dt.date().isoformat()}
                    break
    except Exception:
        log.warning("_lookup_all_screening_dates: imaging lookup failed", exc_info=True)

    # 4. Behavioral health from observations
    bh_loinc = {
        "annual_depression": ["55757-9", "44249-1", "69725-0", "44261-6"],
        "annual_cognitive": ["72233-0", "72172-0"],
    }
    try:
        from canvas_sdk.v1.data.observation import ObservationCoding
        for svc_id, loinc_codes in bh_loinc.items():
            if svc_id in dates:
                continue
            latest = (
                ObservationCoding.objects
                .filter(
                    observation__patient__id=patient_id,
                    observation__effective_datetime__isnull=False,
                    code__in=loinc_codes,
                    # REVIEW.md "Always check": skip entered-in-error
                    # observations so a PHQ/Mini-Cog the clinician later
                    # invalidated doesn't drive last-screened dates.
                    observation__entered_in_error_id__isnull=True,
                )
                .order_by("-observation__effective_datetime")
                .values_list("observation__effective_datetime", flat=True)
                .first()
            )
            if latest:
                dates[svc_id] = {"last_done": latest.date().isoformat()}
    except Exception:
        log.warning("_lookup_all_screening_dates: BH observation lookup failed", exc_info=True)


class SaveVitalsHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save vitals to the current note via VitalsCommand.

    POST /awv/vitals
    Body: {
        note_id: str,
        height: int (inches),
        weight_lbs: int,
        blood_pressure_systole: int,
        blood_pressure_diastole: int,
        pulse: int,
        bp_arm: "Left" | "Right",
        bp_position: "Seated" | "Standing" | "Supine",
    }
    """

    PATH = "/awv/vitals"

    def post(self) -> list[Response | Effect]:
        """Create or update vitals command in the note."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        # Coerce form values (which arrive as strings) to int. Accepts fractional
        # values like "187.5" and rounds to the nearest whole unit, matching the
        # VitalsCommand SDK schema which is integer-typed for these fields.
        height = _to_int(body.get("height"))
        weight = _to_int(body.get("weight_lbs"))
        systole = _to_int(body.get("blood_pressure_systole"))
        diastole = _to_int(body.get("blood_pressure_diastole"))
        pulse = _to_int(body.get("pulse"))
        bp_arm = body.get("bp_arm", "").strip()
        bp_position = body.get("bp_position", "").strip()

        vitals = VitalsCommand(note_uuid=note_id)
        if height is not None:
            vitals.height = height
        if weight is not None:
            vitals.weight_lbs = weight
        if systole is not None:
            vitals.blood_pressure_systole = systole
        if diastole is not None:
            vitals.blood_pressure_diastole = diastole
        if pulse is not None:
            vitals.pulse = pulse
        # Surface arm + position in the command's note text so the CMS-required
        # documentation isn't lost. The VitalsCommand model has no first-class
        # field for these, so we record them in the note via the comment.
        if bp_arm or bp_position:
            posn_parts = [p for p in (bp_arm, bp_position) if p]
            posn_text = " - ".join(posn_parts) if posn_parts else ""
            try:
                # VitalsCommand exposes blood_pressure_position_and_site as a
                # free-text field on most schemas; assign defensively.
                if posn_text:
                    vitals.blood_pressure_position_and_site = posn_text
            except Exception:
                pass  # Fall back silently if the SDK schema rejects it.

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "vitals", form_fields)

        effects: list[Response | Effect] = [JSONResponse({"success": True}), vitals.originate()]

        # CPT II: 3008F - BMI documented
        if height is not None and weight is not None:
            effects.append(_add_cpt_ii(note_id, "3008F"))

        # CPT II BP range codes per AMA/PCPI long descriptors (HEDIS CBP /
        # CMS MIPS QM236). These are systolic-range and diastolic-range
        # bucket codes, NOT composite controlled/uncontrolled flags - emitting
        # a single "compliant" code for any BP under 140/90 mis-attests the
        # CBP numerator. Each axis fires exactly one code per visit.
        if systole is not None:
            if systole < 130:
                effects.append(_add_cpt_ii(note_id, "3074F"))  # SBP <130
            elif systole < 140:
                effects.append(_add_cpt_ii(note_id, "3075F"))  # SBP 130-139
            else:
                effects.append(_add_cpt_ii(note_id, "3077F"))  # SBP >=140
        if diastole is not None:
            if diastole < 80:
                effects.append(_add_cpt_ii(note_id, "3078F"))  # DBP <80
            elif diastole < 90:
                effects.append(_add_cpt_ii(note_id, "3079F"))  # DBP 80-89
            else:
                effects.append(_add_cpt_ii(note_id, "3080F"))  # DBP >=90

        log.info(f"SaveVitalsHandler: originating vitals for note={note_id}")
        return effects


class SaveDepressionScreeningHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save depression screening (PHQ-2/PHQ-9) results to the note.

    POST /awv/depression-screening
    Body: {
        note_id: str,
        phq2_score: int,
        phq9_score: int | null,
        responses: dict[str, int]  - question_id -> score (0-3)
    }
    """

    PATH = "/awv/depression-screening"

    def post(self) -> list[Response | Effect]:
        """Save depression screening results as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        phq2_score = body.get("phq2_score", 0)
        phq9_score = body.get("phq9_score")
        q9_score = body.get("q9_score", 0)
        safety_assessed = body.get("safety_assessed", False)
        ideation_assessed = body.get("suicide_ideation_assessed", "")

        # Build narrative
        narrative_parts = ["**Depression Screening (PHQ)**"]
        narrative_parts.append(f"PHQ-2 Score: {phq2_score}/6")

        if phq2_score >= 3 and phq9_score is not None:
            narrative_parts.append(f"PHQ-9 Score: {phq9_score}/27")
            severity = _get_phq9_severity(phq9_score)
            narrative_parts.append(f"PHQ-9 Severity: {severity}")

            if q9_score > 0:
                q9_labels = {1: "Several days", 2: "More than half the days", 3: "Nearly every day"}
                q9_label = q9_labels.get(q9_score, f"Score {q9_score}")
                narrative_parts.append("")
                narrative_parts.append(f"**PHQ-9 Q9 POSITIVE (Suicidal Ideation): {q9_label}**")
                narrative_parts.append("Suicide risk assessed and safety addressed per protocol.")
        elif phq2_score < 3:
            narrative_parts.append("PHQ-2 negative (< 3) - no further screening required")

        if ideation_assessed:
            narrative_parts.append(f"Suicide ideation assessed: {ideation_assessed}")
        if ideation_present := body.get("suicide_ideation_present"):
            narrative_parts.append(f"Suicide ideation present: {ideation_present}")

        # The JS now ships these three fields; previously the handler ignored
        # them so the documented safety action and treatment plan were dropped
        # before reaching the chart.
        safety_action_labels = {
            "assessed_no_risk": "Assessed - no risk identified",
            "assessed_safety_plan": "Assessed - safety plan created",
            "assessed_crisis_referral": "Assessed - crisis referral made",
            "not_assessed": "Not assessed",
        }
        if safety_action := body.get("safety_assessed_action"):
            label = safety_action_labels.get(safety_action, safety_action)
            narrative_parts.append(f"Safety action: {label}")
        if treatment_plan := body.get("depression_treatment_plan"):
            narrative_parts.append(f"Treatment plan: {treatment_plan}")
        if treatment_notes := body.get("depression_treatment_notes"):
            narrative_parts.append(f"Treatment notes: {treatment_notes}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "depressionscreening", form_fields)

        # StructuredAssessmentCommand for PHQ-2
        phq2_qid = _get_questionnaire_id("69725-0") or "1a15a892-3cc0-4de1-a50f-4f91d9369204"
        effects: list[Response | Effect] = [
            JSONResponse({"success": True, "phq2_score": phq2_score, "phq9_score": phq9_score}),
        ]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())
        sa_effect = _originate_sa(note_id, phq2_qid, f"PHQ-2 Score: {phq2_score}/6")
        if sa_effect:
            effects.append(sa_effect)

        # StructuredAssessmentCommand for PHQ-9 if triggered
        if phq2_score >= 3 and phq9_score is not None:
            severity = _get_phq9_severity(phq9_score)
            phq9_qid = _get_questionnaire_id("44249-1") or "7d3d137a-e627-41ab-985a-079af22c544c"
            sa_effect = _originate_sa(note_id, phq9_qid, f"PHQ-9 Score: {phq9_score}/27 - {severity}")
            if sa_effect:
                effects.append(sa_effect)

        # CPT II: 3726F (negative) or 3725F (positive with follow-up)
        if phq2_score < 3:
            effects.append(_add_cpt_ii(note_id, "3726F"))
        else:
            effects.append(_add_cpt_ii(note_id, "3725F"))

        log.info(
            f"SaveDepressionScreeningHandler: saving PHQ results for note={note_id}, "
            f"PHQ-2={phq2_score}, Q9={q9_score}, safety_assessed={safety_assessed}"
        )
        return effects


class SaveCognitiveAssessmentHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save cognitive assessment results to the note.

    Supports Mini-Cog (default) and alternative tools (MoCA, SLUMS, MMSE).

    POST /awv/cognitive-assessment
    Body (Mini-Cog): {
        note_id: str,
        words_recalled: int (0-3),
        clock_drawing_score: int (0-2),
        notes: str | null
    }
    Body (alternative): {
        note_id: str,
        tool: "moca" | "slums" | "mmse",
        score: int,
        notes: str | null
    }
    """

    PATH = "/awv/cognitive-assessment"

    ALT_TOOLS: dict[str, dict[str, object]] = {
        "moca": {"label": "MoCA", "max_score": 30, "cutoff": 25, "cutoff_dir": "lt"},
        "slums": {"label": "SLUMS", "max_score": 30, "cutoff": 20, "cutoff_dir": "lt"},
        "mmse": {"label": "MMSE", "max_score": 30, "cutoff": 23, "cutoff_dir": "lt"},
    }

    def post(self) -> list[Response | Effect]:
        """Save cognitive assessment results as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        tool = body.get("tool", "")
        # The JS now ships `screening_completed` / `clinical_notes` (the
        # canonical wire names). Fall back to the legacy
        # `cognitive_screening_completed` / `notes` for any older client.
        screening_completed = (
            body.get("screening_completed")
            or body.get("cognitive_screening_completed", "")
        )
        clinical_notes = body.get("clinical_notes") or body.get("notes", "")

        if tool and tool != "mini_cog" and tool in self.ALT_TOOLS:
            # Alternative tool path (MoCA, SLUMS, MMSE)
            tool_meta = self.ALT_TOOLS[tool]
            tool_label = str(tool_meta["label"])
            max_score = int(str(tool_meta["max_score"]))
            cutoff = int(str(tool_meta["cutoff"]))
            cutoff_dir = str(tool_meta["cutoff_dir"])

            score = int(body.get("score", 0))
            if cutoff_dir == "le":
                positive = score <= cutoff
            else:
                positive = score < cutoff
            screen_result = "Positive screen" if positive else "Negative screen"

            narrative_parts = [f"**Cognitive Assessment ({tool_label})**"]
            if screening_completed:
                narrative_parts.append(f"Screening completed: {screening_completed}")
            narrative_parts.extend([
                f"Score: {score}/{max_score}",
                f"Result: {screen_result}",
            ])
            if clinical_notes:
                narrative_parts.append(f"Clinical notes: {clinical_notes}")

            form_fields = body.pop("_form_fields", {})
            _save_form_state(note_id, "cognitiveassessment", form_fields)
            result_text = f"{tool_label}: {score}/{max_score} - {screen_result}"
            narrative = "\n".join(narrative_parts)

            effects: list[Response | Effect] = [
                JSONResponse({"success": True, "tool": tool, "score": score, "screen_result": screen_result}),
            ]
            # Route the joined narrative to a PlanCommand so the screening
            # completed timestamp and clinical notes the handler just built
            # actually land on the chart. Mirrors the v0.14.11 pattern.
            if narrative.strip():
                effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

            qid = _get_questionnaire_id("AWV_MINI_COG")
            if qid:
                sa_effect = _originate_sa(note_id, qid, result_text)
                if sa_effect:
                    effects.append(sa_effect)

            # CPT II: 1494F - Dementia cognitive assessment performed
            effects.append(_add_cpt_ii(note_id, "1494F"))

            log.info(f"SaveCognitiveAssessmentHandler: {tool_label}={score}/{max_score} for note={note_id}")
            return effects

        # Default: Mini-Cog path
        words_recalled = body.get("words_recalled", 0)
        clock_score = body.get("clock_drawing_score", 0)
        mini_cog_total = int(words_recalled) + int(clock_score)

        screen_result = "Positive screen" if mini_cog_total <= 2 else "Negative screen"

        # Build a narrative that surfaces screening_completed + clinical_notes
        # so this branch doesn't drop them like it used to. The narrative is
        # routed via PlanCommand below.
        narrative_parts = ["**Cognitive Assessment (Mini-Cog)**"]
        if screening_completed:
            narrative_parts.append(f"Screening completed: {screening_completed}")
        narrative_parts.extend([
            f"Words recalled: {words_recalled}/3",
            f"Clock drawing score: {clock_score}/2",
            f"Total: {mini_cog_total}/5",
            f"Result: {screen_result}",
        ])
        if clinical_notes:
            narrative_parts.append(f"Clinical notes: {clinical_notes}")
        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "cognitiveassessment", form_fields)
        result_text = f"Mini-Cog: {mini_cog_total}/5 - {screen_result}"

        effects = [
            JSONResponse({"success": True, "mini_cog_total": mini_cog_total, "screen_result": screen_result}),
        ]
        # Route the joined narrative to a PlanCommand so the screening
        # completed timestamp and clinical notes the handler just built
        # actually land on the chart. Mirrors the v0.14.11 pattern.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        qid = _get_questionnaire_id("AWV_MINI_COG")
        if qid:
            sa_effect = _originate_sa(note_id, qid, result_text)
            if sa_effect:
                effects.append(sa_effect)

        # CPT II: 1494F - Dementia cognitive assessment performed
        effects.append(_add_cpt_ii(note_id, "1494F"))

        log.info(f"SaveCognitiveAssessmentHandler: Mini-Cog={mini_cog_total}/5 for note={note_id}")
        return effects


class SaveFallRiskHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save fall risk assessment results to the note.

    POST /awv/fall-risk
    Body: {
        note_id: str,
        falls_past_year: str ("Yes" | "No"),
        falls_count: int | null,
        fall_injury: str ("Yes" | "No"),
        fear_of_falling: str ("Yes" | "No"),
        gait_concern: str ("Yes" | "No"),
        assistive_device: str ("Yes - cane" | "Yes - walker" | "Yes - other" | "No"),
        tug_time_seconds: float | null,
        ortho_lying_sbp: int | null,
        ortho_lying_dbp: int | null,
        ortho_lying_hr: int | null,
        ortho_standing_sbp: int | null,
        ortho_standing_dbp: int | null,
        ortho_standing_hr: int | null,
        risk_factors: list[str]
    }
    """

    PATH = "/awv/fall-risk"

    def post(self) -> list[Response | Effect]:
        """Save fall risk assessment as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        falls_past_year = body.get("falls_past_year", "No")
        falls_count = body.get("falls_count")
        fall_injury = body.get("fall_injury", "No")
        fear_of_falling = body.get("fear_of_falling", "No")
        gait_concern = body.get("gait_concern", "No")
        assistive_device = body.get("assistive_device", "No")
        tug_time = body.get("tug_time_seconds")
        risk_factors = body.get("risk_factors", [])

        narrative_parts = ["**Fall Risk Assessment**"]
        narrative_parts.append(f"Falls in past year: {falls_past_year}")

        if falls_past_year == "Yes" and falls_count is not None:
            narrative_parts.append(f"Number of falls: {falls_count}")

        if tug_time is not None:
            tug_risk = "increased risk" if float(tug_time) >= 12 else "low risk"
            narrative_parts.append(f"TUG test: {tug_time} seconds ({tug_risk})")

        # Orthostatic vitals
        ortho_lying_sbp = body.get("ortho_lying_sbp")
        ortho_lying_dbp = body.get("ortho_lying_dbp")
        ortho_lying_hr = body.get("ortho_lying_hr")
        ortho_standing_sbp = body.get("ortho_standing_sbp")
        ortho_standing_dbp = body.get("ortho_standing_dbp")
        ortho_standing_hr = body.get("ortho_standing_hr")

        has_lying_bp = ortho_lying_sbp is not None and ortho_lying_dbp is not None
        has_standing_bp = ortho_standing_sbp is not None and ortho_standing_dbp is not None
        if has_lying_bp and has_standing_bp:
            sbp_drop = int(ortho_lying_sbp) - int(ortho_standing_sbp)  # type: ignore[arg-type]
            dbp_drop = int(ortho_lying_dbp) - int(ortho_standing_dbp)  # type: ignore[arg-type]
            positive = sbp_drop >= 20 or dbp_drop >= 10
            result_label = "POSITIVE" if positive else "Negative"
            lying_hr_str = f", HR {ortho_lying_hr}" if ortho_lying_hr is not None else ""
            standing_hr_str = f", HR {ortho_standing_hr}" if ortho_standing_hr is not None else ""
            narrative_parts.append(
                f"Orthostatic vitals: Lying {ortho_lying_sbp}/{ortho_lying_dbp} mmHg{lying_hr_str}"
            )
            narrative_parts.append(
                f"  Standing {ortho_standing_sbp}/{ortho_standing_dbp} mmHg{standing_hr_str}"
            )
            narrative_parts.append(
                f"  SBP drop: {sbp_drop} mmHg, DBP drop: {dbp_drop} mmHg - {result_label}"
            )

        # Overall fall risk level (CDC STEADI criteria)
        high_risk = False
        falls_count_int = int(falls_count) if falls_count is not None else 0
        if falls_past_year == "Yes" and falls_count_int >= 2:
            high_risk = True
        if falls_past_year == "Yes" and fall_injury == "Yes":
            high_risk = True
        if tug_time is not None and float(tug_time) >= 12:
            high_risk = True
        if has_lying_bp and has_standing_bp and positive:
            high_risk = True

        moderate_risk = False
        if not high_risk:
            if falls_past_year == "Yes" and falls_count_int >= 1 and fall_injury != "Yes":
                moderate_risk = True
            if fear_of_falling == "Yes":
                moderate_risk = True
            if gait_concern == "Yes":
                moderate_risk = True
            if assistive_device not in ("No", ""):
                moderate_risk = True

        if high_risk:
            risk_level = "High"
        elif moderate_risk:
            risk_level = "Moderate"
        else:
            risk_level = "Low"

        narrative_parts.append(f"Overall fall risk level: {risk_level}")
        if risk_level == "High":
            narrative_parts.append(
                "Recommend multifactorial fall risk intervention per CDC STEADI guidelines."
            )

        if risk_factors:
            narrative_parts.append(f"Risk factors identified: {', '.join(risk_factors)}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "fallrisk", form_fields)
        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        qid = _get_questionnaire_id("AWV_STEADI")
        if qid:
            sa_effect = _originate_sa(note_id, qid, f"Fall Risk: {risk_level}")
            if sa_effect:
                effects.append(sa_effect)

        # CPT II: 1100F - Patient screened for future fall risk
        effects.append(_add_cpt_ii(note_id, "1100F"))
        # CPT II: 3288F - Fall risk assessment documented
        effects.append(_add_cpt_ii(note_id, "3288F"))

        log.info(f"SaveFallRiskHandler: fall risk documented for note={note_id}")
        return effects


class SearchPharmaciesHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Search the Canvas pharmacy directory.

    GET /awv/search-pharmacies?search=<term>
    Returns: { results: [{ ncpdp_id, organization_name, address_line_1, city, state, zip_code, phone_primary }, ...] }
    """

    PATH = "/awv/search-pharmacies"

    def get(self) -> list[Response | Effect]:
        """Full-text search of pharmacies by name/address/city/state/zip/NCPDP."""
        from canvas_sdk.utils.http import pharmacy_http

        search_term = self.request.query_params.get("search", "").strip()
        if not search_term or len(search_term) < 2:
            return [JSONResponse({"results": []})]

        try:
            raw_results = pharmacy_http.search_pharmacies(search_term) or []
            results = [
                {
                    "ncpdp_id": r.get("ncpdp_id", ""),
                    "organization_name": r.get("organization_name", ""),
                    "address_line_1": r.get("address_line_1", ""),
                    "city": r.get("city", ""),
                    "state": r.get("state", ""),
                    "zip_code": r.get("zip_code", ""),
                    "phone_primary": r.get("phone_primary", ""),
                }
                for r in raw_results[:20]
                if r.get("ncpdp_id")
            ]
        except Exception as e:
            log.warning(f"SearchPharmaciesHandler: pharmacy search failed: {e}")
            results = []

        return [JSONResponse({"results": results})]


class SearchConditionsHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Search ICD-10 conditions via the Canvas ontologies service.

    GET /awv/search-conditions?search=<term>
    Returns: { results: [{ icd10_code, icd10_text, snomed_concept_id }, ...] }
    """

    PATH = "/awv/search-conditions"

    def get(self) -> list[Response | Effect]:
        """Search for conditions matching the query term."""
        from urllib.parse import urlencode

        from canvas_sdk.utils.http import ontologies_http

        search_term = self.request.query_params.get("search", "").strip()
        if not search_term or len(search_term) < 2:
            return [JSONResponse({"results": []})]

        try:
            response = ontologies_http.get_json(
                f"/icd/condition?{urlencode({'search': search_term})}"
            )
            response_json = response.json() or {}
            raw_results = response_json.get("results", [])
            results = [
                {
                    "icd10_code": r.get("icd10_code", ""),
                    "icd10_text": r.get("icd10_text", ""),
                }
                for r in raw_results[:20]
            ]
        except Exception as e:
            log.warning(f"SearchConditionsHandler: ontologies search failed: {e}")
            results = []

        return [JSONResponse({"results": results})]


class AddDiagnosisHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Add a diagnosis to the current note via DiagnoseCommand.

    POST /awv/diagnose
    Body: {
        note_id: str,
        icd10_code: str,
        background: str | null,
        today_assessment: str | null
    }
    """

    PATH = "/awv/diagnose"

    def post(self) -> list[Response | Effect]:
        """Create a DiagnoseCommand in the note."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")
        icd10_code = body.get("icd10_code")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]
        if not icd10_code:
            return [JSONResponse({"success": False, "error": "icd10_code is required"}, status_code=400)]

        dx_cmd = DiagnoseCommand(
            note_uuid=note_id,
            icd10_code=icd10_code,
            background=body.get("background"),
            today_assessment=body.get("today_assessment"),
        )

        log.info(f"AddDiagnosisHandler: adding diagnosis {icd10_code} to note={note_id}")
        return [JSONResponse({"success": True, "icd10_code": icd10_code}), dx_cmd.originate()]


class SavePlanHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save the assessment & plan narrative to the note.

    POST /awv/plan
    Body: {
        note_id: str,
        narrative: str
    }
    """

    PATH = "/awv/plan"

    def post(self) -> list[Response | Effect]:
        """Create or update the PlanCommand in the note, with AWV billing line item."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")
        narrative = body.get("narrative", "")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        # The JS sends section_id so we can distinguish the two callers that
        # both POST to /awv/plan: saveAssessmentPlan() ('assessmentplan') and
        # saveAttestation() ('attestation'). Without this routing the second
        # save would silently clobber the first's form-state cache slot.
        # Default to 'assessmentplan' for backward compat with the original wire format.
        section_id = body.get("section_id", "assessmentplan")
        if section_id not in ("assessmentplan", "attestation"):
            section_id = "assessmentplan"

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, section_id, form_fields)

        effects: list[Response | Effect] = [JSONResponse({"success": True})]

        # Only create PlanCommand when there are additional notes (non-empty narrative)
        if narrative.strip():
            plan_cmd = PlanCommand(note_uuid=note_id, narrative=narrative)
            effects.append(plan_cmd.originate())

        # Add preventive visit diagnosis and AWV billing line item
        attestation = body.get("attestation", "")
        awv_code = body.get("awv_cpt_code", "G0438")
        if attestation or "Provider Attestation" in narrative:
            existing_z00 = _get_z00_assessment_id(note_id)

            if not existing_z00:
                dx_cmd = DiagnoseCommand(
                    note_uuid=note_id,
                    icd10_code="Z00.00",
                    today_assessment="Annual Wellness Visit",
                )
                effects.append(dx_cmd.originate())

            billing_item = AddBillingLineItem(
                note_id=note_id,
                cpt=awv_code,
                assessment_ids=[existing_z00] if existing_z00 else [],
            )
            effects.append(billing_item.apply())

        log.info(f"SavePlanHandler: saving plan narrative for note={note_id}")
        return effects


class ScheduleFollowupHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Schedule a follow-up visit via FollowUpCommand.

    POST /awv/followup
    Body: {
        note_id: str,
        comment: str | null,
        requested_date: str | null  (ISO date YYYY-MM-DD)
    }
    """

    PATH = "/awv/followup"

    def post(self) -> list[Response | Effect]:
        """Create a FollowUpCommand in the note."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        requested_date_str = body.get("requested_date")
        requested_date = None
        if requested_date_str:
            try:
                requested_date = date_type.fromisoformat(requested_date_str)
            except ValueError:
                return [JSONResponse({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}, status_code=400)]

        followup_cmd = FollowUpCommand(
            note_uuid=note_id,
            comment=body.get("comment"),
            requested_date=requested_date,
        )

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "followupscheduling", form_fields)

        log.info(f"ScheduleFollowupHandler: scheduling follow-up for note={note_id}, date={requested_date}")
        return [JSONResponse({"success": True}), followup_cmd.originate()]


class SaveHRAHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save Health Risk Assessment (HRA) responses to the note.

    POST /awv/hra
    Body: {
        note_id: str,
        responses: dict[str, Any],  - field_id -> value
        awv_type: "initial" | "subsequent"
    }
    """

    PATH = "/awv/hra"

    def post(self) -> list[Response | Effect]:
        """Save HRA responses as a structured plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        raw_responses = body.get("responses", {})
        awv_type = body.get("awv_type", "initial")

        # Strip the "hra_" prefix that the template adds to form field names
        responses: dict[str, Any] = {}
        for key, value in raw_responses.items():
            clean_key = key.removeprefix("hra_")
            responses[clean_key] = value

        narrative_parts = [f"**Health Risk Assessment ({'Initial' if awv_type == 'initial' else 'Update'})**"]

        # General health status
        if health_status := responses.get("general_health"):
            narrative_parts.append(f"General health: {health_status}")

        # Behavioral risks
        behavioral_items = []
        if tobacco := responses.get("tobacco_use"):
            behavioral_items.append(f"Tobacco: {tobacco}")
        if (alcohol := responses.get("alcohol_use")) is not None:
            behavioral_items.append(f"Alcohol: {alcohol} drinks/week")
        if exercise := responses.get("exercise_days"):
            behavioral_items.append(f"Exercise: {exercise} days/week")
        if seatbelt := responses.get("seatbelt"):
            behavioral_items.append(f"Seatbelt use: {seatbelt}")
        if behavioral_items:
            narrative_parts.append("Behavioral risks: " + "; ".join(behavioral_items))

        # Psychosocial
        if food_security := responses.get("food_security"):
            narrative_parts.append(f"Food security: {food_security}")
        if housing := responses.get("housing_stability"):
            narrative_parts.append(f"Housing stability: {housing}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "hra", form_fields)

        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        # Tobacco CPT II codes - the previous code attached 1036F to every
        # truthy tobacco_use answer with a comment claiming it meant "Tobacco
        # use screened". Per AMA CPT Category II long descriptors:
        #   1034F - Current tobacco smoker
        #   1035F - Current smokeless tobacco user
        #   1036F - Current tobacco non-user
        # So the prior code was *attesting non-user status* on every Yes
        # answer, and stacking 4004F (cessation intervention received) on
        # top - a billing-correctness bug. Now we route based on the answer.
        tobacco_val = str(responses.get("tobacco_use") or "").strip().lower()
        if tobacco_val:
            if tobacco_val in ("yes", "current", "daily", "occasionally", "current smoker", "smoker"):
                effects.append(_add_cpt_ii(note_id, "1034F"))
                # 4004F - Tobacco cessation intervention received - only emit
                # when the cessation_intervention question actually says so.
                cessation_val = str(responses.get("cessation_intervention") or "").strip().lower()
                if cessation_val in ("yes", "received", "counseled"):
                    effects.append(_add_cpt_ii(note_id, "4004F"))
            elif tobacco_val in ("no", "never", "former", "former user", "never user", "non-user", "non user"):
                effects.append(_add_cpt_ii(note_id, "1036F"))

        log.info(f"SaveHRAHandler: saving HRA responses for note={note_id}")
        return effects


class SaveFamilyHistoryHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save family history to the note via FamilyHistoryCommand (per relative).

    POST /awv/family-history
    Body: {
        note_id: str,
        narrative: str,
        relatives: dict[str, { status: str, age: str, conditions: list[str] }]
    }
    """

    PATH = "/awv/family-history"

    def post(self) -> list[Response | Effect]:
        """Save family history as FamilyHistoryCommand entries per relative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        relatives = body.get("relatives", {})
        effects: list[Response | Effect] = [JSONResponse({"success": True})]

        # The JS ships a free-text 'narrative' field built from the additional-
        # notes textarea. Route it to a PlanCommand when non-empty so the
        # provider's typed notes don't disappear into the cache.
        narrative = str(body.get("narrative") or "").strip()
        if narrative:
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "familyhistory", form_fields)
        relative_items = list(relatives.items())

        for relative_name, data in relative_items:
            conditions = data.get("conditions", [])
            conditions_text = ", ".join(conditions) if conditions else "None reported"
            note_parts = [f"Status: {data.get('status', 'Unknown')}"]
            if data.get("age"):
                note_parts.append(f"Age: {data['age']}")
            note_text = ", ".join(note_parts)
            fhx_cmd = FamilyHistoryCommand(
                note_uuid=note_id,
                family_history=Coding(system=CodeSystems.UNSTRUCTURED, code=conditions_text),
                relative=relative_name,
                note=note_text,
            )
            effects.append(fhx_cmd.originate())

        log.info(f"SaveFamilyHistoryHandler: saving {len(relatives)} relatives for note={note_id}")
        return effects


class SaveFunctionalAbilityHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save functional ability / ADL-IADL assessment to the note.

    POST /awv/functional-ability
    Body: {
        note_id: str,
        adl_responses: dict[str, str],   - item_id -> "independent"|"needs_assistance"|"dependent"|"na"
        iadl_responses: dict[str, str],
        home_safety_concerns: str | null,
        referrals_needed: list[str]
    }
    """

    PATH = "/awv/functional-ability"

    def post(self) -> list[Response | Effect]:
        """Save functional ability assessment as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        adl_responses = body.get("adl_responses", {})
        iadl_responses = body.get("iadl_responses", {})
        home_safety = body.get("home_safety_concerns", "")
        referrals = body.get("referrals_needed", [])

        narrative_parts = ["**Functional Ability / ADLs**"]

        if adl_responses:
            narrative_parts.append("Basic ADLs:")
            for item_id, status in adl_responses.items():
                label = item_id.removeprefix("adl_").replace("_", " ").title()
                narrative_parts.append(f"  {label}: {status}")

        if iadl_responses:
            narrative_parts.append("Instrumental ADLs:")
            for item_id, status in iadl_responses.items():
                label = item_id.removeprefix("iadl_").replace("_", " ").title()
                narrative_parts.append(f"  {label}: {status}")

        if home_safety:
            narrative_parts.append(f"Home safety concerns: {home_safety}")

        if referrals:
            narrative_parts.append(f"Referrals recommended: {', '.join(referrals)}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "functionalability", form_fields)
        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        qid = _get_questionnaire_id("AWV_FUNCTIONAL")
        if qid:
            sa_effect = _originate_sa(note_id, qid, "ADL/IADL assessment completed")
            if sa_effect:
                effects.append(sa_effect)

        # CPT II: 1170F - Functional status assessed
        effects.append(_add_cpt_ii(note_id, "1170F"))

        log.info(f"SaveFunctionalAbilityHandler: saving ADL/IADL assessment for note={note_id}")
        return effects


class SaveAdvanceCarePlanningHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save advance care planning documentation to the note.

    POST /awv/advance-care-planning
    Body: {
        note_id: str,
        acp_discussed: str,
        advance_directive_exists: str | null,
        advance_directive_type: list[str],
        healthcare_proxy_name: str | null,
        healthcare_proxy_relationship: str | null,
        patient_wishes_summary: str | null,
        acp_followup_needed: list[str]
    }
    """

    PATH = "/awv/advance-care-planning"

    def post(self) -> list[Response | Effect]:
        """Save advance care planning as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        narrative_parts = ["**Advance Care Planning**"]

        if acp_discussed := body.get("acp_discussed"):
            narrative_parts.append(f"ACP discussed: {acp_discussed}")

        if code_status := body.get("code_status"):
            narrative_parts.append(f"Code status: {code_status}")

        if directive_exists := body.get("advance_directive_exists"):
            narrative_parts.append(f"Advance directive on file: {directive_exists}")

        directive_types = body.get("advance_directive_type", [])
        if directive_types:
            narrative_parts.append(f"Directive type(s): {', '.join(directive_types)}")

        topics_discussed = body.get("acp_topics_discussed", [])
        if topics_discussed:
            narrative_parts.append(f"Topics discussed: {', '.join(topics_discussed)}")

        if proxy_name := body.get("healthcare_proxy_name"):
            relationship = body.get("healthcare_proxy_relationship", "")
            contact = body.get("healthcare_proxy_contact", "")
            proxy_str = proxy_name
            if relationship:
                proxy_str += f" ({relationship})"
            if contact:
                proxy_str += f" - Contact: {contact}"
            narrative_parts.append(f"Healthcare proxy: {proxy_str}")

        if proxy_designated := body.get("healthcare_proxy_designated"):
            narrative_parts.append(f"Healthcare proxy formally designated: {proxy_designated}")

        if wishes := body.get("patient_wishes_summary"):
            narrative_parts.append(f"Patient wishes: {wishes}")

        documents_completed = body.get("documents_completed_today", [])
        if documents_completed:
            narrative_parts.append(f"Documents completed today: {', '.join(documents_completed)}")

        if copy_given := body.get("copy_given_to_patient"):
            narrative_parts.append(f"Copy given to patient: {copy_given}")

        if documents_scanned := body.get("documents_scanned_to_chart"):
            narrative_parts.append(f"Documents scanned to chart: {documents_scanned}")

        followup_actions = body.get("acp_followup_needed", [])
        if followup_actions:
            narrative_parts.append(f"Follow-up actions: {', '.join(followup_actions)}")

        # Resolve discussion state up front - it gates both the time-bearing
        # narrative line and the CPT 99497 emission below. Mirroring the sister
        # 1124F gate (line below) keeps "did this discussion actually happen"
        # as a single source of truth instead of asymmetric guards.
        acp_discussed = body.get("acp_discussed", "")
        directive_exists = body.get("advance_directive_exists", "")
        discussion_occurred = acp_discussed in ("Yes", "Yes - discussed") or directive_exists in ("Yes", "Yes - on file")

        # CMS-required time documentation for CPT 99497 (face-to-face ACP, first
        # 30 min, billable when at least 16 min are documented).
        acp_start = body.get("acp_start_time", "")
        acp_end = body.get("acp_end_time", "")
        try:
            acp_minutes = int(body.get("acp_total_minutes") or 0)
        except (TypeError, ValueError):
            acp_minutes = 0
        # Only surface the time block when the discussion was actually held.
        # The JS hides the time inputs when the radios flip to "No"/"declined",
        # but reads them regardless of display state, so stale minutes could
        # otherwise document time for a visit where ACP didn't occur.
        if discussion_occurred and (acp_start or acp_end or acp_minutes):
            time_bits = []
            if acp_start:
                time_bits.append(f"start {acp_start}")
            if acp_end:
                time_bits.append(f"end {acp_end}")
            if acp_minutes:
                time_bits.append(f"total {acp_minutes} min")
            narrative_parts.append(f"ACP time: {'; '.join(time_bits)}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "advancecareplanning", form_fields)

        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        # CPT II: 1123F (ACP documented) or 1124F (discussed, no plan completed)
        if directive_exists in ("Yes", "Yes - on file"):
            effects.append(_add_cpt_ii(note_id, "1123F"))
        elif acp_discussed in ("Yes", "Yes - discussed"):
            effects.append(_add_cpt_ii(note_id, "1124F"))

        # CPT 99497 - face-to-face ACP, first 30 minutes. CMS only allows the
        # code when (a) the discussion actually happened AND (b) at least 16
        # minutes of face-to-face time are documented. Without the discussion
        # gate, a provider who enters time then flips the radio to "No" /
        # "Patient declined" would silently bill 99497 - an auditable CMS
        # billing-compliance violation.
        if discussion_occurred and acp_minutes >= 16:
            effects.append(_add_cpt_ii(note_id, "99497"))

        log.info(f"SaveAdvanceCarePlanningHandler: saving ACP for note={note_id}")
        return effects


class SavePreventiveServicesHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save preventive services checklist statuses to the note.

    POST /awv/preventive-services
    Body: {
        note_id: str,
        services: dict[str, str]  - service_id -> "ordered"|"discussed"|"recent"|"declined"|"not_indicated"
    }

    Command types by service category:
    - Vaccines (ordered): PrescribeCommand via FDB lookup, fallback to InstructCommand
    - Labs (ordered): LabOrderCommand via LabPartner lookup, fallback to InstructCommand
    - Imaging (ordered): ImagingOrderCommand
    - Exams (ordered): PerformCommand
    - Any service (discussed): InstructCommand
    """

    PATH = "/awv/preventive-services"

    STATUS_LABELS: dict[str, str] = {
        "ordered": "Ordered today",
        "discussed": "Discussed with patient",
        "recent": "Done recently",
        "declined": "Patient declined",
        "not_indicated": "Not indicated",
    }

    # Service IDs match preventive_services.py module
    VACCINE_CODES: dict[str, dict[str, str]] = {
        "influenza": {"cpt": "90686", "cvx": "171", "search": "influenza vaccine injectable"},
        "pneumococcal": {"cpt": "90670", "cvx": "152", "search": "pneumococcal vaccine"},
        "covid_vaccine": {"cpt": "91318", "cvx": "311", "search": "covid-19 vaccine"},
        "tdap_td": {"cpt": "90715", "cvx": "115", "search": "tetanus diphtheria pertussis vaccine"},
        "shingles": {"cpt": "90750", "cvx": "187", "search": "shingrix zoster vaccine"},
        "rsv": {"cpt": "90679", "cvx": "309", "search": "rsv vaccine"},
    }

    IMAGING_CODES: dict[str, str] = {
        "mammogram": "77067",
        "ldct_lung": "71271",
        "aaa": "76706",
        "dexa": "77080",
    }

    LAB_CODES: dict[str, str] = {
        "colorectal": "82274",
        "diabetes_screen": "82947",
        "hep_c": "86803",
        "lipids": "80061",
        "prostate_psa": "84153",
    }

    EXAM_CODES: dict[str, str] = {
        "cervical_cancer": "88175",
    }

    SERVICE_LABELS: dict[str, str] = {
        "influenza": "Influenza Vaccine",
        "pneumococcal": "Pneumococcal Vaccine",
        "covid_vaccine": "COVID-19 Vaccine",
        "tdap_td": "Tdap/Td Vaccine",
        "shingles": "Shingrix Vaccine",
        "rsv": "RSV Vaccine",
        "mammogram": "Mammography Screening",
        "ldct_lung": "Low-Dose CT Lung Screening",
        "aaa": "Abdominal Aortic Aneurysm Ultrasound",
        "dexa": "Bone Density (DEXA Scan)",
        "colorectal": "Colorectal Cancer Screening",
        "diabetes_screen": "Diabetes/Prediabetes Screening",
        "hep_c": "Hepatitis C Screening",
        "lipids": "Lipid Panel",
        "prostate_psa": "Prostate Cancer Screening (PSA)",
        "cervical_cancer": "Cervical Cancer Screening",
    }

    def _get_staff_id(self) -> str | None:
        """Get the logged-in staff member's ID from session headers."""
        value = self.request.headers.get("canvas-logged-in-user-id")
        return str(value) if value else None

    def _lookup_fdb_medication(self, search_term: str) -> dict[str, Any] | None:
        """Search FDB for a medication and return the first result with clinical quantities."""
        try:
            from urllib.parse import urlencode

            from canvas_sdk.utils.http import ontologies_http

            resp = ontologies_http.get_json(
                f"/fdb/grouped-medication/?{urlencode({'search': search_term})}"
            )
            data = resp.json()
            results = data.get("results", [])
            if results and results[0].get("clinical_quantities"):
                result: dict[str, Any] = results[0]
                return result
        except Exception:
            log.warning(f"FDB lookup failed for '{search_term}'")
        return None

    def _get_lab_partner_and_test(self, cpt_code: str) -> tuple[str, str] | None:
        """Find an active lab partner that offers a test matching the given CPT code."""
        try:
            from canvas_sdk.v1.data.lab import LabPartner, LabPartnerTest

            test = (
                LabPartnerTest.objects.filter(
                    cpt_code=cpt_code,
                    lab_partner__active=True,
                )
                .select_related("lab_partner")
                .first()
            )
            if test:
                return (str(test.lab_partner.id), test.order_code)
        except Exception:
            log.warning(f"Lab partner lookup failed for CPT {cpt_code}")
        return None

    def _order_vaccine(
        self, note_id: str, service_id: str, staff_id: str | None,
    ) -> Effect:
        """Create a PrescribeCommand for a vaccine via FDB lookup, or InstructCommand fallback."""
        vc = self.VACCINE_CODES[service_id]
        label = self.SERVICE_LABELS.get(service_id, service_id)

        fdb_result = self._lookup_fdb_medication(vc["search"])
        if fdb_result and staff_id:
            cq = fdb_result["clinical_quantities"][0]
            return PrescribeCommand(
                note_uuid=note_id,
                fdb_code=str(fdb_result["med_medication_id"]),
                sig="Administer per vaccine schedule",
                days_supply=1,
                quantity_to_dispense=1,
                type_to_dispense=ClinicalQuantity(
                    representative_ndc=cq["representative_ndc"],
                    ncpdp_quantity_qualifier_code=cq["erx_ncpdp_script_quantity_qualifier_code"],
                ),
                refills=0,
                substitutions=PrescribeCommand.Substitutions.NOT_ALLOWED,
                prescriber_id=staff_id,
            ).originate()

        log.info(f"FDB lookup failed for {service_id}, using InstructCommand fallback")
        return InstructCommand(
            note_uuid=note_id,
            coding=Coding(
                system=CodeSystems.UNSTRUCTURED,
                code=f"Order: {label} (CPT {vc['cpt']})",
            ),
            comment="Ordered during AWV — vaccine prescription requires manual entry",
        ).originate()

    def _order_lab(self, note_id: str, service_id: str, staff_id: str | None) -> Effect:
        """Create a LabOrderCommand via LabPartner lookup, or InstructCommand fallback."""
        cpt_code = self.LAB_CODES[service_id]
        label = self.SERVICE_LABELS.get(service_id, service_id)

        result = self._get_lab_partner_and_test(cpt_code)
        if result:
            lab_partner_id, order_code = result
            kwargs: dict[str, Any] = {
                "note_uuid": note_id,
                "lab_partner": lab_partner_id,
                "tests_order_codes": [order_code],
                "comment": "Ordered during AWV",
            }
            if staff_id:
                kwargs["ordering_provider_key"] = staff_id
            return LabOrderCommand(**kwargs).originate()

        log.info(f"Lab partner lookup failed for {service_id}, using InstructCommand fallback")
        return InstructCommand(
            note_uuid=note_id,
            coding=Coding(
                system=CodeSystems.UNSTRUCTURED,
                code=f"Order: {label} (CPT {cpt_code})",
            ),
            comment="Ordered during AWV — lab order requires manual entry (no lab partner found)",
        ).originate()

    def _discuss_service(self, note_id: str, service_id: str) -> Effect:
        """Create an InstructCommand documenting that a service was discussed."""
        label = self.SERVICE_LABELS.get(service_id, service_id.replace("_", " ").title())
        return InstructCommand(
            note_uuid=note_id,
            coding=Coding(
                system=CodeSystems.UNSTRUCTURED,
                code=f"Discussed: {label}",
            ),
            comment="Discussed with patient during AWV",
        ).originate()

    def post(self) -> list[Response | Effect]:
        """Save preventive services statuses with typed Canvas commands."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        # Handle prevention plan comments save (from plan popup window)
        if "prevention_plan_comments" in body:
            existing = _get_all_form_states(note_id).get("preventiveservices", {})
            existing["prevention_plan_comments"] = body["prevention_plan_comments"]
            _save_form_state(note_id, "preventiveservices", existing)
            return [JSONResponse({"success": True})]

        services = body.get("services", {})
        plan_created = body.get("prevention_plan_created")
        written_copy = body.get("written_copy_given")

        # Accept attestation-only saves: a provider who reviewed the chart and
        # decided nothing needs to be ordered/discussed today can still satisfy
        # CMS Element 10 by answering the two attestation radios. Only reject
        # when there's truly nothing to save (no services AND no attestation).
        if not services and not plan_created and not written_copy:
            return [JSONResponse(
                {"success": False, "error": "No service statuses or attestation answers provided"},
                status_code=400,
            )]

        narrative_parts = ["**Preventive Services Checklist**"]
        for service_id, status in services.items():
            label = self.SERVICE_LABELS.get(service_id, service_id.replace("_", " ").title())
            status_label = self.STATUS_LABELS.get(status, status)
            narrative_parts.append(f"  {label}: {status_label}")

        if plan_created:
            narrative_parts.append(f"Personalized prevention plan created: {plan_created}")
        if written_copy:
            narrative_parts.append(f"Written copy of plan given to patient: {written_copy}")

        form_fields = body.pop("_form_fields", {})
        # Merge instead of overwrite. The Prevention Plan popup writes
        # 'prevention_plan_comments' into this same cache slot via the
        # popup-specific code path above, but that field is not rendered
        # inside the AWV modal's preventiveservices section - so the modal's
        # _form_fields cannot carry it. An unconditional overwrite here would
        # silently destroy the provider's typed comments on every subsequent
        # save. Read the existing dict and update in place to preserve any
        # keys the modal didn't send (matches the merge pattern used by the
        # popup save above and by SavePlanHandler attestation/assessmentplan).
        # Cache read is defensive: if it fails (test environment, transient
        # cache outage) we fall back to the legacy overwrite shape rather
        # than reject the save - data loss of the user's current keystrokes
        # would be worse than losing the popup-saved comments.
        try:
            existing_state = _get_all_form_states(note_id).get("preventiveservices", {})
        except Exception as exc:
            log.warning(f"SavePreventiveServicesHandler: cache read failed: {exc}")
            existing_state = {}
        merged_state = {**existing_state, **form_fields}
        _save_form_state(note_id, "preventiveservices", merged_state)
        effects: list[Response | Effect] = [JSONResponse({"success": True})]

        # Route the per-service checklist + CMS Element 10 attestation lines
        # to a PlanCommand. The per-service typed commands below land each
        # individual order on the chart, but the aggregate checklist and the
        # two attestation answers (plan_created / written_copy) only live in
        # the form-state cache without this routing - matching the v0.14.11
        # pattern used by every sister handler in this file.
        narrative = "\n".join(narrative_parts)
        if narrative.strip() and len(narrative_parts) > 1:
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        staff_id = self._get_staff_id()

        for service_id, status in services.items():
            if status == "ordered":
                if service_id in self.VACCINE_CODES:
                    effects.append(self._order_vaccine(note_id, service_id, staff_id))
                elif service_id in self.IMAGING_CODES:
                    effects.append(
                        ImagingOrderCommand(
                            note_uuid=note_id,
                            image_code=self.IMAGING_CODES[service_id],
                            priority=ImagingOrderCommand.Priority.ROUTINE,
                            comment="Ordered during AWV",
                        ).originate()
                    )
                elif service_id in self.EXAM_CODES:
                    effects.append(
                        PerformCommand(
                            note_uuid=note_id,
                            cpt_code=Coding(system=CodeSystems.CPT, code=self.EXAM_CODES[service_id]),
                            notes="Ordered during AWV",
                        ).originate()
                    )
                elif service_id in self.LAB_CODES:
                    effects.append(self._order_lab(note_id, service_id, staff_id))
            elif status == "discussed":
                effects.append(self._discuss_service(note_id, service_id))

        log.info(f"SavePreventiveServicesHandler: saving {len(services)} service statuses for note={note_id}")
        return effects


class SaveCurrentProvidersHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save current providers / suppliers list to the note.

    POST /awv/current-providers
    Body: {
        note_id: str,
        providers: dict[str, str]  - category_id -> text
    }
    """

    PATH = "/awv/current-providers"

    def post(self) -> list[Response | Effect]:
        """Save current providers list as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        providers = body.get("providers", {})

        category_labels = {
            "pcp": "Primary Care Provider",
            "pharmacy": "Pharmacy",
            "dme_suppliers": "DME / Medical Equipment Suppliers",
            "home_health": "Home Health / Visiting Nurse Services",
            "other_providers": "Other Providers",
        }

        narrative_parts = ["**Current Providers & Suppliers**"]
        for category_id, text in providers.items():
            if category_id == "specialists":
                continue
            if isinstance(text, str) and text.strip():
                label = category_labels.get(category_id, category_id.replace("_", " ").title())
                narrative_parts.append(f"{label}: {text.strip()}")

        # Structured specialists
        specialists = providers.get("specialists", [])
        if specialists and isinstance(specialists, list):
            narrative_parts.append("Specialists:")
            for s in specialists:
                name = s.get("name", "").strip()
                specialty = s.get("specialty", "").strip()
                phone = s.get("phone", "").strip()
                if name:
                    parts = [name]
                    if specialty:
                        parts.append(specialty)
                    if phone:
                        parts.append(phone)
                    narrative_parts.append(f"  - {', '.join(parts)}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "currentproviders", form_fields)
        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        # TaskCommand per specialist - prompts staff to add the provider to the
        # patient's external care team. Replaces the previous ReferCommand,
        # which incorrectly fired a clinical referral for every existing
        # specialist the provider happened to list during the AWV.
        if specialists and isinstance(specialists, list):
            for s in specialists:
                name = s.get("name", "").strip()
                if not name:
                    continue
                specialty = s.get("specialty", "").strip()
                phone = s.get("phone", "").strip()
                title = (
                    f"Add {name} ({specialty}) to external care team"
                    if specialty
                    else f"Add {name} to external care team"
                )
                comment_lines = ["Listed during Annual Wellness Visit."]
                if specialty:
                    comment_lines.append(f"Specialty: {specialty}")
                if phone:
                    comment_lines.append(f"Phone: {phone}")
                task_cmd = TaskCommand(
                    note_uuid=note_id,
                    title=title,
                    assign_to=TaskAssigner(to=AssigneeType.UNASSIGNED),
                    comment="\n".join(comment_lines),
                    labels=["AWV", "Care Team"],
                )
                effects.append(task_cmd.originate())

        # CreatePatientPreferredPharmacies for each newly added pharmacy.
        # New pharmacies are added as non-default - the patient's existing
        # default stays the default per user UX requirement.
        patient_id = body.get("patient_id", "")
        new_pharmacies = body.get("new_preferred_pharmacies", [])
        if patient_id and new_pharmacies and isinstance(new_pharmacies, list):
            from canvas_sdk.effects.patient import (
                CreatePatientPreferredPharmacies,
                PatientPreferredPharmacy,
            )
            pharmacy_dataclasses = [
                PatientPreferredPharmacy(
                    ncpdp_id=str(p.get("ncpdp_id", "")).strip(),
                    default=False,
                )
                for p in new_pharmacies
                if isinstance(p, dict) and p.get("ncpdp_id")
            ]
            if pharmacy_dataclasses:
                pharmacy_effect = CreatePatientPreferredPharmacies(
                    patient_id=patient_id,
                    pharmacies=pharmacy_dataclasses,
                )
                effects.append(pharmacy_effect.create())
                log.info(
                    f"SaveCurrentProvidersHandler: adding {len(pharmacy_dataclasses)} "
                    f"preferred pharmacy/pharmacies for patient={patient_id}"
                )

        log.info(f"SaveCurrentProvidersHandler: saving providers list for note={note_id}")
        return effects


class SaveHearingVisionHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save hearing and vision screening results to the note.

    POST /awv/hearing-vision
    Body: {
        note_id: str,
        hearing: dict[str, str],  - field_id -> value
        vision: dict[str, str]
    }
    """

    PATH = "/awv/hearing-vision"

    def post(self) -> list[Response | Effect]:
        """Save hearing and vision screening as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        hearing = body.get("hearing", {})
        vision = body.get("vision", {})

        narrative_parts = ["**Hearing & Vision Screening**"]

        # Hearing
        narrative_parts.append("Hearing:")
        if subjective := hearing.get("hearing_subjective"):
            narrative_parts.append(f"  Subjective: {subjective}")
        if aid_use := hearing.get("hearing_aid_use"):
            narrative_parts.append(f"  Hearing aids: {aid_use}")
        if whisper := hearing.get("whisper_test"):
            narrative_parts.append(f"  Whispered voice test: {whisper}")
        if referral := hearing.get("hearing_referral"):
            narrative_parts.append(f"  Audiology referral: {referral}")

        # Vision
        narrative_parts.append("Vision:")
        if subjective := vision.get("vision_subjective"):
            narrative_parts.append(f"  Subjective: {subjective}")
        if lenses := vision.get("corrective_lenses"):
            narrative_parts.append(f"  Corrective lenses: {lenses}")
        if snellen_r := vision.get("snellen_right"):
            narrative_parts.append(f"  Acuity OD (right): {snellen_r}")
        if snellen_l := vision.get("snellen_left"):
            narrative_parts.append(f"  Acuity OS (left): {snellen_l}")
        if last_exam := vision.get("last_eye_exam"):
            narrative_parts.append(f"  Last eye exam: {last_exam}")
        if referral := vision.get("vision_referral"):
            narrative_parts.append(f"  Eye care referral: {referral}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "hearingvision", form_fields)
        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        qid = _get_questionnaire_id("AWV_HEARING_VISION")
        if qid:
            sa_effect = _originate_sa(note_id, qid, "Hearing & Vision screening completed")
            if sa_effect:
                effects.append(sa_effect)

        log.info(f"SaveHearingVisionHandler: saving screening for note={note_id}")
        return effects


def _resolve_patient_sex_from_note(note_id: str) -> str:
    """Return "M", "F", or "" for the patient on this note.

    Server-side resolution avoids the JS/template plumbing risk that bit the
    AUDIT-C handler: if the frontend forgets to render a hidden patient_sex
    input, the handler used to silently default to the female threshold for
    every patient. Looking up the patient from the note removes that whole
    failure mode.
    """
    if not note_id:
        return ""
    try:
        from canvas_sdk.v1.data import Patient
        from canvas_sdk.v1.data.note import Note as NoteModel

        note = NoteModel.objects.filter(id=note_id).first()
        if not note:
            return ""
        patient = Patient.objects.filter(id=note.patient.id).first() if note.patient else None
        if not patient:
            return ""
        sex = str(getattr(patient, "sex_at_birth", "") or "").upper()
        # Normalize the various ways "male" / "female" can be expressed
        if sex.startswith("M"):
            return "M"
        if sex.startswith("F"):
            return "F"
        return ""
    except Exception as exc:
        log.warning(f"_resolve_patient_sex_from_note: lookup failed for note={note_id}: {exc}")
        return ""


class SaveAlcoholScreeningHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save AUDIT-C alcohol screening results to the note.

    POST /awv/alcohol-screening
    Body: {
        note_id: str,
        auditc_q1: int (0-4),
        auditc_q2: int (0-4),
        auditc_q3: int (0-4),
        total_score: int,
        patient_sex: str  - optional override; the handler otherwise resolves
                           sex_at_birth from the patient record on the note.
                           Server-side resolution is preferred because it
                           cannot silently fall back to the female threshold
                           when the frontend forgets to send the value.
    }
    """

    PATH = "/awv/alcohol-screening"

    def post(self) -> list[Response | Effect]:
        """Save AUDIT-C results as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        q1 = body.get("auditc_q1", 0)
        q2 = body.get("auditc_q2", 0)
        q3 = body.get("auditc_q3", 0)
        total = int(q1) + int(q2) + int(q3)
        # Prefer the patient record over the request body. The frontend used
        # to send patient_sex='' (no input was ever rendered), which defaulted
        # every patient to the female threshold (>=3) and over-flagged male
        # patients with a 3 as Positive. Falling back to the body value keeps
        # explicit overrides working for any caller that does set it.
        patient_sex = _resolve_patient_sex_from_note(note_id)
        if not patient_sex:
            patient_sex = body.get("patient_sex", "").upper()

        threshold = 4 if patient_sex == "M" else 3
        screen_result = "Positive" if total >= threshold else "Negative"

        narrative_parts = [
            "**Alcohol Screening (AUDIT-C)**",
            f"AUDIT-C Score: {total}/12",
            f"Threshold ({patient_sex or 'default'}): {threshold}",
            f"Screen result: {screen_result}",
        ]

        if total >= threshold:
            narrative_parts.append("Recommendation: Brief intervention and/or referral for alcohol misuse counseling.")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "alcoholscreening", form_fields)

        # StructuredAssessmentCommand for AUDIT-C
        qid = _get_questionnaire_id("72109-2") or "37b3d00f-86a1-4bf8-9a3b-f29dae1c39a5"

        effects: list[Response | Effect] = [
            JSONResponse({"success": True, "total_score": total, "screen_result": screen_result}),
        ]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())
        sa_effect = _originate_sa(note_id, qid, f"AUDIT-C Score: {total}/12 - {screen_result}")
        if sa_effect:
            effects.append(sa_effect)

        # CPT II: 3016F - Patient screened for unhealthy alcohol use
        effects.append(_add_cpt_ii(note_id, "3016F"))

        log.info(f"SaveAlcoholScreeningHandler: AUDIT-C={total}/12 ({screen_result}) for note={note_id}")
        return effects


class SaveMedicationReconciliationHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save medication reconciliation data to the note.

    POST /awv/medication-reconciliation
    Body: {
        note_id: str,
        reconciliation_method: str,
        otc_medications: str | null,
        supplements: str | null,
        adherence_assessment: str | null,
        high_risk_meds_identified: str | null,
        high_risk_meds_notes: str | null,
        reconciliation_attestation: list[str],
        reconciliation_notes: str | null
    }
    """

    PATH = "/awv/medication-reconciliation"

    def post(self) -> list[Response | Effect]:
        """Save medication reconciliation as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        narrative_parts = ["**Medication Reconciliation**"]

        if method := body.get("reconciliation_method"):
            narrative_parts.append(f"Reconciliation method: {method}")

        if otc := body.get("otc_medications"):
            narrative_parts.append(f"OTC medications: {otc}")

        if supplements := body.get("supplements"):
            narrative_parts.append(f"Supplements: {supplements}")

        if adherence := body.get("adherence_assessment"):
            narrative_parts.append(f"Adherence: {adherence}")

        high_risk = body.get("high_risk_meds_identified")
        if high_risk:
            narrative_parts.append(f"High-risk medications identified: {high_risk}")
            if high_risk == "Yes" and (notes := body.get("high_risk_meds_notes")):
                narrative_parts.append(f"High-risk medication details: {notes}")

        attestation = body.get("reconciliation_attestation", [])
        if attestation:
            narrative_parts.append(f"Attestation: {', '.join(attestation)}")

        if reconciled := body.get("medications_reconciled"):
            narrative_parts.append(f"Medications reconciled: {reconciled}")

        if recon_notes := body.get("reconciliation_notes"):
            narrative_parts.append(f"Notes: {recon_notes}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "medicationreconciliation", form_fields)
        review_cmd = ChartSectionReviewCommand(
            note_uuid=note_id,
            section=ChartSectionReviewCommand.Sections.MEDICATIONS,
        )

        effects: list[Response | Effect] = [JSONResponse({"success": True}), review_cmd.originate()]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        # CPT II: 1111F - Medications reconciled with current medication list.
        # Only emit when the provider actually attested reconciliation - the
        # prior unconditional append fired 1111F even on saves where the
        # provider answered No, falsely attesting reconciliation occurred.
        reconciled_val = str(body.get("medications_reconciled") or "").strip().lower()
        if reconciled_val in ("yes", "reconciled", "complete", "completed"):
            effects.append(_add_cpt_ii(note_id, "1111F"))

        log.info(f"SaveMedicationReconciliationHandler: saving reconciliation for note={note_id}")
        return effects


class SaveSDOHScreeningHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save SDOH screening results to the note.

    POST /awv/sdoh-screening
    Body: {
        note_id: str,
        responses: dict[str, Any]  - field_id -> value
    }
    """

    PATH = "/awv/sdoh-screening"

    DOMAIN_LABELS: dict[str, str] = {
        "sdoh_tool_used": "Screening tool used",
        "sdoh_housing_worried": "Housing concern",
        "sdoh_housing_conditions": "Housing conditions",
        "sdoh_food_worry": "Food worry",
        "sdoh_food_didnt_last": "Food didn't last",
        "sdoh_transportation": "Transportation barrier",
        "sdoh_social_contact": "Social contact frequency",
        "sdoh_loneliness": "Loneliness",
        "sdoh_feel_safe": "Feels safe",
        "sdoh_afraid_partner": "Afraid of partner/caregiver",
        "sdoh_utility_concerns": "Utility needs concern",
        "sdoh_utility_details": "Utility details",
        "sdoh_recreational_drugs": "Recreational drug use",
        "sdoh_substance_details": "Substance details",
        "sdoh_urinary_leakage": "Urinary leakage",
        "sdoh_incontinence_frequency": "Incontinence frequency",
        "sdoh_pain_present": "Pain present",
        "sdoh_pain_scale": "Pain scale",
        "sdoh_pain_location": "Pain location",
        "sdoh_referral_plan": "Referral/care coordination plan",
    }

    def post(self) -> list[Response | Effect]:
        """Save SDOH screening results as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        responses = body.get("responses", {})

        narrative_parts = ["**Social Determinants of Health (SDOH) Screening**"]
        for field_id, value in responses.items():
            label = self.DOMAIN_LABELS.get(field_id, field_id.replace("sdoh_", "").replace("_", " ").title())
            narrative_parts.append(f"{label}: {value}")

        # Detect positive screens and add summary
        positive_domains = _detect_sdoh_positives(responses)
        if positive_domains:
            narrative_parts.append("")
            narrative_parts.append(f"Positive screens identified: {', '.join(positive_domains)}")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "sdohscreening", form_fields)
        effects: list[Response | Effect] = [JSONResponse({"success": True})]
        # Route the joined narrative to a PlanCommand when non-empty so the
        # detailed clinical content the handler just built (safety warnings,
        # screen results, intervention notes, etc.) actually lands in the
        # note's chart-visible record. Prior code dropped this narrative.
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        qid = _get_questionnaire_id("AWV_SDOH")
        if qid:
            positives = ", ".join(positive_domains) if positive_domains else "None"
            sa_effect = _originate_sa(note_id, qid, f"SDOH Positives: {positives}")
            if sa_effect:
                effects.append(sa_effect)

        # CPT II: 1125F (pain present) or 1126F (no pain)
        pain_present = responses.get("sdoh_pain_present", "")
        if pain_present == "Yes":
            effects.append(_add_cpt_ii(note_id, "1125F"))
        elif pain_present == "No":
            effects.append(_add_cpt_ii(note_id, "1126F"))

        log.info(f"SaveSDOHScreeningHandler: saving SDOH screening for note={note_id}")
        return effects


class SaveMedicalHistoryHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Save medical history attestation to the note.

    POST /awv/medical-history
    Body: {
        note_id: str,
        medical_history_attestation: list[str]
    }
    """

    PATH = "/awv/medical-history"

    def post(self) -> list[Response | Effect]:
        """Save medical history attestation as a plan narrative."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]

        narrative_parts = ["**Medical History Review**"]

        attestation = body.get("medical_history_attestation", [])
        if attestation:
            narrative_parts.append(f"Attestation: {', '.join(attestation)}")
        else:
            narrative_parts.append("Medical history reviewed.")

        narrative = "\n".join(narrative_parts)

        form_fields = body.pop("_form_fields", {})
        _save_form_state(note_id, "medicalhistory", form_fields)
        review_cmd = ChartSectionReviewCommand(
            note_uuid=note_id,
            section=ChartSectionReviewCommand.Sections.CONDITIONS,
        )

        effects: list[Response | Effect] = [JSONResponse({"success": True}), review_cmd.originate()]
        # Route the joined narrative to a PlanCommand when non-empty (matches
        # the pattern used by the other Save handlers after Fix #18).
        if narrative.strip():
            effects.append(PlanCommand(note_uuid=note_id, narrative=narrative).originate())

        log.info(f"SaveMedicalHistoryHandler: saving medical history attestation for note={note_id}")
        return effects


class GetFormStateHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Retrieve saved AWV form state from all command types in the note.

    GET /awv/form-state?note_id=<uuid>
    """

    PATH = "/awv/form-state"

    def get(self) -> list[Response]:
        """Return saved form field values for all sections.

        Checks plugin cache first; falls back to scanning commands for legacy
        embedded form state tags.
        """
        note_id = self.request.query_params.get("note_id")
        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id required"}, status_code=400)]

        # Try cache first
        sections = _get_all_form_states(note_id)
        if sections:
            return [JSONResponse({"success": True, "sections": sections})]

        # Fallback: scan commands for legacy embedded form state
        from canvas_sdk.v1.data.command import Command

        commands = Command.objects.filter(note__id=note_id).order_by("created")

        text_values: list[str] = []
        for cmd in commands:
            data = cmd.data
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    text_values.append(data)
                    continue
            if isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, str):
                        text_values.append(value)

        sections = _extract_form_states(text_values)
        return [JSONResponse({"success": True, "sections": sections})]


class SaveAWVTypeHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Persist the provider's Initial vs Subsequent AWV selection to the
    plugin form-state cache so the choice survives modal reloads.

    The cache key "_awv_meta" is reserved for plugin metadata and is not
    a clinical section.

    POST /awv/awv-type
    Body: { note_id: str, awv_type: "initial" | "subsequent" }
    """

    PATH = "/awv/awv-type"

    def post(self) -> list[Response | Effect]:
        body = _parse_body(self.request)
        note_id = body.get("note_id")
        awv_type = body.get("awv_type")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]
        if awv_type not in ("initial", "subsequent"):
            return [JSONResponse(
                {"success": False, "error": "awv_type must be 'initial' or 'subsequent'"},
                status_code=400,
            )]

        _save_form_state(note_id, "_awv_meta", {"awv_type": awv_type})
        log.info(f"SaveAWVTypeHandler: awv_type={awv_type} note={note_id}")
        return [JSONResponse({"success": True, "awv_type": awv_type})]


def _detect_sdoh_positives(responses: dict[str, Any]) -> list[str]:
    """Return a list of positive SDOH domain labels based on screening responses."""
    positive: list[str] = []

    # Housing
    if responses.get("sdoh_housing_worried") == "Yes" or responses.get("sdoh_housing_conditions") == "Yes":
        positive.append("Housing")

    # Utility needs
    if responses.get("sdoh_utility_concerns") == "Yes":
        positive.append("Utility needs")

    # Food
    if responses.get("sdoh_food_worry") in ("Often true", "Sometimes true") or responses.get("sdoh_food_didnt_last") in ("Often true", "Sometimes true"):
        positive.append("Food")

    # Transportation
    if responses.get("sdoh_transportation") == "Yes":
        positive.append("Transportation")

    # Social isolation
    if responses.get("sdoh_social_contact") in ("Rarely", "Never") or responses.get("sdoh_loneliness") in ("Often", "Always"):
        positive.append("Social isolation")

    # Safety
    if responses.get("sdoh_feel_safe") == "No" or responses.get("sdoh_afraid_partner") == "Yes":
        positive.append("Safety")

    # Substance use
    if responses.get("sdoh_recreational_drugs") == "Yes":
        positive.append("Substance use")

    # Incontinence
    if responses.get("sdoh_urinary_leakage") == "Yes":
        positive.append("Incontinence")

    # Pain
    if responses.get("sdoh_pain_present") == "Yes":
        positive.append("Pain")

    return positive


def _get_phq9_severity(score: int) -> str:
    """Return PHQ-9 severity label for a given score."""
    if score <= 4:
        return "Minimal (0-4)"
    elif score <= 9:
        return "Mild (5-9)"
    elif score <= 14:
        return "Moderate (10-14)"
    elif score <= 19:
        return "Moderately Severe (15-19)"
    else:
        return "Severe (20-27)"


class GetScreeningDatesHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Retrieve last-done dates for preventive screenings from the patient's chart.

    GET /awv/screening-dates?patient_id=<uuid>&note_id=<uuid>
    Returns: { success: true, dates: { service_id: { last_done: "YYYY-MM-DD", overdue: bool }, ... } }
    """

    PATH = "/awv/screening-dates"

    # CVX codes per vaccine service (common codes for each vaccine type)
    VACCINE_CVX: dict[str, list[str]] = {
        "influenza": ["141", "150", "153", "155", "168", "171", "185", "186", "197", "205"],
        "pneumococcal": ["33", "100", "109", "133", "152", "215", "216"],
        "covid_vaccine": ["207", "208", "211", "212", "213", "217", "218", "219", "220", "221", "228", "229", "230", "300", "301", "302"],
        "tdap_td": ["113", "115", "138", "139"],
        "shingles": ["121", "187", "188"],
        "rsv": ["303", "304", "305", "306"],
    }

    # Keywords for matching vaccine display names (fallback when CVX codes don't match)
    VACCINE_KEYWORDS: dict[str, list[str]] = {
        "influenza": ["influenza", "flu vaccine", "flu shot"],
        "pneumococcal": ["pneumococcal", "ppsv23", "pcv13", "pcv15", "pcv20", "prevnar", "pneumovax"],
        "covid_vaccine": ["covid", "sars-cov", "moderna", "pfizer", "janssen", "novavax"],
        "tdap_td": ["tdap", "td vaccine", "tetanus", "diphtheria", "boostrix", "adacel"],
        "shingles": ["shingrix", "zoster", "shingles"],
        "rsv": ["rsv", "abrysvo", "arexvy"],
    }

    # LOINC codes for lab-based screenings
    LAB_LOINC: dict[str, list[str]] = {
        "lipids": ["57698-3", "2093-3", "2571-8", "2085-9", "13457-7"],
        "hep_c": ["16128-1", "5199-5", "13955-0"],
        "diabetes_screen": ["4548-4", "2339-0", "2345-7"],
        "hba1c": ["4548-4", "17856-6"],
        "prostate_psa": ["2857-1", "35741-8"],
    }

    # CPT codes for imaging-based screenings (matched against ImagingOrder.imaging text)
    IMAGING_KEYWORDS: dict[str, list[str]] = {
        "mammogram": ["mammog", "77067"],
        "dexa": ["dexa", "bone density", "77080"],
        "ldct_lung": ["ldct", "low-dose ct", "low dose ct", "lung screen", "71271"],
        "aaa": ["aortic aneurysm", "aaa", "76706"],
        "colorectal": ["colonoscop", "cologuard", "fit", "fobt", "G0121"],
        "cervical_cancer": ["pap", "cervical", "hpv", "88175", "87624"],
    }

    # Services considered annual (overdue if > 12 months)
    ANNUAL_SERVICES: set[str] = {
        "influenza", "mammogram", "annual_depression", "annual_cognitive",
        "lipids", "hba1c",
    }

    def get(self) -> list[Response]:
        """Look up last-done screening dates from the patient's chart."""
        patient_id = self.request.query_params.get("patient_id")
        note_id = self.request.query_params.get("note_id")

        if not patient_id:
            return [JSONResponse({"success": False, "error": "patient_id required"}, status_code=400)]

        dates: dict[str, dict[str, Any]] = {}
        today = date_type.today()
        one_year_ago = today - timedelta(days=365)

        # 1. Vaccines from immunization records
        self._lookup_vaccine_dates(patient_id, dates)

        # 2. Labs from lab results
        self._lookup_lab_dates(patient_id, dates)

        # 3. Imaging from imaging orders
        self._lookup_imaging_dates(patient_id, dates)

        # 4. Behavioral health from observations (chart history)
        self._lookup_bh_dates(patient_id, dates)

        # 5. Cross-section: depression/cognitive from current session (overrides chart)
        if note_id:
            self._lookup_session_dates(note_id, dates, today)

        # 6. Mark overdue for annual services
        for svc_id, info in dates.items():
            if svc_id in self.ANNUAL_SERVICES and info.get("last_done"):
                try:
                    last = date_type.fromisoformat(info["last_done"])
                    if last < one_year_ago:
                        info["overdue"] = True
                except ValueError:
                    pass

        log.info(f"GetScreeningDatesHandler: patient={patient_id}, dates_found={list(dates.keys())}")

        return [JSONResponse({"success": True, "dates": dates})]

    def _lookup_vaccine_dates(self, patient_id: str, dates: dict[str, dict[str, Any]]) -> None:
        """Look up most recent immunization dates from both Immunization and ImmunizationStatement."""
        try:
            from canvas_sdk.v1.data.immunization import (
                Immunization,
                ImmunizationCoding,
                ImmunizationStatement,
                ImmunizationStatementCoding,
            )

            # Build reverse map: CVX code → service ID
            cvx_to_svc: dict[str, str] = {}
            all_cvx: list[str] = []
            for svc_id, codes in self.VACCINE_CVX.items():
                for code in codes:
                    cvx_to_svc[code] = svc_id
                all_cvx.extend(codes)

            # Strategy 1: Single bulk query on ImmunizationStatementCoding
            stmt_rows = (
                ImmunizationStatementCoding.objects
                .filter(
                    immunization_statement__patient__id=patient_id,
                    immunization_statement__date__isnull=False,
                    code__in=all_cvx,
                )
                .order_by("-immunization_statement__date")
                .values_list("code", "immunization_statement__date")
            )
            for code, rec_date in stmt_rows:
                matched_svc = cvx_to_svc.get(code)
                if matched_svc and matched_svc not in dates:
                    dates[matched_svc] = {"last_done": rec_date.isoformat()}

            # Strategy 2: Single bulk query on ImmunizationCoding (fallback)
            missing_cvx = [c for c in all_cvx if cvx_to_svc.get(c) not in dates]
            if missing_cvx:
                imm_rows = (
                    ImmunizationCoding.objects
                    .filter(
                        immunization__patient__id=patient_id,
                        immunization__date_ordered__isnull=False,
                        code__in=missing_cvx,
                    )
                    .order_by("-immunization__date_ordered")
                    .values_list("code", "immunization__date_ordered")
                )
                for code, rec_date in imm_rows:
                    matched_svc = cvx_to_svc.get(code)
                    if matched_svc and matched_svc not in dates:
                        dates[matched_svc] = {"last_done": rec_date.isoformat()}

            # Strategy 3: Keyword match on display text (fallback)
            if any(svc_id not in dates for svc_id in self.VACCINE_KEYWORDS):
                # Fetch all immunization statement codings for this patient
                stmt_codings = list(
                    ImmunizationStatementCoding.objects
                    .filter(
                        immunization_statement__patient__id=patient_id,
                        immunization_statement__date__isnull=False,
                    )
                    .values_list("display", "immunization_statement__date")
                    .order_by("-immunization_statement__date")[:500]
                )
                # Fetch all immunization codings
                imm_codings = list(
                    ImmunizationCoding.objects
                    .filter(
                        immunization__patient__id=patient_id,
                        immunization__date_ordered__isnull=False,
                    )
                    .values_list("display", "immunization__date_ordered")
                    .order_by("-immunization__date_ordered")[:500]
                )
                all_records = stmt_codings + imm_codings

                for svc_id, keywords in self.VACCINE_KEYWORDS.items():
                    if svc_id in dates:
                        continue
                    for display, record_date in all_records:
                        if not display or not record_date:
                            continue
                        display_lower = display.lower()
                        if any(kw in display_lower for kw in keywords):
                            dates[svc_id] = {"last_done": record_date.isoformat()}
                            break
        except Exception:
            log.warning("GetScreeningDatesHandler: vaccine date lookup failed", exc_info=True)

    def _lookup_lab_dates(self, patient_id: str, dates: dict[str, dict[str, Any]]) -> None:
        """Look up most recent lab result dates by LOINC code."""
        try:
            from canvas_sdk.v1.data.lab import LabValueCoding

            # Build reverse map: LOINC code → service ID
            loinc_to_svc: dict[str, str] = {}
            all_loinc: list[str] = []
            for svc_id, codes in self.LAB_LOINC.items():
                for code in codes:
                    loinc_to_svc[code] = svc_id
                all_loinc.extend(codes)

            # Single bulk query for all lab LOINC codes
            lab_rows = (
                LabValueCoding.objects
                .filter(
                    value__report__patient__id=patient_id,
                    value__report__original_date__isnull=False,
                    code__in=all_loinc,
                    # REVIEW.md "Always check": exclude entered-in-error lab
                    # reports so a lab the clinician later invalidated doesn't
                    # claim a screening was done.
                    value__report__entered_in_error_id__isnull=True,
                )
                .order_by("-value__report__original_date")
                .values_list("code", "value__report__original_date")
            )
            for code, rec_date in lab_rows:
                matched_svc = loinc_to_svc.get(code)
                if matched_svc and matched_svc not in dates:
                    dates[matched_svc] = {"last_done": rec_date.date().isoformat()}
        except Exception:
            log.warning("GetScreeningDatesHandler: lab date lookup failed", exc_info=True)

    def _lookup_imaging_dates(self, patient_id: str, dates: dict[str, dict[str, Any]]) -> None:
        """Look up most recent imaging order dates by keyword match."""
        try:
            from canvas_sdk.v1.data.imaging import ImagingOrder

            orders = (
                ImagingOrder.objects
                # REVIEW.md "Always check": skip entered-in-error imaging orders.
                .filter(
                    patient__id=patient_id,
                    date_time_ordered__isnull=False,
                    entered_in_error_id__isnull=True,
                )
                .order_by("-date_time_ordered")
                .values_list("imaging", "date_time_ordered")[:200]
            )
            for svc_id, keywords in self.IMAGING_KEYWORDS.items():
                if svc_id in dates:
                    continue
                for imaging_name, ordered_dt in orders:
                    name_lower = imaging_name.lower()
                    if any(kw.lower() in name_lower for kw in keywords):
                        dates[svc_id] = {"last_done": ordered_dt.date().isoformat()}
                        break
        except Exception:
            log.warning("GetScreeningDatesHandler: imaging date lookup failed", exc_info=True)

    # LOINC codes for behavioral health screenings
    BH_LOINC: dict[str, list[str]] = {
        # Panel codes + individual total-score codes observed in Canvas
        "annual_depression": ["55757-9", "44249-1", "69725-0", "44261-6"],
        "annual_cognitive": ["72233-0", "72172-0"],
    }

    # Keywords for matching observation names (fallback)
    BH_KEYWORDS: dict[str, list[str]] = {
        "annual_depression": ["phq", "depression screen", "depression assess"],
        "annual_cognitive": ["mini-cog", "mini cog", "cognitive", "dementia screen", "mmse", "moca"],
    }

    # Questionnaire LOINC codes for Interview-based lookup
    BH_QUESTIONNAIRE_CODES: dict[str, list[str]] = {
        "annual_depression": ["69725-0", "44249-1"],  # PHQ-2, PHQ-9
        "annual_cognitive": ["72233-0", "72172-0"],  # Cognitive assessment, Mini-Cog
    }

    def _lookup_session_dates(
        self, note_id: str, dates: dict[str, dict[str, Any]], today: date_type
    ) -> None:
        """Check session cache and chart history for depression/cognitive.

        Prefers the section's own ``_last_saved`` ISO timestamp (written by
        the JS at save-time) so multi-day workflows report the correct date.
        Falls back to today only when the timestamp is missing or unparseable.
        """
        try:
            sections = _get_all_form_states(note_id)
            depression_section = sections.get("depressionscreening")
            if depression_section:
                dates["annual_depression"] = {
                    "last_done": _section_last_done_iso(depression_section, today),
                }
            cognitive_section = sections.get("cognitiveassessment")
            if cognitive_section:
                dates["annual_cognitive"] = {
                    "last_done": _section_last_done_iso(cognitive_section, today),
                }
        except Exception:
            log.warning("GetScreeningDatesHandler: session date lookup failed", exc_info=True)

    # Command schema_key patterns for BH screenings
    BH_COMMAND_KEYS: dict[str, list[str]] = {
        "annual_depression": ["structuredAssessment"],
        "annual_cognitive": ["structuredAssessment"],
    }

    # Keywords to match in command data JSON for each BH type
    BH_COMMAND_DATA_KEYWORDS: dict[str, list[str]] = {
        "annual_depression": ["phq", "depression", "PHQ-2", "PHQ-9", "69725-0", "44249-1"],
        "annual_cognitive": ["mini-cog", "mini_cog", "cognitive", "72233-0", "AWV_MINI_COG", "dementia"],
    }

    def _lookup_bh_dates(self, patient_id: str, dates: dict[str, dict[str, Any]]) -> None:
        """Look up behavioral health screening dates from observations and commands."""
        # Strategy 1: Observation records with LOINC codes
        try:
            from canvas_sdk.v1.data.observation import Observation, ObservationCoding

            for svc_id, loinc_codes in self.BH_LOINC.items():
                if svc_id in dates:
                    continue
                latest = (
                    ObservationCoding.objects
                    .filter(
                        observation__patient__id=patient_id,
                        observation__effective_datetime__isnull=False,
                        code__in=loinc_codes,
                        # REVIEW.md "Always check": skip entered-in-error
                        # observations. Strategy 1 runs FIRST and writes
                        # `dates[svc_id]`, with Strategy 2's `if svc_id in
                        # dates: continue` guard meaning Strategy 2 never
                        # touches the same svc - so the FK-reverse filter
                        # has to live here too or the bypass is silent.
                        observation__entered_in_error_id__isnull=True,
                    )
                    .order_by("-observation__effective_datetime")
                    .values_list("observation__effective_datetime", flat=True)
                    .first()
                )
                if latest:
                    dates[svc_id] = {"last_done": latest.date().isoformat()}

            # Strategy 2: Keyword match on observation name
            for svc_id, keywords in self.BH_KEYWORDS.items():
                if svc_id in dates:
                    continue
                for kw in keywords:
                    latest = (
                        Observation.objects
                        .filter(
                            patient__id=patient_id,
                            effective_datetime__isnull=False,
                            name__icontains=kw,
                            # REVIEW.md "Always check": skip entered-in-error
                            # observations so "Last screened" dates don't claim
                            # screenings the clinician already invalidated.
                            entered_in_error_id__isnull=True,
                        )
                        .order_by("-effective_datetime")
                        .values_list("effective_datetime", flat=True)
                        .first()
                    )
                    if latest:
                        dates[svc_id] = {"last_done": latest.date().isoformat()}
                        break
        except Exception:
            log.warning("GetScreeningDatesHandler: BH observation lookup failed", exc_info=True)

        # Strategy 3: Interview records (questionnaire responses)
        try:
            from canvas_sdk.v1.data.questionnaire import Interview

            for svc_id, q_codes in self.BH_QUESTIONNAIRE_CODES.items():
                if svc_id in dates:
                    continue
                latest = (
                    Interview.objects
                    .filter(
                        patient__id=patient_id,
                        status="AC",
                        questionnaires__code__in=q_codes,
                    )
                    .order_by("-dbid")
                    .values_list("note_id", "dbid")
                    .first()
                )
                if latest:
                    note_uuid, interview_dbid = latest
                    # Get the note's datetime for the interview date
                    from canvas_sdk.v1.data.note import Note
                    note = Note.objects.filter(id=note_uuid).values_list("created", flat=True).first()
                    if note:
                        dates[svc_id] = {"last_done": note.date().isoformat()}
        except Exception:
            log.warning("GetScreeningDatesHandler: BH interview lookup failed", exc_info=True)

        # Strategy 4: Command records with questionnaire schema_key
        try:
            from canvas_sdk.v1.data.command import Command

            if "annual_depression" not in dates or "annual_cognitive" not in dates:
                commands = list(
                    Command.objects
                    .filter(
                        patient__id=patient_id,
                        state="committed",
                        schema_key="questionnaire",
                    )
                    .order_by("-created")
                    .values_list("data", "created")[:200]
                )
                for svc_id, keywords in self.BH_COMMAND_DATA_KEYWORDS.items():
                    if svc_id in dates:
                        continue
                    for cmd_data, created in commands:
                        data_str = json.dumps(cmd_data).lower() if isinstance(cmd_data, dict) else str(cmd_data).lower()
                        if any(kw.lower() in data_str for kw in keywords):
                            dates[svc_id] = {"last_done": created.date().isoformat()}
                            break
        except Exception:
            log.warning("GetScreeningDatesHandler: BH command lookup failed", exc_info=True)


class GeneratePreventionPlanHandler(StaffSessionAuthMixin, SimpleAPIRoute):
    """
    Generate a personalized prevention plan document.

    POST /awv/generate-prevention-plan
    Body: { note_id: str }
    Returns: { success: true, html: "<html>...</html>" }
    """

    PATH = "/awv/generate-prevention-plan"

    # Frequency text -> timedelta for next-due calculation
    FREQUENCY_DAYS: dict[str, int] = {
        "Annual": 365,
        "Annual (updated formula)": 365,
        "Every 2 years (if normal)": 730,
        "Every 3 years (if overweight/obese)": 1095,
        "Every 5 years (or per risk)": 1825,
        "Tdap once, then Td booster every 10 years": 3650,
        "Per method (annual FIT/FOBT, every 3y FIT-DNA, every 10y colonoscopy)": 365,
        "Annual (ages 40-74) or biennial": 365,
        "Pap every 3y (21-29), Pap+HPV co-test every 5y or Pap every 3y (30-65)": 1095,
        "Annual (if qualifying smoker)": 365,
        "Every 3-6 months": 180,
    }

    IMMUNIZATION_IDS = {"influenza", "pneumococcal", "covid_vaccine", "tdap_td", "shingles", "rsv"}
    CANCER_SCREENING_IDS = {"colorectal", "dexa", "mammogram", "cervical_cancer", "ldct_lung",
                            "diabetes_screen", "aaa", "prostate_psa", "hep_c", "lipids"}

    def post(self) -> list[Response | Effect]:
        """Generate prevention plan HTML from saved AWV form state."""
        body = _parse_body(self.request)
        note_id = body.get("note_id")
        patient_id = body.get("patient_id")

        if not note_id:
            return [JSONResponse({"success": False, "error": "note_id is required"}, status_code=400)]
        if not patient_id:
            return [JSONResponse({"success": False, "error": "patient_id is required"}, status_code=400)]

        live_texts = body.get("live_texts", {})

        try:
            html = self._build_plan(note_id, patient_id, live_texts)
        except Exception as exc:
            log.warning(f"GeneratePreventionPlanHandler: failed to build plan: {exc}", exc_info=True)
            return [JSONResponse({"success": False, "error": str(exc)})]

        # Cache the generated HTML so the GET view can serve it
        cache = get_cache()
        cache.set(f"awv_prevention_plan_html:{note_id}", html, timeout_seconds=60 * 60)

        return [JSONResponse({"success": True})]

    def get(self) -> list[Response | Effect]:
        """Serve cached prevention plan HTML as a standalone page."""
        note_id = self.request.query_params.get("note_id", "")
        if not note_id:
            return [HTMLResponse("<p>note_id is required</p>", status_code=400)]

        cache = get_cache()
        html = cache.get(f"awv_prevention_plan_html:{note_id}", default="")
        if not html:
            return [HTMLResponse("<p>No prevention plan found. Generate one first.</p>", status_code=404)]

        return [HTMLResponse(html)]

    def _build_plan(self, note_id: str, patient_id: str, live_texts: dict[str, dict[str, str]] | None = None) -> str:
        from canvas_sdk.v1.data.note import Note
        from canvas_sdk.v1.data.patient import Patient, SexAtBirth
        from canvas_sdk.templates import render_to_string

        patient = Patient.objects.filter(id=patient_id).first()
        if not patient:
            raise ValueError("Patient not found")

        today = date_type.today()
        age = self._calculate_age(patient.birth_date)
        sex = patient.sex_at_birth

        # Determine AWV type from the provider's saved selection in the form-state cache.
        # Defaults to Initial (G0438) when no choice has been persisted yet.
        meta = _get_all_form_states(note_id).get("_awv_meta") or {}
        awv_type_value = meta.get("awv_type", "initial")
        awv_type = "Subsequent AWV (G0439)" if awv_type_value == "subsequent" else "Initial AWV (G0438)"

        # Build eligible services list
        from guided_awv.modules.preventive_services import build_services_list
        eligible = build_services_list(age, sex)

        # Get last-done dates from chart
        dates: dict[str, dict[str, Any]] = {}
        _lookup_all_screening_dates(str(patient.id), dates)

        # Check saved form state for ordered services and manually-entered dates
        form_state = _get_all_form_states(note_id)
        ordered_ids: set[str] = set()
        prev_state = form_state.get("preventiveservices", {})
        for key, val in prev_state.items():
            # Checkbox values arrive as lists from the frontend - use the
            # shape-tolerant _form_value_is helper instead of == comparisons.
            if key.startswith("svc_") and key.endswith("_ordered") and _form_value_is(val, "ordered"):
                svc_id = key[4:-8]  # strip svc_ and _ordered
                ordered_ids.add(svc_id)
            if (
                key.startswith("chronic_")
                and not key.endswith("_discussed")
                and not key.endswith("_last_date")
                and _form_value_is(val, "ordered")
            ):
                ordered_ids.add(key[8:])  # strip chronic_

        # Merge manually-entered dates from preventive services form.
        # Form-entered values take priority over chart history: a provider
        # who types a more recent (or corrected) date into the "Last done"
        # input has user-verified it, so it should override the
        # _lookup_all_screening_dates result. The previous guard
        # (``if svc_id not in dates``) only filled gaps - a chart record
        # always won, even when it was stale or wrong.
        for key, val in prev_state.items():
            if key.endswith("_last_date") and val:
                if key.startswith("svc_"):
                    svc_id = key[4:-10]  # strip svc_ and _last_date
                elif key.startswith("bh_"):
                    svc_id = key[3:-10]  # strip bh_ and _last_date
                elif key.startswith("chronic_"):
                    svc_id = key[8:-10]  # strip chronic_ and _last_date
                else:
                    continue
                dates[svc_id] = {"last_done": val}

        # Override last-done with today for ordered services
        for svc_id in ordered_ids:
            dates[svc_id] = {"last_done": today.isoformat()}

        # Build table rows
        imm_services = [s for s in eligible if s["id"] in self.IMMUNIZATION_IDS]
        cancer_services = [s for s in eligible if s["id"] in self.CANCER_SCREENING_IDS]

        imm_html = self._build_section_table("Immunizations", imm_services, dates, ordered_ids, today)
        cancer_html = self._build_section_table("Cancer Screenings & Preventive Labs", cancer_services, dates, ordered_ids, today)

        # Chronic disease monitoring — only if patient has diabetes or CVD
        chronic_html = self._build_chronic_section(str(patient.id), dates, ordered_ids, today, form_state)

        # Behavioral health — annual for all AWV patients
        bh_html = self._build_bh_section(dates, ordered_ids, today, form_state, note_id)

        # Functional assessment — annual for all AWV patients
        functional_html = self._build_functional_section(form_state)

        # Chronological next-due timeline across all sections
        all_plan_services = imm_services + cancer_services
        timeline_html = self._build_next_due_timeline(all_plan_services, dates, ordered_ids, today)

        # Patient display info
        sex_display = "Female" if sex in (SexAtBirth.FEMALE, "F") else "Male" if sex in (SexAtBirth.MALE, "M") else str(sex)
        patient_name = f"{patient.first_name or ''} {patient.last_name or ''}".strip() or "Unknown"
        dob_display = patient.birth_date.strftime("%m/%d/%Y") if patient.birth_date else "Unknown"

        # Next AWV: 11 months from today per CMS
        next_awv = today + timedelta(days=335)

        # Provider comments: previously saved comments, or auto-populated from AWV sections
        # live_texts from the frontend DOM take priority over cached form state
        lt = live_texts or {}
        provider_comments = prev_state.get("prevention_plan_comments", "")
        if not provider_comments:
            comment_parts: list[str] = []
            # Merge live texts over cached form state per section
            ap = {**form_state.get("assessmentplan", {}), **lt.get("assessmentplan", {})}
            if ap.get("prevention_plan"):
                comment_parts.append(f"Prevention Plan: {ap['prevention_plan']}")
            if ap.get("referrals"):
                comment_parts.append(f"Referrals: {ap['referrals']}")
            if ap.get("patient_education"):
                comment_parts.append(f"Patient Education: {ap['patient_education']}")
            medrec = {**form_state.get("medicationreconciliation", {}), **lt.get("medicationreconciliation", {})}
            if medrec.get("reconciliation_notes"):
                comment_parts.append(f"Medication Reconciliation: {medrec['reconciliation_notes']}")
            if medrec.get("high_risk_meds_notes"):
                comment_parts.append(f"High-Risk Medications: {medrec['high_risk_meds_notes']}")
            followup = {**form_state.get("followupscheduling", {}), **lt.get("followupscheduling", {})}
            if followup.get("followup_reason"):
                comment_parts.append(f"Follow-up: {followup['followup_reason']}")
            if followup.get("pending_labs"):
                comment_parts.append(f"Pending Labs/Studies: {followup['pending_labs']}")
            if followup.get("patient_goals"):
                comment_parts.append(f"Patient Goals: {followup['patient_goals']}")
            provider_comments = "\n".join(comment_parts)

        # API base URL from request
        api_base = ""
        try:
            host = self.request.META.get("HTTP_HOST", "") if self.request else ""
            if host:
                api_base = f"https://{host}"
        except Exception:
            pass

        template: str = render_to_string("templates/prevention_plan.html")
        # Escape every interpolated value that is *not* itself pre-built
        # trusted HTML. provider_comments is the highest-risk sink (raw
        # textarea text written to both a <textarea> and a <div>); the patient
        # name and dob come from the chart and could in principle hold HTML
        # characters; the section HTML blobs (imm_html, cancer_html, etc.)
        # are constructed by helpers below that escape their own data.
        # awv_type is one of two hardcoded strings, but escape for consistency.
        html = template.replace("[[patient_name]]", html_escape(str(patient_name)))
        html = html.replace("[[patient_dob]]", html_escape(str(dob_display)))
        html = html.replace("[[patient_age]]", html_escape(str(age)))
        html = html.replace("[[patient_sex]]", html_escape(str(sex_display)))
        html = html.replace("[[visit_date]]", today.strftime("%m/%d/%Y"))
        html = html.replace("[[awv_type]]", html_escape(awv_type))
        html = html.replace("[[immunizations_section]]", imm_html)
        html = html.replace("[[cancer_screenings_section]]", cancer_html)
        html = html.replace("[[chronic_disease_section]]", chronic_html)
        html = html.replace("[[behavioral_health_section]]", bh_html)
        html = html.replace("[[functional_assessment_section]]", functional_html)
        html = html.replace("[[next_due_timeline]]", timeline_html)
        html = html.replace("[[next_awv_date]]", next_awv.strftime("%m/%d/%Y"))
        html = html.replace("[[provider_comments]]", html_escape(provider_comments))
        html = html.replace("[[note_id]]", html_escape(note_id))
        html = html.replace("[[api_base]]", html_escape(api_base))

        return html

    def _build_section_table(
        self,
        title: str,
        services: list[dict[str, Any]],
        dates: dict[str, dict[str, Any]],
        ordered_ids: set[str],
        today: date_type,
    ) -> str:
        if not services:
            return ""

        rows = ""
        for svc in services:
            svc_id = svc["id"]
            name = svc["name"]
            frequency = svc.get("frequency", "")
            date_info = dates.get(svc_id, {})
            last_done_str = date_info.get("last_done", "")

            # Status and next-due calculation
            if svc_id in ordered_ids:
                last_display = today.strftime("%m/%d/%Y")
                status = '<span class="status-ordered">Ordered today</span>'
                next_due = self._calc_next_due(today, frequency)
            elif last_done_str:
                try:
                    last_date = date_type.fromisoformat(last_done_str)
                    last_display = last_date.strftime("%m/%d/%Y")
                    next_due = self._calc_next_due(last_date, frequency)
                    if next_due and next_due <= today:
                        status = '<span class="status-due">Due</span>'
                    else:
                        status = '<span class="status-uptodate">Up to date</span>'
                except ValueError:
                    last_display = last_done_str
                    next_due = None
                    status = '<span class="status-uptodate">Up to date</span>'
            else:
                last_display = "—"
                next_due = None
                status = '<span class="status-due">No record — discuss with provider</span>'

            next_display = next_due.strftime("%m/%d/%Y") if next_due else "—"

            # last_display can hold a raw cached string when fromisoformat
            # fails (see the except ValueError branch above) - escape every
            # value flowing into a <td> to neutralize that and any future
            # data-source surprise. `status` is plugin-built HTML and stays
            # un-escaped; `next_display` is a strftime or "&mdash;".
            rows += (
                f"<tr>"
                f"<td>{html_escape(str(name))}</td>"
                f"<td>{status}</td>"
                f"<td>{next_display}</td>"
                f"<td>{html_escape(str(last_display))}</td>"
                f"<td>{html_escape(str(frequency))}</td>"
                f"</tr>"
            )

        return (
            f'<div class="section-title">{html_escape(str(title))}</div>'
            f"<table>"
            f"<tr><th>Service</th><th>Status</th><th>Next Due</th><th>Last Done</th><th>Frequency</th></tr>"
            f"{rows}"
            f"</table>"
        )

    def _calc_next_due(self, last_date: date_type, frequency: str) -> date_type | None:
        days = self.FREQUENCY_DAYS.get(frequency)
        if days:
            return last_date + timedelta(days=days)
        # One-time screens: no next-due
        freq_lower = frequency.lower()
        if "one-time" in freq_lower or "single dose" in freq_lower or "2-dose" in freq_lower:
            return None
        if "per schedule" in freq_lower:
            return None
        if "discuss" in freq_lower:
            return None
        # Default: annual
        return last_date + timedelta(days=365)

    # ICD-10 prefixes for chronic disease relevance
    DIABETES_ICD10 = ("E08", "E09", "E10", "E11", "E13")
    CVD_ICD10 = ("I10", "I11", "I12", "I13", "I15", "I20", "I21", "I22", "I23", "I24", "I25",
                 "I48", "I50", "I63", "I65", "I66", "I67", "I70")

    CHRONIC_ITEMS = [
        {"id": "hba1c", "name": "HbA1c (Diabetes)", "frequency": "Every 3-6 months", "condition": "diabetes"},
        {"id": "diabetic_eye_exam", "name": "Diabetic Eye Exam", "frequency": "Annual", "condition": "diabetes"},
        {"id": "diabetic_foot_exam", "name": "Diabetic Foot Exam", "frequency": "Annual", "condition": "diabetes"},
        {"id": "lipid_panel_cvd", "name": "Lipid Panel (CVD Monitoring)", "frequency": "Annual", "condition": "cvd"},
    ]

    BH_ITEMS = [
        {"id": "annual_depression", "name": "Annual Depression Screening", "frequency": "Annual"},
        {"id": "annual_cognitive", "name": "Annual Cognitive Assessment", "frequency": "Annual"},
    ]

    FUNCTIONAL_ITEMS = [
        {"id": "fall_risk", "name": "Fall Risk Screening (STEADI)", "frequency": "Annual"},
        {"id": "adl_iadl", "name": "ADL / IADL Functional Assessment", "frequency": "Annual"},
    ]

    def _build_chronic_section(
        self,
        patient_id: str,
        dates: dict[str, dict[str, Any]],
        ordered_ids: set[str],
        today: date_type,
        form_state: dict[str, Any],
    ) -> str:
        """Build chronic disease monitoring section, only if patient has relevant conditions."""
        try:
            from canvas_sdk.v1.data.condition import Condition, ClinicalStatus
            # REVIEW.md "Always check": filter entered-in-error so the
            # chronic-disease panel in the printed Prevention Plan doesn't
            # claim a patient has a condition that was flagged as mistaken.
            conditions = list(
                Condition.objects.filter(
                    patient__id=patient_id,
                    clinical_status=ClinicalStatus.ACTIVE,
                    deleted=False,
                    entered_in_error_id__isnull=True,
                ).values_list("codings__code", flat=True)
            )
        except Exception:
            conditions = []

        has_diabetes = any(
            c and any(c.startswith(p) for p in self.DIABETES_ICD10)
            for c in conditions
        )
        has_cvd = any(
            c and any(c.startswith(p) for p in self.CVD_ICD10)
            for c in conditions
        )

        if not has_diabetes and not has_cvd:
            return ""

        rows = ""
        prev_state = form_state.get("preventiveservices", {})
        for item in self.CHRONIC_ITEMS:
            if item["condition"] == "diabetes" and not has_diabetes:
                continue
            if item["condition"] == "cvd" and not has_cvd:
                continue

            svc_id = item["id"]
            # Check if ordered in this visit
            chronic_key = f"chronic_{svc_id}"
            is_ordered = svc_id in ordered_ids or _form_value_is(prev_state.get(chronic_key), "ordered")

            date_info = dates.get(svc_id, {})
            last_done_str = date_info.get("last_done", "")

            # Form-entered date overrides chart history when present, matching
            # the same priority used in _build_plan above. Provider's typed
            # value is user-verified; chart history may be stale.
            form_last = prev_state.get(f"chronic_{svc_id}_last_date", "")
            if form_last:
                last_done_str = form_last

            if is_ordered:
                last_display = today.strftime("%m/%d/%Y")
                status = '<span class="status-ordered">Ordered today</span>'
                next_due = self._calc_next_due(today, item["frequency"])
            elif last_done_str:
                try:
                    last_date = date_type.fromisoformat(last_done_str)
                    last_display = last_date.strftime("%m/%d/%Y")
                    next_due = self._calc_next_due(last_date, item["frequency"])
                    if next_due and next_due <= today:
                        status = '<span class="status-due">Due</span>'
                    else:
                        status = '<span class="status-uptodate">Up to date</span>'
                except ValueError:
                    last_display = last_done_str
                    next_due = None
                    status = '<span class="status-uptodate">Up to date</span>'
            else:
                last_display = "—"
                next_due = None
                status = '<span class="status-due">No record</span>'

            next_display = next_due.strftime("%m/%d/%Y") if next_due else "—"
            rows += (
                f"<tr><td>{html_escape(str(item['name']))}</td><td>{status}</td>"
                f"<td>{next_display}</td><td>{html_escape(str(last_display))}</td>"
                f"<td>{html_escape(str(item['frequency']))}</td></tr>"
            )

        return (
            '<div class="section-title">Chronic Disease Monitoring</div>'
            "<table>"
            "<tr><th>Service</th><th>Status</th><th>Next Due</th><th>Last Done</th><th>Frequency</th></tr>"
            f"{rows}"
            "</table>"
        )

    def _build_bh_section(
        self,
        dates: dict[str, dict[str, Any]],
        ordered_ids: set[str],
        today: date_type,
        form_state: dict[str, Any],
        note_id: str,
    ) -> str:
        """Build behavioral health monitoring section."""
        # Use the section's _last_saved timestamp when present so a multi-day
        # AWV workflow reports the actual screening date, not "today" relative
        # to when the Prevention Plan was generated.
        sections = form_state
        depression_section = sections.get("depressionscreening")
        if depression_section:
            dates["annual_depression"] = {
                "last_done": _section_last_done_iso(depression_section, today),
            }
        cognitive_section = sections.get("cognitiveassessment")
        if cognitive_section:
            dates["annual_cognitive"] = {
                "last_done": _section_last_done_iso(cognitive_section, today),
            }

        rows = ""
        for item in self.BH_ITEMS:
            svc_id = item["id"]
            date_info = dates.get(svc_id, {})
            last_done_str = date_info.get("last_done", "")

            if last_done_str:
                try:
                    last_date = date_type.fromisoformat(last_done_str)
                    last_display = last_date.strftime("%m/%d/%Y")
                    next_due = last_date + timedelta(days=365)
                    if last_date == today:
                        status = '<span class="status-ordered">Completed today</span>'
                    elif next_due <= today:
                        status = '<span class="status-due">Due</span>'
                    else:
                        status = '<span class="status-uptodate">Up to date</span>'
                except ValueError:
                    last_display = last_done_str
                    next_due = today + timedelta(days=365)
                    status = '<span class="status-uptodate">Up to date</span>'
            else:
                last_display = "—"
                next_due = None
                status = '<span class="status-due">No record</span>'

            next_display = next_due.strftime("%m/%d/%Y") if next_due else "—"
            rows += (
                f"<tr><td>{html_escape(str(item['name']))}</td><td>{status}</td>"
                f"<td>{next_display}</td><td>{html_escape(str(last_display))}</td>"
                f"<td>{html_escape(str(item['frequency']))}</td></tr>"
            )

        return (
            '<div class="section-title">Behavioral Health</div>'
            "<table>"
            "<tr><th>Service</th><th>Status</th><th>Next Due</th><th>Last Done</th><th>Frequency</th></tr>"
            f"{rows}"
            "</table>"
        )

    def _build_functional_section(self, form_state: dict[str, Any]) -> str:
        """Build functional assessment section."""
        today = date_type.today()
        rows = ""
        for item in self.FUNCTIONAL_ITEMS:
            # Check if the related section was saved in this session
            completed_today = False
            if item["id"] == "fall_risk" and form_state.get("fallrisk"):
                completed_today = True
            elif item["id"] == "adl_iadl" and form_state.get("functionalability"):
                completed_today = True

            if completed_today:
                last_display = today.strftime("%m/%d/%Y")
                next_due = today + timedelta(days=365)
                status = '<span class="status-ordered">Completed today</span>'
            else:
                last_display = "—"
                next_due = None
                status = '<span class="status-due">No record</span>'

            next_display = next_due.strftime("%m/%d/%Y") if next_due else "—"
            rows += (
                f"<tr><td>{html_escape(str(item['name']))}</td><td>{status}</td>"
                f"<td>{next_display}</td><td>{html_escape(str(last_display))}</td>"
                f"<td>{html_escape(str(item['frequency']))}</td></tr>"
            )

        return (
            '<div class="section-title">Functional Assessment</div>'
            "<table>"
            "<tr><th>Service</th><th>Status</th><th>Next Due</th><th>Last Done</th><th>Frequency</th></tr>"
            f"{rows}"
            "</table>"
        )

    def _build_next_due_timeline(
        self,
        services: list[dict[str, Any]],
        dates: dict[str, dict[str, Any]],
        ordered_ids: set[str],
        today: date_type,
    ) -> str:
        """Build a chronological list of upcoming services sorted by next-due date."""
        upcoming: list[tuple[date_type, str]] = []

        # Collect from preventive services
        for svc in services:
            svc_id = svc["id"]
            frequency = svc.get("frequency", "")
            date_info = dates.get(svc_id, {})
            last_done_str = date_info.get("last_done", "")

            if svc_id in ordered_ids:
                next_due = self._calc_next_due(today, frequency)
            elif last_done_str:
                try:
                    last_date = date_type.fromisoformat(last_done_str)
                    next_due = self._calc_next_due(last_date, frequency)
                except ValueError:
                    next_due = None
            else:
                next_due = None

            if next_due and next_due > today:
                upcoming.append((next_due, svc["name"]))

        # Add chronic, BH, functional items
        for item in self.CHRONIC_ITEMS + self.BH_ITEMS + self.FUNCTIONAL_ITEMS:
            svc_id = item["id"]
            date_info = dates.get(svc_id, {})
            last_done_str = date_info.get("last_done", "")
            if last_done_str:
                try:
                    last_date = date_type.fromisoformat(last_done_str)
                    next_due = last_date + timedelta(days=365)
                    if next_due > today:
                        upcoming.append((next_due, item["name"]))
                except ValueError:
                    pass

        if not upcoming:
            return ""

        upcoming.sort(key=lambda x: x[0])

        rows = ""
        for due_date, name in upcoming:
            rows += f"<tr><td>{due_date.strftime('%m/%d/%Y')}</td><td>{name}</td></tr>"

        return (
            '<div class="section-title">Upcoming Services Timeline</div>'
            "<table>"
            "<tr><th>Next Due</th><th>Service</th></tr>"
            f"{rows}"
            "</table>"
        )

    def _calculate_age(self, birth_date: date_type | None) -> int:
        if not birth_date:
            return 0
        today = date_type.today()
        return today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )
