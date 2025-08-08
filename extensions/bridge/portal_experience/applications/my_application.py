from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class MyApplication(Application):
    """An embeddable application that can be registered to Canvas."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        # Implement this method to handle the application on_open event.
        # You can look up data here to be used in knowing what to launch, if
        # what you're launching depends on some dynamic criteria.

        return LaunchModalEffect(
            # This URL is what will get iframed. It can be hosted elsewhere,
            # or it could be hosted by your plugin! Canvas plugins can serve
            # html, css, js, or json.
            #
            # If embedding a remote URL, be sure to declare it in the URL
            # permissions section of your plugin's CANVAS_MANIFEST.json
            url="/plugin-io/api/bridge/app/bridge-eligibility",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
