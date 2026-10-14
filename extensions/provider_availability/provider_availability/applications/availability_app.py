"""Application handler for the Provider Availability admin UI."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ProviderAvailabilityApp(Application):
    """Admin UI for managing provider scheduling rules and availability.

    Accessible from the provider menu. Opens in a new browser tab so the
    admin UI doesn't replace whatever the user was on.
    """

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/provider_availability/api/availability-admin?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.NEW_WINDOW,
            title="Provider Availability",
        ).apply()
