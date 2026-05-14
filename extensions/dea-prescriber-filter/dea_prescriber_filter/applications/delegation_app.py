"""Application handler for the prescriber delegation admin UI."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PrescriberDelegationApp(Application):
    """Admin UI for managing prescriber signing delegations.

    Accessible from the app drawer. Opens a window to configure
    which staff members can sign prescriptions for which providers.
    """

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/dea_prescriber_filter/app/delegation-admin?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Prescriber Assist",
        ).apply()
