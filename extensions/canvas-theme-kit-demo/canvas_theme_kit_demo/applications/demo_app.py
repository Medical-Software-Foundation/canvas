"""Provider-menu entry point for the demo page."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Same-origin, so no url_permissions entry is needed in the manifest.
DEMO_URL = "/plugin-io/api/canvas_theme_kit_demo/demo/page"


class ThemeKitDemoApp(Application):
    """Opens the token-styled demo page."""

    def on_open(self) -> Effect:
        """Iframe the page rather than inlining its HTML.

        The point of this demo is that the page arrives from the server with its
        token block already in `<head>`. Rendering the markup into a modal here
        would bypass the very request path being demonstrated.
        """
        return LaunchModalEffect(
            url=DEMO_URL,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Theme Kit Demo",
        ).apply()
