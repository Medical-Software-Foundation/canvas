"""App-drawer entry point for the screening editor.

A global (non-patient) application that opens the editor as a full page. The page
itself is served by ``ScreeningAdminAPI``; this handler only launches it. Access
is enforced on the API side, not here - the SDK has no per-staff control over
which icons appear in the drawer.
"""

import time

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Generated once at module load, so it changes on every deploy - the editor page
# is never served from a stale browser cache after an update.
_CACHE_BUST = str(int(time.time()))


class ScreeningAdminApplication(Application):
    """Admin app: define which preventive screenings the practice tracks."""

    def on_open(self) -> Effect:
        """Open the screening editor."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/preventive_screenings/admin/ui?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
