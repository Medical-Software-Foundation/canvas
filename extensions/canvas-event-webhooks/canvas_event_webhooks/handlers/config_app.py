"""Global Canvas application that opens the webhook configuration UI."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

CONFIG_PATH = "/plugin-io/api/canvas_event_webhooks/config/"

# Refreshed on every plugin restart/deploy so the modal's HTML/JS response
# isn't served stale from a browser cache after an install.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class WebhookConfigApplication(Application):
    """Opens the webhook configuration page in a Canvas modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"{CONFIG_PATH}?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Canvas Event Webhooks",
        ).apply()
