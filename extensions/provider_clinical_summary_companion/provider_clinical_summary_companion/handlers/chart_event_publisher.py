from typing import ClassVar

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Broadcast
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.immunization import Immunization, ImmunizationStatement
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.questionnaire import Interview


def patient_channel(patient_id: str) -> str:
    return f"patient-{patient_id}"


# Map each event type to (model class, [section keys to refresh]).
EVENT_MAP = {
    "CONDITION_CREATED": (Condition, ["conditions", "surgicalHistory"]),
    "CONDITION_UPDATED": (Condition, ["conditions", "surgicalHistory"]),
    "CONDITION_RESOLVED": (Condition, ["conditions", "surgicalHistory"]),
    "CONDITION_ASSESSED": (Condition, ["conditions", "surgicalHistory"]),
    "MEDICATION_LIST_ITEM_CREATED": (Medication, ["medications"]),
    "MEDICATION_LIST_ITEM_UPDATED": (Medication, ["medications"]),
    "ALLERGY_INTOLERANCE_CREATED": (AllergyIntolerance, ["allergies"]),
    "ALLERGY_INTOLERANCE_UPDATED": (AllergyIntolerance, ["allergies"]),
    "IMMUNIZATION_CREATED": (Immunization, ["immunizations"]),
    "IMMUNIZATION_UPDATED": (Immunization, ["immunizations"]),
    "IMMUNIZATION_STATEMENT_CREATED": (ImmunizationStatement, ["immunizations"]),
    "IMMUNIZATION_STATEMENT_UPDATED": (ImmunizationStatement, ["immunizations"]),
    "INTERVIEW_CREATED": (Interview, ["socialDeterminants"]),
    "INTERVIEW_UPDATED": (Interview, ["socialDeterminants"]),
    "VITAL_SIGN_CREATED": (Observation, ["vitals"]),
    "VITAL_SIGN_UPDATED": (Observation, ["vitals"]),
}


def _patient_id_from_target(model, target_id: str) -> str | None:
    if not target_id:
        return None
    record = model.objects.filter(id=target_id).select_related("patient").first()
    patient = getattr(record, "patient", None) if record else None
    return str(patient.id) if patient else None


class ChartEventPublisher(BaseHandler):
    """Broadcasts a section-refresh ping on the patient's channel for each chart change."""

    RESPONDS_TO: ClassVar[list[str]] = [
        EventType.Name(getattr(EventType, event_name)) for event_name in EVENT_MAP
    ]

    def compute(self) -> list[Effect]:
        event_name = EventType.Name(self.event.type)
        mapping = EVENT_MAP.get(event_name)
        if not mapping:
            return []
        model, sections = mapping

        target = getattr(self.event, "target", None)
        target_id = getattr(target, "id", None) if not isinstance(target, str) else target
        if not target_id:
            target_id = self.event.context.get("target") if hasattr(self.event, "context") else None
        patient_id = _patient_id_from_target(model, target_id or "")
        if not patient_id:
            return []

        channel = patient_channel(patient_id)
        return [
            Broadcast(channel=channel, message={"section": section}).apply()
            for section in sections
        ]
