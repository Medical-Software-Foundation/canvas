from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class VaccineCardApplication(Application):
    """Patient portal application that displays the patient's immunization record."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching the vaccine card page."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/portal_vaccine_card/app/card?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
