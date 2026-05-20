from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ProfileApplication(Application):
    """Patient portal application that displays the patient's profile information."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching the profile page."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/patient_portal_profile/app/profile?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
