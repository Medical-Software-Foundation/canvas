from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ProfileApplication(Application):
    """Patient portal application that displays the patient's profile information."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching the profile page."""
        return LaunchModalEffect(
            url="/plugin-io/api/patient_portal_profile/app/profile",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
