"""Patient portal menu item: lets a patient connect or stop sharing on their own."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from oura_ring_viewer.services.settings import PLUGIN_API_PATH


class OuraPortalApp(Application):
    """Opens the patient's own Oura page from the portal menu."""

    def on_open(self) -> Effect:
        """Launch the portal page. The patient is identified by their session, not the URL."""
        return LaunchModalEffect(
            url=f"{PLUGIN_API_PATH}/portal/",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Oura Ring",
        ).apply()
