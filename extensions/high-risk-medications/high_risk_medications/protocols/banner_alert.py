from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from high_risk_medications.helper import get_high_risk_meds

class HighRiskMedicationsBannerAlert(BaseProtocol):

    RESPONDS_TO = [
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_COMMIT),
        EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_ENTER_IN_ERROR),
        EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_COMMIT),
        EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_ENTER_IN_ERROR),
    ]

    # Patterns to search for in medication names (case-insensitive substring matching)
    BANNER_KEY = "high-risk-medication"

    def compute(self) -> list[Effect]:
       
        patient_id = self.context.get("patient", {}).get("id")
        high_risk_meds = get_high_risk_meds(patient_id, self.secrets["HIGH_RISK_PATTERNS"])

        if high_risk_meds:
            med_names = [med['name'] for med in high_risk_meds]
            narrative = f"High Risk Meds: {', '.join(med_names)}"
            if len(narrative) > 90:
                count = len(high_risk_meds)
                narrative = f"{count} High Risk Meds"
            return [
                AddBannerAlert(
                    patient_id=patient_id,
                    key=self.BANNER_KEY,
                    narrative=narrative,
                    placement=[AddBannerAlert.Placement.CHART],
                    intent=AddBannerAlert.Intent.ALERT,
                ).apply()
            ]
        else:
            return [
                RemoveBannerAlert(
                    patient_id=patient_id,
                    key=self.BANNER_KEY,
                ).apply()
            ]