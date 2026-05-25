"""Chart action buttons for CMS ACCESS operations."""
from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


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
        url = (
            f"/plugin-io/api/cms_access_fhir_client/eligibility"
            f"?patient_id={patient_id}&v={_CACHE_BUST}"
        )
        return [
            LaunchModalEffect(
                url=url,
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
        url = (
            f"/plugin-io/api/cms_access_fhir_client/align"
            f"?patient_id={patient_id}&v={_CACHE_BUST}"
        )
        return [
            LaunchModalEffect(
                url=url,
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
        url = (
            f"/plugin-io/api/cms_access_fhir_client/unalign"
            f"?patient_id={patient_id}&v={_CACHE_BUST}"
        )
        return [
            LaunchModalEffect(
                url=url,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Unalign from ACCESS",
            ).apply()
        ]
