from canvas_sdk.effects.patient_chart_group import PatientChartGroup
from canvas_sdk.effects import Effect
from canvas_sdk.effects.group import Group
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from high_risk_medications.helper import get_high_risk_meds


class Protocol(BaseHandler):
    """
    Groups high-risk medications in the patient summary chart.
    """
    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)

    def compute(self) -> list[Effect]:
        groups: dict[str, Group] = {}
        groups.setdefault("High Risk Medications", Group(priority=1000, items=[], name="⚠️ High Risk Medications"))

        patient_id = self.event.target.id
        high_risk_meds = get_high_risk_meds(patient_id, self.secrets["HIGH_RISK_PATTERNS"])
        high_risk_names = {med["name"].lower() for med in high_risk_meds}

        for medication_context_object in self.event.context:
            coding = medication_context_object["codings"][0]
            if coding["display"].lower() in high_risk_names:
                groups["High Risk Medications"].items.append(medication_context_object)

        return [PatientChartGroup(items=groups).apply()]
