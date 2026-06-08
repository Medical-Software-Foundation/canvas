"""Patient-scoped application for using lab order favorites in a chart.

Opens from the app drawer inside a patient chart and renders in the right chart
pane. Lets the provider search favorites, select one or more, pick a target open
note, and insert each as a staged LabOrder command.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from logger import log


class LabFavoritesApp(Application):
    """Patient-scoped application for inserting lab order favorites."""

    def on_open(self) -> Effect:
        patient = Patient.objects.get(id=self.event.context["patient"]["id"])
        log.info(f"Opening Lab Favorites for patient {patient.id}")

        html = render_to_string(
            "templates/favorites.html",
            {
                "api_base": "/plugin-io/api/lab_order_favorites",
                "patient_id": patient.id,
            },
        )
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Lab Favorites",
        ).apply()
