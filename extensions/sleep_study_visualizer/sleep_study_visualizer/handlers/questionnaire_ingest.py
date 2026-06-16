"""SleepStudyQuestionnaireHandler — persist a SleepStudyResult when a Sleep Study
Result questionnaire is committed.

Subscribed to QUESTIONNAIRE_COMMAND__POST_COMMIT because INTERVIEW_CREATED fires
when the empty Interview row is inserted (before any responses exist). POST_COMMIT
fires after the note's questionnaire command commits — all data is in the event
payload, no race-prone DB lookups needed.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Note
from django.db import IntegrityError
from logger import log

from sleep_study_visualizer.constants import (
    Q_AHI,
    Q_EPWORTH,
    Q_ODI,
    Q_RDI,
    Q_SEVERITY,
    Q_STUDY_DATE,
    SEVERITY_OPTION_TO_LABEL,
    SLEEP_STUDY_QUESTIONNAIRE_CODE,
    SLEEP_STUDY_QUESTIONNAIRE_CODE_SYSTEM,
)
from sleep_study_visualizer.models.sleep_study_result import (
    CustomPatient,
    SleepStudyResult,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",  # US-style with hyphens
    "%m-%d-%y",
    "%d-%m-%Y",
)


def _to_decimal(raw: str) -> Optional[Decimal]:
    if not raw:
        return None
    try:
        return Decimal(raw.strip())
    except (ArithmeticError, ValueError):
        return None


def _to_int(raw: str) -> Optional[int]:
    if not raw:
        return None
    try:
        return int(Decimal(raw.strip()))
    except (ArithmeticError, ValueError):
        return None


def _to_date(raw: str) -> Optional[date_type]:
    if not raw:
        return None
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class SleepStudyQuestionnaireHandler(BaseHandler):
    """On QUESTIONNAIRE_COMMAND__POST_COMMIT: if the committed questionnaire is the
    Sleep Study Result form, persist a SleepStudyResult row from the event payload.
    """

    RESPONDS_TO = EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        fields = self.event.context.get("fields") or {}
        questionnaire = fields.get("questionnaire") or {}
        extra = questionnaire.get("extra") or {}
        questions: list[dict[str, Any]] = extra.get("questions") or []

        # Check if any question coding matches our Sleep Study Result questionnaire.
        # Canvas doesn't put the questionnaire's own code on the event — only each
        # question's code. We confirm by looking for any question with our codes.
        question_codes = {
            q.get("coding", {}).get("code"): q for q in questions
        }
        our_codes = {Q_STUDY_DATE, Q_AHI, Q_RDI, Q_ODI, Q_SEVERITY, Q_EPWORTH}
        if not (our_codes & set(question_codes.keys())):
            return []

        # Build {question_code: response_value} where response_value is the raw
        # value (string for TXT, option pk for SING). For SING, also resolve to
        # the option code via the question's options list.
        answers: dict[str, Any] = {}
        for q in questions:
            code = q.get("coding", {}).get("code")
            if code not in our_codes:
                continue
            answer_key = q.get("name") or f"question-{q.get('pk')}"
            raw_answer = fields.get(answer_key)
            if q.get("type") == "SING":
                option_code = _resolve_sing_option_code(q.get("options") or [], raw_answer)
                answers[code] = option_code or ""
            else:
                answers[code] = (raw_answer or "")

        study_date = _to_date(str(answers.get(Q_STUDY_DATE, "")))
        if study_date is None:
            log.warning(
                "[SleepStudyQuestionnaireHandler] No parseable study date "
                "(got %r) — skipping persist.",
                answers.get(Q_STUDY_DATE),
            )
            return []

        patient_dbid = self._resolve_patient_dbid()
        if patient_dbid is None:
            log.warning(
                "[SleepStudyQuestionnaireHandler] Could not resolve patient from "
                "event context. Context keys: %s. Fields keys: %s.",
                list(self.event.context.keys()),
                list(fields.keys()),
            )
            return []

        custom_patient = CustomPatient.objects.filter(dbid=patient_dbid).first()
        if custom_patient is None:
            log.warning(
                "[SleepStudyQuestionnaireHandler] No CustomPatient for patient dbid %s.",
                patient_dbid,
            )
            return []

        # Idempotency: if a SleepStudyResult already exists for this patient+date,
        # treat as duplicate and skip. This is the fast path; the
        # unique_sleep_study_per_patient_date DB constraint is the real guard and
        # closes the check-then-create race for concurrent commits (handled below).
        existing = SleepStudyResult.objects.filter(
            patient=custom_patient,
            study_date=study_date,
        ).first()
        if existing is not None:
            log.info(
                "[SleepStudyQuestionnaireHandler] SleepStudyResult already exists "
                "for patient dbid %s on %s - skipping duplicate.",
                patient_dbid,
                study_date,
            )
            return []

        severity_label = SEVERITY_OPTION_TO_LABEL.get(answers.get(Q_SEVERITY, ""), "")

        try:
            SleepStudyResult.objects.create(
                patient=custom_patient,
                study_date=study_date,
                ahi=_to_decimal(str(answers.get(Q_AHI, ""))),
                rdi=_to_decimal(str(answers.get(Q_RDI, ""))),
                odi=_to_decimal(str(answers.get(Q_ODI, ""))),
                severity=severity_label,
                epworth_score=_to_int(str(answers.get(Q_EPWORTH, ""))),
            )
        except IntegrityError:
            # A concurrent commit inserted the row between the check above and
            # this create. The unique constraint did its job — treat as duplicate.
            log.info(
                "[SleepStudyQuestionnaireHandler] Concurrent SleepStudyResult insert "
                "for patient dbid %s on %s - skipping duplicate.",
                patient_dbid,
                study_date,
            )
            return []

        log.info(
            "[SleepStudyQuestionnaireHandler] Persisted SleepStudyResult for "
            "patient dbid %s on %s.",
            patient_dbid,
            study_date,
        )

        return []

    def _resolve_patient_dbid(self) -> Optional[int]:
        """Resolve the patient's dbid via several event-context paths.

        Canvas events carry the patient/note in different shapes depending on
        version and event source. Try the most common locations.
        """
        # Path 1: event.context.patient.id - used by other Canvas event types.
        ctx_patient = self.event.context.get("patient") or {}
        patient_externally_exposable_id = ctx_patient.get("id") if isinstance(ctx_patient, dict) else None
        if patient_externally_exposable_id:
            patient = CustomPatient.objects.filter(id=patient_externally_exposable_id).first()
            if patient is not None:
                return int(patient.dbid)

        # Path 2: context.note.uuid -> Note -> patient. The note lives at
        # context["note"], not inside context["fields"] (see diagnose_order).
        note_info = self.event.context.get("note") or {}
        note_uuid = note_info.get("uuid") if isinstance(note_info, dict) else None
        if note_uuid:
            note = Note.objects.filter(id=note_uuid).first()
            if note is not None and note.patient_id is not None:
                return int(note.patient_id)

        # Path 3: walk back from the command (event.target.id) -> Note -> patient.
        command_uuid = self.event.target.id
        if command_uuid:
            note = Note.objects.filter(commands__id=command_uuid).first()
            if note is not None and note.patient_id is not None:
                return int(note.patient_id)

        return None


def _resolve_sing_option_code(options: list[dict[str, Any]], selected_pk: Any) -> Optional[str]:
    """Look up a SING answer's option code given its pk."""
    if selected_pk is None or selected_pk == "":
        return None
    try:
        target_pk = int(selected_pk)
    except (TypeError, ValueError):
        return None
    for opt in options:
        if opt.get("pk") == target_pk:
            return opt.get("code")
    return None
