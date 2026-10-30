"""Consent Settings — the app drawer entry for consent admins.

Opens the Consent Settings page without a patient chart open. Only staff on the
``CONSENT_ADMIN_USERS`` allow-list (and the instance root user) see it; the page and
every admin endpoint check access themselves too. The gear in the Consents window
stays as a second way in.

Per-user app drawer entries need SDK 0.243.0 (Canvas release 1.364.0 or later).
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import PanelApplication

from consent_capture.picker_modal import SETTINGS_URL
from consent_capture.service import is_consent_admin


class ConsentSettingsApp(PanelApplication):
    """App drawer icon that opens Consent Settings for consent admins."""

    NAME = "Consent Settings"
    IDENTIFIER = "consent_capture__settings"
    ICON_URL = "/plugin-io/api/consent_capture/admin/icon.svg"

    def _staff_id(self):
        context = getattr(self.event, "context", None) or {}
        user = context.get("user") or context.get("staff") or {}
        return user.get("id") if user.get("type", "Staff") == "Staff" else None

    def visible(self) -> bool:
        secrets = getattr(self, "secrets", None) or {}
        return is_consent_admin(self._staff_id(), secrets.get("CONSENT_ADMIN_USERS", ""))

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=SETTINGS_URL,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Consent Settings",
        ).apply()
