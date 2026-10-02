"""Decides which programme questionnaires the portal offers this patient."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_portal.form_result import FormResult
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler

from medication_followup_protocol.models import (
    EnrolledStep,
    EnrollmentStatus,
    StepKind,
    StepStatus,
)


class PortalForms(BaseHandler):
    """Offer the questionnaire of any live questionnaire step."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PORTAL__GET_FORMS)

    def compute(self) -> list[Effect]:
        """Return one FormResult per live questionnaire step for this patient."""
        patient_id = (self.event.context or {}).get("patient", {}).get("id")
        if not patient_id:
            return []

        live = EnrolledStep.objects.filter(
            kind=StepKind.QUESTIONNAIRE,
            status=StepStatus.FIRED,
            interview_id__isnull=True,
            enrollment__status=EnrollmentStatus.ACTIVE,
            enrollment__patient__id=patient_id,
        ).select_related("program_step")

        return [
            FormResult(questionnaire_id=step.program_step.questionnaire_id).apply()
            for step in live
            if step.program_step.questionnaire_id
        ]
