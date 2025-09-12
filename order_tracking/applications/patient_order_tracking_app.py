from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from logger import log


class PatientOrderTrackingApplication(Application):
    """An embeddable application that can be registered to Canvas."""

    def on_open(self) -> Effect:
        patient_id = self.context["patient"]["id"]
        context = {
            "patientId": patient_id,
            "patientChartApplication": "order_tracking.applications.patient_order_tracking_app:PatientOrderTrackingApplication"
        }
        return LaunchModalEffect(
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Order Tracking Application",
            content=render_to_string("templates/patient_worklist_orders.html", context=context),
        ).apply()