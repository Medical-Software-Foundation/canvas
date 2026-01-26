from canvas_sdk.effects.patient_chart_group import PatientChartGroup
from canvas_sdk.effects import Effect
from canvas_sdk.effects.group import Group
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

# Default patterns for handlers without access to secrets
HIGH_RISK_PATTERNS = ["warfarin", "insulin", "digoxin", "methotrexate"]

class Protocol(BaseHandler):
    """
    Groups high-risk medications in the patient summary chart.
    """
    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)

    def compute(self) -> list[Effect]:
        groups: dict[str, Group] = {}
        groups.setdefault("High Risk Medications", Group(priority=1000, items=[], name="⚠️ High Risk Medications"))

        patterns = HIGH_RISK_PATTERNS
        for medication_context_object in self.event.context:
            # Context looks like this:
            # {
            #   'id': 298,
            #   'codings': [
            #     {'code': '449740', 'system': 'http://www.fdbhealth.com/', 'display': 'Monoject Insulin Syringe 1 mL'}
            #   ]
            # }
            coding = medication_context_object["codings"][0]
            if any(pattern in coding["display"].lower() for pattern in patterns):
                groups["High Risk Medications"].items.append(medication_context_object)

        return [PatientChartGroup(items=groups).apply()]
