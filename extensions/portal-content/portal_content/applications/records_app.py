"""My Records portal application: visit summaries, lab and imaging reports, letters."""

from __future__ import annotations

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class RecordsApp(Application):
    """Launches the My Records page in the patient portal."""

    def on_open(self) -> Effect:
        """Open the tabbed My Records page (Visits, Labs, Imaging, Letters)."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/portal_content/app/records?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
