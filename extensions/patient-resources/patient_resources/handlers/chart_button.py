"""The chart-header button that opens the resource picker."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from patient_resources.constants import picker_url


class ShareResourcesButton(ActionButton):
    """Opens the picker for the patient whose chart is open.

    A chart-header button rather than a patient-scoped Application: the
    button-to-modal path is the one verified working in this repo, and a
    patient-scoped chart application is the surface the order-sets plugin could
    never make behave. The picker page reads its patient only from the config
    block the route injects, so adding an Application entry point later that
    points at the same URL stays a small change.
    """

    # One word on purpose. The chart header gives each plugin button a narrow
    # fixed slot and clips what does not fit, so "Share resources" arrived
    # visibly cut off. The modal it opens is still titled in full, which is where
    # there is room to say what the button does.
    BUTTON_TITLE = "Resources"
    BUTTON_KEY = "patient_resources__share"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def visible(self) -> bool:
        """Always shown.

        No lookup: a chart header always has a real patient, so a per-render
        query would buy nothing and would mean this handler had to declare
        patient read access it does not otherwise need.
        """
        return True

    def handle(self) -> list[Effect]:
        """Open the picker, scoped to this chart's patient."""
        patient_id = str(getattr(self.event.target, "id", "") or "")
        if not patient_id:
            return []

        return [
            LaunchModalEffect(
                url=picker_url(patient_id),
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Share resources",
            ).apply()
        ]
