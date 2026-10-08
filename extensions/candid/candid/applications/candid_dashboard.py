"""Candid dashboard application.

Full-page application launched from the Canvas provider menu. Lists all claims
that have been submitted to Candid along with their current status, last sync,
and any submission errors.

The UI (HTML/CSS/JS) lives in ``static/dashboard.*`` and is served by
``candid.api.app.CandidAppAssets``; this handler just iframes that page.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import MenuPosition, ProviderMenuApplication

from candid.access import staff_can_access_dashboard


class CandidDashboard(ProviderMenuApplication):
    """Full-page list view of all Candid-submitted claims with status."""

    NAME = "Candid Dashboard"
    MENU_POSITION = MenuPosition.TOP

    def _can_access(self) -> bool:
        """Return whether the current user is authorized to access the Candid Dashboard."""
        user = self.event.context.get("user") or {}
        staff_key = user.get("id") if user.get("type") == "Staff" else None
        return staff_can_access_dashboard(staff_key, self.secrets)

    def visible(self) -> bool:
        """Return whether the Candid Dashboard is visible to the current user."""
        return self._can_access()

    def on_open(self) -> Effect | list[Effect]:
        """Open the Candid Dashboard if the current user is authorized, otherwise show an error page.

        The menu entry is hidden from unauthorized users, but the application can still be
        opened directly, so access is checked here as well.
        """
        if not self._can_access():
            return LaunchModalEffect(
                content="You are not authorized to access the Candid Dashboard.",
                target=LaunchModalEffect.TargetType.PAGE,
                title="Candid Dashboard",
            ).apply()
        return LaunchModalEffect(
            url="/plugin-io/api/candid/app/dashboard",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Candid Dashboard",
        ).apply()
