"""
High Risk Medications Viewer Application

This application displays a patient's active high-risk medications in the app drawer.
Shows medications that match high-risk patterns (warfarin, insulin, digoxin, methotrexate).
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.medication import Medication
from logger import log


class HighRiskMedsViewer(Application):
    """
    Application that displays high-risk medications for the current patient.
    """

    def on_open(self) -> Effect | list[Effect]:
        """
        Called when the application is opened from the app drawer.
        Displays a list of the patient's active high-risk medications.
        """
        # Get patient ID from event context
        patient_id = self.event.context.get("patient", {}).get("id")

        if not patient_id:
            log.warning("No patient context available")
            return []

        log.info(f"Loading high-risk medications for patient {patient_id}")

        # Load the view via SimpleAPI URL
        return LaunchModalEffect(
            url=f"/plugin-io/api/high_risk_medications/high-risk-meds/{patient_id}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="High Risk Medications"
        ).apply()


class HighRiskMedsActionButton(ActionButton):
    """
    Action button that appears in the medications section when high-risk meds are present.
    """

    BUTTON_TITLE = "High Risk Medications"
    BUTTON_KEY = "high-risk-meds"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_MEDICATIONS_SECTION
    HIGH_RISK_PATTERNS = ["warfarin", "insulin", "digoxin", "methotrexate"]

    def visible(self) -> bool:
        """Only show button if patient has high-risk medications."""
        medications = Medication.objects.filter(
            patient__id=self.target,
            status="active"
        )

        for med in medications:
            coding = med.codings.first()
            med_name = coding.display or ""
            if any(pattern in med_name.lower() for pattern in self.HIGH_RISK_PATTERNS):
                return True
        return False

    def handle(self) -> list[Effect]:
        """Launch the high-risk medications view."""
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/high_risk_medications/high-risk-meds/{self.target}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="High Risk Medications"
            ).apply()
        ]