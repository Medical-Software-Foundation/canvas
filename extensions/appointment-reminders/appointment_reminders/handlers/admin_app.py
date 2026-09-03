"""Global admin application for appointment reminder configuration.

The provider-menu item itself cannot be hidden per user: ``visible()`` is
defined only on ``EmbeddedApplication`` (note and scheduling scopes), and the
``ProviderMenuConfiguration`` effect states that it "does not affect
plugin-provided menu items". So the entry stays in everyone's menu and the gate
lives here, at open, backed by the role check on the ``/admin`` routes
themselves in ``NotificationAPI.authenticate`` — that API check is the real
boundary, since these URLs are reachable without ever clicking the menu.
"""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log

from appointment_reminders.services.authz import is_admin_staff

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

_BASE_URL = "/plugin-io/api/appointment_reminders"


class NotifyAdminApp(Application):
    """Global admin application for appointment reminder campaigns."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch the admin page, or a refusal for staff without an admin role."""
        user = self.event.context.get("user") or {}
        if user.get("type") != "Staff" or not is_admin_staff(
            user.get("id"), self.secrets
        ):
            log.info("[admin] Non-admin opened Appointment Reminders; showing refusal")
            return LaunchModalEffect(
                url=f"{_BASE_URL}/access-denied?v={_CACHE_BUST}",
                target=LaunchModalEffect.TargetType.PAGE,
                title="Appointment Reminders",
            ).apply()

        url = f"{_BASE_URL}/admin?v={_CACHE_BUST}"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Appointment Reminders",
        ).apply()
