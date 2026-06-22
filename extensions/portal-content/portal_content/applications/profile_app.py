"""My Profile portal application: personal information and insurance on file."""

from __future__ import annotations

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ProfileApp(Application):
    """Launches the My Profile page in the patient portal."""

    def on_open(self) -> Effect:
        """Open the tabbed My Profile page (My Information, My Insurance)."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/portal_content/app/profile?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
