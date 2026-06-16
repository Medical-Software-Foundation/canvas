"""Recent Labs chart-drawer application."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from logger import log

from recent_labs.labs import get_recent_results_by_test


class RecentLabsApp(Application):
    """Patient-scoped app showing each test's most recent results."""

    def on_open(self) -> Effect | list:
        """Render the recent-labs pane for the current patient."""
        patient_id = self.event.context.get("patient", {}).get("id")
        if not patient_id:
            log.warning("RecentLabsApp.on_open: missing patient id in context")
            return []

        lab_groups = get_recent_results_by_test(patient_id)
        log.info(f"RecentLabsApp: {len(lab_groups)} lab tests for patient {patient_id}")

        content = render_to_string(
            "templates/recent_labs.html",
            {
                "patient_id": patient_id,
                "lab_groups": lab_groups,
                "has_values": bool(lab_groups),
            },
        )

        return LaunchModalEffect(
            content=content,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Recent Labs",
        ).apply()
