"""App-drawer entry that opens the dashboard as a full page."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ScoringDashboardApp(Application):
    """Patient-scoped application launching the scoring dashboard."""

    def on_open(self) -> Effect | list[Effect]:
        patient_id = self.event.context.get("patient", {}).get("id", "")
        return LaunchModalEffect(
            url=f"/plugin-io/api/questionnaire_scoring_dashboard/?patient={patient_id}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
