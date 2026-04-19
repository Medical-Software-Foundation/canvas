from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class TaskDashboardApp(Application):
    """Global companion app that opens a filterable task dashboard."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/provider_task_dashboard_companion/app/",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()


class PatientTaskDashboardApp(Application):
    """Patient-scoped companion app showing tasks for the viewed patient."""

    def on_open(self) -> Effect:
        patient = self.event.context.get("patient", {})
        patient_id = patient.get("id", "")
        return LaunchModalEffect(
            url=(
                "/plugin-io/api/provider_task_dashboard_companion/app/"
                f"?patient_id={patient_id}"
            ),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
