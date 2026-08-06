from __future__ import annotations

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

PLUGIN_NAME = "scheduling_modal_with_recurring_support"
API_PREFIX = "scheduling"


class SchedulingApp(Application):
    """Application button on the patient chart that opens the scheduling modal."""

    def on_open(self) -> Effect:
        patient_id = self.context.get("patient", {}).get("id", "")
        url = (
            f"/plugin-io/api/{PLUGIN_NAME}/{API_PREFIX}/ui"
            f"?patient_id={patient_id}&v={_CACHE_BUST}"
        )
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()


class GlobalSchedulingApp(Application):
    """Global application button that opens scheduling without patient context."""

    def on_open(self) -> Effect:
        url = (
            f"/plugin-io/api/{PLUGIN_NAME}/{API_PREFIX}/ui"
            f"?v={_CACHE_BUST}"
        )
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
