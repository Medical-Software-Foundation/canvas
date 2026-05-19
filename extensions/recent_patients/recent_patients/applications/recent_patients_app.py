from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from recent_patients import CACHE_BUST

_MODAL_URL = f"/plugin-io/api/recent_patients/app/?v={CACHE_BUST}"


class RecentPatientsApp(Application):
    """Global-scope launcher entry — opens the browse modal from anywhere."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=_MODAL_URL,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()


class RecentPatientsPatientApp(Application):
    """Patient-chart entry — same modal, surfaced from inside the patient chart."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=_MODAL_URL,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()
