"""Provider-menu entry point for the Manage Availability UI."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ProviderAvailabilityManagerApp(Application):
    """Provider-menu app that opens the drag-and-schedule availability UI."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=(
                "/plugin-io/api/provider_availability_manager/app/availability-app"
                f"?v={_CACHE_BUST}"
            ),
            target=LaunchModalEffect.TargetType.PAGE,
            title="Manage Availability",
        ).apply()
