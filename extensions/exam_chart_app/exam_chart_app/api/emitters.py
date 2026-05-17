"""Section / order command emitters used by ExamChartingAPI.finalize().

Each `_emit_*` function takes a per-section payload from the form and
returns either an Effect (the originated command) or a JSONResponse
(structured validation error / 500). The finalize handler iterates
these and short-circuits on the first error response.

Split out of `exam_api.py` to keep the route handlers + auth surface in
one file and the emitter logic in another. SDK Command classes are
imported here (where they're used) — tests patch them via
``exam_chart_app.api.emitters.<Command>`` rather than the old
``exam_chart_app.api.exam_api.<Command>`` path.
"""
from __future__ import annotations

import uuid
from datetime import date
from http import HTTPStatus
from typing import Any

from canvas_sdk.commands import (
    AssessCommand,
    DiagnoseCommand,
    FollowUpCommand,
    GoalCommand,
    ImagingOrderCommand,
    LabOrderCommand,
    PlanCommand,
    PrescribeCommand,
    ReferCommand,
)
from canvas_sdk.commands.constants import ClinicalQuantity
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse
from logger import log

def _emit_questionnaire(
    kind: str,
    command_cls: Any,
    section_payload: Any,
    note_uuid: str,
) -> tuple[list[Effect], list[tuple[str, str]], JSONResponse | None]:
    """Build and originate a QuestionnaireCommand subclass (ROS or PE) from
    the per-section payload. Returns
    ``(effects, pending_narratives, error_response)``.

    ``pending_narratives`` is a list of ``(command_uuid, narrative)`` pairs
    the caller MUST flush via ``set_narrative(...)`` only after every
    per-section emitter has succeeded (the finalize-level failures gate).
    Flushing inline here would leak an AttributeHub row on a later-section
    failure, violating the documented all-or-nothing finalize invariant.

    - ``([], [], None)`` means the section is empty (no responses, no
      skipped, no narrative) — caller skips it.
    - ``([originate_effect], [(uuid, narrative)], None)`` means the command
      was emitted and a narrative needs to be stashed post-gate.
    - ``([originate_effect], [], None)`` means the command was emitted
      with no narrative to stash.
    - ``([], [], JSONResponse)`` means a structured validation error or an
      ``.originate()`` exception; caller returns the error immediately.
    """
    if not isinstance(section_payload, dict):
        return [], [], None
    questionnaire_id = (section_payload.get("questionnaire_id") or "").strip() or None
    responses_raw = section_payload.get("responses")
    responses = responses_raw if isinstance(responses_raw, dict) else {}
    skipped_raw = section_payload.get("skipped")
    skipped: list[str] = (
        [str(s) for s in skipped_raw] if isinstance(skipped_raw, list) else []
    )
    narrative = str(section_payload.get("narrative") or "").strip()

    has_responses = bool(responses)
    has_skipped = bool(skipped)
    has_narrative = bool(narrative)
    if not (has_responses or has_skipped or has_narrative):
        return [], [], None

    if (has_responses or has_skipped) and not questionnaire_id:
        return [], [], JSONResponse(
            {"errors": [{
                "section": kind,
                "field": "questionnaire_id",
                "message": "Pick a questionnaire before setting responses.",
            }]},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    # Mint a command UUID up front so we can reference the same command
    # in both the originate effect and the metadata-form effect that
    # attaches the narrative.
    command_uuid = str(uuid.uuid4())
    kwargs: dict[str, Any] = {"note_uuid": note_uuid, "command_uuid": command_uuid}
    if questionnaire_id:
        kwargs["questionnaire_id"] = questionnaire_id

    try:
        command = command_cls(**kwargs)
        skipped_set = set(skipped)
        for q in command.questions:
            qid = str(q.id)
            if qid in responses:
                _dispatch_response(q, responses[qid])
                command.set_question_enabled(qid, True)
            else:
                # No response: disable the toggle. For TEXT-type questions
                # also set the response to an empty string so the chart
                # doesn't fall back to the questionnaire's default option
                # value alongside the disabled toggle (which is what we
                # observed on Brief PE: SKIN / CARDIOVASCULAR rows showed
                # default text next to off-toggles).
                if getattr(q, "type", "") == "TXT":
                    try:
                        q.add_response(text="")
                    except (ValueError, TypeError):
                        pass
                command.set_question_enabled(qid, False)
        # Mark the union of skipped_set explicitly too in case it
        # contains question ids that didn't surface in command.questions
        # (defensive — should be a no-op when both lists overlap).
        for qid in skipped_set:
            command.set_question_enabled(qid, False)
        log.info(
            f"[ExamChartingAPI] {kind} originate command_uuid={command_uuid} "
            f"questionnaire_id={questionnaire_id!r} response_qids={list(responses.keys())} "
            f"narrative_len={len(narrative)}"
        )
        out_effects: list[Effect] = [command.originate()]
        # Defer the narrative write to the caller. Writing inline here
        # would persist an AttributeHub row before finalize's failures
        # gate, so a later-section failure would leave an orphaned row
        # while the originate effect is discarded.
        pending_narratives: list[tuple[str, str]] = []
        if narrative:
            pending_narratives.append((command_uuid, narrative))
            log.info(
                f"[ExamChartingAPI] {kind} narrative buffered for "
                f"command_uuid={command_uuid} len={len(narrative)} "
                f"(flush deferred to post-gate)"
            )
        return out_effects, pending_narratives, None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] {kind} originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return [], [], JSONResponse(
            {"errors": [{
                "section": kind,
                "field": "",
                "message": f"Could not emit {kind}: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _dispatch_response(question: Any, raw_response: Any) -> None:
    """Record a response on a single question, dispatching by question type.

    JS always sends responses as a list (`[option_value, ...]`), even for
    single-select questions. The SDK's add_response signatures differ:

      - TextQuestion(TXT):     add_response(text=...)
      - IntegerQuestion(INT):  add_response(integer=...)
      - RadioQuestion(SING):   add_response(option) — must be a ResponseOption
        instance from question.options
      - CheckboxQuestion(MULT): add_response(option, selected=..., comment=...)
        — called once per selected option

    Match by option.value first, then option.code (NLM-style codes vs.
    plugin-bundled values).
    """
    values = raw_response if isinstance(raw_response, list) else [raw_response]
    values_as_str = {str(v) for v in values if v is not None and v != ""}
    if not values_as_str:
        return

    q_type = getattr(question, "type", "")

    if q_type == "MULT":
        for option in getattr(question, "options", []) or []:
            opt_value = str(getattr(option, "value", "") or "")
            opt_code = str(getattr(option, "code", "") or "")
            if opt_value in values_as_str or opt_code in values_as_str:
                question.add_response(option, selected=True)
    elif q_type == "SING":
        for option in getattr(question, "options", []) or []:
            opt_value = str(getattr(option, "value", "") or "")
            opt_code = str(getattr(option, "code", "") or "")
            if opt_value in values_as_str or opt_code in values_as_str:
                question.add_response(option)
                return
    elif q_type == "TXT":
        question.add_response(text=next(iter(values_as_str)))
    elif q_type == "INT":
        try:
            question.add_response(integer=int(next(iter(values_as_str))))
        except (ValueError, TypeError):
            pass
    # Unknown / unset type → silently skip; the command can still originate
    # with this question unanswered.


_ASSESS_STATUS_MAP = {
    "improved": AssessCommand.Status.IMPROVED,
    "stable": AssessCommand.Status.STABLE,
    "deteriorated": AssessCommand.Status.DETERIORATED,
}


def _emit_diagnosis_block(
    note_uuid: str, entry: Any
) -> tuple[list[Effect], dict[str, int], JSONResponse | None]:
    """One diagnosis entry → 1 DiagnoseCommand + optional AssessCommand +
    optional PlanCommand, all keyed to the same ICD-10. Entries missing a
    code are silently skipped (the JS shouldn't allow them, defensive).

    Returns (effects, counts_by_type, error_response).
    counts_by_type: {"diagnose": int, "assess": int, "plan": int}
    """
    counts = {"diagnose": 0, "assess": 0, "plan": 0}
    if not isinstance(entry, dict):
        return [], counts, None
    code = str(entry.get("code") or "").strip()
    if not code:
        return [], counts, None

    existing_condition_id = str(entry.get("existing_condition_id") or "").strip()

    effects: list[Effect] = []

    # ----- DiagnoseCommand (only for new diagnoses) -----
    # When the picked code already exists as an active patient Condition,
    # we skip DiagnoseCommand (which creates a new Condition) and emit
    # only AssessCommand with condition_id pointing to the existing row.
    if not existing_condition_id:
        dx_kwargs: dict[str, Any] = {"note_uuid": note_uuid, "icd10_code": code}
        today_assessment = str(entry.get("today_assessment") or "").strip()
        if today_assessment:
            dx_kwargs["today_assessment"] = today_assessment
        background = str(entry.get("background") or "").strip()
        if background:
            dx_kwargs["background"] = background
        try:
            effects.append(DiagnoseCommand(**dx_kwargs).originate())
            counts["diagnose"] = counts["diagnose"] + 1
        except (ValueError, TypeError) as exc:
            log.warning(
                f"[ExamChartingAPI] Diagnose originate failed for {code!r}: "
                f"{exc.__class__.__name__}: {exc}"
            )
            return [], counts, JSONResponse(
                {"errors": [{
                    "section": "ap.diagnoses",
                    "field": "icd10_code",
                    "message": f"Could not emit Diagnose ({code}): {exc.__class__.__name__}",
                }]},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    # ----- AssessCommand (per-diagnosis) -----
    raw_assessment = entry.get("assessment")
    assessment: dict[str, Any] = raw_assessment if isinstance(raw_assessment, dict) else {}
    status_raw = str(assessment.get("status") or "").strip().lower()
    assess_narrative = str(assessment.get("narrative") or "").strip()
    # Existing-condition entries always emit Assess (with condition_id),
    # even with empty status/narrative — the chart needs the Assess row
    # to surface the existing condition as touched on this visit. New
    # diagnoses skip Assess when both fields are empty (provider may
    # not have intended one).
    if existing_condition_id or status_raw or assess_narrative:
        ass_kwargs: dict[str, Any] = {"note_uuid": note_uuid}
        if existing_condition_id:
            ass_kwargs["condition_id"] = existing_condition_id
        if status_raw:
            status_enum = _ASSESS_STATUS_MAP.get(status_raw)
            if status_enum is None:
                return effects, counts, JSONResponse(
                    {"errors": [{
                        "section": "ap.diagnoses",
                        "field": "assessment.status",
                        "message": f"Unknown status: {status_raw!r}",
                    }]},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ass_kwargs["status"] = status_enum
        if assess_narrative:
            ass_kwargs["narrative"] = assess_narrative
        try:
            effects.append(AssessCommand(**ass_kwargs).originate())
            counts["assess"] = counts["assess"] + 1
        except (ValueError, TypeError) as exc:
            log.warning(
                f"[ExamChartingAPI] Assess originate failed for dx={code!r}: "
                f"{exc.__class__.__name__}: {exc}"
            )
            return effects, counts, JSONResponse(
                {"errors": [{
                    "section": "ap.diagnoses",
                    "field": "assessment",
                    "message": f"Could not emit Assess for {code}: {exc.__class__.__name__}",
                }]},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    # ----- PlanCommand (per-diagnosis) -----
    raw_plan = entry.get("plan")
    plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    plan_narrative = str(plan.get("narrative") or "").strip()
    if plan_narrative:
        try:
            effects.append(PlanCommand(note_uuid=note_uuid, narrative=plan_narrative).originate())
            counts["plan"] = counts["plan"] + 1
        except (ValueError, TypeError) as exc:
            log.warning(
                f"[ExamChartingAPI] Plan originate failed for dx={code!r}: "
                f"{exc.__class__.__name__}: {exc}"
            )
            return effects, counts, JSONResponse(
                {"errors": [{
                    "section": "ap.diagnoses",
                    "field": "plan.narrative",
                    "message": f"Could not emit Plan for {code}: {exc.__class__.__name__}",
                }]},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    return effects, counts, None


_IMAGING_PRIORITY_MAP = {
    "routine": ImagingOrderCommand.Priority.ROUTINE,
    "urgent": ImagingOrderCommand.Priority.URGENT,
}
_REFER_PRIORITY_MAP = {
    "routine": ReferCommand.Priority.ROUTINE,
    "urgent": ReferCommand.Priority.URGENT,
}
_REFER_CLINICAL_QUESTION_MAP = {
    "COGNITIVE_ASSISTANCE": ReferCommand.ClinicalQuestion.COGNITIVE_ASSISTANCE,
    "ASSISTANCE_WITH_ONGOING_MANAGEMENT": ReferCommand.ClinicalQuestion.ASSISTANCE_WITH_ONGOING_MANAGEMENT,
    "SPECIALIZED_INTERVENTION": ReferCommand.ClinicalQuestion.SPECIALIZED_INTERVENTION,
    "DIAGNOSTIC_UNCERTAINTY": ReferCommand.ClinicalQuestion.DIAGNOSTIC_UNCERTAINTY,
}
_RX_SUBSTITUTIONS_MAP = {
    "ALLOWED": PrescribeCommand.Substitutions.ALLOWED,
    "NOT_ALLOWED": PrescribeCommand.Substitutions.NOT_ALLOWED,
}
_GOAL_PRIORITY_MAP = {
    "LOW": GoalCommand.Priority.LOW,
    "MEDIUM": GoalCommand.Priority.MEDIUM,
    "HIGH": GoalCommand.Priority.HIGH,
}


def _parse_iso_date(value: Any) -> date | None:
    """Return a `date` for an ISO-format string (YYYY-MM-DD) or None.

    The frontend's <input type="date"> always emits ISO; anything else
    (empty string, junk) should be ignored rather than raising — the
    backend treats the date as optional.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if v not in (None, "")]


def _missing_required(
    entry: dict[str, Any], scalar_fields: list[str], list_fields: list[str]
) -> str | None:
    """Return the first missing required field name, or None when all set.

    `scalar_fields` are checked truthy-after-strip; `list_fields` need at
    least one non-empty entry. Caller wraps the field name in a 400
    JSONResponse with the right section. This consolidates the per-card
    required-field gates so the emitters stay readable.
    """
    for f in scalar_fields:
        if not str(entry.get(f) or "").strip():
            return f
    for f in list_fields:
        values = entry.get(f) or []
        if not isinstance(values, list) or not any(
            str(v).strip() for v in values if v not in (None, "")
        ):
            return f
    return None


def _required_error(section: str, field: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"errors": [{"section": section, "field": field, "message": message}]},
        status_code=HTTPStatus.BAD_REQUEST,
    )


_LAB_REQUIRED_MESSAGES = {
    "lab_partner": "Lab order is missing its lab partner.",
    "ordering_provider_key": "Lab order is missing its ordering provider.",
    "tests": "Lab order needs at least one test.",
    "diagnosis_codes": "Lab order needs at least one diagnosis code.",
}


def _emit_lab_order(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    missing = _missing_required(
        entry,
        scalar_fields=["lab_partner", "ordering_provider_key"],
        list_fields=["diagnosis_codes"],
    )
    if missing is None:
        # tests is a list of dicts — check existence + at least one with
        # a non-empty order_code (the SDK needs order codes, not arbitrary
        # objects).
        tests = entry.get("tests") or []
        if not (isinstance(tests, list) and any(
            isinstance(t, dict) and (t.get("order_code") or "").strip() for t in tests
        )):
            missing = "tests"
    if missing is not None:
        return None, _required_error(
            "ap.orders.lab", missing, _LAB_REQUIRED_MESSAGES[missing]
        )
    try:
        kwargs: dict[str, Any] = {
            "note_uuid": note_uuid,
            "lab_partner": str(entry["lab_partner"]),
            "ordering_provider_key": str(entry["ordering_provider_key"]),
        }
        kwargs["tests_order_codes"] = [
            str(t.get("order_code")) for t in entry.get("tests") or []
            if isinstance(t, dict) and t.get("order_code")
        ]
        kwargs["diagnosis_codes"] = _str_list(entry.get("diagnosis_codes"))
        if entry.get("fasting_required") is True:
            kwargs["fasting_required"] = True
        if entry.get("comment"):
            kwargs["comment"] = str(entry["comment"])
        return LabOrderCommand(**kwargs).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] LabOrder originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.lab", "field": "",
                "message": f"Could not emit LabOrder: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


_IMAGING_REQUIRED_MESSAGES = {
    "ordering_provider_key": "Imaging order is missing its ordering provider.",
    "diagnosis_codes": "Imaging order needs at least one diagnosis code.",
}


def _emit_imaging_order(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    # image_code is intentionally NOT gated and NOT forwarded to the
    # chart. The chart's staged Imaging command requires its own CPT-
    # typeahead pick to populate the "Image:" row; plugin-emitted
    # image_code strings either:
    #   - fuzzy-match to an unrelated study (when short/vague)
    #   - render empty (when a full catalog-format description is sent)
    # Either way the chart's UI ignores or mismatches our value. Better
    # to send no value at all: the staged command shows an empty
    # "Image:" row, which signals to the provider that THEY must pick.
    # The plugin form's image_code is preserved in state for draft
    # purposes only (visible in the form on reopen).
    missing = _missing_required(
        entry,
        scalar_fields=["ordering_provider_key"],
        list_fields=["diagnosis_codes"],
    )
    if missing is not None:
        return None, _required_error(
            "ap.orders.imaging", missing, _IMAGING_REQUIRED_MESSAGES[missing]
        )
    try:
        provider_key = str(entry["ordering_provider_key"])
        kwargs: dict[str, Any] = {
            "note_uuid": note_uuid,
            "ordering_provider_key": provider_key,
        }
        # NOTE on the "Ordering provider" UI binding:
        # ImagingOrderCommand has BOTH `ordering_provider_key: str` AND
        # `service_provider: ServiceProvider` (TypedDict). Only the
        # latter carries the chart form's `commands_api_name` for
        # "ordering_provider", so the chart-side UI binds to that.
        # Passing a ServiceProvider with empty specialty/practice_name
        # (which is all we can build from a Staff row — Staff has no
        # specialty/practice_name attrs) causes the runtime to silently
        # reject the entire effect, so the command never appears in the
        # note. Keeping only `ordering_provider_key` for now: the chart
        # renders the Imaging command but with an empty "Ordering
        # provider" row. See git history for the failed attempt.
        prio = str(entry.get("priority") or "").strip().lower()
        if prio in _IMAGING_PRIORITY_MAP:
            kwargs["priority"] = _IMAGING_PRIORITY_MAP[prio]
        kwargs["diagnosis_codes"] = _str_list(entry.get("diagnosis_codes"))
        if entry.get("additional_details"):
            kwargs["additional_details"] = str(entry["additional_details"])
        if entry.get("comment"):
            kwargs["comment"] = str(entry["comment"])
        return ImagingOrderCommand(**kwargs).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] ImagingOrder originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.imaging", "field": "",
                "message": f"Could not emit ImagingOrder: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


_PRESCRIBE_REQUIRED_MESSAGES = {
    "fdb_code": "Prescription is missing its medication (no FDB code picked).",
    "sig": "Prescription is missing its sig.",
    "prescriber_id": "Prescription is missing its prescriber.",
    "icd10_codes": "Prescription needs at least one ICD-10 code.",
    "quantity_to_dispense": "Prescription is missing quantity to dispense.",
    "days_supply": "Prescription is missing days supply.",
    "refills": "Prescription is missing refills (0 is a valid value).",
}


def _is_blank_number(value: Any) -> bool:
    """A numeric Rx field is missing iff the payload sends None, an empty
    string, or only-whitespace. 0 is a valid value (esp. for refills)."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _emit_prescribe(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    missing = _missing_required(
        entry,
        scalar_fields=["fdb_code", "sig", "prescriber_id"],
        list_fields=["icd10_codes"],
    )
    if missing is None:
        # Numeric fields use a different blank-check because 0 is valid.
        for f in ("quantity_to_dispense", "days_supply", "refills"):
            if _is_blank_number(entry.get(f)):
                missing = f
                break
    if missing is not None:
        return None, _required_error(
            "ap.orders.prescribe", missing, _PRESCRIBE_REQUIRED_MESSAGES[missing]
        )
    try:
        kwargs: dict[str, Any] = {
            "note_uuid": note_uuid,
            "fdb_code": str(entry["fdb_code"]),
            "sig": str(entry["sig"]),
            "prescriber_id": str(entry["prescriber_id"]),
        }
        kwargs["quantity_to_dispense"] = entry["quantity_to_dispense"]
        kwargs["days_supply"] = int(entry["days_supply"])
        kwargs["refills"] = int(entry["refills"])
        sub = str(entry.get("substitutions") or "").strip().upper()
        if sub in _RX_SUBSTITUTIONS_MAP:
            kwargs["substitutions"] = _RX_SUBSTITUTIONS_MAP[sub]
        kwargs["icd10_codes"] = _str_list(entry.get("icd10_codes"))
        if entry.get("pharmacy"):
            kwargs["pharmacy"] = str(entry["pharmacy"])
        if entry.get("note_to_pharmacist"):
            kwargs["note_to_pharmacist"] = str(entry["note_to_pharmacist"])
        # Pair the FDB code with its dispense form (NDC + NCPDP qualifier)
        # so the chart's Rx UI doesn't sit on "Loading…" waiting for the
        # quantity dropdown. Both fields must be present together — passing
        # one without the other would build a half-constructed quantity.
        ndc = str(entry.get("representative_ndc") or "").strip()
        qual = str(entry.get("ncpdp_quantity_qualifier_code") or "").strip()
        if ndc and qual:
            kwargs["type_to_dispense"] = ClinicalQuantity(
                representative_ndc=ndc,
                ncpdp_quantity_qualifier_code=qual,
            )
        return PrescribeCommand(**kwargs).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] Prescribe originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.prescribe", "field": "",
                "message": f"Could not emit Prescribe: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


_REFER_REQUIRED_MESSAGES = {
    "service_provider": "Referral is missing the specialist (none picked).",
    "notes_to_specialist": "Referral is missing notes to specialist.",
    "diagnosis_codes": "Referral needs at least one diagnosis code.",
}


def _emit_refer(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    sp = entry.get("service_provider")
    sp_picked = (
        isinstance(sp, dict)
        and ((sp.get("first_name") or "").strip()
             or (sp.get("last_name") or "").strip())
    )
    if not sp_picked:
        return None, _required_error(
            "ap.orders.refer", "service_provider",
            _REFER_REQUIRED_MESSAGES["service_provider"],
        )
    missing = _missing_required(
        entry,
        scalar_fields=["notes_to_specialist"],
        list_fields=["diagnosis_codes"],
    )
    if missing is not None:
        return None, _required_error(
            "ap.orders.refer", missing, _REFER_REQUIRED_MESSAGES[missing]
        )
    try:
        kwargs: dict[str, Any] = {
            "note_uuid": note_uuid,
            "notes_to_specialist": str(entry["notes_to_specialist"]).strip(),
            "service_provider": {
                k: str(sp.get(k) or "")  # type: ignore[union-attr]
                for k in (
                    "first_name", "last_name", "specialty", "practice_name",
                    "business_fax", "business_phone", "business_address", "notes",
                )
            },
        }
        cq = str(entry.get("clinical_question") or "").strip()
        if cq in _REFER_CLINICAL_QUESTION_MAP:
            kwargs["clinical_question"] = _REFER_CLINICAL_QUESTION_MAP[cq]
        prio = str(entry.get("priority") or "").strip().lower()
        if prio in _REFER_PRIORITY_MAP:
            kwargs["priority"] = _REFER_PRIORITY_MAP[prio]
        kwargs["diagnosis_codes"] = _str_list(entry.get("diagnosis_codes"))
        if "include_visit_note" in entry:
            kwargs["include_visit_note"] = bool(entry["include_visit_note"])
        if entry.get("comment"):
            kwargs["comment"] = str(entry["comment"])
        return ReferCommand(**kwargs).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] Refer originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.refer", "field": "",
                "message": f"Could not emit Refer: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _emit_goal(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    statement = str(entry.get("goal_statement") or "").strip()
    if not statement:
        return None, _required_error(
            "ap.orders.goal", "goal_statement",
            "Goal is missing its goal statement.",
        )
    try:
        kwargs: dict[str, Any] = {
            "note_uuid": note_uuid,
            "goal_statement": statement,
        }
        due = _parse_iso_date(entry.get("due_date"))
        if due is not None:
            kwargs["due_date"] = due
        priority_raw = str(entry.get("priority") or "").strip().upper()
        if priority_raw in _GOAL_PRIORITY_MAP:
            kwargs["priority"] = _GOAL_PRIORITY_MAP[priority_raw]
        progress = str(entry.get("progress") or "").strip()
        if progress:
            kwargs["progress"] = progress
        return GoalCommand(**kwargs).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] Goal originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.goal", "field": "",
                "message": f"Could not emit Goal: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _emit_plan_item(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    """Visit-level Plan (not tied to a specific diagnosis).

    Distinct from the per-diagnosis Plan emitted by `_emit_diagnosis_block` —
    this is for plans the provider wants to record alongside other orders
    (lifestyle, monitoring, etc.) without attaching to a Dx code.
    """
    try:
        narrative = str(entry.get("narrative") or "").strip()
        if not narrative:
            # Empty plan card — silently skip (frontend allows blank cards
            # while the provider is filling things out).
            return None, None
        return PlanCommand(note_uuid=note_uuid, narrative=narrative).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] PlanItem originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.plan_item", "field": "",
                "message": f"Could not emit Plan: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _emit_follow_up(
    note_uuid: str, entry: dict[str, Any]
) -> tuple[Effect | None, JSONResponse | None]:
    try:
        kwargs: dict[str, Any] = {"note_uuid": note_uuid}
        req = _parse_iso_date(entry.get("requested_date"))
        if req is not None:
            kwargs["requested_date"] = req
        rfv = str(entry.get("reason_for_visit") or "").strip()
        if rfv:
            # structured=False (default) → reason_for_visit is free text;
            # avoids the ReasonForVisitSettingCoding validation gate the
            # RFV command runs into.
            kwargs["reason_for_visit"] = rfv
        comment = str(entry.get("comment") or "").strip()
        if comment:
            kwargs["comment"] = comment
        return FollowUpCommand(**kwargs).originate(), None
    except (ValueError, TypeError) as exc:
        log.warning(
            f"[ExamChartingAPI] FollowUp originate failed: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, JSONResponse(
            {"errors": [{
                "section": "ap.orders.follow_up", "field": "",
                "message": f"Could not emit FollowUp: {exc.__class__.__name__}",
            }]},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


_ORDER_EMITTERS: dict[str, Any] = {
    "lab": _emit_lab_order,
    "imaging": _emit_imaging_order,
    "prescribe": _emit_prescribe,
    "refer": _emit_refer,
    "goal": _emit_goal,
    "plan_item": _emit_plan_item,
    "follow_up": _emit_follow_up,
}
