"""Chart action buttons for CMS ACCESS operations.

Modals are launched with inline ``content=`` (matching the proven sticky_note
pattern) rather than a separate URL — embedding HTML avoids the iframe-cookie
issue that produced a blank modal when loaded via URL.
"""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from cms_access_fhir_client.modal_html import ALIGN_HTML, ELIGIBILITY_HTML, UNALIGN_HTML


class EligibilityActionButton(ActionButton):
    """Check ACCESS eligibility for the current patient."""

    BUTTON_TITLE = "Check ACCESS Eligibility"
    BUTTON_KEY = "CHECK_ACCESS_ELIGIBILITY"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    PRIORITY = 10

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        if not patient_id:
            return []
        return [
            LaunchModalEffect(
                content=ELIGIBILITY_HTML.format(patient_id=patient_id),
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Check ACCESS Eligibility",
            ).apply()
        ]


class AlignActionButton(ActionButton):
    """Enroll the current patient in CMS ACCESS."""

    BUTTON_TITLE = "Enroll in ACCESS"
    BUTTON_KEY = "ENROLL_IN_ACCESS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    PRIORITY = 20

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        if not patient_id:
            return []
        return [
            LaunchModalEffect(
                content=ALIGN_HTML.format(patient_id=patient_id),
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Enroll in ACCESS",
            ).apply()
        ]


class UnalignActionButton(ActionButton):
    """Unalign the current patient from CMS ACCESS."""

    BUTTON_TITLE = "Unalign from ACCESS"
    BUTTON_KEY = "UNALIGN_FROM_ACCESS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    PRIORITY = 30

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        if not patient_id:
            return []
        return [
            LaunchModalEffect(
                content=UNALIGN_HTML.format(patient_id=patient_id),
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Unalign from ACCESS",
            ).apply()
        ]
