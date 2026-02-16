"""
Observation Visualizer Application

Patient-specific application for visualizing observations in table and graph views.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ObservationVisualizerApp(Application):
    """
    Patient-specific application accessed from the Applications menu.

    Opens a modal containing the observation visualizer UI with table
    and graph views of the patient's observations.
    """

    def on_open(self) -> list[Effect]:
        """
        Handle application open event.

        Launches a modal with the visualizer UI, passing the patient ID
        from the application context. Staff ID is obtained from headers in the SimpleAPI.
        """
        patient_id = self.event.context.get("patient", {}).get("id")
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/custom_observation_management/visualizer?patient_id={patient_id}"
            ).apply()
        ]
