"""Configuration application for lab order favorites.

A provider-menu item (global, non-patient context) that opens the favorites
configuration page in a new browser tab. The page itself is served by
`ConfigPageAPI`; this handler just launches it. Lets staff create, edit, and
delete favorites, mark them personal or shared, manage tags, set a default
ordering provider, and bulk upload favorites from a CSV.
"""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

CONFIG_PAGE_URL = "/plugin-io/api/lab_order_favorites/app/config"
# Stamped at install/load time so a reinstalled version busts the browser cache
# of the served config page when it opens in a new tab.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class LabFavoritesConfigApp(Application):
    """Provider-menu application for managing lab order favorites."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"{CONFIG_PAGE_URL}?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.NEW_WINDOW,
            title="Lab Favorites - Configuration",
        ).apply()
