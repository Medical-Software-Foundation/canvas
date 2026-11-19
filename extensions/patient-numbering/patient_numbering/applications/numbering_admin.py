from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Recomputed on every plugin load, so a redeploy changes the iframe src and the browser
# fetches the fresh admin page instead of a cached copy.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PatientNumberingAdmin(Application):
    """Admin app to number existing patients and check progress."""

    def on_open(self) -> Effect:
        """Open the admin page as a full Canvas page."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/patient_numbering/admin?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Patient Numbering",
        ).apply()
