"""Admin application — opens the HTML console as a full page from the left nav."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class SalesforceAdminApp(Application):
    """Admin console for the Salesforce to Canvas patient sync plugin.

    The application is registered as a provider menu item (see
    ``CANVAS_MANIFEST.json``) so it sits in the left sidebar nav alongside the
    core staff tools rather than on patient charts. Admin and config work does
    not belong on a patient context. The console is a wide multi table
    dashboard, so it opens as a full page rather than a modal.
    """

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/salesforce_to_canvas_integration/admin",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
