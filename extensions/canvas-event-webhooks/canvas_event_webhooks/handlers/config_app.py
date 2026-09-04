"""Global Canvas application that opens the webhook configuration UI."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

CONFIG_PATH = "/plugin-io/api/canvas_event_webhooks/config/"


class WebhookConfigApplication(Application):
    """Opens the webhook configuration page in a Canvas modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=CONFIG_PATH,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Canvas Event Webhooks",
        ).apply()
