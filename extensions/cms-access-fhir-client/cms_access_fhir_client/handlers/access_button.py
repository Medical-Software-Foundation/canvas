"""Chart-header button that opens the CMS ACCESS inspector.

Replaces the patient-chart app-launcher icon with a single ACCESS button in the
patient chart header. Clicking it renders the inspector as a self-contained inline
modal (HTML + CSS + JS embedded) — the same UI the AccessOperationsApi /app endpoints
back. Inline content= is used (not a URL) to avoid the blank-iframe issue.
"""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string


class AccessInspectorButton(ActionButton):
    """ACCESS chart-header button → opens the inspector modal for the current patient."""

    BUTTON_TITLE = "ACCESS"
    BUTTON_KEY = "ACCESS_INSPECTOR"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    BUTTON_BACKGROUND_COLOR = "#0D2499"
    BUTTON_TEXT_COLOR = "#FFFFFF"
    PRIORITY = 1

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        if not patient_id:
            return []
        html = render_to_string(
            "static/index.html",
            {
                "patient_id": patient_id,
                "styles": render_to_string("static/styles.css"),
                "script": render_to_string("static/main.js"),
            },
        )
        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="CMS ACCESS Inspector",
            ).apply()
        ]
